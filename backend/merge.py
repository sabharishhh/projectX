import json
import os

from memory_client import client
from memory import invalidate_state_cache

MERGE_COMPARE_PROMPT = """Compare two sets of memory facts about the same person —
one from branch "{from_branch}", one from branch "{into_branch}".

Facts only on {from_branch} (incoming):
{incoming}

Facts already on {into_branch} (existing):
{existing}

Find pairs that DIRECTLY CONFLICT — same subject, different value, both cannot
be true at once. Most incoming facts will NOT conflict with anything; those
should just be adopted as-is. Only flag genuine contradictions.

Return JSON only:
{{"conflicts": [{{"incoming_hash": "...", "existing_hash": "...", "reason": "one line"}}]}}

Return {{"conflicts": []}} if nothing conflicts."""


def preview(from_branch: str, into_branch: str) -> dict:
    r = client.get("/merge/preview", params={"from": from_branch, "into": into_branch})
    r.raise_for_status()
    return r.json()


def _facts_block(units: list[dict]) -> str:
    if not units:
        return "(none)"
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)


def find_conflicts(provider, from_branch: str, into_branch: str,
                    incoming: list[dict], existing: list[dict]) -> list[dict]:
    if not incoming or not existing:
        return []

    prompt = MERGE_COMPARE_PROMPT.format(
        from_branch=from_branch,
        into_branch=into_branch,
        incoming=_facts_block(incoming),
        existing=_facts_block(existing),
    )
    try:
        raw = "".join(provider.stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": "Compare."}],
            os.getenv("CAPTURE_MODEL", "gpt-5.6-luna"),
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        pairs = parsed.get("conflicts", [])
    except Exception:
        return []

    resolved = []
    for p in pairs:
        if not isinstance(p, dict):
            continue
        incoming_hash = p.get("incoming_hash")
        existing_hash = p.get("existing_hash")
        if not incoming_hash or not existing_hash:
            continue
        inc = next((u for u in incoming if u["hash"].startswith(incoming_hash)), None)
        exi = next((u for u in existing if u["hash"].startswith(existing_hash)), None)
        if inc and exi:
            resolved.append({"incoming": inc, "existing": exi, "reason": p.get("reason", "")})
    return resolved


def apply(from_branch: str, into_branch: str, adopt: list[str],
          replace: list[dict], source: str, summary: str) -> dict:
    r = client.post("/merge/apply", json={
        "from": from_branch, "into": into_branch,
        "adopt": adopt, "replace": replace,
        "source": source, "summary": summary,
    })
    r.raise_for_status()
    invalidate_state_cache(into_branch)
    return r.json()