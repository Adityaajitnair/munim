"""
pipeline/graph.py - The LangGraph "brain" of MunimAI.

Builds a small flowchart of the order pipeline:

        START
          |
      transcribe     (audio -> English text, Sarvam Saaras)
          |
        map          (LLM -> supplier/item/quantity/unit/total JSON)
          |   ^-------- retry on parse failure, max 2 attempts --^
          |
       complete     (fill missing item from supplier lookup table,
          |          or flag "needs_clarification" if we can't)
         END

Safety rule (from the project plan):
    NEVER invent an item. If the merchant didn't say one and we have no
    default for that supplier, we ask: needs_clarification = True.

Docs (verified Oct 2026):
    LangGraph:  https://langchain-ai.github.io/langgraph/
    Sarvam chat + strict JSON:  https://docs.sarvam.ai/api/token-factory/chat-completions
"""

from __future__ import annotations

import json
from typing import Optional, TypedDict

from pydantic import BaseModel, ValidationError

from pipeline.stt import get_client, transcribe_to_english

# ---------------------------------------------------------------------------
# Configuration constants (small, visible, easy to explain in a hackathon)
# ---------------------------------------------------------------------------

CHAT_MODEL = "sarvam-105b"   # Sarvam's flagship LLM (verified in docs Oct 2026)
MAX_PARSE_RETRIES = 2        # graph plan: retry the map step up to 2 times

# Small lookup table: if the supplier is known but the item wasn't spoken,
# we MAY silently fill this in - and only from this table.
DEFAULT_ITEMS = {
    "amul": "milk packet",
    "parle-g": "biscuit carton",
    "britannia": "bread loaf",
}

# ---------------------------------------------------------------------------
# Structured-order schema (what the LLM must return)
# ---------------------------------------------------------------------------

# Pydantic model = our own validation. Even though Sarvam's strict JSON mode
# guarantees the SHAPE, we still validate values ourselves (docs recommend it).
class RawOrder(BaseModel):
    """The order fields we want out of the spoken sentence."""

    supplier: Optional[str]      # company/brand, e.g. "Amul"
    item: Optional[str]          # thing ordered, e.g. "milk packet"
    quantity: Optional[float]    # how many, as a NUMBER (1500, not "one thousand five hundred")
    unit: Optional[str]          # packet / carton / kg ...
    total_amount: Optional[float]  # rupees, as a NUMBER


# JSON Schema sent to Sarvam's strict structured-output mode. All fields are
# required (but may be null) - that's what "strict": True needs, and it forces
# the model to think about every field before answering.
ORDER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier": {"type": ["string", "null"], "description": "Company or brand name, e.g. Amul"},
        "item": {"type": ["string", "null"], "description": "The product ordered, e.g. milk packet"},
        "quantity": {"type": ["number", "null"], "description": "How many, as digits"},
        "unit": {"type": ["string", "null"], "description": "packet / carton / kg / piece"},
        "total_amount": {"type": ["number", "null"], "description": "Bill amount in rupees, as digits"},
    },
    "required": ["supplier", "item", "quantity", "unit", "total_amount"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# The graph state - data that flows through all nodes
# ---------------------------------------------------------------------------

class OrderState(TypedDict):
    """Shared 'clip-board' the nodes pass around. Each node reads/edits it."""

    # -- things we fill in as we go
    audio_path: str                  # input: which audio clip to process
    transcript: str                  # English text from Sarvam STT
    supplier: Optional[str]
    item: Optional[str]
    quantity: Optional[float]
    unit: Optional[str]
    total_amount: Optional[float]
    item_guessed: bool               # True if item was filled from lookup table
    needs_clarification: bool        # True = we must ask the merchant a question
    clarification_question: str
    parse_ok: bool                   # did the LLM give us a valid order?
    parse_attempts: int              # how many times the map step tried
    parse_error: str
    final_order: dict                # the finished, ready-to-send order


# ---------------------------------------------------------------------------
# Prompt: tell the LLM exactly how to convert speech -> structured order
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You convert spoken shop orders into structured JSON. "
    "A brand/company name (amul, parag, parle-g, britannia...) is the SUPPLIER, "
    "never the ITEM. The item is the product (milk, biscuit, bread, sugar...)."
)

USER_PROMPT_TEMPLATE = """A shopkeeper (kirana merchant) ordered supplies out loud.
Below is the English translation of what they said.

SPEECH: "{transcript}"

Rules:
- Convert spoken number words ("one thousand five hundred") into digits (1500).
- supplier = ONLY the brand/company that was spoken (Amul, Parag, Parle-G...). null if none was spoken.
- item = the product bought (milk, biscuit, bread...). null if no product was spoken, even when a brand was.
- Use null for any field the speaker did not clearly say.
- DO NOT guess or invent items. If the item wasn't spoken, use null.
- Reply with the JSON object only."""

# ---------------------------------------------------------------------------
# The node functions - each node = one box of the flowchart
# ---------------------------------------------------------------------------

def transcribe_node(state: OrderState) -> dict:
    """Box 1: audio file -> English transcript (Sarvam speech-to-text)."""
    print(f"[transcribe] sending '{state['audio_path']}' to Sarvam...")
    transcript = transcribe_to_english(state["audio_path"])
    print(f"[transcribe] transcript: {transcript}")
    return {"transcript": transcript}


