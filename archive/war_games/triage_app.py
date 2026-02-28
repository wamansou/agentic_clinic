#!/usr/bin/env python3
"""
Kvinde Klinikken AI Triage — v2 Architecture
Single conversation agent + Python orchestrator. No LLM-based dispatcher.

Usage:
    python triage_app.py                    # interactive mode
    python triage_app.py --session <name>   # named session
"""

import os
import sys
import yaml
import json
import asyncio
from datetime import date, datetime, timedelta
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

# Add parent dir to path so we can find conditions.yaml
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
os.chdir(PROJECT_DIR)

load_dotenv()

MODEL = os.getenv("TRIAGE_MODEL", "gpt-4o")


# =============================================================================
# Pydantic Models
# =============================================================================

class TriageData(BaseModel):
    """Data collected by the conversation agent from the patient."""
    # Always filled
    language: str = "en"
    escalate: bool = False
    escalation_reason: str | None = None
    # Intake
    patient_name: str | None = None
    phone_number: str | None = None
    insurance_type: str | None = None  # "public", "dss"
    has_referral: bool | None = None
    is_followup: bool = False
    # Clinical
    condition_id: int | None = None
    condition_name: str | None = None
    category: str | None = None
    doctor: str | None = None
    duration_minutes: int | None = None
    priority_window: str | None = None
    patient_age: int | None = None
    # Cycle info (only for cycle-dependent procedures)
    last_period_date: str | None = None  # YYYY-MM-DD
    cycle_length: int | None = None
    no_periods: bool = False


class BookingRequest(BaseModel):
    """Final staged output — everything the clinic needs to call the patient."""
    # From TriageData
    triage: TriageData
    # Computed by Python
    cycle_dependent: bool = False
    valid_booking_window: str | None = None
    provera_recommended: bool = False
    lab_required: bool = False
    lab_details: str | None = None
    questionnaire: str | None = None
    partner_questionnaire: str | None = None
    guidance_document: str | None = None
    self_pay: bool = False
    self_pay_price_dkk: float | None = None
    notes: str | None = None


class HandoffRequest(BaseModel):
    """For staff escalation — urgent, DSS, or patient request."""
    triage: TriageData
    reason: str
    urgency: str  # "immediate", "high", "normal"
    conversation_summary: str
    suggested_action: str | None = None


# =============================================================================
# Load YAML Config
# =============================================================================

with open("conditions.yaml") as f:
    CONFIG = yaml.safe_load(f)

CONDITIONS = {c["id"]: c for c in CONFIG["conditions"]}
GROUPS = CONFIG["condition_groups"]


# =============================================================================
# Build Condition Reference (injected into agent prompt)
# =============================================================================

def _build_condition_reference() -> str:
    """Generate a compact reference table of all conditions and groups for the LLM prompt."""
    lines = ["=== CONDITION REFERENCE ==="]

    # Group conditions by category
    cat_labels = {
        "A": "CATEGORY A (Urgent — escalate to staff)",
        "B": "CATEGORY B (Semi-urgent — book within 1-2 weeks)",
        "C": "CATEGORY C (Standard)",
    }
    by_cat: dict[str, list] = {"A": [], "B": [], "C": []}
    for cond in CONFIG["conditions"]:
        by_cat[cond["category"]].append(cond)

    for cat in ("A", "B", "C"):
        lines.append(f"\n--- {cat_labels[cat]} ---")
        for c in by_cat[cat]:
            desc = c.get("description", c["name"])
            lines.append(f"  [{c['id']}] {c['name']}: {desc}")

    # Condition groups
    lines.append("\n=== CONDITION GROUPS (ask clarifying question before assigning) ===")
    for group in GROUPS:
        desc = group.get("description", "")
        lines.append(f"\n  GROUP: {group['group']} — {desc}")
        lines.append(f"  Ask: \"{group['clarifying_question']}\"")
        for opt in group["options"]:
            lines.append(f"    - {opt['label']} → condition [{opt['condition_id']}]")

    return "\n".join(lines)


CONDITION_REFERENCE = _build_condition_reference()


# =============================================================================
# Raw Tool Functions (deterministic Python — unchanged from v1)
# =============================================================================

def get_condition_details(condition_id: int) -> str:
    cond = CONDITIONS.get(condition_id)
    if not cond:
        return json.dumps({"error": f"Condition {condition_id} not found"})
    return json.dumps(cond, indent=2, ensure_ascii=False)


