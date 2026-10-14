---
description: Approval thresholds and what the AI may and may not do
approval_threshold: 500
allowed_urls: http://127.0.0.1:5001
allowed_paths: sandbox/data
---
# Policies
- Refunds above the approval threshold (USD 500) need recorded human approval before they are logged. The system blocks the submit until approval is recorded.
- If the customer name is ambiguous (matches more than one customer), ask the human which one. Never guess.
- If several refund requests could be "the latest" (same date), ask the human.
- The AI may only open URLs on the allow-list and read files under the allowed paths.
- The AI must never log the same refund twice. If the helpdesk reports a duplicate, stop and report it.
- The AI must not change or delete existing helpdesk records.
