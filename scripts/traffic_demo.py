# MunimAI - traffic demo: fires a few representative API calls at the
# ledger so the /dashboard "Live API calls" panel has something to show.
#
# Run while the server is up:  .\venv\Scripts\python.exe scripts\traffic_demo.py

import requests

BASE = "http://127.0.0.1:8000"

print("POST good order  ->",
      requests.post(f"{BASE}/orders", json={
          "supplier": "amul", "item": "milk packet", "quantity": 25,
          "unit": "packets", "total_amount": 1000, "item_guessed": True,
      }, timeout=5).status_code)

print("POST invalid     ->",
      requests.post(f"{BASE}/orders", json={
          "supplier": "amul", "quantity": -5,   # missing 'item', negative qty
      }, timeout=5).status_code, "(422 = Pydantic validation rejected it)")

print("GET unknown id   ->",
      requests.get(f"{BASE}/orders/zzzz", timeout=5).status_code)

print("GET home         ->", requests.get(f"{BASE}/", timeout=5).status_code)

print()
print("--- /calls panel content (what the dashboard shows) ---")
for c in requests.get(f"{BASE}/calls", timeout=5).json():
    print(f"  {c['status']}  {c['method']:4} {c['path']:<18} {c['ms']}ms")
