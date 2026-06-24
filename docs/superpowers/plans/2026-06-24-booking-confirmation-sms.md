# Booking Confirmation via SMS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a clinic secretary mark a triaged booking as "booked," which sends the patient an SMS confirmation link they click within 48 hours to flip the booking to `confirmed`; unconfirmed bookings expire and resurface for follow-up, with a manual `cancelled` state.

**Architecture:** A new `confirmation_status` lifecycle (`none → pending → confirmed`, plus derived `expired` and manual `cancelled`) tracked on the existing `sessions` table, independent of the secretary's `processing_status` workflow. A pluggable SMS sender (console stub for the demo) delivers a tokenized public confirm link. Expiry is derived on read (no scheduler). Phone number becomes mandatory at triage so every booking has an SMS target.

**Tech Stack:** Python 3.14, FastAPI, Jinja2, SQLite (`sqlite3`), OpenAI Agents SDK, vanilla JS. No pytest — tests are a standalone assert-based script run with `python -m tests.test_confirmation`.

## Global Constraints

- Python 3.14 via `.venv` — activate with `source .venv/bin/activate` before running anything.
- No new third-party dependencies. Use stdlib `secrets`, `sqlite3`, `datetime`, `logging`.
- All timestamps stored as ISO-8601 UTC strings (`datetime.now(timezone.utc).isoformat()`).
- SQLite schema changes go through the existing idempotent `_ensure_session_columns(conn)` migration — never a manual migration step.
- Demo defaults must work with zero config: `SMS_PROVIDER=console`, `PUBLIC_BASE_URL=http://localhost:8000`, `CONFIRMATION_TTL_HOURS=48`.
- Scope: only `result_type == "booking"` sessions get the confirmation flow; `handoff` sessions are excluded.
- `confirmation_status` and `processing_status` stay independent — confirming does NOT auto-complete the secretary workflow.
- `cancelled` is record-keeping in our app only; it does NOT touch the clinic's external booking system.
- Run the test script after every task: `python -m tests.test_confirmation` (fast; no LLM, no network).

---

### Task 1: Config + Notifications module (SMS sender)

**Files:**
- Modify: `triage/config.py` (append confirmation settings after the `MODEL` line)
- Create: `triage/notifications.py`
- Create: `tests/test_confirmation.py` (test harness + notification tests)

**Interfaces:**
- Produces:
  - `triage.config.SMS_PROVIDER: str`, `PUBLIC_BASE_URL: str`, `CONFIRMATION_TTL_HOURS: int`
  - `triage.notifications.build_confirmation_url(token: str) -> str`
  - `triage.notifications.build_confirmation_message(token: str, language: str = "da") -> str`
  - `triage.notifications.SmsSender` (base), `ConsoleSmsSender`, `TwilioSmsSender`
  - `triage.notifications.get_sms_sender() -> SmsSender`

- [ ] **Step 1: Create the test harness + failing notification tests**

Create `tests/test_confirmation.py`:

```python
"""Standalone verification for booking-confirmation logic.

Run: python -m tests.test_confirmation
No LLM, no network — pure SQLite + helpers.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

_TESTS = []


def test(fn):
    _TESTS.append(fn)
    return fn


# ---------------------------------------------------------------------------
# Task 1 — notifications
# ---------------------------------------------------------------------------

@test
def test_confirmation_url_contains_token():
    from triage.notifications import build_confirmation_url
    url = build_confirmation_url("abc123")
    assert url.endswith("/confirm/abc123"), url


@test
def test_confirmation_message_is_bilingual_with_link():
    from triage.notifications import build_confirmation_message
    body = build_confirmation_message("tok", "da")
    assert "/confirm/tok" in body, body
    assert "Bekræft" in body and "Confirm" in body, body


@test
def test_console_sender_does_not_raise():
    from triage.notifications import ConsoleSmsSender
    ConsoleSmsSender().send("12345678", "hello")


@test
def test_get_sms_sender_defaults_to_console():
    from triage.notifications import get_sms_sender, ConsoleSmsSender
    assert isinstance(get_sms_sender(), ConsoleSmsSender)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    failed = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {e!r}")
    print(f"\n{len(_TESTS) - failed}/{len(_TESTS)} passed")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if run() else 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python -m tests.test_confirmation`
Expected: ERRORs — `ModuleNotFoundError: No module named 'triage.notifications'`.

- [ ] **Step 3: Add config settings**

Append to `triage/config.py` (after the `MODEL = ...` line at line 16):

```python

# Booking-confirmation settings
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "console")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
CONFIRMATION_TTL_HOURS = int(os.getenv("CONFIRMATION_TTL_HOURS", "48"))
```

- [ ] **Step 4: Create the notifications module**

Create `triage/notifications.py`:

