#!/usr/bin/env python3
"""
projectX integration test suite.

Exercises the live backend (FastAPI, :8000) and memory engine (Rust/axum, :8100)
end to end — real HTTP calls, real LLM calls, real SSE streams. Not a unit test
suite; this is closer to the manual curl-based testing done throughout this
project's build, just automated and sequenced.

Prerequisites:
  - backend running: cd backend && uv run uvicorn main:app --reload
  - memory engine running: cd memory-engine && cargo run
  - SearXNG running (for the search tests): docker start searxng
  - OPENAI_API_KEY (or your configured provider) set in backend/.env

Usage:
  cd backend
  uv run python3 test_projectx.py

Notes:
  - This suite is intentionally destructive: it resets memory and clears chat
    history at various points. Do not run against data you want to keep.
  - LLM calls are non-deterministic, so assertions are written to be lenient
    (checking for presence/absence of signals, not exact wording).
  - Each test is isolated in a try/except so one failure doesn't abort the run.
"""

import json
import sys
import time
import uuid

import httpx

BACKEND = "http://127.0.0.1:8000"
MEMORY = "http://127.0.0.1:8100"

results = {"pass": 0, "fail": 0, "skip": 0}


def ok(label: str, condition: bool, detail: str = ""):
    if condition:
        results["pass"] += 1
        print(f"  \033[92m✓\033[0m {label}")
    else:
        results["fail"] += 1
        print(f"  \033[91m✗\033[0m {label}" + (f"  ({detail})" if detail else ""))
    return condition


def skip(label: str, reason: str):
    results["skip"] += 1
    print(f"  \033[93m—\033[0m {label}  [skipped: {reason}]")


def section(title: str):
    print(f"\n\033[1m{title}\033[0m")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def chat(conversation_id: str, message: str, timeout: float = 120.0) -> dict:
    """Sends a message, consumes the SSE stream, returns the assembled result:
    {"text": full response, "activity": [event, ...]}."""
    text = ""
    activity = []
    with httpx.stream(
        "POST", f"{BACKEND}/api/chat",
        json={"conversation_id": conversation_id, "message": message},
        timeout=timeout,
    ) as r:
        buffer = ""
        for chunk in r.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if ev["type"] == "text":
                    text += ev["value"]
                elif ev["type"] == "activity":
                    activity.append(ev["event"])
                elif ev["type"] == "error":
                    activity.append({"kind": "__error__", "message": ev["message"]})
    return {"text": text, "activity": activity}


def activity_kinds(result: dict) -> list[str]:
    return [a["kind"] for a in result["activity"]]


def memory_state(branch: str = "main") -> list[dict]:
    r = httpx.get(f"{MEMORY}/state", params={"branch": branch}, timeout=5.0)
    r.raise_for_status()
    return r.json()


def reset_memory():
    httpx.post(f"{MEMORY}/reset", timeout=5.0)


def clear_chat(conversation_id: str):
    httpx.delete(f"{BACKEND}/api/messages/{conversation_id}", timeout=5.0)


def ledger(limit: int = 20) -> list[dict]:
    r = httpx.get(f"{BACKEND}/api/ledger", params={"limit": limit}, timeout=5.0)
    r.raise_for_status()
    return r.json()


def new_conversation_id() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_infra():
    section("Infrastructure")
    try:
        r = httpx.get(f"{BACKEND}/health", timeout=5.0)
        ok("backend is reachable", r.status_code == 200)
    except Exception as e:
        ok("backend is reachable", False, str(e))
        print("\n  Backend not reachable — aborting remaining tests.")
        sys.exit(1)

    try:
        r = httpx.get(f"{MEMORY}/health", timeout=5.0)
        ok("memory engine is reachable", r.status_code == 200)
    except Exception as e:
        ok("memory engine is reachable", False, str(e))
        print("\n  Memory engine not reachable — aborting remaining tests.")
        sys.exit(1)

    try:
        r = httpx.get("http://localhost:8888/search", params={"q": "test", "format": "json"}, timeout=5.0)
        ok("searxng is reachable", r.status_code == 200)
    except Exception:
        skip("searxng is reachable", "search-dependent tests will be skipped")


