import json
from state import CAPTURE_MODEL

CANONICAL_DOMAINS = ["work", "personal"]

DOMAIN_PROMPT = """Classify which domain this message belongs to, for routing memory.
Choose exactly one:

- "main" — general facts about the person that aren't specific to one life
  context: identity, broad preferences, communication style
- "work" — anything about their job, employer, colleagues, professional
  projects, or career
- "personal" — anything about their life outside work: family, friends,
  pets, home, hobbies, health, relationships, plans, or personal time
{extra}

Lean toward "work" or "personal" whenever the message is clearly about that
part of someone's life, even if it's brief or casual — a passing mention of
a pet, a family member, or a hobby is still personal-domain, not "main".
Reserve "main" for facts that are genuinely context-free — the kind of thing
true regardless of whether the conversation is about work or personal life
(e.g. "prefers short answers", "is named Alex").

Return JSON only: {{"domain": "main"}}"""


def infer_domain(provider, message: str, existing_branches: list[str]) -> str:
    """Which branch this turn's memory should be read from, beyond main."""
    extras = [b for b in existing_branches if b not in ("main", *CANONICAL_DOMAINS)]
    extra_line = "\n".join(f'- "{b}" — an existing custom branch' for b in extras)
    prompt = DOMAIN_PROMPT.format(extra=extra_line)

    try:
        raw = "".join(provider.stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": message}],
            CAPTURE_MODEL,
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        domain = parsed.get("domain", "main")
        allowed = {"main", *CANONICAL_DOMAINS, *existing_branches}
        return domain if domain in allowed else "main"
    except Exception:
        return "main"