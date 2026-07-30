"""Infra-correctness eval cases — not LLM behavior, real systems
regressions: cache invalidation and the centralized memory-engine
client. Guards against exactly the class of bug that took several
rounds to fix tonight (invalidation ordering, wrong-path routing)."""

import uuid

import memory
import capture
from eval.framework import case

BRANCH = f"eval-infra-{uuid.uuid4().hex[:8]}"
SOURCE = "eval-infra"


@case("cache_invalidates_on_commit", "infra", "fetch_state must reflect a new fact immediately after commit")
def _cache_invalidates():
    unit = {"content": "Eval infra test fact", "unit_type": "preference",
            "provenance": "stated", "summary": "test"}
    ok = capture.commit_unit(unit, SOURCE, branch=BRANCH)
    if not ok:
        return False, "commit_unit failed"
    state = memory.fetch_state(BRANCH)
    found = any(u["content"] == unit["content"] for u in state)
    return found, "new fact not visible immediately after commit — cache invalidation failed"


@case("cache_branch_isolation", "infra", "writing to one branch must not invalidate another branch's cache")
def _branch_isolation():
    other_branch = f"eval-infra-other-{uuid.uuid4().hex[:8]}"
    memory.fetch_state(BRANCH)
    memory.fetch_state(other_branch)

    unit = {"content": "Isolation test fact", "unit_type": "preference",
            "provenance": "stated", "summary": "test"}
    capture.commit_unit(unit, SOURCE, branch=BRANCH)

    # If isolation is broken, other_branch's cache would have been cleared
    # too — not directly observable without mocking, so this checks the
    # weaker but still meaningful property: other_branch's state is
    # unaffected in content.
    other_state = memory.fetch_state(other_branch)
    leaked = any(u["content"] == unit["content"] for u in other_state)
    return not leaked, "fact committed to BRANCH leaked into a different branch's state"