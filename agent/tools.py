"""LangChain tools. Errors are returned as observations, never raised."""
import functools
import json
import re
import time

from langchain_core.tools import tool
from pypdf import PdfReader

from agent import state as S
from agent.context_loader import CONTEXT_DIR
from agent.policy import Policy, parse_date, to_decimal

MAX_OBS = 3500


def _run():
    if S.RUN is None:
        raise RuntimeError("No active run")
    return S.RUN


def safe(fn):
    """Convert exceptions into observation strings so the Actor/Planner can react."""
    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        try:
            out = await fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            out = f"ERROR: {type(e).__name__}: {e}"
        out = str(out)
        return out if len(out) <= MAX_OBS else out[:MAX_OBS] + "\n...[truncated]"
    return wrapper


def read_text_file(path: str) -> str:
    """Sync helper (also used by verify). Reads text or extracts PDF text, policy-checked."""
    p = _run().policy.resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if p.suffix.lower() == ".pdf":
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------- customers ----------------
def load_customers() -> list[dict]:
    customers = []
    for line in (CONTEXT_DIR / "customers.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \*\*(.+?)\*\*\s*[—-]\s*aliases:\s*(.*)$", line.strip())
        if m:
            customers.append({"name": m.group(1).strip(),
                            "aliases": [a.strip() for a in m.group(2).split(",") if a.strip()]})
    return customers


def match_customers(query: str) -> list[str]:
    q = query.strip().casefold()
    vs = load_customers()
    exact = [v["name"] for v in vs if v["name"].casefold() == q]
    if exact:
        return exact
    alias = [v["name"] for v in vs if q in [a.casefold() for a in v["aliases"]]]
    if alias:
        return alias
    return [v["name"] for v in vs if q in v["name"].casefold()]


# ---------------- source documents (refunds, emails, tickets) ----------------
DOC_FOLDERS = {"refund": ["sandbox/data/refunds", "sandbox/data/emails"],
               "ticket": ["sandbox/data/tickets"]}
NUMBER_RE = {"refund": r"Refund No:\s*(\S+)", "ticket": r"Ticket No:\s*(\S+)"}
DATE_RE = {"refund": r"Refund Date:\s*(.+)", "ticket": r"Opened Date:\s*(.+)"}


def customer_slug(customer: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", customer.lower()).strip("-")


def scan_documents(kind: str, customer: str) -> list[dict]:
    """All source documents (PDF or email text) for a customer, with number and date read from inside the file."""
    prefix, docs = customer_slug(customer) + "_", []
    for folder in DOC_FOLDERS[kind]:
        p = _run().policy.resolve_path(folder)
        for f in sorted(p.glob("*")):
            if not f.name.startswith(prefix):
                continue
            rel = f"{folder}/{f.name}"
            text = read_text_file(rel)
            n, d = re.search(NUMBER_RE[kind], text), re.search(DATE_RE[kind], text)
            when = parse_date(d.group(1)) if d else None
            if n and when:
                docs.append({"path": rel, "number": n.group(1), "date": when})
    return docs


def resolve_latest(kind: str, customer: str):
    """Return (latest_docs, message, status) where status is ok | ambiguous | none.
    A tie on the latest date is ambiguous unless a human answer names exactly one document number."""
    r = _run()
    docs = scan_documents(kind, customer)
    if not docs:
        return [], f"NO {kind.upper()} DOCUMENTS found for {customer}", "none"
    top = max(d["date"] for d in docs)
    latest = [d for d in docs if d["date"] == top]
    if len(latest) > 1:
        picked = [d for d in latest if any(d["number"].casefold() in a["answer"].casefold()
                                           for a in r.human_answers)]
        if len(picked) == 1:
            return picked, "", "ok"
        nums = [d["number"] for d in latest]
        r.pending = {"kind": "clarification", "meta": {"candidates": nums},
                     "question": (f"{len(latest)} {kind} documents from {customer} share the latest date "
                                  f"({top.isoformat()}): {', '.join(nums)}. Which one should I use?")}
        r.audit("ambiguous_latest_document", customer=customer, candidates=nums)
        return latest, f"AMBIGUOUS: several documents share the latest date: {', '.join(nums)}.", "ambiguous"
    return latest, "", "ok"


# ---------------- files ----------------
@tool
@safe
async def list_files(path: str) -> str:
    """List files in a folder (relative to the project root, e.g. 'sandbox/data/refunds')."""
    p = _run().policy.resolve_path(path)
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) or "(empty)"