def calculate_cycle_window(
    last_period_date: str,
    condition_id: int,
    cycle_length: int = 28,
    cycle_range_min: int | None = None,
    cycle_range_max: int | None = None,
    no_cycle: bool = False,
) -> str:
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

    window_start = lp + timedelta(days=cd_start - 1)
    window_end = lp + timedelta(days=cd_end - 1)

    if window_end < today:
        if cycle_range_min and cycle_range_max:
            next_lp_earliest = lp + timedelta(days=cycle_range_min)
            next_lp_latest = lp + timedelta(days=cycle_range_max)
            next_start = next_lp_earliest + timedelta(days=cd_start - 1)
            next_end = next_lp_latest + timedelta(days=cd_end - 1)
            msg = f"This cycle's window has passed. Next window (approximate due to irregular cycle): {next_start.strftime('%b %d')} - {next_end.strftime('%b %d')}"
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


def get_lab_requirements(condition_id: int, patient_age: int | None = None) -> str:
    cond = CONDITIONS.get(condition_id)
    if not cond or not cond.get("lab"):
        return json.dumps({"lab_required": False})

    lab = cond["lab"]
    lab_condition = lab.get("condition", "always")

    if lab_condition == "age_under_30" and patient_age is not None and patient_age >= 30:
        return json.dumps({"lab_required": False, "reason": "Patient is 30 or older, lab not required."})

    if lab_condition == "age_under_45" and patient_age is not None and patient_age >= 45:
        return json.dumps({"lab_required": False, "reason": "Patient is 45 or older, lab not required."})

    return json.dumps({
        "lab_required": True,
        "test": lab.get("test") or lab.get("tests"),
        "description": lab["description"],
    }, ensure_ascii=False)


def get_questionnaire(condition_id: int) -> str:
    cond = CONDITIONS.get(condition_id)
    if not cond:
        return json.dumps({"questionnaires": [], "message": "Condition not found."})

    result = {"questionnaires": []}
    if cond.get("questionnaires"):
        result["questionnaires"] = [{"name": q} for q in cond["questionnaires"]]
    if cond.get("partner_questionnaire"):
        result["partner_questionnaire"] = cond["partner_questionnaire"]
    if not result["questionnaires"]:
        result["message"] = "No questionnaire required for this condition."
    return json.dumps(result, ensure_ascii=False)


def get_guidance_document(condition_id: int) -> str:
    cond = CONDITIONS.get(condition_id)
    if cond and cond.get("guidance_document"):
        return json.dumps({"document": cond["guidance_document"]})
    return json.dumps({"document": None, "message": "No guidance document for this condition."})


def get_self_pay_price(condition_id: int) -> str:
    cond = CONDITIONS.get(condition_id)
    if cond and cond.get("self_pay_price_dkk"):
        return json.dumps({"condition_id": condition_id, "name": cond["name"], "price_dkk": cond["self_pay_price_dkk"]}, ensure_ascii=False)
    return json.dumps({"price_dkk": None, "message": "Price not yet available. Staff will confirm the cost."})


# =============================================================================
# Agent SDK Setup
# =============================================================================

from agents import Agent, Runner, SQLiteSession, ModelSettings, function_tool
from agents.agent import ToolsToFinalOutputResult
from agents.tool import FunctionToolResult


# --- Agent tools (details + complete) ---

@function_tool
def fetch_condition_details(condition_id: int) -> str:
    """Get full details for a specific condition including doctor, duration, priority, cycle requirements, lab requirements, and routing questions."""
    return get_condition_details(condition_id)


@function_tool
def complete_triage(data: TriageData) -> str:
    """Call this when you have collected all required information from the patient.
    Fill in ALL fields you have gathered. For escalations, set escalate=true and provide escalation_reason."""
    # Validation: non-escalation cases must have condition_id and doctor
    if not data.escalate:
        if data.condition_id is None:
            return (
                "ERROR: condition_id is required for non-escalation bookings. "
                "You MUST identify the condition from the CONDITION REFERENCE in your prompt, "
                "then call fetch_condition_details() to get routing info. "
                "Do NOT call complete_triage until you have condition_id."
            )
        if data.doctor is None:
            return (
                "ERROR: doctor is required. Call fetch_condition_details() with the "
                "condition_id to get the default doctor. If the condition has a "
                "routing_question, ask it first to determine the correct doctor (HS or LB)."
            )
    return data.model_dump_json()


