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
