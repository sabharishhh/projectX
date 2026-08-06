import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import time
import ledger
import logging
import chatlog
import branching
import threading
import forgetting
import time_travel
import summarization
import agentic_search
import skills as skill_registry
from pipeline import Stage, Pipeline

import search_decision as search_decision_module
from capture import (
    extract_units, commit_unit, is_semantic_duplicate, find_open_commitments,
    find_due_commitments, detect_commitment_resolutions,
    check_correction_compliance, check_reply_sufficiency, fetch_known_entities,
)
from memory import fetch_state, fetch_relevant, fetch_branches, build_system_message, fetch_state_at_time
from db import load_messages, save_message, update_message_activity, to_provider_messages, save_retrieval_trace, search_messages
from state import provider, model, PENDING, PENDING_FORGETS, PENDING_COMMITMENT_RESOLUTIONS, MAIN_REASONING_EFFORT


logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("chat_engine")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stage_summarize(ctx: dict):
    """Runs after the SSE stream has already closed — summarization has no
    live activity card, so nothing the user sees depends on this
    finishing before the stream ends. Only fires on turns where enough
    messages have aged past the visible window (TRIGGER_BUFFER), so this
    is a no-op most turns; on the turns it does fire, running it as a
    background stage removes a full extra LLM call from the user's wait
    time. on_fail='open' — a failed summary update just means the next
    trigger point re-attempts it; it's not a correctness issue like a
    dropped memory write would be."""
    summarization.maybe_update_summary(
        provider, ctx["conversation_id"],
        ctx["history"] + [
            {"role": "user", "content": ctx["message"]},
            {"role": "assistant", "content": ctx["full_response"]},
        ],
    )


def _stage_skill_select(ctx):
    try:
        return skill_registry.select(provider, ctx["message"])
    except Exception as e:
        ledger.log("classify_failed", f"skill selection failed: {e!r}", "system", actor="system")
        return None

def _stage_search_decision(ctx):
    try:
        return search_decision_module.should_search(provider, ctx["message"])
    except Exception as e:
        ledger.log("classify_failed", f"search decision failed: {e!r}", "system", actor="system")
        return None

_classify_pipeline = Pipeline([
    Stage("skill_select", deps=[], on_fail="open", fn=_stage_skill_select),
    Stage("search_decision", deps=[], on_fail="open", fn=_stage_search_decision),
])

# Reused across every stream_chat call — a single long-lived pipeline for
# post-response background work, not one created per turn. This also means
# post_response._background naturally tracks every summarization job
# currently in flight across the whole app, which a bare
# threading.Thread(daemon=True) per call had no way to expose.
post_response = Pipeline([
    Stage("summarize", deps=[], mode="background", on_fail="open", fn=_stage_summarize),
])


# --- Phase: classification ---

def _classify(message: str) -> tuple[dict | None, dict | None]:
    """Skill-selection and search-decision are both independent LLM
    classifications of the same message — neither reads the other's
    output — so they run concurrently. Now two declared Stages instead of
    a hand-nested ThreadPoolExecutor; Pipeline derives the same
    concurrency from both having deps=[]. Each stage's own try/except is
    kept (not delegated to Pipeline's generic on_fail handling) so the
    exact same ledger.log('classify_failed', ...) call still fires on
    failure — that's a user-visible audit trail via /api/ledger, not
    just a debug log, and needed to survive the migration unchanged."""
    context = _classify_pipeline.run({"message": message})
    skill = context["skill_select"]
    search_decision = context["search_decision"]

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

