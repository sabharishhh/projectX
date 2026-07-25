import os
import json
import ledger
import sqlite3
import research
import branching
from uuid import uuid4
from fastapi import FastAPI
import merge as merge_engine
from pydantic import BaseModel
from dotenv import load_dotenv
import skills as skill_registry
from providers import get_provider
from datetime import datetime, timezone
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from memory import fetch_state, fetch_relevant, fetch_branches, build_system_message
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
            activity TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # migrations for dbs created before these columns existed. The `branch`
    # column is left in place (unused) rather than dropped — conversations
    # are single-threaded again now that branch inference is per-fact, not
    # per-conversation, but no need to churn the schema to remove it.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "activity" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN activity TEXT")
    if "branch" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN branch TEXT NOT NULL DEFAULT 'main'")
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

    skill = skill_registry.select(provider, req.message)

    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})
    domain = branching.infer_domain(provider, req.message, existing_branches)
    read_branches = ["main"] if domain == "main" else ["main", domain]

    # aggregate memory across the relevant branches — tagging each unit with
    # its origin so capture can look up which branch a conflict target lives on
    known = [{**u, "branch": b} for b in allowed_branches for u in fetch_state(b)]

    seen, injected = set(), []
    for b in read_branches:
        for u in fetch_relevant(
            req.message, branch=b, max_units=12,
            boost_types=(skill or {}).get("boost_types"),
        ):
            if u["hash"] not in seen:
                seen.add(u["hash"])
                injected.append({**u, "branch": b})
    injected = injected[:12]

    conversation = [build_system_message(injected, (skill or {}).get("system_prompt"))] \
        + to_provider_messages(history) \
        + [{"role": "user", "content": req.message}]

    ledger.log("provider_call", f"model={model}", req.conversation_id, actor="user")
    if skill:
        ledger.log("skill_invoked", f"{skill['name']}: {req.message[:60]}",
                   req.conversation_id, actor="system")

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    def event_stream():
        activity_log = []

        if skill:
            ev = {"kind": "skill", "label": f"Using {skill['name']} skill"}
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})

        if injected:
            branch_note = ", ".join(read_branches)
            ev = {
                "kind": "memory_read",
                "label": f"Recalled {len(injected)} {'fact' if len(injected) == 1 else 'facts'} ({branch_note})",
                "units": injected,
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})

        search_query = None
        if skill_registry.allows(skill, "web_search"):
            search_query = research.should_search(provider, req.message)

        if search_query:
            yield sse({"type": "activity", "event": {"kind": "searching", "label": f"Searching: {search_query}"}})
            distilled = research.research(provider, search_query)
            if distilled:
                ev = {
                    "kind": "search",
                    "label": f"Read {len(distilled)} page{'s' if len(distilled) != 1 else ''}: {search_query}",
                    "results": distilled,
                }
                activity_log.append(ev)
                yield sse({"type": "activity", "event": ev})
                conversation.append({
                    "role": "system",
                    "content": research.format_for_context(search_query, distilled),
                })
                ledger.log("search_call", f"{search_query} ({len(distilled)} pages read)",
                           req.conversation_id, actor="system")
            else:
                ev = {"kind": "search_failed", "label": f"Searched, but couldn't read any results: {search_query}"}
                activity_log.append(ev)
                yield sse({"type": "activity", "event": ev})
                ledger.log("search_call", f"{search_query} (0 pages read — extraction failed)",
                           req.conversation_id, actor="system")

        full_response = ""
        try:
            for chunk in provider.stream(conversation, model):
                full_response += chunk
                yield sse({"type": "text", "value": chunk})
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return

        units = extract_units(provider, req.message, full_response, known, allowed_branches)
        added, conflicts = [], []

        for u in units:
            short = u.get("supersedes")
            target = next((k for k in known if k["hash"].startswith(short)), None) if short else None
            branch = u.get("branch", "main")

            if target:
                cid = uuid4().hex[:12]
                PENDING[cid] = {
                    "from": target["hash"],
                    "unit": u,
                    "source": req.conversation_id,
                    "branch": target["branch"],  # supersede lands on the target's own branch
                }
                conflicts.append({"id": cid, "old": target, "new": u})
                ledger.log("conflict_raised",
                           f"'{u['content']}' conflicts with '{target['content']}'",
                           req.conversation_id, actor="system")
            elif commit_unit(u, req.conversation_id, branch):
                added.append(u)
                ledger.log("memory_commit", f"added to {branch}: {u['content']}",
                           req.conversation_id, actor="system")

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
        supersede_unit(p["from"], p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"replaced with: {p['unit']['content']}", p["source"], actor="user")
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"], p["branch"])
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