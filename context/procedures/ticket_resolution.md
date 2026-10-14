---
description: Procedure for marking a customer's support ticket as resolved in the helpdesk
---
# Procedure: resolve a support ticket
1. Confirm the customer with `lookup_customer` (ask the human if AMBIGUOUS).
2. Call `find_latest_document(kind="ticket", customer=<canonical name>)` to get the latest ticket number and its source_file.
3. `read_file` the source_file to confirm the ticket number.
4. Open `/tickets`, find that ticket and open its detail page (it must be open, not already resolved).
5. Call `submit_record` with record_type="ticket_resolve", customer and ticket_number (this presses "Mark as resolved").
6. Take a screenshot of the result.
