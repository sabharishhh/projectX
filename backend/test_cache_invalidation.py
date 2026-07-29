"""test_cache_invalidation.py — verifies memory.py's fetch_state cache and
its four write-triggered invalidation points (commit, supersede, forget,
merge.apply) actually behave correctly. Run from backend/:
    uv run python3 test_cache_invalidation.py

Uses a disposable branch so it doesn't touch real data, and counts real
HTTP calls (rather than trusting timing) so results are deterministic, not
just "seemed faster."
"""

import sys
import time
import uuid
from unittest.mock import patch

import httpx

import memory
import capture
import merge

TEST_BRANCH = f"test-cache-{uuid.uuid4().hex[:8]}"
OTHER_BRANCH = f"test-cache-other-{uuid.uuid4().hex[:8]}"
SOURCE = "test-cache-invalidation"

failures = []


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def count_state_calls(mock) -> int:
    return sum(1 for c in mock.call_args_list if "/state" in str(c))


# --- 1. Basic caching: second fetch_state within TTL shouldn't hit the network ---
print("\n--- 1. fetch_state caching ---")
memory._state_cache.clear()
with patch("memory.httpx.get", wraps=httpx.get) as mock_get:
    memory.fetch_state(TEST_BRANCH)
    memory.fetch_state(TEST_BRANCH)
    memory.fetch_state(TEST_BRANCH)
    n = count_state_calls(mock_get)
check("three fetch_state() calls in a row hit the network exactly once", n == 1, f"got {n} calls")


# --- 2. commit_unit invalidates only the branch it wrote to ---
print("\n--- 2. commit_unit invalidation ---")
memory._state_cache.clear()
memory.fetch_state(TEST_BRANCH)   # populate cache for TEST_BRANCH
memory.fetch_state(OTHER_BRANCH)  # populate cache for OTHER_BRANCH

unit = {"content": "Test fact from cache-invalidation script", "unit_type": "preference",
        "provenance": "stated", "summary": "test"}
ok = capture.commit_unit(unit, SOURCE, branch=TEST_BRANCH)
check("commit_unit succeeded", ok)

with patch("memory.httpx.get", wraps=httpx.get) as mock_get:
    state = memory.fetch_state(TEST_BRANCH)
    memory.fetch_state(OTHER_BRANCH)
    n_test = sum(1 for c in mock_get.call_args_list if TEST_BRANCH in str(c))
    n_other = sum(1 for c in mock_get.call_args_list if OTHER_BRANCH in str(c))

check("TEST_BRANCH cache was invalidated (fresh fetch happened)", n_test == 1, f"got {n_test}")
check("OTHER_BRANCH cache was NOT touched (still cached, no fetch)", n_other == 0, f"got {n_other}")
check("the new fact is actually visible after invalidation",
      any(u["content"] == unit["content"] for u in state))

committed_hash = next((u["hash"] for u in state if u["content"] == unit["content"]), None)


# --- 3. supersede_unit invalidates ---
print("\n--- 3. supersede_unit invalidation ---")
if committed_hash:
    memory.fetch_state(TEST_BRANCH)  # repopulate cache
    new_unit = {"content": "Superseding test fact", "unit_type": "preference",
                "provenance": "stated", "summary": "test supersede"}
    ok = capture.supersede_unit(committed_hash, new_unit, SOURCE, branch=TEST_BRANCH)
    check("supersede_unit succeeded", ok)

    with patch("memory.httpx.get", wraps=httpx.get) as mock_get:
        state = memory.fetch_state(TEST_BRANCH)
        n = count_state_calls(mock_get)
    check("cache invalidated after supersede", n == 1, f"got {n}")
    check("superseded content no longer present, new content is",
          not any(u["content"] == unit["content"] for u in state)
          and any(u["content"] == new_unit["content"] for u in state))

    superseded_hash = next((u["hash"] for u in state if u["content"] == new_unit["content"]), None)
else:
    print("[SKIP] no committed_hash from step 2 — skipping supersede test")
    superseded_hash = None


# --- 4. forget_unit invalidates ---
print("\n--- 4. forget_unit invalidation ---")
if superseded_hash:
    memory.fetch_state(TEST_BRANCH)  # repopulate cache
    ok = capture.forget_unit(superseded_hash, SOURCE, TEST_BRANCH, "test forget")
    check("forget_unit succeeded", ok)

    with patch("memory.httpx.get", wraps=httpx.get) as mock_get:
        state = memory.fetch_state(TEST_BRANCH)
        n = count_state_calls(mock_get)
    check("cache invalidated after forget", n == 1, f"got {n}")
    check("forgotten fact no longer in live state",
          not any(u["hash"] == superseded_hash for u in state))
else:
    print("[SKIP] no superseded_hash from step 3 — skipping forget test")


# --- 5. merge.preview does NOT invalidate anything ---
print("\n--- 5. merge.preview should be a pure read ---")
memory.fetch_state(TEST_BRANCH)
memory.fetch_state(OTHER_BRANCH)
cache_before = dict(memory._state_cache)
try:
    merge.preview(OTHER_BRANCH, TEST_BRANCH)
except Exception as e:
    print(f"[INFO] preview() raised (fine if branches are just empty/unrelated): {e!r}")
cache_after = dict(memory._state_cache)
check("cache dict unchanged after preview()", cache_before.keys() == cache_after.keys())


# --- 6. merge.apply invalidates into_branch, not from_branch ---
print("\n--- 6. merge.apply invalidation ---")
memory.fetch_state(TEST_BRANCH)
memory.fetch_state(OTHER_BRANCH)
try:
    merge.apply(OTHER_BRANCH, TEST_BRANCH, adopt=[], replace=[], source=SOURCE, summary="test merge, no-op")
    with patch("memory.httpx.get", wraps=httpx.get) as mock_get:
        memory.fetch_state(TEST_BRANCH)
        memory.fetch_state(OTHER_BRANCH)
        n_into = sum(1 for c in mock_get.call_args_list if TEST_BRANCH in str(c))
        n_from = sum(1 for c in mock_get.call_args_list if OTHER_BRANCH in str(c))
    check("into_branch (TEST_BRANCH) cache invalidated", n_into == 1, f"got {n_into}")
    check("from_branch (OTHER_BRANCH) cache NOT touched", n_from == 0, f"got {n_from}")
except Exception as e:
    print(f"[FAIL] merge.apply raised unexpectedly: {e!r}")
    failures.append("merge.apply invalidation")


# --- summary ---
print("\n" + "=" * 50)
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)