# Kvinde Klinikken AI Triage — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Jupyter notebook PoC that triages gynecology patients through a 5-agent pipeline, classifying 53 conditions and producing structured BookingRequest/HandoffRequest Pydantic outputs.

**Architecture:** Pipeline of 5 OpenAI Agents SDK agents (Intake → Classification → Routing → Scheduling → Booking) with handoffs. Condition data lives in a YAML config. Tool functions handle lookups and cycle date math. All agents use guided conversational prompts (no lists, one question at a time).

**Tech Stack:** OpenAI Agents SDK (`openai-agents`), Pydantic v2, PyYAML, Python 3.11+, Jupyter

---

## Task 1: Create `conditions.yaml` — Full Condition Config

**Files:**
- Create: `conditions.yaml`

**Reference:** `Triage_Conversation_Chain.md` (all 53 conditions, cycle rules, lab rules, questionnaires, guidance docs)

**Step 1: Write the complete YAML file**

Include all 5 sections:
- `condition_groups` — 9 groups (IUD, Prolapse, Polyps, Lichen, Incontinence, PCOS, Menopause, Contraception, Cysts)
- `conditions` — all 53 conditions with fields: id, name, category (A/B/C), keywords (DA + EN), doctor, duration, priority, referral_required, cycle_days, routing_question, lab, questionnaire, guidance
- `cycle_rules` — 9 entries from Step 6 table
- `questionnaires` — 7 questionnaires with applies_to condition IDs
- `guidance_documents` — 3 documents with applies_to condition IDs
- `self_pay_prices` — placeholder entries (prices TBD from clinic)

For keywords, include Danish and English terms. Ukrainian can be added later.

Each condition entry follows this schema:
```yaml
- id: 19
  name: "IUD insertion"
  category: "C"
  keywords: ["spiral insertion", "IUD insertion", "spiral indsættelse", "get an IUD"]
  doctor: "LB"
  duration: 30
  priority: "standard"
  referral_required: true
  cycle_days: [3, 7]          # null if not cycle-dependent
  routing_question: null       # or object with trigger, question, rules
  lab:                         # null if no lab required
    condition: "age_under_30"
    test: "chlamydia"
    description: "Negative chlamydia test required for patients under 30"
  questionnaire: null
  guidance: null
```

Category A conditions (ids 1-5) have `doctor: null`, `duration: null`, `priority: "same_day"`.
Category B conditions (ids 6-9) have specific doctors and `priority: "1_week"` or `"14_days"`.

**Step 2: Validate the YAML loads correctly**

```python
import yaml
with open("conditions.yaml") as f:
    config = yaml.safe_load(f)
print(f"Groups: {len(config['condition_groups'])}")
print(f"Conditions: {len(config['conditions'])}")
print(f"Cycle rules: {len(config['cycle_rules'])}")
```

Expected: Groups: 9, Conditions: 53, Cycle rules: 9

---

## Task 2: Create Notebook — Setup + Pydantic Models

**Files:**
- Create: `kvinde_klinikken_triage.ipynb`

**Step 1: Create notebook with title cell**

```markdown
# Kvinde Klinikken — AI Triage PoC
Multi-agent triage pipeline using OpenAI Agents SDK.
Classifies 53 gynecological conditions and produces structured booking requests.
```

**Step 2: Add setup cell**

```python
!pip install openai-agents pyyaml pydantic python-dotenv
```

**Step 3: Add imports cell**

```python
import os
import yaml
import json
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
```

**Step 4: Add Pydantic models cell**

Define all 4 models exactly as specified in the design doc:
- `PatientContext` — language, gdpr_consent, insurance_type, has_referral, is_followup, patient_name, patient_age, email, doctor_preference
- `ConditionMatch` — condition_id, condition_name, category, doctor, duration_minutes, priority_window
- `BookingRequest` — patient, condition, cycle fields, lab fields, document fields, booking fields
- `HandoffRequest` — patient, reason, urgency, conversation_summary, suggested_action

**Step 5: Run cell to verify models compile**

```python
# Quick validation
p = PatientContext(language="da", gdpr_consent=True, insurance_type="public", has_referral=True, is_followup=False)
print(p.model_dump_json(indent=2))
```

