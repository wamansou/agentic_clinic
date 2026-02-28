"""Configuration: YAML loading, model settings, condition reference."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Project paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_DIR / "data"
DB_DIR.mkdir(exist_ok=True)

load_dotenv(PROJECT_DIR / ".env")

MODEL = os.getenv("TRIAGE_MODEL", "gpt-4o")

# =============================================================================
# Load YAML Config
# =============================================================================

with open(PROJECT_DIR / "conditions.yaml") as f:
    CONFIG = yaml.safe_load(f)

CONDITIONS: dict[int, dict] = {c["id"]: c for c in CONFIG["conditions"]}
GROUPS: list[dict] = CONFIG["condition_groups"]


# =============================================================================
# Build Condition Reference (injected into agent prompt)
# =============================================================================

def build_condition_reference() -> str:
    """Generate a compact reference table of all conditions and groups for the LLM prompt."""
    lines = ["=== CONDITION REFERENCE ==="]

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

    lines.append("\n=== CONDITION GROUPS (ask clarifying question before assigning) ===")
    for group in GROUPS:
        desc = group.get("description", "")
        lines.append(f"\n  GROUP: {group['group']} — {desc}")
        lines.append(f"  Ask: \"{group['clarifying_question']}\"")
        for opt in group["options"]:
            lines.append(f"    - {opt['label']} → condition [{opt['condition_id']}]")

    return "\n".join(lines)


CONDITION_REFERENCE = build_condition_reference()
