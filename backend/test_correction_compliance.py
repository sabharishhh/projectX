"""test_correction_enforcement.py — exercises the full compiled-
correction pipeline via stream_chat(): capture of a new correction unit,
the deterministic gate (no active corrections = unchanged pass-through
behavior), the natural-compliance path, and a DETERMINISTIC forced
violation (via monkeypatch, not hoping the model gets it wrong) to prove
the regeneration path actually fires and only the corrected reply ever
reaches the client.

Run from backend/, with the memory engine + backend dependencies running:
    uv run python3 test_correction_enforcement.py
"""

import json
import sys
import uuid

from dotenv import load_dotenv
load_dotenv()

import chat_engine
import capture

failures = []


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def run_turn(conversation_id: str, message: str) -> list[dict]:
    events = []
    
    for raw in chat_engine.stream_chat(conversation_id, message):
        payload = json.loads(raw.removeprefix("data: ").strip())
        events.append(payload)
        if payload["type"] == "activity":
            print(f"  [activity] {payload['event'].get('kind')}: {payload['event'].get('label', '')}")
    return events


def text_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "text"]


def full_text(events: list[dict]) -> str:
    return "".join(e["value"] for e in text_events(events))


def kinds(events: list[dict], event_type: str) -> list[str]:
    return [e["event"]["kind"] for e in events if e["type"] == event_type]


BRANCH_CONV = f"test-correction-{uuid.uuid4().hex[:8]}"


# --- 1. Control: no active corrections yet — behavior must be byte-for-
#        byte unchanged (live streaming, no "reveal" flag, no check card) ---
print("\n--- 1. control: no active corrections ---")
events = run_turn(BRANCH_CONV, "hey, how's it going")
check("no correction_check activity card", "correction_check" not in kinds(events, "activity"))
check("no text event carries a 'reveal' flag (true live streaming)",
      all("reveal" not in e for e in text_events(events)))
check("no error, done present", not any(e["type"] == "error" for e in events) and any(e["type"] == "done" for e in events))


# --- 2. Capture a real correction ---
print("\n--- 2. capturing a correction ---")
events2 = run_turn(BRANCH_CONV, "no, I already told you — always end every response with the exact phrase 'Anything else?'")
check("memory_write activity appears for the correction", "memory_write" in kinds(events2, "activity"), detail=str(kinds(events2, "activity")))


# --- 3. Natural compliance: unrelated message, correction now active ---
print("\n--- 3. active correction, natural compliance ---")
events3 = run_turn(BRANCH_CONV, "what's the capital of France")
check("correction_check activity card appears now that a correction is active",
      "correction_check" in kinds(events3, "activity"))
texts3 = text_events(events3)
check("exactly one text event (buffered, not token-streamed)", len(texts3) == 1, detail=f"got {len(texts3)}")
if texts3:
    check("that text event is marked for simulated reveal", texts3[0].get("reveal") == "simulated")
reply3 = full_text(events3)
check("reply actually complies with the correction", reply3.strip().endswith("Anything else?"), detail=reply3[-60:])


# --- 4. Deterministic forced violation, via monkeypatch — proves the
#        regeneration path fires and the flawed draft is never shown ---
print("\n--- 4. forced violation (monkeypatched) ---")
original_check = chat_engine.check_correction_compliance
call_count = {"n": 0}


def _forced_violation(provider, corrections, reply):
    call_count["n"] += 1
    if call_count["n"] == 1:
        return {"compliant": False, "violated": ["Always end every response with 'Anything else?'"],
                "guidance": "You forgot to end with 'Anything else?' — add it."}
    return original_check(provider, corrections, reply)  # real check on any subsequent call


chat_engine.check_correction_compliance = _forced_violation
try:
    events4 = run_turn(BRANCH_CONV, "what's 2 plus 2")
finally:
    chat_engine.check_correction_compliance = original_check

texts4 = text_events(events4)
reply4 = full_text(events4)
check("still exactly one text event reaches the client (flawed draft never shown)", len(texts4) == 1, detail=f"got {len(texts4)}")
check("the ONE reply shown is the corrected version, compliant with the rule",
      reply4.strip().endswith("Anything else?"), detail=reply4[-60:])
check("no error surfaced to the client despite the internal regeneration pass",
      not any(e["type"] == "error" for e in events4))


print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)