def _validate_complete_triage(
    context, tool_results: list[FunctionToolResult]
) -> ToolsToFinalOutputResult:
    """Custom tool_use_behavior: validates complete_triage output before stopping.
    If validation fails (ERROR prefix), lets the agent continue to fix it."""
    for result in tool_results:
        if result.tool.name == "complete_triage":
            output = result.output
            if isinstance(output, str) and output.startswith("ERROR:"):
                # Validation failed — agent sees the error and retries
                return ToolsToFinalOutputResult(is_final_output=False)
            # Valid output — stop and return to orchestrator
            return ToolsToFinalOutputResult(
                is_final_output=True, final_output=output
            )
    # No complete_triage called — agent continues normally
    return ToolsToFinalOutputResult(is_final_output=False)


# =============================================================================
# Agent Definitions
# =============================================================================

_TODAY = date.today()
_TODAY_ISO = _TODAY.strftime("%Y-%m-%d")
_TODAY_READABLE = _TODAY.strftime("%A, %B %d, %Y")

TRIAGE_INSTRUCTIONS = f"""You are the AI triage assistant for Kvinde Klinikken, a Danish gynecology clinic.
You handle the ENTIRE patient conversation — from greeting to final data collection.

=== LANGUAGE DETECTION ===
Detect from the patient's WORDS (not names or context):
- English words ("Hi", "Hello", "I have") → respond in English
- Danish words ("Hej", "Jeg har", "Jeg skal") → respond in Danish
- Ukrainian → respond in Ukrainian
- SHORT/AMBIGUOUS messages ("hi", "hello", "hey", "ok") → DEFAULT TO ENGLISH
  "hi" is English. Do NOT assume Danish for short greetings.
- If the patient later writes in Danish, switch from that point on.

=== INSURANCE CLASSIFICATION — CRITICAL ===
- "offentlig sygesikring" / "det gule kort" / "offentlig forsikring" / "public insurance" / "sygesikring" = PUBLIC (insurance_type="public") → continue triage
- "Dansk Sundhedssikring" / "DSS" / "privat forsikring" / "private insurance" = DSS (insurance_type="dss") → escalate immediately
Do NOT confuse "offentlig sygesikring" (public) with DSS. They are completely different.
Self-pay is NOT an insurance type — it depends on whether the patient has a referral (asked later).
IMPORTANT: "henvist" / "henvisning" means "referred" / "referral" in Danish — this is about referral status, NOT insurance. Do NOT classify a patient as DSS just because they mention being referred. Always ASK the insurance question explicitly.

=== URGENT DETECTION — CHECK FIRST ===
BEFORE starting the normal flow, check the patient's FIRST or CURRENT message for signs of a Category A medical emergency:
- ACTIVE heavy bleeding RIGHT NOW — hemorrhage, soaking through pads, can't stop the bleeding
- Sudden severe pain — can't stand up, worst pain of their life, acute onset
- Suspected ectopic pregnancy — pregnant with pain and/or bleeding
- Pregnancy with bleeding/pain (1st trimester)
- Abortion request

IMPORTANT: Only escalate for ACUTE, HAPPENING-NOW emergencies (Category A).
Do NOT escalate for:
- Postmenopausal bleeding (a woman past menopause who has started bleeding again) — this is Category B, handle through normal booking
- Chronic or recurring bleeding patterns — this is Category C, handle through normal booking
- Bleeding that started days/weeks ago and is not currently heavy/acute — handle through normal booking

If the patient describes a TRUE Category A emergency → identify the Category A condition from the CONDITION REFERENCE below → tell them empathetically this needs urgent attention and that a staff member will contact them very soon. Then ask for their name and phone number (you can ask both in one message for urgency). Once you have name + phone, call complete_triage with escalate=true, escalation_reason="Category A: [condition]", AND fill in condition_id, condition_name, and category="A". Skip insurance, referral, and all other intake steps — just name and phone.

=== CONVERSATION FLOW ===
For NON-URGENT cases, collect information in this order. Ask ONE question at a time. Skip items the patient already provided.

1. INSURANCE TYPE — Ask: "Do you have public health insurance (sygesikring)?"
   - If they say yes / public / offentlig → insurance_type="public"
   - If DSS / private insurance → set escalate=true, escalation_reason="DSS/private insurance requires staff handling" → call complete_triage immediately

2. REFERRAL STATUS — "Do you have a referral from your GP?"
   - If no referral → let them know: "Without a referral, the visit would be self-pay (you pay privately). Would you like to proceed?"
   - If yes they proceed → set has_referral=false, continue normally. The system will calculate self-pay pricing.
   - If the patient mentions they're a follow-up / existing patient / kontrol → set is_followup=true, but still note has_referral=false

3. PATIENT NAME — "Could I have your name, please?"

4. PHONE NUMBER — "And a phone number where we can reach you?"

5. CONDITION — "What brings you in today?"
   - Match the patient's description against the CONDITION REFERENCE below.
   - Check CONDITION GROUPS first. If the description matches a group, ask the clarifying question to narrow down to a specific condition ID.
   - If it clearly matches a single condition, note the ID.
   - If you cannot determine a clear match, ask ONE clarifying question.
   - If the patient's symptoms still don't match any condition after clarification, do NOT force a match. Instead, set escalate=true with escalation_reason="Condition not found in database — requires staff review" and call complete_triage.
   - IMPORTANT: If the patient mentions BOTH bleeding AND menopause/overgangsalder (especially age >50), this is postmenopausal bleeding [7] (Category B), NOT regular menopause [29].
   - If the patient is PREGNANT and has bleeding/pain, this is Category A (condition [4]), NOT premenopausal bleeding [15].
   - If Category A → empathize, escalate, skip remaining steps.
   - Once you have a condition_id → call fetch_condition_details(condition_id) to get routing info.

6. ROUTING FOLLOW-UPS — Only if the condition has a routing_question:
   - Condition 15 (premenopausal bleeding): ask age → age >45: doctor="HS", age ≤45: doctor="LB"
   - Conditions 20, 21 (IUD removal/replacement): ask about string visibility → not visible: doctor="HS"; visible: doctor="LB"
   - Condition 29 (menopause new): "Have you been seen by Dr. Skensved before?" → yes: doctor="HS"; no: doctor="LB"
   - Condition 30 (menopause follow-up): "Which doctor did you see last time?" → route to same doctor
   - Condition 52 (second opinion): "Is this related to fertility?" → yes: doctor="LB"; no: doctor="HS"
   - If no routing_question → use the condition's default doctor

7. CYCLE INFO — Only if the condition has cycle_days (check from fetch_condition_details result):
   - Ask: "When did your last period start?"
   - The patient may answer with a relative expression like "about a week ago", "last Monday", "10 days ago", "on the 15th".
     Convert their answer to YYYY-MM-DD using today's date (see TODAY'S DATE section at the end). Do NOT ask the patient to restate in a specific format.
   - Ask: "How long is your cycle usually?" (default 28 if patient unsure)
   - If patient mentions no periods / amenorrhea / PCOS → set no_periods=true

=== MANDATORY TOOL USAGE — CRITICAL ===
NEVER produce a text summary of the booking. NEVER tell the patient "I've registered your appointment" or "I'll arrange your booking" in text. Your ONLY way to complete the conversation is by calling complete_triage(). If you have enough information, CALL THE TOOL — do not describe what you would do.

You MUST follow these steps in order:
1. Identify condition from the CONDITION REFERENCE below (no tool needed — use your reasoning to match the patient's description)
2. IMMEDIATELY call fetch_condition_details(condition_id) — to get doctor, duration, priority, cycle_days, routing_question (REQUIRED after identifying condition)
3. Ask any routing/cycle follow-up questions if needed (based on the fetch_condition_details result)
4. IMMEDIATELY call complete_triage() with ALL collected data — this is the ONLY way to finish

NEVER call complete_triage with condition_id=null or doctor=null for non-escalation cases. The system will reject it.

=== WHEN DONE ===
As soon as you have all required info, IMMEDIATELY call complete_triage(). Do NOT send the patient a text message summarizing the booking — the system handles confirmation separately.

Fill in ALL fields you have gathered:
- language, insurance_type, has_referral, patient_name, phone_number
- condition_id, condition_name, category, doctor, duration_minutes, priority_window
- patient_age (only if asked/provided), last_period_date, cycle_length, no_periods
- is_followup (true if patient mentioned follow-up)
- escalate=false for normal flow

=== ESCAPE HATCH ===
If the patient's CURRENT message (not older messages) says "speak to staff" / "talk to a person" / "I want a human":
→ Call complete_triage with escalate=true, escalation_reason="Patient requested staff"
IGNORE older messages with similar phrases — only the current message triggers this.

=== RULES ===
- ONE question at a time — never multiple questions in one message
- Natural conversation — no numbered lists, no bullet points
- Empathetic and professional tone
- Never re-ask information already provided
- Store all dates in YYYY-MM-DD format in complete_triage output (but accept natural language dates from patients — convert them yourself)
- Do NOT ask for doctor preference during intake — only ask routing questions when the condition requires it
- Do NOT ask for age unless the condition's routing_question requires it
- Do NOT ask for cycle info unless the condition has cycle_days
- NEVER produce a text response when you have enough data to call a tool — always prefer calling fetch_condition_details() or complete_triage() over sending text
- NEVER say "I've registered/arranged/booked your appointment" — only complete_triage() does that

""" + CONDITION_REFERENCE + f"""

=== TODAY'S DATE ===
Today is {_TODAY_READABLE} ({_TODAY_ISO}).
Use this to convert relative dates from patients (e.g. "about a week ago", "last Monday") to YYYY-MM-DD format.
"""

