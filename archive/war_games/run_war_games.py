#!/usr/bin/env python3
"""
Live AI-vs-AI war game testing.
A patient simulator LLM plays a patient role and converses with the triage agent.
Results are evaluated against expected outcomes.

Usage:
    python run_war_games.py                          # run all scenarios
    python run_war_games.py --scenario heavy_bleeding # run one scenario
    python run_war_games.py --list                    # list available scenarios
"""

import os
import sys
import json
import asyncio
import argparse
import uuid
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

from openai import AsyncOpenAI
from triage_app import (
    triage_agent, _parse_triage_data, _enrich_booking, _run_handoff,
    BookingRequest, HandoffRequest, TriageData, CONDITIONS, MODEL,
)
from agents import Runner, SQLiteSession


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
    db_path = os.path.join(SCRIPT_DIR, "war_games_live.db")
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
        # Let the patient simulator generate the opening
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
                triage_data = _parse_triage_data(result.final_output)
                conversation_log.append({"turn": turn, "role": "triage", "text": "[TRIAGE COMPLETE]"})
                break
            except Exception:
                agent_response = result.final_output.strip()
        else:
            try:
                triage_data = _parse_triage_data(result.final_output)
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
        handoff = await _run_handoff(triage_data, session, interactive=False)
        output = {
            "condition_id": triage_data.condition_id,
            "category": triage_data.category,
            "insurance_type": triage_data.insurance_type,
            "language": triage_data.language,
            "urgency": handoff.urgency,
        }
    else:
        booking = _enrich_booking(triage_data)
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


# =============================================================================
# Scenario Definitions
# =============================================================================

