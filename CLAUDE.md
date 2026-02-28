# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI triage system for **Kvinde Klinikken**, a Danish gynecology clinic. Patients interact via a web chat UI and are guided through a conversation with an AI triage agent that classifies their condition (out of 53 gynecological conditions), determines the right doctor, handles scheduling constraints (menstrual cycle windows, lab prerequisites), and produces a structured booking or staff-handoff request.

Built on the **OpenAI Agents SDK** with Pydantic structured outputs and a **FastAPI** web interface.

## Environment

- **Python 3.14** via `.venv` (activate: `source .venv/bin/activate`)
- **Key packages:** `openai-agents` 0.10.2, `pydantic` v2, `PyYAML`, `python-dotenv`, `fastapi`, `uvicorn`, `jinja2`
- **LLM:** Configured via `TRIAGE_MODEL` env var in `.env`
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
python -m tests.war_games.run_war_games                          # all scenarios
python -m tests.war_games.run_war_games --scenario selfpay_smear # one scenario
python -m tests.war_games.run_war_games --list                   # list scenarios
```

## Architecture

Single conversation agent + Python orchestrator + FastAPI web UI.

```
Browser → FastAPI (api.py)
            ├→ WebSocket /ws/{session_id}
            │     → orchestrator.run_agent_turn()
            │         → triage_agent (collects data via conversation)
            │         → enrich_booking() or run_handoff() (deterministic Python)
            │         → confirmation_agent (generates patient message)
            ├→ REST API (/api/sessions, /health)
            └→ Jinja2 templates (chat UI, history dashboard)
```

## Project Structure

```
new_triage/
├── conditions.yaml          # Knowledge base: 53 conditions, groups, cycle rules, prices
├── main.py                  # Uvicorn entry point
├── triage/                  # Python package
│   ├── __init__.py
│   ├── config.py            # YAML loading, MODEL, PROJECT_DIR, CONDITIONS, CONDITION_REFERENCE
│   ├── models.py            # TriageData, BookingRequest, HandoffRequest, WSMessage, SessionMeta
│   ├── tools.py             # 6 raw fns + 2 @function_tool + validator
│   ├── agents.py            # triage_agent, handoff_agent, confirmation_agent + prompts
│   ├── orchestrator.py      # enrich_booking, run_agent_turn, run_handoff, extract_partial_triage
│   ├── session_store.py     # SQLite session metadata for dashboard history
│   ├── auth.py              # Password login via DEMO_USER/DEMO_PASS env vars
│   └── api.py               # FastAPI app, REST routes, WebSocket
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/
│   ├── base.html            # Nav, CSS/JS includes
│   ├── login.html           # Username + password form
│   ├── index.html           # Chat (left) + triage panel (right) + result card
│   └── history.html         # Session history table
├── tests/
│   └── war_games/           # AI-vs-AI testing
│       ├── scenarios.py     # 22 test scenarios
│       ├── runner.py         # Patient simulator + scenario runner
│       └── run_war_games.py # CLI entry point
├── data/                    # SQLite DBs (gitignored)
├── archive/                 # Old monolithic files preserved
└── Triage_Conversation_Chain.md  # Source specification
```

## Key Files

- **`conditions.yaml`** — Knowledge base. 53 conditions (categories A/B/C), 9 condition groups, cycle rules, questionnaires, guidance docs, self-pay prices.
- **`triage/agents.py`** — Agent definitions and the full triage instruction prompt.
- **`triage/orchestrator.py`** — Core logic: `run_agent_turn()` for web UI, enrichment, handoff processing.
- **`triage/api.py`** — FastAPI routes and WebSocket handler.
- **`triage/tools.py`** — Tool functions that query `conditions.yaml`.

## Tool Functions (in triage/tools.py)

| Tool | Purpose |
|------|---------|
| `fetch_condition_details()` | Full condition details by ID (agent tool) |
| `complete_triage()` | Submit collected triage data (agent tool, with validation) |
| `get_condition_details()` | Raw condition lookup |
| `calculate_cycle_window()` | Calculate valid booking dates from cycle data |
| `get_lab_requirements()` | Check age-dependent lab prerequisites |
| `get_questionnaire()` | Get pre-visit questionnaire(s) |
| `get_guidance_document()` | Get patient guidance documents |
| `get_self_pay_price()` | Self-pay pricing lookup |

## Condition Categories

- **Category A (ids 1-5):** Urgent/same-day — always escalate to staff
- **Category B (ids 6-9):** High priority — book within 1-2 weeks
- **Category C (ids 10-53):** Standard bookings, many with cycle-day constraints

## Domain-Specific Rules

- **Doctor routing:** Two doctors — Dr. HS (Skensved) and Dr. LB. Routing depends on condition, patient age (>45 for bleeding), IUD string visibility, menopause history, and fertility context.
- **DSS/private insurance:** Always hand off to staff.
- **Cycle-dependent procedures:** 9 procedures require booking on specific menstrual cycle days.
- **Condition groups:** 9 ambiguous keyword groups require clarifying questions.
- **Languages:** Danish (primary), English, Ukrainian.
- **Self-pay path:** Patients without referrals can proceed as self-pay for certain conditions.
