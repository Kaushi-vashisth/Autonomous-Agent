# Autonomous Helpdesk Operator

A prototype AI operator that turns a short business request into actions in a mock helpdesk. Instead of only generating instructions, it can inspect local company documents, use a browser to interact with a simulated support application, pause for clarification or approval, recover from selected failures, and check whether the requested change actually happened.

The prototype focuses on two workflows:
- **Refund entry:** find the latest refund for a customer, extract the relevant details from a PDF or email, and enter the record into the helpdesk.
- **Ticket resolution:** find a customer's latest ticket and mark it resolved.

It is intentionally scoped to a local sandbox, not a production helpdesk or arbitrary websites.

## What it demonstrates

- **Goal-to-action workflow:** converts a natural-language request into a structured plan.
- **Context selection:** loads company and policy context and selects relevant procedure documents.
- **Browser and file tools:** reads local PDFs/text files and interacts with the mock helpdesk through Playwright.
- **Human-in-the-loop controls:** asks for clarification when a customer/document is ambiguous and requests approval for refunds above the configured threshold.
- **Bounded recovery:** retries a failed step, replans after failures, and escalates to a person after the configured replan limit.
- **Policy gates:** allow-lists browser URLs and file paths; the record-submission tool enforces approval and latest-document checks.
- **Verification and evidence:** checks the source document, the saved helpdesk record, and side effects; stores logs, screenshots, and a run report.
- **Evaluation cases:** includes scripted cases for ambiguity, recovery, approval, verification, tied dates, and a second workflow (ticket resolution).

## Architecture

```text
User request
    |
    v
Context loading and selection
    |
    v
Planner (structured plan)
    |
    v
Actor / tool-using agent
    |
    v
Observe result
    |-----------------------------|
    | success                     | failure / ambiguity / policy gate
    v                             v
Next step                     Retry / replan / ask human
    |                             |
    +---------------<-------------+
    |
    v
Verifier
    |
    v
Run report, audit log, screenshots
```

The workflow is implemented as a **LangGraph state graph** (`agent/graph.py`). Planning and context selection use structured model outputs. The actor executes one planned step at a time using LangChain's agent framework and a defined set of tools. Runtime state is shared through a per-run context and graph state. The browser is controlled by Playwright and targets the local Flask sandbox in `sandbox/`; it does not operate arbitrary third-party systems.

### Verification

The verifier runs three checks:
1. **Saved record:** reads the helpdesk page and checks the submitted record's fields.
2. **Source consistency:** confirms the extracted facts are present in the specific source document.
3. **Side effects and policy:** checks that the expected record was created and any required approval occurred before submission.

The sandbox can inject a date-format mismatch and a one-time HTTP 500 so recovery behavior can be exercised. These are demo faults, not claims about handling every real-world failure.

## Technology

- Python
- LangGraph for workflow state and routing
- LangChain agents and structured output
- Pydantic for typed plans and step results
- Playwright for browser automation
- Flask for the local mock helpdesk
- Streamlit for the operator interface
- pypdf for extracting text from PDF documents
- pandas for displaying helpdesk/report data
- PyYAML and python-dotenv for configuration and environment variables

The model provider is configurable. The default is Anthropic (`claude-sonnet-5-5`); the code also supports Groq, OpenAI, Google, and xAI providers when the corresponding LangChain integration and environment variables are configured. No API key is included in this repository.

## Setup

Python 3.10+ is recommended.

### 1. Create an environment and install dependencies

**macOS/Linux**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**Windows PowerShell**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure the model provider

Copy `.env.example` to `.env` and add the API key for your chosen provider.

**macOS/Linux**
```bash
cp .env.example .env
```

**Windows PowerShell**
```powershell
Copy-Item .env.example .env
```

By default, the project uses:
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key_here
```

If using OpenAI, Google, or xAI, set `OPERATOR_MODEL` to a model available to your account and install/confirm the matching provider integration. For Groq, set `LLM_PROVIDER=groq` and `GROQ_API_KEY`.

### 3. Run the Streamlit interface

From the project root:
```bash
streamlit run streamlit_app.py
```

The app has three tabs:
- **Run:** enter a request or choose an example; inspect the plan, activity, prompts for human input, and final verification.
- **Helpdesk:** view the mock application's records and source documents.
- **History:** inspect completed runs and their reports.

The helpdesk starts automatically for a run. Demo login credentials are `demo` / `demo123` and are only for the local sandbox.

### CLI alternative

```bash
python main.py
python main.py "Mark the latest ticket from Contoso as resolved."
python main.py --headed "Find the latest refund from Contoso Ltd and log it in the helpdesk."
python main.py --debug "Find the latest refund from Northwind Traders and log it in the helpdesk."
```

`--headed` opens a visible browser. `--debug` prints detailed model and tool traces.

## Tests and evaluation

Run the offline tool/policy/verifier tests:
```bash
python tests/test_tools_offline.py
```

Run the scripted end-to-end sandbox evaluations:
```bash
python evals/run_evals.py
```

Run one evaluation by ID, for example:
```bash
python evals/run_evals.py approval
```

The included evaluation cases cover ambiguity handling, a recoverable failure, approval gating, source/record verification, tied latest-document dates, and ticket resolution. They are useful prototype checks, not a comprehensive production reliability benchmark.

## Runtime artifacts and debugging

Each run writes artifacts under `runs/<run_id>/`, including:
- `audit.jsonl` — structured events and decisions
- `operator.log` — detailed model, tool, and workflow logs
- screenshots captured during submission/verification
- `report.json` and `report.md` — final result and summary

The Streamlit interface also shows the activity timeline, verification results, screenshots, and downloadable reports. For more detail, set `LOG_LEVEL=DEBUG` in `.env` or run the CLI with `--debug`. Do not use debug logs with sensitive production data.

## Configuration and safety boundaries

Company context, procedures, and policies live under `context/`. Policy configuration includes the approval threshold, allowed URLs, and allowed file paths. The submit action is gated in code rather than relying only on the model's instructions.

The included helpdesk and documents are synthetic demo data. The prototype should be run against the local sandbox; it is not configured for real customer records or unrestricted browser use.

## Known limitations

- Supports a small, predefined set of workflows and local files, not arbitrary enterprise tasks.
- Uses a mock Flask helpdesk and a limited Playwright browser toolset; it is not a general desktop/computer-use agent.
- Context selection is based on a small local document set.
- Run state and memory are in-process and per-run; there is no durable cross-run company memory or multi-user execution model.
- The model receives text snapshots rather than visual screenshots as its primary browser observation.
- Recovery is bounded by fixed retry, tool-call, and replan limits; some failures still require a person.
- The included evaluations cover selected scenarios only and do not establish production-level reliability or security.

## Next steps

1. Add durable, isolated run state and a persistent company-memory layer.
2. Expand tool/connector interfaces so new workflows can be added without modifying core orchestration.
3. Add richer failure classification, configurable retry policies, and more systematic evaluation across varied tasks.
4. Improve verification with stronger evidence linking and clearer handling of partial completion.
5. Add authentication, role-based permissions, and deployment safeguards before connecting to any real internal system.

## Repository layout

```text
agent/       Planner, actor, tools, policy, graph, state, verification, reporting
context/     Company information, policies, and workflow procedures
sandbox/     Flask mock helpdesk and synthetic PDFs/emails/tickets
ui/          Background runner for the Streamlit interface
tests/       Offline tool/policy/verifier tests
evals/       Scripted end-to-end evaluation cases
runs/        Per-run logs, screenshots, and reports (generated at runtime)
main.py      CLI entry point
streamlit_app.py  Streamlit application
```