triage_agent = Agent(
    name="Triage",
    model=MODEL,
    instructions=TRIAGE_INSTRUCTIONS,
    tools=[fetch_condition_details, complete_triage],
    tool_use_behavior=_validate_complete_triage,
    model_settings=ModelSettings(prompt_cache_retention="24h"),
)


# --- Staff Handoff Agent (produces structured HandoffRequest) ---

handoff_agent = Agent(
    name="Staff Handoff",
    model=MODEL,
    instructions="""You are summarizing a patient conversation for clinic staff at Kvinde Klinikken.

Read the FULL conversation and the triage data provided. Produce a HandoffRequest with:
- triage: The TriageData passed to you (parse from the input)
- reason: Clear explanation of why the patient needs human staff
- urgency: "immediate" for Category A / acute emergencies, "high" for Category B, "normal" for everything else (DSS, patient request, unclear condition)
- conversation_summary: Brief summary of what was discussed and what stage the conversation reached
- suggested_action: What the staff member should do next

Be thorough — the staff member has NOT read the chat.""",
    output_type=HandoffRequest,
)


# --- Confirmation Agent (produces patient-facing summary) ---

confirmation_agent = Agent(
    name="Confirmation",
    model=MODEL,
    instructions="""You are sending a confirmation message to a patient at Kvinde Klinikken.
You have just finished collecting their information for a gynecology appointment.

Write a warm, professional confirmation in the patient's language. Include:
- Thank them by name
- Confirm their condition/reason for visit (in patient-friendly terms, not medical codes)
- Mention the assigned doctor (Dr. Skensved for "HS", Dr. Bech for "LB")
- If there's a questionnaire to complete, mention it
- If there are lab requirements, remind them
- If cycle-dependent, mention the approximate timing window
- Let them know the clinic will call them at their phone number to confirm the appointment
- Keep it concise — 3-5 sentences max

Do NOT mention condition IDs, category codes, or internal system details.
Use the same language the patient has been writing in.""",
)


