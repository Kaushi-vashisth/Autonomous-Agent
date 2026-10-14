"""Streamlit UI for the Brightline Support Desk AI Operator.

    streamlit run streamlit_app.py
"""
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

import main as M
from agent import state as S
from agent.llm import check_credentials, provider
from agent.tools import load_customers
from ui.runner import RunHandle

ROOT = Path(__file__).resolve().parent
EXAMPLES = {
    "Refund: ambiguous customer": "Find the latest refund from Northwind, extract the amount and respond-by date, log it in the helpdesk, and tell me when it's done.",
    "Refund: needs approval": "Find the latest refund from Northwind Logistics, extract the amount and respond-by date, and log it in the helpdesk.",
    "Refund: injected faults": "Find the latest refund from Northwind Traders, extract the amount and respond-by date, and log it in the helpdesk.",
    "Refund: from an email": "Enter the latest refund from Contoso Ltd in the helpdesk.",
    "Refund: tie on date": "Find the latest refund from Fabrikam and log it in the helpdesk.",
    "Ticket: resolve latest": "Mark the latest ticket from Contoso as resolved.",
}
STATUS_LABEL = {"completed": "Completed", "failed": "Not completed", "aborted": "Aborted"}

st.set_page_config(page_title="Support Desk Operator", page_icon=":material/support_agent:", layout="wide")


# ---------------------------------------------------------------- sandbox management
@st.cache_resource
def _sandbox_state() -> dict:
    return {"proc": None}


def ensure_sandbox(reset: bool = False, faults: bool = True):
    state = _sandbox_state()
    if reset and state["proc"] is not None:
        state["proc"].terminate()
        state["proc"].wait()
        state["proc"] = None
    if reset and state["proc"] is None and M.sandbox_is_up():
        raise RuntimeError("The helpdesk is running outside this app; restart it with `python sandbox/app.py --reset`.")
    if not M.sandbox_is_up():
        state["proc"] = M.start_sandbox(reset=True, faults=faults)


def fetch_stats() -> dict | None:
    try:
        return S.fetch_stats()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- audit timeline
def describe(ev: dict) -> tuple[str, str] | None:
    """(marker, text) for an audit event worth showing, else None."""
    e = ev["event"]
    if e == "load_context":
        return "ctx", f"Selected context: {', '.join(ev.get('selected') or []) or 'none'} (always: company.md, policies.md)"
    if e == "act_start":
        return "run", f"Step {ev['step']}: {ev['description']}"
    if e == "act_end":
        return ("ok" if ev["status"] == "done" else "warn"), f"Step {ev['step']} {ev['status']}: {ev.get('note') or ''}".strip()
    if e == "act_retry":
        return "warn", f"Retrying step {ev['step']}: {ev.get('error')}"
    if e in ("ambiguous_customer", "ambiguous_latest_document"):
        return "warn", f"Ambiguity detected: {', '.join(ev.get('candidates') or [])}"
    if e == "submit_blocked":
        return "warn", f"Submit blocked by policy: {ev.get('reason')} ({ev.get('customer')}, USD {ev.get('amount')})"
    if e == "submit_record":
        return ("ok" if ev.get("ok") else "warn"), (
            f"Submitted {ev.get('record_type')}: " + ("saved" if ev.get("ok") else f"failed - {str(ev.get('error'))[:140]}"))
    if e == "human_answer":
        return "human", f"You answered ({ev['kind']}): {ev['answer']}"
    if e == "approval":
        return "ok", f"Approval recorded: {ev['customer']} USD {ev['amount']}"
    if e == "escalate":
        return "warn", f"Escalated to human after {ev.get('replans')} replans"
    if e == "verify_end":
        checks = ev.get("checks", {})
        passed = sum(c["passed"] for c in checks.values())
        return ("ok" if passed == len(checks) else "warn"), f"Verification: {passed}/{len(checks)} checks passed"
    return None


MARK = {"ctx": ":material/folder_open:", "run": ":material/play_arrow:", "ok": ":green[:material/check_circle:]",
        "warn": ":orange[:material/warning:]", "human": ":blue[:material/person:]"}


def render_timeline(events: list[dict]):
    for ev in events:
        if ev["event"] == "plan":
            with st.expander(f"Plan: {ev['objective']}", expanded=False):
                for i, s in enumerate(ev["steps"], 1):
                    st.markdown(f"{i}. {s}")
                if ev.get("assumptions"):
                    st.caption("Assumptions: " + "; ".join(ev["assumptions"]))
            continue
        d = describe(ev)
        if d:
            st.markdown(f"{MARK[d[0]]} {d[1]}")


