import json
import os

import httpx

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")
CAPTURE_MODEL = os.getenv("CAPTURE_MODEL", "gpt-5.4-mini")

CAPTURE_PROMPT = """You extract durable facts about the user from a conversation turn.

Capture ONLY things that will still be true and useful in a future conversation:
- identity: stable facts about who they are (role, background, location)
- preference: how they like things done (style, tools, tastes)
- project: something ongoing they're working on
- decision: a specific choice they made, and why
- relationship: people or entities in their life

Do NOT capture:
- questions they asked, or the content of tasks they gave you
- topics merely discussed, rather than facts revealed about them
- anything already in the known facts list below
- transient state ("I'm tired today")

Mark provenance as "stated" only if they said it outright. If you're reading
between the lines, mark it "inferred".

Known facts already stored:
{known}

Return JSON only, no other text:
{{"units": [{{"content": "...", "unit_type": "preference", "provenance": "stated", "summary": "short plain-language note on what changed"}}]}}

Return {{"units": []}} if nothing is worth remembering."""


def _known_facts_block(units: list[dict]) -> str:
    if not units:
        return "(none yet)"
    return "\n".join(f"- {u['content']}" for u in units)


def extract_units(provider, user_message: str, assistant_message: str,
                  known: list[dict]) -> list[dict]:
    """Ask a small model what's worth remembering. Returns [] on any failure —
    capture must never break the chat."""
    prompt = CAPTURE_PROMPT.format(known=_known_facts_block(known))
    exchange = f"User: {user_message}\n\nAssistant: {assistant_message}"

    try:
        raw = "".join(provider.stream(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": exchange},
            ],
            CAPTURE_MODEL,
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return parsed.get("units", [])
    except Exception:
        return []


def commit_unit(unit: dict, source: str) -> bool:
    try:
        r = httpx.post(
            f"{MEMORY_URL}/remember",
            json={
                "content": unit["content"],
                "unit_type": unit["unit_type"],
                "provenance": unit["provenance"],
                "source": source,
                "summary": unit.get("summary", unit["content"]),
            },
            timeout=3.0,
        )
        r.raise_for_status()
        return True
    except Exception:
        return False


def capture(provider, user_message: str, assistant_message: str,
            known: list[dict], source: str) -> list[dict]:
    """Extract and store. Returns the units actually committed."""
    units = extract_units(provider, user_message, assistant_message, known)
    return [u for u in units if commit_unit(u, source)]