"""Run the full eval suite:  uv run python3 -m eval.run_evals
Or one category only:        uv run python3 -m eval.run_evals commitments
"""

import eval.cases_capture
import eval.cases_commitments
import eval.cases_time_travel
import eval.cases_retrieval
import eval.cases_chat_engine
import eval.cases_infra
from eval.framework import main

if __name__ == "__main__":
    main()