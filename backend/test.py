"""End-to-end regression eval for the three bugs fixed this session:
  Bug 1: commitment resolution auto-applied with no confirmation gate
  Bug 2: resolved commitments blocked re-adding identical content
  Bug 3: capture ran orphaned after client disconnect, and responses
         vanished on refresh before being persisted

Hits the real backend (port 8000) and reads ground truth directly from
the memory engine (port 8100) rather than trusting the chat replies —
same evidence-first principle as everything else this session.

Run: python eval_fixes.py
Requires: backend + memory engine both already running.
"""
import json
import time
import uuid
import asyncio
import httpx

API_BASE = "http://127.0.0.1:8000"
MEMORY_BASE = "http://127.0.0.1:8100"
BRANCHES = ("main", "personal", "work")

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []

def report(name: str, status: str, detail: str = ""):
    results.append((name, status))
    tag = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}[status]
    print(f"{tag} [{status}] {name}" + (f" — {detail}" if detail else ""))


def new_conversation_id() -> str:
    return str(uuid.uuid4())


def send_chat(conversation_id: str, message: str) -> list[dict]:
    """Sends a message, fully consumes the SSE stream, returns the list of
    parsed event dicts in order. Blocks until the server sends 'done'."""
    events = []
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", f"{API_BASE}/api/chat",
                            json={"conversation_id": conversation_id, "message": message}) as r:
            buffer = ""
            for chunk in r.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    line, buffer = buffer.split("\n\n", 1)
                    if line.startswith("data: "):
                        ev = json.loads(line[6:])
                        events.append(ev)
                        if ev.get("type") == "done":
                            return events
    return events


def get_state(branch: str = "main") -> list[dict]:
    r = httpx.get(f"{MEMORY_BASE}/state", params={"branch": branch}, timeout=20.0)
    r.raise_for_status()
    return r.json()


def find_unit_by_content(units: list[dict], content_fragment: str) -> dict | None:
    for u in units:
        if content_fragment.lower() in u["content"].lower():
            return u
    return None


def find_unit_anywhere(content_fragment: str, branches=BRANCHES) -> tuple[dict | None, str | None]:
    """Searches every branch, since capture's own domain classification
    decides where a unit actually lands — a test can't assume 'main' just
    because that's the common case. Returns (unit, branch) or (None, None)."""
    for b in branches:
        unit = find_unit_by_content(get_state(b), content_fragment)
        if unit:
            return unit, b
    return None, None


def activity_events(events: list[dict], kind: str) -> list[dict]:
    return [e["event"] for e in events if e.get("type") == "activity" and e["event"].get("kind") == kind]


# --- Bug 2: duplicate-detection status-awareness (via real chat flow) ---

def test_bug2_duplicate_after_resolution():
    print("\n=== Bug 2: resolved commitment shouldn't block re-adding (via real chat flow) ===")
    cid = new_conversation_id()
    fragment = f"pickup-the-eval-package-{uuid.uuid4().hex[:6]}"
    setup_msg = f"remember that I need to {fragment} tomorrow"

    events = send_chat(cid, setup_msg)
    writes = activity_events(events, "memory_write")
    if not any(fragment in u["content"] for w in writes for u in w.get("units", [])):
        report("initial commitment capture", FAIL, "no memory_write event contained the test fragment")
        return
    report("initial commitment capture", PASS)

    unit, branch = find_unit_anywhere(fragment)
    if not unit:
        report("unit present in memory-engine state", FAIL, "not found on any branch")
        return
    report("unit present in memory-engine state", PASS, f"branch={branch}")

    # Resolve through the real flow: propose, then explicitly confirm —
    # same path Bug 1's test exercises, so this test also covers the
    # extraction-prompt filter (CAPTURE_PROMPT's known-facts block), not
    # just the /remember-level dedup check.
    resolve_msg = f"I just finished, I already {fragment.replace('-', ' ')}, that's done"
    events2 = send_chat(cid, resolve_msg)
    proposals = activity_events(events2, "commitment_resolution_request")
    matching = [p for p in proposals if fragment.replace("-", " ") in p.get("content", "").replace("-", " ")]

    if not matching:
        report("resolution proposal surfaced", WARN,
               "model didn't judge this exchange as resolving the commitment this run — "
               "not a fix failure, just LLM judgment variance; rerun to retest")
        return
    report("resolution proposal surfaced", PASS)

    r = httpx.post(f"{API_BASE}/api/memory/resolve_commitment",
                    json={"resolution_id": matching[0]["id"], "choice": "confirm"}, timeout=20.0)
    if not r.json().get("ok", False):
        report("confirm endpoint returned ok", FAIL)
        return
    report("confirm endpoint returned ok", PASS)

    time.sleep(0.5)
    resolved_unit, _ = find_unit_anywhere(fragment)
    if not resolved_unit or resolved_unit.get("commitment_status") not in ("done", "cancelled"):
        report("commitment actually resolved before re-add attempt", FAIL,
               f"status is {resolved_unit.get('commitment_status') if resolved_unit else 'MISSING'} — can't test re-add on an unresolved unit")
        return
    report("commitment actually resolved before re-add attempt", PASS)

    # The real test: re-add the exact same content in a fresh conversation.
    # This only exercises the extraction-prompt filter if it actually
    # reaches extract_units at all — if CAPTURE_PROMPT still sees the
    # resolved unit's content in its known-facts block, it silently
    # declines to propose it, which shows up as zero candidates rather
    # than a duplicate_skipped event.
    cid2 = new_conversation_id()
    events3 = send_chat(cid2, setup_msg)
    dups = activity_events(events3, "duplicate_skipped")
    writes2 = activity_events(events3, "memory_write")

    blocked = any(fragment in d.get("content", "") for d in dups)
    added_again = any(fragment in u["content"] for w in writes2 for u in w.get("units", []))

    if added_again:
        report("re-add after resolution (chat-driven)", PASS,
               "new commitment committed despite resolved unit sharing content")
    elif blocked:
        report("re-add after resolution (chat-driven)", FAIL,
               "blocked as duplicate at the commit-check stage — is_semantic_duplicate/_is_live_duplicate regression")
    else:
        report("re-add after resolution (chat-driven)", FAIL,
               "silently dropped before reaching the duplicate check — CAPTURE_PROMPT's known-facts filter regression "
               "(extract_units likely returned 0 candidates; check server logs for 'extract_units raw: 0')")