---

## Task 3: YAML Loader + Lookup Helpers

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add YAML loader cell**

```python
with open("conditions.yaml") as f:
    CONFIG = yaml.safe_load(f)

CONDITIONS = {c["id"]: c for c in CONFIG["conditions"]}
GROUPS = CONFIG["condition_groups"]
CYCLE_RULES = CONFIG["cycle_rules"]
QUESTIONNAIRES = CONFIG["questionnaires"]
GUIDANCE_DOCS = CONFIG["guidance_documents"]
SELF_PAY_PRICES = {p["condition_id"]: p for p in CONFIG.get("self_pay_prices", [])}

print(f"Loaded {len(CONDITIONS)} conditions, {len(GROUPS)} groups")
```

**Step 2: Run cell and verify output**

Expected: `Loaded 53 conditions, 9 groups`

---

## Task 4: Tool Function — `lookup_conditions()`

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Implement lookup_conditions**

This is the Classification Agent's main tool. Given a patient description string, it:
1. Searches condition keywords for matches
2. Searches group keywords for matches
3. Returns a list of matching conditions and/or groups

```python
def lookup_conditions(description: str) -> str:
    """Search conditions and groups by patient description. Returns JSON with matches."""
    description_lower = description.lower()
    matches = []
    group_matches = []

    # Search individual conditions
    for cond in CONFIG["conditions"]:
        for keyword in cond["keywords"]:
            if keyword.lower() in description_lower:
                matches.append({
                    "type": "condition",
                    "id": cond["id"],
                    "name": cond["name"],
                    "category": cond["category"],
                    "doctor": cond["doctor"],
                    "duration": cond["duration"],
                })
                break

    # Search groups
    for group in GROUPS:
        for keyword in group["keywords"]:
            if keyword.lower() in description_lower:
                group_matches.append({
                    "type": "group",
                    "group": group["group"],
                    "clarifying_question": group["clarifying_question"],
                    "options": group["options"],
                })
                break

    result = {"conditions": matches, "groups": group_matches}
    return json.dumps(result, indent=2)
```

**Step 2: Test it**

```python
# Should match IUD group
print(lookup_conditions("I need help with my spiral"))

# Should match Category A - acute bleeding
print(lookup_conditions("I'm having heavy bleeding"))

# Should match specific condition - smear test
print(lookup_conditions("I need a smear test"))
```

---

## Task 5: Tool Function — `get_condition_details()`

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Implement get_condition_details**

```python
def get_condition_details(condition_id: int) -> str:
    """Get full details for a condition by ID. Returns JSON."""
    cond = CONDITIONS.get(condition_id)
    if not cond:
        return json.dumps({"error": f"Condition {condition_id} not found"})
    return json.dumps(cond, indent=2, ensure_ascii=False)
```

**Step 2: Test it**

```python
# IUD insertion
print(get_condition_details(19))
# Should show doctor=LB, duration=30, cycle_days=[3,7], lab for under 30
```

---

## Task 6: Tool Function — `calculate_cycle_window()`

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Implement calculate_cycle_window**

Handles regular cycles, irregular ranges, and no-cycle cases.

