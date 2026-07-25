import json
import os
import tomllib
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
SKILL_MODEL = os.getenv("CAPTURE_MODEL", "gpt-5.4-mini")


def load_skills() -> dict[str, dict]:
    """Read every .toml in skills/. A malformed file is skipped, not fatal."""
    skills = {}
    if not SKILLS_DIR.exists():
        return skills

    for path in sorted(SKILLS_DIR.glob("*.toml")):
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            name = data.get("name") or path.stem
            skills[name] = {
                "name": name,
                "description": data.get("description", ""),
                "system_prompt": data.get("system_prompt", "").strip(),
                "tools": data.get("tools", []),
                "boost_types": data.get("boost_types", []),
            }
        except Exception:
            continue
    return skills


SKILLS = load_skills()


SKILL_SELECT_PROMPT = """Pick the single skill that best fits what the user is asking for,
or none if no skill clearly applies.

Available skills:
{listing}

Most messages need no skill — only pick one when the request clearly matches.
Casual conversation, quick questions, and coding help need no skill.

Return JSON only:
{{"skill": "name"}}
or
{{"skill": null}}"""


def select(provider, message: str) -> dict | None:
    """Returns the matching skill config, or None."""
    if not SKILLS:
        return None

    listing = "\n".join(f"- {s['name']}: {s['description']}" for s in SKILLS.values())
    try:
        raw = "".join(provider.stream(
            [
                {"role": "system", "content": SKILL_SELECT_PROMPT.format(listing=listing)},
                {"role": "user", "content": message},
            ],
            SKILL_MODEL,
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return SKILLS.get(parsed.get("skill")) if parsed.get("skill") else None
    except Exception:
        return None


def allows(skill: dict | None, tool: str) -> bool:
    """No active skill = default permissions (everything allowed)."""
    if skill is None:
        return True
    return tool in skill.get("tools", [])