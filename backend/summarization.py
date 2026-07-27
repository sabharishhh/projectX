import json

from state import CAPTURE_MODEL
import db

WINDOW_MESSAGES = 12
TRIGGER_BUFFER = 6

SUMMARIZE_PROMPT = """Update the rolling summary of this conversation with the
new messages below. Keep it to a few sentences — open threads, decisions
made, things still in progress. Not a transcript, not verbatim quotes.

Existing summary:
{existing}

New messages to fold in:
{new_messages}

Return the updated summary as plain text, nothing else."""


def _format_messages(msgs: list[dict]) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in msgs)


def get_current_summary(conversation_id: str) -> str | None:
    row = db.get_summary(conversation_id)
    return row["summary"] if row else None


def maybe_update_summary(provider, conversation_id: str, full_history: list[dict]) -> str | None:
    """full_history includes every message so far, this turn's included.
    No-ops (cheaply, no LLM call) unless enough new messages have aged
    past the visible window to be worth a fold-in call."""
    row = db.get_summary(conversation_id)
    existing = row["summary"] if row else None
    summarized_through = row["summarized_through"] if row else 0

    aged_out_end = max(0, len(full_history) - WINDOW_MESSAGES)
    new_batch = full_history[summarized_through:aged_out_end]

    if len(new_batch) < TRIGGER_BUFFER:
        return existing

    try:
        raw = "".join(provider.stream(
            [{"role": "system", "content": SUMMARIZE_PROMPT.format(
                existing=existing or "(none yet)",
                new_messages=_format_messages(new_batch),
            )}],
            CAPTURE_MODEL,
        ))
        updated = raw.strip()
        db.save_summary(conversation_id, updated, aged_out_end)
        return updated
    except Exception:
        return existing  # keep the old summary rather than losing it on a bad call