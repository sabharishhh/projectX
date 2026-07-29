# test_forgetting.py — run from backend/
from dotenv import load_dotenv
load_dotenv()

from providers import get_provider
from memory import fetch_state
import forgetting

provider, model = get_provider()
known = [{**u, "branch": "main"} for u in fetch_state("main")]

tests = [
    "forget stuff about movies",
    "forget everything about films",
    "I don't like Cillian Murphy anymore, forget that",
    "forget my trip to Japan",  # should also work — different fact, sanity check
    "what's the weather today",  # should return [] — not a forget request at all
]

for msg in tests:
    print(f"\n--- {msg!r} ---")
    matches = forgetting.detect_forget_request(provider, msg, known, ["main"])
    for m in matches:
        print(f"  MATCHED: {m['unit']['content']}  ({m['reason']})")
    if not matches:
        print("  (no matches)")