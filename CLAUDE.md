# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI triage system for **Kvinde Klinikken**, a Danish gynecology clinic. Patients interact via a web chat UI and are guided through a conversation with an AI triage agent that classifies their condition (out of 53 gynecological conditions), determines the right doctor, handles scheduling constraints (menstrual cycle windows, lab prerequisites), and produces a structured booking or staff-handoff request.

Built on the **OpenAI Agents SDK** with Pydantic structured outputs and a **FastAPI** web interface.

## Environment

- **Python 3.14** via `.venv` (activate: `source .venv/bin/activate`)
- **Key packages:** `openai-agents` 0.10.2, `pydantic` v2, `PyYAML`, `python-dotenv`, `fastapi`, `uvicorn`, `jinja2`
- **LLM:** Configured via `TRIAGE_MODEL` env var in `.env` (defaults to `gpt-5.4`)
- **API key:** `OPENAI_API_KEY` in `.env`
- **Demo auth:** `DEMO_USER` / `DEMO_PASS` in `.env` (defaults: admin / kvinde2026)

## Running

```bash
# Activate venv first
source .venv/bin/activate

# Web UI (FastAPI + WebSocket chat)
python main.py
# → http://localhost:8000 (login with DEMO_USER/DEMO_PASS)

# War games (AI-vs-AI testing)
python -m tests.war_games.run_war_games                          # all 22 scenarios
python -m tests.war_games.run_war_games --scenario selfpay_smear # one scenario
python -m tests.war_games.run_war_games --list                   # list scenarios
```

There are no unit tests or linting configured. The war games are the primary test suite — each scenario is a full AI-vs-AI conversation that verifies the triage agent routes correctly (condition ID, doctor, escalation, self-pay, labs, etc.).

## Architecture

Three-agent pipeline with deterministic Python enrichment between LLM stages:

```
Browser ↔ WebSocket /ws/{session_id}
              │
              ↓
     orchestrator.run_agent_turn()
              │
              ├─ [1] triage_agent (multi-turn conversation)
              │     Tools: fetch_condition_details, complete_triage
              │     Collects: insurance, name, phone, condition, cycle info
              │     Outputs: TriageData (via complete_triage tool)
              │
              ├─ [2] Deterministic Python (NO LLM)
              │     orchestrator.enrich_booking() or orchestrator.run_handoff()
              │     Adds: cycle window, lab reqs, questionnaire, guidance doc, pricing
              │     Outputs: BookingRequest or HandoffRequest
              │
              └─ [3] confirmation_agent (single-turn)
                    Generates patient-facing confirmation message
                    Uses patient language, includes prep instructions
```

### Key architectural patterns

- **Session persistence:** The OpenAI Agents SDK's `SQLiteSession` stores full conversation history in `data/triage_sessions.db`. A separate `SessionStore` (in `data/dashboard.db`) tracks session metadata for the history dashboard.
- **Dynamic prompt injection:** `triage_agent.instructions` is a callable (`_build_triage_instructions`) — the full condition reference (all 53 conditions + 9 groups) is regenerated from YAML on every turn. This means edits to `conditions.yaml` take effect immediately.
- **Tool validation loop:** `complete_triage` returns `ERROR:` prefixed strings for missing `condition_id` or `doctor`. The custom `validate_complete_triage` handler checks for this — if it's an error, the agent retries instead of terminating. This is the `tool_use_behavior` callback on the triage agent.
- **Enrichment is deterministic:** After the agent calls `complete_triage`, all downstream logic (cycle calculation, lab checks, questionnaires, pricing) runs in Python with no LLM calls. Only the final confirmation message uses an LLM.
- **Escalation paths:** Category A (urgent), DSS insurance, unclassifiable conditions, and patient "escape hatch" all route through `run_handoff()` → `handoff_agent` → `HandoffRequest`.

## Key Files

- **`conditions.yaml`** — Knowledge base. 53 conditions (categories A/B/C), 9 condition groups, cycle rules, questionnaires, guidance docs, self-pay prices. This is the single source of truth for clinical data.
- **`triage/agents.py`** — Agent definitions and the full triage instruction prompt (~150 lines of LLM instructions). The prompt encodes the entire conversation flow, escalation rules, and condition matching logic.
- **`triage/orchestrator.py`** — Core pipeline: `run_agent_turn()` drives the web UI loop, `enrich_booking()` adds deterministic data, `process_completed_triage()` decides booking vs handoff.
- **`triage/tools.py`** — Two `@function_tool` wrappers (exposed to LLM) + 6 raw Python functions (used by enrichment). The agent only calls `fetch_condition_details` and `complete_triage`.
- **`triage/config.py`** — YAML loading, runtime reload, and `build_condition_reference()` which generates the condition lookup table injected into the agent prompt.
- **`triage/models.py`** — `TriageData` (agent output), `BookingRequest` (enriched booking), `HandoffRequest` (staff escalation).

## Condition Categories

- **Category A (ids 1-5):** Urgent/same-day — always escalate to staff
- **Category B (ids 6-9):** High priority — book within 1-2 weeks
- **Category C (ids 10-53):** Standard bookings, many with cycle-day constraints

## Domain-Specific Rules

- **Doctor routing:** Two doctors — Dr. HS (Skensved) and Dr. LB. Routing depends on condition, patient age (>45 for bleeding), IUD string visibility, menopause history, and fertility context.
- **DSS/private insurance:** Always hand off to staff.
- **Cycle-dependent procedures:** 9 procedures require booking on specific menstrual cycle days.
- **Condition groups:** 9 ambiguous keyword groups require clarifying questions to disambiguate.
- **Languages:** Danish (primary), English, Ukrainian. Agent must match the language of the patient's most recent message.
- **Self-pay path:** Patients without referrals can proceed as self-pay for certain conditions.
- **Referral is passive:** The agent never asks about referrals — it only records `has_referral=true` if the patient volunteers the information.

## War Games Testing

War game scenarios (`tests/war_games/scenarios.py`) define patient personas with expected outcomes. The runner (`tests/war_games/runner.py`) spins up an LLM-powered patient simulator that converses with the triage agent, then verifies the output matches `expect` fields (condition_id, doctor, category, self_pay, etc.) and `expect_escalation`. Scenarios cover Category A emergencies, DSS escalation, group disambiguation, cycle-dependent bookings, self-pay pricing, doctor preference overrides, and edge cases.
