from fastapi import APIRouter

import db
import ledger
from capture import supersede_unit, commit_unit, forget_unit, purge_unit
from models import ResolveRequest, ForgetResolveRequest
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