def test_basic_chat():
    section("Basic chat")
    conv = new_conversation_id()
    result = chat(conv, "Say the word 'pineapple' and nothing else.")
    ok("got a non-empty response", len(result["text"].strip()) > 0)
    ok("response is roughly on-topic", "pineapple" in result["text"].lower())

    msgs = httpx.get(f"{BACKEND}/api/messages/{conv}").json()
    ok("message persisted (2 turns)", len(msgs) == 2, f"got {len(msgs)}")
    ok("first turn is the user message", msgs[0]["role"] == "user")
    ok("second turn is the assistant reply", msgs[1]["role"] == "assistant")

    clear_chat(conv)
    msgs_after = httpx.get(f"{BACKEND}/api/messages/{conv}").json()
    ok("clear chat empties the thread", len(msgs_after) == 0)


def test_conversation_isolation():
    section("Conversation isolation (transcripts don't leak across threads)")
    conv_a = new_conversation_id()
    conv_b = new_conversation_id()

    marker = f"the secret phrase is zebra-{uuid.uuid4().hex[:6]}"
    chat(conv_a, marker)
    chat(conv_b, "hello")

    msgs_b = httpx.get(f"{BACKEND}/api/messages/{conv_b}").json()
    leaked = any(marker in m["content"] for m in msgs_b)
    ok("conversation B's transcript never contains conversation A's messages", not leaked)

    r = httpx.get(f"{BACKEND}/api/conversations").json()
    ids = [c["conversation_id"] for c in r]
    ok("conversation list includes both threads", conv_a in ids and conv_b in ids)

    clear_chat(conv_a)
    clear_chat(conv_b)


def test_memory_capture_and_cross_conversation_recall():
    section("Memory capture + cross-conversation recall")
    reset_memory()
    conv_a = new_conversation_id()
    conv_b = new_conversation_id()

    r1 = chat(conv_a, "I'm a backend developer and I mostly work in Python.")
    ok("memory_write activity fired on a stated fact", "memory_write" in activity_kinds(r1))

    state = memory_state("main") + memory_state("work") + memory_state("personal")
    found = any("python" in u["content"].lower() for u in state)
    ok("fact actually landed in the memory store", found)

    # different conversation entirely — memory should still be visible,
    # since memory is global and not scoped to a conversation thread
    r2 = chat(conv_b, "What do you know about me?")
    ok(
        "a brand-new conversation still recalls memory from elsewhere",
        "python" in r2["text"].lower() or "backend" in r2["text"].lower(),
        r2["text"][:150],
    )
    ok("memory_read activity fired on recall", "memory_read" in activity_kinds(r2))

    clear_chat(conv_a)
    clear_chat(conv_b)


def test_branch_inference():
    section("Branch inference (per-fact domain routing)")
    reset_memory()
    conv = new_conversation_id()

    chat(conv, "I work at a company called Acme.")
    chat(conv, "I have a dog named Max.")

    work_state = memory_state("work")
    personal_state = memory_state("personal")

    ok(
        "work-flavored fact landed on the work branch",
        any("acme" in u["content"].lower() for u in work_state),
    )
    ok(
        "personal-flavored fact landed on the personal branch",
        any("max" in u["content"].lower() or "dog" in u["content"].lower() for u in personal_state),
    )
    ok(
        "work fact did NOT also land on personal",
        not any("acme" in u["content"].lower() for u in personal_state),
    )

    clear_chat(conv)


