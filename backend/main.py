import os
import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from providers import get_provider
from memory import fetch_state, build_system_message
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
    conn.commit()
    conn.close()

init_db()
ledger.init_ledger()


def load_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content, activity FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
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


def save_message(conversation_id: str, role: str, content: str, activity: list | None = None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, activity, created_at) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, role, content, json.dumps(activity) if activity else None,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class ResolveRequest(BaseModel):
    conflict_id: str
    choice: str  # "update" | "keep_both" | "keep_old"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/messages/{conversation_id}")
def get_messages(conversation_id: str):
    return load_messages(conversation_id)


@app.get("/api/ledger")
def get_ledger(limit: int = 50):
    return ledger.recent(limit)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = load_messages(req.conversation_id)
    save_message(req.conversation_id, "user", req.message)

    known = fetch_state()
    conversation = [build_system_message(known)] + to_provider_messages(history) + [
        {"role": "user", "content": req.message}
    ]

    ledger.log("provider_call", f"model={model}", req.conversation_id, actor="user")

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    def event_stream():
        activity_log = []

        if known:
            ev = {
                "kind": "memory_read",
                "label": f"Recalled {len(known)} {'fact' if len(known) == 1 else 'facts'}",
                "units": known,
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})

        full_response = ""
        try:
            for chunk in provider.stream(conversation, model):
                full_response += chunk
                yield sse({"type": "text", "value": chunk})
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return

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
            elif commit_unit(u, req.conversation_id):
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

        save_message(req.conversation_id, "assistant", full_response, activity_log)
        yield sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/memory/resolve")
def resolve_conflict(req: ResolveRequest):
    p = PENDING.pop(req.conflict_id, None)
    if not p:
        return {"ok": False, "reason": "already resolved or expired"}

    if req.choice == "update":
        supersede_unit(p["from"], p["unit"], p["source"])
        ledger.log("conflict_resolved", f"replaced with: {p['unit']['content']}", p["source"], actor="user")
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"])
        ledger.log("conflict_resolved", f"kept both: {p['unit']['content']}", p["source"], actor="user")
    else:
        ledger.log("conflict_resolved", "kept the original, ignored the new fact", p["source"], actor="user")

    return {"ok": True}


@app.delete("/api/messages/{conversation_id}")
def clear_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    ledger.log("conversation_cleared", "chat history wiped", conversation_id, actor="user")
    return {"cleared": conversation_id}