```python
def calculate_cycle_window(
    last_period_date: str,
    condition_id: int,
    cycle_length: int = 28,
    cycle_range_min: int | None = None,
    cycle_range_max: int | None = None,
    no_cycle: bool = False,
) -> str:
    """Calculate valid booking window based on cycle data. Returns JSON."""
    cond = CONDITIONS.get(condition_id)
    if not cond or not cond.get("cycle_days"):
        return json.dumps({"cycle_dependent": False, "message": "No cycle constraint for this procedure."})

    if no_cycle:
        return json.dumps({
            "cycle_dependent": True,
            "no_cycle": True,
            "provera_recommended": True,
            "message": "Patient has no regular cycle. Doctor may prescribe Provera (10 days) to induce a period. Booking window can be calculated 2-4 days after completing the course."
        })

    cycle_days = cond["cycle_days"]
    # Handle special case: "just_before_next_period"
    if cycle_days == "just_before_next_period":
        lp = datetime.strptime(last_period_date, "%Y-%m-%d").date()
        next_period = lp + timedelta(days=cycle_length)
        window_start = next_period - timedelta(days=3)
        window_end = next_period - timedelta(days=1)
        return json.dumps({
            "cycle_dependent": True,
            "valid_start": window_start.isoformat(),
            "valid_end": window_end.isoformat(),
            "message": f"Best scheduled just before next period: {window_start.strftime('%b %d')} - {window_end.strftime('%b %d')}"
        })

    cd_start, cd_end = cycle_days
    lp = datetime.strptime(last_period_date, "%Y-%m-%d").date()
    today = date.today()

    # Current cycle window
    window_start = lp + timedelta(days=cd_start - 1)
    window_end = lp + timedelta(days=cd_end - 1)

    if window_end < today:
        # Window passed — calculate next cycle
        if cycle_range_min and cycle_range_max:
            next_lp_earliest = lp + timedelta(days=cycle_range_min)
            next_lp_latest = lp + timedelta(days=cycle_range_max)
            next_start = next_lp_earliest + timedelta(days=cd_start - 1)
            next_end = next_lp_latest + timedelta(days=cd_end - 1)
            msg = f"This cycle's window has passed. Next window (approximate): {next_start.strftime('%b %d')} - {next_end.strftime('%b %d')}"
        else:
            next_lp = lp + timedelta(days=cycle_length)
            next_start = next_lp + timedelta(days=cd_start - 1)
            next_end = next_lp + timedelta(days=cd_end - 1)
            msg = f"This cycle's window has passed. Next window: {next_start.strftime('%b %d')} - {next_end.strftime('%b %d')}"
        return json.dumps({
            "cycle_dependent": True,
            "window_passed": True,
            "next_valid_start": next_start.isoformat(),
            "next_valid_end": next_end.isoformat(),
            "message": msg
        })

    return json.dumps({
        "cycle_dependent": True,
        "valid_start": window_start.isoformat(),
        "valid_end": window_end.isoformat(),
        "message": f"Valid booking window: {window_start.strftime('%b %d')} - {window_end.strftime('%b %d')} (cycle days {cd_start}-{cd_end})"
    })
```

**Step 2: Test it**

```python
# IUD insertion (CD 3-7), last period today → window should be in a few days
print(calculate_cycle_window("2026-02-24", 19))

# Window already passed
print(calculate_cycle_window("2026-02-01", 19))

# No cycle
print(calculate_cycle_window("2026-02-01", 19, no_cycle=True))

# Non-cycle-dependent condition (smear test, id=38)
print(calculate_cycle_window("2026-02-01", 38))
```

---

## Task 7: Tool Function — `get_lab_requirements()`

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Implement get_lab_requirements**

```python
def get_lab_requirements(condition_id: int, patient_age: int | None = None) -> str:
    """Check if a condition requires lab work. Returns JSON."""
    cond = CONDITIONS.get(condition_id)
    if not cond or not cond.get("lab"):
        return json.dumps({"lab_required": False})

    lab = cond["lab"]
    lab_condition = lab.get("condition", "always")

    # Check age-based conditions
    if lab_condition == "age_under_30" and patient_age is not None and patient_age >= 30:
        return json.dumps({"lab_required": False, "reason": "Patient is 30 or older, lab not required."})

    if lab_condition == "age_under_45" and patient_age is not None and patient_age >= 45:
        return json.dumps({"lab_required": False, "reason": "Patient is 45 or older, lab not required."})

    return json.dumps({
        "lab_required": True,
        "test": lab.get("test") or lab.get("tests"),
        "description": lab["description"],
    }, ensure_ascii=False)
```

**Step 2: Test it**

```python
# IUD insertion, patient age 25 → chlamydia required
print(get_lab_requirements(19, 25))

# IUD insertion, patient age 35 → not required
print(get_lab_requirements(19, 35))

# Fertility initial → always required
print(get_lab_requirements(10, 30))

# Smear test → no lab
print(get_lab_requirements(38, 40))
```

---

