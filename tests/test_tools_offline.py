"""Offline check of the deterministic parts (tools, policy gate, verify). No LLM / API key needed.
Usage: python tests/test_tools_offline.py"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SANDBOX_DB"] = str(ROOT / "runs" / "offline_test.db")

from agent import state as S  # noqa: E402
from agent.browser import Browser  # noqa: E402
from agent.policy import Policy  # noqa: E402
from agent import tools as T  # noqa: E402
from agent.verify import run_checks  # noqa: E402


def start_sandbox():
    p = subprocess.Popen([sys.executable, str(ROOT / "sandbox" / "app.py"), "--reset"],
                         env={**os.environ, "SANDBOX_FAULTS": "1"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(S.SANDBOX_URL + "/login", timeout=1)
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    p.terminate()
    raise RuntimeError("sandbox did not start")


async def call(tool_name, **kw):
    out = await T.TOOL_MAP[tool_name].ainvoke(kw)
    print(f"  {tool_name}({', '.join(f'{k}={v!r}' for k, v in kw.items())}) -> {out.splitlines()[0][:110]}")
    return out


async def main():
    proc = start_sandbox()
    r = S.new_run("offline test")
    r.policy, r.browser = Policy.load(), Browser()
    await r.browser.start(headless=True)
    await r.browser.ensure_logged_in()
    r.baseline = S.fetch_stats()
    try:
        print("1. ambiguity / lookup")
        assert "AMBIGUOUS" in await call("lookup_customer", name="Northwind")
        assert r.pending and r.pending["kind"] == "clarification"; r.pending = None
        assert "MATCH: Contoso Ltd" in await call("lookup_customer", name="Contoso")

        print("2. latest document (email beats PDFs) + tie")
        out = await call("find_latest_document", kind="refund", customer="Contoso Ltd")
        assert "RF-5602" in out and "emails/" in out
        assert "AMBIGUOUS" in await call("find_latest_document", kind="refund", customer="Fabrikam Inc"); r.pending = None

        print("3. refund above threshold is blocked until approved")
        await call("goto", url=S.SANDBOX_URL + "/refunds/new")
        out = await call("submit_record", record_type="refund", customer="Northwind Logistics", amount="782.50",
                         respond_by="2026-04-09", refund_number="RF-0329")
        assert out.startswith("BLOCKED") and r.pending["kind"] == "approval"
        r.pending = None
        r.approvals.append({"customer": "Northwind Logistics", "amount": "782.50", "ts": time.time(), "by": "human"})

        print("4. approved submit: first POST hits the injected HTTP 500, second succeeds")
        out = await call("submit_record", record_type="refund", customer="Northwind Logistics", amount="782.50",
                         respond_by="2026-04-09", refund_number="RF-0329")
        assert out.startswith("SUBMIT FAILED"), out
        await call("goto", url=S.SANDBOX_URL + "/refunds/new")
        out = await call("submit_record", record_type="refund", customer="Northwind Logistics", amount="782.50",
                         respond_by="2026-04-09", refund_number="RF-0329")
        assert out.startswith("SUCCESS"), out
        checks = await run_checks(dict(r.facts))
        for k, v in checks.items():
            print(f"  verify {k}: {'PASS' if v['passed'] else 'FAIL'} - {v['detail'][:90]}")
        assert all(c["passed"] for c in checks.values())

        print("5. duplicate / not-latest are refused")
        await call("goto", url=S.SANDBOX_URL + "/refunds/new")
        out = await call("submit_record", record_type="refund", customer="Northwind Traders", amount="125.00",
                         respond_by="2026-01-17", refund_number="RF-2042")
        assert out.startswith("BLOCKED") and "not the latest" in out

        print("6. ticket resolution")
        r.submissions.clear(); r.facts.clear(); r.baseline = S.fetch_stats()
        await call("goto", url=S.SANDBOX_URL + "/tickets/3")
        out = await call("submit_record", record_type="ticket_resolve", customer="Contoso Ltd", ticket_number="TCK-7003")
        assert out.startswith("SUCCESS"), out
        checks = await run_checks(dict(r.facts))
        assert all(c["passed"] for c in checks.values()), checks
        assert S.fetch_stats()["resolved_tickets"] == ["TCK-7003"]
        print("ALL OFFLINE CHECKS PASSED")
    finally:
        await r.browser.close()
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
