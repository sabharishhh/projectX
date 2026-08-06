"""Per-conversation debug/documentation log — one markdown file per
conversation, appended each turn. Deliberately compact: full detail (search
result text, retrieval scores, ledger entries) already lives in the DB and
ledger; this file exists to be skimmed by a human or pasted into an LLM
context without burning tokens on redundant detail."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("chatlog")

LOG_DIR = Path(os.getenv("CHAT_LOG_DIR", "logs/chats"))
MAX_RESPONSE_CHARS = 2200


def _summarize_activity(activity_log: list[dict]) -> list[str]:
    lines = []
    for a in activity_log:
        kind = a.get("kind")
        if kind in ("skill", "source", "correction_check"):
            continue  # skill logged separately; source is citation bookkeeping;
                       # correction_check is a transient "checking..." indicator
                       # with nothing left to say once the turn has completed
        elif kind == "memory_read":
            lines.append(f"recalled {len(a.get('units', []))} facts")
        elif kind == "memory_write":
            contents = "; ".join(u.get("content", "") for u in a.get("units", []))
            lines.append(f"remembered {len(a.get('units', []))} things: {contents}")
        elif kind == "tool_step":
            lines.append(a.get("label", "tool step"))
        elif kind == "search":
            lines.append(f"read {len(a.get('results', []))} pages: {a.get('label', '')}")
        elif kind == "search_failed":
            lines.append("search failed — no pages read")
        elif kind == "conflict":
            lines.append(f"conflict: '{a.get('old', {}).get('content', '')}' vs '{a.get('new', {}).get('content', '')}'")
        elif kind == "forget_request":
            lines.append(f"forget requested: {a.get('content', '')}")
        elif kind == "duplicate_skipped":
            lines.append(f"duplicate skipped: {a.get('content', '')}")
        elif kind == "time_travel":
            lines.append(f"{a.get('label', 'time travel')} ({len(a.get('units', []))} facts as of that point)")
        elif kind == "commitments_due":
            lines.append(f"{len(a.get('units', []))} commitment(s) surfaced as due soon")
        elif kind == "commitment_resolution_request":
            lines.append(f"proposed {a.get('status', '?')}: {a.get('content', '')}")
        elif kind == "reasoning":
            lines.append(f"reasoning: {a.get('label', '')}")
    return lines


def _collect_sources(activity_log: list[dict]) -> list[str]:
    urls = []
    for a in activity_log:
        if a.get("kind") == "source" and a.get("url"):
            urls.append(a["url"])
        elif a.get("kind") == "search":
            urls.extend(r["url"] for r in a.get("results", []) if r.get("url"))
    return list(dict.fromkeys(urls))  # de-dupe, preserve first-fetched/first-listed order


def log_turn(conversation_id: str, message: str, skill: dict | None,
             injected: list[dict], activity_log: list[dict], full_response: str,
             duration_seconds: float | None = None,
             sufficiency: dict | None = None) -> None:
    """duration_seconds and sufficiency are both values the caller already
    computed during the turn (a time.monotonic() diff, and
    check_reply_sufficiency's own result dict) — passed through for
    logging, not recomputed here, so this adds no real overhead beyond a
    couple of string formats and one file append, same as before."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)

        # 1. Search for an existing log file linked to this conversation ID
        existing_files = list(LOG_DIR.glob(f"*_{conversation_id}.md"))

        if existing_files:
            # If found, use the existing file (keeps appending to the same session)
            path = existing_files[0]
        else:
            # If not found (first turn), create a new timestamped file
            file_ts = now.strftime("%Y-%m-%d_%H-%M-%S")
            path = LOG_DIR / f"{file_ts}_{conversation_id}.md"

        # 2. Format the standard timestamp for the markdown block header
        ts = now.strftime("%Y-%m-%d %H:%M:%SZ")
        header = f"## {ts}" + (f" ({duration_seconds:.1f}s)" if duration_seconds is not None else "")

        skill_line = skill["name"] if skill else "none"
        recalled = ", ".join(u["content"] for u in injected[:5]) or "none"
        if len(injected) > 5:
            recalled += f" (+{len(injected) - 5} more)"
        activity_lines = _summarize_activity(activity_log)
        sources = _collect_sources(activity_log)
        response = full_response.strip()
        if len(response) > MAX_RESPONSE_CHARS:
            response = response[:MAX_RESPONSE_CHARS] + "… [truncated, full text in DB]"

        entry = [
            header,
            f"**User:** {message.strip()}",
            f"**Skill:** {skill_line}",
            f"**Recalled:** {recalled}",
        ]
        if activity_lines:
            entry.append("**Activity:** " + "; ".join(activity_lines))
        if sources:
            entry.append("**Sources:** " + ", ".join(sources))
        if sufficiency and sufficiency.get("verdict"):
            suff_line = f"**Sufficiency:** {sufficiency['verdict']}"
            if sufficiency.get("reason"):
                suff_line += f" — {sufficiency['reason']}"
            entry.append(suff_line)
        entry += [f"**Response:** {response}", "", "---", ""]

        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(entry) + "\n")
    except Exception as e:
        # logging must never break a chat turn — same defensive pattern as
        # everything else in this codebase (search failures, MEMORY_URL warmup).
        logger.warning(f"log_turn failed: {e!r}")