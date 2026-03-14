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

MODEL = os.getenv("TRIAGE_MODEL", "gpt-5.4")

# =============================================================================
# Load YAML Config (mutable — supports runtime reload)
# =============================================================================

def _load_yaml():
    with open(PROJECT_DIR / "conditions.yaml") as f:
        return yaml.safe_load(f)

_CONFIG = _load_yaml()
CONDITIONS: dict[int, dict] = {c["id"]: c for c in _CONFIG["conditions"]}
GROUPS: list[dict] = _CONFIG["condition_groups"]


def get_conditions() -> dict[int, dict]:
    """Get the current conditions dict (supports dynamic reload)."""
    return CONDITIONS


def get_condition_reference() -> str:
    """Get the current condition reference string (supports dynamic reload)."""
    return CONDITION_REFERENCE


def reload_conditions():
    """Reload conditions from YAML and rebuild the reference. No server restart needed."""
    global _CONFIG, CONDITIONS, GROUPS, CONDITION_REFERENCE
    _CONFIG = _load_yaml()
    CONDITIONS.clear()
    CONDITIONS.update({c["id"]: c for c in _CONFIG["conditions"]})
    GROUPS.clear()
    GROUPS.extend(_CONFIG["condition_groups"])
    CONDITION_REFERENCE = build_condition_reference()


def save_conditions():
    """Save current config back to YAML."""
    with open(PROJECT_DIR / "conditions.yaml", "w") as f:
        yaml.dump(_CONFIG, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def update_condition(condition_id: int, data: dict):
    """Update a single condition in the config and save."""
    for i, c in enumerate(_CONFIG["conditions"]):
        if c["id"] == condition_id:
            _CONFIG["conditions"][i].update(data)
            _CONFIG["conditions"][i]["id"] = condition_id  # preserve id
            break
    save_conditions()
    reload_conditions()


def add_condition(data: dict):
    """Add a new condition to the config and save."""
    _CONFIG["conditions"].append(data)
    save_conditions()
    reload_conditions()


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
    for cond in _CONFIG["conditions"]:
        by_cat[cond["category"]].append(cond)

    for cat in ("A", "B", "C"):
        lines.append(f"\n--- {cat_labels[cat]} ---")
        for c in by_cat[cat]:
            desc = c.get("description", c["name"])
            lines.append(f"  [{c['id']}] {c['name']}: {desc}")
            if c.get("special_instructions"):
                si_lines = c["special_instructions"].strip().split("\n")
                lines.append(f"    ⚠ {si_lines[0]}")
                for si_line in si_lines[1:]:
                    lines.append(f"      {si_line}")
            if c.get("contraindications"):
                lines.append(f"    ⛔ Contraindications: {', '.join(c['contraindications'])}")
            if c.get("age_range"):
                ar = c["age_range"]
                ar_parts = []
                if ar.get("min"):
                    ar_parts.append(f"min {ar['min']}")
                if ar.get("max"):
                    ar_parts.append(f"max {ar['max']}")
                if ar_parts:
                    lines.append(f"    🔢 Age range: {', '.join(ar_parts)}")

    lines.append("\n=== CONDITION GROUPS (ask clarifying question before assigning) ===")
    for group in GROUPS:
        desc = group.get("description", "")
        lines.append(f"\n  GROUP: {group['group']} — {desc}")
        lines.append(f"  Ask: \"{group['clarifying_question']}\"")
        for opt in group["options"]:
            lines.append(f"    - {opt['label']} → condition [{opt['condition_id']}]")

    return "\n".join(lines)


CONDITION_REFERENCE = build_condition_reference()