## Task 8: Tool Functions — Questionnaire, Guidance, Slots, Price

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Implement remaining tool functions**

```python
def get_questionnaire(condition_id: int) -> str:
    """Get questionnaire(s) for a condition. Returns JSON."""
    result = {"questionnaires": []}
    for name, info in QUESTIONNAIRES.items():
        if condition_id in info["applies_to"]:
            entry = {"name": name}
            if info.get("target"):
                entry["target"] = info["target"]
            result["questionnaires"].append(entry)
    if not result["questionnaires"]:
        result["message"] = "No questionnaire required for this condition."
    return json.dumps(result, ensure_ascii=False)


def get_guidance_document(condition_id: int) -> str:
    """Get guidance document for a condition. Returns JSON."""
    for name, condition_ids in GUIDANCE_DOCS.items():
        if condition_id in condition_ids:
            return json.dumps({"document": name})
    return json.dumps({"document": None, "message": "No guidance document for this condition."})


def get_available_slots(doctor: str, duration_minutes: int, date_range_start: str, date_range_end: str) -> str:
    """Get available appointment slots (MOCK for PoC). Returns JSON."""
    start = datetime.strptime(date_range_start, "%Y-%m-%d").date()
    # Generate 3 fake slots within range
    slots = []
    for i in range(3):
        slot_date = start + timedelta(days=i)
        # Skip weekends
        while slot_date.weekday() >= 5:
            slot_date += timedelta(days=1)
        hour = 9 + (i * 2)  # 09:00, 11:00, 13:00
        slots.append({
            "date": slot_date.isoformat(),
            "time": f"{hour:02d}:00",
            "doctor": f"Dr. {doctor}",
            "duration_minutes": duration_minutes,
        })
    return json.dumps({"slots": slots})


def get_self_pay_price(condition_id: int) -> str:
    """Get self-pay price for a condition. Returns JSON."""
    price_entry = SELF_PAY_PRICES.get(condition_id)
    if price_entry:
        return json.dumps(price_entry, ensure_ascii=False)
    return json.dumps({"price_dkk": None, "message": "Price not yet available. Staff will confirm."})
```

**Step 2: Test each function**

```python
# Questionnaire for fertility (id 10) → UXOR + VIR
print(get_questionnaire(10))

# Guidance for cone biopsy (id 8) → Kegleoperation
print(get_guidance_document(8))

# Mock slots
print(get_available_slots("LB", 30, "2026-03-02", "2026-03-06"))

# Self-pay price (placeholder)
print(get_self_pay_price(24))
```

---

## Task 9: Agent Definition — Intake Agent (Steps 0-3)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Import Agents SDK**

```python
from agents import Agent, Runner, handoff, RunContextWrapper, SQLiteSession
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
```

**Step 2: Define Intake Agent**

The Intake Agent has NO tools — it's pure conversation. It collects GDPR consent, insurance type, referral status, and doctor preference. It hands off to the Classification Agent or produces a HandoffRequest for DSS/no-consent cases.

Key prompting rules:
- Detect language from first message, respond in that language throughout
- Guide naturally — one question at a time
- DSS → HandoffRequest with urgency "normal"
- No consent → end conversation politely
- No referral → offer self-pay path OR suggest getting a referral
- Ask about doctor preference naturally

Write the full system prompt in the agent instructions. Include Danish + English example phrasings for each step. The prompt should encode the entire Steps 0-3 logic.

See design doc `Agent Prompting Principles` section for tone guidelines.

---

## Task 10: Agent Definition — Classification Agent (Step 4)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Define Classification Agent**

This agent has ONE tool: `lookup_conditions()`.

Key prompting rules:
- Ask patient to describe their issue naturally
- Call `lookup_conditions()` with the patient's description
- If result has group matches → guide patient through sub-options conversationally (NOT as a numbered list)
- If result has a single condition match → confirm and hand off
- If result matches Category A → produce HandoffRequest immediately with urgency "immediate"
- If no matches → ask the patient to describe differently, or produce HandoffRequest if still unclear
- NEVER present the condition groups as a menu — weave options into natural questions

