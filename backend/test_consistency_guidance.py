"""test_consistency_guidance.py — v3, with proper branch isolation and
relative-time deadlines so the suite doesn't silently fail depending on
what wall-clock time it happens to run at (root cause of two false
failures found and confirmed via debug_extract.py / debug_resolve.py)."""

import json
import sys
import uuid
import httpx

import chat_engine
import capture

failures = []

def real_state(branch="main"):
    """Bypasses memory.py's module-level cache entirely — reads directly
    from the engine, for verifying actual ground truth in tests, not
    what the app's read-path happens to have cached."""
    r = httpx.get(f"http://127.0.0.1:8100/state", params={"branch": branch}, timeout=10.0)
    r.raise_for_status()
    return r.json()

def find_unit_and_branch(keyword: str):
    """Searches all standard branches for a commitment matching the keyword."""
    for branch in ["main", "personal", "work"]:
        state = real_state(branch)
        target = next((u for u in state if keyword in u["content"].lower()
                       and u.get("unit_type") == "commitment"), None)
        if target:
            return target, branch
    return None, None

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
    return events


def full_text(events: list[dict]) -> str:
    return "".join(e["value"] for e in events if e["type"] == "text")


# --- 0. asking about a commitment must NOT resolve it ---
print("--- 0. asking about a commitment must not silently resolve it ---")
conv0 = f"test-consistency-{uuid.uuid4().hex[:8]}"
run_turn(conv0, "I need to water the plants in 3 hours")
run_turn(conv0, "what are my commitments for today?")

plant_unit, _ = find_unit_and_branch("plant")
check("commitment still shows OPEN after being merely asked about — not silently resolved",
      plant_unit is not None and plant_unit.get("commitment_status") == "open",
      detail=str(plant_unit))


# --- 1. Core case: state -> confirmed -> deleted -> must NOT defend stale claim ---
print("\n--- 1. delete mid-conversation, must not insist on stale claim ---")
conv1 = f"test-consistency-{uuid.uuid4().hex[:8]}"

run_turn(conv1, "I need to feed the cat in 3 hours")
events3 = run_turn(conv1, "what are my commitments for today?")
reply3 = full_text(events3).lower()
check("reply mentions the live commitment", "cat" in reply3, detail=reply3)

target, target_branch = find_unit_and_branch("cat")
check("commitment found and still open before manual delete",
      target is not None and target.get("commitment_status") == "open",
      detail="Not found in any branch")

if target:
    ok = capture.forget_unit(target["hash"], "test-consistency", target_branch, "test cleanup")
    check("forget_unit succeeded", ok)

    events4 = run_turn(conv1, "is the cat feeding commitment still open?")
    reply4 = full_text(events4).lower()
    check("does NOT insist the commitment is still open (the original bug)",
          not ("still" in reply4 and "open" in reply4), detail=reply4)


# --- 2. Reverse: genuinely still open, must not falsely resolve from stale context ---
print("\n--- 2. genuinely open commitment must stay reported as open ---")
conv2 = f"test-consistency-{uuid.uuid4().hex[:8]}"
run_turn(conv2, "I need to call the bank tomorrow")
run_turn(conv2, "did I call the bank yet?")
events3 = run_turn(conv2, "what commitments do I still have open?")
reply3 = full_text(events3).lower()
check("correctly still reports the bank call as open", "bank" in reply3, detail=reply3)


# --- 3. Control: isolated branch, nothing pre-existing, no cross-test bleed ---
print("\n--- 3. control: isolated branch, genuinely nothing tracked ---")
conv3 = f"test-consistency-{uuid.uuid4().hex[:8]}"
isolated_branch = f"eval-isolated-{uuid.uuid4().hex[:8]}"
events = run_turn(conv3, f"what are my commitments for today on the {isolated_branch} branch?")
# Note: this still queries against the router's chosen branch since branch
# routing is content-driven, not directly controllable via phrasing — this
# control is best-effort; a true isolated-branch control would need
# chat_engine's branch resolution exposed directly, which it currently isn't.
reply = full_text(events).lower()
print(f"  [INFO] reply: {reply!r} — not asserted, branch routing can't be forced from a chat message alone")


print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)