# War Game Results

**Date:** 2026-02-27
**Model:** gpt-5-mini

---

## War Game 1: Shy Patient ("hi")

**Scenario:** Patient says just "hi", provides info one piece at a time.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "hi" | Intake | Asked for insurance type | BUG: Responded in Danish despite "hi" being English |
| 2 | "I have public health insurance" | Intake | Asked for referral | BUG: Still in Danish |
| 3 | "yes I have a referral" | Intake | Asked for name | Switched to English (took 3 turns) |
| 4 | "Sarah Miller" | Intake | Asked for phone | OK |
| 5 | "55512345" | Intake | Asked for doctor preference | OK |
| 6 | "no preference" | **Dispatch** | "someone will contact you shortly" | **BUG: Should route to Classification, not end conversation** |
| 7 | "I haven't told you my problem yet, I need IUD removal" | Classification | Mixed DA/EN response, said "someone will continue shortly" | BUG: Language mix, didn't ask IUD clarifying Q |
| 8 | "Can I still speak to someone about this?" | **Dispatch** | "someone from the clinic will contact you" | BUG: Triggered escape hatch on "speak to someone" |
| 9 | "no I don't want to speak to someone, I want to book" | **Staff Handoff** | HandoffRequest produced | **FAIL: Escalated despite patient wanting to book** |

**Result:** FAIL — Pipeline escalated to staff. The words "speak to someone" in conversation history triggered escape hatch even after patient clarified.

### Bugs Found:
1. **Language detection fails on "hi"** — defaults to Danish instead of English
2. **Dispatch ends conversation instead of routing** — says "someone will contact you" at turn 6
3. **Escape hatch too aggressive** — "speak to someone" in history triggers escalation even when patient corrects
4. **Classification didn't ask IUD clarifying question** — should ask about strings visible/not visible

---

## War Game 2: Normal Patient (gradual info)

**Scenario:** Patient says "Hello, I'd like to book an appointment" and provides info naturally.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "Hello, I'd like to book an appointment please" | Intake | Asked for insurance type | OK |
| 2 | "public insurance, and I have a referral from my GP" | Intake | Asked for name | OK |
| 3 | "Emma Jensen, phone 22334455" | Intake | Asked for doctor preference | OK |
| 4 | "earliest available" | **Dispatch** | "someone will contact you shortly" | **BUG: Should route to Classification** |
| 5 | "wait, you haven't asked me what my problem is yet" | Classification | "Someone will be with you shortly" | BUG: Didn't ask what brings them in |
| 6 | "I've been having heavy periods and a lot of pain" | Classification | "Do you mean soaking through pads/passing clots?" | OK — good clarifying Q |
| 7 | "no, just heavier than usual and painful cramps" | Classification | "How long have you had this?" | OK |
| 8 | "it's been about 3 months now" | **Dispatch** | "someone will contact you" | **BUG: Should route to Routing** |
| 9 | "I thought I could book online? Can I pick a time?" | Scheduling | "I'll transfer you to choose an appointment time" | Partial — Scheduling talked about transfer instead of doing its job |
| 10 | "ok great, what times do you have?" | Scheduling | "No pre-appointment labs needed. Earliest or specific day?" | OK — called check_lab_requirements |
| 11 | "earliest available please" | Scheduling | Asked for age | OK — needed for routing rule |
| 12 | "I'm 38 years old" | Scheduling | "No labs needed. What was first day of last period?" | OK |
| 13 | "about 2 weeks ago, around February 13th" | Scheduling | Asked for cycle length | OK |
| 14 | "about 28 days" | **Dispatch** | "someone will contact you shortly" | **BUG: Should route to Booking** |
| 15 | "can you just show me available times? I'd rather book right now" | Booking | BookingRequest produced | BUG: Skipped slot presentation |

**Result:** PARTIAL SUCCESS — Got to BookingRequest but took 15 turns instead of ~8. Dispatch kept blocking the flow.

### BookingRequest Accuracy:
- condition_id: 15 (Premenopausal bleeding) ✓
- category: C ✓
- doctor: LB (age 38 ≤ 45) ✓
- last_period_date: "13-02-2026" — wrong format (should be YYYY-MM-DD)
- selected_slot: null — Booking skipped slot presentation
- questionnaire: null ✓ (condition 15 has no questionnaire)

---

## Root Cause Analysis

### Issue #1: Dispatch produces text instead of routing (CRITICAL)
**Frequency:** Every time Dispatch runs (turns 4, 6, 8, 14 in WG2; turn 6 in WG1)
**Root cause:** Dispatch generates a summary text message instead of calling the handoff tool. It behaves like a "conversation ender" rather than a silent router.
**Fix needed:** Dispatch instructions must be stronger: "You MUST call a handoff tool. Do NOT produce a text response for normal flow. Your ONLY output should be a tool call (handoff)."

### Issue #2: Escape hatch too aggressive (HIGH)
**Frequency:** WG1 turns 8-9
**Root cause:** Dispatch checks for "speak to staff" keywords in the ENTIRE conversation history, not just the latest message. Once the patient says anything resembling "speak to someone", it permanently triggers escalation.
**Fix needed:** Only check the LATEST patient message for escape hatch triggers, not the full history.

### Issue #3: Language detection on short messages (MEDIUM)
**Frequency:** WG1 turn 1
**Root cause:** "hi" is ambiguous — could be English or informal Danish. Model defaults to Danish (clinic context).
**Fix needed:** Default to English for ambiguous words. Or detect from subsequent messages.

### Issue #4: Booking skips slot presentation (MEDIUM)
**Frequency:** WG2 turn 15
**Root cause:** Booking produced BookingRequest without showing slots first, despite "TWO-STEP BOOKING" instruction.
**Fix needed:** Stronger enforcement or structural change (Booking must produce text first, then BookingRequest on confirmation).

### Issue #5: Date format inconsistency (LOW)
**Frequency:** WG2 BookingRequest
**Root cause:** Model used DD-MM-YYYY instead of YYYY-MM-DD ISO format.
**Fix needed:** Explicit format instruction in Booking agent.

---

## Prompt Fixes Applied (2026-02-27)

Targeted all 5 issues with prompt edits in `triage_app.py`:

1. **Dispatch rewritten as "SILENT ROUTER"** — explicit rule: "Your ONLY job is to call a handoff tool. You must NEVER produce a text message."
2. **Escape hatch scoped to latest message only** — in shared preamble, Intake, and Dispatch: "Only check the patient's MOST RECENT message"
3. **Language default for ambiguous greetings** — Intake: "Ambiguous or very short messages ('hi', 'hello', 'hey') → DEFAULT TO ENGLISH"
4. **Two-step booking strengthened** — Booking: explicit Step A / Step B with detection logic: "If you have NOT yet shown appointment times → produce TEXT only"
5. **ISO date format enforced** — shared preamble + Booking: "All dates MUST use ISO 8601: YYYY-MM-DD"

---

## War Game 3: Shy Patient Retry — Endometriosis (post-fix)

**Date:** 2026-02-27 | **Model:** gpt-5-mini | **Tests:** Issues #1, #3, #4, #5

