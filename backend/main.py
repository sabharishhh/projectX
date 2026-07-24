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
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()


def load_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in rows]


def save_message(conversation_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
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


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = load_messages(req.conversation_id)
    save_message(req.conversation_id, "user", req.message)

    known = fetch_state()
    conversation = [build_system_message(known)] + history + [
        {"role": "user", "content": req.message}
    ]

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    def event_stream():
        # what memory contributed to this turn — emitted before the answer
        if known:
            yield sse({
                "type": "activity",
                "event": {
                    "kind": "memory_read",
                    "label": f"Recalled {len(known)} {'fact' if len(known) == 1 else 'facts'}",
                    "units": known,
                },
            })

        full_response = ""
        try:
            for chunk in provider.stream(conversation, model):
                full_response += chunk
                yield sse({"type": "text", "value": chunk})
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return

        save_message(req.conversation_id, "assistant", full_response)

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
                PENDING[cid] = {
                    "from": target["hash"],
                    "unit": u,
                    "source": req.conversation_id,
                }
                conflicts.append({"id": cid, "old": target, "new": u})
            elif commit_unit(u, req.conversation_id):
                added.append(u)

        if added:
            yield sse({
                "type": "activity",
                "event": {
                    "kind": "memory_write",
                    "label": f"Remembered {len(added)} {'thing' if len(added) == 1 else 'things'}",
                    "units": added,
                },
            })

        for c in conflicts:
            yield sse({
                "type": "activity",
                "event": {
                    "kind": "conflict",
                    "label": "This changes something I already knew",
                    "id": c["id"],
                    "old": c["old"],
                    "new": c["new"],
                },
            })

        yield sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/memory/resolve")
def resolve_conflict(req: ResolveRequest):
    p = PENDING.pop(req.conflict_id, None)
    if not p:
        return {"ok": False, "reason": "already resolved"}

    if req.choice == "update":
        supersede_unit(p["from"], p["unit"], p["source"])
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"])
    # keep_old: nothing is written

    return {"ok": True}


@app.delete("/api/messages/{conversation_id}")
def clear_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    return {"cleared": conversation_id}