@tool
@safe
async def read_file(path: str) -> str:
    """Read a text file or extract the text of a PDF (path relative to the project root)."""
    text = read_text_file(path)
    r = _run()
    if path not in r.files_read:
        r.files_read.append(path)
    r.audit("read_file", path=path)
    return text


# ---------------- browser ----------------
async def _audit_value(element_id: str, value: str) -> str:
    """Never write a password into the audit log."""
    try:
        if await _run().browser._loc(element_id).first.get_attribute("type") == "password":
            return "***"
    except Exception:  # noqa: BLE001
        pass
    return value


async def _snap_after(prefix: str) -> str:
    return f"{prefix}\n{await _run().browser.snapshot()}"


async def _fill_one(element_id: str, value: str) -> tuple[str, str]:
    """Fill one field; a respond_by field always resolves ISO (YYYY-MM-DD). Returns (observation, typed value)."""
    b, typed, note = _run().browser, value, ""
    try:
        name, ident = await b._loc(element_id).first.evaluate("e => [e.name || '', e.id || '']")
        if "respond_by" in (name, ident) and (d := parse_date(value)) is not None and d.isoformat() != value.strip():
            typed, note = d.isoformat(), f" (converted from {value!r})"
    except Exception:  # noqa: BLE001 - unknown element etc.: browser.fill reports it
        pass
    out = await b.fill(element_id, typed)
    return (out.rstrip(".") + note if note and not out.startswith("ERROR") else out), typed


@tool
@safe
async def goto(url: str) -> str:
    """Open a URL in the browser (allow-listed sandbox URLs only). Returns the page snapshot."""
    r = _run()
    blocked = r.policy.check_url(url)
    if blocked:
        return blocked
    status = await r.browser.goto(url)
    r.audit("goto", url=url, status=status)
    return await _snap_after(status)


@tool
@safe
async def snapshot() -> str:
    """Compact text list of visible interactive elements with short ids (e1, e2...)."""
    return await _run().browser.snapshot()


@tool
@safe
async def click(element_id: str) -> str:
    """Click an element by id from the latest snapshot. Returns the new page snapshot."""
    r = _run()
    out = await r.browser.click(element_id)
    r.audit("click", element=element_id, result=out)
    if out.startswith(("ERROR", "BLOCKED")):
        return out
    return await _snap_after(out)


@tool
@safe
async def fill(element_id: str, value: str) -> str:
    """Type a value into an input or choose an option in a select (element id from snapshot)."""
    r = _run()
    out, typed = await _fill_one(element_id, value)
    r.audit("fill", element=element_id, value=await _audit_value(element_id, typed))
    return out


@tool
@safe
async def fill_form(values: dict[str, str]) -> str:
    """Fill several fields at once. `values` maps element id -> value, e.g. {"e1": "Northwind Traders", "e2": "RF-1"}."""
    r = _run()
    res = {eid: await _fill_one(eid, v) for eid, v in values.items()}
    r.audit("fill_form", values={k: await _audit_value(k, typed) for k, (_, typed) in res.items()})
    return "\n".join(out for out, _ in res.values())


@tool
@safe
async def read_page_text() -> str:
    """Read the visible text of the current page (tables, flash messages, errors)."""
    return await _run().browser.read_text()


@tool
@safe
async def screenshot(name: str) -> str:
    """Save a screenshot of the current page as evidence (saved under runs/<id>/)."""
    r = _run()
    safe_name = re.sub(r"[^\w\-]", "_", name)[:40]
    path = await r.browser.screenshot(r.run_dir / f"{safe_name}.png")
    r.screenshots.append(path)
    r.audit("screenshot", path=path)
    return f"Saved {path}"


# ---------------- control ----------------
@tool
@safe
async def remember(key: str, value: str) -> str:
    """Store a discovered value in facts (e.g. customer, refund_number, amount, respond_by, source_file)."""
    r = _run()
    r.facts[key] = value
    r.audit("remember", key=key, value=value)
    return f"Remembered {key}={value}"


