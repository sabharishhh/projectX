"""Single source of truth for 'what time is it right now' — injected into
every LLM call automatically via Provider.stream()/stream_with_tools()/
complete_json(), never something individual call sites have to remember to
add themselves. Computed fresh at call time, never cached, so 'now' never
goes stale across a long-running process."""

from datetime import datetime


def current_time_context() -> str:
    now = datetime.now().astimezone()
    return f"Current datetime: {now.strftime('%Y-%m-%d %H:%M %Z')}."