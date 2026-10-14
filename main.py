"""CLI entry point + the reusable `run_goal` / `start_sandbox` helpers (used by evals and the Streamlit UI).

    python main.py                          # demo task
    python main.py "Mark the latest ticket from Contoso as resolved."
    python main.py --headed --debug "..."
"""
import argparse
import asyncio
import inspect
import logging
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from langgraph.types import Command  # noqa: E402

from agent import state as S  # noqa: E402
from agent.browser import Browser  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.llm import check_credentials  # noqa: E402
from agent.log import get_logger, setup_logging  # noqa: E402
from agent.policy import Policy  # noqa: E402

DEMO_GOAL = ("Find the latest refund from Northwind, extract the amount and respond-by date, "
             "log it in the helpdesk, and tell me when it's done.")
log = get_logger("main")


def sandbox_is_up() -> bool:
    try:
        urllib.request.urlopen(S.SANDBOX_URL + "/login", timeout=1)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_sandbox(reset: bool = True, faults: bool = True):
    """Start the mock helpdesk as a subprocess and wait until it answers. Returns the Popen handle."""
    port = S.SANDBOX_URL.rsplit(":", 1)[-1].strip("/")
    cmd = [sys.executable, str(ROOT / "sandbox" / "app.py"), "--port", port] + (["--reset"] if reset else [])
    (ROOT / "runs").mkdir(exist_ok=True)
    out = open(ROOT / "runs" / "sandbox.log", "a", encoding="utf-8")
    proc = subprocess.Popen(cmd, env={**os.environ, "SANDBOX_FAULTS": "1" if faults else "0"},
                            stdout=out, stderr=subprocess.STDOUT)
    for _ in range(75):
        if sandbox_is_up():
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("sandbox did not start (see runs/sandbox.log)")


async def run_goal(goal: str, answer_fn=None, headless: bool = True, log_level: str = "INFO",
                   extra_handlers: list | None = None, on_run_created=None) -> dict:
    """Run one task end-to-end and return the report dict.

    answer_fn(prompt: {"kind", "question"}) -> str, sync or async, is called whenever the graph pauses for a human.
    on_run_created(run_context) is called as soon as the run directory exists (the UI uses it to tail the audit log).
    """
    if err := check_credentials():
        raise RuntimeError(err)
    run = S.new_run(goal)
    setup_logging(os.getenv("LOG_LEVEL", log_level), run.log_path)
    for h in extra_handlers or []:
        logging.getLogger("operator").addHandler(h)
    if on_run_created:
        on_run_created(run)
    run.policy, run.browser = Policy.load(), Browser()
    graph = build_graph()
    cfg = {"configurable": {"thread_id": run.run_id}, "recursion_limit": 100}
    try:
        await run.browser.start(headless=headless)
        await run.browser.ensure_logged_in()
        run.baseline = S.fetch_stats()
        run.audit("run_start", goal=goal)
        result = await graph.ainvoke({"goal": goal, "facts": {}, "replans": 0}, cfg)
        while result.get("__interrupt__"):
            prompt = result["__interrupt__"][0].value
            run.interrupts.append(prompt["kind"])
            log.info("WAITING FOR HUMAN [%s]: %s", prompt["kind"], prompt["question"])
            answer = answer_fn(prompt) if answer_fn else input(f"\n[{prompt['kind']}] {prompt['question']}\n> ")
            if inspect.isawaitable(answer):
                answer = await answer
            result = await graph.ainvoke(Command(resume=answer), cfg)
        return result["report"]
    finally:
        await run.browser.close()


def _cli():
    ap = argparse.ArgumentParser(description="Brightline Support Desk AI Operator")
    ap.add_argument("goal", nargs="?", default=DEMO_GOAL)
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--debug", action="store_true", help="full prompts/responses on the console")
    ap.add_argument("--no-faults", action="store_true", help="disable the sandbox's injected faults")
    a = ap.parse_args()
    proc = None if sandbox_is_up() else start_sandbox(reset=True, faults=not a.no_faults)
    try:
        rep = asyncio.run(run_goal(a.goal, headless=not (a.headed or os.getenv("HEADLESS") == "0"),
                                   log_level="DEBUG" if a.debug else "INFO"))
        print("\n" + rep["summary"])
        sys.exit(0 if rep["status"] == "completed" else 1)
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    _cli()
