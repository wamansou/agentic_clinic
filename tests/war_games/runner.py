"""War game runner — AI-vs-AI conversation simulator."""

import os
import uuid

from openai import AsyncOpenAI
from agents import Runner, SQLiteSession

from triage.config import MODEL, DB_DIR
from triage.models import BookingRequest, HandoffRequest
from triage.agents import triage_agent
from triage.orchestrator import parse_triage_data, enrich_booking, run_handoff


# =============================================================================
# Patient Simulator
# =============================================================================

PATIENT_SYSTEM = """You are a patient contacting Kvinde Klinikken (a Danish gynecology clinic) via chat.
You are role-playing the scenario described below. Behave like a REAL patient:

- Answer questions naturally — one piece of info at a time unless it flows naturally
- Use casual, everyday language (not medical jargon)
- You may mention your issue early or wait to be asked — vary your approach
- If asked something you don't know from your scenario, make up a plausible answer
- Stay in character — do NOT break the fourth wall or mention you are simulating
- Keep responses short (1-2 sentences typically, like a real chat message)

{language_instruction}

=== YOUR SCENARIO ===
{scenario}

=== YOUR DETAILS ===
Name: {name}
Phone: {phone}
"""


async def simulate_patient(
    client: AsyncOpenAI,
    scenario: dict,
    max_turns: int = 15,
) -> dict:
    """Run a full AI-vs-AI conversation and return results."""
    session_id = f"wg_{scenario['name']}_{uuid.uuid4().hex[:6]}"
    db_path = str(DB_DIR / "war_games_live.db")
    session = SQLiteSession(session_id, db_path)

    # Build patient simulator prompt
    lang_inst = ""
    if scenario.get("language") == "da":
        lang_inst = "You speak DANISH (dansk). Write all your messages in Danish."
    elif scenario.get("language") == "en":
        lang_inst = "You speak English."
    else:
        lang_inst = "You speak English unless specified otherwise."

    patient_system = PATIENT_SYSTEM.format(
        scenario=scenario["persona"],
        name=scenario.get("patient_name", "Anna Jensen"),
        phone=scenario.get("phone", "55512345"),
        language_instruction=lang_inst,
    )

    patient_history = [{"role": "system", "content": patient_system}]
    triage_data = None
    conversation_log = []

    # Patient opens the conversation
    opening = scenario.get("opening")
    if opening:
        patient_msg = opening
    else:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=patient_history + [
                {"role": "user", "content": "You are now contacting the clinic. Send your first message."}
            ],
            max_completion_tokens=150,
        )
        patient_msg = resp.choices[0].message.content.strip()

    for turn in range(1, max_turns + 1):
        conversation_log.append({"turn": turn, "role": "patient", "text": patient_msg})

        # Send to triage agent
        result = await Runner.run(triage_agent, patient_msg, session=session, max_turns=5)

        # Check for triage completion
        if isinstance(result.final_output, str):
            try:
                triage_data = parse_triage_data(result.final_output)
                conversation_log.append({"turn": turn, "role": "triage", "text": "[TRIAGE COMPLETE]"})
                break
            except Exception:
                agent_response = result.final_output.strip()
        else:
            try:
                triage_data = parse_triage_data(result.final_output)
                conversation_log.append({"turn": turn, "role": "triage", "text": "[TRIAGE COMPLETE]"})
                break
            except Exception:
                agent_response = str(result.final_output)

        conversation_log.append({"turn": turn, "role": "triage", "text": agent_response})

        # Generate patient response
        patient_history.append({"role": "assistant", "content": patient_msg})
        patient_history.append({"role": "user", "content": f"The clinic assistant says: \"{agent_response}\"\n\nRespond as the patient."})

        resp = await client.chat.completions.create(
            model=MODEL,
            messages=patient_history,
            max_completion_tokens=150,
        )
        patient_msg = resp.choices[0].message.content.strip()

    # Build result
    total_turns = len([c for c in conversation_log if c["role"] == "patient"])

    if triage_data is None:
        return {
            "name": scenario["name"],
            "status": "FAIL",
            "reason": f"No triage completion after {total_turns} turns",
            "turns": total_turns,
            "conversation": conversation_log,
        }

    # Process through orchestrator
    is_escalation = triage_data.escalate or triage_data.insurance_type == "dss" or triage_data.category == "A"
    expect_escalation = scenario.get("expect_escalation", False)

    if expect_escalation and not is_escalation:
        return {
            "name": scenario["name"],
            "status": "FAIL",
            "reason": f"Expected escalation but got booking. condition_id={triage_data.condition_id}",
            "turns": total_turns,
            "triage_data": triage_data.model_dump(),
            "conversation": conversation_log,
        }

    if not expect_escalation and is_escalation:
        return {
            "name": scenario["name"],
            "status": "FAIL",
            "reason": f"Unexpected escalation. reason={triage_data.escalation_reason}",
            "turns": total_turns,
            "triage_data": triage_data.model_dump(),
            "conversation": conversation_log,
        }

    # Build output for verification
    if is_escalation:
        handoff = await run_handoff(triage_data, session)
        output = {
            "condition_id": triage_data.condition_id,
            "category": triage_data.category,
            "insurance_type": triage_data.insurance_type,
            "language": triage_data.language,
            "urgency": handoff.urgency,
        }
    else:
        booking = enrich_booking(triage_data)
        output = {
            "condition_id": triage_data.condition_id,
            "condition_name": triage_data.condition_name,
            "category": triage_data.category,
            "doctor": triage_data.doctor,
            "language": triage_data.language,
            "insurance_type": triage_data.insurance_type,
            "cycle_dependent": booking.cycle_dependent,
            "lab_required": booking.lab_required,
            "self_pay": booking.self_pay,
            "self_pay_price_dkk": booking.self_pay_price_dkk,
            "questionnaire": booking.questionnaire,
            "guidance_document": booking.guidance_document,
        }

    # Verify expected fields
    failures = []
    for key, expected in scenario.get("expect", {}).items():
        actual = output.get(key)
        if actual != expected:
            failures.append(f"{key}: expected={expected}, got={actual}")

    if failures:
        return {
            "name": scenario["name"],
            "status": "FAIL",
            "reason": "; ".join(failures),
            "turns": total_turns,
            "output": output,
            "conversation": conversation_log,
        }

    return {
        "name": scenario["name"],
        "status": "PASS",
        "turns": total_turns,
        "output": output,
        "conversation": conversation_log,
    }


async def run_scenario(client: AsyncOpenAI, scenario: dict) -> dict:
    """Run a single scenario with error handling."""
    try:
        return await simulate_patient(client, scenario)
    except Exception as e:
        return {
            "name": scenario["name"],
            "status": "ERROR",
            "reason": str(e),
            "turns": 0,
            "conversation": [],
        }
