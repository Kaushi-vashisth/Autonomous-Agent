# Operator report: DONE

**Goal:** Mark the latest ticket from Contoso as resolved.
**Run:** 20261014-110823-297c

## Facts
- customer: Contoso Ltd
- ticket_number: TCK-7002
- source_file: sandbox/data/tickets/contoso-ltd_TCK-7002.pdf
- ticket_status: resolved
- screenshot_name: ticket_resolved_confirmation
- record_type: ticket_resolve
- record_id: 2
- record_url: http://127.0.0.1:5001/tickets/2

## Verification
- PASS record_check: ticket shows resolved ({'customer': 'Contoso Ltd', 'ticket_number': 'TCK-7002', 'status': 'resolved'}). Evidence: D:\autonomus agent\runs\20261014-110823-297c\verify_record.png
- PASS source_check: Extracted values appear literally in sandbox/data/tickets/contoso-ltd_TCK-7002.pdf
- PASS side_effect_check: Exactly one new record; approval ordering OK

## Approvals / human input
- none

Replans used: 1

## Evidence
- D:\autonomus agent\runs\20261014-110823-297c\ticket_resolved_confirmation.png
- D:\autonomus agent\runs\20261014-110823-297c\submit_1.png
- D:\autonomus agent\runs\20261014-110823-297c\ticket_resolved_confirmation.png
- D:\autonomus agent\runs\20261014-110823-297c\verify_record.png
- audit log: D:\autonomus agent\runs\20261014-110823-297c\audit.jsonl