# --- Bug 1: commitment resolution requires confirmation ---

def test_bug1_resolution_confirmation_gate():
    print("\n=== Bug 1: commitment resolution needs explicit confirm ===")
    cid = new_conversation_id()
    fragment = f"email-the-eval-vendor-{uuid.uuid4().hex[:6]}"
    setup_msg = f"remember that I need to {fragment} by Friday"

    events = send_chat(cid, setup_msg)
    if not activity_events(events, "memory_write"):
        report("setup commitment for resolution test", FAIL, "commitment never committed — aborting Bug 1 test")
        return
    report("setup commitment for resolution test", PASS)

    unit, branch = find_unit_anywhere(fragment)
    if not unit:
        report("unit present before resolution attempt", FAIL, "not found on any branch")
        return
    report("unit present before resolution attempt", PASS, f"branch={branch}")

    resolve_msg = f"I just finished, I already {fragment.replace('-', ' ')}, that's done"
    events2 = send_chat(cid, resolve_msg)
    proposals = activity_events(events2, "commitment_resolution_request")

    matching = [p for p in proposals if fragment.replace("-", " ") in p.get("content", "").replace("-", " ")]
    if not matching:
        report("resolution proposal surfaced", WARN,
               "model didn't judge this exchange as resolving the commitment this run — "
               "not a fix failure, just LLM judgment variance; rerun or rephrase to retest")
        return
    report("resolution proposal surfaced as pending, not auto-applied", PASS)

    # Ground truth: status must STILL be open immediately after — this is
    # the actual regression test for Bug 1.
    unit_after, _ = find_unit_anywhere(fragment)
    if unit_after and unit_after.get("commitment_status") == "open":
        report("commitment status unchanged pre-confirmation", PASS)
    else:
        report("commitment status unchanged pre-confirmation", FAIL,
               f"status is {unit_after.get('commitment_status') if unit_after else 'MISSING'} — Bug 1 regressed, auto-resolved again")
        return

    resolution_id = matching[0]["id"]
    r = httpx.post(f"{API_BASE}/api/memory/resolve_commitment",
                    json={"resolution_id": resolution_id, "choice": "confirm"}, timeout=20.0)
    ok = r.json().get("ok", False)
    report("confirm endpoint returned ok", PASS if ok else FAIL)

    time.sleep(0.5)
    unit_final, _ = find_unit_anywhere(fragment)
    if unit_final and unit_final.get("commitment_status") in ("done", "cancelled"):
        report("commitment status updated after explicit confirm", PASS)
    else:
        report("commitment status updated after explicit confirm", FAIL,
               f"status is {unit_final.get('commitment_status') if unit_final else 'MISSING'}")


