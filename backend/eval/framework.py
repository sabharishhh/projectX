"""Shared eval harness. Cases register themselves via @case(...); running
eval/run_evals.py discovers and runs every registered case, printing one
consolidated scorecard — pass/fail per case, rolled up by category — the
same assertion style every test script tonight already used, just no
longer scattered across a dozen one-off files run by hand."""

import sys
import time
import traceback
from dataclasses import dataclass, field

_REGISTRY: list["EvalCase"] = []


@dataclass
class EvalCase:
    id: str
    category: str
    fn: callable
    description: str = ""


@dataclass
class EvalResult:
    case: EvalCase
    passed: bool
    detail: str = ""
    duration_s: float = 0.0
    error: str = ""


def case(id: str, category: str, description: str = ""):
    """Decorator: registers a function as an eval case. The function
    should return True/False, or raise — an exception is treated as a
    fail with the traceback captured, not a crash of the whole suite."""
    def decorator(fn):
        _REGISTRY.append(EvalCase(id=id, category=category, fn=fn, description=description))
        return fn
    return decorator


def run_all(category_filter: str | None = None) -> list[EvalResult]:
    results = []
    cases = [c for c in _REGISTRY if category_filter is None or c.category == category_filter]
    for c in cases:
        t0 = time.monotonic()
        try:
            outcome = c.fn()
            passed, detail = (outcome, "") if isinstance(outcome, bool) else outcome
            results.append(EvalResult(case=c, passed=passed, detail=detail, duration_s=time.monotonic() - t0))
        except Exception:
            results.append(EvalResult(
                case=c, passed=False, duration_s=time.monotonic() - t0,
                error=traceback.format_exc(),
            ))
    return results


def print_scorecard(results: list[EvalResult]) -> bool:
    """Prints pass/fail per case grouped by category, then totals. Returns
    True if everything passed — run_evals.py uses this for its exit code."""
    by_category: dict[str, list[EvalResult]] = {}
    for r in results:
        by_category.setdefault(r.case.category, []).append(r)

    all_passed = True
    for category, cat_results in by_category.items():
        passed_count = sum(1 for r in cat_results if r.passed)
        print(f"\n=== {category} ({passed_count}/{len(cat_results)}) ===")
        for r in cat_results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.case.id}" + (f" — {r.detail}" if r.detail and not r.passed else ""))
            if r.error:
                print(f"    {r.error.strip().splitlines()[-1]}")
                all_passed = False
            if not r.passed:
                all_passed = False

    total = len(results)
    total_passed = sum(1 for r in results if r.passed)
    total_time = sum(r.duration_s for r in results)
    print(f"\n{'=' * 50}")
    print(f"TOTAL: {total_passed}/{total} passed ({total_time:.1f}s)")
    return all_passed


def main():
    category_filter = sys.argv[1] if len(sys.argv) > 1 else None
    results = run_all(category_filter)
    ok = print_scorecard(results)
    sys.exit(0 if ok else 1)