# =============================================================================
# Python Orchestrator
# =============================================================================

def _parse_triage_data(raw_output) -> TriageData:
    """Parse TriageData from agent's complete_triage tool output."""
    if isinstance(raw_output, TriageData):
        return raw_output
    if isinstance(raw_output, str):
        return TriageData.model_validate_json(raw_output)
    if isinstance(raw_output, dict):
        return TriageData.model_validate(raw_output)
    raise ValueError(f"Cannot parse TriageData from {type(raw_output)}: {raw_output}")


def _enrich_booking(triage: TriageData) -> BookingRequest:
    """Deterministic enrichment — no LLM calls. Computes cycle, lab, questionnaire, etc."""
    booking = BookingRequest(triage=triage)

    if not triage.condition_id:
        return booking

    cond = CONDITIONS.get(triage.condition_id)
    if not cond:
        return booking

    # Cycle window
    if cond.get("cycle_days"):
        booking.cycle_dependent = True
        if triage.no_periods:
            booking.provera_recommended = True
            booking.notes = "Patient has no regular cycle. Doctor may prescribe Provera to induce a period."
        elif triage.last_period_date:
            cycle_result = json.loads(calculate_cycle_window(
                triage.last_period_date,
                triage.condition_id,
                triage.cycle_length or 28,
            ))
            booking.valid_booking_window = cycle_result.get("message")
            booking.provera_recommended = cycle_result.get("provera_recommended", False)

    # Lab requirements
    lab_result = json.loads(get_lab_requirements(triage.condition_id, triage.patient_age))
    booking.lab_required = lab_result.get("lab_required", False)
    if booking.lab_required:
        test = lab_result.get("test") or lab_result.get("tests")
        desc = lab_result.get("description", "")
        if isinstance(test, list):
            booking.lab_details = f"{', '.join(test)}. {desc}"
        else:
            booking.lab_details = f"{test}. {desc}" if test else desc

    # Questionnaire
    q_result = json.loads(get_questionnaire(triage.condition_id))
    if q_result.get("questionnaires"):
        booking.questionnaire = ", ".join(q["name"] for q in q_result["questionnaires"])
    if q_result.get("partner_questionnaire"):
        booking.partner_questionnaire = q_result["partner_questionnaire"]

    # Guidance document
    g_result = json.loads(get_guidance_document(triage.condition_id))
    if g_result.get("document"):
        booking.guidance_document = g_result["document"]

    # Self-pay: no referral = patient pays privately
    if triage.has_referral is False:
        booking.self_pay = True
        price_result = json.loads(get_self_pay_price(triage.condition_id))
        if price_result.get("price_dkk"):
            booking.self_pay_price_dkk = price_result["price_dkk"]

    return booking


