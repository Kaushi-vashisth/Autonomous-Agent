"""Runs `main.run_goal` on a background thread so Streamlit can poll it and answer human-in-the-loop prompts.

Streamlit reruns the script on every interaction, so the run lives in a RunHandle kept in st.session_state:
the worker thread owns its own asyncio loop (Playwright + LangGraph), publishes state on the handle,
and blocks on a queue whenever the graph interrupts for approval / clarification.
"""
import asyncio
import json
import logging
import queue
import threading
import time
from pathlib import Path

import main as M


class _ListHandler(logging.Handler):
    def __init__(self, sink: list):
        super().__init__(logging.INFO)
        self.sink = sink
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)-16s| %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.sink.append(self.format(record))


class RunHandle:
    def __init__(self, goal: str, headless: bool = True):
        self.goal, self.headless = goal, headless
        self.status = "starting"            # starting | running | waiting | done | error
        self.pending: dict | None = None    # {"kind", "question"} while the graph waits for a human
        self.report: dict | None = None
        self.error: str | None = None
        self.run_dir: Path | None = None
        self.log_lines: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self._answers: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._main, daemon=True)
        self._thread.start()

    # ---- worker thread ----
    def _main(self):
        async def ask(prompt):
            self.pending, self.status = prompt, "waiting"
            answer = await asyncio.get_running_loop().run_in_executor(None, self._answers.get)
            self.pending, self.status = None, "running"
            return answer

        def created(run):
            self.run_dir, self.status = run.run_dir, "running"

        try:
            self.report = asyncio.run(M.run_goal(self.goal, answer_fn=ask, headless=self.headless,
                                                 extra_handlers=[_ListHandler(self.log_lines)],
                                                 on_run_created=created))
            self.status = "done"
        except Exception as e:  # noqa: BLE001
            self.error, self.status = f"{type(e).__name__}: {e}", "error"
        finally:
            self.finished = time.time()

    # ---- UI side ----
    def answer(self, text: str):
        if self.pending is not None:
            self._answers.put(text)
            self.pending = None

    @property
    def active(self) -> bool:
        return self.status in ("starting", "running", "waiting")

    def audit(self) -> list[dict]:
        p = self.run_dir / "audit.jsonl" if self.run_dir else None
        if not p or not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