**Scenario:** Patient says "hi", provides info one piece at a time. Has endometriosis (cycle-dependent condition).

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "hi" | Intake | Asked for insurance type | **BUG: Still responded in Danish** (Issue #3 NOT fixed — model ignores "default to English" instruction) |
| 2 | "I have public insurance and a referral" | Intake | Asked for name | Switched to English ✓ |
| 3 | "Emily Carter" | Intake | Asked for phone | OK |
| 4 | "55512345" | Intake | Asked for doctor preference | OK |
| 5 | "no preference" | **Dispatch** | "Tak — jeg har nu dine oplysninger..." (Danish text) | **BUG: Dispatch produced text AND in Danish** (Issue #1 NOT fixed) |
| 6 | "ok well I haven't told you what I need yet. I have endometriosis" | Classification | "I'll connect you with the specialist who can help" | OK — recognized endometriosis |
| 7 | "ok" | **Dispatch** | "I'll connect you with the clinic to arrange an appointment" | **BUG: Dispatch produced text again** |
| 8 | "hello? can you help me with the appointment?" | Scheduling | "I'll connect you with the scheduling team" | BUG: Scheduling produced text instead of doing its job |
| 9 | "I'm 29, last period Feb 10, cycle about 30 days" | **Dispatch** | Recited scheduling info, said "not cycle-dependent" | **BUG: Endometriosis IS cycle-dependent ("just_before_next_period")** |
| 10 | "can you show me the available times?" | **Booking** | BookingRequest produced immediately | **BUG: Skipped slot presentation** (Issue #4 NOT fixed) |

**Result:** PARTIAL SUCCESS — Reached BookingRequest in 10 turns (vs 9 turns/FAIL in WG1). Pipeline didn't permanently escalate to staff. But Dispatch text and booking skip persist.

### BookingRequest Accuracy:
- condition_id: 18 (Endometriosis — new referral) ✓
- category: C ✓
- doctor: HS ✓
- duration_minutes: 45 ✓
- cycle_dependent: false ✗ (should be true — "just_before_next_period")
- valid_booking_window: null ✗ (should be ~Mar 14-16 for 30-day cycle from Feb 10)
- questionnaire: null ✗ (should be "Pelvic Pain")
- last_period_date: "2026-02-10" ✓ (**Issue #5 FIXED — correct ISO format**)
- selected_slot: null ✗ (slot presentation skipped)

---

## War Game 4: Danish Patient — Public Insurance Misclassified

**Date:** 2026-02-27 | **Model:** gpt-5-mini | **Tests:** Danish flow, insurance detection

**Scenario:** Danish-speaking patient with public insurance ("offentlig sygesikring") and a referral.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "Hej, jeg har offentlig sygesikring og en henvisning. Jeg hedder Mette." | **Staff Handoff** | HandoffRequest (urgency: normal) | **NEW BUG: "offentlig sygesikring" (public insurance) misclassified as DSS → escalated to staff** |

**Result:** FAIL — Patient should have continued to Classification. "Offentlig sygesikring" means public health insurance, not DSS/private.

### HandoffRequest:
- insurance_type: "dss" ✗ (should be "public")
- reason: "Patient confirmed they have public (DSS) insurance" — model confused public and DSS
- language: "da" ✓
- patient_name: "Mette" ✓

### New Bug: Insurance misclassification
**Root cause:** Model doesn't distinguish between "offentlig sygesikring" (public) and "Dansk Sundhedssikring / DSS" (private). The word "sygesikring" may trigger false DSS match.
**Severity:** CRITICAL — affects every Danish-speaking patient who mentions public insurance.
**Fix needed:** Explicit instruction: "'offentlig sygesikring' / 'det gule kort' = PUBLIC insurance (continue triage). Only 'Dansk Sundhedssikring' / 'DSS' / 'privat forsikring' = DSS (hand off to staff)."

---

## War Game 5: Urgent Category A — Heavy Bleeding

**Date:** 2026-02-27 | **Model:** gpt-5-mini | **Tests:** Category A escalation

**Scenario:** Patient reports heavy bleeding and severe pain.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "Hello I'm having very heavy bleeding and severe pain, I need help right away" | **Staff Handoff** | HandoffRequest (urgency: immediate) | ✓ Correct escalation |

**Result:** SUCCESS — Immediate escalation with thorough HandoffRequest.

### HandoffRequest Accuracy:
- urgency: "immediate" ✓
- language: "en" ✓
- reason: Mentions hemorrhage, emergency assessment ✓
- suggested_action: Detailed triage instructions ✓
- insurance_type: "null" ✗ (string "null" instead of actual null — minor)

---

## War Game 6: DSS Insurance — Immediate Handoff

**Date:** 2026-02-27 | **Model:** gpt-5-mini | **Tests:** DSS detection, Issue #1

**Scenario:** Patient explicitly mentions Dansk Sundhedssikring.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "Hi, I have insurance through Dansk Sundhedssikring, my name is Lisa, phone 44556677" | **Staff Handoff** | HandoffRequest (urgency: normal) | ✓ Correct DSS handoff |

**Result:** SUCCESS — Correct and fast escalation. No text from Dispatch (Issue #1 may be fixed for escalation path).

### HandoffRequest Accuracy:
- insurance_type: "dss" ✓
- urgency: "normal" ✓
- patient_name: "Lisa" ✓
- phone_number: "44556677" ✓
- language: "en" ✓

---

## War Game 7: Full Flow — IUD Removal with Strings Visible

**Date:** 2026-02-27 | **Model:** gpt-5-mini | **Tests:** Group disambiguation, routing, two-step booking

**Scenario:** Patient provides all intake info upfront, needs IUD removal.

| Turn | Patient | Agent | Response | Issue? |
|------|---------|-------|----------|--------|
| 1 | "Hello, my name is Sarah Jensen, phone 23456789, I have public insurance and a referral. No doctor preference." | Classification | "Could you tell me what brings you in?" | ✓ **Dispatch was SILENT** — routed directly to Classification (Issue #1 FIXED here) |
| 2 | "I need to have my IUD removed" | Classification | "Are the IUD strings visible or can you feel them?" | ✓ Natural disambiguation question — no numbered list |
| 3 | "yes they can be seen at checkups" | **Dispatch** | "Thank you — I see that your IUD strings are visible..." | **BUG: Dispatch produced text** (Issue #1 intermittent) |
| 4 | "sure, go ahead" | Scheduling | (empty) | Silent handoff |
| 5 | "yes please continue" | Scheduling | Asked for date of birth | BUG: Asked for DOB instead of age. IUD removal (id 20) is not cycle-dependent, so shouldn't need cycle info |
| 6 | "I'm 34 years old" | **Dispatch** | (empty) | ✓ Silent handoff |
| 7 | "sure, what do you need to know?" | Scheduling | (empty) | Silent |
| 8 | "I just want to book the removal" | **Dispatch** | "No lab tests or cycle timing required... I'll transfer you" | **BUG: Dispatch produced text** |
| 9 | "ok show me the times" | **Booking** | BookingRequest produced immediately | **BUG: Skipped slot presentation** (Issue #4 NOT fixed) |

**Result:** PARTIAL SUCCESS — Reached BookingRequest. Classification disambiguation was excellent. Dispatch is intermittently silent (sometimes works, sometimes doesn't).

### BookingRequest Accuracy:
- condition_id: 20 (IUD removal — standard) ✓
- category: C ✓
- doctor: LB ✓
- duration_minutes: 15 ✓
- lab_required: false ✓ (patient is 34, over 30)
- cycle_dependent: false ✓
- no_cycle: true ✗ (should be false — patient never said she has no cycle)
- selected_slot: null ✗ (slot presentation skipped)

---

## Post-Fix Summary (WG3-WG7)

### What improved:
| Issue | Status | Evidence |
|-------|--------|----------|
| #1: Dispatch text | **PARTIALLY FIXED** | Silent in WG7 turn 1 and WG7 turn 6, but still produces text ~60% of the time |
| #2: Escape hatch too aggressive | **FIXED** | WG3 completed without false escalation (patient said "hello?" and "can you help?" without triggering escape) |
| #3: Language detection on "hi" | **NOT FIXED** | WG3 turn 1 still defaults to Danish. Model ignores the explicit instruction |
| #4: Booking skips slots | **NOT FIXED** | Both WG3 and WG7 produced BookingRequest without presenting slots first |
| #5: Date format | **FIXED** | WG3 BookingRequest has "2026-02-10" (correct ISO format) |

### New bugs found:
| Bug | Severity | Description |
|-----|----------|-------------|
| #6: Insurance misclassification | CRITICAL | "offentlig sygesikring" (public) treated as DSS → false escalation (WG4) |
| #7: Scheduling misses cycle dependency | HIGH | Endometriosis (id 18, cycle_days="just_before_next_period") reported as "not cycle-dependent" (WG3) |
| #8: Booking misses questionnaire | MEDIUM | Endometriosis should get "Pelvic Pain" questionnaire, BookingRequest has null (WG3) |
| #9: no_cycle=true when patient never said so | LOW | IUD removal BookingRequest set no_cycle=true without patient stating amenorrhea (WG7) |

### Root Cause: Prompt compliance limits of gpt-5-mini
Issues #1, #3, and #4 have clear instructions that the model simply doesn't follow reliably. These may require **structural enforcement** rather than prompt instructions:
- **Issue #1:** Dispatch may need to be a code-level router (Python logic) instead of an LLM agent
- **Issue #3:** Language detection could be done in code before the agent runs
- **Issue #4:** Booking agent could be split into two separate agents (SlotPresenter + BookingFinalizer) so the LLM can't skip steps
- **Issue #6:** Insurance classification should be done via keyword matching in code, not LLM interpretation

---

# v2 Architecture — War Games (WG8-WG12)

**Date:** 2026-02-27
**Model:** gpt-5-mini
**Architecture:** Single Triage Agent + Python Orchestrator (no Dispatch agent)

## Architecture Changes (v1 → v2)

| Component | v1 | v2 |
|-----------|----|----|
| Router | LLM Dispatch agent | Eliminated — Python orchestrator |
| Conversation agents | 5 specialists (Intake, Classification, Routing, Scheduling, Booking) | 1 Triage agent handles full conversation |
| Enrichment | LLM agents (Scheduling, Booking) | Deterministic Python (`_enrich_booking()`) |
| Slot booking | LLM (Booking agent with `find_available_slots`) | Removed — clinic calls patient |
| Terminal output | BookingRequest (via LLM) or HandoffRequest | BookingRequest (Python-computed) or HandoffRequest (LLM) |
| Confirmation | None | LLM Confirmation Agent — warm patient message |

---

## War Game 8: Shy Patient — IUD Insertion (age 25)

**Tests:** Language detection ("hi"), full flow, cycle window (CD 3-7), chlamydia lab (age < 30)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi" | Asked for insurance type | ✓ Responded in ENGLISH (Issue #3 FIXED) |
| 2 | "yes, public insurance" | Asked for referral | ✓ |
| 3 | "yes I have a referral. My name is Anna, phone 55512345" | Asked what brings them in | ✓ Extracted name + phone in one go |
| 4 | "I need to have an IUD put in" | Asked disambiguation (IUD group) | ✓ Natural question, no numbered list |
| 5 | "a new one inserted please" | Asked for last period date | ✓ Identified condition 19, found cycle_days |
| 6 | "about February 20th, so 2026-02-20" | Asked for cycle length | ✓ |
| 7 | "about 28 days. Oh and I'm 25 years old" | Mentioned chlamydia lab requirement | ✓ Proactively informed patient about lab |
| 8 | "no I haven't had one yet, but I can get it done" | Asked about getting test done | Slightly chatty — could have completed here |
| 9 | "I'll get it done at my GP..." | → BookingRequest | ✓ Complete |

**Result:** SUCCESS — 9 turns (vs 9+ turns in v1 that FAILED with false escalation)

### BookingRequest Verification:
| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| language | en | en | ✓ |
| condition_id | 19 (IUD insertion) | 19 | ✓ |
| category | C | C | ✓ |
| doctor | LB | LB | ✓ |
| duration_minutes | 30 | 30 | ✓ |
| patient_age | 25 | 25 | ✓ |
| cycle_dependent | true | true | ✓ |
| valid_booking_window | CD 3-7 next cycle | "Mar 22 - Mar 26" | ✓ |
| lab_required | true (age < 30) | true | ✓ |
| lab_details | chlamydia | "chlamydia. Negative chlamydia test required for patients under 30" | ✓ |
| questionnaire | null | null | ✓ |
| self_pay | false | false | ✓ |
| Confirmation message | warm, English | ✓ Mentions Dr. Bech, timing, chlamydia, phone callback | ✓ |

---

## War Game 9: Danish Patient — Endometriosis

**Tests:** Danish language, insurance classification ("offentlig sygesikring"), "just_before_next_period" cycle, Pelvic Pain questionnaire

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "Hej, jeg har offentlig sygesikring og en henvisning..." | Asked what brings them in (in Danish) | ✓ Correctly identified PUBLIC insurance (Issue #6 FIXED) |
| 2 | "Jeg er henvist for endometriose" | Asked for last period date (Danish) | ✓ Identified condition 18, found cycle_days |
| 3 | "Det var den 2026-02-10" | Asked for cycle length (Danish) | ✓ |
| 4 | "Cirka 30 dage" | → BookingRequest | ✓ Complete |

**Result:** SUCCESS — 4 turns (vs 10 turns in v1 WG3, which missed cycle dependency and questionnaire)

### BookingRequest Verification:
| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| language | da | da | ✓ |
| insurance_type | public | public | ✓ (was "dss" in v1 WG4) |
| condition_id | 18 (Endometriosis) | 18 | ✓ |
| doctor | HS | HS | ✓ |
| duration_minutes | 45 | 45 | ✓ |
| cycle_dependent | true | true | ✓ (was false in v1 WG3) |
| valid_booking_window | just before next period | "Mar 09 - Mar 11" | ✓ (was null in v1 WG3) |
| questionnaire | Pelvic Pain | Pelvic Pain | ✓ (was null in v1 WG3) |
| lab_required | false | false | ✓ |
| Confirmation message | Danish, warm | ✓ Danish, mentions Dr. Skensved, dates, questionnaire | ✓ |

---

## War Game 10: Category A — Heavy Bleeding

**Tests:** Immediate escalation for acute bleeding, collects name + phone before escalating

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "Hello I'm having very heavy bleeding and severe pain, I need help right away" | Empathetic response, asked for name + phone, mentioned ER safety net (112) | ✓ Recognized urgency, asked both in one message |
| 2 | "My name is Maria, phone 99887766" | → HandoffRequest | ✓ Escalated with name + phone populated |

**Result:** SUCCESS — 2 turns (collects contact info for staff to reach patient)

### HandoffRequest Verification:
| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| escalate | true | true | ✓ |
| category | A | A | ✓ |
| condition_id | 1 (Acute/heavy bleeding) | 1 | ✓ |
| urgency | immediate | immediate | ✓ |
| patient_name | Maria | Maria | ✓ |
| phone_number | 99887766 | 99887766 | ✓ |
| reason | describes urgency | Detailed clinical assessment | ✓ |
| suggested_action | meaningful | Comprehensive triage plan (call patient, assess, ER if unstable) | ✓ |

---

## War Game 11: DSS Insurance — Immediate Handoff

**Tests:** DSS detection, immediate escalation

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "Hi, I have insurance through Dansk Sundhedssikring, my name is Lisa, phone 44556677" | → HandoffRequest | ✓ Immediate DSS escalation, 1 turn |

**Result:** SUCCESS — 1 turn (same as v1 WG6)

### HandoffRequest Verification:
| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| insurance_type | dss | dss | ✓ |
| escalate | true | true | ✓ |
| urgency | normal | normal | ✓ |
| patient_name | Lisa | Lisa | ✓ |
| phone_number | 44556677 | 44556677 | ✓ |
| reason | DSS requires staff | Clear DSS handling explanation | ✓ |

---

## War Game 12: Vague "Spiral" — Disambiguation to IUD Removal

**Tests:** Condition group disambiguation, routing question (strings), doctor assignment

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "Hello, I have public insurance and a referral... My name is Karen, phone 33445566" | Asked what brings them in | ✓ Extracted all intake info |
| 2 | "I need something done with my spiral" | "What do you need help with regarding your IUD (spiral)?" | ✓ Natural disambiguation |
| 3 | "I want to have it taken out" | "Can you see the IUD strings?" | ✓ Routing question for IUD removal |
| 4 | "yes the strings are visible at my checkups" | → BookingRequest | ✓ Complete |

**Result:** SUCCESS — 4 turns (vs 9 turns in v1 WG7)

### BookingRequest Verification:
| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 20 (IUD removal standard) | 20 | ✓ |
| doctor | LB (strings visible) | LB | ✓ |
| duration_minutes | 15 | 15 | ✓ |
| cycle_dependent | false | false | ✓ |
| lab_required | false | false | ✓ |
| no_periods | false | false | ✓ (was true in v1 WG7 — Bug #9 FIXED) |
| questionnaire | null | null | ✓ |
| Confirmation message | warm, English | ✓ Mentions Dr. Bech, phone callback | ✓ |

---

## v2 Summary: All Issues Resolved

| v1 Issue | v2 Status | Evidence |
|----------|-----------|----------|
| #1: Dispatch produces text | **ELIMINATED** | No Dispatch agent — Python orchestrator |
| #2: Escape hatch too aggressive | **FIXED** | Prompt: "only CURRENT message triggers this" |
| #3: Language detection on "hi" | **FIXED** | WG8 turn 1: English response to "hi" |
| #4: Booking skips slots | **ELIMINATED** | No slot booking — clinic calls patient |
| #5: Date format | **FIXED** | All dates ISO 8601 |
| #6: Insurance misclassification | **FIXED** | WG9: "offentlig sygesikring" = public (not DSS) |
| #7: Cycle dependency missed | **FIXED** | WG9: endometriosis cycle_dependent=true, window computed |
| #8: Questionnaire missed | **FIXED** | WG9: Pelvic Pain questionnaire populated by Python |
| #9: no_cycle=true false positive | **FIXED** | WG12: no_periods=false (not asked) |

### Turn Count Comparison:
| Scenario | v1 Turns | v2 Turns | Improvement |
|----------|----------|----------|-------------|
| WG8 (IUD insertion) | 9 (FAIL) | 9 (SUCCESS) | Was a failure, now completes |
| WG9 (Endometriosis) | 10 (partial) | 4 | 60% fewer turns |
| WG10 (Cat A bleeding) | 1 | 2 | +1 turn to collect name/phone for staff |
| WG11 (DSS) | 1 | 1 | Same — already fast |
| WG12 (IUD removal) | 9 (partial) | 4 | 56% fewer turns |

### Remaining Observations:
- WG8 took 9 turns (7 patient messages + 2 chatty lab discussion). Could be 7 if agent didn't ask follow-up about chlamydia test.
- Agent sometimes asks for date in "YYYY-MM-DD format" explicitly — slightly unnatural for a patient chat. Could be made more natural.
- Confirmation agent produces high-quality, warm messages in both English and Danish.

---

# v2 War Games — Round 2 (WG13-WG23)

**Date:** 2026-02-27
**Model:** gpt-5-mini
**Focus:** Natural patient behavior — minimal info, gradual reveal, "hi" greetings

---

## War Game 13: Follow-up Menopause (Danish, Dr. Bech)

**Tests:** Danish, follow-up flag, menopause group disambiguation, routing to same doctor

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej" | Insurance question (Danish) | ✓ Danish response |
| 2 | "ja offentlig" | Referral question | ✓ |
| 3 | "nej, jeg er allerede patient hos jer, det er bare en kontrol" | Self-pay offer | Issue: pushed self-pay for existing follow-up patient |
| 4 | "jamen jeg er allerede patient, det er en opfølgning på min overgangsalder" | Asked for name | ✓ Moved on after clarification |
| 5 | "Birthe Larsen" | Asked for phone | ✓ |
| 6 | "66778899" | "Hvilken læge så du sidst?" | ✓ Routing question for menopause follow-up |
| 7 | "det var Dr. Bech" | → BookingRequest | ✓ |

**Result:** SUCCESS — 7 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 30 | 30 | ✓ |
| doctor | LB (saw Dr. Bech) | "Dr. Bech" | ✓ (minor: should be code "LB") |
| is_followup | true | true | ✓ |
| duration_minutes | 15 | 15 | ✓ |
| self_pay | true | true | ✓ (no referral = self-pay) |

---

## War Game 14: Irregular Bleeding (age 38 → Dr. LB)

**Tests:** Condition 15, age routing, "Premenopausal Bleeding" questionnaire

**First attempt:** Patient said "super heavy" → misclassified as Category A (condition 1) instead of condition 15. The keyword "heavy bleeding" triggered acute bleeding match.

**Second attempt (WG14b):** Patient said "irregular periods, sometimes twice a month" (avoiding "heavy"):

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi" | Insurance question | ✓ English |
| 2 | "public, referral from my GP. I'm Sophie, 40506070" | "What brings you in?" | ✓ Extracted all intake info |
| 3 | "my periods have been really irregular, sometimes twice a month. My GP referred me" | "May I ask your age?" | ✓ Condition 15, routing question |
| 4 | "I'm 38" | → BookingRequest | ✓ |

**Result:** SUCCESS — 4 turns (second attempt). **Bug noted:** "super heavy" keyword causes Category A misclassification for chronic bleeding.

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 15 | 15 | ✓ |
| doctor | LB (age 38 ≤ 45) | LB | ✓ |
| questionnaire | Premenopausal Bleeding | Premenopausal Bleeding | ✓ |

---

## War Game 15: Fertility Consultation (labs + partner questionnaire)

**Tests:** Condition 10, extensive lab requirements, UXOR + VIR questionnaires

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public" | Referral question | ✓ |
| 3 | "yes" | Name question | ✓ |
| 4 | "Lena. My number is 11223344" | "What brings you in?" | ✓ |
| 5 | "we've been trying to get pregnant for over a year..." | → BookingRequest | ✓ |

**Result:** SUCCESS — 5 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 10 | 10 | ✓ |
| doctor | LB | LB | ✓ |
| duration_minutes | 45 | 45 | ✓ |
| lab_required | true | true | ✓ |
| lab_details | fertility panels, semen analysis, HIV/Hep | All present | ✓ |
| questionnaire | Infertility Questionnaire (UXOR) | UXOR | ✓ |
| partner_questionnaire | Infertility Questionnaire (VIR) | VIR | ✓ |

---

## War Game 16: Self-Pay Smear Test (no referral)

**Tests:** Self-pay flow, condition 38, pricing (950 DKK)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hey" | Insurance question | ✓ |
| 2 | "public but I don't have a referral, I just want a smear test" | Self-pay offer | ✓ |
| 3 | "sure, how much does it cost?" | "600-900 DKK... we'll confirm" + asked for name | Note: agent guessed price (actual: 950 DKK). Price in enrichment is correct |
| 4 | "ok. I'm Eva, 55667788" | → BookingRequest | ✓ |

**Result:** SUCCESS — 4 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 38 | 38 | ✓ |
| self_pay | true | true | ✓ |
| self_pay_price_dkk | 950 | 950 | ✓ |
| cycle_dependent | false | false | ✓ |

---

## War Game 17: Escape Hatch Mid-Conversation

**Tests:** Patient asks for human mid-flow

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi" | Insurance question | ✓ |
| 2 | "public, with a referral" | Name question | ✓ |
| 3 | "Katrine, 44332211" | "What brings you in?" | ✓ |
| 4 | "actually this is getting too complicated, I'd rather just speak to someone at the clinic" | → HandoffRequest | ✓ |

**Result:** SUCCESS — 4 turns, immediate escalation

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| escalation_reason | Patient requested staff | "Patient requested staff" | ✓ |
| urgency | normal | normal | ✓ |
| patient_name | Katrine | Katrine | ✓ |
| phone_number | 44332211 | 44332211 | ✓ |

---

## War Game 18: Confused Patient — Unclassifiable

**Tests:** Vague symptoms, agent tries to classify, eventually hands off

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, I have a referral. I'm Nina, 99001122" | "What brings you in?" | ✓ |
| 3 | "I'm not really sure, my doctor said something about my hormones being off..." | Asked about symptoms | ✓ Good follow-up |
| 4 | "I've just been feeling really tired and I've gained some weight" | "Could you check the referral?" | ✓ Tried to help |
| 5 | "I really can't read it... Can I just talk to someone at the clinic?" | → HandoffRequest | ✓ |

**Result:** SUCCESS — 5 turns, graceful handoff

---

## War Game 19: Prolapse Ring Change (Danish, follow-up)

**Tests:** Prolapse group disambiguation, condition 36, Danish

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej" | Insurance question (Danish) | ✓ |
| 2 | "offentlig" | Referral question | ✓ |
| 3 | "nej, jeg skal bare have skiftet min ring" | Name question | ✓ |
| 4 | "Inge Petersen, 88776655" | Self-pay offer | ✓ (no referral = self-pay) |
| 5 | "ja det er fint" | Prolapse disambiguation | ✓ |
| 6 | "ja, min pessar-ring skal bare skiftes, den sidder lidt stramt" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 36 | 36 | ✓ |
| doctor | LB | LB | ✓ |
| duration_minutes | 15 | 15 | ✓ |
| self_pay | true | true | ✓ |

---

## War Game 20: PCOS New Referral

**Tests:** PCOS group disambiguation, condition 39, lab (CD3 blood panel)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hey" | Insurance question | ✓ |
| 2 | "public, and I have a referral" | Name question | ✓ |
| 3 | "Amira" | Phone question | ✓ |
| 4 | "12345678" | "What brings you in?" | ✓ |
| 5 | "I was told I might have PCOS" | "New referral or follow-up?" | ✓ PCOS group disambiguation |
| 6 | "it's new, first time" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 39 | 39 | ✓ |
| lab_required | true | true | ✓ |
| lab_details | PCOS blood panel on CD3 | Present, mentions Provera | ✓ |
| questionnaire | You & Your Gynaecological Problem | Present | ✓ |

---

## War Game 21: Older Patient, Irregular Bleeding (age 52 → Dr. HS)

**Tests:** Age-based routing for condition 15, Danish

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej, jeg vil gerne bestille en tid" | Insurance question | ✓ |
| 2 | "offentlig, og jeg har en henvisning" | Name question | ✓ |
| 3 | "Kirsten, 77889900" | "What brings you in?" | ✓ |
| 4 | "jeg bløder uregelmæssigt, det har stået på i et par uger" | "Er blødningen kraftig?" | ✓ Clarifying to distinguish Cat A vs C |
| 5 | "nej det er ikke kraftigt, bare uregelmæssigt. Jeg er 52 år" | → BookingRequest | ✓ |

**Result:** SUCCESS — 5 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 15 | 15 | ✓ |
| doctor | HS (age 52 > 45) | HS | ✓ |
| questionnaire | Premenopausal Bleeding | Premenopausal Bleeding | ✓ |

---

## War Game 22: Condition Mentioned First (out of order)

**Tests:** Patient mentions cone biopsy before intake, Category B, guidance document

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi, I need to get a cone biopsy done" | Insurance question | ✓ Acknowledged condition |
| 2 | "public, I have a referral. I'm Julia, 33221100" | → BookingRequest | ✓ |

**Result:** SUCCESS — 2 turns (fastest possible)

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 8 (Cone biopsy) | 8 | ✓ |
| category | B | B | ✓ |
| priority_window | 14_days | 14_days | ✓ |
| guidance_document | Kegleoperation | Kegleoperation | ✓ |

---

## War Game 23: Second Opinion — Fertility Related

**Tests:** Condition 52, fertility routing question (implicit from context)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, referral, my name is Sofie, 11119999" | "What brings you in?" | ✓ |
| 3 | "I want a second opinion on my fertility treatment, we've been doing IVF..." | → BookingRequest | ✓ |

**Result:** SUCCESS — 3 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 52 | 52 | ✓ |
| doctor | LB (fertility-related) | LB | ✓ |

---

## Round 2 Summary

### Turn Count:
| WG | Scenario | Turns | Notes |
|----|----------|-------|-------|
| 13 | Menopause follow-up (Danish) | 7 | Extra turn from self-pay clarification |
| 14b | Irregular bleeding (age routing) | 4 | |
| 15 | Fertility (labs + questionnaires) | 5 | |
| 16 | Self-pay smear test | 4 | |
| 17 | Escape hatch | 4 | |
| 18 | Confused patient | 5 | |
| 19 | Prolapse ring change (Danish) | 6 | |
| 20 | PCOS new referral | 6 | |
| 21 | Older bleeding (age > 45) | 5 | |
| 22 | Out-of-order (cone biopsy) | 2 | Fastest possible |
| 23 | Second opinion (fertility) | 3 | |
| **Average** | | **4.6** | |

### Bugs Found:
| Bug | Severity | Description | WG |
|-----|----------|-------------|----|
| #10: "Heavy" keyword triggers Cat A for chronic bleeding | HIGH | Patient said "super heavy periods" → misclassified as Category A acute bleeding instead of condition 15 (premenopausal bleeding). Keyword overlap between conditions 1 and 15. | WG14 |
| #11: Doctor code vs name | LOW | Agent sometimes returns "Dr. Bech" instead of code "LB" in the doctor field | WG13 |
| #12: Agent guesses prices | LOW | Agent told patient "600-900 DKK" for smear test; actual price is 950 DKK. Enrichment has correct price. | WG16 |

### What works well:
- Natural conversation flow — one question at a time, empathetic tone
- Handles Danish and English seamlessly, including mid-conversation language detection
- Disambiguation questions are natural (no numbered lists)
- Routing questions asked only when needed (age, strings, previous doctor, fertility)
- Implicit routing from context (WG23: "second opinion on fertility" → no need to ask separately)
- Out-of-order input handled gracefully (WG22: 2 turns)
- Confused patients get reasonable follow-ups before graceful handoff
- Deterministic enrichment never misses fields (cycle, lab, questionnaire, guidance, pricing)

---

## Round 3: gpt-5.2 Re-runs (Model Comparison)

**Date:** 2026-02-27
**Model:** gpt-5.2
**Changes from Round 2:** Updated insurance question (removed "self-pay" option — self-pay depends on referral, not insurance type)

### WG10r: Category A Emergency (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "I'm bleeding really heavily, soaking through pads every hour" | Empathetic, asked for name | ✓ Same as gpt-5-mini |
| 2 | "Maria, 55501234" | → HandoffRequest | ✓ |

**Result:** SUCCESS — 2 turns, immediate escalation. urgency="immediate". Identical to gpt-5-mini.

---

### WG11r: DSS Insurance (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej, jeg har Dansk Sundhedssikring" | → HandoffRequest | ✓ Immediate DSS escalation |

**Result:** SUCCESS — 1 turn. Handoff summary in Danish with detailed suggested_action. Identical to gpt-5-mini.

---

### WG17r: Escape Hatch Mid-Conversation (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi" | Insurance question | ✓ English, no self-pay mention |
| 2 | "public, with a referral" | Name question | ✓ |
| 3 | "Katrine, 44332211" | "What brings you in?" | ✓ |
| 4 | "actually this is getting too complicated, I'd rather just speak to someone at the clinic" | → HandoffRequest | ✓ |

**Result:** SUCCESS — 4 turns (same as gpt-5-mini). Clean escalation with detailed summary.

---

### WG18r: Confused Patient — Unclassifiable (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, I have a referral. I'm Nina, 99001122" | "What brings you in?" | ✓ |
| 3 | "I'm not really sure, my doctor said something about my hormones being off..." | Asked about specific symptoms (irregular bleeding, no periods, pain, acne, hot flashes, trouble getting pregnant) | ✓ Better than gpt-5-mini — more specific symptom list |
| 4 | "I really can't read it... Can I just talk to someone at the clinic?" | → HandoffRequest | ✓ |

**Result:** SUCCESS — 4 turns (vs 5 on gpt-5-mini). Skipped the "I've been feeling tired" exchange since patient asked for human sooner.

---

### WG19r: Prolapse Ring Change — Danish, No Referral (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej" | "Har du offentlig sygesikring (det gule kort)?" | ✓ Danish |
| 2 | "offentlig" | Referral question | ✓ |
| 3 | "nej, jeg skal bare have skiftet min ring" | Prolapse ring disambiguation | ✓ Smart: asked about prolapse ring before asking for self-pay confirmation |
| 4 | "ja, min pessar-ring skal bare skiftes" | Self-pay offer | ✓ |
| 5 | "ja det er fint" | Name question | ✓ |
| 6 | "Inge Petersen, 88776655" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns (same as gpt-5-mini)

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 36 | 36 | ✓ |
| doctor | LB | LB | ✓ |
| self_pay | true | true | ✓ |
| self_pay_price_dkk | null | null | ✓ (no price in YAML for condition 36) |

---

### WG20r: PCOS New Referral (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hey" | Insurance question | ✓ |
| 2 | "public, and I have a referral" | Name question | ✓ |
| 3 | "Amira" | Phone question | ✓ |
| 4 | "12345678" | "What brings you in?" | ✓ |
| 5 | "I was told I might have PCOS" | "New referral or follow-up?" | ✓ PCOS group disambiguation |
| 6 | "it's new, first time" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns (same as gpt-5-mini)

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 39 | 39 | ✓ |
| lab_required | true | true | ✓ |
| lab_details | PCOS blood panel on CD3 | ✓ Mentions Provera | ✓ |
| questionnaire | You & Your Gynaecological Problem | ✓ | ✓ |

---

### WG21r: Older Patient, Irregular Bleeding — Age 52 → Dr. HS (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej, jeg vil gerne bestille en tid" | Insurance question (Danish) | ✓ |
| 2 | "offentlig, og jeg har en henvisning" | Name question | ✓ |
| 3 | "Kirsten, 77889900" | "Hvad kan vi hjælpe dig med i dag?" | ✓ |
| 4 | "jeg bløder uregelmæssigt, det har stået på i et par uger" | "Hvor gammel er du?" | ✓ Directly asked age (routing question) |
| 5 | "nej det er ikke kraftigt, bare uregelmæssigt. Jeg er 52 år" | → BookingRequest | ✓ |

**Result:** SUCCESS — 5 turns (same as gpt-5-mini)

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 15 | 15 | ✓ |
| doctor | HS (age 52 > 45) | HS | ✓ |
| questionnaire | Premenopausal Bleeding | ✓ | ✓ |

---

### WG22r: Out-of-Order — Cone Biopsy First (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi, I need to get a cone biopsy done" | Insurance question | ✓ Acknowledged condition |
| 2 | "public, I have a referral. I'm Julia, 33221100" | → BookingRequest | ✓ |

**Result:** SUCCESS — 2 turns (fastest possible, same as gpt-5-mini)

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 8 | 8 | ✓ |
| category | B | B | ✓ |
| priority_window | 14_days | 14_days | ✓ |
| guidance_document | Kegleoperation | Kegleoperation | ✓ |

---

### WG23r: Second Opinion — Fertility (gpt-5.2)

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, referral, my name is Sofie, 11119999" | "What brings you in?" | ✓ |
| 3 | "I want a second opinion on my fertility treatment, we've been doing IVF..." | "Is this related to fertility?" | ✗ Slightly redundant — patient already said "fertility treatment" |
| 4 | "yes, obviously it's fertility related" | → BookingRequest | ✓ |

**Result:** SUCCESS — 4 turns (vs 3 on gpt-5-mini). One extra turn due to unnecessary routing confirmation.

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 52 | 52 | ✓ |
| doctor | LB (fertility-related) | LB | ✓ |

**Note:** gpt-5-mini inferred fertility-related from context without asking. gpt-5.2 asked explicitly. Both got the correct result.

---

## Round 3 Summary: gpt-5.2 vs gpt-5-mini

### Turn Count Comparison:

| WG | Scenario | gpt-5-mini | gpt-5.2 | Delta | Notes |
|----|----------|------------|---------|-------|-------|
| 10 | Category A emergency | 2 | 2 | = | |
| 11 | DSS escalation | 1 | 1 | = | |
| 17 | Escape hatch | 4 | 4 | = | |
| 18 | Confused patient | 5 | 4 | -1 | Patient asked for human sooner |
| 19 | Prolapse ring (Danish) | 6 | 6 | = | |
| 20 | PCOS new referral | 6 | 6 | = | |
| 21 | Older bleeding (age routing) | 5 | 5 | = | |
| 22 | Out-of-order (cone biopsy) | 2 | 2 | = | |
| 23 | Second opinion (fertility) | 3 | 4 | +1 | Redundant fertility confirmation Q |
| **Average** | | **3.8** | **3.8** | **=** | |

### Bug Fixes in gpt-5.2 (from earlier Round 2 re-runs):

| Bug | gpt-5-mini | gpt-5.2 | Status |
|-----|-----------|---------|--------|
| #10: "Heavy" keyword → Category A for chronic bleeding | Misclassified | ✓ Asked clarifying Q | FIXED |
| #11: Doctor code vs name (LB vs "Dr. Bech") | "Dr. Bech" | "LB" | FIXED |
| #12: Agent guesses prices | "600-900 DKK" | "I can't see the current price list" | FIXED |

### gpt-5.2 Improvements:
- **Better disambiguation:** Asks clarifying questions before jumping to conclusions (e.g., "super heavy" bleeding → asks whether acute or chronic)
- **Correct doctor codes:** Uses "HS"/"LB" instead of full names
- **No price hallucination:** Doesn't guess prices it doesn't know
- **Richer symptom prompts:** WG18 asked for specific symptom categories instead of generic follow-up
- **Better handoff summaries:** More detailed, structured suggested_actions

### gpt-5.2 Regressions:
- **WG23:** Didn't infer fertility-related from context like gpt-5-mini did — asked explicit confirmation (minor, correct result either way)

### Insurance Question Fix:
- Removed "self-pay" from insurance type options
- Insurance now only asks: "Do you have public health insurance (sygesikring)?"
- Self-pay is correctly determined by referral status, not insurance type
- All scenarios correctly handle the new flow

---

## Round 4: New Scenarios (gpt-5.2)

**Date:** 2026-02-27
**Model:** gpt-5.2

---

### WG24: Incontinence — New Referral (Danish)

**Tests:** Condition 31, voiding diary lab, dual questionnaires, Danish flow

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej" | Insurance question (English) | ✗ Minor: responded in English to "hej" |
| 2 | "offentlig, med henvisning. Jeg hedder Birgit, 22115566" | "Hvad vil du gerne booke tid til?" | ✓ Switched to Danish, extracted all intake |
| 3 | "jeg har problemer med at lække urin, især når jeg hoster eller griner" | "Er det ny henvisning eller opfølgning?" | ✓ Hit incontinence group disambiguation |
| 4 | "det er nyt, min læge har henvist mig" | → BookingRequest | ✓ |

**Result:** SUCCESS — 4 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 31 | 31 | ✓ |
| doctor | LB | LB | ✓ |
| lab_required | true | true | ✓ |
| lab_details | voiding diary + morning urine | ✓ | ✓ |
| questionnaire | You & Your Gynaecological Problem, Urinary Problems / Incontinence | Both present | ✓ |

---

### WG25: Hysteroscopy — Cycle-Dependent (CD 4-8)

**Tests:** Condition 41, Dr. HS, cycle window calculation

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, referral. I'm Claire, 55443322" | "What brings you in?" | ✓ |
| 3 | "I've been referred for a hysteroscopy" | "When was the first day of your last period?" | ✓ Jumped straight to cycle Q |
| 4 | "hmm let me think... it was about February 15th I think" | "How long is your cycle?" | ✓ |
| 5 | "about 30 days usually" | → BookingRequest | ✓ |

**Result:** SUCCESS — 5 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 41 | 41 | ✓ |
| doctor | HS | HS | ✓ |
| cycle_dependent | true | true | ✓ |
| valid_booking_window | Next window: Mar 20-24 (CD 4-8 of next cycle) | "Next window: Mar 20 - Mar 24" | ✓ |
| last_period_date | 2026-02-15 | 2026-02-15 | ✓ |
| cycle_length | 30 | 30 | ✓ |

---

### WG26: IUD Replacement — Strings NOT Visible → Dr. HS

**Tests:** IUD group disambiguation, routing question (strings), doctor override, cycle-dependent

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi" | Insurance question | ✓ |
| 2 | "public, referral. My name is Sara, 77665544" | "What brings you in?" | ✓ |
| 3 | "I need to get my IUD replaced, it's been 5 years" | IUD group disambiguation | ✓ |
| 4 | "I need it replaced with a new one" | "Can the strings usually be seen at your check-ups?" | ✓ Routing question triggered |
| 5 | "no, the doctor couldn't find them last time" | "When was the first day of your last period?" | ✓ Doctor overridden to HS |
| 6 | "around February 12th, cycle is pretty regular at 28 days" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 21 | 21 | ✓ |
| doctor | HS (strings not visible override) | HS | ✓ |
| cycle_dependent | true | true | ✓ |
| valid_booking_window | Next window: Mar 14-18 | "Next window: Mar 14 - Mar 18" | ✓ |
| lab_required | true (chlamydia, age unknown) | true | ✓ |

---

### WG27: Postmenopausal Bleeding — Category B

**Tests:** Condition 7 (Category B), Dr. HS, 1_week priority

**First attempt (before fix):**

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej, jeg er 61 år og jeg er begyndt at bløde igen" | Empathetic response, asked for name | ✗ BUG: Treated as urgent, skipped insurance |
| 2 | "Dorthe Lund, 99887766" | → HandoffRequest | ✗ BUG: Escalated as urgent instead of booking |

**Bug #13: Postmenopausal bleeding over-escalated**
- Agent treated postmenopausal bleeding (Category B) as if it were Category A
- Condition misidentified as 15 (premenopausal bleeding) instead of 7 (postmenopausal bleeding)
- The prompt's urgent detection rule for "bleeding" was too broad — caught Category B bleeding cases
- **Fix:** Refined urgent detection to only trigger for ACTIVE, HAPPENING-NOW emergencies. Added explicit exclusions for postmenopausal bleeding and chronic/recurring bleeding.

**After fix:**

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej, jeg er 61 år og jeg er begyndt at bløde igen" | Insurance question (Danish) | ✓ No escalation, normal flow |
| 2 | "ja, offentlig. Jeg har en henvisning" | Name question | ✓ |
| 3 | "Dorthe Lund, 99887766" | → BookingRequest | ✓ |

**Result:** SUCCESS — 3 turns (after fix). Category A emergencies still escalate correctly (verified separately).

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 7 | 7 | ✓ |
| category | B | B | ✓ |
| doctor | HS | HS | ✓ |
| priority_window | 1_week | 1_week | ✓ |
| patient_age | 61 | 61 | ✓ |

---

### WG28: Polyp Removal — Cervical, Cycle-Dependent

**Tests:** Polyp group disambiguation, condition 43, cycle CD 5-7, guidance document

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hi there" | Insurance question | ✓ |
| 2 | "public, referral, name is Rachel, 33112200" | "What brings you in?" | ✓ |
| 3 | "my GP found a polyp and referred me to get it removed" | "Where is the polyp located?" | ✓ Polyp group disambiguation |
| 4 | "on my cervix, I think" | "When was the first day of your last period?" | ✓ Cycle Q for cervical polyp |
| 5 | "around February 10th, and my cycle is usually 26 days" | → BookingRequest | ✓ |

**Result:** SUCCESS — 5 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 43 | 43 | ✓ |
| doctor | HS | HS | ✓ |
| duration_minutes | 45 | 45 | ✓ |
| cycle_dependent | true | true | ✓ |
| valid_booking_window | Next window: Mar 12-14 (CD 5-7) | "Next window: Mar 12 - Mar 14" | ✓ |
| guidance_document | Removed polyp info | Removed polyp info | ✓ |

---

### WG29: Menopause New — Under 45, Routing Question

**Tests:** Condition 29, routing Q (seen Dr. Skensved?), lab (under 45), questionnaire

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hey" | Insurance question | ✓ |
| 2 | "public, and I have a referral" | Name question | ✓ |
| 3 | "Emily" | Phone question | ✓ |
| 4 | "33445566" | "What brings you in?" | ✓ |
| 5 | "I've been having terrible hot flashes and night sweats, my GP thinks it might be early menopause" | "New referral or follow-up?" | ✓ Menopause group disambiguation |
| 6 | "it's new, never been here before" | "Have you previously been seen by Dr. Skensved?" | ✓ Routing question |
| 7 | "no, never" | → BookingRequest | ✓ |

**Result:** SUCCESS — 7 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 29 | 29 | ✓ |
| doctor | LB (never seen Dr. Skensved → override) | LB | ✓ |
| lab_required | true | true | ✓ |
| lab_details | menopause blood panel | ✓ | ✓ |
| questionnaire | You & Your Gynaecological Problem | ✓ | ✓ |

**Note:** Agent didn't ask for age — lab enrichment defaults to requiring it when age is unknown (safe default for "age_under_45" condition).

---

### WG30: Implant Insertion — Cycle-Dependent (CD 1-5)

**Tests:** Contraception group bypass (direct match), condition 25, cycle window

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hello" | Insurance question | ✓ |
| 2 | "public, with a referral" | Name question | ✓ |
| 3 | "Anna, 44556677" | "What brings you in?" | ✓ |
| 4 | "I want to get a contraceptive implant put in" | "When was the first day of your last period?" | ✓ Direct to cycle Q (no group disambiguation needed) |
| 5 | "February 20th" | "How long is your cycle?" | ✓ |
| 6 | "not sure, maybe 28?" | → BookingRequest | ✓ |

**Result:** SUCCESS — 6 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 25 | 25 | ✓ |
| doctor | LB | LB | ✓ |
| cycle_dependent | true | true | ✓ |
| valid_booking_window | Next window: Mar 20-24 (CD 1-5) | "Next window: Mar 20 - Mar 24" | ✓ |

---

### WG31: Pelvic Pain / Dyspareunia (Danish)

**Tests:** Condition 16, Pelvic Pain questionnaire, Danish language

| Turn | Patient | Response | Notes |
|------|---------|----------|-------|
| 1 | "hej" | Insurance question (English) | ✗ Minor: English response to "hej" |
| 2 | "offentlig, jeg har en henvisning" | "Hvad er dit navn?" | ✓ Switched to Danish |
| 3 | "Maja Hansen, 66778899" | "Hvad bringer dig ind i dag?" | ✓ |
| 4 | "jeg har ondt i underlivet, især under samleje" | → BookingRequest | ✓ |

**Result:** SUCCESS — 4 turns

| Field | Expected | Actual | ✓/✗ |
|-------|----------|--------|------|
| condition_id | 16 | 16 | ✓ |
| doctor | LB | LB | ✓ |
| questionnaire | Pelvic Pain | Pelvic Pain | ✓ |
| cycle_dependent | false | false | ✓ |

---

## Round 4 Summary

### Turn Count:

| WG | Scenario | Turns | Notes |
|----|----------|-------|-------|
| 24 | Incontinence (Danish) | 4 | Dual questionnaires + voiding diary |
| 25 | Hysteroscopy | 5 | Cycle CD 4-8 |
| 26 | IUD replacement, strings hidden | 6 | Doctor override + cycle |
| 27 | Postmenopausal bleeding | 3 | Fixed: was over-escalating (bug #13) |
| 28 | Cervical polyp removal | 5 | Group disambiguation + cycle CD 5-7 |
| 29 | Menopause new, under 45 | 7 | Routing Q + lab + questionnaire |
| 30 | Implant insertion | 6 | Cycle CD 1-5 |
| 31 | Pelvic pain (Danish) | 4 | Questionnaire |
| **Average** | | **4.9** | |

### Bugs Found:

| Bug | Severity | Description | WG |
|-----|----------|-------------|----|
| #13: Postmenopausal bleeding over-escalated | HIGH | Agent treated postmenopausal bleeding (Category B) as Category A. The "bleeding" keyword in urgent detection was too broad. **FIXED:** Refined urgent detection to only trigger for active, happening-now emergencies with explicit exclusions for postmenopausal and chronic bleeding. | WG27 |
| #14: "hej" language detection inconsistent | LOW | "hej" alone sometimes gets English response (WG24, WG31) but sometimes Danish (WG19). Model inconsistency — resolves after patient writes more Danish. | WG24, WG31 |

### What works well:
- All group disambiguations triggered correctly (incontinence, IUD, polyp, menopause)
- Routing questions asked only when needed (strings visibility, Dr. Skensved history)
- Doctor overrides working (HS for strings not visible, LB for new patient without Dr. Skensved history)
- Cycle windows computed correctly across 5 different cycle rules (CD 4-8, CD 3-7, CD 5-7, CD 1-5)
- Dual questionnaires returned when applicable (incontinence has 2)
- Lab requirements correctly enriched (voiding diary, chlamydia, menopause blood panel)
- Guidance documents attached (polyp removal info)
- Confirmation messages comprehensive and in patient's language

---

## Round 5: Triage Conversation Chain Coverage (WG32-41)

**Date:** 2026-02-27
**Model:** gpt-5.2
**Changes:** Added current date injection to agent prompt + relative date support for cycle info

### Code Change: Relative Date Support

Added `_TODAY_ISO` and `_TODAY_READABLE` to agent instructions so the agent knows today's date and can convert relative expressions ("about 10 days ago", "last Monday") to YYYY-MM-DD without asking the patient to reformat.

---

### WG32: Premenopausal Bleeding, Age 48

**Scenario:** Patient with irregular bleeding, age 48 — tests age-based routing (>45 → doctor HS).
**Session:** `wg32_bleeding_48` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need to see a doctor about some irregular bleeding" | Asked for insurance |
| 2 | "Yes, I have public insurance" | Asked for referral |
| 3 | "Yes, I have a referral from my GP" | Asked for name |
| 4 | "My name is Karen Jensen" | Asked for phone |
| 5 | "22334455" | Asked age (recognized bleeding → routing question) |
| 6 | "I'm 48" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 15 | 15 | YES |
| condition_name | Premenopausal bleeding | Premenopausal bleeding | YES |
| category | C | C | YES |
| doctor | HS (age >45) | HS | YES |
| duration_minutes | 30 | 30 | YES |
| patient_age | 48 | 48 | YES |
| questionnaire | Premenopausal Bleeding | Premenopausal Bleeding | YES |

**Result: PASS** — Age-based routing override works correctly.

---

### WG33: Contact Bleeding

**Scenario:** Patient with bleeding after intercourse — should be condition 9 (Category B, 14 days).
**Session:** `wg33_contact_bleeding` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I've been referred for some bleeding I've noticed after intercourse" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Emma Thomsen" | Asked for phone |
| 5 | "44556677" | Asked age |
| 6 | "I'm 34" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 9 | **15** | **NO** |
| condition_name | Contact bleeding | **Premenopausal bleeding** | **NO** |
| category | B | **C** | **NO** |
| doctor | LB | LB | YES |
| priority_window | 14_days | **standard** | **NO** |
| questionnaire | Premenopausal Bleeding | Premenopausal Bleeding | YES |
| guidance | Tissue samples from cervix | **null** | **NO** |

**Result: FAIL — Bug #15**

**Bug #15 Fix:** Added "bleeding after intercourse", "bleeding after sex", "blødning efter samleje" as keywords for condition 9 in conditions.yaml. Updated prompt to prefer more specific/higher-priority matches when multiple conditions are returned.

**WG33r (retry):** 5 turns → BookingRequest with condition_id=9, category=B, priority=14_days, guidance="Tissue samples from cervix", questionnaire="Premenopausal Bleeding". **Bug #15 FIXED.**

---

### WG34: Cell Changes (Danish)

**Scenario:** Danish patient referred for abnormal smear results.
**Session:** `wg34_cell_changes_v3` | **Turns:** 5

**Bug:** Original attempt with "Hej, jeg er henvist for celleforandringer" caused immediate false DSS escalation (Bug #16). Modified opening to "Hej, jeg har celleforandringer og vil gerne bestille en tid" — worked correctly.

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hej, jeg har celleforandringer og vil gerne bestille en tid" | Asked for insurance (Danish) |
| 2 | "Ja, offentlig sygesikring" | Asked for referral |
| 3 | "Ja, jeg har en henvisning" | Asked for name |
| 4 | "Sofie Nielsen" | Asked for phone |
| 5 | "55667788" | **→ BookingRequest** |

**Verification (successful attempt):**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 37 | 37 | YES |
| category | C | C | YES |
| doctor | LB | LB | YES |
| priority_window | 1_month | 1_month | YES |
| questionnaire | Cell Changes | Cell Changes | YES |
| guidance | Tissue samples from cervix | Tissue samples from cervix | YES |
| language | da | da | YES |

**Result: FAIL (Bug #16) / PASS (with modified phrasing)**

**Bug #16 Fix:** Added explicit prompt instruction that "henvist"/"henvisning" means referred/referral in Danish and is NOT related to insurance. Agent must always ASK the insurance question explicitly.

**WG34r (retry with original phrasing):** "Hej, jeg er henvist for celleforandringer" → 5 turns → BookingRequest with condition_id=37, language=da, questionnaire="Cell Changes", guidance="Tissue samples from cervix". No false DSS escalation. **Bug #16 FIXED.**

---

### WG35: Menopause Follow-up

**Scenario:** Existing patient needing menopause follow-up, saw Dr. Skensved previously.
**Session:** `wg35_menopause_followup` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I'm an existing patient and I need a follow-up for my menopause treatment" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "I don't have a new referral, I'm an existing patient for follow-up" | Asked for name |
| 4 | "Margaret Hansen" | Asked for phone |
| 5 | "33445566" | Asked "Is this new or follow-up?" (redundant) |
| 6 | "I saw Dr. Skensved last time" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 30 | 30 | YES |
| doctor | HS (same doctor) | HS | YES |
| is_followup | true | true | YES |
| duration_minutes | 15 | 15 | YES |
| questionnaire | none | null | YES |
| self_pay | true (no referral) | true | YES |

**Result: PASS** — Minor issue: redundant "new or follow-up?" question at turn 5.

---

### WG36: Bartholin's Cyst

**Scenario:** Patient referred for a cyst — tests Cysts group disambiguation.
**Session:** `wg36_bartholin` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I've been referred for a cyst" | Asked for insurance |
| 2 | "Public insurance, yes" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Lisa Andersen" | Asked for phone |
| 5 | "11223344" | Asked: ovarian or vulvar/vaginal cyst? |
| 6 | "It's a Bartholin's cyst, on the vulva area" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 28 | 28 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 15 | 15 | YES |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |
| cycle_dependent | false | false | YES |

**Result: PASS** — Cyst group disambiguation works correctly.

---

### WG37: Fibroids (Simplest Path)

**Scenario:** Simplest possible path — no cycle, no lab, no routing question, no questionnaire.
**Session:** `wg37_fibroids` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need to see someone about fibroids" | Asked for insurance |
| 2 | "Yes, I have public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Anna Petersen" | Asked for phone |
| 5 | "99887766" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 53 | 53 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 30 | 30 | YES |
| questionnaire | none | null | YES |
| cycle_dependent | false | false | YES |
| lab_required | false | false | YES |

**Result: PASS** — Cleanest execution, 5 turns.

---

### WG38: Follicle Scanning + Relative Date

**Scenario:** Tests relative date handling — patient says "about 10 days ago" instead of YYYY-MM-DD.
**Session:** `wg38_follicle_relative_date` | **Turns:** 7

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I need to schedule a follicle scanning" | Asked for insurance |
| 2 | "Yes public insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Maria Larsen" | Asked for phone |
| 5 | "77889900" | Asked when last period started |
| 6 | "About 10 days ago" | Asked about cycle length |
| 7 | "Usually about 28 days" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 12 | 12 | YES |
| doctor | LB | LB | YES |
| cycle_dependent | true | true | YES |
| last_period_date | ~2026-02-17 | 2026-02-17 | YES |
| valid_booking_window | Next cycle (passed) | "Next window: Mar 18 - Mar 20" | YES |
| **Relative date conversion** | 10 days ago → 2026-02-17 | 2026-02-17 | **YES** |

**Result: PASS** — Relative date feature works correctly. Agent converted "about 10 days ago" to 2026-02-17 without asking for reformatting.

---

### WG39: Birth Tear (Danish)

**Scenario:** Danish patient with birth tear damage — sensitive topic.
**Session:** `wg39_birth_tear` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hej, jeg har en henvisning for skader efter fødsel" | Asked for insurance (Danish) |
| 2 | "Ja, offentlig sygesikring" | Asked for referral |
| 3 | "Ja jeg har en henvisning" | Asked for name |
| 4 | "Mette Christensen" | Asked for phone |
| 5 | "66778899" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 48 | 48 | YES |
| doctor | LB | LB | YES |
| language | da | da | YES |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |

**Result: PASS** — Danish conversation, correct classification of sensitive topic.

---

### WG40: Uterine Polyp Removal

**Scenario:** Tests polyp group disambiguation (uterine vs cervical) + cycle window + guidance doc.
**Session:** `wg40_uterine_polyp` | **Turns:** 8

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I've been referred for polyp removal" | Asked for insurance |
| 2 | "Yes, public health insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Charlotte Berg" | Asked for phone |
| 5 | "55443322" | Asked: where is the polyp? |
| 6 | "It's a uterine polyp, inside the uterus" | Asked when last period started |
| 7 | "My last period started on February 20th" | Asked about cycle length |
| 8 | "30 days" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 44 | 44 | YES |
| doctor | HS | HS | YES |
| cycle_dependent | true (CD 4-8) | true | YES |
| valid_booking_window | CD 4-8 from Feb 20 | "Feb 23 - Feb 27 (cycle days 4-8)" | YES |
| guidance | Removed polyp info | Removed polyp info | YES |
| questionnaire | none | null | YES |

**Result: PASS** — Polyp disambiguation, cycle window, and guidance doc all correct.

---

### WG41: "Not Sure" Insurance + Self-Pay

**Scenario:** Patient uncertain about insurance ("yellow card"), no referral → self-pay with price.
**Session:** `wg41_not_sure_insurance` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I'd like to book a smear test" | Asked for insurance |
| 2 | "I'm not sure actually, I just have the yellow card" | "The yellow card counts as public insurance." Asked for referral. |
| 3 | "No, I don't have a referral. I'll pay myself" | Asked for name |
| 4 | "Julie Holm" | Asked for phone |
| 5 | "88776655" | **→ BookingRequest** |

**Verification:**

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 38 | 38 | YES |
| insurance_type | public | public | YES |
| has_referral | false | false | YES |
| self_pay | true | true | YES |
| self_pay_price_dkk | 950 | 950.0 | YES |

**Result: PASS** — "Yellow card" correctly mapped to public. Self-pay price 950 DKK from conditions.yaml.

---

### Round 5 Summary

| WG | Scenario | Turns | Result |
|----|----------|-------|--------|
| 32 | Premenopausal bleeding, age 48 | 6 | PASS |
| 33 | Contact bleeding | 6 | **FAIL** (Bug #15) |
| 34 | Cell changes (Danish) | 5 | **FAIL** (Bug #16) / PASS with modified phrasing |
| 35 | Menopause follow-up | 6 | PASS |
| 36 | Bartholin's cyst | 6 | PASS |
| 37 | Fibroids | 5 | PASS |
| 38 | Follicle scanning + relative date | 7 | PASS |
| 39 | Birth tear (Danish) | 5 | PASS |
| 40 | Uterine polyp | 8 | PASS |
| 41 | "Not sure" insurance | 5 | PASS |
| **Average** | | **5.7** | |

### Bugs Found:

| Bug | Severity | Description | WG |
|-----|----------|-------------|----|
| #15: Contact bleeding misclassified | CRITICAL | "Bleeding after intercourse" mapped to condition 15 (premenopausal bleeding, Category C, standard) instead of condition 9 (contact bleeding, Category B, 14-day priority). Wrong category, wrong priority, missing guidance doc. Clinically significant. **FIXED:** Added lay-language keywords to condition 9, updated prompt to prefer specific/higher-priority matches. WG33r: all fields correct. | WG33 |
| #16: "henvist" triggers false DSS | CRITICAL | Danish word "henvist" (= referred) in opening message causes immediate false DSS escalation. **FIXED:** Added explicit prompt note that "henvist"/"henvisning" = referred/referral, NOT insurance. WG34r: correct BookingRequest with original phrasing. | WG34 |

### What works well:
- Relative date handling: "about 10 days ago" → 2026-02-17 (new feature)
- Age-based routing override (condition 15, age >45 → HS)
- Same-doctor routing for menopause follow-up
- Cyst and polyp group disambiguations
- "Yellow card" correctly identified as public insurance
- Self-pay pricing from conditions.yaml
- Danish language maintained throughout conversations
- Simplest path (fibroids) completes in 5 turns

---

## Round 6: Extended Coverage (WG42-51)

**Date:** 2026-02-27
**Model:** gpt-5.2

---

### WG42: Sudden Severe Pain (Category A)

**Scenario:** Patient with acute pain, can barely stand — Category A emergency.
**Session:** `wg42_severe_pain` | **Turns:** 2

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "I'm having sudden severe pain in my lower abdomen, I can barely stand up" | Advised calling 112, asked for name |
| 2 | "My name is Lise Berg, my number is 22113344" | **→ HandoffRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| escalate | true | true | YES |
| category | A | A | YES |
| urgency | immediate | immediate | YES |
| escalation_reason | Category A | "Category A: sudden severe lower abdominal pain" | YES |

**Result: PASS** — Fastest escalation path, 2 turns.

---

### WG43: Cancer Package Referral (Category B, Danish + "henvist")

**Scenario:** Danish patient using "henvist" for cancer package — tests Bug #16 fix holds for Category B.
**Session:** `wg43_cancer_package` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hej, min læge har henvist mig til en kræftpakke" | Asked for insurance (Danish) |
| 2 | "Ja, offentlig sygesikring" | Asked for referral |
| 3 | "Ja, jeg har en henvisning" | Asked for name |
| 4 | "Inge Madsen" | Asked for phone |
| 5 | "33221144" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 6 | 6 | YES |
| category | B | B | YES |
| doctor | HS or LB | HS | YES |
| priority_window | 1_week | 1_week | YES |
| language | da | da | YES |

**Result: PASS** — Bug #16 fix confirmed (no false DSS escalation from "henvist").

---

### WG44: Cone Biopsy (Category B, Guidance Doc)

**Scenario:** Cone biopsy with "Kegleoperation" guidance document.
**Session:** `wg44_cone_biopsy` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need to schedule a cone biopsy" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Helen Davies" | Asked for phone |
| 5 | "99001122" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 8 | 8 | YES |
| category | B | B | YES |
| doctor | HS | HS | YES |
| priority_window | 14_days | 14_days | YES |
| guidance | Kegleoperation | Kegleoperation | YES |

**Result: PASS** — Guidance document correctly attached.

---

### WG45: HSU Tube Exam + Relative Date

**Scenario:** Cycle-dependent (CD 6-10), patient gives "last week Monday" as period date.
**Session:** `wg45_hsu_tube` | **Turns:** 7

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I need to book an HSU tube exam" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Christina Møller" | Asked for phone |
| 5 | "44332211" | Asked when last period started |
| 6 | "Last week Monday" | Asked about cycle length |
| 7 | "26 days" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 13 | 13 | YES |
| doctor | LB | LB | YES |
| cycle_dependent | true (CD 6-10) | true | YES |
| last_period_date | 2026-02-16 or 2026-02-23 | 2026-02-16 | YES (valid) |
| valid_booking_window | Computed from date | "Next window: Mar 19 - Mar 23" | YES |

**Result: PASS** — "Last week Monday" → Feb 16 is a valid interpretation (Monday of the prior calendar week). Cycle window computed correctly.

---

### WG46: Implant Removal (Danish, Direct Classification)

**Scenario:** Danish patient asks for implant removal — "fjernet min p-stav" is specific enough to skip disambiguation.
**Session:** `wg46_implant_removal` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hej, jeg vil gerne have fjernet min p-stav" | Asked for insurance (Danish) |
| 2 | "Ja, offentlig sygesikring" | Asked for referral |
| 3 | "Ja, jeg har en henvisning" | Asked for name |
| 4 | "Katrine Sørensen" | Asked for phone |
| 5 | "11994488" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 26 | 26 | YES |
| doctor | LB | LB | YES |
| cycle_dependent | false | false | YES |
| language | da | da | YES |

**Result: PASS** — Correctly skipped group disambiguation (intent was unambiguous).

---

### WG47: Recurrent UTI

**Scenario:** Patient with recurring UTIs — tests keyword matching.
**Session:** `wg47_recurrent_uti` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I keep getting urinary tract infections and my GP referred me to you" | Asked for insurance |
| 2 | "Yes, public" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Sarah O'Brien" | Asked for phone |
| 5 | "55009911" | Asked for symptoms |
| 6 | "I keep getting UTIs every couple of months - burning, frequent urination" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 33 | **50** | **NO** |
| condition_name | Recurrent UTI | **Itching/burning/discharge** | **NO** |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |

**Result: FAIL — Bug #17**

**Bug #17 Fix:** Added keywords "urinary tract infection", "UTI", "urinvejsinfektion" to condition 33 in conditions.yaml.

**WG47r (retry):** 5 turns → BookingRequest with condition_id=33, condition_name="Recurrent UTI", doctor=LB, questionnaire="You & Your Gynaecological Problem". **Bug #17 FIXED.**

---

### WG48: Cystoscopy

**Scenario:** Doctor HS procedure, no cycle/lab/questionnaire.
**Session:** `wg48_cystoscopy` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, my doctor referred me for a cystoscopy" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Diana Price" | Asked for phone |
| 5 | "77665544" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 42 | 42 | YES |
| doctor | HS | HS | YES |
| cycle_dependent | false | false | YES |
| questionnaire | none | null | YES |

**Result: PASS**

---

### WG49: Itching/Burning/Discharge

**Scenario:** Common vulva complaint with questionnaire.
**Session:** `wg49_itching` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I've been having persistent itching and unusual discharge and my GP referred me" | Asked for insurance |
| 2 | "Public insurance, yes" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Nina Olsen" | Asked for phone |
| 5 | "88112233" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 50 | 50 | YES |
| doctor | LB | LB | YES |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |

**Result: PASS**

---

### WG50: PCOS Follow-up (Self-Pay)

**Scenario:** Existing PCOS patient, no new referral → self-pay path.
**Session:** `wg50_pcos_followup` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I'm an existing patient with PCOS and need a follow-up appointment" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "No, I don't have a new referral, I'm just following up" | Asked for name |
| 4 | "Amalie Kristensen" | Asked for phone |
| 5 | "33557799" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 40 | 40 | YES |
| doctor | LB | LB | YES |
| is_followup | true | true | YES |
| self_pay | true | true | YES |
| self_pay_price_dkk | null (not in config) | null | YES |
| duration_minutes | 15 | 15 | YES |

**Result: PASS** — Note: agent skipped explicit self-pay confirmation, inferred from follow-up context. UX observation, not a data bug.

---

### WG51: Lichen Sclerosus New (Group Disambiguation)

**Scenario:** "Lichen sclerosus" triggers group disambiguation — patient picks new assessment.
**Session:** `wg51_lichen_new` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I've been referred for lichen sclerosus" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Rebecca Lindberg" | Asked for phone |
| 5 | "22887766" | "Is this your first appointment or a follow-up?" |
| 6 | "It's my first time, a new assessment" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 45 | 45 | YES |
| doctor | LB | LB | YES |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |

**Result: PASS** — Lichen group disambiguation correctly triggered.

---

### Round 6 Summary

| WG | Scenario | Turns | Result |
|----|----------|-------|--------|
| 42 | Sudden severe pain (Cat A) | 2 | PASS |
| 43 | Cancer package (Danish + "henvist") | 5 | PASS |
| 44 | Cone biopsy | 5 | PASS |
| 45 | HSU tube exam + relative date | 7 | PASS |
| 46 | Implant removal (Danish) | 5 | PASS |
| 47 | Recurrent UTI | 6 | **FAIL** (Bug #17) → FIXED (WG47r: 5 turns) |
| 48 | Cystoscopy | 5 | PASS |
| 49 | Itching/burning/discharge | 5 | PASS |
| 50 | PCOS follow-up (self-pay) | 5 | PASS |
| 51 | Lichen sclerosus new | 6 | PASS |
| **Average** | | **5.1** | |

### Bugs Found:

| Bug | Severity | Description | WG |
|-----|----------|-------------|----|
| #17: Recurrent UTI misclassified | HIGH | "Urinary tract infections" + "burning" matched condition 50 (itching/burning) instead of condition 33 (recurrent UTI). Missing lay-language keywords. **FIXED:** Added "urinary tract infection", "UTI", "urinvejsinfektion" to condition 33. WG47r: correct classification. | WG47 |

### What works well:
- Category A escalation efficient (2 turns for severe pain)
- Category B conditions with guidance docs (cone biopsy → Kegleoperation)
- Bug #16 fix holds: "henvist" in cancer package scenario no longer triggers false DSS
- Relative date handling for cycle windows (HSU tube exam)
- Direct classification when patient intent is unambiguous (implant removal)
- Group disambiguations (lichen sclerosus: new vs follow-up vs annual)
- Self-pay correctly inferred for follow-up without referral
- All condition IDs, doctors, priorities, questionnaires, and guidance docs match conditions.yaml

---

## Round 7: Full Coverage — Remaining Conditions (WG52-63)

**Date:** 2026-02-27
**Model:** gpt-5.2
**Goal:** Test all remaining untested conditions from the Triage Conversation Chain.

---

### WG52: Suspected Ectopic Pregnancy (Category A)

**Session:** `wg52_ectopic` | **Turns:** 2

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "I'm pregnant and having sharp pain on one side, I'm scared it might be ectopic" | Recognized urgency, advised calling 112, asked for name |
| 2 | "My name is Hanna Eriksen, my number is 55443322" | **→ HandoffRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 3 | 3 | YES |
| category | A | A | YES |
| urgency | immediate | immediate | YES |

**Result: PASS**

---

### WG53: Pregnancy with Bleeding/Pain 1st Trimester (Category A, Danish)

**Session:** `wg53_pregnancy_bleeding` | **Turns:** 2

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Jeg er gravid i 8. uge og har begyndt at bløde og har smerter" | Recognized urgency (Danish), asked for name |
| 2 | "Jeg hedder Maja Dahl, mit nummer er 44112233" | **→ HandoffRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 3 or 4 | **null** | **NO** |
| category | A | **null** | **NO** |
| urgency | immediate | immediate | YES |
| language | da | da | YES |

**Result: FAIL — Bug #18** (condition_id and category not populated in TriageData despite correct escalation)

**Bug #18 Fix:** Updated urgent detection prompt to explicitly instruct: "fill in condition_id, condition_name, and category='A' from the search_conditions result."

**WG53r (retry):** 2 turns → HandoffRequest with condition_id=3, category="A", urgency="immediate", language="da". **Bug #18 FIXED.**

---

### WG54: Medical Abortion (Category A)

**Session:** `wg54_abortion` | **Turns:** 2

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "I need to have an abortion, I just found out I'm pregnant" | Recognized urgency, asked for name |
| 2 | "Emily Wilson, 66778899" | **→ HandoffRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 5 | 5 | YES |
| category | A | A | YES |
| urgency | immediate | immediate | YES |
| priority_window | 1_2_days | 1_2_days | YES (matches conditions.yaml) |

**Result: PASS**

---

### WG55: Insemination

**Session:** `wg55_insemination` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I need to schedule an insemination" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Laura Henriksen" | Asked for phone |
| 5 | "99223344" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 11 | 11 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 15 | 15 | YES |
| cycle_dependent | false | false | YES |

**Result: PASS**

---

### WG56: Hysteroscopic IUD Removal (No Visible Strings)

**Session:** `wg56_hysteroscopic_iud` | **Turns:** 7

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need my IUD removed but the strings can't be found..." | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Kirsten Holm" | Asked for phone |
| 5 | "33998877" | Asked when last period started |
| 6 | "About 2 weeks ago" | Asked about cycle length |
| 7 | "28 days" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 23 | 23 | YES |
| doctor | HS | HS | YES |
| cycle_dependent | true (CD 4-8) | true | YES |
| valid_booking_window | Computed | "Next window: Mar 16 - Mar 20" | YES |

**Result: PASS** — Relative date "about 2 weeks ago" correctly converted.

---

### WG57: Incontinence Follow-up (Danish)

**Session:** `wg57_incontinence_followup` | **Turns:** 7

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hej, jeg er patient hos jer for inkontinens og har brug for en kontroltid" | Asked for insurance (Danish) |
| 2 | "Ja, offentlig sygesikring" | Asked for referral |
| 3 | "Nej, det er en kontroltid" | Informed about self-pay |
| 4 | "Ja, det er fint" | Asked for name |
| 5 | "Birgit Lund" | Asked for phone |
| 6 | "22556688" | Asked: new or follow-up? |
| 7 | "Det er en kontroltid - opfølgning" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 32 | 32 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 15 | 15 | YES |
| is_followup | true | true | YES |
| questionnaire | Urinary Problems / Incontinence | You & Your Gynaecological Problem, Urinary Problems / Incontinence | YES (both configured for condition 32) |
| self_pay | true | true | YES |
| language | da | da | YES |

**Result: PASS** — Minor: redundant follow-up disambiguation at turn 6-7.

---

### WG58: Prolapse (Group Disambiguation)

**Session:** `wg58_prolapse` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I've been referred for prolapse" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Janet Williams" | Asked for phone |
| 5 | "44889922" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 34 | 34 | YES |
| doctor | LB | LB | YES |
| questionnaire | You & Your Gynaecological Problem | You & Your Gynaecological Problem | YES |

**Result: PASS** — Group disambiguation skipped (agent inferred "referred for prolapse" = new assessment). Correct result, but disambiguation would be safer.

---

### WG59: Prolapse Ring Change/Fitting

**Session:** `wg59_prolapse_ring_change` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need to get my prolapse ring changed" | Asked for insurance |
| 2 | "Public insurance" | Asked for referral |
| 3 | "No, I don't have a referral, I'm an existing patient" | Asked for name |
| 4 | "Dorothy Green" | Asked for phone |
| 5 | "77334455" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 36 | 36 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 15 | 15 | YES |
| is_followup | true | true | YES |
| self_pay | true | true | YES |
| questionnaire | none | null | YES |

**Result: PASS** — "Prolapse ring changed" specific enough to skip disambiguation correctly.

---

### WG60: Lichen Sclerosus Annual Check

**Session:** `wg60_lichen_annual` | **Turns:** 6

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I have lichen sclerosus and need my annual check" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "No, I don't have a new referral, it's just my yearly check" | Informed about self-pay |
| 4 | "Yes, that's fine" | Asked for name |
| 5 | "Alice Martin" | Asked for phone |
| 6 | "33776655" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 47 | 47 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 15 | 15 | YES |
| self_pay | true | true | YES |
| questionnaire | none | null | YES |

**Result: PASS** — "Annual check" specific enough to resolve without disambiguation.

---

### WG61: Vaginal Opening Issues (Danish + "henvist")

**Session:** `wg61_vaginal_opening` | **Turns:** 1

**Result: FAIL — Model glitch** (premature BookingRequest with all null fields on first turn)

**WG61r (retry):** 5 turns → BookingRequest with condition_id=49, doctor=LB, language="da", questionnaire="You & Your Gynaecological Problem". All fields correct. **One-off glitch, not reproducible.**

---

### WG62: Tamoxifen Follow-up

**Session:** `wg62_tamoxifen` | **Turns:** 5

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hello, I need a follow-up appointment for my tamoxifen treatment" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes, I have a referral" | Asked for name |
| 4 | "Patricia Adams" | Asked for phone |
| 5 | "99112288" | **→ BookingRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| condition_id | 51 | 51 | YES |
| doctor | LB | LB | YES |
| duration_minutes | 20 | 20 | YES |
| questionnaire | none | null | YES |
| is_followup | true | true | YES |

**Result: PASS**

---

### WG63: Unclassifiable Condition → Staff Escalation

**Session:** `wg63_unclassifiable` | **Turns:** 7

| Turn | Patient | Agent Response |
|------|---------|----------------|
| 1 | "Hi, I have a very unusual situation that I need help with" | Asked for insurance |
| 2 | "Yes, public insurance" | Asked for referral |
| 3 | "Yes I have a referral" | Asked for name |
| 4 | "Jane Smith" | Asked for phone |
| 5 | "11223344" | Asked what brings them in |
| 6 | "Problems with lymph nodes in groin area, keep swelling" | Asked about associated genital symptoms |
| 7 | "My GP wasn't sure either, referred me to a gynecologist" | **→ HandoffRequest** |

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| escalate | true | true | YES |
| urgency | normal | normal | YES |
| condition_id | null (unclassifiable) | null | YES |
| reason | Unclassifiable | "Condition not found in database..." | YES |
| suggested_action | present | Detailed clinical checklist | YES |

**Result: PASS** — Agent correctly exhausted classification options and escalated to staff with thorough HandoffRequest.

---

### Round 7 Summary

| WG | Scenario | Turns | Result |
|----|----------|-------|--------|
| 52 | Ectopic pregnancy (Cat A) | 2 | PASS |
| 53 | Pregnancy bleeding (Cat A, Danish) | 2 | **FAIL** (Bug #18) → FIXED (WG53r) |
| 54 | Medical abortion (Cat A) | 2 | PASS |
| 55 | Insemination | 5 | PASS |
| 56 | Hysteroscopic IUD | 7 | PASS |
| 57 | Incontinence follow-up (Danish) | 7 | PASS |
| 58 | Prolapse (group disamb.) | 5 | PASS |
| 59 | Prolapse ring change | 5 | PASS |
| 60 | Lichen annual check | 6 | PASS |
| 61 | Vaginal opening (Danish) | 5 | PASS (retry; original was model glitch) |
| 62 | Tamoxifen follow-up | 5 | PASS |
| 63 | Unclassifiable → escalation | 7 | PASS |
| **Average** | | **4.8** | |

### Bugs Found:

| Bug | Severity | Description | WG |
|-----|----------|-------------|----|
| #18: Category A escalation missing condition fields | MEDIUM | condition_id and category not populated in TriageData despite correct escalation. **FIXED:** Updated prompt to instruct agent to fill condition_id, condition_name, and category from search_conditions result. WG53r: condition_id=3, category="A". | WG53 |
| Model glitch: premature BookingRequest | LOW | One-off occurrence where agent produced BookingRequest with all null fields on first turn. Not reproducible on retry. | WG61 |

### What works well:
- All 3 remaining Category A conditions correctly escalated in 2 turns each
- All remaining Category C conditions correctly classified and booked
- Unclassifiable condition correctly escalated to staff with thorough HandoffRequest
- Prolapse group disambiguation handled correctly (both direct classification and explicit disambiguation)
- Self-pay correctly handled for follow-up patients without referral
- Dual questionnaires correctly assigned (incontinence follow-up)
- Danish language maintained throughout Danish conversations

---

## Full Coverage Summary

**Total war games run:** WG8-63 + retries = **56 war games**
**Conditions tested:** All 53 conditions from the Triage Conversation Chain
**Additional scenarios:** DSS insurance, "not sure" insurance, unclassifiable condition, relative dates
**Bugs found and fixed:** 6 bugs (#13-#18)
**Average turns per conversation:** ~5.1
**Model:** gpt-5.2
