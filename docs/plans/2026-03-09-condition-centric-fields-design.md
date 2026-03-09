# Condition-Centric Fields Expansion

**Date:** 2026-03-09
**Status:** Approved

## Goal

Make every aspect of the triage system driven by per-condition YAML data, editable by the clinic via the UI. Replace hardcoded logic with structured fields while keeping `special_instructions` as a free-text escape valve for unusual rules.

## New YAML Fields

### Triage (affect routing/booking)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `contraindications` | list[str] | null | Agent screens for these during triage; triggers escalation or warning |
| `age_range` | {min: int, max: int} | null | Agent checks patient age against range; escalate if outside |
| `visits_required` | int | null (=1) | Agent informs patient if multiple visits needed |

### Patient Preparation (fed to confirmation agent)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `preparation_instructions` | list[str] | null | Confirmation agent tells patient what to do before visit |
| `companion_required` | bool | false | Confirmation agent tells patient to arrange a ride home |
| `estimated_recovery` | str | null | Confirmation agent sets expectations for recovery |

### Clinic/Scheduling

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `equipment` | list[str] | null | Staff knows which room/equipment to book |
| `followup_interval` | str | null | Staff knows when to schedule follow-up |

### Existing fields now exposed in editor

| Field | Already in YAML | Already in editor | Now editable |
|-------|----------------|-------------------|--------------|
| `lab` | Yes | No | Yes — test name, description, age condition |
| `guidance_document` | Yes | No | Yes — URL or text |

## YAML Structure (per condition)

```yaml
- id: 41
  name: Hysteroscopy
  # ... existing fields unchanged ...

  contraindications:
    - "Cannot be performed during pregnancy"
    - "Not suitable if on blood thinners"
  age_range:
    min: null
    max: null
  visits_required: 2
  preparation_instructions:
    - "Take 400mg ibuprofen 1 hour before the appointment"
  companion_required: true
  estimated_recovery: "1-2 days of light discomfort"
  equipment:
    - hysteroscope
    - ultrasound
  followup_interval: "4-6 weeks"
```

All new fields default to null. The system uses whatever is populated and ignores null fields.

## Data Migration

Populate known data from existing special_instructions and hardcoded logic into the new structured fields:
- Condition 5 (abortion): `age_range: {min: 15}`
- Conditions requiring hysteroscope (23, 41, 44): `equipment: [hysteroscope]`
- Conditions with known prep requirements: populate `preparation_instructions`
- Any other data currently hardcoded or buried in special_instructions

## System Flow

### Agent (triage conversation)
- `fetch_condition_details` already returns full condition dict — new fields included automatically
- Agent checks `contraindications` against patient context → escalate or ask clarifying question
- Agent checks `age_range` → escalate if outside bounds
- Agent mentions `visits_required` if > 1
- `special_instructions` remains for anything not captured by structured fields

### Confirmation agent (patient message)
- `build_confirmation_context()` feeds new fields:
  - `preparation_instructions` → "Please remember to..."
  - `companion_required` → "Please arrange for someone to drive you home"
  - `estimated_recovery` → "You can expect..."
  - `guidance_document` → link in message

### Enrichment (`enrich_booking`)
- Populates new `BookingRequest` fields from condition data
- Staff-facing result includes `equipment`, `followup_interval`, `visits_required`

## Files Changed

| File | Change |
|------|--------|
| `conditions.yaml` | Add new fields to all 53 conditions, populate known data |
| `triage/models.py` | Add fields to `BookingRequest` |
| `triage/orchestrator.py` | `enrich_booking()` + `build_confirmation_context()` use new fields |
| `triage/agents.py` | Update triage prompt (contraindications, age_range), update confirmation prompt |
| `templates/conditions.html` | New editor fields in 3 groups |
| `static/js/conditions.js` | Load/save new fields, dynamic lists |
| `triage/api.py` | Handle new fields in condition save endpoint |

## Design Principles

- All fields optional (null = not applicable)
- Clinic fills in data over time via editor
- Structured fields preferred over free text, but `special_instructions` stays
- No hardcoded per-condition logic in Python — everything data-driven from YAML