def _gather_branches_known_commitments() -> tuple[list[str], list[dict], list[dict]]:
    """Bundles the branch-list fetch (fast, deterministic) with the two
    downstream fetches that depend on it (known facts, due commitments).
    Submitted as a single future from stream_chat's top-level gather wave
    so this whole chain runs concurrently with the independent
    classifiers (skill, search-decision, time-travel) instead of after
    them — this group and the classifiers share no dependency on each
    other, only on `message` (classifiers) or branch state (this
    function)."""
    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})

    with ThreadPoolExecutor(max_workers=2) as pool:
        known_future = pool.submit(_fetch_known, allowed_branches)
        due_future = pool.submit(_fetch_due_commitments, allowed_branches)
        known = known_future.result()
        due_commitments = due_future.result()

    return allowed_branches, known, due_commitments

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
        "content": "None of the user's open commitments are due within the next 48 "
                   "hours — that's the only thing this means. You DO track and store "
                   "commitments normally; don't claim you can't add reminders or don't "
                   "track commitments at all. If asked what's coming up soon, say "
                   "nothing is due soon. If asked about commitments generally, check "
                   "what's actually in memory rather than assuming none exist.",
    }


def _should_check_sufficiency(skill: dict | None, injected: list[dict], search_decision: dict | None) -> bool:
    """Gate, decided BEFORE generation runs (nothing about activity_log
    exists yet at that point) — real context in play (recalled memory, an
    active skill, or a search) means the answer is worth checking; plain
    small talk with none of the three isn't, and skipping it there is what
    keeps this from doubling the cost of every single turn."""
    return bool(injected) or skill is not None or search_decision is not None

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

    return build_system_message(injected, (skill or {}).get("system_prompt"),
                                 include_identity=not (skill or {}).get("skip_identity", False)) \
        + ([{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] if summary else []) \
        + ([forget_context] if forget_context else []) \
        + ([commitment_context] if commitment_context else []) \
        + ([correction_context] if correction_context else []) \
        + to_provider_messages(visible_history) \
        + [{"role": "user", "content": message}]

def _system_context_from_conversation(conversation: list[dict], activity_log: list[dict] | None = None) -> str:
    """Pre-generation context (due commitments, recalled facts, summary)
    plus sources actually found DURING this turn's search. The second
    half matters: agentic_search.run()'s source list only ever lands in
    activity_log, live, mid-generation — it never re-enters `conversation`
    before the sufficiency check runs. Without it, the checker sees a
    reply's [N] citations with no idea what they reference, and judges
    real, correctly-grounded citations as unexplained noise — exactly
    what caused a genuinely well-sourced search reply to be flagged as
    insufficient and regenerated into a false self-disclaimer."""
    parts = [m["content"] for m in conversation if m["role"] == "system"]
    sources = [a for a in (activity_log or []) if a.get("kind") == "source"]
    if sources:
        lines = [f"[{a['citation']}] {a.get('url', '')} — {a.get('preview', '')}" for a in sources]
        parts.append("Sources found and cited during this turn's search:\n" + "\n".join(lines))
    return "\n\n".join(parts)

# --- Phase: reply generation ---
def _generate_reply(conversation_id: str, conversation: list[dict], skill: dict | None,
                     search_decision: dict | None, activity_log: list[dict], disconnected=None):
    memory_allowed = skill_registry.allows(skill, "memory_search")
    web_needed = search_decision is not None and skill_registry.allows(skill, "web_fetch")

    allowed_tools = set()
    if memory_allowed:
        allowed_tools.add("memory_search")
        allowed_tools.add("list_open_commitments")
        allowed_tools.add("conversation_history_search")
    if web_needed:
        allowed_tools.update({"web_search", "web_fetch", "github_search"})

    use_agentic = provider.supports_tools and bool(allowed_tools)

    logger.info(f"[{conversation_id}] reply-path: skill={skill!r} search_decision={search_decision!r} "
                f"memory_allowed={memory_allowed} web_needed={web_needed} "
                f"allowed_tools={allowed_tools} use_agentic={use_agentic}")

    full_response = ""

    if use_agentic:
        try:
            for event in agentic_search.run(provider, model, conversation,
                                             reasoning_effort=MAIN_REASONING_EFFORT,
                                             allowed_tools=allowed_tools,
                                             disconnected=disconnected,
                                             conversation_id=conversation_id):
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
                           active_corrections: list[dict], disconnected=None,
                           check_sufficiency: bool = False, message: str = ""):
    """The only function stream_chat calls for reply generation now.

    Fast pass-through only when NEITHER standing corrections NOR the
    sufficiency gate apply — the common case (plain small talk, no
    context in play) keeps live token-by-token streaming with zero added
    latency. Otherwise: buffer the full reply, run correction-check
    (existing, unchanged), then sufficiency-check (new) against the
    corrected-or-original result, each with its own regenerate-on-failure
    pass — the user only ever sees the final settled text, streamed once
    via simulated reveal."""
    gen = _generate_reply(conversation_id, conversation, skill, search_decision, activity_log, disconnected)

    if not active_corrections and not check_sufficiency:
        while True:
            try:
                event = next(gen)
            except StopIteration as stop:
                return (*stop.value, None)
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
            return "".join(buffered_text), True, None
        else:
            yield _sse(event)

    if errored:
        return full_response, True, None

    if active_corrections:
        check = check_correction_compliance(provider, active_corrections, full_response)
        if not check.get("compliant", True):
            guidance = check.get("guidance") or "Revise to follow the standing corrections exactly."
            corrective_conversation = conversation + [
                {"role": "assistant", "content": full_response},
                {"role": "system", "content": f"That reply violated a standing correction: {guidance} "
                                                "Regenerate a corrected reply from scratch — don't reference "
                                                "or apologize for the previous draft, the user never saw it."},
            ]
            try:
                full_response = "".join(provider.stream(corrective_conversation, model, reasoning_effort=MAIN_REASONING_EFFORT))
                ledger.log("correction_enforced", f"guidance={guidance}", conversation_id, actor="system")
            except Exception as e:
                ledger.log("correction_regen_failed", f"{e!r} — serving original draft", conversation_id, actor="system")

    sufficiency_result = None
    if check_sufficiency:
        context_summary = _system_context_from_conversation(conversation, activity_log)
        result = check_reply_sufficiency(provider, message, full_response, context_summary)
        sufficiency_result = result
        verdict = result.get("verdict", "answer")

        if verdict == "clarify":
            reason = result.get("reason") or "missing information"
            ev = {"kind": "reasoning", "label": f"Reconsidering: {reason}"}
            activity_log.append(ev)
            yield _sse({"type": "activity", "event": ev})

            instruction = (f"Your draft reply can't actually be completed — {reason} "
                            "Don't guess. Ask the user a direct, specific clarifying question "
                            "instead of answering. Don't reference the previous draft, the user "
                            "never saw it.")
            regen_conversation = conversation + [
                {"role": "assistant", "content": full_response},
                {"role": "system", "content": instruction},
            ]
            try:
                full_response = "".join(provider.stream(regen_conversation, model, reasoning_effort=MAIN_REASONING_EFFORT))
                ledger.log("sufficiency_regenerated", f"verdict=clarify reason={reason}", conversation_id, actor="system")
            except Exception as e:
                ledger.log("sufficiency_regen_failed", f"{e!r} — serving prior draft", conversation_id, actor="system")

        elif verdict == "search_more":
            reason = result.get("reason") or "missing information"
            ev = {"kind": "reasoning", "label": f"Checking earlier in this conversation for: {reason}"}
            activity_log.append(ev)
            yield _sse({"type": "activity", "event": ev})

            history_hits = search_messages(reason, conversation_id=conversation_id, limit=6)
            if history_hits:
                hits_block = "\n".join(
                    f"- ({h['role']}, {h['created_at']}): {h['content'][:200]}" for h in history_hits
                )
                instruction = (f"Your draft reply may be missing something: {reason} "
                                f"A search of this conversation's earlier history turned up:\n{hits_block}\n\n"
                                "Use it if it actually helps answer the question — don't force it in if "
                                "it doesn't. If it still doesn't resolve the gap, say plainly what's "
                                "uncertain rather than guessing.")
                found_ev = {"kind": "reasoning", "label": f"Found {len(history_hits)} earlier message(s) that might help"}
            else:
                instruction = (f"Your draft reply may be missing something: {reason} "
                                "A search of this conversation's earlier history found nothing relevant. "
                                "Regenerate being explicit about what's uncertain or missing, rather than "
                                "stating it as settled fact.")
                found_ev = {"kind": "reasoning", "label": "Nothing relevant found earlier in this conversation"}
            activity_log.append(found_ev)
            yield _sse({"type": "activity", "event": found_ev})

            regen_conversation = conversation + [
                {"role": "assistant", "content": full_response},
                {"role": "system", "content": instruction},
            ]
            try:
                full_response = "".join(provider.stream(regen_conversation, model, reasoning_effort=MAIN_REASONING_EFFORT))
                ledger.log("sufficiency_regenerated", f"verdict=search_more reason={reason} hits={len(history_hits)}", conversation_id, actor="system")
            except Exception as e:
                ledger.log("sufficiency_regen_failed", f"{e!r} — serving prior draft", conversation_id, actor="system")

    yield _sse({"type": "text", "value": full_response, "reveal": "simulated"})
    return full_response, False, sufficiency_result