def _build_confirmation_context(triage: TriageData, booking: BookingRequest) -> str:
    """Build a context string for the confirmation agent."""
    parts = [f"Patient language: {triage.language}"]
    if triage.patient_name:
        parts.append(f"Patient name: {triage.patient_name}")
    if triage.phone_number:
        parts.append(f"Phone: {triage.phone_number}")

    if triage.condition_name:
        parts.append(f"Condition: {triage.condition_name}")
    if triage.doctor:
        doctor_name = "Dr. Skensved" if triage.doctor == "HS" else "Dr. Bech"
        parts.append(f"Doctor: {doctor_name}")
    if booking.cycle_dependent and booking.valid_booking_window:
        parts.append(f"Timing: {booking.valid_booking_window}")
    if booking.provera_recommended:
        parts.append("Provera may be prescribed to induce a period.")
    if booking.lab_required:
        parts.append(f"Lab required: {booking.lab_details}")
    if booking.questionnaire:
        parts.append(f"Questionnaire to complete: {booking.questionnaire}")
    if booking.partner_questionnaire:
        parts.append(f"Partner questionnaire: {booking.partner_questionnaire}")
    if booking.guidance_document:
        parts.append(f"Guidance document: {booking.guidance_document}")
    if booking.self_pay:
        price_str = f" ({booking.self_pay_price_dkk} DKK)" if booking.self_pay_price_dkk else ""
        parts.append(f"Self-pay appointment{price_str}")

    parts.append("\nWrite a warm confirmation message for the patient. The clinic will call them to finalize the appointment.")
    return "\n".join(parts)


async def run_triage(session_name: str, interactive: bool = True):
    """Main orchestrator — runs the full triage pipeline."""
    db_path = os.path.join(SCRIPT_DIR, "war_games.db")
    session = SQLiteSession(session_name, db_path)
    max_turns = 20

    if interactive:
        print(f"\n{'='*60}")
        print("  Kvinde Klinikken AI Triage (v2)")
        print(f"  Model: {MODEL}")
        print(f"  Session: {session_name}")
        print(f"{'='*60}")
        print("  Type your messages as the patient.")
        print("  Type 'quit' to exit.\n")

    triage_data = None

    for turn in range(1, max_turns + 1):
        # Get patient input
        if interactive:
            try:
                user_input = input(f"  You [{turn}]: ")
            except (EOFError, KeyboardInterrupt):
                print("\n  Session ended.")
                return None
            if user_input.strip().lower() in ("quit", "exit", "q"):
                print("  Session ended.")
                return None
            if not user_input.strip():
                continue
        else:
            break  # non-interactive mode uses run_single_turn

        # Run triage agent
        result = await Runner.run(triage_agent, user_input, session=session, max_turns=5)

        # Check if complete_triage was called (final_output will be JSON string from the tool)
        if isinstance(result.final_output, str):
            try:
                triage_data = _parse_triage_data(result.final_output)
                break
            except (json.JSONDecodeError, ValidationError, ValueError):
                # It's a text response — show to patient and continue
                text = result.final_output.strip()
                if text and interactive:
                    print(f"\n  Triage: {text}\n")
        else:
            # Structured output or unexpected type
            try:
                triage_data = _parse_triage_data(result.final_output)
                break
            except (ValidationError, ValueError):
                if interactive:
                    print(f"\n  Triage: {result.final_output}\n")

    if triage_data is None:
        if interactive:
            print(f"\n  Reached max turns ({max_turns}). Session ended.")
        return None

    if interactive:
        print(f"\n  [Triage complete — processing...]")

    # --- Escalation check (deterministic Python) ---
    if triage_data.escalate or triage_data.insurance_type == "dss" or triage_data.category == "A":
        return await _run_handoff(triage_data, session, interactive)

    # --- Enrichment (all deterministic — no LLM) ---
    booking = _enrich_booking(triage_data)

    if interactive:
        print(f"\n  BookingRequest:")
        print(booking.model_dump_json(indent=2))

    # --- Confirmation message (LLM-generated) ---
    confirmation_input = _build_confirmation_context(triage_data, booking)
    conf_result = await Runner.run(confirmation_agent, confirmation_input, session=session)
    if interactive:
        print(f"\n  Confirmation message to patient:")
        print(f"  {conf_result.final_output}\n")

    return booking


