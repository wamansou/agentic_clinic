# Kvinde Klinikken AI Triage — Architecture Design

**Date:** 2026-02-26
**Type:** Proof of Concept (Jupyter Notebook)
**Stack:** OpenAI Agents SDK + Pydantic + YAML config

---

## Overview

An AI triage system for Kvinde Klinikken (Danish gynecology clinic) that conducts natural multi-turn conversations with patients via chat to classify their condition, determine the right doctor, handle scheduling constraints, and produce a structured booking request. Built on the OpenAI Agents SDK using a pipeline of specialist agents with handoffs.

## Architecture: Pipeline of Specialist Agents

```
Patient Message
       │
       ▼
┌─────────────────────────────────────────────────┐
│  INTAKE AGENT (Steps 0-3)                       │
│  - Detect language (DA/EN/UK)                   │
│  - GDPR consent                                 │
│  - Insurance check (DSS → HandoffRequest)       │
│  - Referral check (no referral → self-pay path) │
│  - Doctor preference question                   │
│  Output: → Classification Agent                 │
│       OR → HandoffRequest (DSS / no consent)    │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  CLASSIFICATION AGENT (Step 4)                  │
│  - Asks patient to describe their issue         │
│  - Tool: lookup_conditions() → YAML             │
│  - Handles condition groups (IUD, prolapse...)  │
│    by guiding patient with follow-up questions  │
│  - Classifies into Category A / B / C           │
│  - Category A → HandoffRequest (urgent)         │
│  Output: → Routing Agent (with condition_id)    │
│       OR → HandoffRequest                       │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  ROUTING AGENT (Step 5)                         │
│  - Tool: get_condition_details(condition_id)    │
│  - Asks conditional follow-ups:                 │
│    age, IUD strings, menopause history, etc.    │
│  - Determines: doctor (HS/LB), duration,        │
│    priority window                              │
│  - Respects doctor preference override          │
│  Output: → Scheduling Agent                     │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  SCHEDULING AGENT (Steps 6-7)                   │
│  - Tool: calculate_cycle_window()               │
│  - Tool: get_lab_requirements()                 │
│  - Asks for last period date (if needed)        │
│  - Handles irregular/absent cycles              │
│  - Checks lab prerequisites                     │
│  Output: → Booking Agent                        │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│  BOOKING AGENT (Steps 8-11)                     │
│  - Tool: get_questionnaire()                    │
│  - Tool: get_guidance_document()                │
│  - Tool: get_available_slots() (mock for PoC)   │
│  - Tool: get_self_pay_price() (if applicable)   │
│  - Sends questionnaire + guidance info          │
│  - Presents mock booking slots                  │
│  - Notes if booked outside clinic hours         │
│  Output: BookingRequest (structured Pydantic)   │
└─────────────────────────────────────────────────┘
```

Any agent can produce a `HandoffRequest` at any point if the patient says "speak to staff" or describes something unclassifiable.

---

## Pydantic Output Models

### Shared context (passed between agents via handoff input_type)

```python
class PatientContext(BaseModel):
    language: str                     # "da", "en", or "uk"
    gdpr_consent: bool
    insurance_type: str               # "public", "dss", or "self_pay"
    has_referral: bool
    is_followup: bool
    patient_name: str | None
    patient_age: int | None
    email: str | None
    doctor_preference: str | None     # "HS", "LB", "earliest", or None

class ConditionMatch(BaseModel):
    condition_id: int                 # 1-53 from YAML
    condition_name: str
    category: str                     # "A", "B", or "C"
    doctor: str                       # "HS", "LB", or "same_doctor"
    duration_minutes: int
    priority_window: str | None       # "same_day", "1_2_days", "1_week", "14_days", "1_month", "standard"
```

### Final outputs

```python
class BookingRequest(BaseModel):
    patient: PatientContext
    condition: ConditionMatch
    # Scheduling
    cycle_dependent: bool
    last_period_date: str | None
    cycle_length: int | None
    cycle_range: tuple[int, int] | None
    no_cycle: bool
    valid_booking_window: str | None
    scheduling_restrictions: list[str]
    provera_recommended: bool
    # Lab
    lab_required: bool
    lab_details: str | None
    lab_status: str | None            # "completed", "pending", "not_needed"
    # Documents
    questionnaire: str | None
    partner_questionnaire: str | None
    guidance_document: str | None
    # Booking
    tentative: bool
    booked_outside_hours: bool
    self_pay: bool
    self_pay_price_dkk: float | None
    selected_slot: str | None
    notes: str | None

class HandoffRequest(BaseModel):
    patient: PatientContext
    reason: str
    urgency: str                      # "immediate", "high", "normal"
    conversation_summary: str
    suggested_action: str | None
```

---

## YAML Config Structure

File: `conditions.yaml`

### Condition groups (for disambiguation)

```yaml
condition_groups:
  - group: "IUD"
    keywords: ["spiral", "IUD", "coil", "ВМС"]
    clarifying_question: "What do you need regarding your IUD?"
    options:
      - label: "New insertion"
        condition_id: 19
      - label: "Removal (strings visible)"
        condition_id: 20
      - label: "Replacement"
        condition_id: 21
      - label: "Removal (strings not visible / over 8 years)"
        condition_id: 22
      - label: "Not sure"
        condition_id: null
  # ... (Prolapse, Polyps, Lichen, Incontinence, PCOS, Menopause,
  #      Contraception, Cysts — see design discussion)
```

