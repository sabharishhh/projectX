import os

from dotenv import load_dotenv
load_dotenv()

from providers import get_provider

provider, model = get_provider()

# Reasoning effort for the main chat reply specifically — background calls
# (capture, forget-detection, skill-select, search-decision) intentionally
# stay at stream()'s "none" default; only this one call site opts in.
MAIN_REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")

# The model used for cheap background calls (skill selection, capture,
# domain classification, forget-detection, search-decision, distillation).
# Under local mode there's no universal cheap fallback that would exist on
# an arbitrary local server, so default to the same model as the main chat
# unless explicitly overridden — never silently fall back to a cloud model
# name that doesn't exist on the active provider.
CAPTURE_MODEL = os.getenv("CAPTURE_MODEL") or (
    model if os.getenv("PROVIDER") == "local" else "gpt-5.4-mini"
)

# conflicts/forgets awaiting the user's decision (in-process; lost on restart)
PENDING: dict[str, dict] = {}
PENDING_FORGETS: dict[str, dict] = {}