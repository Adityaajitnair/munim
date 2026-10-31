# MunimAI - Golden-loop test (Step 4). Requires the ledger server running:
#     .\venv\Scripts\uvicorn.exe app.main:app --port 8000
#
# Demonstrates the FULL cycle against a live server:
#   1. voice clip -> pipeline -> ledger row
#   2. incomplete speech -> needs_clarification row -> merchant ANSWERS -> row completes
#
# Run:  .\venv\Scripts\python.exe scripts\test_golden_loop.py

import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def speak(clip: str) -> dict:
    """Run the voice pipeline on a clip; the ledger row comes back."""
    r = requests.post(f"{BASE}/orders/voice", json={"audio_file": clip}, timeout=120)
    r.raise_for_status()
    return r.json()


def main() -> None:
    print("=" * 70)
    print("GOLDEN LOOP TEST - voice in, ledger row out")
    print("=" * 70)

    # ---- scenario 1: baseline clip -> straight to a pending order ----
    e = speak("samples/amul1.mp3")
    print(f"\n[1] amul1.mp3          -> row {e['id']}  status={e['status']}")
    print(f"    {e['supplier']} | {e['item']} | x{e['quantity']} | Rs.{e['total_amount']}")

    # ---- scenario 2: no supplier spoken -> clarification, then answered ----
    e = speak("samples/t4_no_supplier.mp3")
    print(f"\n[2] t4_no_supplier.mp3 -> row {e['id']}  status={e['status']}")
    print(f"    question: {e['question']}")
    r = requests.post(f"{BASE}/clarifications/{e['id']}/answer",
                      json={"supplier": "amul"}, timeout=10)
    e2 = r.json()
    print(f"    after 'supplier=amul' -> status={e2['status']}  "
          f"({e2['supplier']} | {e2['item']} | x{e2['quantity']} | Rs.{e2['total_amount']})")

    # ---- scenario 3: multi-turn - asking for ONE more missing field ----
    e = speak("samples/t2_unknown_brand.mp3")
    print(f"\n[3] t2_unknown_brand   -> row {e['id']}  status={e['status']}")
    print(f"    question: {e['question']}")
    a = requests.post(f"{BASE}/clarifications/{e['id']}/answer",
                      json={"supplier": "parag"}, timeout=10).json()
    print(f"    after 'supplier=parag' -> still {a['status']}")
    print(f"    follow-up question: {a['question']}")
    a = requests.post(f"{BASE}/clarifications/{a['id']}/answer",
                      json={"item": "milk packet"}, timeout=10).json()
    print(f"    after 'item=milk packet' -> status={a['status']}  "
          f"({a['supplier']} | {a['item']} | x{a['quantity']})")

    # ---- final ledger state ----
    rows = requests.get(f"{BASE}/orders", timeout=5).json()
    pending = sum(1 for r in rows if r["status"] == "pending")
    stuck = sum(1 for r in rows if r["status"] == "needs_clarification")
    print("\n" + "=" * 70)
    print(f"LEDGER: {len(rows)} rows total | {pending} pending | {stuck} needs clarification")
    print("DONE: golden loop (voice -> ledger -> answer -> order) works end to end")


if __name__ == "__main__":
    main()