The prompt should include the Category A conditions explicitly so the agent can recognize urgency even without calling the tool (e.g., patient says "I'm bleeding heavily" — don't delay with a tool call, escalate immediately).

---

## Task 11: Agent Definition — Routing Agent (Step 5)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Define Routing Agent**

This agent has ONE tool: `get_condition_details()`.

Key prompting rules:
- Receives condition_id from Classification Agent
- Calls `get_condition_details()` to get routing rules
- If `routing_question` exists → ask the follow-up naturally (age, IUD strings, menopause history, fertility second opinion)
- If `doctor_preference` was set by patient → respect it (override default routing)
- If `doctor_preference` is "earliest" → note both doctors as acceptable
- Determine final: doctor (HS/LB), duration, priority_window
- Hand off to Scheduling Agent

---

## Task 12: Agent Definition — Scheduling Agent (Steps 6-7)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Define Scheduling Agent**

This agent has TWO tools: `calculate_cycle_window()` and `get_lab_requirements()`.

Key prompting rules:
- Check if condition is cycle-dependent (from condition details passed forward)
- If yes → ask about last period date AND cycle length/regularity
- Handle irregular cycles: ask for range, or if no periods → note Provera recommendation
- Call `calculate_cycle_window()` with collected data
- If window has passed → explain and offer next cycle's window
- Call `get_lab_requirements()` with condition_id and patient_age
- If lab required → ask if patient already has results
- Explain any restrictions (not during menstruation, morning urine, etc.)
- Hand off to Booking Agent

---

## Task 13: Agent Definition — Booking Agent (Steps 8-11)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Define Booking Agent**

This agent has FOUR tools: `get_questionnaire()`, `get_guidance_document()`, `get_available_slots()`, `get_self_pay_price()`.

This is the FINAL agent — it produces the structured `BookingRequest` output.

Set `output_type=BookingRequest` on this agent.

Key prompting rules:
- Call `get_questionnaire()` → if questionnaire exists, tell patient it will be sent
- Call `get_guidance_document()` → if doc exists, tell patient
- If self_pay → call `get_self_pay_price()` and inform patient
- Call `get_available_slots()` with doctor, duration, and date range from cycle window (or general range)
- Present 2-3 slots naturally
- After patient selects → produce BookingRequest with all collected data
- If lab pending → mark `tentative: True`
- If outside clinic hours → mark `booked_outside_hours: True`
- Include any special instructions in `notes`

---

## Task 14: Wire Up Agent Pipeline with Handoffs

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cell)

**Step 1: Connect agents via handoffs**

```python
# Wire the pipeline: Intake → Classification → Routing → Scheduling → Booking
# Each agent hands off to the next via the handoffs parameter

intake_agent = Agent(
    name="Intake",
    instructions="...",  # from Task 9
    handoffs=[classification_agent, handoff_to_staff],
)

# handoff_to_staff is a special agent that produces HandoffRequest
# Used by any agent that needs to escalate
```

The key decision here: how to pass accumulated context (PatientContext, ConditionMatch) between agents. Options:

**Use handoff input_type**: Each handoff carries structured data. The on_handoff callback stores it in a shared context dict that tools can access.

Define this wiring cell after all agent definitions. It should:
1. Create a `handoff_to_staff` agent with `output_type=HandoffRequest`
2. Set `handoffs=[]` on each agent pointing to the next in pipeline + `handoff_to_staff`
3. Ensure context flows through the session

**Step 2: Verify pipeline structure**

```python
print(f"Intake handoffs: {[h.agent_name for h in intake_agent.handoffs]}")
print(f"Classification handoffs: {[h.agent_name for h in classification_agent.handoffs]}")
# etc.
```

---

## Task 15: Test — Category C Single-Shot (IUD Insertion)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test markdown header**

```markdown
## Test 1: Category C — IUD Insertion (single-shot)
Patient provides all info in one message. Should flow through all 5 agents and produce a BookingRequest.
```

**Step 2: Add test cell**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Maria Hansen, email maria@test.dk. Jeg har en henvisning "
    "og offentlig sygesikring. Jeg skal have indsat en ny spiral. Jeg er 25 år "
    "og min sidste menstruation startede den 24. februar.",
)

