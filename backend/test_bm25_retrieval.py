"""test_bm25_retrieval.py — verifies BM25 is actually influencing
retrieval, not just compiling and sitting unused. Uses a nonsense/invented
term specifically because dense embeddings have essentially no semantic
signal for a made-up word — if a fact containing it still ranks highly for
an exact-match query, that's direct evidence BM25 is doing real work, not
just embedding proximity coincidentally lining up.

Run from memory-engine/ (or wherever the engine is), with the engine
already running on 127.0.0.1:8100:
    python3 test_bm25_retrieval.py
"""

import sys
import uuid

import httpx

MEMORY_URL = "http://127.0.0.1:8100"
BRANCH = f"test-bm25-{uuid.uuid4().hex[:8]}"

failures = []


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def remember(content: str, unit_type: str = "project") -> str:
    r = httpx.post(f"{MEMORY_URL}/remember", json={
        "content": content, "unit_type": unit_type, "provenance": "stated",
        "source": "bm25-test", "summary": content, "branch": BRANCH,
    }, timeout=15.0)
    r.raise_for_status()
    return r.json()["hash"]


def retrieve(query: str) -> list[dict]:
    r = httpx.post(f"{MEMORY_URL}/retrieve", json={
        "query": query, "max_units": 12, "branch": BRANCH, "boost_types": [],
    }, timeout=15.0)
    r.raise_for_status()
    return r.json()


# --- Seed: one fact with a made-up, exact term; two semantically-related
# distractors that share NO exact vocabulary with it. ---
print("--- seeding facts ---")
target_hash = remember("The internal project codename is Nightjar-Vorlax-9.")
distractor1_hash = remember("User is currently working on a big software project.")
distractor2_hash = remember("User enjoys birdwatching, especially spotting nightjars.")
print(f"target={target_hash[:8]} distractor1={distractor1_hash[:8]} distractor2={distractor2_hash[:8]}")


# --- Test 1: exact nonsense-term query should surface the target fact
# strongly. Dense embeddings have ~no real semantic signal for an invented
# compound word — if this ranks well, BM25 is doing the work. ---
print("\n--- 1. exact-term query ---")
results = retrieve("What is the codename Nightjar-Vorlax-9?")
hashes = [r["hash"] for r in results]
check("target fact appears in results at all", target_hash in hashes)
if target_hash in hashes:
    rank = hashes.index(target_hash)
    check(f"target fact ranks near the top (got rank {rank})", rank <= 1)
    target_score = next(r["score"] for r in results if r["hash"] == target_hash)
    print(f"  target score: {target_score}")


# --- Test 2: same query, but check the target fact clearly outranks the
# semantically-adjacent-but-exact-term-free distractors — isolates that
# it's the exact term doing the work, not just topical relevance. ---
print("\n--- 2. target should outrank semantic-only distractors ---")
if target_hash in hashes:
    target_rank = hashes.index(target_hash)
    d1_rank = hashes.index(distractor1_hash) if distractor1_hash in hashes else 999
    d2_rank = hashes.index(distractor2_hash) if distractor2_hash in hashes else 999
    check("target outranks the generic 'working on a project' distractor",
          target_rank < d1_rank, detail=f"target={target_rank} distractor1={d1_rank}")
    check("target outranks the 'nightjars' (partial word overlap) distractor",
          target_rank < d2_rank, detail=f"target={target_rank} distractor2={d2_rank}")


# --- Test 3: a purely semantic query with NO exact-term overlap should
# still work reasonably (confirms BM25 addition didn't break the dense
# path for ordinary paraphrased queries). ---
print("\n--- 3. dense path still works for paraphrased queries ---")
results2 = retrieve("What software project am I working on right now?")
hashes2 = [r["hash"] for r in results2]
check("generic project query still finds the generic distractor fact",
      distractor1_hash in hashes2)


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