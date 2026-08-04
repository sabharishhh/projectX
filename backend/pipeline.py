"""Declared-stage-graph runner. Replaces hand-nested ThreadPoolExecutor
blocks with an explicit dependency list — the runner derives execution
waves from `deps` instead of a human re-deriving them by reading comments
every time the graph changes.

Three things this buys over the manual pattern it replaces:
  1. One shared, bounded thread pool for the whole process instead of a
     fresh short-lived pool per phase — real backpressure across
     concurrent turns (multiple chat panes), not per-turn assumption of
     exclusive access to the machine.
  2. disconnected is checked once, structurally, between every wave — not
     an optional parameter a stage author has to remember to thread
     through by hand.
  3. Background stages (fire-and-forget work that must happen but
     shouldn't block the response) are a declared mode with real failure
     visibility, not a bare `threading.Thread(daemon=True).start()`.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

logger = logging.getLogger("pipeline")


@dataclass
class Stage:
    name: str
    fn: Callable[[dict], Any]
    deps: list[str] = field(default_factory=list)
    gate: Callable[[dict], bool] | None = None
    on_fail: Literal["open", "closed"] = "open"
    mode: Literal["blocking", "background"] = "blocking"


class SharedExecutor:
    """One bounded pool for the whole process. Stages submit into this
    rather than each phase spinning up and tearing down its own pool."""

    def __init__(self, max_workers: int = 24):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, fn, *args, **kwargs) -> Future:
        return self._pool.submit(fn, *args, **kwargs)


# App-wide default. Not per-request — created once at import time, shared
# across every Pipeline.run() call, so total in-flight work is genuinely
# bounded regardless of how many turns are concurrently in progress.
SHARED_EXECUTOR = SharedExecutor()


class Pipeline:
    def __init__(self, stages: list[Stage], executor: SharedExecutor = SHARED_EXECUTOR):
        self.stages = {s.name: s for s in stages}
        self.executor = executor
        self._background: set[Future] = set()

    def run(self, context: dict, disconnected: threading.Event | None = None) -> dict:
        done: set[str] = set()
        while len(done) < len(self.stages):
            ready = [
                s for s in self.stages.values()
                if s.name not in done and all(d in done for d in s.deps)
            ]
            if not ready:
                raise RuntimeError(
                    f"pipeline stalled — unresolvable dependency among: "
                    f"{[s.name for s in self.stages.values() if s.name not in done]}"
                )

            if disconnected is not None and disconnected.is_set():
                logger.info(f"disconnected — stopping before {[s.name for s in ready]}")
                return context

            futures: dict[Future, Stage] = {}
            for s in ready:
                if s.gate is not None and not s.gate(context):
                    context[s.name] = None
                    done.add(s.name)
                    continue
                futures[self.executor.submit(self._run_one, s, context)] = s

            for fut, s in futures.items():
                if s.mode == "background":
                    self._background.add(fut)
                    fut.add_done_callback(lambda f, name=s.name: self._on_background_done(name, f))
                    context[s.name] = None  # doesn't block the pipeline; nothing downstream should depend on this stage's result
                else:
                    context[s.name] = fut.result()
                done.add(s.name)
        return context

    def _run_one(self, stage: Stage, context: dict):
        t0 = time.monotonic()
        try:
            result = stage.fn(context)
            logger.info(f"[pipeline] {stage.name}: {time.monotonic() - t0:.3f}s")
            return result
        except Exception as e:
            logger.warning(f"[pipeline] {stage.name} failed: {e!r}")
            if stage.on_fail == "closed":
                raise
            return None

    def _on_background_done(self, name: str, fut: Future):
        self._background.discard(fut)
        exc = fut.exception()
        if exc:
            logger.warning(f"[pipeline] background stage {name!r} failed: {exc!r}")