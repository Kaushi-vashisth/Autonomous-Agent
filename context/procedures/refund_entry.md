---
description: Step-by-step procedure for logging a customer refund request in the helpdesk
---
# Procedure: log a customer refund request
1. Confirm the customer with `lookup_customer`. If it reports AMBIGUOUS, ask the human (needs_human) and do not continue.
2. Call `find_latest_document(kind="refund", customer=<canonical name>)`. It searches refund PDFs and refund emails and
   picks the latest by the date printed inside each file. If it reports AMBIGUOUS (several share the latest date), ask the human.
3. `read_file` the returned source_file and extract: refund_number, amount (Refund Amount, numeric only), respond_by (Respond-by Date). Report them in the step result facts.
4. Open `/refunds/new`.
5. Fill customer, refund number, amount, respond-by date using `fill_form`, then call `submit_record` with record_type="refund".
6. If the helpdesk shows a validation error, read the message, correct the field and resubmit. On HTTP 500 / Internal Server Error the save did not happen: goto /refunds/new again (the page has no form elements) and call submit_record once more with the SAME values. Do not change formats or values.
7. Success is a flash message and the refund detail page. Take a screenshot.
Never click the form's submit button directly; always use `submit_record`.
