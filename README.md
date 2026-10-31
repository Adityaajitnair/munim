# MunimAI

Voice-first ordering assistant: a merchant speaks in Hindi/Hinglish → speech-to-text → structured order JSON → confirmation → WhatsApp purchase order + ledger.

## Current status

Early prototype ("walking skeleton") tests:

- `test_stt.py` — sends `samples/amul1.mp3` to Sarvam AI speech-to-text (`saaras:v3`, codemix mode)
- `test_parse.py` — parses transcript into a structured order
- `test_env.py` — sanity-checks the environment / API key

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt   # or install deps manually (requests, python-dotenv, sarvamai, websockets)
copy .env.example .env            # then put your real SARVAM_API_KEY in .env
python test_stt.py
```

## Notes

- `munim.txt` contains the build plan / roadmap.
- `.env` is git-ignored and never committed — only `.env.example` is tracked.
