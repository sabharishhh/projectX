"""chat_engine.py orchestration eval cases — the error-abort path is the
most structurally important case in this file: it proves a mid-reply
failure stops the ENTIRE turn (no capture, no persistence, no "done"),
matching the original pre-refactor behavior exactly. Verified via
deterministic monkeypatching, not hoping a real API call fails."""

import json
import uuid

import chat_engine
from eval.framework import case


def _run_turn(conversation_id: str, message: str) -> list[dict]:
    events = []
    for raw in chat_engine.stream_chat(conversation_id, message):
        events.append(json.loads(raw.removeprefix("data: ").strip()))
    return events


@case("chat_engine_plain_message_clean", "chat_engine", "ordinary message must complete cleanly")
def _plain():
    conv = f"eval-ce-{uuid.uuid4().hex[:8]}"
    events = _run_turn(conv, "hey, how's it going")
    no_error = not any(e["type"] == "error" for e in events)
    has_done = any(e["type"] == "done" for e in events)
    done_last = events[-1]["type"] == "done" if events else False
    ok = no_error and has_done and done_last
    return ok, f"error={not no_error} done_present={has_done} done_last={done_last}"


@case("chat_engine_error_aborts_entire_turn", "chat_engine",
      "a reply-generation error must stop the turn completely — no capture/forget/done after it")
def _error_abort():
    conv = f"eval-ce-{uuid.uuid4().hex[:8]}"

    original_stream = chat_engine.provider.stream
    original_stream_with_tools = getattr(chat_engine.provider, "stream_with_tools", None)

    def _broken_stream(*args, **kwargs):
        raise RuntimeError("deliberate eval failure")
        yield  # unreachable, keeps this a generator

    chat_engine.provider.stream = _broken_stream
    if original_stream_with_tools is not None:
        chat_engine.provider.stream_with_tools = _broken_stream

    try:
        events = _run_turn(conv, "this should fail deliberately")
    finally:
        chat_engine.provider.stream = original_stream
        if original_stream_with_tools is not None:
            chat_engine.provider.stream_with_tools = original_stream_with_tools

    has_error = any(e["type"] == "error" for e in events)
    no_done = not any(e["type"] == "done" for e in events)
    no_side_effects = not any(
        e["type"] == "activity" and e["event"]["kind"] in ("memory_write", "conflict", "forget_request")
        for e in events
    )
    error_is_last = events and events[-1]["type"] == "error"

    ok = has_error and no_done and no_side_effects and error_is_last
    return ok, f"error={has_error} no_done={no_done} no_side_effects={no_side_effects} error_last={error_is_last}"