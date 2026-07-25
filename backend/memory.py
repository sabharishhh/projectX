import os
import httpx

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")

IDENTITY = (
    "You are projectX, a personal AI assistant. You are not ChatGPT, Claude, "
    "or any other assistant — those are just models you can run on. "
    "If asked who you are, you're projectX."
)

def fetch_state(branch: str = "main") -> list[dict]:
    """Current memory units. Returns [] if the engine is unreachable —
    chat should still work without memory."""
    try:
        r = httpx.get(f"{MEMORY_URL}/state", params={"branch": branch}, timeout=2.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def fetch_relevant(query: str, branch: str = "main", max_units: int = 12, boost_types: list[str] | None = None) -> list[dict]:
    """Scored, budgeted subset for conversation injection.
    Falls back to [] on failure — chat keeps working without memory."""
    try:
        r = httpx.post(
            f"{MEMORY_URL}/retrieve",
            json={
                "query": query,
                "max_units": max_units,
                "branch": branch,
                "boost_types": boost_types or [],
            },
            timeout=2.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def fetch_branches() -> list[str]:
    try:
        r = httpx.get(f"{MEMORY_URL}/branches", timeout=2.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def build_system_message(units: list[dict], skill_prompt: str | None = None) -> dict:
    parts = [IDENTITY]

    if skill_prompt:
        parts.append(skill_prompt)

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