```python
"""SMS notification layer for booking confirmations.

Pluggable sender: a console/log stub for the demo, with a documented slot for a
real provider (e.g. Twilio) selected via the SMS_PROVIDER env var.
"""

import logging

from triage.config import SMS_PROVIDER, PUBLIC_BASE_URL, CONFIRMATION_TTL_HOURS

logger = logging.getLogger("triage.sms")


def build_confirmation_url(token: str) -> str:
    """Public URL the patient clicks to confirm their appointment."""
    return f"{PUBLIC_BASE_URL.rstrip('/')}/confirm/{token}"


def build_confirmation_message(token: str, language: str = "da") -> str:
    """Bilingual (Danish + English) SMS body containing the confirm link."""
    url = build_confirmation_url(token)
    hours = CONFIRMATION_TTL_HOURS
    return (
        f"Gynækologerne Skensved og Bune: Bekræft din aftale inden for "
        f"{hours} timer: {url}\n\n"
        f"Confirm your appointment within {hours} hours: {url}"
    )


class SmsSender:
    """Interface for SMS providers."""

    def send(self, to: str, body: str) -> None:
        raise NotImplementedError


class ConsoleSmsSender(SmsSender):
    """Demo sender — logs the message instead of sending a real SMS."""

    def send(self, to: str, body: str) -> None:
        logger.info("[SMS -> %s]\n%s", to, body)
        print(f"\n=== SMS to {to} ===\n{body}\n====================\n")


class TwilioSmsSender(SmsSender):
    """Real provider slot — not implemented for the demo."""

    def send(self, to: str, body: str) -> None:
        raise NotImplementedError(
            "TwilioSmsSender is not configured. Set SMS_PROVIDER=console for the demo."
        )


def get_sms_sender() -> SmsSender:
    """Return the SMS sender selected by the SMS_PROVIDER env var."""
    if SMS_PROVIDER == "twilio":
        return TwilioSmsSender()
    return ConsoleSmsSender()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m tests.test_confirmation`
Expected: `4/4 passed`.

- [ ] **Step 6: Commit**

```bash
git add triage/config.py triage/notifications.py tests/test_confirmation.py
git commit -m "feat: SMS notification layer + config for booking confirmation"
```

---

### Task 2: Phone-required validation in triage

**Files:**
- Modify: `triage/tools.py` (extract a pure validator, add the phone gate)
- Modify: `triage/agents.py` (prompt: phone mandatory)
- Modify: `tests/test_confirmation.py` (validator tests)

**Interfaces:**
- Produces: `triage.tools.validate_triage_completion(data: TriageData) -> str | None` — returns an `ERROR:`-prefixed string when a required field is missing, else `None`.
- Consumes: `triage.models.TriageData` (already has `phone_number`, `cpr_number`).

- [ ] **Step 1: Add failing validator tests**

Add to `tests/test_confirmation.py` after the notification tests (before the Runner section):

```python
# ---------------------------------------------------------------------------
# Task 2 — phone-required validation
# ---------------------------------------------------------------------------

def _booking_data(**kw):
    from triage.models import TriageData
    base = dict(
        condition_id=42, doctor="HS", has_referral=True,
        cpr_number="010190-1234", phone_number="12345678",
    )
    base.update(kw)
    return TriageData(**base)


@test
def test_validator_ok_for_complete_booking():
    from triage.tools import validate_triage_completion
    assert validate_triage_completion(_booking_data()) is None


@test
def test_validator_rejects_empty_phone():
    from triage.tools import validate_triage_completion
    err = validate_triage_completion(_booking_data(phone_number=None))
    assert err and "phone_number is required" in err, err


@test
def test_validator_rejects_empty_phone_on_escalation():
    from triage.tools import validate_triage_completion
    err = validate_triage_completion(
        _booking_data(escalate=True, phone_number=None, condition_id=None, doctor=None)
    )
    assert err and "phone_number is required" in err, err


@test
def test_validator_still_rejects_empty_cpr():
    from triage.tools import validate_triage_completion
    err = validate_triage_completion(_booking_data(cpr_number=None))
    assert err and "cpr_number is required" in err, err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m tests.test_confirmation`
Expected: ERRORs — `cannot import name 'validate_triage_completion' from 'triage.tools'`.

- [ ] **Step 3: Extract the validator and add the phone gate**

In `triage/tools.py`, replace the entire `complete_triage` function body (the current `@function_tool def complete_triage(...)` block) with a pure validator plus a thin tool wrapper. The CPR/condition/doctor/referral/insurance ERROR strings are copied **verbatim** from the existing code; only the new `phone_number` gate is added.

```python
def validate_triage_completion(data: TriageData) -> str | None:
    """Pure validation for complete_triage. Returns an ERROR string, or None if OK."""
    # CPR is required for EVERY case (booking and escalation) so staff don't have to call back.
    if not data.cpr_number:
        return (
            "ERROR: cpr_number is required for ALL cases. You MUST ask the patient for "
            "their CPR number (10 digits): \"Could I have your CPR number?\" / "
            "\"Må jeg få dit CPR-nummer?\". Store it in cpr_number. "
            "If the patient explicitly refuses or genuinely cannot provide it (or is a "
            "distressed Category A emergency), set cpr_number=\"declined\" so staff can "
            "follow up. Do NOT call complete_triage with an empty cpr_number."
        )
    # Phone is required for EVERY case — it is the SMS target for the booking confirmation.
    if not data.phone_number:
        return (
            "ERROR: phone_number is required for ALL cases. You MUST ask the patient for "
            "a mobile number we can reach them on (used to send the booking confirmation "
            "SMS): \"What is the best mobile number to reach you on?\" / "
            "\"Hvilket mobilnummer kan vi bedst kontakte dig på?\". Store it in "
            "phone_number. Do NOT call complete_triage with an empty phone_number."
        )
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
        # Referral/insurance check: for non-abortion conditions, referral must be explicitly asked
        if data.condition_id != 5 and data.has_referral is None:
            return (
                "ERROR: has_referral is required. You MUST ask the patient: "
                "\"Do you have a referral from your doctor?\" (\"Har du en henvisning fra din læge?\"). "
                "Set has_referral=true if yes, has_referral=false if no. "
                "If no referral, also ask about insurance (the yellow card) to check for DSS."
            )
        # For abortion (condition 5), insurance_type must be set (yellow card question)
        if data.condition_id == 5 and data.insurance_type is None:
            return (
                "ERROR: insurance_type is required for abortion cases. You MUST ask the patient: "
                "\"Do you have public health insurance (det gule sygesikringskort)?\" "
                "Set insurance_type=\"public\" or insurance_type=\"dss\"."
            )
    return None


@function_tool
def complete_triage(data: TriageData) -> str:
    """Call this when you have collected all required information from the patient.
    Fill in ALL fields you have gathered. For escalations, set escalate=true and provide escalation_reason."""
    error = validate_triage_completion(data)
    if error:
        return error
    return data.model_dump_json()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m tests.test_confirmation`
