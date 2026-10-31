"""Settings read from environment variables (.env is loaded if present)."""
import os

from dotenv import load_dotenv

load_dotenv()
WHATSAPP_WEBHOOK_URL = os.getenv("WHATSAPP_WEBHOOK_URL", "http://localhost:8000/mock-whatsapp/webhook")
# Used by the mock to call back /orders/{id}/executed
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
STT_MODEL = os.getenv("STT_MODEL", "saaras:v3")
STT_MODE = os.getenv("STT_MODE", "codemix")
LLM_MODEL = os.getenv("LLM_MODEL", "sarvam-105b")
TTS_MODEL = os.getenv("TTS_MODEL", "bulbul:v3")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "shubh")
REORDER_THRESHOLD = float(os.getenv("REORDER_THRESHOLD", "15"))
# True: low stock auto-confirms and sends the PO. False: PO waits for the merchant's "haan".
AUTO_CONFIRM_REORDER = os.getenv("AUTO_CONFIRM_REORDER", "true").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./munimai.db")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_CALLBACK_SECRET = os.getenv("N8N_CALLBACK_SECRET", "change-me")
MAX_UPLOAD_BYTES = int(float(os.getenv("MAX_UPLOAD_MB", "5")) * 1024 * 1024)

# Supplier matching thresholds (see spec section 8)
MATCH_ACCEPT = 0.8
MATCH_REJECT = 0.5
