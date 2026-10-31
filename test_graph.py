# MunimAI - Step 2 test: run the LangGraph pipeline end to end.
#
#   audio file -> [transcribe] -> [map LLM] -> [complete] -> final order JSON
#
# Run:  .\venv\Scripts\python.exe test_graph.py
#
# Prints the full final order at the end. Total Sarvam calls: 1 STT + 1 chat
# (plus a retry of the chat step only if the LLM output couldn't be parsed).

import json

from pipeline.graph import run_pipeline


def show_order(state) -> None:
    """Pretty-print what the pipeline decided, with plain-language labels."""
    print()
    print("=" * 60)
    print("PIPELINE RESULT")
    print("=" * 60)
    print(f"English transcript   : {state['transcript']}")
    print()

    order = state["final_order"]
    if not order:
        # Nothing executed - we need to ask the merchant a question.
        print("STATUS               : needs_clarification")
        print(f"Question for merchant: {state['clarification_question']}")
        if state.get("parse_error"):
            print(f"Cause                : {state['parse_error']}")
        return

    print("STATUS               : ready_to_confirm")
    print(f"Supplier             : {order['supplier']}")
    print(f"Item                 : {order['item']}"
          + ("   (guessed from lookup table!)" if order["item_guessed"] else ""))
    print(f"Quantity             : {order['quantity']} {order['unit'] or ''}")
    print(f"Total                : Rs. {order['total_amount']}")
    print()
    print("Full JSON:")
    print(json.dumps(order, indent=2))


if __name__ == "__main__":
    AUDIO = "samples/amul1.mp3"   # our known-good test clip
    final_state = run_pipeline(AUDIO)
    show_order(final_state)
