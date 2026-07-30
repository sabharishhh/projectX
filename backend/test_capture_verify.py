"""test_capture_verify.py — checks whether the new verify stage in
capture.py actually rejects assistant-about-itself exchanges, across
several phrasings, not just the one that originally surfaced the bug.
Calls extract_units() directly (bypassing chat_engine.py entirely) so
this isolates capture's own behavior from routing/skill/search noise.

Run from backend/:
    uv run python3 test_capture_verify.py
"""

import sys

from dotenv import load_dotenv
load_dotenv()

from providers import get_provider
from capture import extract_units

provider, model = get_provider()
BRANCHES = ["main", "work", "personal"]

# Each case: (user_message, assistant_reply, should_capture_anything)
# The assistant replies are written as plausible real answers projectX
# would actually give, not idealized text — testing against what the
# verify stage would really see in a live turn.
CASES = [
    ("who created you?", "I was created by Sabharish.", False),
    ("who made you", "Sabharish built me.", False),
    ("who built you?", "I was built by Sabharish.", False),
    ("what's your name?", "I'm projectX.", False),
    ("what are you called", "My name is projectX.", False),
    ("who are you", "I'm projectX, your personal AI assistant.", False),
    ("are you an AI made by Sabharish?", "Yes, I'm projectX, and Sabharish created me.", False),

    # Adjacent-but-legitimate cases — should still capture normally,
    # confirms the verify stage isn't rejecting everything indiscriminately
    ("my name is Arjun", "Nice to meet you, Arjun.", True),
    ("I created a new project called Nightjar", "Got it — I'll remember that.", True),
    ("remember that I was born in Kochi", "Noted — you were born in Kochi.", True),
]

failures = []


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


for user_msg, assistant_reply, should_capture in CASES:
    print(f"\n--- {user_msg!r} ---")
    units = extract_units(provider, user_msg, assistant_reply, known=[], branches=BRANCHES)
    got_something = len(units) > 0
    for u in units:
        print(f"  captured: {u['content']!r} ({u['unit_type']})")

    if should_capture:
        check(f"correctly captured something for {user_msg!r}", got_something)
    else:
        check(f"correctly captured NOTHING for {user_msg!r}", not got_something,
              detail=f"got: {[u['content'] for u in units]}")

print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)