def map_node(state: OrderState) -> dict:
    """Box 2: English transcript -> structured order fields (LLM)."""
    transcript = state["transcript"]
    attempts = state.get("parse_attempts", 0) + 1
    print(f"[map] asking {CHAT_MODEL} (attempt {attempts}/{MAX_PARSE_RETRIES + 1})...")

    try:
        response = get_client().chat.completions(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(transcript=transcript)},
            ],
            # STRICT structured output: the API enforces our JSON Schema.
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "shop_order",
                    "strict": True,
                    "schema": ORDER_JSON_SCHEMA,
                },
            },
            reasoning_effort=None,   # skip 'thinking' tokens -> faster, cheaper
            temperature=0.2,         # low randomness: parsing should be deterministic
            max_tokens=512,
        )

        # With json_schema mode the reply arrives as a JSON *string*.
        raw = response.choices[0].message.content
        data = json.loads(raw)

        # Normalize "ghost nulls": models sometimes write the WORD "null" /
        # "none" / "" instead of a real JSON null. Turn those into None so
        # downstream code treats them as genuinely missing.
        data = {
            k: (None if isinstance(v, str) and v.strip().lower() in {"null", "none", ""}
                else v)
            for k, v in data.items()
        }

        order = RawOrder.model_validate(data)   # Pydantic validation, just in case

        print(f"[map] parsed: {order.model_dump()}")
        return {
            "supplier": order.supplier,
            "item": order.item,
            "quantity": order.quantity,
            "unit": order.unit,
            "total_amount": order.total_amount,
            "parse_ok": True,
            "parse_attempts": attempts,
            "parse_error": "",
        }

    except (json.JSONDecodeError, ValidationError) as e:
        # The model returned something we couldn't use -> retry pass decides.
        print(f"[map] parse failed: {type(e).__name__}")
        return {
            "parse_ok": False,
            "parse_attempts": attempts,
            "parse_error": f"LLM output could not be parsed: {type(e).__name__}",
        }


def complete_node(state: OrderState) -> dict:
    """Box 3: apply safety rules and build the final order dict.

    - Missing item + supplier has a default  -> fill it, flag item_guessed.
    - Missing item + no default              -> needs_clarification (NEVER guess).
    """
    supplier = state.get("supplier")
    item = state.get("item")

    # Case 1: parsing totally failed even after retries -> tell the app to ask.
    if not state.get("parse_ok"):
        return {
            "needs_clarification": True,
            "clarification_question": "Couldn't understand the order, please repeat or type it.",
            "final_order": {},
        }

    # Case 2: item missing but supplier is a known brand with a default.
    if item is None and supplier and supplier.lower() in DEFAULT_ITEMS:
        item = DEFAULT_ITEMS[supplier.lower()]
        print(f"[complete] item missing -> using default for {supplier}: '{item}'")
        return {
            "item": item,
            "item_guessed": True,
            "needs_clarification": False,
            "final_order": {
                "supplier": supplier,
                "item": item,
                "quantity": state.get("quantity"),
                "unit": state.get("unit"),
                "total_amount": state.get("total_amount"),
                "item_guessed": True,
            },
        }

    # Case 3: item still missing and no default -> ASK, don't guess.
    if item is None:
        question = (
            f"Order from {supplier} noted. What item?" if supplier
            else "What item (and supplier) did you order?"
        )
        print(f"[complete] no item and no default -> needs_clarification")
        return {
            "needs_clarification": True,
            "clarification_question": question,
            "item_guessed": False,
            "final_order": {},
        }

    # Case 3b: item known but supplier missing. A purchase order must go
    # to SOME distributor, so we ask instead of shipping it "to nobody".
    if supplier is None:
        print(f"[complete] no supplier for a known item -> needs_clarification")
        return {
            "needs_clarification": True,
            "clarification_question": (
                f"{item} noted. Which supplier (distributor) is this for?"
            ),
            "item_guessed": False,
            "final_order": {},
        }

    # Case 4: everything is present -> clean final order.
    return {
        "item_guessed": False,
        "needs_clarification": False,
        "final_order": {
            "supplier": supplier,
            "item": item,
            "quantity": state.get("quantity"),
            "unit": state.get("unit"),
            "total_amount": state.get("total_amount"),
            "item_guessed": False,
        },
    }


# ---------------------------------------------------------------------------
# Wire the boxes together into a graph
# ---------------------------------------------------------------------------

def build_graph():
    """Build and compile the MunimAI pipeline graph."""
    from langgraph.graph import START, END, StateGraph

    builder = StateGraph(OrderState)

    builder.add_node("transcribe", transcribe_node)
    builder.add_node("map", map_node)
    builder.add_node("complete", complete_node)

    builder.add_edge(START, "transcribe")
    builder.add_edge("transcribe", "map")

    # Router after the map node:
    #   - retry "map" if parsing failed and retries remain
    #   - else go on to "complete" (which always produces a final decision)
    def route_after_map(state: OrderState) -> str:
        if not state.get("parse_ok") and state.get("parse_attempts", 0) < MAX_PARSE_RETRIES + 1:
            return "retry"
        return "next"

    builder.add_conditional_edges("map", route_after_map, {
        "retry": "map",
        "next": "complete",
    })

    builder.add_edge("complete", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Convenience: run the whole pipeline on one audio file
# ---------------------------------------------------------------------------

def run_pipeline(audio_path: str) -> OrderState:
    """Full pipeline for one spoken order. Returns the final graph state."""
    graph = build_graph()
    final_state = graph.invoke({"audio_path": audio_path})
    return final_state
