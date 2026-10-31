# MunimAI - Step 1 test: speech -> ENGLISH text
#
# What this does:
#   Takes our recorded Hindi audio clip and asks Sarvam's Saaras speech-to-text
#   model to TRANSLATE it to English (mode="translate").
#   Same endpoint as test_stt.py, just a different mode.
#
# Expected flow:
#   samples/amul1.mp3  ("Amul ke 50 packet, 1500 ka bill")
#       -> English text like "50 packets of Amul, a bill of 1500"
#
# Docs (verified Oct 2026): https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/rest-api

# dotenv reads the .env file in this folder and puts SARVAM_API_KEY into
# environment variables, so the key never appears in our code.
from dotenv import load_dotenv
import os

# The official Sarvam Python SDK. The response object throws ApiError when
# something goes wrong (bad key, bad audio, rate limit...).
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

# --- Load our secret key from .env into os.environ -------------------------
load_dotenv()

try:
    api_key = os.environ["SARVAM_API_KEY"]
except KeyError:
    # Missing key: fail with a clear, non-technical message.
    raise SystemExit(
        "ERROR: SARVAM_API_KEY not found in .env.\n"
        "Make sure a file named .env exists in this folder with a line like:\n"
        "  SARVAM_API_KEY=your_real_key_here"
    )

# One shared client object = one place we send our key to Sarvam.
client = SarvamAI(api_subscription_key=api_key)

# --- Open the audio file and send it ----------------------------------------
# The file is opened in binary mode ("rb"), then handed straight to the API.
# We use "with" so the file is always closed afterwards, even on errors.
with open("samples/amul1.mp3", "rb") as f:
    try:
        resp = client.speech_to_text.transcribe(
            file=f,
            model="saaras:v3",   # v4 is also available; same call shape
            mode="translate",    # <-- the only real change vs test_stt.py
        )
    except ApiError as e:
        # Friendly messages for the most common failure cases,
        # based on Sarvam's error-code table.
        if e.status_code == 403:
            print("ERROR 403: API key was rejected.")
            print("  -> Check that the key in .env is current and active.")
        elif e.status_code == 422:
            print("ERROR 422: The audio file was rejected.")
            print("  -> Is the file missing, empty, or longer than 30 seconds?")
        elif e.status_code == 429:
            print("ERROR 429: Too many requests in a short time.")
            print("  -> Wait a few seconds and run this again.")
        elif e.status_code == 503:
            print("ERROR 503: Sarvam's service is overloaded.")
            print("  -> Wait a bit and retry.")
        else:
            print(f"ERROR {e.status_code}: {e.body}")
        raise SystemExit(1)  # nonzero exit code = this test failed

# --- Show the result ---------------------------------------------------------
# resp is an object with .transcript (the English text) and .language_code
# (the language detected in the audio, e.g. "hi-IN" for Hindi).
print("Detected source language :", resp.language_code)
print("Translated English text  :", resp.transcript)
