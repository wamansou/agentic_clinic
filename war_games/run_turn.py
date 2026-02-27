#!/usr/bin/env python3
"""
War game turn runner — sends one patient message and prints the agent response.
Maintains conversation state across turns via SQLiteSession.

v2: Single triage agent — no agent state tracking needed.

Usage:
    python run_turn.py <session_name> <message>

Example:
    python run_turn.py shy_patient "hi"
    python run_turn.py shy_patient "yes, public insurance"
"""

import os
import sys
import asyncio

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
os.chdir(PROJECT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from triage_app import (
    run_single_turn, BookingRequest, HandoffRequest, MODEL
)


async def run_turn(session_name: str, message: str):
    print(f"[Session: {session_name} | Model: {MODEL}]")
    print(f"[Patient]: {message}")

    result = await run_single_turn(session_name, message)

    if isinstance(result, BookingRequest):
        print(f"\n[Triage] → BookingRequest:")
        print(result.model_dump_json(indent=2))
    elif isinstance(result, HandoffRequest):
        print(f"\n[Triage] → HandoffRequest:")
        print(result.model_dump_json(indent=2))
    else:
        # Text response — conversation continues
        text = str(result).strip()
        print(f"[Triage]: {text}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run_turn.py <session_name> <message>")
        sys.exit(1)

    session_name = sys.argv[1]
    message = " ".join(sys.argv[2:])

    asyncio.run(run_turn(session_name, message))
