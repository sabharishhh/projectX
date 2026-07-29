import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import ledger
import chatlog
import branching
import threading
import forgetting
import summarization
import agentic_search
import skills as skill_registry

import search_decision as search_decision_module
from capture import extract_units, commit_unit
from memory import fetch_state, fetch_relevant, fetch_branches, build_system_message
from db import load_messages, save_message, to_provider_messages, save_retrieval_trace
from state import provider, model, PENDING, PENDING_FORGETS, MAIN_REASONING_EFFORT


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _run_summarization(provider, conversation_id: str, history: list[dict], message: str, full_response: str):
    """Runs after the SSE stream has already closed — summarization has no
    live activity card, so deferring it changes nothing the user sees,
    only removes its LLM call (on the turns it actually fires) from the
    critical path the user waits through."""
    try:
        summarization.maybe_update_summary(
            provider, conversation_id,
            history + [{"role": "user", "content": message}, {"role": "assistant", "content": full_response}],
        )
    except Exception as e:
        # background task — must never surface as a crash the user sees;
        # worst case a summary update is silently skipped this turn
        chatlog.logger.warning(f"background summarization failed: {e!r}") if hasattr(chatlog, "logger") else None


def stream_chat(conversation_id: str, message: str):
    """Generator yielding SSE-formatted strings for one chat turn: memory
    injection, skill selection, optional search, the streamed reply, then
    capture (facts, conflicts, forget requests)."""
    history = load_messages(conversation_id)
    save_message(conversation_id, "user", message)

    # Skill-selection and search-decision are both independent LLM
    # classifications of the same message — neither reads the other's
    # output — so they run concurrently instead of one after another.
    # search_decision fires unconditionally here and gets discarded below
    # if the resolved skill turns out to disallow web_search (e.g. the
    # "writing" skill's deny-all tools list) — a small, occasional wasted
    # call traded for latency on every other turn.
    with ThreadPoolExecutor(max_workers=2) as pool:
        skill_future = pool.submit(skill_registry.select, provider, message)
        search_decision_future = pool.submit(search_decision_module.should_search, provider, message)
        skill = skill_future.result()
        search_decision = search_decision_future.result()

    if not skill_registry.allows(skill, "web_search"):
        search_decision = None

    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})

    # Always read across every branch — domain classification still decides
    # where a new fact gets *written* (capture routes work/personal/main per
    # fact), but it no longer gates what can be *read back*. A per-turn domain
    # guess was silently hiding whole categories of real, stored memory whenever
    # it guessed wrong or a question didn't clearly belong to one domain.
    # Retrieval scoring (relevance + recency + pinned set) now decides what's
    # worth injecting, instead of a folder-like filter deciding it first.
    # Each branch's fetch_state call is independent of the others, so they
    # fire concurrently rather than one after another — results are then
    # reassembled in allowed_branches order (not completion order) so
    # behavior stays deterministic regardless of which branch responds first.
    with ThreadPoolExecutor(max_workers=max(len(allowed_branches), 1)) as pool:
        state_futures = {b: pool.submit(fetch_state, b) for b in allowed_branches}
        known = [{**u, "branch": b} for b in allowed_branches for u in state_futures[b].result()]

    forget_matches = forgetting.detect_forget_request(provider, message, known, allowed_branches)

    # Same concurrency treatment for the relevance-scored fetch per branch.
    # Iterating the results in allowed_branches order afterward (not
    # completion order) matters here specifically: when the same hash
    # appears in more than one branch's results, `seen` lets only the
    # first-encountered one through, and "first" needs to mean "first in
    # allowed_branches order," not "whichever thread happened to finish
    # first" — otherwise which branch a duplicate gets credited to would
    # be nondeterministic between runs.
    seen, all_candidates = set(), []
    per_branch_debug = {}
    with ThreadPoolExecutor(max_workers=max(len(allowed_branches), 1)) as pool:
        relevant_futures = {
            b: pool.submit(
                fetch_relevant, message, branch=b, max_units=12,
                boost_types=(skill or {}).get("boost_types"),
            )
            for b in allowed_branches
        }
        for b in allowed_branches:
            results = relevant_futures[b].result()
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

    forget_context = None
    if forget_matches:
        matched = "; ".join(f'"{m["unit"]["content"]}"' for m in forget_matches)
        forget_context = {
            "role": "system",
            "content": (
                f"The user's message matches a stored fact you can forget: {matched}. "
                "A confirmation prompt will render below your reply — acknowledge this "
                "specifically and naturally. Do not say you're unable to forget or delete memory."
            ),
        }
    elif forgetting.mentions_forgetting(message):
        forget_context = {
            "role": "system",
            "content": (
                "The user's message sounds like a request to forget something, but no "
                "confident match was found among stored facts — either it's already been "
                "forgotten, or the reference isn't clear. Do NOT claim a confirmation prompt "
                "will appear, since none will. Say you couldn't find a matching stored fact, "
                "or ask them to clarify."
            ),
        }

    conversation = [build_system_message(injected, (skill or {}).get("system_prompt"))] \
        + ([{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] if summary else []) \
        + ([forget_context] if forget_context else []) \
        + to_provider_messages(visible_history) \
        + [{"role": "user", "content": message}]

    ledger.log("provider_call", f"model={model}", conversation_id, actor="user")
    if skill:
        ledger.log("skill_invoked", f"{skill['name']}: {message[:60]}", conversation_id, actor="system")

    activity_log = []

    if skill:
        ev = {"kind": "skill", "label": f"{skill['name']}ing"}
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

    # Every branch now converges on agentic_search — there's no separate
    # fixed pipeline to route between anymore. web_search/web_fetch are
    # available whenever search_decision found a real need; memory_search
    # is available whenever the skill allows it, independent of that.
    memory_allowed = skill_registry.allows(skill, "memory_search")
    web_needed = search_decision is not None and skill_registry.allows(skill, "web_fetch")

    allowed_tools = set()
    if memory_allowed:
        allowed_tools.add("memory_search")
    if web_needed:
        allowed_tools.update({"web_search", "web_fetch"})

    use_agentic = provider.supports_tools and bool(allowed_tools)

    full_response = ""

    if use_agentic:
        try:
            for event in agentic_search.run(provider, model, conversation,
                                             reasoning_effort=MAIN_REASONING_EFFORT,
                                             allowed_tools=allowed_tools):
                if event["type"] == "text":
                    full_response += event["value"]
                yield _sse(event)
                if event["type"] == "activity":
                    activity_log.append(event["event"])
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return
    else:
        # Reached only when the provider can't do tool calling at all (or
        # no tools are applicable this turn) — a search need with no way
        # to act on it agentic-ly. Surface that plainly rather than
        # silently answering as if no search was needed.
        if search_decision:
            ev = {"kind": "search_failed", "label": f"Couldn't search — no tool-calling support available: {search_decision['query']}"}
            activity_log.append(ev)
            yield _sse({"type": "activity", "event": ev})
            ledger.log("search_call", f"{search_decision['query']} (0 pages read — no tool support)",
                       conversation_id, actor="system")

        try:
            for chunk in provider.stream(conversation, model, reasoning_effort=MAIN_REASONING_EFFORT):
                full_response += chunk
                yield _sse({"type": "text", "value": chunk})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return

    # Forget requests are detected BEFORE capture now, not after. Capture has
    # no way to honor its own "don't create a unit describing a forget
    # request" rule if it runs first without knowing this message is one —
    # that's exactly what produced a bogus "user wants X forgotten" memory
    # unit in testing. Skipping capture entirely on a forget-request turn is
    # the deterministic fix; relying on the model to self-censor was not.
    units = [] if forget_matches else extract_units(provider, message, full_response, known, allowed_branches)
    added, conflicts = [], []

    for u in units:
        if any(k["content"] == u["content"] for k in known):
            activity_log.append({"kind": "duplicate_skipped", "content": u["content"]})
            continue  # verbatim duplicate of something already known — not a
                    # conflict (nothing changed) and not a new fact (already
                    # have it) — no-op either way
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

    # forget_matches was already computed above, before capture ran — reused
    # here, not recomputed. conflicted_hashes still guards against
    # double-prompting when a message both matches a forget AND capture
    # flagged a conflict on a different, unrelated fact in the same turn.
    conflicted_hashes = {c["old"]["hash"] for c in conflicts}
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

    chatlog.log_turn(conversation_id, message, skill, injected, activity_log, full_response)
    yield _sse({"type": "done"})

    # Deferred until after "done" — summarization has no live activity card
    # (maybe_update_summary never yields one), so nothing the user sees
    # depends on this finishing before the stream closes. It only fires on
    # turns where enough messages have aged past the visible window
    # (TRIGGER_BUFFER), so this is a no-op most turns; on the turns it does
    # fire, this removes a full extra LLM call from the user's wait time.
    # Fire-and-forget from a plain sync generator (no asyncio.create_task
    # available here) — a daemon thread, since the request/response cycle
    # is already fully done by this point and nothing needs to join it.
    threading.Thread(
        target=_run_summarization,
        args=(provider, conversation_id, history, message, full_response),
        daemon=True,
    ).start()