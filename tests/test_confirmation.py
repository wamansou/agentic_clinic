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
