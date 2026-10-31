"""Sarvam speech-to-text (same call as test_stt.py, but takes bytes)."""
import logging
import time
from dataclasses import dataclass

from . import config


class STTError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    language: str | None
    latency_ms: int


log = logging.getLogger("munimai.stt")
_client = None


def _get_client():
    global _client
    if _client is None:
        from sarvamai import SarvamAI
        if not config.SARVAM_API_KEY:
            raise STTError("SARVAM_API_KEY is not set")
        _client = SarvamAI(api_subscription_key=config.SARVAM_API_KEY)
    return _client


def transcribe(audio: bytes, filename: str = "audio.webm", content_type: str = "audio/webm") -> Transcript:
    content_type = content_type.split(";")[0]
    log.info("STT input: %s, %s, %d bytes", filename, content_type, len(audio))
    t0 = time.perf_counter()
    try:
        resp = _get_client().speech_to_text.transcribe(
            file=(filename, audio, content_type),
            model=config.STT_MODEL,
            mode=config.STT_MODE,
        )
    except STTError:
        raise
    except Exception as e:  # network, auth, bad audio...
        raise STTError(f"Sarvam STT failed: {e}") from e
    text = (getattr(resp, "transcript", None) or "").strip()
    if not text:
        raise STTError("Empty transcript")
    log.info("STT heard: %r (lang=%s)", text, getattr(resp, "language_code", None))
    return Transcript(
        text=text,
        language=getattr(resp, "language_code", None),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
