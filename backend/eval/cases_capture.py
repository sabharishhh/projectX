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