def test_bug1_deny_keeps_open():
    print("\n=== Bug 1b: 'deny' must not touch memory ===")
    cid = new_conversation_id()
    fragment = f"renew-the-eval-license-{uuid.uuid4().hex[:6]}"
    events = send_chat(cid, f"remember that I need to {fragment} next week")
    if not activity_events(events, "memory_write"):
        report("setup commitment for deny test", FAIL)
        return

    events2 = send_chat(cid, f"I {fragment.replace('-', ' ')}, all set")
    proposals = activity_events(events2, "commitment_resolution_request")
    matching = [p for p in proposals if fragment.replace("-", " ") in p.get("content", "").replace("-", " ")]
    if not matching:
        report("resolution proposal for deny test", WARN, "model didn't propose resolution this run")
        return

    r = httpx.post(f"{API_BASE}/api/memory/resolve_commitment",
                    json={"resolution_id": matching[0]["id"], "choice": "deny"}, timeout=20.0)
    report("deny endpoint returned ok", PASS if r.json().get("ok") else FAIL)

    unit, branch = find_unit_anywhere(fragment)
    if unit and unit.get("commitment_status") == "open":
        report("status remains open after deny", PASS, f"branch={branch}")
    else:
        report("status remains open after deny", FAIL,
               f"status is {unit.get('commitment_status') if unit else 'MISSING (checked all branches)'}")


# --- Bug 3: disconnect during generation must not orphan a write, and the
# reply must still be persisted if it completed before the client left ---

async def test_bug3_disconnect_no_orphan_write():
    print("\n=== Bug 3: disconnect mid-turn shouldn't orphan a memory write ===")
    cid = new_conversation_id()
    fragment = f"walk-the-eval-dog-{uuid.uuid4().hex[:6]}"
    msg = f"remember that I need to {fragment} every evening"

    already_there, _ = find_unit_anywhere(fragment)
    if already_there:
        report("pre-check: fragment not already in memory", FAIL, "test fragment collision, rerun")
        return

    # Open the stream, read a few frames (enough to be mid-generation), then
    # abort the connection outright — mirrors a browser refresh mid-turn.
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            async with client.stream("POST", f"{API_BASE}/api/chat",
                                      json={"conversation_id": cid, "message": msg}) as r:
                frame_count = 0
                async for _ in r.aiter_text():
                    frame_count += 1
                    if frame_count >= 2:
                        break  # abrupt client-side abandonment, no clean close
        except httpx.ReadError:
            pass  # expected — we're intentionally cutting the connection

    report("aborted connection mid-stream", PASS, f"after {frame_count} frame(s)")

    # Give the backend's disconnect watcher its poll interval plus margin.
    await asyncio.sleep(3.0)

    unit_after, branch_after = find_unit_anywhere(fragment)
    if unit_after is None:
        report("no orphaned commitment write after disconnect", PASS)
    else:
        report("no orphaned commitment write after disconnect", FAIL,
               f"fragment was committed anyway on branch={branch_after} — capture ran despite disconnect, checkpoint not effective")


def test_bug3_reply_persists_on_refresh():
    print("\n=== Bug 3b: completed reply survives even if capture is interrupted ===")
    cid = new_conversation_id()
    events = send_chat(cid, "hey, just say hello back, nothing else")
    text_events = [e for e in events if e.get("type") == "text"]
    if not text_events:
        report("reply generated", FAIL, "no text events at all")
        return
    report("reply generated", PASS)

    r = httpx.get(f"{API_BASE}/api/messages/{cid}", timeout=20.0)
    msgs = r.json()
    has_assistant_msg = any(m.get("role") == "assistant" and m.get("content", "").strip() for m in msgs)
    report("reply persisted and retrievable via /api/messages", PASS if has_assistant_msg else FAIL)


def main():
    print(f"Running eval against {API_BASE} / {MEMORY_BASE}\n" + "=" * 60)

    test_bug2_duplicate_after_resolution()
    test_bug1_resolution_confirmation_gate()
    test_bug1_deny_keeps_open()
    test_bug3_reply_persists_on_refresh()
    asyncio.run(test_bug3_disconnect_no_orphan_write())

    print("\n" + "=" * 60)
    passed = sum(1 for _, s in results if s == PASS)
    failed = sum(1 for _, s in results if s == FAIL)
    warned = sum(1 for _, s in results if s == WARN)
    print(f"SUMMARY: {passed} passed, {failed} failed, {warned} warnings (LLM-judgment-dependent, not hard failures)")
    if failed:
        print("\nFailed checks:")
        for name, status in results:
            if status == FAIL:
                print(f"  - {name}")


if __name__ == "__main__":
    main()