"""Capture-layer eval cases — false-positive exclusions and basic
extraction correctness, consolidated from tonight's isolated test
scripts into the standing suite."""

from dotenv import load_dotenv
load_dotenv()

from providers import get_provider
from capture import extract_units
from eval.framework import case

provider, model = get_provider()
BRANCH = "eval-capture"


@case("assistant_identity_rejected", "capture", "who are you / who created you must not be captured")
def _assistant_identity():
    for msg in ["who created you?", "what's your name?", "who are you"]:
        units = extract_units(provider, msg, "I'm projectX, created by Sabharish.", known=[], branches=[BRANCH])
        if any(u.get("unit_type") != "commitment" for u in units):
            return False, f"wrongly captured for {msg!r}: {units}"
    return True


@case("hypothetical_commitment_rejected", "capture", "hypothetical phrasing must not be a real commitment")
def _hypothetical():
    units = extract_units(provider, "I would follow up with him if he replies", "Understood.", known=[], branches=[BRANCH])
    commits = [u for u in units if u.get("unit_type") == "commitment"]
    return len(commits) == 0, f"got: {commits}"


@case("past_tense_reflection_rejected", "capture", "past-tense reflection must not be a real commitment")
def _past_tense():
    units = extract_units(provider, "I should have followed up last week", "That happens.", known=[], branches=[BRANCH])
    commits = [u for u in units if u.get("unit_type") == "commitment"]
    return len(commits) == 0, f"got: {commits}"


@case("explicit_remember_captured", "capture", "explicit 'remember that' is an unconditional instruction")
def _explicit_remember():
    units = extract_units(provider, "remember that I was born in Kochi", "Noted.", known=[], branches=[BRANCH])
    return len(units) >= 1, f"got: {units}"


@case("multi_commitment_split", "capture", "distinct actions with a shared deadline must split, not fuse")
def _multi_split():
    units = extract_units(
        provider, "I'll text Jamie about the venue and also confirm the caterer by Thursday",
        "Got both.", known=[], branches=[BRANCH],
    )
    commits = [u for u in units if u.get("unit_type") == "commitment"]
    return len(commits) == 2, f"got: {commits}"


# --- Granular identity-family cases, from test_capture_verify.py ---
# Each phrasing kept separate rather than bundled, so a scorecard shows
# exactly which wording regresses, not just "the group failed."

_IDENTITY_PHRASINGS = [
    ("who created you?", "I was created by Sabharish."),
    ("who made you", "Sabharish built me."),
    ("who built you?", "I was built by Sabharish."),
    ("what's your name?", "I'm projectX."),
    ("what are you called", "My name is projectX."),
    ("who are you", "I'm projectX, your personal AI assistant."),
    ("are you an AI made by Sabharish?", "Yes, I'm projectX, and Sabharish created me."),
]


def _make_identity_case(user_msg, assistant_msg):
    def _fn():
        units = extract_units(provider, user_msg, assistant_msg, known=[], branches=[BRANCH])
        return len(units) == 0, f"got: {units}"
    return _fn


for _i, (_u, _a) in enumerate(_IDENTITY_PHRASINGS, 1):
    case(f"identity_phrasing_{_i}", "capture", f"{_u!r} must not be captured")(_make_identity_case(_u, _a))


@case("legitimate_name_captured", "capture", "a real name statement must be captured")
def _legit_name():
    units = extract_units(provider, "my name is Arjun", "Nice to meet you, Arjun.", known=[], branches=[BRANCH])
    return len(units) >= 1, f"got: {units}"


@case("legitimate_project_captured", "capture", "a real project statement must be captured")
def _legit_project():
    units = extract_units(provider, "I created a new project called Nightjar", "Got it — I'll remember that.", known=[], branches=[BRANCH])
    return len(units) >= 1, f"got: {units}"