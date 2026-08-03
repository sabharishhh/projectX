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
    extract_units, commit_unit, is_semantic_duplicate, find_open_commitments,
    find_due_commitments, detect_commitment_resolutions, resolve_commitment,
    check_correction_compliance, fetch_known_entities,
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
    if due_commitments:
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
    return {
        "role": "system",
        "content": "There are currently NO open commitments tracked for this user — "
                   "if asked about commitments, tasks, or reminders, say so plainly. "
                   "This is the current, authoritative state, overriding anything "
                   "said earlier in this conversation.",
    }

def _build_correction_context(active_corrections: list[dict]) -> dict | None:
    """Stated explicitly, up front — not because the check downstream
    can't catch a violation on its own, but because telling the model
    directly is what makes the check rarely need to fire at all. The
    check is the guarantee; this is what keeps the guarantee cheap."""
    if not active_corrections:
        return None
    lines = "\n".join(f"- {c['content']}" for c in active_corrections)
    return {
        "role": "system",
        "content": f"You have standing behavioral corrections that MUST be followed "
                   f"in this reply, without exception:\n{lines}",
    }

def _build_conversation(conversation_id: str, message: str, skill: dict | None,
                         injected: list[dict], forget_matches: list[dict],
                         due_commitments: list[dict], history: list[dict],
                         active_corrections: list[dict]) -> list[dict]:
    """Windowed history + rolling summary, replacing full unwindowed history."""
    visible_history = history[-summarization.WINDOW_MESSAGES:]
    summary = summarization.get_current_summary(conversation_id)
    forget_context = _build_forget_context(forget_matches, message)
    commitment_context = _build_commitment_context(due_commitments)

    correction_context = _build_correction_context(active_corrections)

    return [build_system_message(injected, (skill or {}).get("system_prompt"))] \
        + ([{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] if summary else []) \
        + ([forget_context] if forget_context else []) \
        + ([commitment_context] if commitment_context else []) \
        + ([correction_context] if correction_context else []) \
        + to_provider_messages(visible_history) \
        + [{"role": "user", "content": message}]


# --- Phase: reply generation ---

def _generate_reply(conversation_id: str, conversation: list[dict], skill: dict | None,
                     search_decision: dict | None, activity_log: list[dict]):
    """... (docstring unchanged) ...
    Yields RAW event dicts now, not pre-serialized SSE strings — the
    caller (_generate_reply_gated) needs to inspect event types to know
    what to buffer versus forward live. SSE-wrapping now happens exactly
    once, at that boundary, not scattered across this function too."""
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
                yield event
                if event["type"] == "activity":
                    activity_log.append(event["event"])
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return full_response, True
    else:
        if search_decision:
            ev = {"kind": "search_failed", "label": f"Couldn't search — no tool-calling support available: {search_decision['query']}"}
            activity_log.append(ev)
            yield {"type": "activity", "event": ev}
            ledger.log("search_call", f"{search_decision['query']} (0 pages read — no tool support)",
                       conversation_id, actor="system")

        try:
            for chunk in provider.stream(conversation, model, reasoning_effort=MAIN_REASONING_EFFORT):
                full_response += chunk
                yield {"type": "text", "value": chunk}
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return full_response, True

    return full_response, False

def _generate_reply_gated(conversation_id: str, conversation: list[dict], skill: dict | None,
                           search_decision: dict | None, activity_log: list[dict],
                           active_corrections: list[dict]):
    """The only function stream_chat calls for reply generation now.

    When active_corrections is empty (the common case), this is a thin
    pass-through — re-wraps _generate_reply's raw dicts as SSE and
    forwards them, byte-for-byte the same behavior as calling
    _generate_reply directly. Zero added latency, zero behavior change.

    When corrections are active: text is buffered instead of streamed
    live; activity events (search/tool steps) still pass through live,
    so the wait is never blank. Once generation completes, the buffered
    reply is checked exactly once. Compliant -> released as one text
    event, marked for simulated reveal on the frontend. Violated -> one
    corrective regeneration pass, informed of exactly what was wrong —
    the flawed first draft is never shown; only the corrected version
    ever reaches the client."""
    gen = _generate_reply(conversation_id, conversation, skill, search_decision, activity_log)

    if not active_corrections:
        while True:
            try:
                event = next(gen)
            except StopIteration as stop:
                return stop.value
            yield _sse(event)

    buffered_text = []
    full_response, errored = "", False
    while True:
        try:
            event = next(gen)
        except StopIteration as stop:
            full_response, errored = stop.value
            break
        if event["type"] == "text":
            buffered_text.append(event["value"])
        elif event["type"] == "error":
            yield _sse(event)
            return "".join(buffered_text), True
        else:
            yield _sse(event)

    if errored:
        return full_response, True

    check = check_correction_compliance(provider, active_corrections, full_response)
    if check.get("compliant", True):
        yield _sse({"type": "text", "value": full_response, "reveal": "simulated"})
        return full_response, False

    guidance = check.get("guidance") or "Revise to follow the standing corrections exactly."
    corrective_conversation = conversation + [
        {"role": "assistant", "content": full_response},
        {"role": "system", "content": f"That reply violated a standing correction: {guidance} "
                                        "Regenerate a corrected reply from scratch — don't reference "
                                        "or apologize for the previous draft, the user never saw it."},
    ]
    try:
        corrected = "".join(provider.stream(corrective_conversation, model, reasoning_effort=MAIN_REASONING_EFFORT))
    except Exception as e:
        # Regeneration itself failed — serve the original imperfect draft
        # rather than give the user nothing at all.
        ledger.log("correction_regen_failed", f"{e!r} — serving original draft", conversation_id, actor="system")
        yield _sse({"type": "text", "value": full_response, "reveal": "simulated"})
        return full_response, False

    yield _sse({"type": "text", "value": corrected, "reveal": "simulated"})
    ledger.log("correction_enforced", f"guidance={guidance}", conversation_id, actor="system")
    return corrected, False

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
    known_entities = [] if forget_matches else fetch_known_entities()
    units = [] if forget_matches else extract_units(provider, message, full_response, known, allowed_branches, known_entities)
    added, conflicts = [], []
    added, conflicts = [], []

    for u in units:
        if any(k["content"] == u["content"] for k in known):
            activity_log.append({"kind": "duplicate_skipped", "content": u["content"]})
            continue  # verbatim duplicate of something already known — not a
                    # conflict (nothing changed) and not a new fact (already
                    # have it) — no-op either way

        short = u.get("supersedes")
        branch = u.get("branch", "main")

        if not short and is_semantic_duplicate(u, branch):
            activity_log.append({"kind": "duplicate_skipped", "content": u["content"]})
            continue  # fuzzy backstop — catches rephrasings CAPTURE_PROMPT's own
                    # judgment missed; explicit supersedes always bypasses this,
                    # since that's a deliberate replacement, not a duplicate

        target = next((k for k in known if k["hash"].startswith(short)), None) if short else None

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
    active_corrections = [u for u in known if u.get("unit_type") == "correction"]
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

    conversation = _build_conversation(conversation_id, message, skill, injected, forget_matches, due_commitments, history, active_corrections)

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

    if active_corrections:
        ev = {"kind": "correction_check",
              "label": f"Checking against {len(active_corrections)} standing correction{'s' if len(active_corrections) != 1 else ''}..."}
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})

    full_response, errored = yield from _generate_reply_gated(
        conversation_id, conversation, skill, search_decision, activity_log, active_corrections,
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