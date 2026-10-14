# Operator report: DONE

**Goal:** Mark the latest ticket from Contoso as resolved.
**Run:** 20261014-110408-e956

## Facts
- customer: Contoso Ltd
- source_file: sandbox/data/tickets/contoso-ltd_TCK-7003.pdf
- ticket_date: 2026-03-12
- ticket_number: TCK-7003
- status: resolved
- record_type: ticket_resolve
- record_id: 3
- record_url: http://127.0.0.1:5001/tickets/3

## Verification
- PASS record_check: ticket shows resolved ({'customer': 'Contoso Ltd', 'ticket_number': 'TCK-7003', 'status': 'resolved'}). Evidence: D:\autonomus agent\runs\20261014-110408-e956\verify_record.png
- PASS source_check: Extracted values appear literally in sandbox/data/tickets/contoso-ltd_TCK-7003.pdf
- PASS side_effect_check: Exactly one new record; approval ordering OK

## Approvals / human input
- none

Replans used: 0

## Evidence
- D:\autonomus agent\runs\20261014-110408-e956\submit_1.png
- D:\autonomus agent\runs\20261014-110408-e956\ticket_resolved.png
- D:\autonomus agent\runs\20261014-110408-e956\verify_record.png
- audit log: D:\autonomus agent\runs\20261014-110408-e956\audit.jsonl