print(f"Final agent: {result.last_agent.name}")
print(f"Output type: {type(result.final_output).__name__}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=19, doctor=LB, duration=30, cycle_dependent=True, lab_required=True (age 25 < 30)

---

## Task 16: Test — Category A Urgent Handoff

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg har meget kraftig blødning og stærke smerter. Jeg har offentlig "
    "sygesikring og en henvisning. Jeg hedder Anna Larsen.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: HandoffRequest with urgency="immediate", reason containing "heavy bleeding" or "acute"

---

## Task 17: Test — DSS Insurance Handoff

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hi, I have private insurance through Dansk Sundhedssikring. I need to book "
    "an appointment for a fertility consultation.",
)

print(f"Final agent: {result.last_agent.name}")
print(type(result.final_output).__name__)
```

Expected: HandoffRequest produced by Intake Agent (should not reach Classification). Reason mentions DSS/private insurance.

---

## Task 18: Test — Self-Pay No Referral

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hello, I don't have a referral but I'd like to book as a self-paying patient. "
    "I need contraception counselling. My name is Lisa Berg, lisa@email.com. "
    "I have public health insurance.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with self_pay=True, condition_id=24 (contraception counselling)

---

## Task 19: Test — Irregular Cycle

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Sofie Nielsen, sofie@test.dk. Offentlig sygesikring, har "
    "henvisning. Jeg har PCOS og har ikke haft menstruation i flere måneder. "
    "Jeg skal til ny udredning.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with no_cycle=True, provera_recommended=True, condition_id=39 (PCOS new)

---

## Task 20: Test — Multi-Turn Interactive Loop

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add interactive loop cell**

```python
async def interactive_triage():
    """Interactive triage — type messages, the pipeline guides you through."""
    session = SQLiteSession("triage_interactive", "triage_conversations.db")
    current_agent = intake_agent

    print("Kvinde Klinikken AI Triage (type 'quit' to exit)")
    print("=" * 50)

    while True:
        user_input = input("\nPatient: ")
        if user_input.lower() in ("quit", "exit"):
            print("Session ended.")
            return None

        result = await Runner.run(current_agent, user_input, session=session)
        current_agent = result.last_agent

        if not isinstance(result.final_output, str):
            # Structured output produced
            output_type = type(result.final_output).__name__
            print(f"\n[{result.last_agent.name}] produced {output_type}:")
            print(result.final_output.model_dump_json(indent=2))
            return result.final_output
        else:
            print(f"\n[{result.last_agent.name}]: {result.final_output}")

final = await interactive_triage()
```

**Step 2: Add result inspection cell**

```python
if final:
    print(f"Type: {type(final).__name__}")
    print(final.model_dump_json(indent=2))
```

---

## Task 21: Test — Doctor Preference Override

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Mette Olsen, mette@test.dk. Offentlig sygesikring, "
    "har henvisning. Jeg vil gerne have den tidligst mulige tid. "
    "Jeg skal have foretaget en hysteroskopi.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with doctor_preference="earliest" — even though hysteroscopy normally routes to HS, the booking should note that either doctor is acceptable.

---

## Task 22: Test — Premenopausal Bleeding Age Routing (Over 45 → HS)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Birgitte Madsen, birgitte@test.dk. Offentlig sygesikring "
    "og jeg har en henvisning. Jeg har uregelmæssig blødning. Jeg er 48 år.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with condition_id=15, doctor=HS (not LB, because patient is over 45), duration=30

---

## Task 23: Test — IUD Group Disambiguation (Vague "spiral" Input)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test — patient says "spiral" without specifying what**

```python
# This tests that the Classification Agent asks a clarifying question
# rather than picking a random IUD condition
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Karen Holm, karen@test.dk. Offentlig sygesikring, "
    "har henvisning. Jeg har brug for hjælp med min spiral.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    # If it's a string, the agent is still asking questions (expected for multi-turn)
    print(f"Agent response: {result.final_output}")