@tool
@safe
async def lookup_customer(name: str) -> str:
    """Resolve a customer name or alias against the customer list. Reports AMBIGUOUS when several customers match."""
    r = _run()
    matches = match_customers(name)
    if len(matches) > 1:
        # a human answer that names exactly one candidate resolves the ambiguity
        picked = [m for m in matches if any(m.casefold() in a["answer"].casefold() for a in r.human_answers)]
        if picked:
            best = max(picked, key=len)
            r.facts["customer"] = best
            return f"RESOLVED by human answer: {best}"
        r.pending = {"kind": "clarification", "meta": {"candidates": matches},
                     "question": f"'{name}' matches several customers: {'; '.join(matches)}. Which one do you mean?"}
        r.audit("ambiguous_customer", query=name, candidates=matches)
        return ("AMBIGUOUS: " + "; ".join(matches) + ". Stop now and return status=needs_human "
                "asking the human which customer they mean.")
    if not matches:
        return f"NO MATCH for '{name}'. Known customers: {', '.join(v['name'] for v in load_customers())}"
    r.facts["customer"] = matches[0]
    return f"MATCH: {matches[0]}"


@tool
@safe
async def find_latest_document(kind: str, customer: str) -> str:
    """Find the latest source document for a customer. kind: 'refund' (searches refund PDFs and emails) or 'ticket'.
    'Latest' is the date printed inside the file. Returns the document number, date and source_file;
    read_file the source_file to extract amount and due date. Reports AMBIGUOUS on a tie."""
    r = _run()
    kind = kind.strip().lower()
    if kind not in DOC_FOLDERS:
        return "ERROR: kind must be 'refund' or 'ticket'"
    names = match_customers(customer)
    if len(names) != 1:
        return "ERROR: resolve the customer first with lookup_customer (need exactly one canonical customer)."
    latest, msg, status = resolve_latest(kind, names[0])
    if status == "ambiguous":
        return msg + " Stop now and return status=needs_human."
    if status == "none":
        return msg
    d = latest[0]
    r.facts["source_file"] = d["path"]
    r.audit("find_latest_document", kind=kind, customer=names[0], number=d["number"], path=d["path"])
    return (f"LATEST {kind} for {names[0]}: number={d['number']} date={d['date'].isoformat()} "
            f"source_file={d['path']}")


