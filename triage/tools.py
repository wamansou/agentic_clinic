"""Tool functions for the triage agent — both raw helpers and @function_tool wrappers."""

import json
from datetime import date, datetime, timedelta

from agents import function_tool
from agents.agent import ToolsToFinalOutputResult
from agents.tool import FunctionToolResult

from triage.config import CONDITIONS
from triage.models import TriageData


# =============================================================================
# Raw Tool Functions (deterministic Python)
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
# Agent Tools (@function_tool wrappers)
# =============================================================================

@function_tool
def fetch_condition_details(condition_id: int) -> str:
    """Get full details for a specific condition including doctor, duration, priority, cycle requirements, lab requirements, and routing questions."""
    return get_condition_details(condition_id)


@function_tool
def complete_triage(data: TriageData) -> str:
    """Call this when you have collected all required information from the patient.
    Fill in ALL fields you have gathered. For escalations, set escalate=true and provide escalation_reason."""
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


def validate_complete_triage(
    context, tool_results: list[FunctionToolResult]
) -> ToolsToFinalOutputResult:
    """Custom tool_use_behavior: validates complete_triage output before stopping.
    If validation fails (ERROR prefix), lets the agent continue to fix it."""
    for result in tool_results:
        if result.tool.name == "complete_triage":
            output = result.output
            if isinstance(output, str) and output.startswith("ERROR:"):
                return ToolsToFinalOutputResult(is_final_output=False)
            return ToolsToFinalOutputResult(
                is_final_output=True, final_output=output
            )
    return ToolsToFinalOutputResult(is_final_output=False)
