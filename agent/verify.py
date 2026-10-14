"""Three deterministic checks (no LLM). All must pass before the task can complete."""
import re
from datetime import date, datetime
from decimal import Decimal

from agent import state as S
from agent.policy import parse_date, to_decimal
from agent.tools import read_text_file

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def dates_in_text(text: str) -> set:
    found = set()
    for y, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        found.add(_d(int(y), int(m), int(d)))
    for m, d, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        found.add(_d(int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text):
        if mon[:3].lower() in MONTHS:
            found.add(_d(int(y), MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", text):
        if mon[:3].lower() in MONTHS:
            found.add(_d(int(y), MONTHS[mon[:3].lower()], int(d)))
    found.discard(None)
    return found


def _d(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def amounts_in_text(text: str) -> set:
    out = set()
    for tok in re.findall(r"\d[\d,]*\.\d{2}\b|\b\d+\b", text):
        try:
            out.add(Decimal(tok.replace(",", "")))
        except Exception:  # noqa: BLE001
            pass
    return out


def _result(passed: bool, detail: str) -> dict:
    return {"passed": bool(passed), "detail": detail}


async def _read_record(url: str, fields: list[str], shot_name: str):
    """Open the saved record in a fresh tab and read the given #f-<field> cells."""
    r = S.RUN
    page = await r.browser.context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        values = {}
        for f in fields:
            loc = page.locator(f"#f-{f}")
            values[f] = (await loc.first.inner_text()).strip() if await loc.count() else None
        shot = str(r.run_dir / shot_name)
        await page.screenshot(path=shot, full_page=True)
        r.screenshots.append(shot)
        return values, shot
    finally:
        await page.close()


async def check_record(facts: dict) -> dict:
    url, rtype = facts.get("record_url"), facts.get("record_type")
    if not url:
        return _result(False, "No saved record found (nothing was submitted successfully).")
    if rtype == "refund":
        vals, shot = await _read_record(url, ["customer", "refund_number", "amount", "respond_by"], "verify_record.png")
        problems = []
        if (vals["customer"] or "").casefold() != facts.get("customer", "").casefold():
            problems.append(f"customer helpdesk={vals['customer']!r} facts={facts.get('customer')!r}")
        try:
            if to_decimal(vals["amount"]) != to_decimal(facts.get("amount")):
                problems.append(f"amount helpdesk={vals['amount']} facts={facts.get('amount')}")
        except ValueError:
            problems.append("amount not numeric")
        if parse_date(vals["respond_by"] or "") != parse_date(facts.get("respond_by", "")):
            problems.append(f"respond_by helpdesk={vals['respond_by']} facts={facts.get('respond_by')}")
        if facts.get("refund_number") and vals["refund_number"] != facts["refund_number"]:
            problems.append(f"refund_number helpdesk={vals['refund_number']} facts={facts['refund_number']}")
        return _result(not problems, "; ".join(problems) or f"helpdesk record matches facts ({vals}). Evidence: {shot}")
    if rtype == "ticket_resolve":
        vals, shot = await _read_record(url, ["customer", "ticket_number", "status"], "verify_record.png")
        problems = []
        if (vals["customer"] or "").casefold() != facts.get("customer", "").casefold():
            problems.append(f"customer helpdesk={vals['customer']!r} facts={facts.get('customer')!r}")
        if vals["ticket_number"] != facts.get("ticket_number"):
            problems.append(f"ticket_number helpdesk={vals['ticket_number']} facts={facts.get('ticket_number')}")
        if vals["status"] != "resolved":
            problems.append(f"status is {vals['status']!r}, expected 'resolved'")
        return _result(not problems, "; ".join(problems) or f"ticket shows resolved ({vals}). Evidence: {shot}")
    return _result(False, f"Unknown record_type {rtype!r}")


def check_source(facts: dict) -> dict:
    """Re-read the source document and confirm the extracted values literally appear in it."""
    rtype, src = facts.get("record_type"), facts.get("source_file")
    if not src:
        return _result(False, "No source_file recorded; cannot confirm the extraction.")
    try:
        text = read_text_file(src)
    except Exception as e:  # noqa: BLE001
        return _result(False, f"could not re-read {src}: {e}")
    problems = []
    if (facts.get("customer") or "").casefold() not in text.casefold():
        problems.append("customer name not in source")
    if rtype == "refund":
        try:
            if to_decimal(facts["amount"]) not in amounts_in_text(text):
                problems.append(f"amount {facts['amount']} not in source")
        except (KeyError, ValueError):
            problems.append("amount missing or not numeric")
        due = parse_date(facts.get("respond_by", ""))
        if due is None or due not in dates_in_text(text):
            problems.append(f"due date {facts.get('respond_by')} not in source")
        if facts.get("refund_number") and facts["refund_number"] not in text:
            problems.append(f"refund number {facts['refund_number']} not in source")
    elif rtype == "ticket_resolve":
        if not facts.get("ticket_number") or facts["ticket_number"] not in text:
            problems.append(f"ticket number {facts.get('ticket_number')} not in source")
    else:
        problems.append(f"unknown record_type {rtype!r}")
    return _result(not problems, "; ".join(problems) or f"Extracted values appear literally in {src}")


def check_side_effects(facts: dict) -> dict:
    r = S.RUN
    ok_subs = [s for s in r.submissions if s["ok"]]
    stats = S.fetch_stats()
    problems = []
    if len(ok_subs) != 1:
        problems.append(f"{len(ok_subs)} successful submissions this run (expected exactly 1)")
    rtype = facts.get("record_type")
    if rtype == "refund":
        delta = stats["refunds"] - r.baseline.get("refunds", 0)
        if delta != 1:
            problems.append(f"helpdesk refund count changed by {delta} (expected +1)")
        for s in ok_subs:
            if r.policy.requires_approval("refund", s["amount"]):
                prior = [a for a in r.approvals if a["ts"] < s["ts"] and
                         a["customer"].casefold() == s["customer"].casefold() and
                         to_decimal(a["amount"]) == to_decimal(s["amount"])]
                if not prior:
                    problems.append("approval required but none logged before the submit")
    elif rtype == "ticket_resolve":
        delta = stats["tickets_resolved"] - r.baseline.get("tickets_resolved", 0)
        if delta != 1:
            problems.append(f"resolved tickets changed by {delta} (expected +1)")
    else:
        problems.append("no record type")
    return _result(not problems, "; ".join(problems) or "Exactly one new record; approval ordering OK")


async def run_checks(facts: dict) -> dict:
    return {"record_check": await check_record(facts),
            "source_check": check_source(facts),
            "side_effect_check": check_side_effects(facts)}