Expected: `8/8 passed`.

- [ ] **Step 5: Update the triage prompt so the agent treats phone as mandatory**

In `triage/agents.py`, replace the step-2 line:

```
2. PHONE NUMBER — "And a phone number where we can reach you?"
```

with:

```
2. PHONE NUMBER — MANDATORY for every patient. Ask: "And a mobile number where we can reach you?" / "Hvilket mobilnummer kan vi kontakte dig på?" This is the number we send the booking confirmation SMS to, so it is required for every case (booking and escalation).
```

Then, in the `=== RULES ===` section, add a line immediately after the existing CPR rule line (`- ALWAYS collect the CPR number (step 3) ...`):

```
- ALWAYS collect a mobile phone number (step 2) for every patient — complete_triage rejects an empty phone_number. It is the SMS target for the booking confirmation.
```

- [ ] **Step 6: Verify the prompt builds and still rejects empty phone**

Run:
```bash
python -c "from triage import agents; p=agents._build_triage_instructions(); assert 'MANDATORY for every patient' in p and 'SMS target for the booking confirmation' in p; print('prompt OK')"
python -m tests.test_confirmation
```
Expected: `prompt OK` then `8/8 passed`.

- [ ] **Step 7: Commit**

```bash
git add triage/tools.py triage/agents.py tests/test_confirmation.py
git commit -m "feat: require phone_number at triage (SMS target for confirmation)"
```

---

### Task 3: SessionStore confirmation lifecycle

**Files:**
- Modify: `triage/session_store.py` (imports, migration columns, helpers, methods, enrichment)
- Modify: `tests/test_confirmation.py` (store tests)

**Interfaces:**
- Produces:
  - `triage.session_store.effective_confirmation_status(row: dict, now: datetime | None = None) -> str`
  - `triage.session_store.confirmation_hours_left(row: dict, now: datetime | None = None) -> float | None`
  - `SessionStore.mark_booked(session_id) -> dict` → `{"ok": True, "token": str, "phone": str}` or `{"ok": False, "error": str}`
  - `SessionStore.confirm_by_token(token) -> dict` → `{"status": "confirmed"|"expired"|"already_confirmed"|"cancelled"|"invalid", "session_id"?: str}`
  - `SessionStore.cancel_booking(session_id) -> dict` → `{"ok": True, "status": "cancelled"}` or `{"ok": False, "error": str}`
  - `get_session`/`list_inbox` rows gain `confirmation` (effective status) and `confirmation_hours_left`.
- Consumes: `triage.config.CONFIRMATION_TTL_HOURS`.

- [ ] **Step 1: Add failing store tests**

Add to `tests/test_confirmation.py` after the Task 2 tests (before the Runner section):

```python
# ---------------------------------------------------------------------------
# Task 3 — SessionStore confirmation lifecycle
# ---------------------------------------------------------------------------

def _store():
    from triage.session_store import SessionStore
    d = tempfile.mkdtemp()
    return SessionStore(Path(d) / "dash.db")


def _seed_booking(store, sid="s1", phone="12345678", result_type="booking"):
    store.create_session(sid)
    store.update_session(sid, status="completed", result_type=result_type, patient_name="Test")
    store.save_result(sid, json.dumps({"triage": {"phone_number": phone, "patient_name": "Test"}}))


@test
def test_mark_booked_sets_pending_and_returns_phone():
    s = _store(); _seed_booking(s)
    res = s.mark_booked("s1")
    assert res["ok"] and res["token"] and res["phone"] == "12345678", res
    assert s.get_session("s1")["confirmation"] == "pending"


@test
def test_mark_booked_rejects_no_phone():
    s = _store(); _seed_booking(s, phone=None)
    res = s.mark_booked("s1")
    assert not res["ok"] and res["error"] == "no phone on file", res


@test
def test_mark_booked_rejects_non_booking():
    s = _store(); _seed_booking(s, result_type="handoff")
    res = s.mark_booked("s1")
    assert not res["ok"] and res["error"] == "not a booking", res


@test
def test_confirm_by_token_happy_path():
    s = _store(); _seed_booking(s)
    tok = s.mark_booked("s1")["token"]
    assert s.confirm_by_token(tok)["status"] == "confirmed"
    assert s.get_session("s1")["confirmation"] == "confirmed"


@test
def test_confirm_twice_is_already_confirmed():
    s = _store(); _seed_booking(s)
    tok = s.mark_booked("s1")["token"]
    s.confirm_by_token(tok)
    assert s.confirm_by_token(tok)["status"] == "already_confirmed"


@test
def test_confirm_unknown_token_is_invalid():
    s = _store()
    assert s.confirm_by_token("nope")["status"] == "invalid"


@test
def test_expiry_derived_and_confirm_returns_expired():
    from triage.config import CONFIRMATION_TTL_HOURS
    s = _store(); _seed_booking(s)
    tok = s.mark_booked("s1")["token"]
    old = (datetime.now(timezone.utc) - timedelta(hours=CONFIRMATION_TTL_HOURS + 1)).isoformat()
    with sqlite3.connect(s.db_path) as c:
        c.execute("UPDATE sessions SET confirmation_sent_at=? WHERE session_id='s1'", (old,))
        c.commit()
    assert s.get_session("s1")["confirmation"] == "expired"
    assert s.confirm_by_token(tok)["status"] == "expired"


@test
def test_cancel_booking_sets_cancelled():
    s = _store(); _seed_booking(s)
    s.mark_booked("s1")
    res = s.cancel_booking("s1")
    assert res["ok"] and res["status"] == "cancelled", res
    assert s.get_session("s1")["confirmation"] == "cancelled"


@test
def test_list_inbox_exposes_confirmation():
    s = _store(); _seed_booking(s)
    s.mark_booked("s1")
    row = next(r for r in s.list_inbox() if r["session_id"] == "s1")
    assert row["confirmation"] == "pending"
    assert row["confirmation_hours_left"] is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m tests.test_confirmation`
