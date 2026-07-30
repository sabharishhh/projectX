"""Forgetting-pipeline eval cases — the three-stage pattern/search/
confirm design, the trigger-word stem fix, and the trap-fact scoping,
consolidated from tonight's rewritten test script."""

import uuid

from dotenv import load_dotenv
load_dotenv()

import httpx
from providers import get_provider
from memory import fetch_state
import forgetting
from eval.framework import case

provider, model = get_provider()
BRANCH = f"eval-forgetting-{uuid.uuid4().hex[:8]}"


def _seed(content: str, unit_type: str = "preference") -> None:
    httpx.post("http://127.0.0.1:8100/remember", json={
        "content": content, "unit_type": unit_type, "provenance": "stated",
        "source": "eval-forgetting", "summary": content, "branch": BRANCH,
    }, timeout=15.0)


_seeded = False


def _seed_once():
    global _seeded
    if _seeded:
        return
    _seed("User enjoys watching Christopher Nolan movies.")
    _seed("User likes Quentin Tarantino films.")
    _seed("User's favorite actor is Cillian Murphy.")
    _seed("User works as a data analyst at a fintech startup.")
    _seed("User is planning a trip to Japan in December.")
    _seed("User prefers dark roast coffee.")
    _seeded = True


def _known():
    return [{**u, "branch": BRANCH} for u in fetch_state(BRANCH)]


@case("forget_broad_pattern_catches_related", "forgetting", "broad 'movies' query must catch the movie cluster")
def _broad_catches():
    _seed_once()
    matches = forgetting.detect_forget_request(provider, "forget stuff about movies", _known(), [BRANCH])
    contents = [m["unit"]["content"] for m in matches]
    ok = any("Nolan" in c for c in contents) and any("Tarantino" in c for c in contents)
    return ok, f"got: {contents}"


@case("forget_excludes_unrelated", "forgetting", "broad 'movies' query must NOT catch unrelated facts")
def _excludes_unrelated():
    _seed_once()
    matches = forgetting.detect_forget_request(provider, "forget stuff about movies", _known(), [BRANCH])
    contents = [m["unit"]["content"] for m in matches]
    leaked = any("data analyst" in c for c in contents) or any("Japan" in c for c in contents)
    return not leaked, f"unrelated fact leaked into match: {contents}"


@case("forget_trap_fact_scoped_correctly", "forgetting",
      "Cillian Murphy excluded from broad query, but reachable when explicitly targeted")
def _trap_scoping():
    _seed_once()
    known = _known()
    broad = forgetting.detect_forget_request(provider, "forget stuff about movies", known, [BRANCH])
    broad_contents = [m["unit"]["content"] for m in broad]
    if any("Cillian Murphy" in c for c in broad_contents):
        return False, "trap fact wrongly swept into broad query"

    targeted = forgetting.detect_forget_request(
        provider, "I don't like Cillian Murphy anymore, forget that", known, [BRANCH],
    )
    targeted_contents = [m["unit"]["content"] for m in targeted]
    return any("Cillian Murphy" in c for c in targeted_contents), f"targeted query missed it: {targeted_contents}"


@case("forget_unrelated_message_no_match", "forgetting", "non-forget message must produce zero matches")
def _no_match_unrelated():
    _seed_once()
    matches = forgetting.detect_forget_request(provider, "what's the weather today", _known(), [BRANCH])
    return len(matches) == 0, f"got: {matches}"


@case("forget_natural_phrasing_trigger_stem", "forgetting",
      "'drop the memory...' must match — the original single-word-stem bug")
def _natural_phrasing():
    _seed_once()
    matches = forgetting.detect_forget_request(
        provider, "drop the memory related to my coffee preference", _known(), [BRANCH],
    )
    contents = [m["unit"]["content"] for m in matches]
    return any("coffee" in c for c in contents), f"got: {contents}"


@case("forget_prefilter_fires_on_explicit_request", "forgetting", "mentions_forgetting must fire on real forget language")
def _prefilter_fires():
    return forgetting.mentions_forgetting("please forget my old job"), "prefilter did not fire"


@case("forget_prefilter_fires_on_drop_stem", "forgetting", "mentions_forgetting must fire on the broadened 'drop' stem")
def _prefilter_drop():
    return forgetting.mentions_forgetting("can you drop that fact"), "prefilter did not fire on 'drop'"


@case("forget_never_stated_no_confident_match", "forgetting", "a fact that was never stated must produce zero matches")
def _never_stated():
    _seed_once()
    matches = forgetting.detect_forget_request(
        provider, "forget my interest in astronomy", _known(), [BRANCH],
    )
    return len(matches) == 0, f"got: {matches}"