@tool
@safe
async def submit_record(record_type: str, customer: str, amount: str = "", respond_by: str = "",
                        refund_number: str = "", ticket_number: str = "") -> str:
    """Submit the record on the current page through the policy gate.
    record_type: 'refund' (on /refunds/new, after the form is filled) or 'ticket_resolve' (on a ticket detail page).
    For refunds pass customer, amount (number), respond_by and refund_number exactly as entered in the form.
    For ticket_resolve pass customer and ticket_number."""
    r = _run()
    if record_type not in ("refund", "ticket_resolve"):
        return "ERROR: record_type must be 'refund' or 'ticket_resolve'"
    names = match_customers(customer)
    if len(names) != 1:
        return f"ERROR: '{customer}' is not exactly one known customer; use lookup_customer and pass the canonical name"
    customer = names[0]
    if record_type == "ticket_resolve":
        match = [d for d in scan_documents("ticket", customer) if d["number"] == ticket_number]
        if not match:
            return f"BLOCKED: no source ticket document found for {customer} {ticket_number}"
        r.facts["source_file"] = match[0]["path"]
        # the click is irreversible: make sure the open page really is this ticket (verify would only notice afterwards)
        loc = r.browser.page.locator("#f-ticket_number")
        shown = (await loc.first.inner_text()).strip() if await loc.count() else None
        if shown != ticket_number:
            return (f"ERROR: the current page shows ticket {shown!r}, not {ticket_number}. "
                    f"Open the detail page of {ticket_number} from /tickets first, then call submit_record again.")
        status = (await r.browser.page.locator("#f-status").first.inner_text()).strip()
        if status != "open":
            return f"ERROR: {ticket_number} has status {status!r}, not 'open'; it cannot be resolved again."
    if record_type == "refund":
        if not (amount and refund_number and respond_by):
            return "ERROR: refund needs customer, amount, respond_by and refund_number"
        amount = f"{to_decimal(amount):.2f}"
        parsed = parse_date(respond_by)
        if parsed is None:
            return "ERROR: respond_by not understood"
        due_iso = parsed.isoformat()
        # write the canonical values into the form ourselves, so a wrong format can never reach the server
        page, form = r.browser.page, {}
        if await page.locator("#customer").count():
            await page.locator("#customer").select_option(label=customer)
            await page.locator("#refund_number").fill(refund_number)
            await page.locator("#amount").fill(amount)
            await page.locator("#respond_by").fill(due_iso)
        # the approval threshold is checked on the arguments, so they must match what is really in the form
        for f in ("customer", "refund_number", "amount", "respond_by"):
            loc = page.locator(f"#{f}")
            form[f] = (await loc.first.input_value()).strip() if await loc.count() else None
        bad = []
        if (form["customer"] or "").casefold() != customer.casefold():
            bad.append(f"customer form={form['customer']!r}")
        if form["refund_number"] != refund_number:
            bad.append(f"refund_number form={form['refund_number']!r}")
        try:
            if to_decimal(form["amount"]) != to_decimal(amount):
                bad.append(f"amount form={form['amount']!r}")
        except ValueError:
            bad.append(f"amount form={form['amount']!r}")
        if form["respond_by"] != due_iso:
            bad.append(f"respond_by form={form['respond_by']!r}")
        if bad:
            return ("ERROR: the form on the page does not match the submit_record arguments (" + "; ".join(bad) +
                    "). Fix the form fields (or the arguments) so they agree, then call submit_record again.")
        # code-enforced: must be the latest refund; ties go to a human
        latest, msg, status = resolve_latest("refund", customer)
        if status == "ambiguous":
            return "BLOCKED: " + msg + " Stop now and return status=needs_human."
        if status == "none":
            return "BLOCKED: " + msg
        match = [d for d in latest if d["number"] == refund_number]
        if not match:
            return (f"BLOCKED: {refund_number} is not the latest refund for {customer} "
                    f"(latest is {latest[0]['number']}). Re-check the source documents.")
        r.facts["source_file"] = match[0]["path"]
        if r.policy.requires_approval("refund", amount) and not r.policy.approved(r.approvals, customer, amount):
            r.pending = {"kind": "approval", "meta": {"customer": customer, "amount": amount,
                                                      "refund_number": refund_number},
                         "question": (f"Refund {refund_number} from {customer} for USD {amount} exceeds the "
                                      f"approval threshold (USD {r.policy.approval_threshold}). Approve submission? (yes/no)")}
            r.audit("submit_blocked", reason="approval required", amount=amount, customer=customer)
            return "BLOCKED: approval required. Stop now and return status=needs_human."
    submitted_at = time.time()
    await r.browser.press_gated_submit()
    page = r.browser.page
    ok = await page.locator(".flash-ok").count() > 0
    text = await r.browser.read_text(1200)
    m = re.search(r"/(refunds|tickets)/(\d+)", page.url)
    n = len(r.submissions) + 1
    shot = await r.browser.screenshot(r.run_dir / f"submit_{n}.png")
    r.screenshots.append(shot)
    sub = {"ts": submitted_at, "record_type": record_type, "customer": customer, "amount": amount,
           "respond_by": respond_by, "refund_number": refund_number, "ticket_number": ticket_number,
           "ok": bool(ok and m), "url": page.url, "screenshot": shot,
           "error": None if ok else text[:300]}
    r.submissions.append(sub)
    r.audit("submit_record", **{k: v for k, v in sub.items() if k != "screenshot"})
    if sub["ok"]:
        r.facts.update({"record_type": record_type, "record_id": m.group(2), "record_url": page.url,
                        "customer": customer})
        if record_type == "refund":
            r.facts.update({"amount": amount, "respond_by": respond_by, "refund_number": refund_number})
        else:
            r.facts["ticket_number"] = ticket_number
        return f"SUCCESS: record saved at {page.url}\n{text}"
    return f"SUBMIT FAILED (nothing confirmed saved). Page says:\n{text}"


TOOLS = [list_files, read_file, goto, snapshot, click, fill, fill_form, read_page_text,
         screenshot, lookup_customer, find_latest_document, submit_record]   # no `remember`: tools record facts in code
TOOL_MAP = {t.name: t for t in TOOLS}
TOOL_GUIDE = "\n".join(f"- {t.name}: {(t.description or '').splitlines()[0]}" for t in TOOLS)