Expected: ERRORs — `'SessionStore' object has no attribute 'mark_booked'`.

- [ ] **Step 3: Add imports + module-level helpers**

In `triage/session_store.py`, ensure the top imports include `secrets`, `timezone`, `timedelta`, and the TTL config. The existing imports already include `json`, `sqlite3`, `Path`, and `from datetime import datetime`. Update them to:

```python
import json
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from triage.config import CONFIRMATION_TTL_HOURS
from triage.models import SessionMeta
```

(Keep any other existing imports; only add `secrets`, the `timezone, timedelta` additions, and the `CONFIRMATION_TTL_HOURS` import. If `SessionMeta` is already imported, leave that line as-is.)

Then add these two module-level helpers immediately above the `class SessionStore:` line:

```python
def effective_confirmation_status(row: dict, now: datetime | None = None) -> str:
    """Derive 'expired' from a pending row past the TTL; otherwise the stored status.
    A NULL/absent stored value is treated as 'none'."""
    status = row.get("confirmation_status") or "none"
    if status == "pending":
        sent = row.get("confirmation_sent_at")
        if sent:
            now = now or datetime.now(timezone.utc)
            try:
                sent_dt = datetime.fromisoformat(sent)
            except ValueError:
                return status
            if now - sent_dt > timedelta(hours=CONFIRMATION_TTL_HOURS):
                return "expired"
    return status


def confirmation_hours_left(row: dict, now: datetime | None = None) -> float | None:
    """Hours remaining in the 48h window for a pending row; None otherwise."""
    if (row.get("confirmation_status") or "none") != "pending":
        return None
    sent = row.get("confirmation_sent_at")
    if not sent:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        sent_dt = datetime.fromisoformat(sent)
    except ValueError:
        return None
    remaining = timedelta(hours=CONFIRMATION_TTL_HOURS) - (now - sent_dt)
    return max(0.0, remaining.total_seconds() / 3600.0)
```

- [ ] **Step 4: Add the migration columns**

In `_ensure_session_columns`, extend the `migrations` dict (which currently holds `processing_status`, `processed_by`, `processing_updated_at`, `urgency`) with:

```python
            "confirmation_status": "TEXT DEFAULT 'none'",
            "confirmation_token": "TEXT",
            "confirmation_sent_at": "TEXT",
            "confirmation_confirmed_at": "TEXT",
            "confirmation_cancelled_at": "TEXT",
```

- [ ] **Step 5: Add the three lifecycle methods**

Add these methods to the `SessionStore` class (e.g. right after `save_result`):

```python
    def mark_booked(self, session_id: str) -> dict:
        """Generate a confirmation token, set status=pending, sent_at=now.
        Returns {ok, token, phone} or {ok: False, error}."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT result_type, result_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "not found"}
            if (row["result_type"] or "") != "booking":
                return {"ok": False, "error": "not a booking"}
            phone = None
            if row["result_json"]:
                try:
                    triage = (json.loads(row["result_json"]) or {}).get("triage") or {}
                    phone = triage.get("phone_number")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    phone = None
            if not phone:
                return {"ok": False, "error": "no phone on file"}
            token = secrets.token_urlsafe(24)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='pending', confirmation_token=?, "
                "confirmation_sent_at=?, confirmation_confirmed_at=NULL, "
                "confirmation_cancelled_at=NULL WHERE session_id=?",
                (token, now, session_id),
            )
            conn.commit()
        return {"ok": True, "token": token, "phone": phone}

    def confirm_by_token(self, token: str) -> dict:
        """Patient confirms via token. Returns
        {status: confirmed|expired|already_confirmed|cancelled|invalid, session_id?}."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE confirmation_token = ?", (token,)
            ).fetchone()
            if row is None:
                return {"status": "invalid"}
            d = dict(row)
            stored = d.get("confirmation_status") or "none"
            if stored == "confirmed":
                return {"status": "already_confirmed", "session_id": d["session_id"]}
            if stored == "cancelled":
                return {"status": "cancelled", "session_id": d["session_id"]}
            if effective_confirmation_status(d) == "expired":
                return {"status": "expired", "session_id": d["session_id"]}
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='confirmed', "
                "confirmation_confirmed_at=? WHERE session_id=?",
                (now, d["session_id"]),
            )
            conn.commit()
            return {"status": "confirmed", "session_id": d["session_id"]}

    def cancel_booking(self, session_id: str) -> dict:
        """Secretary marks a booking cancelled (record-keeping; external slot
        release is manual). Returns {ok, status} or {ok: False, error}."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "not found"}
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE sessions SET confirmation_status='cancelled', "
                "confirmation_cancelled_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
        return {"ok": True, "status": "cancelled"}
```

