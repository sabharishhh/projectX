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

For each fact, also decide which branch it belongs on, from this list:
{branches}
Use "main" unless the fact is clearly and specifically about one of the other
listed domains. Never invent a branch name not in this list.

Known facts already stored:
{known}

If a new fact DIRECTLY CONTRADICTS one of the known facts above — same subject,
different value — add "supersedes": "<the 8-char id in brackets>" to that unit.
Only for real contradictions, where both cannot be true at once. Do NOT use it
for facts that merely relate to, extend, or sit alongside an existing one.

Return JSON only, no other text:
{{"units": [{{"content": "...", "unit_type": "preference", "provenance": "stated", "summary": "short plain-language note on what changed", "branch": "main", "supersedes": "a1b2c3d4"}}]}}

Omit "supersedes" entirely when the fact is new rather than a replacement.
Return {{"units": []}} if nothing is worth remembering."""


def _known_facts_block(units: list[dict]) -> str:
    if not units:
        return "(none yet)"
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)


def extract_units(provider, user_message: str, assistant_message: str,
                  known: list[dict], branches: list[str]) -> list[dict]:
    prompt = CAPTURE_PROMPT.format(
        known=_known_facts_block(known),
        branches=", ".join(branches),
    )
    exchange = f"User: {user_message}\n\nAssistant: {assistant_message}"

    try:
        raw = "".join(provider.stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": exchange}],
            os.getenv("CAPTURE_MODEL", "gpt-5.4-mini"),
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        units = parsed.get("units", [])
        for u in units:
            if u.get("branch") not in branches:
                u["branch"] = "main"
        return units
    except Exception:
        return []


def commit_unit(unit: dict, source: str, branch: str = "main") -> bool:
    try:
        r = httpx.post(
            f"{MEMORY_URL}/remember",
            json={
                "content": unit["content"],
                "unit_type": unit["unit_type"],
                "provenance": unit["provenance"],
                "source": source,
                "summary": unit.get("summary", unit["content"]),
                "branch": branch,
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

def supersede_unit(from_hash: str, unit: dict, source: str, branch: str = "main") -> bool:
    try:
        r = httpx.post(
            f"{MEMORY_URL}/supersede",
            json={
                "from": from_hash,
                "content": unit["content"],
                "unit_type": unit["unit_type"],
                "provenance": unit["provenance"],
                "source": source,
                "summary": unit.get("summary", unit["content"]),
                "branch": branch,
            },
            timeout=3.0,
        )
        r.raise_for_status()
        return True
    except Exception:
        return False