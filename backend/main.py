import os
import json
import sqlite3
from uuid import uuid4
from pydantic import BaseModel
import merge as merge_engine
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from providers import get_provider
from memory import fetch_state, fetch_relevant, build_system_message
from capture import extract_units, commit_unit, supersede_unit
import ledger

load_dotenv()

app = FastAPI(title="projectX")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

provider, model = get_provider()

DB_PATH = "projectx.db"

# conflicts awaiting the user's decision (in-process; lost on restart)
PENDING: dict[str, dict] = {}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            activity TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # migration for dbs created before the activity column existed
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "activity" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN activity TEXT")
    if "branch" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN branch TEXT NOT NULL DEFAULT 'main'")
    conn.commit()
    conn.close()

init_db()
ledger.init_ledger()


def load_messages(conversation_id: str, branch: str = "main"):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content, activity FROM messages WHERE conversation_id = ? AND branch = ? ORDER BY id ASC",
        (conversation_id, branch),
    ).fetchall()
    conn.close()
    out = []
    for role, content, activity in rows:
        msg = {"role": role, "content": content}
        if activity:
            msg["activity"] = json.loads(activity)
        out.append(msg)
    return out


def to_provider_messages(msgs):
    """Strip UI-only fields (activity) before sending to the model."""
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def save_message(conversation_id: str, branch: str, role: str, content: str, activity: list | None = None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (conversation_id, branch, role, content, activity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, branch, role, content, json.dumps(activity) if activity else None,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    branch: str = "main"


class ResolveRequest(BaseModel):
    conflict_id: str
    choice: str  # "update" | "keep_both" | "keep_old"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/messages/{conversation_id}")
def get_messages(conversation_id: str, branch: str = "main"):
    return load_messages(conversation_id, branch)


@app.get("/api/ledger")
def get_ledger(limit: int = 50):
    return ledger.recent(limit)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = load_messages(req.conversation_id, req.branch)
    save_message(req.conversation_id, req.branch, "user", req.message)

    # --- CHANGE 1 LANDS HERE ---
    known = fetch_state(req.branch)  # full state — capture/dedup needs everything
    injected = fetch_relevant(req.message, branch=req.branch, max_units=12)  # scored subset — what the model actually sees
    
    # Notice we pass `injected` to the system message, not `known`
    conversation = [build_system_message(injected)] + to_provider_messages(history) + [
        {"role": "user", "content": req.message}
    ]
    # ---------------------------

    ledger.log("provider_call", f"model={model}", req.conversation_id, actor="user")

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    def event_stream():
        activity_log = []

        # --- CHANGE 2 LANDS HERE ---
        # The UI should only show what was actually injected into the context window
        if injected:
            ev = {
                "kind": "memory_read",
                "label": f"Recalled {len(injected)} {'fact' if len(injected) == 1 else 'facts'}",
                "units": injected,
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})
        # ---------------------------

        full_response = ""
        try:
            for chunk in provider.stream(conversation, model):
                full_response += chunk
                yield sse({"type": "text", "value": chunk})
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return

        # 'known' (the full database) is still used here for deduplication/conflict checks
        units = extract_units(provider, req.message, full_response, known)
        added, conflicts = [], []

        for u in units:
            short = u.get("supersedes")
            target = (
                next((k for k in known if k["hash"].startswith(short)), None)
                if short else None
            )
            if target:
                cid = uuid4().hex[:12]
                PENDING[cid] = {"from": target["hash"], "unit": u, "source": req.conversation_id}
                conflicts.append({"id": cid, "old": target, "new": u})
                ledger.log("conflict_raised",
                           f"'{u['content']}' conflicts with '{target['content']}'",
                           req.conversation_id, actor="system")
            elif commit_unit(u, req.conversation_id, req.branch):
                added.append(u)
                ledger.log("memory_commit", f"added: {u['content']}", req.conversation_id, actor="system")

        if added:
            ev = {
                "kind": "memory_write",
                "label": f"Remembered {len(added)} {'thing' if len(added) == 1 else 'things'}",
                "units": added,
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})

        for c in conflicts:
            ev = {
                "kind": "conflict",
                "label": "This changes something I already knew",
                "id": c["id"],
                "old": c["old"],
                "new": c["new"],
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})

        save_message(req.conversation_id, req.branch, "assistant", full_response, activity_log)
        yield sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/memory/resolve")
def resolve_conflict(req: ResolveRequest):
    p = PENDING.pop(req.conflict_id, None)
    if not p:
        return {"ok": False, "reason": "already resolved or expired"}

    if req.choice == "update":
        supersede_unit(p["from"], p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"replaced with: {p['unit']['content']}", p["source"], actor="user")
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"kept both: {p['unit']['content']}", p["source"], actor="user")
    else:
        ledger.log("conflict_resolved", "kept the original, ignored the new fact", p["source"], actor="user")

    return {"ok": True}


@app.delete("/api/messages/{conversation_id}")
def clear_messages(conversation_id: str, branch: str = "main"):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE conversation_id = ? AND branch = ?", (conversation_id, branch))
    conn.commit()
    conn.close()
    ledger.log("conversation_cleared", f"branch={branch}", conversation_id, actor="user")
    return {"cleared": conversation_id, "branch": branch}

class MergeApplyRequest(BaseModel):
    from_branch: str
    into_branch: str
    adopt: list[str] = []
    replace: list[dict] = []
    summary: str = "manual merge"

@app.get("/api/merge/preview")
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


@app.post("/api/merge/apply")
def merge_apply(req: MergeApplyRequest):
    result = merge_engine.apply(
        req.from_branch, req.into_branch, req.adopt, req.replace,
        source="merge", summary=req.summary,
    )
    ledger.log("merge_applied", req.summary, req.from_branch, actor="user")
    return result