```

Expected: The Classification Agent should respond with a natural guiding question like "Are you looking to have a new IUD put in, or is this about one you already have?" — NOT immediately pick a condition.

---

## Task 24: Test — English Language Full Flow

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test — English-speaking patient**

```python
result = await Runner.run(
    intake_agent,
    "Hello, my name is Emily Brown, emily@mail.com. I have public health insurance "
    "and a referral from my GP. I've been having pelvic pain during intercourse. "
    "It's been going on for a few weeks. I'm 32 years old.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=16 (pelvic pain/dyspareunia), doctor=LB, duration=30, language="en". All agent responses should be in English.

---

## Task 25: Test — "Speak to Staff" Escape Hatch Mid-Conversation

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test — patient requests human mid-flow**

```python
# Simulate multi-turn where patient gives up and asks for staff
session = SQLiteSession("test_escape_hatch", "triage_conversations.db")

# Turn 1: normal start
result = await Runner.run(
    intake_agent,
    "Hej, jeg har offentlig sygesikring og en henvisning.",
    session=session,
)
print(f"Turn 1 [{result.last_agent.name}]: {result.final_output}\n")

# Turn 2: patient asks to speak to staff
result = await Runner.run(
    result.last_agent,
    "Jeg vil gerne tale med en person i stedet",  # "I'd like to speak to a person instead"
    session=session,
)
print(f"Turn 2 [{result.last_agent.name}]:")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: HandoffRequest with reason mentioning patient requested human staff.

---

## Task 26: Test — Abortion Without Referral (Emergency Booking)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hi, I need to book an abortion. I don't have a referral. "
    "My name is Anne Jensen, anne@test.dk. I have public insurance.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: HandoffRequest with urgency="immediate" (Category A), should NOT be blocked by missing referral. The handoff reason should mention abortion/emergency booking within 1-2 days.

---

## Task 27: Test — Endometriosis Cycle Timing ("Just Before Next Period")

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Camilla Poulsen, camilla@test.dk. Offentlig sygesikring, "
    "har henvisning. Jeg er henvist for endometriose. Jeg er 29 år. "
    "Min sidste menstruation startede den 15. februar og min cyklus er ca. 30 dage.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=18, doctor=HS, duration=45. The valid_booking_window should be "just before next period" — approximately March 14-16 (30-day cycle from Feb 15). questionnaire="Pelvic Pain".

---

## Task 28: Test — Fertility Initial (Partner Labs + Dual Questionnaire)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Louise Berg, louise@test.dk. Offentlig sygesikring, "
    "har henvisning. Vi har forsøgt at blive gravide i over et år og vil gerne "
    "have en fertilitetsudredning. Jeg er 33 år. Min cyklus er ret regelmæssig, "
    "ca. 28 dage, sidste menstruation den 20. februar.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=10, doctor=LB, duration=45. lab_required=True with fertility blood panel + partner tests. questionnaire="Infertility Questionnaire (UXOR)", partner_questionnaire="Infertility Questionnaire (VIR)".

---

## Task 29: Test — Menopause Follow-Up (Route to Same Doctor)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Kirsten Sørensen, kirsten@test.dk. Offentlig sygesikring, "
    "jeg er eksisterende patient. Jeg skal til kontrol for min overgangsalder-behandling. "
    "Jeg har sidst set Dr. Skensved.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=30, doctor="HS" (same doctor who started treatment = Dr. Skensved = HS), duration=15. is_followup=True.

---

## Task 30: Test — Second Opinion (Fertility vs Non-Fertility Routing)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test — fertility second opinion**

```python
result = await Runner.run(
    intake_agent,
    "Hi, I'm Sarah Thompson, sarah@test.dk. Public insurance, I have a referral. "
    "I'd like a second opinion about my fertility treatment from another clinic.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    data = result.final_output.model_dump()
    print(f"Doctor: {data.get('condition', {}).get('doctor', 'N/A')}")
    print(result.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with condition_id=52, doctor=LB (fertility second opinion → LB), duration=30.

**Step 2: Add test — non-fertility second opinion**

```python
result2 = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Lene Kristensen, lene@test.dk. Offentlig sygesikring, "
    "har henvisning. Jeg ønsker en second opinion om min endometriose-diagnose.",
)

print(f"Final agent: {result2.last_agent.name}")
if hasattr(result2.final_output, 'model_dump_json'):
    data2 = result2.final_output.model_dump()
    print(f"Doctor: {data2.get('condition', {}).get('doctor', 'N/A')}")
    print(result2.final_output.model_dump_json(indent=2))
```

Expected: BookingRequest with condition_id=52, doctor=HS (non-fertility second opinion → HS), duration=30.

---

## Task 31: Test — Category B Cancer Package (High Priority, 1 Week)

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Helle Thomsen, helle@test.dk. Offentlig sygesikring, "
    "har henvisning fra min læge som kræftpakke. Jeg er 55 år.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    data = result.final_output.model_dump()
    print(f"Priority: {data.get('condition', {}).get('priority_window', 'N/A')}")
    print(result.final_output.model_dump_json(indent=2))
else:
    print(result.final_output)
```

Expected: BookingRequest with condition_id=6, category="B", priority_window="1_week", duration=30. Should be booked within 1 week.

---

## Task 32: Test — Lichen Sclerosus Group Disambiguation

**Files:**
- Modify: `kvinde_klinikken_triage.ipynb` (add cells)

**Step 1: Add test — patient says "lichen" without specifying new/follow-up/check**

```python
result = await Runner.run(
    intake_agent,
    "Hej, jeg hedder Inge Petersen, inge@test.dk. Offentlig sygesikring, "
    "har henvisning. Jeg har lichen sclerosus.",
)

print(f"Final agent: {result.last_agent.name}")
if hasattr(result.final_output, 'model_dump_json'):
    print(result.final_output.model_dump_json(indent=2))
else:
    print(f"Agent response: {result.final_output}")
```

Expected: Classification Agent should guide the patient — "Is this a new referral, or have you been seen for this before?" Should disambiguate between id 45 (new), 46 (follow-up with symptoms), 47 (annual check).

---

## Summary

| Task | What | Depends On |
|------|------|------------|
|------|------|------------|
| 1 | `conditions.yaml` (all 53 conditions) | — |
| 2 | Notebook setup + Pydantic models | — |
| 3 | YAML loader | Tasks 1, 2 |
| 4 | `lookup_conditions()` tool | Task 3 |
| 5 | `get_condition_details()` tool | Task 3 |
| 6 | `calculate_cycle_window()` tool | Task 3 |
| 7 | `get_lab_requirements()` tool | Task 3 |
| 8 | Questionnaire, guidance, slots, price tools | Task 3 |
| 9 | Intake Agent | Task 2 |
| 10 | Classification Agent | Tasks 4, 9 |
| 11 | Routing Agent | Tasks 5, 10 |
| 12 | Scheduling Agent | Tasks 6, 7, 11 |
| 13 | Booking Agent | Tasks 8, 12 |
| 14 | Wire up pipeline with handoffs | Tasks 9-13 |
| 15 | Test: Category C single-shot | Task 14 |
| 16 | Test: Category A urgent | Task 14 |
| 17 | Test: DSS handoff | Task 14 |
| 18 | Test: Self-pay no referral | Task 14 |
| 19 | Test: Irregular cycle | Task 14 |
| 20 | Test: Interactive multi-turn | Task 14 |
| 21 | Test: Doctor preference override | Task 14 |
| 22 | Test: Premenopausal bleeding age routing (>45 → HS) | Task 14 |
| 23 | Test: IUD group disambiguation (vague "spiral") | Task 14 |
| 24 | Test: English language full flow | Task 14 |
| 25 | Test: "Speak to staff" escape hatch | Task 14 |
| 26 | Test: Abortion without referral (emergency) | Task 14 |
| 27 | Test: Endometriosis "just before next period" cycle | Task 14 |
| 28 | Test: Fertility initial (partner labs + dual questionnaire) | Task 14 |
| 29 | Test: Menopause follow-up (route to same doctor) | Task 14 |
| 30 | Test: Second opinion (fertility vs non-fertility routing) | Task 14 |
| 31 | Test: Category B cancer package (high priority) | Task 14 |
| 32 | Test: Lichen sclerosus group disambiguation | Task 14 |
