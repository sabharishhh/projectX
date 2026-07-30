"""Run the full eval suite:  uv run python3 -m eval.run_evals
Or one category only:        uv run python3 -m eval.run_evals commitments
"""

import eval.cases_capture       # noqa: F401 — registers its cases on import
import eval.cases_commitments   # noqa: F401
from eval.framework import main

if __name__ == "__main__":
    main()