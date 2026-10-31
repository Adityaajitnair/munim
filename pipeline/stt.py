"""
pipeline/stt.py - Speech-to-Text helper for MunimAI.

One job: give it an audio file path, get back the ENGLISH transcript.

    samples/amul1.mp3 ("Amul ke 50 packet, 1500 ka bill")
        -> "Amul's fifty packets, bill of one thousand five hundred."

Used by the LangGraph pipeline (pipeline/graph.py) as the "transcribe node".

Docs (verified Oct 2026):
    https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/rest-api
"""

import os

from dotenv import load_dotenv
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

# Read .env (SARVAM_API_KEY) into environment variables once, when this
# module is first imported. The key itself never gets printed anywhere.
load_dotenv()

# Cache for the one shared client object, so we don't rebuild it on every
# transcription (tiny speed win, and one clear place to fix key problems).
_client: SarvamAI | None = None


def get_client() -> SarvamAI:
    """Return a SarvamAI client built from the key in .env (created lazily)."""
    global _client
    if _client is None:
        try:
            key = os.environ["SARVAM_API_KEY"]
        except KeyError:
            raise SystemExit(
                "ERROR: SARVAM_API_KEY not found in .env.\n"
                "Create a file named .env in the project folder containing:\n"
                "  SARVAM_API_KEY=your_real_key_here"
            )
        _client = SarvamAI(api_subscription_key=key)
    return _client


def transcribe_to_english(audio_path: str, model: str = "saaras:v3") -> str:
    """
    Send an audio file to Sarvam and return the transcript in English.

    Raises a RuntimeError with a plain-language message if anything fails,
    so the caller (LangGraph node) can show it to the developer/user.
    """
    # The file must be opened in binary mode and passed as an object,
    # not as a path string (Sarvam docs: "Pass a file object, not a path").
    try:
        audio_file = open(audio_path, "rb")
    except FileNotFoundError:
        raise RuntimeError(f"Audio file not found: '{audio_path}'")

    try:
        response = get_client().speech_to_text.transcribe(
            file=audio_file,
            model=model,
            mode="translate",  # Hindi (or any of 22 languages) -> English
        )
    except ApiError as e:
        # Translate the raw HTTP error into something a human understands.
        if e.status_code == 403:
            raise RuntimeError(
                "API key was rejected (403). Check that the key in .env "
                "is current and active."
            )
        elif e.status_code == 422:
            raise RuntimeError(
                f"Sarvam rejected the audio in '{audio_path}' (422). "
                "Is it empty, corrupt, or longer than 30 seconds?"
            )
        elif e.status_code == 429:
            raise RuntimeError("Sarvam rate limit hit (429). Wait a few seconds and retry.")
        elif e.status_code == 503:
            raise RuntimeError("Sarvam service overloaded (503). Try again shortly.")
        else:
            raise RuntimeError(f"Sarvam error {e.status_code}: {e.body}")
    finally:
        # always close the file, success or error
        audio_file.close()

    return response.transcript