- [ ] **Step 6: Enrich `get_session` and `list_inbox`**

In `get_session`, change the final `return dict(row)` to:

```python
        result = dict(row)
        result["confirmation"] = effective_confirmation_status(result)
        result["confirmation_hours_left"] = confirmation_hours_left(result)
        return result
```

In `list_inbox`, add the confirmation columns to the SELECT — change the column list from:

```python
                "result_type, processing_status, processed_by, processing_updated_at, urgency, "
                "result_json "
```

to:

```python
                "result_type, processing_status, processed_by, processing_updated_at, urgency, "
                "confirmation_status, confirmation_sent_at, confirmation_confirmed_at, "
                "confirmation_cancelled_at, result_json "
```

Then, inside the `for r in rows:` loop, after `row["doctor"] = doctor` and before `enriched.append(row)`, add:

```python
            row["confirmation"] = effective_confirmation_status(row)
            row["confirmation_hours_left"] = confirmation_hours_left(row)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m tests.test_confirmation`
Expected: `18/18 passed`.

- [ ] **Step 8: Commit**

```bash
git add triage/session_store.py tests/test_confirmation.py
git commit -m "feat: confirmation lifecycle on SessionStore (book/confirm/cancel/expiry)"
```

---

### Task 4: API routes + public confirm page

**Files:**
- Modify: `triage/auth.py:19` (add `/confirm/` to public prefixes)
- Modify: `triage/api.py` (imports + 4 routes)
- Create: `templates/confirm.html`
- Modify: `tests/test_confirmation.py` (TestClient route test, skips if `httpx` missing)

**Interfaces:**
- Consumes: `store.mark_booked`, `store.confirm_by_token`, `store.cancel_booking`, `store.get_result`; `build_confirmation_message`, `build_confirmation_url`, `get_sms_sender`.
- Produces (HTTP):
  - `POST /api/sessions/{id}/book` → `{ok, confirmation: "pending", confirm_url}` or 400 `{error}`
  - `POST /api/sessions/{id}/cancel` → `{ok, confirmation: "cancelled"}` or 400 `{error}`
  - `GET /confirm/{token}` → `confirm.html` (state `prompt`)
  - `POST /confirm/{token}` → `confirm.html` (state from `confirm_by_token`)

- [ ] **Step 1: Add the failing route test**

Add to `tests/test_confirmation.py` after the Task 3 tests:

```python
# ---------------------------------------------------------------------------
# Task 4 — API routes (public confirm page)
# ---------------------------------------------------------------------------

@test
def test_confirm_route_public_and_confirms():
    try:
        from fastapi.testclient import TestClient
    except Exception:  # noqa: BLE001
        print("  (skipped: TestClient/httpx unavailable)")
        return
    import triage.api as api_mod
    from triage.session_store import SessionStore

    d = tempfile.mkdtemp()
    temp = SessionStore(Path(d) / "dash.db")
    temp.create_session("apis1")
    temp.update_session("apis1", status="completed", result_type="booking", patient_name="T")
    temp.save_result("apis1", json.dumps({"triage": {"phone_number": "12345678", "language": "da"}}))

    orig = api_mod.store
    api_mod.store = temp
    try:
        client = TestClient(api_mod.app)
        # /book requires auth -> 401 without cookie
        assert client.post("/api/sessions/apis1/book").status_code == 401
        # mint a token directly, then confirm via the PUBLIC route (no auth)
        token = temp.mark_booked("apis1")["token"]
        assert client.get(f"/confirm/{token}").status_code == 200
        r = client.post(f"/confirm/{token}")
        assert r.status_code == 200 and ("Bekræftet" in r.text or "Confirmed" in r.text), r.text[:200]
        assert temp.get_session("apis1")["confirmation"] == "confirmed"
    finally:
        api_mod.store = orig
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m tests.test_confirmation`
Expected: the new test ERRORs (404 on `/confirm/...`, or template missing) — or prints the skip line if `httpx` is not installed. If skipped, rely on the manual check in Step 7.

- [ ] **Step 3: Make `/confirm/` public**

In `triage/auth.py` line 19, change:

```python
EXEMPT_PREFIXES = ("/static/",)
```

to:

```python
EXEMPT_PREFIXES = ("/static/", "/confirm/")
```

- [ ] **Step 4: Add API imports**

In `triage/api.py`, add to the imports block (after `from triage.orchestrator import run_agent_turn`):

```python
from triage.notifications import get_sms_sender, build_confirmation_message, build_confirmation_url
```

- [ ] **Step 5: Add the four routes**

