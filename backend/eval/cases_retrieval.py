"""Retrieval eval cases — confirms BM25's exact-term signal is actually
contributing to ranking, not just present and unused. Uses an invented
term deliberately, since dense embeddings carry ~no real signal for a
made-up compound word — if it still ranks highly, BM25 is doing the
work, isolating the thing this test needs to prove."""

import uuid

import httpx
from eval.framework import case

MEMORY_URL = "http://127.0.0.1:8100"
BRANCH = f"eval-bm25-{uuid.uuid4().hex[:8]}"


def _remember(content: str, unit_type: str = "project") -> str:
    r = httpx.post(f"{MEMORY_URL}/remember", json={
        "content": content, "unit_type": unit_type, "provenance": "stated",
        "source": "eval-bm25", "summary": content, "branch": BRANCH,
    }, timeout=15.0)
    r.raise_for_status()
    return r.json()["hash"]


def _retrieve(query: str) -> list[dict]:
    r = httpx.post(f"{MEMORY_URL}/retrieve", json={
        "query": query, "max_units": 12, "branch": BRANCH, "boost_types": [],
    }, timeout=15.0)
    r.raise_for_status()
    return r.json()


_target_hash = None
_distractor1_hash = None
_distractor2_hash = None


def _seed_once():
    global _target_hash, _distractor1_hash, _distractor2_hash
    if _target_hash is not None:
        return
    _target_hash = _remember("The internal project codename is Nightjar-Vorlax-9.")
    _distractor1_hash = _remember("User is currently working on a big software project.")
    _distractor2_hash = _remember("User enjoys birdwatching, especially spotting nightjars.")


@case("bm25_exact_term_ranks_top", "retrieval", "invented exact term must surface via BM25, not miss dense's cutoff")
def _exact_term_top():
    _seed_once()
    results = _retrieve("What is the codename Nightjar-Vorlax-9?")
    hashes = [r["hash"] for r in results]
    if _target_hash not in hashes:
        return False, "target fact absent from results entirely"
    return hashes.index(_target_hash) <= 1, f"target ranked at index {hashes.index(_target_hash)}, expected top-2"


@case("bm25_beats_semantic_only_distractors", "retrieval",
      "exact-term match must outrank topically-similar-but-inexact distractors")
def _beats_distractors():
    _seed_once()
    results = _retrieve("What is the codename Nightjar-Vorlax-9?")
    hashes = [r["hash"] for r in results]
    if _target_hash not in hashes:
        return False, "target fact absent from results"
    target_rank = hashes.index(_target_hash)
    d1_rank = hashes.index(_distractor1_hash) if _distractor1_hash in hashes else 999
    d2_rank = hashes.index(_distractor2_hash) if _distractor2_hash in hashes else 999
    return target_rank < d1_rank and target_rank < d2_rank, f"target={target_rank} d1={d1_rank} d2={d2_rank}"


@case("dense_path_still_works_paraphrased", "retrieval", "BM25 addition must not break ordinary paraphrased queries")
def _dense_still_works():
    _seed_once()
    results = _retrieve("What software project am I working on right now?")
    hashes = [r["hash"] for r in results]
    return _distractor1_hash in hashes, "generic paraphrased query failed to find the generic distractor fact"