async def _run_handoff(triage_data: TriageData, session: SQLiteSession, interactive: bool) -> HandoffRequest:
    """Run the handoff agent to produce a staff summary."""
    if triage_data.escalation_reason:
        reason = triage_data.escalation_reason
    elif triage_data.category == "A":
        reason = "Category A urgent condition"
    else:
        reason = "DSS/private insurance"

    handoff_input = f"""Triage data collected so far:
{triage_data.model_dump_json(indent=2)}

Escalation reason: {reason}
Please produce a HandoffRequest for clinic staff."""

    result = await Runner.run(handoff_agent, handoff_input, session=session)

    if not isinstance(result.final_output, HandoffRequest):
        # Fallback: construct a minimal HandoffRequest
        result_output = HandoffRequest(
            triage=triage_data,
            reason=reason,
            urgency="immediate" if triage_data.category == "A" else "normal",
            conversation_summary=str(result.final_output),
        )
    else:
        result_output = result.final_output

    if interactive:
        print(f"\n  [ESCALATED TO STAFF]")
        print(result_output.model_dump_json(indent=2))

    return result_output


async def run_single_turn(session_name: str, message: str):
    """Run a single turn — for scripted war-game testing via run_turn.py."""
    db_path = os.path.join(SCRIPT_DIR, "war_games.db")
    session = SQLiteSession(session_name, db_path)

    result = await Runner.run(triage_agent, message, session=session, max_turns=5)

    # Check if complete_triage was called
    if isinstance(result.final_output, str):
        try:
            triage_data = _parse_triage_data(result.final_output)
            return await _process_completed_triage(triage_data, session)
        except (json.JSONDecodeError, ValidationError, ValueError):
            # Text response — return it for display
            return result.final_output
    else:
        try:
            triage_data = _parse_triage_data(result.final_output)
            return await _process_completed_triage(triage_data, session)
        except (ValidationError, ValueError):
            return str(result.final_output)


async def _process_completed_triage(triage_data: TriageData, session) -> BookingRequest | HandoffRequest:
    """After triage is complete, run escalation check or enrichment."""
    if triage_data.escalate or triage_data.insurance_type == "dss" or triage_data.category == "A":
        return await _run_handoff(triage_data, session, interactive=False)

    booking = _enrich_booking(triage_data)

    # Generate confirmation message
    confirmation_input = _build_confirmation_context(triage_data, booking)
    conf_result = await Runner.run(confirmation_agent, confirmation_input, session=session)
    prefix = f"{booking.notes}\n\n" if booking.notes else ""
    booking.notes = f"{prefix}Confirmation sent: {conf_result.final_output}"

    return booking


# =============================================================================
# Interactive CLI
# =============================================================================

if __name__ == "__main__":
    import uuid

    session_id = f"war_game_{uuid.uuid4().hex[:8]}"

    if len(sys.argv) > 1 and sys.argv[1] == "--session":
        session_id = sys.argv[2] if len(sys.argv) > 2 else session_id

    result = asyncio.run(run_triage(session_id))

    if result:
        print(f"\n{'='*60}")
        print(f"  Final output: {type(result).__name__}")
        print(f"{'='*60}")
