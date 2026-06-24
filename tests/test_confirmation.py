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
