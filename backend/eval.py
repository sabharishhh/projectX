"""test_prompt_caching.py — verifies the build_system_message split +
_with_time reorder actually produce cache hits, without needing to click
through the UI. Calls the real provider directly with a realistic,
large-enough system prompt, three times with increasing delay between
calls, and checks whether cached_tokens ever goes non-zero.

v3: prints the ACTUAL message order _with_time produces before sending —
the OpenAI usage dashboard appeared to show the user message first and
all system messages after, which contradicts what the code should be
producing. This confirms definitively whether the bug is in _with_time's
logic or whether the dashboard's display order is just misleading.

Run: python test_prompt_caching.py
"""

import sys
import os
import time
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from state import provider, model
from memory import build_system_message
from providers.base import Provider

FAKE_UNITS = [
    {"unit_type": "identity", "content": f"Fact number {i} about the user, padded with some extra "
     "descriptive text to make sure the overall system prompt comfortably clears the token "
     "threshold OpenAI requires before prompt caching becomes eligible at all.", "provenance": "stated"}
    for i in range(15)
]

FAKE_SKILL_PROMPT = (
    "You are helping with a general task. Be thorough, cite sources where relevant, "
    "and structure your answer clearly with headers and bullet points where it helps "
    "readability. Avoid unnecessary hedging but flag genuine uncertainty honestly."
)


def run_call(label: str):
    messages = build_system_message(FAKE_UNITS, FAKE_SKILL_PROMPT, include_identity=True) + [
        {"role": "user", "content": f"Quick check-in message, call label: {label}. "
                                     "Just reply with a short acknowledgement."},
    ]

    # Show the EXACT order _with_time produces, before it ever reaches
    # the API — this is the ground truth for what the code does,
    # independent of how OpenAI's dashboard chooses to display it.
    final_messages = Provider._with_time(messages)
    print(f"\n--- {label}: actual message order produced by _with_time ---")
    for i, m in enumerate(final_messages):
        preview = m["content"][:60].replace("\n", " ")
        print(f"  [{i}] role={m['role']:10s} content={preview!r}...")

    total_tokens = sum(len(m["content"]) for m in messages) // 4
    print(f"\n--- {label} (approx {total_tokens} tokens) ---")
    t0 = time.monotonic()
    text = "".join(provider.stream(messages, model, reasoning_effort="none"))
    elapsed = time.monotonic() - t0
    print(f"Response ({elapsed:.2f}s): {text[:80]!r}")
    print("^ check the 'prompt cache: X/Y input tokens cached' line above this for the real number")


def main():
    print("=" * 70)
    print("PROMPT CACHING TEST (v3 — message-order verification)")
    print("=" * 70)

    run_call("first-call")

    print("\nWaiting 15s before second call...")
    time.sleep(15)
    run_call("second-call")

    print("\nWaiting 15s before third call...")
    time.sleep(15)
    run_call("third-call")

    print("\n" + "=" * 70)
    print("Compare the printed [0][1][2][3] order above against what the")
    print("OpenAI usage dashboard shows for these calls. If they match,")
    print("the dashboard's order is accurate and the caching gap is real.")
    print("If they differ, the dashboard was reordering for display only.")
    print("=" * 70)


if __name__ == "__main__":
    main()