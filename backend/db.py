import json
import sqlite3
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("db")

DB_PATH = "loki.db"


def _connect() -> sqlite3.Connection:
    """Every write path in this module opens its own short-lived
    connection rather than sharing one — safe across threads since each
    connection never leaves the thread that created it, but under
    concurrent writes (multiple chat panes hitting SQLite at once)
    SQLite's default busy_timeout of 0ms means a lock conflict raises
    immediately instead of waiting, and that exception was unhandled in
    several call sites, crashing the request. WAL mode lets reads and
    writes coexist without blocking each other in the common case; the
    busy_timeout is the backstop for the remaining write-vs-write case,
    so a transient lock waits up to 10s instead of failing instantly."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db():
    conn = _connect()
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

    # Full-text search over raw turn content — closes the gap where
    # something relevant fell out of WINDOW_MESSAGES and got lost in the
    # rolling summary's lossy compression. Standalone (not external-
    # content) FTS5 table: simpler trigger semantics, and message content
    # is effectively append-only (activity gets patched, content never
    # does), so there's no update-sync case to handle.
    fts_existed = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
    ).fetchone()
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content, conversation_id UNINDEXED, message_id UNINDEXED
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content, conversation_id, message_id)
            VALUES (new.id, new.content, new.conversation_id, new.id);
        END
    """)
    if not fts_existed:
        # First-ever creation only — backfill every message that predates
        # the index, since the trigger above only fires on new inserts.
        conn.execute("""
            INSERT INTO messages_fts(rowid, content, conversation_id, message_id)
            SELECT id, content, conversation_id, id FROM messages
        """)
        logger.info("messages_fts created — backfilled existing message history")

    conn.commit()
    conn.close()


def load_messages(conversation_id: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content, activity, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    conn.close()
    out = []
    for role, content, activity, created_at in rows:
        msg = {"role": role, "content": content, "created_at": created_at}
        if activity:
            msg["activity"] = json.loads(activity)
        out.append(msg)
    return out


def to_provider_messages(msgs: list[dict]) -> list[dict]:
    """Strip UI-only fields (activity) before sending to the model."""
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def save_message(conversation_id: str, role: str, content: str, activity: list | None = None) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, activity, created_at) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, role, content, json.dumps(activity) if activity else None,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    message_id = cur.lastrowid
    conn.close()
    return message_id

def update_message_activity(message_id: int, activity: list | None):
    """Patches an already-saved message's activity in place — used when
    capture/forget/resolution add events after the initial early-save,
    so the turn ends up as one row with the final activity, not two rows."""
    conn = _connect()
    conn.execute(
        "UPDATE messages SET activity = ? WHERE id = ?",
        (json.dumps(activity) if activity else None, message_id),
    )
    conn.commit()
    conn.close()



def search_messages(query: str, conversation_id: str | None = None, limit: int = 6) -> list[dict]:
    """FTS5 keyword search over raw turn content — scope=None searches
    every conversation (the cross-chat case), scope=<id> searches only
    that one (the long-single-conversation case). Same underlying index
    either way; which one gets used is a caller decision, not a schema
    one — deliberately not turned on for true cross-chat yet, since that
    needs its own scope decision (search everything vs. recent chats
    only), not just a missing filter."""
    conn = _connect()
    terms = [w.strip() for w in query.split() if w.strip()]
    if not terms:
        conn.close()
        return []
    fts_query = " OR ".join(f'"{t}"' for t in terms)

    sql = """
        SELECT m.conversation_id, m.role, m.content, m.created_at
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.message_id
        WHERE messages_fts MATCH ?
    """
    params = [fts_query]
    if conversation_id is not None:
        sql += " AND m.conversation_id = ?"
        params.append(conversation_id)
    sql += " ORDER BY bm25(messages_fts) LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        logger.warning(f"search_messages failed for query={query!r}: {e!r}")
        rows = []
    conn.close()
    return [{"conversation_id": r[0], "role": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def clear_messages(conversation_id: str):
    conn = _connect()
    conn.execute("DELETE FROM messages_fts WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.commit()
    conn.close()


def list_conversations() -> list[dict]:
    conn = _connect()
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

def _ensure_pending_table():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_state (
            kind TEXT NOT NULL,
            id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (kind, id)
        )
    """)
    conn.commit()
    conn.close()


def load_pending(kind: str) -> dict[str, dict]:
    """All not-yet-resolved conflict/forget entries of a given kind,
    keyed by id — used once at startup to rehydrate PENDING/PENDING_FORGETS
    after a restart."""
    _ensure_pending_table()
    conn = _connect()
    rows = conn.execute("SELECT id, payload FROM pending_state WHERE kind = ?", (kind,)).fetchall()
    conn.close()
    return {id_: json.loads(payload) for id_, payload in rows}


def save_pending(kind: str, id_: str, payload: dict):
    _ensure_pending_table()
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO pending_state (kind, id, payload, created_at) VALUES (?, ?, ?, datetime('now'))",
        (kind, id_, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def delete_pending(kind: str, id_: str):
    _ensure_pending_table()
    conn = _connect()
    conn.execute("DELETE FROM pending_state WHERE kind = ? AND id = ?", (kind, id_))
    conn.commit()
    conn.close()

def mark_conflict_status(conversation_id: str, conflict_id: str, resolution: str) -> bool:
    """Find the message that raised this conflict and record how it was
    resolved, so a reload reflects the true state instead of re-showing it
    as pending. Returns True if a matching event was found and patched."""
    conn = _connect()
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
    conn = _connect()
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
    conn = _connect()
    row = conn.execute(
        "SELECT summary, summarized_through FROM conversation_summaries WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"summary": row[0], "summarized_through": row[1]}

def save_summary(conversation_id: str, summary: str, summarized_through: int):
    conn = _connect()
    conn.execute(
        """INSERT INTO conversation_summaries (conversation_id, summary, summarized_through)
           VALUES (?, ?, ?)
           ON CONFLICT(conversation_id) DO UPDATE SET summary = ?, summarized_through = ?""",
        (conversation_id, summary, summarized_through, summary, summarized_through),
    )
    conn.commit()
    conn.close()

def save_retrieval_trace(conversation_id: str, message: str, trace: dict, keep_last: int = 20):
    conn = _connect()
    conn.execute(
        "INSERT INTO retrieval_traces (conversation_id, message, trace, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, message, json.dumps(trace), datetime.now(timezone.utc).isoformat()),
    )
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
    conn = _connect()
    rows = conn.execute(
        "SELECT message, trace, created_at FROM retrieval_traces "
        "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [{"message": m, "trace": json.loads(t), "created_at": c} for m, t, c in rows]

def mark_commitment_resolution_status(conversation_id: str, resolution_id: str, resolution: str) -> bool:
    """Same persistence pattern as mark_conflict_status/mark_forget_status —
    writes the resolution onto the stored message's activity so a
    confirmed/declined commitment resolution survives reload instead of
    reappearing as pending."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, activity FROM messages WHERE conversation_id = ? AND activity IS NOT NULL",
        (conversation_id,),
    ).fetchall()
    for row_id, activity_json in rows:
        events = json.loads(activity_json)
        changed = False
        for ev in events:
            if ev.get("kind") == "commitment_resolution_request" and ev.get("id") == resolution_id:
                ev["resolved"] = resolution
                changed = True
        if changed:
            conn.execute("UPDATE messages SET activity = ? WHERE id = ?", (json.dumps(events), row_id))
            conn.commit()
            conn.close()
            return True
    conn.close()
    return False