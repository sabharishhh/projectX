"""
test_entity_graph_generalization.py — generalization test for the
entity-centric memory graph, using a DIFFERENT domain than the Max/dog
test (work project + colleague + concept) to check the pipeline isn't
overfit to one entity_type or one narrative shape.

Runs against a LIVE memory-engine (port 8100) and makes REAL LLM calls.
Same shape as test_entity_graph_e2e.py — three separate facts, phrased
differently, across two branches, all converging on shared entities.

Run from backend/: python test_entity_graph_generalization.py

REQUIRES: memory-engine running on 127.0.0.1:8100 with an EMPTY store —
this script calls /reset at the start.
"""

import sys
import requests

from capture import extract_units, commit_unit, fetch_known_entities
from state import provider

ENGINE = "http://127.0.0.1:8100"
BRANCHES = ["main", "work", "personal"]


def reset_store():
    r = requests.post(f"{ENGINE}/reset")
    r.raise_for_status()
    print("[setup] store reset\n")


def run_capture_turn(user_msg: str, assistant_msg: str, branch: str, known: list[dict]):
    known_entities = fetch_known_entities()
    units = extract_units(provider, user_msg, assistant_msg, known, BRANCHES, known_entities)
    committed = []
    for u in units:
        target_branch = u.get("branch", branch)
        if commit_unit(u, source="test_generalization", branch=target_branch):
            committed.append(u)
    return committed


def get_state(branch: str) -> list[dict]:
    r = requests.get(f"{ENGINE}/state", params={"branch": branch})
    r.raise_for_status()
    return r.json()


def retrieve(query: str, branch: str, max_units: int = 5) -> list[dict]:
    r = requests.post(f"{ENGINE}/retrieve", json={
        "query": query, "max_units": max_units, "branch": branch,
    })
    r.raise_for_status()
    return r.json()


def list_entities() -> list[dict]:
    r = requests.get(f"{ENGINE}/entities")
    r.raise_for_status()
    return r.json()


def run():
    failures = []
    reset_store()

    # --- Turn 1: introduce a colleague (person) and a project (project) ---
    print("=== Turn 1 (work branch) ===")
    committed_1 = run_capture_turn(
        "I'm pairing with Priya on the checkout redesign this sprint.",
        "Good to know — I'll keep that context in mind.",
        branch="work",
        known=[],
    )
    for u in committed_1:
        print(f"  committed: [{u['unit_type']}] {u['content']} -> branch={u.get('branch')}")
        print(f"    entities proposed: {u.get('entities')}")
    print()

    # --- Turn 2: refer to the same person and project differently, on `main` ---
    print("=== Turn 2 (main branch, different phrasing) ===")
    known_after_turn_1 = get_state("work")
    committed_2 = run_capture_turn(
        "She flagged a blocker on the redesign — the payment gateway API is rate-limiting us.",
        "That's a real constraint — worth raising early.",
        branch="main",
        known=known_after_turn_1,
    )
    for u in committed_2:
        print(f"  committed: [{u['unit_type']}] {u['content']} -> branch={u.get('branch')}")
        print(f"    entities proposed: {u.get('entities')}")
    print()

    # --- Turn 3: a third, more distant mention — tests multi-fact convergence ---
    print("=== Turn 3 (work branch, third mention) ===")
    known_after_turn_2 = get_state("work") + get_state("main")
    committed_3 = run_capture_turn(
        "Priya's out next Thursday, so I'll cover her part of the redesign demo.",
        "Got it — noted for your schedule.",
        branch="work",
        known=known_after_turn_2,
    )
    for u in committed_3:
        print(f"  committed: [{u['unit_type']}] {u['content']} -> branch={u.get('branch')}")
        print(f"    entities proposed: {u.get('entities')}")
    print()

    if not committed_1 or not committed_2 or not committed_3:
        print("[FAIL] one or more turns produced no committed units — cannot continue")
        sys.exit(1)

    # --- Check 1: entity resolution — one Priya, one redesign project ---
    print("=== Check 1: entity resolution ===")
    entities = list_entities()
    print(f"  total entities tracked: {len(entities)}")
    for e in entities:
        print(f"    {e.get('name')} [{e.get('entity_type')}] aliases={e.get('aliases')}")

    priya_entities = [e for e in entities if e.get("name", "").lower() == "priya"]
    project_entities = [e for e in entities if e.get("entity_type") == "project"]

    if len(priya_entities) == 1:
        print("  [PASS] exactly one Priya entity exists")
    else:
        print(f"  [FAIL] {len(priya_entities)} Priya entities found — expected 1")
        failures.append("priya_dedup")

    if len(project_entities) >= 1:
        print(f"  [PASS] at least one project entity exists ({[e['name'] for e in project_entities]})\n")
    else:
        print("  [FAIL] no project entity found for the redesign work\n")
        failures.append("project_entity_missing")

    # --- Check 2: content fidelity — "she"/"her" shouldn't be rewritten as "Priya" ---
    print("=== Check 2: content fidelity ===")
    rewritten = [u for u in committed_2 + committed_3 if "priya" in u["content"].lower()]
    original_pronouns = [u for u in committed_2 + committed_3 if u["content"].lower().startswith(("she", "her")) or " she " in u["content"].lower() or " her " in u["content"].lower()]
    print(f"  committed_2/3 content: {[u['content'] for u in committed_2 + committed_3]}")
    if rewritten and not original_pronouns:
        print("  [WARN] pronoun exchanges got rewritten to use 'Priya' directly in content — "
              "not strictly a failure (the wording is still faithful in spirit), but check "
              "whether this drifts from the intended fresh-context verifier design\n")
    else:
        print("  [PASS] content stayed reasonably faithful to original phrasing\n")

    # --- Check 3: entity-mediated retrieval — do all three facts connect? ---
    print("=== Check 3: entity-mediated retrieval across turns/branches ===")
    results = retrieve("what's going on with Priya", branch="work", max_units=6)
    for r in results:
        tag = f" via_edge_reason={r['via_edge_reason']!r}" if r.get("via_edge_reason") else ""
        print(f"  [{r['score']:.3f}] {r['content']}{tag}")

    edge_mediated_count = sum(1 for r in results if r.get("via_edge_reason"))
    if edge_mediated_count >= 1:
        print(f"  [PASS] {edge_mediated_count} fact(s) pulled in via entity-mediated edge\n")
    else:
        print("  [FAIL] no entity-mediated neighbors appeared in retrieval\n")
        failures.append("entity_mediated_retrieval")

    # --- Summary ---
    print("=" * 50)
    if failures:
        print(f"{len(failures)} check(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("All checks PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run()