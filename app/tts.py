"""Sarvam text-to-speech via the REST API (avoids SDK version differences).
Check Sarvam's docs for current model/speaker names and set TTS_MODEL / TTS_SPEAKER."""
import base64

import requests

from . import config


class TTSError(Exception):
    pass


def synthesize(text: str, language: str = "hi-IN") -> bytes:
    if not config.SARVAM_API_KEY:
        raise TTSError("SARVAM_API_KEY is not set")
    try:
        r = requests.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": config.SARVAM_API_KEY},
            json={
                "text": text,
                "target_language_code": language,
                "model": config.TTS_MODEL,
                "speaker": config.TTS_SPEAKER,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise TTSError(f"Sarvam TTS request failed: {e}") from e
    if r.status_code != 200:
        raise TTSError(f"Sarvam TTS returned {r.status_code}: {r.text[:300]}")
    try:
        return base64.b64decode("".join(r.json()["audios"]))
    except (KeyError, ValueError, TypeError) as e:
        raise TTSError(f"Unexpected Sarvam TTS response: {r.text[:200]}") from e