def test_conflict_detection_and_resolution():
    section("Conflict detection + resolution")
    reset_memory()
    conv = new_conversation_id()

    chat(conv, "I work mostly in Python.")
    r2 = chat(conv, "Actually, I work mostly in Go now.")

    conflicts = [a for a in r2["activity"] if a["kind"] == "conflict"]
    if not ok("a genuine contradiction is flagged as a conflict, not silently overwritten", len(conflicts) > 0):
        clear_chat(conv)
        return

    conflict_id = conflicts[0]["id"]
    res = httpx.post(
        f"{BACKEND}/api/memory/resolve",
        json={"conflict_id": conflict_id, "choice": "update", "conversation_id": conv},
        timeout=10.0,
    ).json()
    ok("conflict resolves successfully", res.get("ok") is True)

    state = memory_state("main") + memory_state("work") + memory_state("personal")
    has_go = any("go" in u["content"].lower() and "python" not in u["content"].lower() for u in state)
    ok("resolved fact reflects the update (Go), not the stale value", has_go)

    # confirms the resolution actually persisted onto the stored message —
    # the specific bug the redesign fixed (resolution surviving a reload/restart),
    # not just that the endpoint returned ok:true in the moment
    msgs = httpx.get(f"{BACKEND}/api/messages/{conv}").json()
    resolved_entry = None
    for m in msgs:
        for act in m.get("activity", []) or []:
            if act.get("kind") == "conflict" and act.get("id") == conflict_id:
                resolved_entry = act
    ok(
        "conflict's resolution status is persisted on the stored message, not just the live response",
        resolved_entry is not None and resolved_entry.get("resolved") == "update",
        f"found: {resolved_entry}",
    )

    # the real regression test: reload the same conversation fresh (as a page
    # refresh would) and confirm the resolved state survives, rather than
    # reverting to an unresolved/pending conflict
    msgs_reloaded = httpx.get(f"{BACKEND}/api/messages/{conv}").json()
    still_resolved = any(
        act.get("kind") == "conflict" and act.get("id") == conflict_id and act.get("resolved") == "update"
        for m in msgs_reloaded
        for act in (m.get("activity") or [])
    )
    ok("resolution survives a fresh reload of the conversation", still_resolved)

    clear_chat(conv)


def test_skills():
    section("Skills (selection + tool gating)")
    reset_memory()

    conv1 = new_conversation_id()
    r1 = chat(conv1, "Help me write a short, upbeat product announcement email.")
    ok("writing-flavored request triggers a skill", "skill" in activity_kinds(r1))
    ok(
        "writing skill does not trigger search (tools=[] in writing.toml)",
        "search" not in activity_kinds(r1) and "searching" not in activity_kinds(r1),
    )
    clear_chat(conv1)

    conv2 = new_conversation_id()
    r2 = chat(conv2, "What's 17 * 4?")
    ok("a plain arithmetic question triggers no skill at all", "skill" not in activity_kinds(r2))
    clear_chat(conv2)


def test_search_decision_and_pipeline():
    section("Search (decision gating + discovery/extraction/distillation)")
    try:
        httpx.get("http://localhost:8888/search", params={"q": "test", "format": "json"}, timeout=3.0)
    except Exception:
        skip("search pipeline", "SearXNG not reachable")
        return

    reset_memory()

    conv1 = new_conversation_id()
    r1 = chat(conv1, "Write me a haiku about autumn leaves.", timeout=30.0)
    ok(
        "a purely creative request does not trigger search",
        "searching" not in activity_kinds(r1) and "search" not in activity_kinds(r1),
    )
    clear_chat(conv1)

    conv2 = new_conversation_id()
    r2 = chat(conv2, "What's the latest version of the Rust programming language?", timeout=90.0)
    triggered = "searching" in activity_kinds(r2)
    ok("a current-info request triggers the search pipeline", triggered)

    if triggered:
        outcome = [a for a in r2["activity"] if a["kind"] in ("search", "search_failed")]
        ok("search pipeline resolves to a definite outcome (found results or explicitly failed)", len(outcome) == 1)
    clear_chat(conv2)

