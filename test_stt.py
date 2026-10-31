from dotenv import load_dotenv
import os
from sarvamai import SarvamAI

load_dotenv()
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

with open("samples/amul1.mp3", "rb") as f:
    resp = client.speech_to_text.transcribe(
        file=f,
        model="saaras:v3",
        mode="codemix",
    )
print(resp)