# --- Phase: capture (facts + conflicts) ---
def _process_capture(conversation_id: str, message: str, full_response: str,
                      known: list[dict], allowed_branches: list[str],
                      forget_matches: list[dict], activity_log: list[dict],
                      disconnected=None):
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
    needed in this function itself.

    disconnected, if given, is checked before each individual write in
    the loop below — not just once before the phase starts — so a client
    that leaves partway through a multi-unit capture stops the remaining
    writes instead of committing all of them regardless.

    The duplicate-check wave below is a dynamic fan-out — a variable
    number of candidates per turn, unlike the fixed named stages in
    stream_chat's intake pipeline — built as a Stage list at call time
    rather than declared statically, since the candidate count isn't
    known until extract_units returns. Same Pipeline runner either way;
    only the write loop after it stays hand-sequential, since concurrent
    writes to the git-versioned memory store haven't been evaluated for
    commit-ordering safety."""

    def _is_live_duplicate(k: dict, content: str) -> bool:
        if k["content"] != content:
            return False
        if k.get("unit_type") == "commitment" and k.get("commitment_status") not in (None, "open"):
            return False
        return True

    known_entities = [] if forget_matches else fetch_known_entities()
    units = [] if forget_matches else extract_units(provider, message, full_response, known, allowed_branches, known_entities)
    added, conflicts = [], []

    needs_dup_check = [
        i for i, u in enumerate(units)
        if not any(_is_live_duplicate(k, u["content"]) for k in known) and not u.get("supersedes")
    ]

    dup_results: dict[int, bool] = {}
    if needs_dup_check:
        dup_stages = [
            Stage(
                name=f"dup_{i}",
                deps=[],
                on_fail="open",  # fail open — a missed duplicate is recoverable later, silently blocking a real new fact is not
                fn=(lambda ctx, i=i: is_semantic_duplicate(units[i], units[i].get("branch", "main"))),
            )
            for i in needs_dup_check
        ]
        dup_context = Pipeline(dup_stages).run({})
        dup_results = {i: bool(dup_context[f"dup_{i}"]) for i in needs_dup_check}

    for i, u in enumerate(units):
        if disconnected is not None and disconnected.is_set():
            logger.info(f"[{conversation_id}] disconnected mid-capture — "
                        f"stopping before further writes ({i}/{len(units)} units processed)")
            break

        if any(_is_live_duplicate(k, u["content"]) for k in known):
            activity_log.append({"kind": "duplicate_skipped", "content": u["content"]})
            continue

        short = u.get("supersedes")
        branch = u.get("branch", "main")

        if not short and dup_results.get(i, False):
            activity_log.append({"kind": "duplicate_skipped", "content": u["content"]})
            continue

        target = next((k for k in known if k["hash"].startswith(short)), None) if short else None

        if target:
            cid = uuid4().hex[:12]
            PENDING[cid] = {
                "from": target["hash"],
                "unit": u,
                "source": conversation_id,
                "branch": target["branch"],
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

BULK_CLOSE_WORDS = ("close", "resolve", "mark", "clear", "complete", "cancel")

def _mentions_bulk_commitment_close(message: str) -> bool:
    m = message.lower()
    return "commitment" in m and any(w in m for w in BULK_CLOSE_WORDS)

def _process_commitment_resolutions(conversation_id: str, message: str, full_response: str,
                                     allowed_branches: list[str], activity_log: list[dict]):
    open_commitments = []
    for b in allowed_branches:
        open_commitments.extend({**u, "branch": b} for u in find_open_commitments(b))

    if not open_commitments:
        return

    if _mentions_bulk_commitment_close(message):
        # Deterministic, no LLM judgment needed — the user asked for
        # everything, so propose everything currently open, one card per
        # commitment, same PENDING/confirm-before-act pattern as the
        # single-item path. No risk of under-matching via keyword search,
        # since this reads the authoritative open list directly.
        for unit in open_commitments:
            rid = uuid4().hex[:12]
            PENDING_COMMITMENT_RESOLUTIONS[rid] = {
                "unit": unit, "status": "cancelled",
                "source": conversation_id, "branch": unit.get("branch", "main"),
            }
            ev = {
                "kind": "commitment_resolution_request",
                "label": f"Mark cancelled: {unit['content']}",
                "id": rid, "content": unit["content"], "status": "cancelled",
            }
            activity_log.append(ev)
            yield _sse({"type": "activity", "event": ev})
            ledger.log("commitment_resolution_proposed", f"bulk cancelled: {unit['content']}",
                       conversation_id, actor="system")
        return

    resolutions = detect_commitment_resolutions(provider, message, full_response, open_commitments)
    for r in resolutions:
        branch = r["unit"].get("branch", "main")
        rid = uuid4().hex[:12]
        PENDING_COMMITMENT_RESOLUTIONS[rid] = {
            "unit": r["unit"],
            "status": r["status"],
            "source": conversation_id,
            "branch": branch,
        }
        ev = {
            "kind": "commitment_resolution_request",
            "label": f"Mark {r['status']}: {r['unit']['content']}",
            "id": rid,
            "content": r["unit"]["content"],
            "status": r["status"],
        }
        activity_log.append(ev)
        yield _sse({"type": "activity", "event": ev})
        ledger.log("commitment_resolution_proposed", f"{r['status']}: {r['unit']['content']}",
                   conversation_id, actor="system")

# --- Orchestration ---
def stream_chat(conversation_id: str, message: str, disconnected: threading.Event | None = None):
    """Generator yielding SSE-formatted strings for one chat turn: memory
    injection, skill selection, optional search, the streamed reply, then
    capture (facts, conflicts, forget requests, commitment resolutions).

    The intake phase (everything before the reply starts generating) now
    runs through a declared Pipeline instead of hand-nested
    ThreadPoolExecutor blocks — same two waves as before (classify/
    time-travel/branch-gather, then forget-detection/retrieval), same
    concurrency, same dependency structure, just expressed as `deps`
    instead of literal code nesting. Everything from _build_conversation
    onward is unchanged from before this migration."""
    turn_start = time.monotonic()

    history = load_messages(conversation_id)
    save_message(conversation_id, "user", message)

    def _stage_classify(ctx):
        return _classify(ctx["message"])

    def _stage_time_travel(ctx):
        return time_travel.detect_time_travel_query(provider, ctx["message"])

    def _stage_branches(ctx):
        return _gather_branches_known_commitments()

    def _stage_forget(ctx):
        allowed_branches, known, _ = ctx["branches_known_commitments"]
        return forgetting.detect_forget_request(provider, ctx["message"], known, allowed_branches)

    def _stage_retrieval_normal(ctx):
        skill, _ = ctx["classify"]
        allowed_branches, _, _ = ctx["branches_known_commitments"]
        return _fetch_relevant(ctx["message"], skill, allowed_branches)

    def _stage_retrieval_time_travel(ctx):
        allowed_branches, _, _ = ctx["branches_known_commitments"]
        return [fetch_state_at_time(b, ctx["time_travel"]) for b in allowed_branches]

    intake = Pipeline([
        Stage("classify", deps=[], fn=_stage_classify),
        Stage("time_travel", deps=[], fn=_stage_time_travel),
        Stage("branches_known_commitments", deps=[], fn=_stage_branches),
        Stage("forget_detect", deps=["branches_known_commitments"], fn=_stage_forget),
        Stage("retrieval_normal", deps=["classify", "branches_known_commitments", "time_travel"],
            gate=lambda ctx: not ctx["time_travel"], fn=_stage_retrieval_normal),
        Stage("retrieval_time_travel", deps=["time_travel", "branches_known_commitments"],
              gate=lambda ctx: bool(ctx["time_travel"]), fn=_stage_retrieval_time_travel),
    ])

    context = intake.run({"message": message}, disconnected=disconnected)

    skill, search_decision = context["classify"]
    time_travel_target = context["time_travel"]
    allowed_branches, known, due_commitments = context["branches_known_commitments"]
    forget_matches = context["forget_detect"] or []
    active_corrections = [u for u in known if u.get("unit_type") == "correction"]

    if time_travel_target:
        tt_results = context["retrieval_time_travel"]
        tt_units = [u for r in tt_results for u in r["units"]]
        resolved_dates = [r["resolved_at"] for r in tt_results if r["resolved_at"]]
        injected = tt_units[:12]
        per_branch_debug = {}
    else:
        injected, per_branch_debug = context["retrieval_normal"]

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

    full_response, errored, sufficiency_result = yield from _generate_reply_gated(
        conversation_id, conversation, skill, search_decision, activity_log, active_corrections, disconnected,
        check_sufficiency=_should_check_sufficiency(skill, injected, search_decision),
        message=message,
    )
    if errored:
        return

    assistant_message_id = save_message(conversation_id, "assistant", full_response, activity_log)

    if disconnected is not None and disconnected.is_set():
        logger.info(f"[{conversation_id}] client disconnected — skipping capture/forget/resolution, no orphaned writes")
        return

    conflicts = yield from _process_capture(
        conversation_id, message, full_response, known, allowed_branches, forget_matches, activity_log,
        disconnected,
    )
    yield from _process_forgets(conversation_id, forget_matches, conflicts, activity_log)
    yield from _process_commitment_resolutions(
        conversation_id, message, full_response, allowed_branches, activity_log,
    )

    persisted_activity = [a for a in activity_log if a["kind"] != "skill"]
    update_message_activity(assistant_message_id, persisted_activity)

    chatlog.log_turn(conversation_id, message, skill, injected, activity_log, full_response,
                      duration_seconds=time.monotonic() - turn_start, sufficiency=sufficiency_result)
    yield _sse({"type": "done"})

    # Fire-and-forget, but no longer a bare daemon thread with no failure
    # visibility — post_response.run() submits into the shared executor
    # and returns immediately (background stages don't block the caller);
    # a failure is logged by Pipeline._on_background_done, not silently
    # swallowed past a single warning line at the call site.
    post_response.run({
        "conversation_id": conversation_id,
        "history": history,
        "message": message,
        "full_response": full_response,
    })