---
description: Company overview, systems and URLs, naming conventions
---
# Brightline (sandbox company)
We are a small company whose support team handles customer refund requests and support tickets.

## Systems
- Internal helpdesk (mock): http://127.0.0.1:5001
  - The browser session is already logged in. Never log in; if you land on /login the tools re-authenticate automatically.
  - Customers: /customers, Refunds: /refunds, New refund: /refunds/new
  - Tickets: /tickets, ticket detail: /tickets/<id>
- Source documents are local files under `sandbox/data/`:
  - `sandbox/data/refunds/`  customer refund request forms (PDF), named `<customer-slug>_<refund-no>.pdf`
  - `sandbox/data/tickets/`  support ticket PDFs, named `<customer-slug>_<ticket-no>.pdf`
  - `sandbox/data/emails/`  customer emails, named `<customer-slug>_<refund-no>.txt`; some refund requests arrive only as emails
    (same fields as the PDF forms: Refund No, Refund Date, Respond-by Date, Refund Amount)

## Conventions
- Amounts are entered as plain numbers with two decimals, no currency symbol or commas (e.g. 348.00).
- Dates: the helpdesk requires YYYY-MM-DD even though the form label says MM/DD/YYYY.
- Always use the customer's canonical name from the customer list.
- "Latest" means the most recent date printed inside the document, not the file name or file time.
- "Respond-by date" is the SLA deadline by which the customer must receive an answer about the refund.
