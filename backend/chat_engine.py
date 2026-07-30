import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import ledger
import chatlog
import branching
import threading
import forgetting
import time_travel
import summarization
import agentic_search
import skills as skill_registry

import search_decision as search_decision_module
from capture import (
    extract_units, commit_unit, find_open_commitments,
    find_due_commitments, detect_commitment_resolutions, resolve_commitment,
)
from memory import fetch_state, fetch_relevant, fetch_branches, build_system_message, fetch_state_at_time
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
        chatlog.logger.warning(f"background summarization failed: {e!r}") if hasattr(chatlog, "logger") else None


# --- Phase: classification ---

def _classify(message: str) -> tuple[dict | None, dict | None]:
    """Skill-selection and search-decision are both independent LLM
    classifications of the same message — neither reads the other's
    output — so they run concurrently instead of one after another.
    search_decision fires unconditionally and gets discarded here if the
    resolved skill turns out to disallow web_search. Both futures are
    read defensively — if either classifier's own internal retry/error
    handling is ever exhausted (a real, observed failure, not
    theoretical), that must degrade this turn to "no skill, no search"
    rather than crash the entire turn with an unhandled exception."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        skill_future = pool.submit(skill_registry.select, provider, message)
        search_decision_future = pool.submit(search_decision_module.should_search, provider, message)

        try:
            skill = skill_future.result()
        except Exception as e:
            ledger.log("classify_failed", f"skill selection failed: {e!r}", "system", actor="system")
            skill = None

        try:
            search_decision = search_decision_future.result()
        except Exception as e:
            ledger.log("classify_failed", f"search decision failed: {e!r}", "system", actor="system")
            search_decision = None

    if not skill_registry.allows(skill, "web_search"):
        search_decision = None

    return skill, search_decision


# --- Phase: memory gathering ---

def _fetch_known(allowed_branches: list[str]) -> list[dict]:
    """Always read across every branch — domain classification still
    decides where a new fact gets *written*, but no longer gates what can
    be *read back*. Each branch's fetch_state call is independent, so
    they fire concurrently — results are reassembled in allowed_branches
    order (not completion order) so behavior stays deterministic
    regardless of which branch responds first."""
    with ThreadPoolExecutor(max_workers=max(len(allowed_branches), 1)) as pool:
        state_futures = {b: pool.submit(fetch_state, b) for b in allowed_branches}
        return [{**u, "branch": b} for b in allowed_branches for u in state_futures[b].result()]


def _fetch_relevant(message: str, skill: dict | None, allowed_branches: list[str]) -> tuple[list[dict], dict]:
    """Same concurrency treatment as _fetch_known. Iterating results in
    allowed_branches order afterward (not completion order) matters
    specifically for the dedup: when the same hash appears in more than
    one branch's results, `seen` lets only the first-encountered one
    through, and "first" needs to mean "first in allowed_branches order,"
    not "whichever thread finished first" — otherwise which branch a
    duplicate gets credited to would be nondeterministic between runs."""
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
    return all_candidates[:12], per_branch_debug


def _fetch_due_commitments(allowed_branches: list[str]) -> list[dict]:
    """Deterministic, no LLM — every currently-open commitment across
    allowed branches whose deadline falls within the surfacing window
    (find_due_commitments' default). Same per-branch concurrency pattern
    as _fetch_known/_fetch_relevant. This is the "what's coming up"
    surfacing side of the feature — distinct from find_open_commitments,
    which ignores deadline entirely and is only used for resolution-
    matching in _process_commitment_resolutions below."""
    with ThreadPoolExecutor(max_workers=max(len(allowed_branches), 1)) as pool:
        futures = {b: pool.submit(find_due_commitments, b) for b in allowed_branches}
        return [{**u, "branch": b} for b in allowed_branches for u in futures[b].result()]


# --- Phase: conversation assembly ---

def _build_forget_context(forget_matches: list[dict], message: str) -> dict | None:
    if forget_matches:
        matched = "; ".join(f'"{m["unit"]["content"]}"' for m in forget_matches)
        return {
            "role": "system",
            "content": (
                f"The user's message matches a stored fact you can forget: {matched}. "
                "A confirmation prompt will render below your reply — acknowledge this "
                "specifically and naturally. Do not say you're unable to forget or delete memory."
            ),
        }
    if forgetting.mentions_forgetting(message):
        return {
            "role": "system",
            "content": (
                "The user's message sounds like a request to forget something, but no "
                "confident match was found among stored facts — either it's already been "
                "forgotten, or the reference isn't clear. Do NOT claim a confirmation prompt "
                "will appear, since none will. Say you couldn't find a matching stored fact, "
                "or ask them to clarify."
            ),
        }
    return None


def _build_commitment_context(due_commitments: list[dict]) -> dict | None:
    """Injects due-soon open commitments as a system-stated fact the model
    can naturally weave in — never a mandate to mention every one, and
    never something the model has to independently judge is true, since
    the deterministic due-check already established that."""
    if not due_commitments:
        return None
    lines = "; ".join(
        f'"{c["content"]}"' + (f' (due {c["deadline"]})' if c.get("deadline") else "")
        for c in due_commitments
    )
    return {
        "role": "system",
        "content": (
            f"The user has open commitments coming due soon: {lines}. If one is "
            "naturally relevant to this exchange, you may mention it — don't force "
            "it into an unrelated conversation, and don't recite the whole list "
            "mechanically."
        ),
    }


def _build_conversation(conversation_id: str, message: str, skill: dict | None,
                         injected: list[dict], forget_matches: list[dict],
                         due_commitments: list[dict], history: list[dict]) -> list[dict]:
    """Windowed history + rolling summary, replacing full unwindowed history."""
    visible_history = history[-summarization.WINDOW_MESSAGES:]
    summary = summarization.get_current_summary(conversation_id)
    forget_context = _build_forget_context(forget_matches, message)
    commitment_context = _build_commitment_context(due_commitments)

    return [build_system_message(injected, (skill or {}).get("system_prompt"))] \
        + ([{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] if summary else []) \
        + ([forget_context] if forget_context else []) \
        + ([commitment_context] if commitment_context else []) \
        + to_provider_messages(visible_history) \
        + [{"role": "user", "content": message}]


# --- Phase: reply generation ---

def _generate_reply(conversation_id: str, conversation: list[dict], skill: dict | None,
                     search_decision: dict | None, activity_log: list[dict]):
    """Every branch converges on agentic_search — no separate fixed
    pipeline to route between. web_search/web_fetch are available
    whenever search_decision found a real need; memory_search is
    available whenever the skill allows it, independent of that.

    Yields the same SSE-ready dicts stream_chat already streams; mutates
    activity_log in place, same convention every phase here uses.

    Returns (full_response, errored) via the generator's return value.
    errored=True means an error was already yielded and the caller must
    stop the turn immediately — matching the original behavior exactly:
    on a reply-generation error, capture/conflict/forget/persistence/done
    are all skipped, not just the reply itself."""
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
            return full_response, True
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
            return full_response, True

    return full_response, False


# --- Phase: capture (facts + conflicts) ---

def _process_capture(conversation_id: str, message: str, full_response: str,
                      known: list[dict], allowed_branches: list[str],
                      forget_matches: list[dict], activity_log: list[dict]):
    """Forget requests are detected BEFORE this runs, not after — capture
    can't honor its own "don't create a unit describing a forget request"
    rule if it runs first without knowing this message is one. Skipping
    capture entirely on a forget-matched turn is the deterministic fix;
    relying on the model to self-censor was not.

    Yields memory_write/conflict SSE activity events, mutates
    activity_log. Returns the conflicts list — the caller needs it to
    build conflicted_hashes for the forget-processing phase after this.

    New commitments are captured here through the same path as any other
    fact — extract_units/commit_unit already carry deadline/
    commitment_status through unchanged, nothing commitment-specific
    needed in this function itself."""
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

    return conflicts


# --- Phase: forget-request surfacing ---

def _process_forgets(conversation_id: str, forget_matches: list[dict],
                      conflicts: list[dict], activity_log: list[dict]):
    """forget_matches was already computed earlier, before capture ran —
    reused here, not recomputed. conflicted_hashes guards against
    double-prompting when a message both matches a forget AND capture
    flagged a conflict on a different, unrelated fact in the same turn."""
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


# --- Phase: commitment resolution ---

def _process_commitment_resolutions(conversation_id: str, message: str, full_response: str,
                                     allowed_branches: list[str], activity_log: list[dict]):
    """Deterministic candidate-gathering (every currently-open commitment
    across allowed branches, regardless of deadline) followed by one
    bounded LLM judgment over that pre-narrowed set — mirrors the
    forget-pipeline's pattern-then-confirm shape exactly. Skips the LLM
    call entirely, at zero cost, when there's nothing open to resolve.
    Yields commitment_resolved activity events, mutates activity_log."""
    open_commitments = []
    for b in allowed_branches:
        open_commitments.extend({**u, "branch": b} for u in find_open_commitments(b))

    if not open_commitments:
        return

    resolutions = detect_commitment_resolutions(provider, message, full_response, open_commitments)
    for r in resolutions:
        branch = r["unit"].get("branch", "main")
        if resolve_commitment(r, conversation_id, branch):
            ev = {
                "kind": "commitment_resolved",
                "label": f"{r['status'].capitalize()}: {r['unit']['content']}",
                "content": r["unit"]["content"],
                "status": r["status"],
            }
            activity_log.append(ev)
            yield _sse({"type": "activity", "event": ev})
            ledger.log("commitment_resolved", f"{r['status']}: {r['unit']['content']}",
                       conversation_id, actor="system")


# --- Orchestration ---

def stream_chat(conversation_id: str, message: str):
    """Generator yielding SSE-formatted strings for one chat turn: memory
    injection, skill selection, optional search, the streamed reply, then
    capture (facts, conflicts, forget requests, commitment resolutions).
    Each phase above is a focused function; this orchestrator sequences
    them and owns the state that carries between phases."""
    history = load_messages(conversation_id)
    save_message(conversation_id, "user", message)

    skill, search_decision = _classify(message)

    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})

    time_travel_target = time_travel.detect_time_travel_query(provider, message)

    known = _fetch_known(allowed_branches)
    forget_matches = forgetting.detect_forget_request(provider, message, known, allowed_branches)
    due_commitments = _fetch_due_commitments(allowed_branches)

    if time_travel_target:
        tt_results = [fetch_state_at_time(b, time_travel_target) for b in allowed_branches]
        tt_units = [u for r in tt_results for u in r["units"]]
        resolved_dates = [r["resolved_at"] for r in tt_results if r["resolved_at"]]
        injected = tt_units[:12]
        per_branch_debug = {}  # historical path doesn't populate the normal retrieval trace
    else:
        injected, per_branch_debug = _fetch_relevant(message, skill, allowed_branches)

    save_retrieval_trace(conversation_id, message, {
        "allowed_branches": allowed_branches,
        "per_branch": per_branch_debug,
        "merged_top12": [
            {"hash": u["hash"][:8], "content": u["content"], "score": u["score"], "branch": u["branch"]}
            for u in injected
        ],
    })

    conversation = _build_conversation(conversation_id, message, skill, injected, forget_matches, due_commitments, history)

    ledger.log("provider_call", f"model={model}", conversation_id, actor="user")
    if skill:
        ledger.log("skill_invoked", f"{skill['name']}: {message[:60]}", conversation_id, actor="system")

    activity_log = []

    if skill:
        ev = {"kind": "skill", "label": f"{skill['name']}ing"}
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    if time_travel_target:
        actual_date = min(resolved_dates) if resolved_dates else time_travel_target
        ev = {
            "kind": "time_travel",
            "label": f"Looking back to {actual_date}",
            "units": injected,
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})
    elif injected:
        ev = {
            "kind": "memory_read",
            "label": f"Recalled {len(injected)} {'fact' if len(injected) == 1 else 'facts'}",
            "units": injected,
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    if due_commitments:
        ev = {
            "kind": "commitments_due",
            "label": f"{len(due_commitments)} commitment{'s' if len(due_commitments) != 1 else ''} coming due",
            "units": due_commitments,
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    full_response, errored = yield from _generate_reply(
        conversation_id, conversation, skill, search_decision, activity_log,
    )
    if errored:
        return

    conflicts = yield from _process_capture(
        conversation_id, message, full_response, known, allowed_branches, forget_matches, activity_log,
    )
    yield from _process_forgets(conversation_id, forget_matches, conflicts, activity_log)
    yield from _process_commitment_resolutions(
        conversation_id, message, full_response, allowed_branches, activity_log,
    )

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