import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "projectx.db"


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            summarized_through INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retrieval_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            message TEXT NOT NULL,
            trace TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "activity" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN activity TEXT")
    if "branch" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN branch TEXT NOT NULL DEFAULT 'main'")
    conn.commit()
    conn.close()


def load_messages(conversation_id: str) -> list[dict]:
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


def to_provider_messages(msgs: list[dict]) -> list[dict]:
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


def clear_messages(conversation_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()


def list_conversations() -> list[dict]:
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

def get_summary(conversation_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT summary, summarized_through FROM conversation_summaries WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"summary": row[0], "summarized_through": row[1]}

def save_summary(conversation_id: str, summary: str, summarized_through: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO conversation_summaries (conversation_id, summary, summarized_through)
           VALUES (?, ?, ?)
           ON CONFLICT(conversation_id) DO UPDATE SET summary = ?, summarized_through = ?""",
        (conversation_id, summary, summarized_through, summary, summarized_through),
    )
    conn.commit()
    conn.close()

def save_retrieval_trace(conversation_id: str, message: str, trace: dict, keep_last: int = 20):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO retrieval_traces (conversation_id, message, trace, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, message, json.dumps(trace), datetime.now(timezone.utc).isoformat()),
    )
    # Pure debug/introspection data — nothing in the app depends on old
    # entries surviving, so bounding per-conversation prevents unbounded
    # growth with no new scheduler/cron infrastructure needed. keep_last
    # matches get_retrieval_traces' existing default limit=20 — the read
    # side never asks for more than that anyway.
    conn.execute(
        """DELETE FROM retrieval_traces
           WHERE conversation_id = ? AND id NOT IN (
               SELECT id FROM retrieval_traces
               WHERE conversation_id = ?
               ORDER BY id DESC LIMIT ?
           )""",
        (conversation_id, conversation_id, keep_last),
    )
    conn.commit()
    conn.close()


def get_retrieval_traces(conversation_id: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT message, trace, created_at FROM retrieval_traces "
        "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [{"message": m, "trace": json.loads(t), "created_at": c} for m, t, c in rows]