SCENARIOS = [
    # --- Category A: Emergencies ---
    {
        "name": "cat_a_heavy_bleeding",
        "persona": "You are experiencing very heavy vaginal bleeding right now — soaking through pads, feeling dizzy. You are scared and need help immediately.",
        "patient_name": "Maria Hansen",
        "phone": "99887766",
        "expect_escalation": True,
        "expect": {"category": "A", "urgency": "immediate"},
    },
    {
        "name": "cat_a_ectopic",
        "persona": "You are about 6 weeks pregnant and having sharp, stabbing pain on your right side. You are worried it might be ectopic. You are frightened.",
        "patient_name": "Hanna Eriksen",
        "phone": "55443322",
        "expect_escalation": True,
        "expect": {"category": "A", "urgency": "immediate"},
    },
    {
        "name": "cat_a_abortion",
        "persona": "You just found out you are pregnant and you want to have an abortion. You have public insurance.",
        "patient_name": "Emily Wilson",
        "phone": "66778899",
        "expect_escalation": True,
        "expect": {"condition_id": 5, "category": "A"},
    },
    {
        "name": "cat_a_severe_pain",
        "persona": "You are having sudden, severe lower abdominal pain that started an hour ago. You can barely stand up. The pain is sharp and constant.",
        "patient_name": "Lise Berg",
        "phone": "22113344",
        "expect_escalation": True,
        "expect": {"category": "A", "urgency": "immediate"},
    },

    # --- DSS / Private Insurance ---
    {
        "name": "dss_insurance",
        "persona": "You have private insurance through Dansk Sundhedssikring (DSS). You want to book an appointment for a gynecological check-up.",
        "patient_name": "Lisa Møller",
        "phone": "44556677",
        "expect_escalation": True,
        "expect": {"insurance_type": "dss"},
    },

    # --- Standard Bookings (simple) ---
    {
        "name": "cone_biopsy",
        "persona": "Your GP referred you for a cone biopsy (keglesnit / konisation). You have public insurance and a referral.",
        "patient_name": "Julia Frederiksen",
        "phone": "33221100",
        "expect_escalation": False,
        "expect": {"condition_id": 8, "category": "B", "guidance_document": "Kegleoperation"},
    },
    {
        "name": "fibroids",
        "persona": "You were told you have fibroids (myomer) and your GP referred you to a gynecologist. You have public insurance and a referral.",
        "patient_name": "Anna Petersen",
        "phone": "99887766",
        "expect_escalation": False,
        "expect": {"condition_id": 53, "doctor": "LB"},
    },
    {
        "name": "cystoscopy",
        "persona": "Your doctor referred you for a cystoscopy. You have public insurance and a referral.",
        "patient_name": "Diana Price",
        "phone": "77665544",
        "expect_escalation": False,
        "expect": {"condition_id": 42, "doctor": "HS"},
    },
    {
        "name": "itching_discharge",
        "persona": "You have been having persistent itching and unusual discharge for a few weeks. Your GP referred you. You have public insurance.",
        "patient_name": "Nina Olsen",
        "phone": "88112233",
        "expect_escalation": False,
        "expect": {"condition_id": 50, "doctor": "LB"},
    },
    {
        "name": "insemination",
        "persona": "You need to schedule an insemination procedure. You have public insurance and a referral from your fertility doctor.",
        "patient_name": "Laura Henriksen",
        "phone": "99223344",
        "expect_escalation": False,
        "expect": {"condition_id": 11, "doctor": "LB"},
    },

    # --- Group Disambiguations ---
    {
        "name": "iud_removal_strings_visible",
        "persona": "You want to have your IUD (spiral) removed. The strings are visible — your doctor has seen them at check-ups. You have public insurance and a referral.",
        "patient_name": "Karen Sørensen",
        "phone": "33445566",
        "expect_escalation": False,
        "expect": {"condition_id": 20, "doctor": "LB"},
    },
    {
        "name": "pcos_new",
        "persona": "Your GP suspects you might have PCOS (polycystic ovary syndrome). This is your first time being assessed for it — it's a new referral. You have public insurance.",
        "patient_name": "Amira Saleh",
        "phone": "12345678",
        "expect_escalation": False,
        "expect": {"condition_id": 39, "doctor": "LB", "lab_required": True},
    },
    {
        "name": "bartholin_cyst",
        "persona": "You have been referred for a cyst. When asked, it's a Bartholin's cyst (on the vulva area, not ovarian). You have public insurance and a referral.",
        "patient_name": "Lisa Andersen",
        "phone": "11223344",
        "expect_escalation": False,
        "expect": {"condition_id": 28, "doctor": "LB"},
    },
    {
        "name": "lichen_new",
        "persona": "You have been referred for lichen sclerosus. This is your first time — a new assessment, not a follow-up. You have public insurance and a referral.",
        "patient_name": "Rebecca Lindberg",
        "phone": "22887766",
        "expect_escalation": False,
        "expect": {"condition_id": 45, "doctor": "LB"},
    },

    # --- Routing + Age + Danish ---
    {
        "name": "endometriosis_danish",
        "persona": "Du er henvist for endometriose. Du har offentlig sygesikring og en henvisning. Din sidste menstruation startede for cirka 2 uger siden, og din cyklus er cirka 30 dage.",
        "patient_name": "Mette Nielsen",
        "phone": "55512345",
        "language": "da",
        "expect_escalation": False,
        "expect": {"condition_id": 18, "doctor": "HS", "cycle_dependent": True},
    },
    {
        "name": "bleeding_age_48",
        "persona": "You have been having irregular bleeding for a few weeks — not heavy, just irregular. You are 48 years old. You have public insurance and a GP referral.",
        "patient_name": "Karen Jensen",
        "phone": "22334455",
        "expect_escalation": False,
        "expect": {"condition_id": 15, "doctor": "HS"},
    },
    {
        "name": "contact_bleeding",
        "persona": "You have been having bleeding after sex (contact bleeding). Your GP referred you. You have public insurance and a referral.",
        "patient_name": "Emma Thomsen",
        "phone": "44556677",
        "expect_escalation": False,
        "expect": {"condition_id": 9, "category": "B"},
    },
    {
        "name": "cancer_package_danish",
        "persona": "Din læge har henvist dig til en kræftpakke. Du har offentlig sygesikring og en henvisning.",
        "patient_name": "Inge Madsen",
        "phone": "33221144",
        "language": "da",
        "expect_escalation": False,
        "expect": {"condition_id": 6, "category": "B"},
    },

    # --- Cycle-dependent + Labs + Self-pay ---
    {
        "name": "fertility_consultation",
        "persona": "You and your partner have been trying to get pregnant for over a year with no success. You have public insurance and a referral.",
        "patient_name": "Lena Berg",
        "phone": "11223344",
        "expect_escalation": False,
        "expect": {"condition_id": 10, "doctor": "LB", "lab_required": True},
    },
    {
        "name": "selfpay_smear",
        "persona": "You want a routine smear test (cervical screening). You have public insurance but NO referral. You are willing to pay yourself (self-pay).",
        "patient_name": "Eva Holm",
        "phone": "55667788",
        "expect_escalation": False,
        "expect": {"condition_id": 38, "self_pay": True, "self_pay_price_dkk": 950.0},
    },
    {
        "name": "recurrent_uti",
        "persona": "You keep getting urinary tract infections (UTIs) — every couple of months, with burning and frequent urination. Your GP referred you. You have public insurance.",
        "patient_name": "Sarah O'Brien",
        "phone": "55009911",
        "expect_escalation": False,
        "expect": {"condition_id": 33, "doctor": "LB"},
    },
    {
        "name": "unclassifiable_escalation",
        "persona": "You have a problem with lymph nodes in your groin area that keep swelling up. Your GP wasn't sure what it was and referred you to a gynecologist. If the assistant can't figure out what condition this is, you'd like to just talk to someone at the clinic.",
        "patient_name": "Jane Smith",
        "phone": "11223344",
        "expect_escalation": True,
        "expect": {"urgency": "normal"},
    },
    {
        "name": "escape_hatch",
        "persona": "You want to book an appointment but after a couple of questions you get frustrated and want to speak to a real person at the clinic. Say something like 'I'd rather just talk to someone'.",
        "patient_name": "Katrine Lund",
        "phone": "44332211",
        "expect_escalation": True,
        "expect": {"urgency": "normal"},
    },
]


