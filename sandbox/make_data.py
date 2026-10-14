"""Generate sample refund-request / ticket PDFs and emails (no third-party deps). Run: python sandbox/make_data.py"""
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines):
    content = "BT /F1 12 Tf 14 TL 60 760 Td\n" + "\n".join(f"({_esc(l)}) Tj T*" for l in lines) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# customer, slug, refund no, request date, respond-by date, amount, reason
REFUNDS = [
    ("Northwind Traders", "northwind-traders", "RF-2042", "18 Dec 2025", "17 Jan 2026", "125.00", "Late delivery compensation"),
    ("Northwind Traders", "northwind-traders", "RF-2057", "22 Jan 2026", "21 Feb 2026", "98.40", "Wrong item shipped"),
    ("Northwind Traders", "northwind-traders", "RF-2071", "27 Feb 2026", "29 Mar 2026", "348.00", "Damaged goods, February order"),
    ("Northwind Logistics", "northwind-logistics", "RF-0311", "03 Feb 2026", "05 Mar 2026", "215.00", "Duplicate billing"),
    ("Northwind Logistics", "northwind-logistics", "RF-0329", "10 Mar 2026", "09 Apr 2026", "782.50", "Service outage credit, March"),
    ("Contoso Ltd", "contoso-ltd", "RF-5510", "14 Feb 2026", "16 Mar 2026", "64.00", "Cancelled subscription"),
    ("Fabrikam Inc", "fabrikam-inc", "RF-0088", "05 Jan 2026", "04 Feb 2026", "41.25", "Unused licence seats"),
    # same request date as RF-0088 -> "latest" is ambiguous, a human must choose
    ("Fabrikam Inc", "fabrikam-inc", "RF-0089", "05 Jan 2026", "11 Feb 2026", "51.75", "Support plan downgrade"),
]
# Refund requests that arrive as emails (the refund source is PDFs AND emails)
EMAIL_REFUNDS = [
    ("Contoso Ltd", "contoso-ltd", "RF-5602", "20 Mar 2026", "19 Apr 2026", "112.50", "Faulty gadget returned"),
]
# customer, slug, ticket no, opened date, issue
TICKETS = [
    ("Contoso Ltd", "contoso-ltd", "TCK-7001", "05 Jan 2026", "Cannot log in to portal"),
    ("Contoso Ltd", "contoso-ltd", "TCK-7002", "20 Feb 2026", "Invoice PDF will not download"),
    ("Contoso Ltd", "contoso-ltd", "TCK-7003", "12 Mar 2026", "Gadget firmware update fails"),
    ("Northwind Traders", "northwind-traders", "TCK-4410", "01 Mar 2026", "Order tracking page shows an error"),
    ("Fabrikam Inc", "fabrikam-inc", "TCK-9100", "02 Feb 2026", "Licence seats not syncing"),
]


def main():
    for d in ("refunds", "tickets", "emails"):
        (DATA / d).mkdir(parents=True, exist_ok=True)
    for v, slug, no, rdate, due, amt, why in REFUNDS:
        lines = ["REFUND REQUEST", f"Customer: {v}", f"Refund No: {no}", f"Refund Date: {rdate}",
                 f"Respond-by Date: {due}", f"Reason: {why}", f"Refund Amount: USD {amt}",
                 "Contact: support@" + slug + ".example"]
        (DATA / "refunds" / f"{slug}_{no}.pdf").write_bytes(make_pdf(lines))
    for v, slug, no, rdate, due, amt, why in EMAIL_REFUNDS:
        body = (f"From: help@{slug}.example\nTo: support@brightline.example\nSubject: Refund request {no} from {v}\n\n"
                f"Hello, please find our refund request details below.\n\nCustomer: {v}\nRefund No: {no}\n"
                f"Refund Date: {rdate}\nRespond-by Date: {due}\nReason: {why}\nRefund Amount: USD {amt}\n\nThanks")
        (DATA / "emails" / f"{slug}_{no}.txt").write_text(body, encoding="utf-8")
    for v, slug, no, odate, issue in TICKETS:
        lines = ["SUPPORT TICKET", f"Customer: {v}", f"Ticket No: {no}", f"Opened Date: {odate}",
                 f"Issue: {issue}", "Assigned to: Brightline Support"]
        (DATA / "tickets" / f"{slug}_{no}.pdf").write_bytes(make_pdf(lines))
    # distractor emails: they mention "latest" things but carry no structured refund/ticket fields
    (DATA / "emails" / "northwind_followup.txt").write_text(
        "From: help@northwind.example\nSubject: Reminder - February refund\n\n"
        "Hi, just a reminder that our latest refund request is in the usual folder. Thanks, Northwind support\n",
        encoding="utf-8")
    (DATA / "emails" / "contoso_update.txt").write_text(
        "From: ops@contoso.example\nSubject: Ticket update\n\n"
        "Our most recent ticket has been worked on and should be ready to close this week.\n", encoding="utf-8")
    print("Sample data written to", DATA)


if __name__ == "__main__":
    main()
