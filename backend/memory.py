import os
import httpx

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")

IDENTITY = (
    "You are projectX, a personal AI assistant. You are not ChatGPT, Claude, "
    "or any other assistant — those are just models you can run on. "
    "If asked who you are, you're projectX."
)

def fetch_state() -> list[dict]:
    """Current memory units. Returns [] if the engine is unreachable —
    chat should still work without memory."""
    try:
        r = httpx.get(f"{MEMORY_URL}/state", timeout=2.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def build_system_message(units: list[dict]) -> dict:
    parts = [IDENTITY]

    if units:
        lines = []
        for u in units:
            prefix = "(uncertain) " if u["provenance"] == "inferred" else ""
            lines.append(f"- [{u['unit_type']}] {prefix}{u['content']}")
        parts.append(
            "What you know about this user, from previous conversations:\n"
            + "\n".join(lines)
            + "\n\nUse this naturally. Don't recite it back or mention that you "
            "have stored memory unless asked."
        )

    return {"role": "system", "content": "\n\n".join(parts)}