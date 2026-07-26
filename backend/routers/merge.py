from fastapi import APIRouter

import ledger
import merge as merge_engine
from models import MergeApplyRequest
from state import provider

router = APIRouter()


@router.get("/api/merge/preview")
def merge_preview(from_branch: str, into_branch: str):
    data = merge_engine.preview(from_branch, into_branch)
    conflicts = merge_engine.find_conflicts(
        provider, from_branch, into_branch, data["incoming"], data["existing"]
    )
    conflict_incoming_hashes = {c["incoming"]["hash"] for c in conflicts}
    clean = [u for u in data["incoming"] if u["hash"] not in conflict_incoming_hashes]

    ledger.log("merge_preview",
               f"{from_branch} → {into_branch}: {len(clean)} clean, {len(conflicts)} conflicting",
               from_branch, actor="user")

    return {"clean": clean, "conflicts": conflicts, "existing": data["existing"]}


@router.post("/api/merge/apply")
def merge_apply(req: MergeApplyRequest):
    result = merge_engine.apply(
        req.from_branch, req.into_branch, req.adopt, req.replace,
        source="merge", summary=req.summary,
    )
    ledger.log("merge_applied", req.summary, req.from_branch, actor="user")
    return result