from fastapi import APIRouter

import db
import ledger
from capture import supersede_unit, commit_unit, forget_unit, purge_unit, confirm_commitment_resolution
from models import ResolveRequest, ForgetResolveRequest, DirectDeleteRequest, DirectEditRequest, ManualCommitRequest, CommitmentResolutionRequest
from state import PENDING, PENDING_FORGETS, PENDING_COMMITMENT_RESOLUTIONS

router = APIRouter()


@router.post("/api/memory/resolve")
def resolve_conflict(req: ResolveRequest):
    p = PENDING.pop(req.conflict_id, None)
    if not p:
        db.mark_conflict_status(req.conversation_id, req.conflict_id, "expired")
        return {"ok": False, "reason": "already resolved or expired"}

    if req.choice == "update":
        supersede_unit(p["from"], p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"replaced with: {p['unit']['content']}", p["source"], actor="user")
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"kept both: {p['unit']['content']}", p["source"], actor="user")
    else:
        ledger.log("conflict_resolved", "kept the original, ignored the new fact", p["source"], actor="user")

    db.mark_conflict_status(p["source"], req.conflict_id, req.choice)
    return {"ok": True}


@router.post("/api/memory/delete")
def delete_unit(req: DirectDeleteRequest):
    """Manual delete from the memory panel — not tied to a PENDING_FORGETS
    entry, since there's no LLM proposal here, just direct user action.
    Soft-forgets, matching every other deletion path in this system —
    recoverable via Timeline, not gone without a trace."""
    ok = forget_unit(req.hash, "memory-panel", req.branch, "user manually deleted this from the memory panel")
    if ok:
        ledger.log("memory_forgotten", f"manually deleted via panel: {req.hash[:8]}", "memory-panel", actor="user")
    return {"ok": ok}

@router.post("/api/memory/forget")
def resolve_forget(req: ForgetResolveRequest):
    p = PENDING_FORGETS.pop(req.forget_id, None)
    if not p:
        return {"ok": False, "reason": "already resolved or expired"}

    if req.choice == "soft":
        forget_unit(p["hash"], p["source"], p["branch"], "user asked to forget this")
        ledger.log("memory_forgotten", f"soft-forgot: {p['content']}", p["source"], actor="user")
    elif req.choice == "hard":
        forget_unit(p["hash"], p["source"], p["branch"], "user asked to permanently delete this")
        purge_unit(p["hash"])
        # per ledger-spec §4: record that a hard-delete occurred, without
        # retaining the deleted content itself
        ledger.log("memory_purged", f"permanently deleted a {p['branch']}-branch fact", p["source"], actor="user")
    else:
        ledger.log("forget_cancelled", f"kept: {p['content']}", p["source"], actor="user")

    db.mark_forget_status(p["source"], req.forget_id, req.choice)
    return {"ok": True}

@router.post("/api/memory/edit")
def edit_unit(req: DirectEditRequest):
    """Edit-in-place maps directly onto supersede — the exact same
    primitive every other content change in this system uses. No LLM
    verification pass, unlike normal capture: the user editing their own
    stored fact IS the authority, nothing to judge. The old version stays
    fully visible in Timeline, same guarantee as everything else."""
    unit = {
        "content": req.new_content,
        "unit_type": req.unit_type,
        "provenance": req.provenance,
        "summary": f"User edited: {req.new_content}",
        "deadline": req.deadline,
        "commitment_status": req.commitment_status,
    }
    ok = supersede_unit(req.hash, unit, "memory-panel", req.branch)
    if ok:
        ledger.log("memory_edited", f"user edited {req.hash[:8]} -> {req.new_content}", "memory-panel", actor="user")
    return {"ok": ok}

@router.post("/api/memory/commit")
def create_commitment(req: ManualCommitRequest):
    """Manual creation — skips extraction and verification entirely. The
    user directly stating "track this" is the authority, same reasoning
    as manual edit needing no re-verification. deadline is optional —
    None means "no due date, stays open as a passive reminder," never
    surfaced via find_due_commitments (which only matches units that
    actually have a deadline), only visible in the Memory panel."""
    unit = {
        "content": req.content,
        "unit_type": "commitment",
        "provenance": "stated",
        "summary": req.content,
        "deadline": req.deadline,
        "commitment_status": "open",
    }
    ok = commit_unit(unit, "memory-panel", req.branch)
    if ok:
        ledger.log("memory_commit", f"manually created: {req.content}", "memory-panel", actor="user")
    return {"ok": ok}

@router.post("/api/memory/resolve_commitment")
def resolve_commitment_confirmation(req: CommitmentResolutionRequest):
    p = PENDING_COMMITMENT_RESOLUTIONS.pop(req.resolution_id, None)
    if not p:
        return {"ok": False, "reason": "already resolved or expired"}

    ok = confirm_commitment_resolution(p, req.choice)
    if ok:
        if req.choice == "confirm":
            ledger.log("commitment_resolved", f"{p['status']}: {p['unit']['content']}", p["source"], actor="user")
        else:
            ledger.log("commitment_resolution_declined", f"kept open: {p['unit']['content']}", p["source"], actor="user")
        db.mark_commitment_resolution_status(p["source"], req.resolution_id, req.choice)
    return {"ok": ok}