In `triage/api.py`, add these routes immediately after the existing `PATCH /api/sessions/{session_id}/processing` route:

```python
@app.post("/api/sessions/{session_id}/book")
async def api_book(session_id: str):
    from fastapi.responses import JSONResponse
    res = store.mark_booked(session_id)
    if not res.get("ok"):
        return JSONResponse({"error": res.get("error", "could not book")}, status_code=400)
    result = store.get_result(session_id) or {}
    lang = (result.get("triage") or {}).get("language") or "da"
    body = build_confirmation_message(res["token"], lang)
    get_sms_sender().send(res["phone"], body)
    return {"ok": True, "confirmation": "pending", "confirm_url": build_confirmation_url(res["token"])}


@app.post("/api/sessions/{session_id}/cancel")
async def api_cancel(session_id: str):
    from fastapi.responses import JSONResponse
    res = store.cancel_booking(session_id)
    if not res.get("ok"):
        return JSONResponse({"error": res.get("error", "could not cancel")}, status_code=400)
    return {"ok": True, "confirmation": "cancelled"}


@app.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_get(request: Request, token: str):
    return templates.TemplateResponse(
        "confirm.html", {"request": request, "token": token, "state": "prompt"}
    )


@app.post("/confirm/{token}", response_class=HTMLResponse)
async def confirm_post(request: Request, token: str):
    res = store.confirm_by_token(token)
    return templates.TemplateResponse(
        "confirm.html", {"request": request, "token": token, "state": res["status"]}
    )
```

- [ ] **Step 6: Create the confirmation page**

Create `templates/confirm.html`:

```html
<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bekræft aftale / Confirm appointment</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; background:#f4f6f8; margin:0; color:#1f2933; }
    .card { max-width:440px; margin:8vh auto; background:#fff; border-radius:14px; padding:32px;
            box-shadow:0 6px 24px rgba(0,0,0,.08); text-align:center; }
    h1 { font-size:1.3rem; margin:0 0 8px; }
    p { line-height:1.5; color:#52606d; }
    .btn { display:inline-block; margin-top:18px; background:#2563eb; color:#fff; border:none;
           border-radius:8px; padding:14px 28px; font-size:1rem; cursor:pointer; }
    .btn:hover { background:#1d4ed8; }
    .ok { color:#15803d; } .warn { color:#b45309; } .err { color:#b91c1c; }
    .sub { font-size:.85rem; color:#9aa5b1; margin-top:20px; }
  </style>
</head>
<body>
  <div class="card">
    {% if state == 'prompt' %}
      <h1>Bekræft din aftale</h1>
      <p>Klik på knappen for at bekræfte din aftale hos Gynækologerne Skensved og Bune.</p>
      <p><em>Click below to confirm your appointment.</em></p>
      <form method="post" action="/confirm/{{ token }}">
        <button class="btn" type="submit">Bekræft / Confirm</button>
      </form>
    {% elif state == 'confirmed' %}
      <h1 class="ok">✓ Bekræftet / Confirmed</h1>
      <p>Tak! Din aftale er bekræftet.</p>
      <p><em>Thank you! Your appointment is confirmed.</em></p>
    {% elif state == 'already_confirmed' %}
      <h1 class="ok">✓ Allerede bekræftet / Already confirmed</h1>
      <p>Din aftale er allerede bekræftet.</p>
      <p><em>Your appointment was already confirmed.</em></p>
    {% elif state == 'expired' %}
      <h1 class="warn">Linket er udløbet / Link expired</h1>
      <p>Bekræftelsesfristen er overskredet. Klinikken kontakter dig.</p>
      <p><em>The confirmation window has passed. The clinic will contact you.</em></p>
    {% elif state == 'cancelled' %}
      <h1 class="err">Aftale annulleret / Appointment cancelled</h1>
      <p>Denne aftale er annulleret. Kontakt klinikken ved spørgsmål.</p>
      <p><em>This appointment has been cancelled. Please contact the clinic.</em></p>
    {% else %}
      <h1 class="err">Ugyldigt link / Invalid link</h1>
      <p>Dette bekræftelseslink er ugyldigt.</p>
      <p><em>This confirmation link is not valid.</em></p>
    {% endif %}
    <div class="sub">Gynækologerne Skensved og Bune</div>
  </div>
</body>
</html>
```

- [ ] **Step 7: Verify**

Run:
```bash
python -c "import triage.api; print('api imports OK')"
python -m tests.test_confirmation
```
Expected: `api imports OK`, then `19/19 passed` (the route test passes; or it prints the skip line and the count is `18/18 passed` with one skip — in that case do the manual check below).

Manual fallback (only if the TestClient test skipped): `source .venv/bin/activate && python main.py`, then in a browser open `http://localhost:8000/confirm/bogustoken` — expect the bilingual "Invalid link / Ugyldigt link" page **without** being redirected to login (proves the public exemption works).

- [ ] **Step 8: Commit**

```bash
git add triage/auth.py triage/api.py templates/confirm.html tests/test_confirmation.py
git commit -m "feat: book/cancel API + public SMS confirmation page"
```

---

### Task 5: Inbox UI — confirmation badges and actions

**Files:**
- Modify: `static/js/inbox-board.js`
- Modify: `static/css/style.css` (append confirmation styles)
- Modify: `templates/inbox.html:47` (cache-bust `inbox-board.js`)

