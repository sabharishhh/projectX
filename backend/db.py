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