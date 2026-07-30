"""Time-travel query eval cases — the ambiguous-date fallback fix and
the historical-override behavior, consolidated from tonight's isolated
test script."""

import json
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

import chat_engine
from eval.framework import case


def _run_turn(conversation_id: str, message: str) -> list[dict]:
    events = []
    for raw in chat_engine.stream_chat(conversation_id, message):
        events.append(json.loads(raw.removeprefix("data: ").strip()))
    return events


def _kinds(events: list[dict], event_type: str) -> list[str]:
    return [e["event"]["kind"] for e in events if e["type"] == event_type]


def _full_text(events: list[dict]) -> str:
    return "".join(e["value"] for e in events if e["type"] == "text")


@case("time_travel_no_crash_ordinary", "time_travel", "plain message must never hit the time-travel path")
def _ordinary():
    conv = f"eval-tt-{uuid.uuid4().hex[:8]}"
    events = _run_turn(conv, "hey, how's it going")
    return not any(e["type"] == "error" for e in events), "unexpected error on plain message"


@case("time_travel_resolves_vague_date", "time_travel",
      "'used to' with no explicit date must resolve a fallback target, not None")
def _vague_resolves():
    conv = f"eval-tt-{uuid.uuid4().hex[:8]}"
    _run_turn(conv, "remember that my favorite programming language is Python")
    time.sleep(1.5)
    _run_turn(conv, "actually my favorite programming language is now Rust")
    events = _run_turn(conv, "what did I used to say my favorite programming language was?")
    fired = "time_travel" in _kinds(events, "activity")
    return fired, "time_travel activity did not fire for vague-but-genuine retrospective query"


@case("time_travel_surfaces_old_fact", "time_travel", "must answer with the OLD fact, not the current one")
def _surfaces_old():
    conv = f"eval-tt-{uuid.uuid4().hex[:8]}"
    _run_turn(conv, "remember that my favorite color is teal")
    time.sleep(1.5)
    _run_turn(conv, "actually my favorite color is now crimson")
    events = _run_turn(conv, "what did I used to say my favorite color was?")
    reply = _full_text(events).lower()
    return "teal" in reply, f"reply did not mention the historical fact: {reply!r}"


@case("time_travel_present_tense_not_triggered", "time_travel",
      "'as of today' must not misfire as a time-travel query")
def _present_tense():
    conv = f"eval-tt-{uuid.uuid4().hex[:8]}"
    _run_turn(conv, "remember that I live in Kochi")
    events = _run_turn(conv, "what is my current city, as of today?")
    fired = "time_travel" in _kinds(events, "activity")
    return not fired, "incorrectly triggered time_travel for a present-tense query"


@case("time_travel_no_history_graceful", "time_travel", "no matching history must not crash the turn")
def _no_history():
    conv = f"eval-tt-{uuid.uuid4().hex[:8]}"
    events = _run_turn(conv, "what did I used to think about my career back in 2020?")
    return not any(e["type"] == "error" for e in events), "error on a time-travel query with nothing to find"