import os
import json
import ledger
import sqlite3
import research
import branching
import forgetting
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
from capture import extract_units, commit_unit, supersede_unit, forget_unit, purge_unit

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
PENDING_FORGETS: dict[str, dict] = {}


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

def mark_conflict_status(conversation_id: str, conflict_id: str, resolution: str) -> bool:
    """Find the message that raised this conflict and record how it was
    resolved, so a reload reflects the true state instead of re-showing it
    as pending. Returns True if a matching event was found and patched."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, activity FROM messages WHERE conversation_id = ? AND activity IS NOT NULL",
        (conversation_id,),
    ).fetchall()

    for row_id, activity_json in rows:
        events = json.loads(activity_json)
        changed = False
        for ev in events:
            if ev.get("kind") == "conflict" and ev.get("id") == conflict_id:
                ev["resolved"] = resolution
                changed = True
        if changed:
            conn.execute("UPDATE messages SET activity = ? WHERE id = ?", (json.dumps(events), row_id))
            conn.commit()
            conn.close()
            return True

    conn.close()
    return False

def mark_forget_status(conversation_id: str, forget_id: str, resolution: str) -> bool:
    """Same persistence pattern as mark_conflict_status — writes the
    resolution onto the stored message's activity so it survives reload."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, activity FROM messages WHERE conversation_id = ? AND activity IS NOT NULL",
        (conversation_id,),
    ).fetchall()
    for row_id, activity_json in rows:
        activity = json.loads(activity_json)
        changed = False
        for act in activity:
            if act.get("kind") == "forget_request" and act.get("id") == forget_id:
                act["resolved"] = resolution
                changed = True
        if changed:
            conn.execute("UPDATE messages SET activity = ? WHERE id = ?", (json.dumps(activity), row_id))
    conn.commit()
    conn.close()
    return True

class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class ResolveRequest(BaseModel):
    conflict_id: str
    choice: str  # "update" | "keep_both" | "keep_old"
    conversation_id: str


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
def chat(req: ChatRequest):
    history = load_messages(req.conversation_id)
    save_message(req.conversation_id, "user", req.message)

    skill = skill_registry.select(provider, req.message)

    existing_branches = fetch_branches()
    allowed_branches = sorted({"main", *branching.CANONICAL_DOMAINS, *existing_branches})

    # Always read across every branch — domain classification still decides
    # where a new fact gets *written* (capture routes work/personal/main per
    # fact), but it no longer gates what can be *read back*. A per-turn domain
    # guess was silently hiding whole categories of real, stored memory whenever
    # it guessed wrong or a question didn't clearly belong to one domain.
    # Retrieval scoring (relevance + recency + pinned set) now decides what's
    # worth injecting, instead of a folder-like filter deciding it first.
    known = [{**u, "branch": b} for b in allowed_branches for u in fetch_state(b)]

    seen, injected = set(), []
    for b in allowed_branches:
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
            ev = {
                "kind": "memory_read",
                "label": f"Recalled {len(injected)} {'fact' if len(injected) == 1 else 'facts'}",
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

        # Explicit forget requests — checked after capture/conflicts, and
        # deliberately skips any unit capture already flagged as a conflict.
        # Without this, a message like "I don't use vim anymore, I use emacs"
        # could get interpreted BOTH as a contradiction (by capture) and as
        # an implicit forget (by forget-detection) — surfacing two separate
        # prompts asking the user to resolve the same underlying fact twice.
        conflicted_hashes = {c["old"]["hash"] for c in conflicts}
        forget_matches = forgetting.detect_forget_request(provider, req.message, known)
        for m in forget_matches:
            if m["unit"]["hash"] in conflicted_hashes:
                continue  # capture already surfaced this as a conflict — don't ask twice
            fid = uuid4().hex[:12]
            PENDING_FORGETS[fid] = {
                "hash": m["unit"]["hash"],
                "content": m["unit"]["content"],
                "branch": m["unit"]["branch"],
                "source": req.conversation_id,
            }
            ev = {
                "kind": "forget_request",
                "label": "Forget this?",
                "id": fid,
                "content": m["unit"]["content"],
                "reason": m["reason"],
            }
            activity_log.append(ev)
            yield sse({"type": "activity", "event": ev})
            ledger.log("forget_requested", f"candidate: {m['unit']['content']}", req.conversation_id, actor="system")

        save_message(req.conversation_id, "assistant", full_response, activity_log)
        yield sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/memory/resolve")
def resolve_conflict(req: ResolveRequest):
    p = PENDING.pop(req.conflict_id, None)

    if not p:
        mark_conflict_status(req.conversation_id, req.conflict_id, "expired")
        return {"ok": False, "reason": "already resolved or expired"}

    if req.choice == "update":
        supersede_unit(p["from"], p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"replaced with: {p['unit']['content']}", p["source"], actor="user")
    elif req.choice == "keep_both":
        commit_unit(p["unit"], p["source"], p["branch"])
        ledger.log("conflict_resolved", f"kept both: {p['unit']['content']}", p["source"], actor="user")
    else:
        ledger.log("conflict_resolved", "kept the original, ignored the new fact", p["source"], actor="user")

    mark_conflict_status(p["source"], req.conflict_id, req.choice)
    return {"ok": True}


@app.delete("/api/messages/{conversation_id}")
def clear_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    ledger.log("conversation_cleared", "chat history wiped", conversation_id, actor="user")
    return {"cleared": conversation_id}

@app.get("/api/conversations")
def list_conversations():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT conversation_id,
               MIN(created_at) as started,
               MAX(created_at) as updated,
               (SELECT content FROM messages m2
                WHERE m2.conversation_id = m1.conversation_id AND m2.role = 'user'
                ORDER BY m2.id ASC LIMIT 1) as first_message
        FROM messages m1
        GROUP BY conversation_id
        ORDER BY updated DESC
    """).fetchall()
    conn.close()
    return [
        {"conversation_id": r[0], "started": r[1], "updated": r[2],
         "label": (r[3][:60] if r[3] else "New chat")}
        for r in rows
    ]

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

class ForgetResolveRequest(BaseModel):
    forget_id: str
    choice: str 

@app.post("/api/memory/forget")
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

    mark_forget_status(p["source"], req.forget_id, req.choice)
    return {"ok": True}