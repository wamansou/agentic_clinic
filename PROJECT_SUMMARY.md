# Kvinde Klinikken AI Triage System — Project Summary

**Date:** February 27, 2026
**Author:** Walid Mansour + Claude (Anthropic)

---

## 1. What This Is

An AI-powered triage system for **Kvinde Klinikken**, a Danish gynecology clinic. Patients chat with the system (via WhatsApp or web), and it guides them through a natural conversation to collect the information the clinic needs to schedule their appointment. The system classifies the patient's condition (out of 53 gynecological conditions), determines the correct doctor, handles scheduling constraints (menstrual cycle windows, lab prerequisites), and produces a structured output for the clinic staff to act on.

The system does **not** book appointments directly. It stages patients with all required information so the clinic can call them to confirm.

---

## 2. Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.14 |
| AI framework | OpenAI Agents SDK (`openai-agents` 0.10.2) |
| LLM | GPT-5.2 (configurable via `TRIAGE_MODEL` env var) |
| Data models | Pydantic v2 (structured outputs) |
| Knowledge base | YAML (`conditions.yaml`) |
| Session persistence | SQLite (via SDK's `SQLiteSession`) |
| Environment | `python-dotenv` for API keys |

---

## 3. Architecture Evolution

### v1: Hub-and-Spoke (7 LLM Agents)

The original design used an LLM-based Dispatch agent as a central router with 5 specialist agents:

```
Patient → Dispatch (LLM router)
            ├→ Intake Agent         (insurance, referral, name, phone)
            ├→ Classification Agent  (identify condition)
            ├→ Routing Agent         (determine doctor)
            ├→ Scheduling Agent      (cycle windows, labs)
            ├→ Booking Agent         (questionnaires, guidance, slot booking → BookingRequest)
            └→ Staff Handoff Agent   (→ HandoffRequest)
```

**Problems discovered through war games (WG1-WG7):**

| Bug | Severity | Description |
|-----|----------|-------------|
| #1 | CRITICAL | Dispatch produced text ("someone will contact you") instead of silently routing — ~60% of the time |
| #2 | HIGH | Escape hatch too aggressive — "speak to someone" anywhere in history triggered permanent escalation |
| #3 | MEDIUM | "hi" defaulted to Danish instead of English |
| #4 | MEDIUM | Booking agent skipped slot presentation, produced BookingRequest immediately |
| #5 | LOW | Dates in DD-MM-YYYY instead of ISO YYYY-MM-DD |
| #6 | CRITICAL | "offentlig sygesikring" (public insurance) misclassified as DSS → false escalation |
| #7 | HIGH | Endometriosis cycle dependency missed entirely |
| #8 | MEDIUM | Questionnaires missed (Python enrichment not done by LLM) |
| #9 | LOW | `no_cycle=true` set without patient ever mentioning amenorrhea |

**Root cause:** LLM agents don't reliably follow complex behavioral instructions. The Dispatch agent, in particular, could not be made to stay silent — it was fundamentally a "conversation ender" rather than a router. These issues required **structural enforcement** (code), not prompt engineering.

### v2: Single Agent + Python Orchestrator (3 LLM Agents)

Complete architectural rewrite that eliminated the Dispatch agent and replaced most LLM work with deterministic Python:

```
Patient Message
     │
     ▼
┌─────────────────────────────────────┐
│  Python Orchestrator (main loop)    │
│                                     │
│  while True:                        │
│    result = Runner.run(             │
│      triage_agent, user_input,      │
│      session=session                │
│    )                                │
│    if complete_triage was called:   │
│      break                          │
│    else:                            │
│      show text → get next input     │
│                                     │
│  ┌─ Escalation? ─────────────────┐  │
│  │  if escalate or DSS or Cat A: │  │
│  │    → Staff Handoff Agent      │  │
│  │    → return HandoffRequest    │  │
│  └───────────────────────────────┘  │
│                                     │
│  ┌─ Deterministic Enrichment ────┐  │
│  │  calculate_cycle_window()     │  │
│  │  get_lab_requirements()       │  │
│  │  get_questionnaire()          │  │
│  │  get_guidance_document()      │  │
│  │  get_self_pay_price()         │  │
│  └───────────────────────────────┘  │
│                                     │
│  → Confirmation Agent               │
│    (warm patient-facing message)    │
│                                     │
│  → return BookingRequest            │
└─────────────────────────────────────┘
```

**What changed:**

| Component | v1 | v2 |
|-----------|----|----|
| Router | LLM Dispatch agent | **Eliminated** — Python controls flow |
| Conversation | 5 specialist agents | **1 Triage agent** handles full conversation |
| Enrichment | LLM agents (Scheduling, Booking) | **Deterministic Python** (`_enrich_booking()`) |
| Slot booking | LLM with `find_available_slots` | **Removed** — clinic calls patient |
| Confirmation | None | **Confirmation Agent** — warm natural message |
| Agent count | 7 LLM agents | **3 LLM agents** (Triage, Staff Handoff, Confirmation) |
| Average turns | 9-15 (often failing) | **~5 turns** (96.4% success rate) |

---

## 4. System Design (v2 — Final)

### 4.1 Data Models

Three Pydantic models cleanly separate LLM-collected data from Python-computed data:

**`TriageData`** — Collected by the Triage agent from the patient:
- `language`, `escalate`, `escalation_reason`
- `patient_name`, `phone_number`, `insurance_type`, `has_referral`, `is_followup`
- `condition_id`, `condition_name`, `category`, `doctor`, `duration_minutes`, `priority_window`
- `patient_age`, `last_period_date`, `cycle_length`, `no_periods`

**`BookingRequest`** — Final output for the clinic (TriageData + Python enrichment):
- `triage` (nested TriageData)
- `cycle_dependent`, `valid_booking_window`, `provera_recommended`
- `lab_required`, `lab_details`
- `questionnaire`, `partner_questionnaire`
- `guidance_document`
- `self_pay`, `self_pay_price_dkk`
- `notes` (includes confirmation message)

**`HandoffRequest`** — For staff escalation:
- `triage` (nested TriageData)
- `reason`, `urgency` ("immediate" / "high" / "normal")
- `conversation_summary`, `suggested_action`

### 4.2 Knowledge Base (`conditions.yaml`)

Single source of truth with 5 sections:

1. **Condition Groups** (9 groups) — For ambiguous keywords that map to multiple conditions:
   - IUD (5 options), Prolapse (3), Polyp (2), Lichen sclerosus (3), Incontinence (2), PCOS (2), Menopause (2), Contraception (3), Cysts (2)
   - Each group has a `clarifying_question` and `options` with `condition_id` mappings

2. **Conditions** (53 conditions across 3 categories):
   - **Category A (ids 1-5):** Acute/urgent — always escalate to staff
     - Heavy bleeding, sudden severe pain, ectopic pregnancy, 1st trimester bleeding, medical abortion
   - **Category B (ids 6-9):** Semi-urgent — book within 1-2 weeks
     - Cancer package, postmenopausal bleeding, cone biopsy, contact bleeding
   - **Category C (ids 10-53):** Standard — the bulk of bookings
     - Fertility (10-13), pregnancy (14), bleeding (15), pain (16-17), endometriosis (18), IUD (19-23), contraception (24-26), cysts (27-28), menopause (29-30), incontinence (31-33), prolapse (34-36), cervical (37-38), PCOS (39-40), procedures (41-44), skin (45-47), vulva/vagina (48-50), other (51-53)

3. **Cycle Rules** — 9 cycle-dependent procedures with specific cycle day windows:
   - IUD insertion: CD 3-7
   - Follicle scanning: CD 2-4
   - Hysteroscopy: CD 4-8
   - Polyp removal (cervical): CD 5-7
   - Polyp removal (uterine): CD 4-8
   - HSU tube exam: CD 6-10
   - Implant insertion: CD 1-5
   - Endometriosis: "just before next period"
   - PCOS blood panel: CD 3

4. **Questionnaires** (7):
   - "You & Your Gynaecological Problem" (13 conditions)
   - "Premenopausal Bleeding" (2 conditions)
   - "Pelvic Pain" (3 conditions)
   - "Cell Changes" (1 condition)
   - "Urinary Problems / Incontinence" (2 conditions)
   - "Infertility Questionnaire (UXOR)" (patient)
   - "Infertility Questionnaire (VIR)" (partner)

5. **Guidance Documents** (3) and **Self-Pay Prices** (4 conditions with set prices)

### 4.3 Tool Functions

8 deterministic Python functions that query `conditions.yaml`:

| Function | Purpose | Used By |
|----------|---------|---------|
| `lookup_conditions()` | Keyword search across conditions + groups | Triage agent (via `search_conditions` tool) |
| `get_condition_details()` | Full condition details by ID | Triage agent (via `fetch_condition_details` tool) |
| `calculate_cycle_window()` | Compute valid booking dates from cycle data | Python orchestrator |
| `get_lab_requirements()` | Check age-dependent lab prerequisites | Python orchestrator |
| `get_questionnaire()` | Get pre-visit questionnaire(s) | Python orchestrator |
| `get_guidance_document()` | Get patient guidance documents | Python orchestrator |
| `get_self_pay_price()` | Self-pay pricing lookup | Python orchestrator |

Only 2 of these are exposed to the LLM as `@function_tool` wrappers (`search_conditions`, `fetch_condition_details`). Plus 1 structural tool: `complete_triage(data: TriageData)` — the agent calls this to signal it has collected all required information.

### 4.4 Agents

**Triage Agent** — Single agent handling the entire patient conversation:
- Tools: `search_conditions`, `fetch_condition_details`, `complete_triage`
- Custom `tool_use_behavior` for programmatic validation (see Section 6)
- Temperature: 0.0 (via `ModelSettings`)
- Prompt covers: language detection, insurance classification, urgent detection, conversation flow (7 steps), mandatory tool usage, escape hatch, tone rules

**Staff Handoff Agent** — Produces structured `HandoffRequest` for clinic staff:
- Output type: `HandoffRequest` (Pydantic structured output)
- Receives TriageData + escalation reason
- Summarizes conversation for staff who haven't read the chat

**Confirmation Agent** — Generates warm patient-facing confirmation:
- No structured output — produces natural text
- Receives enriched BookingRequest context
- Writes in the patient's language (Danish/English/Ukrainian)
- Mentions doctor, questionnaires, labs, cycle timing, phone callback

### 4.5 Conversation Flow

The Triage agent collects information in this order (one question at a time):

1. **Urgent detection** — Check for Category A emergencies first (active heavy bleeding, sudden severe pain, ectopic pregnancy, pregnancy with bleeding, abortion)
2. **Insurance type** — "Do you have public health insurance?" → if DSS → escalate immediately
3. **Referral status** — "Do you have a referral from your GP?" → if no → offer self-pay path
4. **Patient name** and **phone number**
5. **Condition** — "What brings you in today?" → call `search_conditions()` → if group match → ask clarifying question → call `fetch_condition_details()`
6. **Routing follow-ups** — Only if condition has a `routing_question` (age for bleeding, string visibility for IUD, previous doctor for menopause, fertility for second opinion)
7. **Cycle info** — Only if condition has `cycle_days` (last period date, cycle length, amenorrhea)

Then calls `complete_triage()` with all collected data.

### 4.6 Doctor Routing

Two doctors: **Dr. HS (Skensved)** and **Dr. LB (Bech)**. Routing rules:

| Rule | Condition(s) | Doctor |
|------|-------------|--------|
| Default per condition | All | Specified in `conditions.yaml` |
| Age > 45 | Premenopausal bleeding (15) | HS |
| Age ≤ 45 | Premenopausal bleeding (15) | LB |
| Strings not visible | IUD removal (20), IUD replacement (21) | HS |
| Strings visible | IUD removal (20), IUD replacement (21) | LB |
| Previously seen Dr. Skensved | Menopause new (29) | HS |
| Not seen Dr. Skensved | Menopause new (29) | LB |
| Same doctor as last visit | Menopause follow-up (30) | HS or LB |
| Fertility-related | Second opinion (52) | LB |
| Not fertility-related | Second opinion (52) | HS |

---

## 5. Key Design Decisions

### 5.1 No Slot Booking

The system stages patients with all required information but does **not** book slots. The clinic calls the patient to confirm the appointment. This eliminates:
- Complex slot availability logic
- Race conditions with concurrent bookings
- The need for a Novax integration at this stage
- An entire LLM agent (Booking) that was unreliable

### 5.2 Deterministic Enrichment

All post-conversation data computation happens in Python, not LLM:
- Cycle window calculation (date math with `datetime`)
- Lab requirements (age-dependent lookups)
- Questionnaire assignment (condition ID mapping)
- Guidance document assignment (condition ID mapping)
- Self-pay pricing (condition ID lookup)

This guarantees correctness. In v1, the LLM agents frequently missed cycle dependencies, skipped questionnaires, or produced wrong dates.

### 5.3 Doctor Preference Not Asked

The system does **not** ask for doctor preference during intake. It only asks routing questions when the condition's rules require it (e.g., "Which doctor did you see last time?" for menopause follow-up). This avoids confusion and unnecessary turns.

### 5.4 LLM-Generated Confirmation

Rather than a template, the Confirmation Agent produces a warm, natural message in the patient's language. This creates a more human experience at the end of an AI-driven conversation.

---

## 6. Programmatic Tool-Use Validation

A key innovation that improved reliability from ~89% to ~96.4%.

### Problem

The Triage agent sometimes skipped calling `search_conditions()` and `fetch_condition_details()`, jumping straight to `complete_triage()` with `condition_id=null` and `doctor=null`. Prompt instructions alone ("you MUST call these tools") weren't sufficient.

### Solution

Custom `tool_use_behavior` using the OpenAI Agents SDK's `ToolsToFinalOutputResult`:

```python
@function_tool
def complete_triage(data: TriageData) -> str:
    if not data.escalate:
        if data.condition_id is None:
            return "ERROR: condition_id is required..."
        if data.doctor is None:
            return "ERROR: doctor is required..."
    return data.model_dump_json()

def _validate_complete_triage(context, tool_results):
    for result in tool_results:
        if result.tool.name == "complete_triage":
            if result.output.startswith("ERROR:"):
                return ToolsToFinalOutputResult(is_final_output=False)
            return ToolsToFinalOutputResult(
                is_final_output=True, final_output=result.output
            )
    return ToolsToFinalOutputResult(is_final_output=False)
```

**How it works:**
1. Agent calls `complete_triage` with collected data
2. Tool validates: if `condition_id` or `doctor` is null → returns ERROR string
3. Custom `tool_use_behavior` detects ERROR → returns `is_final_output=False`
4. SDK sends error back to the LLM → agent reads the error message
5. Agent calls `search_conditions()` and `fetch_condition_details()` to get the missing data
6. Agent retries `complete_triage` with valid data → validation passes → `is_final_output=True`

This is superior to `ModelSettings(tool_choice="required")` because it only validates at the output gate, allowing the agent to freely converse during intake without forced tool calls on every turn.

---

## 7. War Games — Testing Methodology

All testing was done through "war games" — scripted multi-turn conversations where each turn is sent via `python run_turn.py <session> "<message>"`. Session state persists in SQLite across turns.

### 7.1 Coverage Summary

| Round | War Games | Model | Focus |
|-------|-----------|-------|-------|
| 1 (v1) | WG1-WG7 | gpt-5-mini | Architecture validation → revealed fundamental Dispatch problem |
| 2 (v2) | WG8-WG12 | gpt-5-mini | v2 architecture validation → all v1 issues resolved |
| 3 | WG13-WG23 | gpt-5-mini then gpt-5.2 | Natural patient behavior, edge cases |
| 4 | WG24-WG31 | gpt-5.2 | Group disambiguations, cycle windows, routing |
| 5 | WG32-WG41 | gpt-5.2 | Triage Conversation Chain coverage, relative dates |
| 6 | WG42-WG51 | gpt-5.2 | Extended coverage, all remaining conditions |
| 7 | WG52-WG63 | gpt-5.2 | Full coverage — every condition tested |
| Regression | All 56 WGs | gpt-5.2 | Full regression after validation fix |

### 7.2 Final Results

**56 war games total. 54 PASS, 2 FAIL (96.4% pass rate).**

All 53 conditions from the Triage Conversation Chain have been tested and verified at least once.

### 7.3 Scenarios Tested

- **Category A emergencies:** Heavy bleeding, sudden severe pain, ectopic pregnancy, 1st trimester bleeding, medical abortion (all 5 conditions)
- **Category B urgent:** Cancer package, postmenopausal bleeding, cone biopsy, contact bleeding (all 4 conditions)
- **Category C standard:** All 44 conditions including fertility, IUD (5 variants), contraception, cysts, menopause, incontinence, prolapse, cervical, PCOS, procedures, skin conditions, vulva/vagina, and other
- **Insurance paths:** Public, DSS (immediate escalation), "yellow card" (= public), "not sure" → public
- **Referral paths:** With referral, without referral (→ self-pay), follow-up without referral
- **Languages:** English, Danish, language detection on ambiguous messages
- **Group disambiguations:** All 9 condition groups tested (IUD, Prolapse, Polyp, Lichen, Incontinence, PCOS, Menopause, Contraception, Cysts)
- **Routing questions:** Age-based (bleeding), string visibility (IUD), previous doctor (menopause), fertility (second opinion)
- **Cycle-dependent procedures:** 9 different cycle rules tested with correct window computation
- **Relative dates:** "about 10 days ago", "last week Monday", "around February 15th"
- **Edge cases:** Confused/unclassifiable patient → graceful handoff, mid-conversation escape hatch, condition mentioned before intake, out-of-order information

### 7.4 The 2 Remaining Failures

| WG | Expected | Actual | Severity |
|----|----------|--------|----------|
| WG19 | Prolapse ring change (id 36) | Prolapse ring new (id 35) | LOW — same doctor, same duration |
| WG39 | Birth tear (id 48) | Pelvic pain (id 16) | MEDIUM — different condition but overlapping symptoms |

**Decision: Not fixed.** Both are genuine ambiguity cases where the patient's description could reasonably map to either condition. Overfitting the system to these specific phrasings would risk degrading performance on the 54 passing cases. The clinic staff reviews every staged booking before calling the patient, providing a safety net for edge-case misclassifications.

---

## 8. Bugs Found and Fixed

### v1 Bugs (Architectural — fixed by v2 rewrite)

| # | Bug | Severity | Root Cause | Fix |
|---|-----|----------|------------|-----|
| 1 | Dispatch produces text instead of routing | CRITICAL | LLM can't reliably be a silent router | Eliminated Dispatch — Python orchestrator |
| 2 | Escape hatch too aggressive | HIGH | Checked full history, not just current message | Scoped to current message only in prompt |
| 3 | "hi" defaults to Danish | MEDIUM | Model assumed Danish from clinic context | Prompt: "SHORT/AMBIGUOUS → DEFAULT TO ENGLISH" |
| 4 | Booking skips slot presentation | MEDIUM | LLM skipped two-step flow | Eliminated slot booking — clinic calls patient |
| 5 | Date format DD-MM-YYYY | LOW | Model didn't follow ISO format instruction | Prompt: "All dates MUST use ISO 8601: YYYY-MM-DD" |
| 6 | "offentlig sygesikring" misclassified as DSS | CRITICAL | "sygesikring" confused the model | Explicit classification rules in prompt |
| 7 | Cycle dependency missed (endometriosis) | HIGH | LLM agent didn't check cycle_days field | Deterministic Python enrichment |
| 8 | Questionnaire missed | MEDIUM | LLM agent didn't look up questionnaires | Deterministic Python enrichment |
| 9 | `no_cycle=true` false positive | LOW | Agent hallucinated amenorrhea | Single agent with clearer data flow |

### v2 Bugs (found and fixed during war games)

| # | Bug | Severity | WG | Fix |
|---|-----|----------|----|-----|
| 10 | "Heavy" keyword → Cat A for chronic bleeding | HIGH | WG14 | Model upgrade (gpt-5.2 asks clarifying Q) |
| 11 | Doctor code vs name ("Dr. Bech" instead of "LB") | LOW | WG13 | Fixed by gpt-5.2 |
| 12 | Agent guesses prices it doesn't know | LOW | WG16 | Fixed by gpt-5.2 |
| 13 | Postmenopausal bleeding over-escalated as Cat A | HIGH | WG27 | Refined urgent detection: only ACTIVE, HAPPENING-NOW emergencies |
| 14 | "hej" language detection inconsistent | LOW | WG24 | Accepted — resolves after patient writes more Danish |
| 15 | Contact bleeding misclassified as premenopausal | CRITICAL | WG33 | Added lay-language keywords to condition 9, prompt to prefer specific matches |
| 16 | "henvist" triggers false DSS escalation | CRITICAL | WG34 | Prompt: "henvist/henvisning = referred, NOT insurance" |
| 17 | Recurrent UTI misclassified as itching/burning | HIGH | WG47 | Added "UTI", "urinary tract infection" keywords to condition 33 |
| 18 | Cat A escalation missing condition_id/category | MEDIUM | WG53 | Prompt: "fill in condition_id, condition_name, category from search_conditions" |

---

## 9. Performance Metrics

### Turn Count

| Architecture | Average Turns | Range |
|-------------|---------------|-------|
| v1 (7 agents) | 9-15 | Often FAILED before completing |
| v2 (1 agent) | **~5.1** | 1-9 turns |

**Turn distribution (v2):**
- 1-2 turns: DSS escalation, Category A emergencies
- 3-4 turns: Out-of-order info (patient gives condition + all intake at once)
- 5-6 turns: Standard flow (insurance → referral → name → phone → condition)
- 7-9 turns: Complex cases (group disambiguation + routing question + cycle info)

### LLM Calls

| Architecture | LLM Calls Per Conversation |
|-------------|---------------------------|
| v1 | 10-30+ (Dispatch on every turn + specialist agents) |
| v2 | **~5-7** (1 per patient turn + 1 for handoff or confirmation) |

### Accuracy

| Metric | v1 | v2 |
|--------|----|----|
| Condition classification | ~70% | **96.4%** |
| Doctor routing | ~80% | **100%** (on passing cases) |
| Cycle window computation | ~30% | **100%** |
| Questionnaire attachment | ~40% | **100%** |
| Lab requirement detection | ~60% | **100%** |
| Guidance document attachment | ~50% | **100%** |
| Self-pay pricing | N/A | **100%** |

---

## 10. Files

| File | Purpose |
|------|---------|
| `conditions.yaml` | Knowledge base — 53 conditions, 9 groups, cycle rules, questionnaires, guidance docs, prices |
| `war_games/triage_app.py` | Main codebase — Pydantic models, YAML loading, 8 tool functions, 3 agent definitions, Python orchestrator |
| `war_games/run_turn.py` | Single-turn runner for scripted war game testing |
| `war_games/war_games.db` | SQLite database for session persistence |
| `war_games/war_game_results.md` | Complete war game documentation (2155 lines) |
| `.env` | API key + model configuration |
| `Triage_Conversation_Chain.md` | Source specification document |
| `CLAUDE.md` | Developer guidance for AI coding assistants |

---

## 11. What We Learned

### On LLM Agent Architecture

1. **LLM agents should not be routers.** The Dispatch agent was the single biggest source of failure in v1. Python if/else is infinitely more reliable for flow control.

2. **Fewer agents = fewer failure points.** Going from 7 agents to 1 conversation agent eliminated context loss between handoffs, reduced latency, and made the conversation more natural.

3. **Deterministic computation should never be delegated to an LLM.** Date math, lookup tables, and keyword matching are trivially correct in Python. LLMs get them wrong 30-60% of the time.

4. **Programmatic validation > prompt instructions.** The custom `tool_use_behavior` that rejects incomplete `complete_triage` calls was more effective than any amount of "you MUST call these tools" in the prompt.

5. **Custom `tool_use_behavior` is the right pattern for output gates.** It only validates when the agent tries to finish, allowing free-form conversation during the intake phase.

### On Testing

6. **War games are essential.** Every round of testing revealed bugs that were invisible in the design phase. The progression from WG1 (9 turns, FAIL) to WG22 (2 turns, PASS) tells the whole story.

7. **Don't overfit to test cases.** The decision to accept 96.4% and stop was correct. The remaining 2 failures are genuine ambiguity, not system bugs. Adding more keywords and hints would create fragile special cases.

8. **Keyword matching has limits.** Natural language has many ways to say the same thing. "Skade efter fødsel" vs "smerter under samleje" both describe aspects of the same condition but match different keywords. This is a fundamental limitation of substring matching — not a bug to fix.

### On Model Selection

9. **GPT-5.2 > GPT-5-mini for this task.** Three bugs (#10, #11, #12) fixed themselves when upgrading. Better disambiguation, correct doctor codes, no price hallucination. The marginal cost increase is worth the reliability.

---

## 12. What's Next (Not Yet Built)

- **Novax integration** — Connect to the clinic's scheduling system for real slot booking
- **WhatsApp/web frontend** — Currently CLI-only
- **Ukrainian language testing** — Supported in prompt but no war games in Ukrainian
- **Production monitoring** — Track condition classification accuracy over real conversations
- **Feedback loop** — Staff corrections feed back to improve keyword matching
- **Multi-clinic support** — Different conditions.yaml per clinic
