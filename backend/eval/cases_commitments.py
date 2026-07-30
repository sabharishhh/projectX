"""Commitment lifecycle eval cases — the subject-discrimination fix and
its regression coverage, kept as standing cases so a future prompt
change can never silently re-break what several rounds of stress-testing
fixed tonight."""

from dotenv import load_dotenv
load_dotenv()

import uuid
from providers import get_provider
from capture import extract_units, commit_unit, find_open_commitments, detect_commitment_resolutions
from eval.framework import case

provider, model = get_provider()


def _seed(branch, content):
    units = extract_units(provider, content, "Got it, noted.", known=[], branches=[branch])
    for u in units:
        if u.get("unit_type") == "commitment":
            commit_unit(u, "eval", branch=branch)


@case("resolution_same_entity_different_task", "commitments",
      "same entity, different task must NOT resolve — the original stress-test bug")
def _same_entity_diff_task():
    branch = f"eval-commit-{uuid.uuid4().hex[:6]}"
    _seed(branch, "I will email the landlord about the lease renewal")
    open_commitments = find_open_commitments(branch)
    resolutions = detect_commitment_resolutions(
        provider, "I emailed the landlord about a leaky faucet", "Good.", open_commitments,
    )
    return len(resolutions) == 0, f"false-positive match: {resolutions}"


@case("resolution_correct_match", "commitments", "genuine resolution must still match correctly")
def _correct_match():
    branch = f"eval-commit-{uuid.uuid4().hex[:6]}"
    _seed(branch, "I will follow up with Arjun about the proposal")
    open_commitments = find_open_commitments(branch)
    resolutions = detect_commitment_resolutions(
        provider, "I followed up with Arjun about the proposal, he approved it", "Great.", open_commitments,
    )
    return len(resolutions) == 1 and resolutions[0]["status"] == "done", f"got: {resolutions}"


@case("resolution_same_person_different_commitment", "commitments",
      "a new commitment about the same person must NOT cancel an unrelated older one")
def _same_person_no_cancel():
    branch = f"eval-commit-{uuid.uuid4().hex[:6]}"
    _seed(branch, "I will follow up with Arjun about the proposal")
    open_commitments = find_open_commitments(branch)
    resolutions = detect_commitment_resolutions(
        provider, "I need to follow up with Arjun about lunch plans too", "Noted.", open_commitments,
    )
    return len(resolutions) == 0, f"wrongly resolved: {resolutions}"