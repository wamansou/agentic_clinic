"""Pydantic models for the triage system."""

from datetime import datetime
from pydantic import BaseModel


# =============================================================================
# Core Triage Models (from triage_app.py)
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
# Web UI Models
# =============================================================================

class WSMessage(BaseModel):
    """WebSocket message envelope."""
    type: str  # "chat", "triage_update", "complete", "status"
    data: dict


class SessionMeta(BaseModel):
    """Session metadata for the dashboard history view."""
    session_id: str
    created_at: datetime
    patient_name: str | None = None
    status: str = "active"  # "active", "completed", "escalated"
    condition_name: str | None = None
    result_type: str | None = None  # "booking", "handoff"
