"""Runs scripted tasks and asserts final app state.  Usage: python evals/run_evals.py [case_id ...]"""
import asyncio
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import run_goal, start_sandbox  # noqa: E402
from agent import state as S  # noqa: E402


async def run_case(case: dict) -> list[str]:
    proc = start_sandbox(reset=True, faults=True)
    try:
        answers = iter(case.get("answers", []))
        rep = await run_goal(case["goal"], answer_fn=lambda p: next(answers, "yes"), headless=True)
        stats = S.fetch_stats()
    finally:
        proc.terminate()
        proc.wait()
    exp, errs = case["expect"], []

    def check(name, ok, got):
        if not ok:
            errs.append(f"{name}: got {got!r}")

    check("status", rep["status"] == exp.get("status", "completed"), rep["status"])
    if "interrupt_kinds" in exp:
        check("interrupt_kinds", rep["interrupts"] == exp["interrupt_kinds"], rep["interrupts"])
    if "new_refunds" in exp:
        check("new_refunds", stats["refunds"] == exp["new_refunds"], stats["refunds"])
    if "tickets_resolved" in exp:
        check("tickets_resolved", stats["tickets_resolved"] == exp["tickets_resolved"], stats["tickets_resolved"])
    if "resolved_tickets" in exp:
        check("resolved_tickets", stats["resolved_tickets"] == exp["resolved_tickets"], stats["resolved_tickets"])
    row = stats["refund_rows"][0] if stats["refund_rows"] else {}
    for key in ("customer", "respond_by"):
        if key in exp:
            check(key, row.get(key) == exp[key], row.get(key))
    if "amount" in exp:
        check("amount", f"{row.get('amount', 0):.2f}" == exp["amount"], row.get("amount"))
    if "min_failed_submits" in exp:
        failed = [s for s in rep["submissions"] if not s["ok"]]
        check("failed_submits", len(failed) >= exp["min_failed_submits"], len(failed))
    if exp.get("all_checks_pass"):
        check("all_checks_pass", bool(rep["checks"]) and all(c["passed"] for c in rep["checks"].values()), rep["checks"])
    return errs


async def main(only: list[str]):
    cases = yaml.safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))
    failures = 0
    for case in cases:
        if only and case["id"] not in only:
            continue
        try:
            errs = await run_case(case)
        except Exception as e:  # noqa: BLE001
            errs = [f"exception: {type(e).__name__}: {e}"]
        print(f"{'PASS' if not errs else 'FAIL'}  {case['id']}")
        for e in errs:
            print("      -", e)
        failures += bool(errs)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
