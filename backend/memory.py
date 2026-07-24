import os
import httpx

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")


def fetch_state() -> list[dict]:
    """Current memory units. Returns [] if the engine is unreachable —
    chat should still work without memory."""
    try:
        r = httpx.get(f"{MEMORY_URL}/state", timeout=2.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def build_system_message(units: list[dict]) -> dict | None:
    if not units:
        return None

    lines = []
    for u in units:
        # inferred facts are marked so the model treats them as tentative
        prefix = "(uncertain) " if u["provenance"] == "inferred" else ""
        lines.append(f"- [{u['unit_type']}] {prefix}{u['content']}")

    content = (
        "What you know about this user, from previous conversations:\n"
        + "\n".join(lines)
        + "\n\nUse this naturally. Don't recite it back or mention that you "
        "have stored memory unless asked."
    )
    return {"role": "system", "content": content}