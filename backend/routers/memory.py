from fastapi import APIRouter

import db
import ledger
from capture import supersede_unit, commit_unit, forget_unit, purge_unit
from models import ResolveRequest, ForgetResolveRequest, DirectDeleteRequest, DirectEditRequest
from state import PENDING, PENDING_FORGETS

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