**Interfaces:**
- Consumes: inbox rows now include `confirmation` and `confirmation_hours_left`; `POST /api/sessions/{id}/book` returns `{confirm_url}`; `POST /api/sessions/{id}/cancel`.
- Produces: per-booking-card badge + "Mark booked" / "Cancelled" buttons; expired cards sort to the top; cancelled cards leave the active board.

- [ ] **Step 1: Add confirmation helpers and update sort/placement**

In `static/js/inbox-board.js`, after the line `function isUrgent(r) { ... }` (line 18), add:

```javascript
  const CONF = { none: '', pending: 'Awaiting confirmation', confirmed: 'Confirmed ✓',
                 expired: 'Unconfirmed — follow up', cancelled: 'Cancelled' };
  function confOf(r) { return r.confirmation || 'none'; }
  function isBooking(r) { return (r.result_type || '') === 'booking'; }
  function needsAttention(r) { return isUrgent(r) || confOf(r) === 'expired'; }
  function isClosed(r) { return statusOf(r) === 'done' || confOf(r) === 'cancelled'; }
  function confBadge(r) {
    const c = confOf(r);
    if (!isBooking(r) || c === 'none') return '';
    let txt = CONF[c];
    if (c === 'pending' && r.confirmation_hours_left != null) {
      txt += ' · ' + Math.ceil(r.confirmation_hours_left) + 'h left';
    }
    return `<span class="conf-badge conf-${c}">${esc(txt)}</span>`;
  }
  function confActions(r) {
    if (!isBooking(r)) return '';
    const c = confOf(r);
    if (c === 'none') return `<button class="conf-book" title="Mark booked & send SMS">Mark booked</button>`;
    if (c === 'expired') return `<button class="conf-cancel" title="Mark cancelled">Cancelled</button>`;
    return '';
  }
```

Then replace the existing `sortCards` function with one that pins expired/urgent to the top:

```javascript
  function sortCards(a, b) {
    const ua = needsAttention(a) ? 0 : 1, ub = needsAttention(b) ? 0 : 1;
    if (ua !== ub) return ua - ub;
    return (b.created_at || '').localeCompare(a.created_at || '');
  }
```

- [ ] **Step 2: Show the badge + actions on each card**

In `cardHtml`, replace the `card-meta` and `card-actions` blocks. Change:

```javascript
        <div class="card-meta">
          ${t ? `<span class="type-badge type-${esc(t)}">${esc(t)}</span>` : ''}
          ${r.processed_by ? `<span class="card-by">${esc(r.processed_by)}</span>` : ''}
        </div>
      </div>
      <div class="card-actions">
```

to:

```javascript
        <div class="card-meta">
          ${t ? `<span class="type-badge type-${esc(t)}">${esc(t)}</span>` : ''}
          ${confBadge(r)}
          ${r.processed_by ? `<span class="card-by">${esc(r.processed_by)}</span>` : ''}
        </div>
      </div>
      <div class="card-actions">
        ${confActions(r)}
```

- [ ] **Step 3: Treat cancelled as closed in board placement**

In `render`, change:

```javascript
    const activeRows = visible.filter(r => statusOf(r) !== 'done');
    const doneRows = visible.filter(r => statusOf(r) === 'done');
```

to:

```javascript
    const activeRows = visible.filter(r => !isClosed(r));
    const doneRows = visible.filter(r => isClosed(r));
```

- [ ] **Step 4: Bind the new buttons and add the handlers**

In `bindCards`, inside the `forEach(card => { ... })` block, after the `adv` handler lines, add:

```javascript
      const bookBtn = card.querySelector('.conf-book');
      if (bookBtn) bookBtn.onclick = (e) => { e.stopPropagation(); bookCard(sid); };
      const cancelBtn = card.querySelector('.conf-cancel');
      if (cancelBtn) cancelBtn.onclick = (e) => { e.stopPropagation(); cancelCard(sid); };
```

Then add these two functions immediately after the `moveCard` function:

```javascript
  function bookCard(sessionId) {
    fetch(`/api/sessions/${sessionId}/book`, { method: 'POST' }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { showError(data.error || 'Could not send confirmation.'); return; }
      if (data.confirm_url) window.prompt('Confirmation SMS sent. Demo link:', data.confirm_url);
      load();
    }).catch(() => showError('Could not send confirmation.'));
  }

  function cancelCard(sessionId) {
    if (!window.confirm('Mark this booking cancelled? Release the slot in the clinic system first.')) return;
    fetch(`/api/sessions/${sessionId}/cancel`, { method: 'POST' }).then(async r => {
      if (!r.ok) { const d = await r.json().catch(() => ({})); showError(d.error || 'Could not cancel.'); return; }
      load();
    }).catch(() => showError('Could not cancel.'));
  }
```

- [ ] **Step 5: Add styles**

Append to `static/css/style.css`:

```css
/* Booking confirmation badges + actions */
.conf-badge { display:inline-block; font-size:.7rem; padding:2px 7px; border-radius:10px;
  margin-left:6px; font-weight:600; }
.conf-pending { background:#fef3c7; color:#92400e; }
.conf-confirmed { background:#dcfce7; color:#166534; }
.conf-expired { background:#fee2e2; color:#991b1b; }
.conf-cancelled { background:#e5e7eb; color:#4b5563; }
.conf-book, .conf-cancel { font-size:.72rem; border:1px solid #d1d5db; background:#fff;
  border-radius:6px; padding:3px 8px; cursor:pointer; }
.conf-book:hover { background:#eff6ff; border-color:#2563eb; color:#2563eb; }
.conf-cancel:hover { background:#fef2f2; border-color:#b91c1c; color:#b91c1c; }
```

