from dotenv import load_dotenv
import os, json, requests

load_dotenv()

PROMPT = """You extract shop orders from a shopkeeper's sentence (Hindi/Hinglish).
Reply with ONLY a JSON object with these keys:
intent (LOG_PURCHASE_ORDER or OTHER), supplier, item, quantity (number), total_amount (number).
Sentence: """

def parse_order(text):
    r = requests.post(
        "https://api.sarvam.ai/v1/chat/completions",
        headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
        json={
            "model": "sarvam-105b",
            "messages": [{"role": "user", "content": PROMPT + text}],
        },
    )
    print(r.status_code)          # 200 means success
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)

if __name__ == "__main__":
    text = "अमूल के 50 पैकेट 1500 का बिल"
    print(parse_order(text))