# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI triage system for **Kvinde Klinikken**, a Danish gynecology clinic. Patients interact via chat (WhatsApp/web) and are guided through a multi-agent pipeline that classifies their condition (out of 53 gynecological conditions), determines the right doctor, handles scheduling constraints (menstrual cycle windows, lab prerequisites), and produces a structured booking or staff-handoff request.

Built on the **OpenAI Agents SDK** with a hub-and-spoke agent architecture and Pydantic structured outputs.

## Environment

- **Python 3.14** via `.venv` (activate: `source .venv/bin/activate`)
- **Key packages:** `openai-agents` 0.10.2, `pydantic` v2, `PyYAML`, `python-dotenv`
- **LLM:** Configured via `TRIAGE_MODEL` env var in `.env` (currently `gpt-5-mini`)
- **API key:** `OPENAI_API_KEY` in `.env`

## Running

```bash
# Activate venv first
source .venv/bin/activate

# Interactive triage CLI (war-gaming)
cd war_games && python triage_app.py

# Single turn (maintains session state across calls)
cd war_games && python run_turn.py <session_name> "<patient message>"

# Jupyter notebooks
jupyter notebook kvinde_klinikken_triage.ipynb
```

## Architecture: Hub-and-Spoke Agent Pipeline

The system uses a **Dispatch agent** as a central router (hub) with 5 specialist agents (spokes) that hand back to Dispatch after completing their step. Two terminal agents produce structured Pydantic output.

```
Patient Message → Dispatch (router)
                    ├→ Intake Agent         (Steps 0-3: language, insurance, referral, name, phone, doctor pref)
                    ├→ Classification Agent  (Step 4: identify condition from 53 options via keyword search)
                    ├→ Routing Agent         (Step 5: determine doctor HS/LB based on condition + routing rules)
                    ├→ Scheduling Agent      (Steps 6-7: cycle window calculation + lab prerequisites)
                    ├→ Booking Agent         (Steps 8-11: questionnaires, guidance docs, slot presentation → BookingRequest)
                    └→ Staff Handoff Agent   (terminal: produces HandoffRequest for urgent/DSS/unclear cases)
```

Each specialist agent hands back to Dispatch, which determines the next incomplete step and routes forward. Booking and Staff Handoff are terminal — they produce structured Pydantic output (`BookingRequest` or `HandoffRequest`).

## Key Files

- **`conditions.yaml`** — The knowledge base. Contains all 53 conditions (categories A/B/C), 9 condition groups for disambiguation, cycle rules, questionnaire mappings, guidance documents, and self-pay prices. This is the single source of truth for medical routing logic.
- **`war_games/triage_app.py`** — The standalone CLI app. Contains all Pydantic models, YAML loading, tool functions (8 tools), and all agent definitions with their prompts. This is the primary codebase.
- **`war_games/run_turn.py`** — Single-turn runner for scripted war-game testing. Persists agent state in `agent_state.json`.
- **`Triage_Conversation_Chain.md`** — Source specification document defining the full 11-step triage flow, all conditions, routing rules, and escalation logic.
- **`docs/plans/`** — Design doc and implementation plan.
- **`kvinde_klinikken_triage.ipynb`** — Original Jupyter notebook PoC (predates the standalone app).

## Tool Functions (in triage_app.py)

All tools search/query `conditions.yaml` and return JSON strings:

| Tool | Used By | Purpose |
|------|---------|---------|
| `search_conditions()` | Classification | Keyword search across conditions + groups |
| `fetch_condition_details()` | Routing | Full condition details by ID |
| `compute_cycle_window()` | Scheduling | Calculate valid booking dates from cycle data |
| `check_lab_requirements()` | Scheduling | Check age-dependent lab prerequisites |
| `fetch_questionnaire()` | Booking | Get pre-visit questionnaire(s) |
| `fetch_guidance_document()` | Booking | Get patient guidance documents |
| `find_available_slots()` | Booking | Mock appointment slots (to be replaced with Novax integration) |
| `check_self_pay_price()` | Booking | Self-pay pricing lookup |

## Condition Categories

- **Category A (ids 1-5):** Urgent/same-day — always escalate to staff (heavy bleeding, severe pain, ectopic pregnancy, 1st trimester bleeding, abortion)
- **Category B (ids 6-9):** High priority — book within 1-2 weeks (cancer package, postmenopausal bleeding, cone biopsy, contact bleeding)
- **Category C (ids 10-53):** Standard — the bulk of bookings, many with cycle-day constraints and routing rules

## Known Issues (from War Games)

Documented in `war_games/war_game_results.md`:
1. **Dispatch produces text instead of routing** — says "someone will contact you" instead of silently handing off
2. **Escape hatch too aggressive** — "speak to someone" in conversation history permanently triggers escalation
3. **Language detection fails on short messages** — "hi" defaults to Danish
4. **Booking skips two-step slot presentation** — produces BookingRequest without showing slots first
5. **Date format inconsistency** — model uses DD-MM-YYYY instead of ISO YYYY-MM-DD

## Domain-Specific Rules

- **Doctor routing:** Two doctors — Dr. HS (Skensved) and Dr. LB. Routing depends on condition, patient age (>45 for bleeding), IUD string visibility, menopause history, and fertility context.
- **DSS/private insurance:** Always hand off to staff — too many unknowns for AI.
- **Cycle-dependent procedures:** 9 procedures require booking on specific menstrual cycle days (e.g., IUD insertion CD 3-7, hysteroscopy CD 4-8). Endometriosis is special: "just before next period."
- **Condition groups:** 9 ambiguous keyword groups (IUD, Prolapse, Polyps, etc.) require clarifying questions before mapping to a specific condition ID.
- **Languages:** Danish (primary), English, Ukrainian. Agent must respond in the patient's language.
- **Self-pay path:** Patients without referrals can proceed as self-pay for certain conditions.

## Agent Prompting Conventions

All agents share a `SPECIALIST_PREAMBLE` that enforces:
- Read full conversation history before acting
- Never re-ask information already provided
- One question at a time, natural conversation (no numbered lists)
- Language matching with the patient
- Immediate handoff on "speak to staff" requests