# ---------------------------------------------------------------- human-in-the-loop card
def render_pending(h: RunHandle):
    p = h.pending
    if not p:
        return
    kind, q = p["kind"], p["question"]
    key = f"{abs(hash(q))}-{len(h.audit())}"
    with st.container(border=True):
        titles = {"approval": "Approval required", "clarification": "Clarification needed", "escalation": "Operator needs guidance"}
        st.markdown(f"**{titles.get(kind, 'Input needed')}**")
        st.write(q)
        if kind == "approval":
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("Approve", type="primary", key=f"yes-{key}"):
                h.answer("yes")
            if c2.button("Reject", key=f"no-{key}"):
                h.answer("no")
            return
        # quick picks: document numbers or customer names mentioned in the question
        picks = re.findall(r"\b(?:RF|TCK)-\d+\b", q) or [c["name"] for c in load_customers() if c["name"] in q]
        if picks:
            cols = st.columns(len(picks) + 2)
            for col, opt in zip(cols, picks):
                if col.button(opt, key=f"pick-{opt}-{key}"):
                    h.answer(opt)
        text = st.text_input("Your answer", key=f"txt-{key}", placeholder="Type an answer, or 'abort' to stop")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Send", type="primary", key=f"send-{key}") and text.strip():
            h.answer(text.strip())
        if c2.button("Abort run", key=f"abort-{key}"):
            h.answer("abort")


# ---------------------------------------------------------------- report
def render_report(rep: dict):
    status = rep["status"]
    box = {"completed": st.success, "aborted": st.warning, "failed": st.error}[status]
    box(f"**{STATUS_LABEL[status]}**: {rep['goal']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Replans", rep["replans"])
    c2.metric("Human interactions", len(rep["human_answers"]))
    c3.metric("Submit attempts", f"{sum(s['ok'] for s in rep['submissions'])}/{len(rep['submissions'])} ok")

    left, right = st.columns(2)
    with left:
        st.subheader("Verification")
        for name, c in rep["checks"].items():
            st.markdown(f"{':green[:material/check_circle:]' if c['passed'] else ':red[:material/cancel:]'} **{name}**: {c['detail']}")
        if not rep["checks"]:
            st.caption("Verification did not run.")
    with right:
        st.subheader("Facts")
        if rep["facts"]:
            st.dataframe(pd.DataFrame({"fact": list(rep["facts"]), "value": [str(v) for v in rep["facts"].values()]}),
                         hide_index=True)
    if rep["human_answers"]:
        st.subheader("Human input")
        for a in rep["human_answers"]:
            st.markdown(f"- **{a['kind']}**: {a['question']}  \n  -> *{a['answer']}*")
    shots = [p for p in rep["screenshots"] if Path(p).exists()]
    if shots:
        st.subheader("Evidence")
        cols = st.columns(min(3, len(shots)))
        for i, p in enumerate(shots):
            cols[i % len(cols)].image(p, caption=Path(p).name)
    d1, d2 = st.columns(2)
    d1.download_button("Download report.json", json.dumps(rep, indent=2, default=str), f"{rep['run_id']}-report.json")
    d2.download_button("Download report.md", rep["summary"] if "summary" in rep else "", f"{rep['run_id']}-report.md")


# ---------------------------------------------------------------- live run view
def render_live(h: RunHandle):
    if h.status == "starting":
        st.info("Starting browser and graph...")
    elif h.status == "running":
        st.info(f"Working... {time.time() - h.started:.0f}s")
    elif h.status == "waiting":
        st.warning("Paused: waiting for you")
    elif h.status == "error":
        st.error(f"The run crashed: {h.error}")

    render_timeline(h.audit())
    render_pending(h)

    with st.expander("Live operator log", expanded=False):
        st.code("\n".join(h.log_lines[-120:]) or "(no output yet)", language="text")

    if not h.active and st.session_state.pop("polling", False):
        st.rerun()          # run just finished: redraw the whole page with the final report


