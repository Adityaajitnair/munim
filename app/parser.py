"""Sarvam chat model helpers:
  parse_order(text)        shopkeeper's sentence -> ParsedOrder
  parse_reply(text, order) shopkeeper's reply to the read-back -> ParsedReply
Both validate the LLM's JSON strictly with Pydantic."""
import json
import logging
import re

import requests

from . import config
from .schemas import ParsedOrder, ParsedReply

log = logging.getLogger("munimai.parser")

ORDER_PROMPT = """You extract shop orders from a shopkeeper's sentence (Hindi/Hinglish).
Reply with ONLY a JSON object with these keys:
intent (LOG_PURCHASE_ORDER or OTHER), supplier, item, quantity (number), unit (e.g. packet, kg, or null), total_amount (number).
Use null for anything not mentioned. Write supplier and item in English letters.
Sentence: """

REPLY_PROMPT = """A shopkeeper was just read back a purchase order and is now replying in Hindi/Hinglish.
Current order: supplier={supplier}, item={item}, quantity={quantity} {unit}, total=Rs {total}.
Reply with ONLY a JSON object with these keys:
decision, supplier, item, quantity (number), unit, total_amount (number).
decision is one of:
- CONFIRM: the shopkeeper agrees and wants the order sent as it is.
- REJECT: the shopkeeper cancels the order.
- MODIFY: the shopkeeper wants to change something. Fill ONLY the fields they changed, use null for the rest.
- UNCLEAR: anything else, or you are not sure.
If the reply both agrees and changes something, use MODIFY. Write supplier and item in English letters.
Shopkeeper's reply: """


class LLMError(Exception):
    """Upstream LLM unreachable or returned an error status (-> HTTP 502)."""


class ParseError(Exception):
    """LLM replied but not with valid JSON (-> HTTP 422)."""


def _extract_json(content: str) -> dict:
    content = content.replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise ParseError("No JSON object in LLM reply")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON from LLM: {e}") from e


def _call_llm(prompt: str, retries: int = 1) -> dict:
    if not config.SARVAM_API_KEY:
        raise LLMError("SARVAM_API_KEY is not set")
    finish = None
    for _ in range(retries + 1):
        try:
            r = requests.post(
                "https://api.sarvam.ai/v1/chat/completions",
                headers={"api-subscription-key": config.SARVAM_API_KEY},
                json={"model": config.LLM_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 2000},
                timeout=30,
            )
        except requests.RequestException as e:
            raise LLMError(f"LLM request failed: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"LLM returned {r.status_code}: {r.text[:200]}")
        try:
            choice = r.json()["choices"][0]
        except (KeyError, IndexError, ValueError) as e:
            raise ParseError("Unexpected LLM response shape") from e
        content = (choice.get("message") or {}).get("content")
        finish = choice.get("finish_reason")
        log.info("LLM finish_reason=%s raw reply: %r", finish, content)
        if isinstance(content, str) and content.strip():
            return _extract_json(content)
    raise ParseError(f"LLM returned empty content (finish_reason={finish})")

def parse_order(text: str) -> ParsedOrder:
    data = _call_llm(ORDER_PROMPT + text)
    try:
        return ParsedOrder.model_validate(data)
    except Exception as e:  # pydantic ValidationError
        raise ParseError(f"Order failed validation: {e}") from e


def parse_reply(text: str, order: dict) -> ParsedReply:
    """order: dict with supplier, item, quantity, unit, total (current pending order)."""
    prompt = REPLY_PROMPT.format(
        supplier=order.get("supplier"), item=order.get("item"),
        quantity=order.get("quantity"), unit=order.get("unit") or "",
        total=order.get("total"),
    ) + text
    data = _call_llm(prompt)
    try:
        return ParsedReply.model_validate(data)
    except Exception as e:
        raise ParseError(f"Reply failed validation: {e}") from e
