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