- [ ] **Step 6: Cache-bust the script**

In `templates/inbox.html` line 47, change:

```html
<script src="/static/js/inbox-board.js"></script>
```

to:

```html
<script src="/static/js/inbox-board.js?v=20260624a"></script>
```

- [ ] **Step 7: Verify manually**

Run `source .venv/bin/activate && python main.py`. In the browser:
1. Complete a triage chat at `/` that produces a **booking** (e.g. a referred cystoscopy). Provide a phone number.
2. Open `/inbox` → the card shows a **"Mark booked"** button.
3. Click it → a prompt shows the demo confirm link; the badge becomes **"Awaiting confirmation · 48h left"**; the SMS body is printed in the server console.
4. Open the link → click **Bekræft / Confirm** → success page. Reload `/inbox` → badge is green **"Confirmed ✓"**.
5. (Expiry) For a second booking, mark it booked, then verify that after the TTL it shows red **"Unconfirmed — follow up"** pinned to the top with a **"Cancelled"** button. (To test without waiting 48h, temporarily set `CONFIRMATION_TTL_HOURS=0` in `.env` and restart.)

- [ ] **Step 8: Commit**

```bash
git add static/js/inbox-board.js static/css/style.css templates/inbox.html
git commit -m "feat: inbox confirmation badges, mark-booked and cancel actions"
```

---

### Task 6: Documentation + final verification

**Files:**
- Create: `.env.example`
- Modify: `CLAUDE.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Create `.env.example`**

Create `.env.example`:

```bash
# LLM
OPENAI_API_KEY=sk-...
TRIAGE_MODEL=gpt-5.4

# Demo auth
DEMO_USER=admin
DEMO_PASS=kvinde2026

# Booking confirmation (SMS)
SMS_PROVIDER=console               # console (demo) | twilio (not implemented)
PUBLIC_BASE_URL=http://localhost:8000
CONFIRMATION_TTL_HOURS=48
```

- [ ] **Step 2: Document the flow in CLAUDE.md**

In `CLAUDE.md`, under `## Domain-Specific Rules`, add these bullets after the existing **CPR number** bullet:

```markdown
- **Phone number:** Mandatory for every patient. `complete_triage` rejects an empty `phone_number` — it is the SMS target for the booking confirmation. (Multi-channel intake — WhatsApp/Facebook — is not built; the web chat is the only channel.)
- **Booking confirmation (SMS):** After triage, a session appears in the inbox. When the secretary clicks **"Mark booked & send SMS"**, the booking enters `pending` and a tokenized confirmation link is sent by SMS (console stub for the demo, via `triage/notifications.py`). The patient clicks the public `/confirm/{token}` page within `CONFIRMATION_TTL_HOURS` (48) to flip it to `confirmed`. Unconfirmed bookings read as `expired` (derived on read — no scheduler) and resurface at the top of the inbox; the secretary releases the slot in the clinic's own system and clicks **"Cancelled"** (a record-keeping state in this app only). `confirmation_status` is independent of the secretary's `processing_status` workflow.
```

- [ ] **Step 3: Final full-suite verification**

Run:
```bash
source .venv/bin/activate
python -m tests.test_confirmation
python -c "import triage.api; print('app import OK')"
```
Expected: all confirmation tests pass (`19/19 passed`, or `18/18` + one skip if `httpx` is absent) and `app import OK`.

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document booking-confirmation flow and env vars"
```

---

## Self-Review

**Spec coverage:**
- Phone mandatory → Task 2 ✅
- SMS pluggable sender + console stub + Twilio slot → Task 1 ✅
- `mark_booked`/`pending` + token + `sent_at` → Task 3 ✅
- Public `GET`+`POST /confirm/{token}` page (button, not bare GET) → Task 4 ✅
- `confirm_by_token` outcomes (confirmed/expired/already/cancelled/invalid) → Task 3 + Task 4 page states ✅
- Derived expiry (no scheduler) → Task 3 `effective_confirmation_status` ✅
- Manual `cancelled` state + action → Task 3 `cancel_booking`, Task 5 button ✅
- Confirmation independent of `processing_status` → enforced (no auto-done logic anywhere) ✅
- Inbox badges, expired pinned to top, cancelled leaves active board → Task 5 ✅
- AuthMiddleware exempts `/confirm/` → Task 4 ✅
- Migration via `_ensure_session_columns` → Task 3 ✅
- Scope = bookings only → `mark_booked` guards + `confBadge`/`confActions` `isBooking` checks ✅
- Tests (mark→confirm, double-confirm, expiry, cancel, invalid) → Task 3 ✅; phone enforcement via war games + validator tests ✅
- Env vars → Task 1 + Task 6 ✅

**Placeholder scan:** none — every code step has complete code.

**Type consistency:** `mark_booked` returns `{ok, token, phone}`; consumed in Task 4 as `res["token"]`/`res["phone"]` ✅. `confirm_by_token` returns `{status, session_id?}`; Task 4 reads `res["status"]` ✅. `confirmation`/`confirmation_hours_left` produced by Task 3 enrichment, consumed by Task 5 `confOf`/`confBadge` ✅. Page `state` values match `confirm_by_token` statuses plus `prompt` ✅.