# =============================================================================
# Main runner
# =============================================================================

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


async def main():
    parser = argparse.ArgumentParser(description="Live AI-vs-AI war game testing")
    parser.add_argument("--scenario", type=str, help="Run a specific scenario by name")
    parser.add_argument("--list", action="store_true", help="List all available scenarios")
    args = parser.parse_args()

    if args.list:
        for s in SCENARIOS:
            esc = "ESCALATION" if s.get("expect_escalation") else "BOOKING"
            print(f"  {s['name']:30s}  [{esc}]  {s['persona'][:60]}...")
        return 0

    client = AsyncOpenAI()

    if args.scenario:
        scenarios = [s for s in SCENARIOS if s["name"] == args.scenario]
        if not scenarios:
            print(f"Unknown scenario: {args.scenario}")
            print("Use --list to see available scenarios")
            return 1
    else:
        scenarios = SCENARIOS

    # Run scenarios sequentially (each is an independent AI conversation)
    results = []
    for scenario in scenarios:
        print(f"  Running {scenario['name']}...", end=" ", flush=True)
        result = await run_scenario(client, scenario)
        status = result["status"]
        turns = result.get("turns", 0)
        detail = f" — {result.get('reason', '')}" if status != "PASS" else ""
        print(f"{status} ({turns} turns){detail}", flush=True)
        results.append(result)

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] != "PASS")
    total = len(results)
    avg_turns = sum(r.get("turns", 0) for r in results if r["status"] == "PASS") / max(passed, 1)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} passed | Avg turns (passing): {avg_turns:.1f}")
    print(f"{'='*60}")

    if failed:
        print(f"\nFailed scenarios:")
        for r in results:
            if r["status"] != "PASS":
                print(f"  {r['status']}: {r['name']} — {r.get('reason', 'unknown')}")
                if r.get("conversation"):
                    print(f"    Conversation:")
                    for msg in r["conversation"][-6:]:  # last 6 messages
                        print(f"      [{msg['role']}] {msg['text'][:100]}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