def run_tab():
    h: RunHandle | None = st.session_state.get("handle")
    active = bool(h and h.active)
    err = check_credentials()
    if err:
        st.error(err + " Then restart the app.")

    st.markdown("##### Request")
    cols = st.columns(3)
    for i, (label, goal) in enumerate(EXAMPLES.items()):
        if cols[i % 3].button(label, disabled=active):
            st.session_state["goal"] = goal
    goal = st.text_area("What should the operator do?", key="goal", height=90, disabled=active,
                        placeholder="e.g. Find the latest refund from Contoso Ltd and log it in the helpdesk.")
    if st.button("Run operator", type="primary", disabled=active or bool(err) or not goal.strip()):
        ensure_sandbox(reset=False, faults=st.session_state.get("faults", True))
        st.session_state["handle"] = RunHandle(goal.strip(), headless=st.session_state.get("headless", True))
        st.rerun()

    if not h:
        st.caption("Pick an example or type a request. The operator plans, uses a real browser against the mock helpdesk, "
                   "asks you when policy requires it, and verifies the result.")
        return
    st.divider()
    if h.report and not h.active:
        render_report(h.report)
        with st.expander("Timeline"):
            render_timeline(h.audit())
        with st.expander("Operator log"):
            st.code("\n".join(h.log_lines) or "(empty)", language="text")
        return
    if h.status == "error":
        st.error(f"The run crashed: {h.error}")
        with st.expander("Operator log", expanded=True):
            st.code("\n".join(h.log_lines[-80:]), language="text")
        return
    st.session_state["polling"] = True
    st.fragment(run_every=1.5)(render_live)(h)


# ---------------------------------------------------------------- helpdesk + history
def helpdesk_tab():
    st.caption(f"Mock helpdesk at {S.SANDBOX_URL} (login demo / demo123)")
    stats = fetch_stats()
    if stats is None:
        st.info("Helpdesk is not running yet; it starts automatically with your first run.")
        if st.button("Start helpdesk"):
            ensure_sandbox(reset=True, faults=st.session_state.get("faults", True))
            st.rerun()
        return
    c1, c2 = st.columns(2)
    c1.metric("Refunds logged", stats["refunds"])
    c2.metric("Tickets resolved", stats["tickets_resolved"])
    st.subheader("Refunds in helpdesk")
    if stats["refund_rows"]:
        st.dataframe(pd.DataFrame(stats["refund_rows"]), hide_index=True)
    else:
        st.caption("No refunds logged yet.")
    if stats["resolved_tickets"]:
        st.subheader("Resolved tickets")
        st.write(", ".join(stats["resolved_tickets"]))
    st.subheader("Source documents")
    for folder in ("refunds", "emails", "tickets"):
        files = sorted((ROOT / "sandbox" / "data" / folder).glob("*"))
        with st.expander(f"{folder} ({len(files)})"):
            st.write("\n".join(f"- {f.name}" for f in files))


def history_tab():
    reports = sorted((ROOT / "runs").glob("*/report.json"), reverse=True)
    if not reports:
        st.caption("No finished runs yet.")
        return
    labels = {}
    for p in reports:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            labels[p] = f"{p.parent.name}  |  {r['status']}  |  {r['goal'][:70]}"
        except Exception:  # noqa: BLE001
            continue
    pick = st.selectbox("Past run", list(labels), format_func=labels.get)
    if pick:
        rep = json.loads(pick.read_text(encoding="utf-8"))
        md = pick.with_name("report.md")
        rep["summary"] = md.read_text(encoding="utf-8") if md.exists() else ""
        render_report(rep)
        audit = pick.with_name("audit.jsonl")
        if audit.exists():
            with st.expander("Audit log"):
                st.code(audit.read_text(encoding="utf-8"), language="json")


# ---------------------------------------------------------------- page
with st.sidebar:
    st.title("Support Desk Operator")
    st.caption("Planner / Actor / Verifier agent on LangGraph")
    st.toggle("Show browser window", key="show", value=False,
              on_change=lambda: st.session_state.update(headless=not st.session_state["show"]))
    st.session_state.setdefault("headless", True)
    st.toggle("Inject helpdesk faults", key="faults", value=True,
              help="Date-format trap + one-time HTTP 500, to demo recovery. Applies when the helpdesk (re)starts.")
    busy = bool(st.session_state.get("handle") and st.session_state["handle"].active)
    if st.button("Reset helpdesk data", disabled=busy):
        try:
            ensure_sandbox(reset=True, faults=st.session_state["faults"])
            st.toast("Helpdesk reset")
        except RuntimeError as e:
            st.error(str(e))
    st.divider()
    st.caption(f"Provider: {provider()}")
    st.caption("Helpdesk: " + ("running" if M.sandbox_is_up() else "stopped"))

tab_run, tab_desk, tab_hist = st.tabs(["Run", "Helpdesk", "History"])
with tab_run:
    run_tab()
with tab_desk:
    helpdesk_tab()
with tab_hist:
    history_tab()
