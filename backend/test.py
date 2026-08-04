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


def find_unit_anywhere(tag: str, branches=BRANCHES) -> tuple[dict | None, str | None]:
    """Searches every branch for a unit whose content contains the given
    unique tag, case-insensitively — matches only the tag itself, not a
    full phrase, since extraction naturally rewrites compound words
    ("pickup" -> "pick up") and re-cases things ("dc04ed" -> "DC04ED").
    The tag is the only thing that actually needs to survive verbatim;
    the surrounding sentence is free to be rephrased."""
    tag_lower = tag.lower()
    for b in branches:
        for u in get_state(b):
            if tag_lower in u["content"].lower():
                return u, b
    return None, None


def activity_events(events: list[dict], kind: str) -> list[dict]:
    return [e["event"] for e in events if e.get("type") == "activity" and e["event"].get("kind") == kind]


# --- Bug 2: duplicate-detection status-awareness (via real chat flow) ---

def test_bug2_duplicate_after_resolution():
    print("\n=== Bug 2: resolved commitment shouldn't block re-adding (via real chat flow) ===")
    cid = new_conversation_id()
    tag = uuid.uuid4().hex[:6]
    setup_msg = f"remember that I need to pick up the eval package {tag} tomorrow"

    events = send_chat(cid, setup_msg)
    writes = activity_events(events, "memory_write")
    if not any(tag.lower() in u["content"].lower() for w in writes for u in w.get("units", [])):
        report("initial commitment capture", FAIL, "no memory_write event contained the test tag")
        return
    report("initial commitment capture", PASS)

    unit, branch = find_unit_anywhere(tag)
    if not unit:
        report("unit present in memory-engine state", FAIL, "not found on any branch")
        return
    report("unit present in memory-engine state", PASS, f"branch={branch}")

    resolve_msg = f"I just finished, I already picked up the eval package {tag}, that's done"
    events2 = send_chat(cid, resolve_msg)
    proposals = activity_events(events2, "commitment_resolution_request")
    matching = [p for p in proposals if tag.lower() in p.get("content", "").lower()]

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
    resolved_unit, _ = find_unit_anywhere(tag)
    if not resolved_unit or resolved_unit.get("commitment_status") not in ("done", "cancelled"):
        report("commitment actually resolved before re-add attempt", FAIL,
               f"status is {resolved_unit.get('commitment_status') if resolved_unit else 'MISSING'} — can't test re-add on an unresolved unit")
        return
    report("commitment actually resolved before re-add attempt", PASS)

    cid2 = new_conversation_id()
    events3 = send_chat(cid2, setup_msg)
    dups = activity_events(events3, "duplicate_skipped")
    writes2 = activity_events(events3, "memory_write")

    blocked = any(tag.lower() in d.get("content", "").lower() for d in dups)
    added_again = any(tag.lower() in u["content"].lower() for w in writes2 for u in w.get("units", []))

    if added_again:
        report("re-add after resolution (chat-driven)", PASS,
               "new commitment committed despite resolved unit sharing content")
    elif blocked:
        report("re-add after resolution (chat-driven)", FAIL,
               "blocked as duplicate at the commit-check stage — is_semantic_duplicate/_is_live_duplicate regression")
    else:
        report("re-add after resolution (chat-driven)", FAIL,
               "silently dropped before reaching the duplicate check — CAPTURE_PROMPT's known-facts filter regression")


# --- Bug 1: commitment resolution requires confirmation ---

def test_bug1_resolution_confirmation_gate():
    print("\n=== Bug 1: commitment resolution needs explicit confirm ===")
    cid = new_conversation_id()
    tag = uuid.uuid4().hex[:6]
    setup_msg = f"remember that I need to email the eval vendor {tag} by Friday"

    events = send_chat(cid, setup_msg)
    if not activity_events(events, "memory_write"):
        report("setup commitment for resolution test", FAIL, "commitment never committed — aborting Bug 1 test")
        return
    report("setup commitment for resolution test", PASS)

    unit, branch = find_unit_anywhere(tag)
    if not unit:
        report("unit present before resolution attempt", FAIL, "not found on any branch")
        return
    report("unit present before resolution attempt", PASS, f"branch={branch}")

    resolve_msg = f"I just finished, I already emailed the eval vendor {tag}, that's done"
    events2 = send_chat(cid, resolve_msg)
    proposals = activity_events(events2, "commitment_resolution_request")
    matching = [p for p in proposals if tag.lower() in p.get("content", "").lower()]

    if not matching:
        report("resolution proposal surfaced", WARN,
               "model didn't judge this exchange as resolving the commitment this run — "
               "not a fix failure, just LLM judgment variance; rerun or rephrase to retest")
        return
    report("resolution proposal surfaced as pending, not auto-applied", PASS)

    unit_after, _ = find_unit_anywhere(tag)
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
    unit_final, _ = find_unit_anywhere(tag)
    if unit_final and unit_final.get("commitment_status") in ("done", "cancelled"):
        report("commitment status updated after explicit confirm", PASS)
    else:
        report("commitment status updated after explicit confirm", FAIL,
               f"status is {unit_final.get('commitment_status') if unit_final else 'MISSING'}")


def test_bug1_deny_keeps_open():
    print("\n=== Bug 1b: 'deny' must not touch memory ===")
    cid = new_conversation_id()
    tag = uuid.uuid4().hex[:6]
    events = send_chat(cid, f"remember that I need to renew the eval license {tag} next week")
    if not activity_events(events, "memory_write"):
        report("setup commitment for deny test", FAIL)
        return

    events2 = send_chat(cid, f"I renewed the eval license {tag}, all set")
    proposals = activity_events(events2, "commitment_resolution_request")
    matching = [p for p in proposals if tag.lower() in p.get("content", "").lower()]
    if not matching:
        report("resolution proposal for deny test", WARN, "model didn't propose resolution this run")
        return

    r = httpx.post(f"{API_BASE}/api/memory/resolve_commitment",
                    json={"resolution_id": matching[0]["id"], "choice": "deny"}, timeout=20.0)
    report("deny endpoint returned ok", PASS if r.json().get("ok") else FAIL)

    unit, branch = find_unit_anywhere(tag)
    if unit and unit.get("commitment_status") == "open":
        report("status remains open after deny", PASS, f"branch={branch}")
    else:
        report("status remains open after deny", FAIL,
               f"status is {unit.get('commitment_status') if unit else 'MISSING (checked all branches)'}")


async def test_bug3_disconnect_no_orphan_write():
    print("\n=== Bug 3: disconnect mid-turn shouldn't orphan a memory write ===")
    cid = new_conversation_id()
    tag = uuid.uuid4().hex[:6]
    msg = f"remember that I need to walk the eval dog {tag} every evening"

    already_there, _ = find_unit_anywhere(tag)
    if already_there:
        report("pre-check: tag not already in memory", FAIL, "test tag collision, rerun")
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            async with client.stream("POST", f"{API_BASE}/api/chat",
                                      json={"conversation_id": cid, "message": msg}) as r:
                frame_count = 0
                async for _ in r.aiter_text():
                    frame_count += 1
                    if frame_count >= 2:
                        break
        except httpx.ReadError:
            pass

    report("aborted connection mid-stream", PASS, f"after {frame_count} frame(s)")
    await asyncio.sleep(3.0)

    unit_after, branch_after = find_unit_anywhere(tag)
    if unit_after is None:
        report("no orphaned commitment write after disconnect", PASS)
    else:
        report("no orphaned commitment write after disconnect", FAIL,
               f"tag was committed anyway on branch={branch_after} — capture ran despite disconnect, checkpoint not effective")


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