### Individual conditions

```yaml
conditions:
  - id: 19
    name: "IUD insertion"
    category: "C"
    keywords: ["spiral insertion", "IUD insertion", "spiral indsættelse", "встановлення ВМС"]
    doctor: "LB"
    duration: 30
    priority: "standard"
    referral_required: true
    cycle_days: [3, 7]
    routing_question: null
    lab:
      condition: "age_under_30"
      test: "chlamydia"
      description: "Negative chlamydia test required for patients under 30"
    questionnaire: null
    guidance: null
```

### Supporting sections

```yaml
cycle_rules:
  # procedure name → [start_cd, end_cd] or special value
  IUD insertion: [3, 7]
  Hysteroscopy: [4, 8]
  Endometriosis: "just_before_next_period"
  # ...

questionnaires:
  "You & Your Gynaecological Problem":
    applies_to: [27, 28, 45, 29, 39, 34, 35, 33, 48, 49, 50, 31, 32]
  # ...

guidance_documents:
  "Kegleoperation": [8]
  "Tissue samples from cervix": [37, 9]
  # ...

self_pay_prices:
  - condition_id: 24
    name: "Contraception counselling"
    price_dkk: null  # clinic to provide
  # ...
```

---

## Tool Functions

| Agent | Tool | Purpose |
|---|---|---|
| Classification | `lookup_conditions(description)` | Search YAML keywords + groups, return matches |
| Routing | `get_condition_details(condition_id)` | Return doctor, duration, priority, routing rules |
| Scheduling | `calculate_cycle_window(last_period, condition_id, cycle_length, cycle_range, no_cycle)` | Return valid booking dates or Provera recommendation |
| Scheduling | `get_lab_requirements(condition_id, patient_age)` | Return required tests + instructions |
| Booking | `get_questionnaire(condition_id)` | Return questionnaire name(s) |
| Booking | `get_guidance_document(condition_id)` | Return guidance doc name |
| Booking | `get_available_slots(doctor, duration, date_range)` | Return mock appointment slots |
| Booking | `get_self_pay_price(condition_id)` | Return price in DKK |

---

## Agent Prompting Principles

All agents follow these rules:

1. **Guide, don't interrogate.** Never present numbered lists. Use natural follow-up questions that steer the patient toward the right answer.
2. **One question at a time.** Never ask multiple questions in one message.
3. **Use the patient's own words.** Reflect back what they said to confirm understanding.
4. **Language matching.** Respond in the patient's language throughout (DA/EN/UK).
5. **Empathetic tone.** This is a medical context. Be warm, reassuring, professional.
6. **Gentle examples.** When the patient is vague, offer examples to help them identify their situation.
7. **"Speak to staff" escape hatch.** If the patient says this at any point, produce a HandoffRequest immediately.

---

## Client Feedback Incorporated

| Rule | Implementation |
|---|---|
| Patient can request specific doctor | Intake Agent asks preference; overrides standard routing |
| Patient can request earliest available | `doctor_preference: "earliest"` bypasses routing rules |
| Self-pay without referral is allowed | Intake Agent offers self-pay path; price shown from YAML |
| Abortion = emergency, no referral | Category A, priority "1_2_days", `referral_required: false` |
| Irregular cycles | Scheduling Agent collects cycle range or flags no-cycle; may suggest Provera |
| Danish + English + Ukrainian | Intake Agent detects language; YAML keywords in all 3 languages |
| 24/7 availability | Booking Agent flags `booked_outside_hours` for off-hours conversations |

---

## File Structure

```
new_triage/
├── conversational_extraction.ipynb   (existing — general approaches)
├── kvinde_klinikken_triage.ipynb     (new — clinic-specific PoC)
├── conditions.yaml                   (condition config)
├── Triage_Conversation_Chain.md      (source document)
└── docs/plans/
    └── 2026-02-26-kvinde-klinikken-triage-design.md  (this file)
```

## Notebook Structure

| Cell | Type | Content |
|---|---|---|
| 1 | markdown | Title + overview |
| 2 | code | pip install + imports |
| 3 | code | Pydantic models |
| 4 | code | Load conditions.yaml |
| 5-10 | code | Tool functions (one per cell) |
| 11-15 | code | Agent definitions (one per cell) |
| 16-17 | code | Test: Category C single-shot |
| 18-19 | code | Test: Category A urgent handoff |
| 20-21 | code | Test: DSS insurance handoff |
| 22-23 | code | Test: Self-pay no referral |
| 24-25 | code | Test: Irregular cycle |
| 26-27 | code | Test: Multi-turn interactive |

---

## Open Items (for later phases)

- Real Novax booking system integration (replace mock slots)
- WhatsApp channel integration
- Real price list from clinic
- Clinic's step-by-step general booking process (pending from client)
- Ukrainian keyword translations
- Consent flow alignment with existing questionnaire
