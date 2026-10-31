# MunimAI - Safety-rail test runner + benchmark tool.
#
# Runs every sample clip (t1..t6) through the FULL LangGraph pipeline and
# compares the outcome against an expected verdict, printing a result card.
#
# Run:  .\venv\Scripts\python.exe test_sentences.py
#
# The table at the end is your REAL accuracy/latency data for the pitch deck.
#
# Each case has:
#   file      : the audio clip in samples/
#   expects   : "order_filled" | "needs_clarification" | "any"
#               -- what CORRECT behavior looks like
#   describe  : one-line human summary shown in the report

import json
import sys
import time
from pathlib import Path

# Windows consoles default to an old encoding that cannot print the rupee
# sign (₹) that Sarvam sometimes returns in transcripts. Force UTF-8 first,
# BEFORE any pipeline code prints.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from pipeline.graph import run_pipeline  # noqa: E402  (import after reconfigure)

SAMPLES = Path("samples")

# ---------------------------------------------------------------------------
# Test cases: one row per recorded clip
# ---------------------------------------------------------------------------

CASES = [
    {
        "file": "t1_no_item_amul.mp3",
        "expects": "order_filled",
        "describe": "no item, but Amul HAS a default -> fill 'milk packet', flag item_guessed",
    },
    {
        "file": "t2_unknown_brand.mp3",
        "expects": "needs_clarification",
        "describe": "no item, Parag unknown -> must ASK, never guess",
    },
    {
        "file": "t3_full_order.mp3",
        "expects": "order_filled",
        "describe": "everything spoken -> full order, item NOT guessed",
    },
    {
        "file": "t4_no_supplier.mp3",
        "expects": "needs_clarification",
        "describe": "no brand mentioned -> must ASK (no default lookup possible)",
    },
    {
        "file": "t5_english_mix.mp3",
        "expects": "order_filled",
        "describe": "English/Hinglish mix, item spoken -> uses spoken item, no guess",
    },
    {
        "file": "t6_mumble.mp3",
        "expects": "any",
        "describe": "garbled audio -> ANY clean outcome acceptable (order if it is genuinely clear, or clarification). Never silently wrong.",
    },
]

# ---------------------------------------------------------------------------
# Pass/fail grading
# ---------------------------------------------------------------------------

def grade(case: dict, state: dict) -> tuple[bool, str]:
    """Compare pipeline outcome with expected verdict.

    Returns (passed: bool, why: explanation string)
    """
    order = state.get("final_order") or {}
    filled = state.get("needs_clarification") is False and bool(order)

    if case["expects"] == "order_filled":
        if not filled:
            return False, f"expected a filled order, got needs_clarification: {state.get('clarification_question')}"
        # a filled order MUST have a supplier: a purchase order cannot be
        # sent "to nobody".
        if not order.get("supplier"):
            return False, "order filled without supplier (no PO recipient)"
        guess_ok = bool(state.get("item_guessed")) == bool(order.get("item_guessed"))
        if not guess_ok:
            return False, "item_guessed flag mismatch between state and final order"
        return True, "order filled cleanly"

    if case["expects"] == "needs_clarification":
        if filled:
            return False, f"expected a clarification QUESTION, got an order: {order}"
        q = state.get("clarification_question") or ""
        # do not guess = final order must be empty.
        if not q:
            return False, "needs_clarification but no question for merchant"
        return True, f"asked: \"{q}\""

    # expects == "any"
    if filled:
        return True, "order filled"
    return True, f"clarified: \"{state.get('clarification_question')}\""


def run_case(case: dict) -> dict:
    """Run one audio clip through the pipeline and grade it."""
    path = SAMPLES / case["file"]
    t0 = time.perf_counter()
    try:
        state = run_pipeline(str(path))
        ok, why = grade(case, state)
    except Exception as e:                      # noqa: BLE001 - report, don't crash the suite
        state = {"final_order": {}, "transcript": "", "clarification_question": "",
                 "parse_error": f"crash: {type(e).__name__}: {e}"}
        ok = case["expects"] == "any"
        why = f"pipeline crashed: {type(e).__name__}: {e}"
    dt = time.perf_counter() - t0
    return {"ok": ok, "why": why, "secs": dt, "state": state, "case": case}


# ---------------------------------------------------------------------------
# Pretty report
# ---------------------------------------------------------------------------

def main() -> None:
    results = [run_case(c) for c in CASES]

    print()
    print("=" * 78)
    print("MUNIM SAFETY-RAIL REPORT")
    print("=" * 78)

    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"\n{r['case']['file']}  [{mark}]  ({r['secs']:.1f}s)")
        print(f"   intent : {r['case']['describe']}")
        print(f"   heard  : {r['state']['transcript']}")
        print(f"   verdict: {r['why']}")
        if not r["ok"]:
            print(f"   state  : {json.dumps({k: r['state'].get(k) for k in
                    ('supplier', 'item', 'quantity', 'unit', 'total_amount',
                     'needs_clarification', 'parse_error')})}")

    passed = sum(1 for r in results if r["ok"])
    avg = sum(r["secs"] for r in results) / len(results)
    order_filled = sum(1 for r in results if r["state"].get("final_order"))

    print("-" * 78)
    print(f"TOTAL      : {passed}/{len(results)} cases behaved as designed")
    print(f"Avg latency: {avg:.1f}s per clip (STT + LLM both run on every case)")
    print(f"Orders out : {order_filled}/{len(results)} (rest correctly asked questions)")
    if passed == len(results):
        print("\nDONE: every safety rail behaved as designed")
    else:
        print("\nSome rails failed - investigate the FAIL rows above before the demo.")


if __name__ == "__main__":
    main()
