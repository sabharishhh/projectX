import sqlite3
from datetime import datetime, timezone

LEDGER_DB = "projectx.db"  # same file as messages, separate table


def init_ledger():
    conn = sqlite3.connect(LEDGER_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log(event_type: str, description: str, source: str, actor: str = "system"):
    """Append-only — this table is never updated or deleted from,
    only ever inserted into. That's what makes it trustworthy."""
    conn = sqlite3.connect(LEDGER_DB)
    conn.execute(
        "INSERT INTO ledger (event_type, description, source, actor, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_type, description, source, actor, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def recent(limit: int = 50):
    conn = sqlite3.connect(LEDGER_DB)
    rows = conn.execute(
        "SELECT event_type, description, source, actor, created_at "
        "FROM ledger ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"event_type": r[0], "description": r[1], "source": r[2], "actor": r[3], "created_at": r[4]}
        for r in rows
    ]