def test_read_not_domain_gated():
    section("Memory reads are not gated by domain classification (regression)")
    reset_memory()
    conv_b = new_conversation_id()

    # seed directly on the personal branch as a pinned type (identity/preference
    # bypass relevance scoring entirely) — isolates branch-scoping from both
    # capture's domain guess and BM25 relevance, neither of which this test
    # is meant to exercise
    httpx.post(f"{MEMORY}/remember", json={
        "content": "Has a dog named Max.", "unit_type": "identity", "provenance": "stated",
        "source": "test", "summary": "seed", "branch": "personal",
    }, timeout=10.0)

    # a work-flavored question, in a fresh conversation — should still recall
    # the personal-branch fact, since reads now scan every branch
    r = chat(conv_b, "I'm starting a new job at a tech company next week. What do you know about me?")

    read_events = [a for a in r["activity"] if a["kind"] == "memory_read"]
    recalled_content = " ".join(
        u["content"].lower() for ev in read_events for u in ev.get("units", [])
    )
    ok(
        "a personal-branch fact is recalled on a work-flavored turn",
        "max" in recalled_content or "dog" in recalled_content,
        recalled_content[:150],
    )

    clear_chat(conv_b)

def test_merge():
    section("Merge (primitives + semantic conflict detection)")
    reset_memory()

    r1 = httpx.post(f"{MEMORY}/remember", json={
        "content": "Works at Acme.", "unit_type": "identity", "provenance": "stated",
        "source": "test", "summary": "seed", "branch": "main",
    }, timeout=10.0).json()

    r2 = httpx.post(f"{MEMORY}/remember", json={
        "content": "Has a dog named Max.", "unit_type": "relationship", "provenance": "stated",
        "source": "test", "summary": "seed", "branch": "personal",
    }, timeout=10.0).json()

    preview = httpx.get(f"{BACKEND}/api/merge/preview",
                        params={"from_branch": "personal", "into_branch": "main"}, timeout=15.0).json()
    ok("merge preview finds the unmerged fact", len(preview["clean"]) >= 1)

    if preview["clean"]:
        apply_res = httpx.post(f"{BACKEND}/api/merge/apply", json={
            "from_branch": "personal", "into_branch": "main",
            "adopt": [u["hash"] for u in preview["clean"]],
            "replace": [], "summary": "test merge",
        }, timeout=10.0).json()
        ok("merge apply succeeds", apply_res.get("ok") is True)

        main_state = memory_state("main")
        ok("merged fact is now present on main", any("max" in u["content"].lower() for u in main_state))

    personal_state = memory_state("personal")
    ok("merge does not remove the fact from its source branch", any("max" in u["content"].lower() for u in personal_state))


def test_ledger():
    section("Ledger (audit trail)")
    entries = ledger(50)
    ok("ledger is populated after the tests above", len(entries) > 0)
    event_types = {e["event_type"] for e in entries}
    ok(
        "ledger captured a reasonable variety of event types this run",
        len(event_types) >= 3,
        f"saw: {event_types}",
    )


def test_graceful_degradation():
    section("Graceful degradation (memory engine unreachable mid-chat)")
    skip(
        "memory engine down mid-request",
        "requires manually stopping the memory engine — run this scenario by hand: "
        "stop `cargo run`, send a chat message, confirm it still answers without crashing, "
        "then restart the engine.",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    started = time.time()
    print("projectX integration test suite")
    print(f"backend={BACKEND}  memory={MEMORY}\n")

    tests = [
        test_infra,
        test_basic_chat,
        test_conversation_isolation,
        test_memory_capture_and_cross_conversation_recall,
        test_branch_inference,
        test_conflict_detection_and_resolution,
        test_skills,
        test_search_decision_and_pipeline,
        test_merge,
        test_ledger,
        test_graceful_degradation,
        test_read_not_domain_gated,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            results["fail"] += 1
            print(f"  \033[91m✗ {t.__name__} raised an exception: {e!r}\033[0m")

    elapsed = time.time() - started
    total = results["pass"] + results["fail"]
    print(f"\n{'=' * 50}")
    print(f"  {results['pass']}/{total} passed, {results['fail']} failed, {results['skip']} skipped  ({elapsed:.1f}s)")
    print(f"{'=' * 50}\n")

    sys.exit(1 if results["fail"] else 0)


if __name__ == "__main__":
    main()