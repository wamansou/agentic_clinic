"""Orchestration logic: triage processing, enrichment, agent turns for web UI."""

import json
import uuid

from pydantic import ValidationError
from agents import Runner, SQLiteSession

from triage.config import CONDITIONS, DB_DIR
from triage.models import TriageData, BookingRequest, HandoffRequest
from triage.tools import (
    calculate_cycle_window,
    get_lab_requirements,
    get_questionnaire,
    get_guidance_document,
    get_self_pay_price,
)
from triage.agents import triage_agent, handoff_agent, confirmation_agent


# =============================================================================
# Parsing
# =============================================================================

def parse_triage_data(raw_output) -> TriageData:
    """Parse TriageData from agent's complete_triage tool output."""
    if isinstance(raw_output, TriageData):
        return raw_output
    if isinstance(raw_output, str):
        return TriageData.model_validate_json(raw_output)
    if isinstance(raw_output, dict):
        return TriageData.model_validate(raw_output)
    raise ValueError(f"Cannot parse TriageData from {type(raw_output)}: {raw_output}")


# =============================================================================
# Enrichment (deterministic — no LLM)
# =============================================================================

def enrich_booking(triage: TriageData) -> BookingRequest:
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


def build_confirmation_context(triage: TriageData, booking: BookingRequest) -> str:
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


# =============================================================================
# Handoff
# =============================================================================

async def run_handoff(triage_data: TriageData, session) -> HandoffRequest:
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
        return HandoffRequest(
            triage=triage_data,
            reason=reason,
            urgency="immediate" if triage_data.category == "A" else "normal",
            conversation_summary=str(result.final_output),
        )
    return result.final_output


# =============================================================================
# Post-triage Processing
# =============================================================================

async def process_completed_triage(triage_data: TriageData, session) -> tuple:
    """After triage is complete, run escalation check or enrichment.
    Returns (result, confirmation_text)."""
    if triage_data.escalate or triage_data.insurance_type == "dss" or triage_data.category == "A":
        handoff = await run_handoff(triage_data, session)
        return handoff, None

    booking = enrich_booking(triage_data)

    # Generate confirmation message
    confirmation_input = build_confirmation_context(triage_data, booking)
    conf_result = await Runner.run(confirmation_agent, confirmation_input, session=session)
    confirmation_text = str(conf_result.final_output)

    return booking, confirmation_text


# =============================================================================
# Single-Turn Runner (for web UI)
# =============================================================================

def extract_partial_triage(result) -> dict:
    """Inspect agent result for partial triage data (condition_id, name, doctor)
    from fetch_condition_details tool calls — without extra LLM calls."""
    partial = {}
    if hasattr(result, "new_items"):
        for item in result.new_items:
            if hasattr(item, "raw_item") and hasattr(item.raw_item, "type"):
                raw = item.raw_item
                # Check for tool call results
                if raw.type == "function_call_output":
                    try:
                        data = json.loads(raw.output) if isinstance(raw.output, str) else raw.output
                        if isinstance(data, dict) and "id" in data and "name" in data:
                            partial["condition_id"] = data["id"]
                            partial["condition_name"] = data["name"]
                            partial["category"] = data.get("category")
                            if data.get("doctor"):
                                partial["doctor"] = data["doctor"]
                            if data.get("duration"):
                                partial["duration_minutes"] = data["duration"]
                    except (json.JSONDecodeError, TypeError):
                        pass
    return partial


async def run_agent_turn(session_id: str, message: str, db_path: str | None = None) -> dict:
    """Run a single agent turn. Returns a dict with type, content, and optional triage data.

    Return dict keys:
      - type: "text" | "booking" | "handoff"
      - content: agent text response or confirmation message
      - triage_data: dict (if triage complete)
      - result: BookingRequest or HandoffRequest dict (if complete)
      - partial: dict of partial triage fields from tool calls
    """
    if db_path is None:
        db_path = str(DB_DIR / "triage_sessions.db")

    session = SQLiteSession(session_id, db_path)

    result = await Runner.run(triage_agent, message, session=session, max_turns=5)

    # Extract any partial triage info from tool calls
    partial = extract_partial_triage(result)

    # Check if complete_triage was called
    if isinstance(result.final_output, str):
        try:
            triage_data = parse_triage_data(result.final_output)
        except (json.JSONDecodeError, ValidationError, ValueError):
            # Text response — conversation continues
            return {
                "type": "text",
                "content": result.final_output.strip(),
                "partial": partial,
            }
    else:
        try:
            triage_data = parse_triage_data(result.final_output)
        except (ValidationError, ValueError):
            return {
                "type": "text",
                "content": str(result.final_output),
                "partial": partial,
            }

    # Triage complete — process it
    final_result, confirmation = await process_completed_triage(triage_data, session)

    if isinstance(final_result, HandoffRequest):
        return {
            "type": "handoff",
            "content": confirmation or "Your case has been escalated to our staff.",
            "triage_data": triage_data.model_dump(),
            "result": final_result.model_dump(),
        }
    else:
        return {
            "type": "booking",
            "content": confirmation or "Your booking request has been submitted.",
            "triage_data": triage_data.model_dump(),
            "result": final_result.model_dump(),
        }
