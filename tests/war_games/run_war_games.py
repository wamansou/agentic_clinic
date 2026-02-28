#!/usr/bin/env python3
"""
Live AI-vs-AI war game testing.

Usage:
    python -m tests.war_games.run_war_games                          # run all scenarios
    python -m tests.war_games.run_war_games --scenario heavy_bleeding # run one scenario
    python -m tests.war_games.run_war_games --list                    # list available scenarios
"""

import sys
import asyncio
import argparse

from openai import AsyncOpenAI

from tests.war_games.scenarios import SCENARIOS
from tests.war_games.runner import run_scenario


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
