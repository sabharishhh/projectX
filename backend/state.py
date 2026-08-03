import os
import db

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
    model if os.getenv("PROVIDER") == "local" else "gpt-5.6-luna"
)

class PersistentPendingDict(dict):
    """Dict-like store for conflict/forget confirmations awaiting the
    user's decision, backed by SQLite so a backend restart between
    surfacing a choice and the user acting on it doesn't silently
    discard that choice — every existing call site (PENDING[cid] = {...},
    PENDING.pop(id, None)) keeps working unchanged; persistence is
    transparent at the dict interface, not a new API to learn."""

    def __init__(self, kind: str):
        super().__init__(db.load_pending(kind))
        self._kind = kind

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        db.save_pending(self._kind, key, value)

    def pop(self, key, default=None):
        value = super().pop(key, default)
        db.delete_pending(self._kind, key)
        return value


# conflicts/forgets awaiting the user's decision — persisted to SQLite,
# rehydrated on startup, so a restart between surfacing a choice and the
# user acting on it no longer silently discards it
PENDING = PersistentPendingDict("conflict")
PENDING_FORGETS = PersistentPendingDict("forget")