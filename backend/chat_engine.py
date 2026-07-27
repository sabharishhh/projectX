import json
from uuid import uuid4

import ledger
import research
import branching
import forgetting
import summarization
import agentic_search
import skills as skill_registry

from capture import extract_units, commit_unit
from memory import fetch_state, fetch_relevant, fetch_branches, build_system_message
from db import load_messages, save_message, to_provider_messages, save_retrieval_trace
from state import provider, model, PENDING, PENDING_FORGETS, MAIN_REASONING_EFFORT


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def stream_chat(conversation_id: str, message: str):
    """Generator yielding SSE-formatted strings for one chat turn: memory
    injection, skill selection, optional search, the streamed reply, then
    capture (facts, conflicts, forget requests)."""
    history = load_messages(conversation_id)
    save_message(conversation_id, "user", message)

    skill = skill_registry.select(provider, message)

    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})

    # Always read across every branch — domain classification still decides
    # where a new fact gets *written* (capture routes work/personal/main per
    # fact), but it no longer gates what can be *read back*. A per-turn domain
    # guess was silently hiding whole categories of real, stored memory whenever
    # it guessed wrong or a question didn't clearly belong to one domain.
    # Retrieval scoring (relevance + recency + pinned set) now decides what's
    # worth injecting, instead of a folder-like filter deciding it first.
    known = [{**u, "branch": b} for b in allowed_branches for u in fetch_state(b)]

    seen, all_candidates = set(), []
    per_branch_debug = {}
    for b in allowed_branches:
        results = fetch_relevant(
            message, branch=b, max_units=12,
            boost_types=(skill or {}).get("boost_types"),
        )
        per_branch_debug[b] = [
            {"hash": u["hash"][:8], "content": u["content"], "score": u.get("score")}
            for u in results
        ]
        for u in results:
            if u["hash"] not in seen:
                seen.add(u["hash"])
                all_candidates.append({**u, "branch": b})

    all_candidates.sort(key=lambda u: u["score"], reverse=True)
    injected = all_candidates[:12]

    save_retrieval_trace(conversation_id, message, {
        "allowed_branches": allowed_branches,
        "per_branch": per_branch_debug,
        "merged_top12": [
            {"hash": u["hash"][:8], "content": u["content"], "score": u["score"], "branch": u["branch"]}
            for u in injected
        ],
    })

    # Windowed history + rolling summary, replacing full unwindowed history.
    # `skill` and `injected` are both resolved by this point.
    visible_history = history[-summarization.WINDOW_MESSAGES:]
    summary = summarization.get_current_summary(conversation_id)

    conversation = [build_system_message(injected, (skill or {}).get("system_prompt"))] \
        + ([{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] if summary else []) \
        + to_provider_messages(visible_history) \
        + [{"role": "user", "content": message}]

    ledger.log("provider_call", f"model={model}", conversation_id, actor="user")
    if skill:
        ledger.log("skill_invoked", f"{skill['name']}: {message[:60]}", conversation_id, actor="system")

    activity_log = []

    if skill:
        ev = {"kind": "skill", "label": f"Using {skill['name']} skill"}
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    if injected:
        ev = {
            "kind": "memory_read",
            "label": f"Recalled {len(injected)} {'fact' if len(injected) == 1 else 'facts'}",
            "units": injected,
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    # research-skill turns on a tool-calling-capable provider get the agentic
    # web_search/web_fetch loop (agentic_search.py, via the local MCP server).
    # Everything else — other skills, no skill, or a provider without tool
    # support (e.g. local models) — keeps the original fixed pipeline below.
    use_agentic = (
        skill and skill["name"] == "research"
        and skill_registry.allows(skill, "web_fetch")
        and provider.supports_tools
    )

    full_response = ""

    if use_agentic:
        try:
            for event in agentic_search.run(provider, model, conversation, reasoning_effort=MAIN_REASONING_EFFORT):
                if event["type"] == "text":
                    full_response += event["value"]
                yield _sse(event)
                if event["type"] == "activity":
                    activity_log.append(event["event"])
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return
    else:
        search_query = None
        if skill_registry.allows(skill, "web_search"):
            search_query = research.should_search(provider, message)

        if search_query:
            yield _sse({"type": "activity", "event": {"kind": "searching", "label": f"Searching: {search_query}"}})
            distilled = research.research(provider, search_query)
            if distilled:
                ev = {
                    "kind": "search",
                    "label": f"Read {len(distilled)} page{'s' if len(distilled) != 1 else ''}: {search_query}",
                    "results": distilled,
                }
                activity_log.append(ev)
                yield _sse({"type": "activity", "event": ev})
                conversation.append({
                    "role": "system",
                    "content": research.format_for_context(search_query, distilled),
                })
                ledger.log("search_call", f"{search_query} ({len(distilled)} pages read)",
                           conversation_id, actor="system")
            else:
                ev = {"kind": "search_failed", "label": f"Searched, but couldn't read any results: {search_query}"}
                activity_log.append(ev)
                yield _sse({"type": "activity", "event": ev})
                ledger.log("search_call", f"{search_query} (0 pages read — extraction failed)",
                           conversation_id, actor="system")

        try:
            for chunk in provider.stream(conversation, model, reasoning_effort=MAIN_REASONING_EFFORT):
                full_response += chunk
                yield _sse({"type": "text", "value": chunk})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return

    units = extract_units(provider, message, full_response, known, allowed_branches)
    added, conflicts = [], []

    for u in units:
        short = u.get("supersedes")
        target = next((k for k in known if k["hash"].startswith(short)), None) if short else None
        branch = u.get("branch", "main")

        if target:
            cid = uuid4().hex[:12]
            PENDING[cid] = {
                "from": target["hash"],
                "unit": u,
                "source": conversation_id,
                "branch": target["branch"],  # supersede lands on the target's own branch
            }
            conflicts.append({"id": cid, "old": target, "new": u})
            ledger.log("conflict_raised",
                       f"'{u['content']}' conflicts with '{target['content']}'",
                       conversation_id, actor="system")
        elif commit_unit(u, conversation_id, branch):
            added.append(u)
            ledger.log("memory_commit", f"added to {branch}: {u['content']}", conversation_id, actor="system")

    if added:
        ev = {
            "kind": "memory_write",
            "label": f"Remembered {len(added)} {'thing' if len(added) == 1 else 'things'}",
            "units": added,
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    for c in conflicts:
        ev = {
            "kind": "conflict",
            "label": "This changes something I already knew",
            "id": c["id"],
            "old": c["old"],
            "new": c["new"],
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    # Explicit forget requests — checked after capture/conflicts, and
    # deliberately skips any unit capture already flagged as a conflict.
    # Without this, a message like "I don't use vim anymore, I use emacs"
    # could get interpreted BOTH as a contradiction (by capture) and as
    # an implicit forget (by forget-detection) — surfacing two separate
    # prompts asking the user to resolve the same underlying fact twice.
    conflicted_hashes = {c["old"]["hash"] for c in conflicts}
    forget_matches = forgetting.detect_forget_request(provider, message, known)
    for m in forget_matches:
        if m["unit"]["hash"] in conflicted_hashes:
            continue  # capture already surfaced this as a conflict — don't ask twice
        fid = uuid4().hex[:12]
        PENDING_FORGETS[fid] = {
            "hash": m["unit"]["hash"],
            "content": m["unit"]["content"],
            "branch": m["unit"]["branch"],
            "source": conversation_id,
        }
        ev = {
            "kind": "forget_request",
            "label": "Forget this?",
            "id": fid,
            "content": m["unit"]["content"],
            "reason": m["reason"],
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})
        ledger.log("forget_requested", f"candidate: {m['unit']['content']}", conversation_id, actor="system")

    persisted_activity = [a for a in activity_log if a["kind"] != "skill"]
    save_message(conversation_id, "assistant", full_response, persisted_activity)

    # Fold aged-out messages into the rolling summary, now that this turn's
    # user message and full reply both exist. No-ops cheaply unless enough
    # new messages have crossed the visible-window boundary.
    summarization.maybe_update_summary(
        provider, conversation_id,
        history + [{"role": "user", "content": message}, {"role": "assistant", "content": full_response}],
    )

    yield _sse({"type": "done"})