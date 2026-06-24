# Booking Confirmation via SMS — Design

**Date:** 2026-06-24
**Status:** Approved (design phase)
**Context:** Client-requested feature. System is in demo phase for Kvinde Klinikken / Gynækologerne Skensved og Bune.

## Problem

After triage produces a booking, a clinic secretary processes it and books the
appointment in the clinic's own (external) booking system. The client wants the
patient to receive a link they click to **confirm** the booked appointment
within **48 hours**. Patients who do not confirm in time should be surfaced back
to clinic staff for follow-up (the clinic phones them).

## Constraints & key decisions

- **Delivery channel: SMS** to the `phone_number` already collected during
  triage. No new patient field is needed. SMS is sent via a **pluggable
  provider**; for the demo we ship a **console/log stub** (`ConsoleSmsSender`).
  A real provider (e.g. Twilio) is a documented, env-selected slot, not built
  for the demo.
- **Trigger: secretary marks the case "booked."** The confirmation SMS is sent
  at that point — not at end of triage — because the patient is confirming an
  appointment the secretary has actually booked. Matches the client's wording
  ("confirm that they are processed by the clinic secretary and booked").
- **Patient click flips `booked (pending) → confirmed`.**
- **Expiry: no auto-cancel.** The app has no access to the clinic's booking
  system, so it cannot cancel anything. After 48h with no click, the case is
  shown as **`expired` (unconfirmed)** and resurfaces in the inbox so a
  secretary can phone the patient. A human decides what to do.
- **Expiry is derived on read**, not driven by a background job: a `pending`
  confirmation older than `CONFIRMATION_TTL_HOURS` is presented as `expired`
  whenever the inbox/session is read. No scheduler is added. (A scheduled sweep
  + SMS reminders can be added later if desired.)
- **Scope:** only `result_type == "booking"` sessions participate. Escalations
  / handoffs (`result_type == "handoff"`) have no appointment to confirm and are
  excluded.

## Lifecycle

```
none ──(secretary: "Mark booked & send SMS")──▶ pending ──(patient clicks link, POST)──▶ confirmed
                                                   │
                                                   └──(now > sent_at + 48h, no click)──▶ expired   [derived on read]
```

`confirmation_status` is independent of the existing secretary workflow
(`processing_status`: `new` / `in_progress` / `followup` / `done`). The two
dimensions coexist.

## Data model

Four new columns on the `sessions` table (dashboard.db), added through the
existing idempotent `_ensure_session_columns(conn)` migration — no manual
migration step:

| Column | Type | Meaning |
|---|---|---|
| `confirmation_status` | TEXT DEFAULT 'none' | `none` / `pending` / `confirmed` |
| `confirmation_token` | TEXT | random URL-safe token (`secrets.token_urlsafe`), unguessable, nullable |
| `confirmation_sent_at` | TEXT | ISO-8601 UTC timestamp the SMS went out |
| `confirmation_confirmed_at` | TEXT | ISO-8601 UTC timestamp the patient confirmed |

`expired` is **not stored**. A helper `effective_confirmation_status(row, now)`
returns `expired` when `confirmation_status == 'pending'` and
`now > sent_at + CONFIRMATION_TTL_HOURS`; otherwise the stored value.

## Components

### 1. Notifications module — `triage/notifications.py`

- `SmsSender` — interface with `send(to: str, body: str) -> None`.
- `ConsoleSmsSender` — demo default; logs recipient + body. The durable record
  is the token / `sent_at` on the session row.
- `get_sms_sender()` — factory reading `SMS_PROVIDER` env (default `"console"`).
  A `TwilioSmsSender` slot is documented but raises `NotImplementedError`
  until configured (not built for the demo).
- `build_confirmation_message(token, language) -> str` — bilingual (Danish +
  English) body containing `{PUBLIC_BASE_URL}/confirm/{token}` and a "valid 48
  hours" note.

New env vars (with defaults so the demo runs with no config):
`SMS_PROVIDER=console`, `PUBLIC_BASE_URL=http://localhost:8000`,
`CONFIRMATION_TTL_HOURS=48`.

### 2. Store methods — `triage/session_store.py`

- `mark_booked(session_id) -> dict` — generates a token, sets
  `confirmation_status='pending'`, `confirmation_token`, `confirmation_sent_at`.
  Parses `phone_number` from the stored `result_json` and returns
  `{token, phone}`. Returns an error indicator if there is no phone on file or
  the session is not a booking.
- `confirm_by_token(token) -> dict` — resolves the token. Outcomes:
  `confirmed` (success, sets `confirmed_at`), `expired`, `already_confirmed`,
  `invalid` (unknown token).
- `list_inbox` / `get_session` enrichment extended with effective
  `confirmation_status` and an `hours_left` value for `pending` rows.

### 3. API routes — `triage/api.py`

- `POST /api/sessions/{id}/book` *(behind login)* — secretary action:
  `mark_booked` then `get_sms_sender().send(phone, body)`. Returns the
  confirmation status and, for the demo, the generated confirm link so the
  secretary can see/copy it. 400 if no phone / not a booking.
- `GET /confirm/{token}` *(PUBLIC)* — renders `confirm.html` landing page with a
  "Confirm appointment" button.
- `POST /confirm/{token}` *(PUBLIC)* — performs the confirmation (button submit),
  so SMS link-preview scanners cannot auto-confirm via a GET. Renders
  success / expired / invalid / already-confirmed states.
- `AuthMiddleware` public allowlist extended with `/confirm` (the only
  patient-facing public surface), alongside existing `/login`, `/static`,
  `/health`.

### 4. Inbox UI — `static/js/inbox-board.js`, `templates/inbox.html`, `static/css/style.css`

Per booking card, a confirmation badge + action:

- `none` → **"Mark booked & send SMS"** button → `POST …/book`; on success the
  badge becomes `pending` and the demo link is shown.
- `pending` → "Awaiting confirmation · {N}h left" (amber).
- `confirmed` → "Confirmed ✓" (green).
- `expired` → **"Unconfirmed — follow up"** (red), **pinned to the top** of the
  board by reusing the existing urgent-sort ordering, so staff see it.

Escalation/handoff cards show no confirmation controls.

### 5. Confirmation page — `templates/confirm.html`

Standalone minimal page (no clinic nav, no login), bilingual (Danish +
English), with distinct success / expired / invalid / already-confirmed states.

## Data flow

```
Secretary clicks "Mark booked & send SMS" on an inbox card
  → POST /api/sessions/{id}/book
    → store.mark_booked(id)            # token + pending + sent_at
    → get_sms_sender().send(phone, build_confirmation_message(token, lang))
  → card shows "pending"; demo link returned for display

Patient opens SMS link
  → GET /confirm/{token}               # public landing page + button
  → POST /confirm/{token}
    → store.confirm_by_token(token)    # confirmed | expired | already | invalid
  → confirm.html renders the outcome

Secretary reloads inbox
  → GET /api/inbox
    → list_inbox() applies effective_confirmation_status (derives expired)
  → confirmed = green; expired = red + pinned to top
```

## Error handling & edge cases

- **No phone on file** (patient declined): `book` returns 400; the card shows
  the reason; no token is created.
- **Not a booking** (`result_type == 'handoff'`): `book` is rejected; UI never
  offers the action for these.
- **Unknown / tampered token:** `invalid` page.
- **Double click / re-click after confirm:** `already_confirmed` page (idempotent;
  does not error).
- **Click after 48h:** `expired` page; the inbox already shows it as expired.
- **Re-booking:** calling `book` again on a `pending`/`expired` case regenerates
  the token and resets the 48h window (lets staff re-send). Confirmed cases are
  left as-is unless explicitly re-opened (out of scope for the demo).

## Testing

War games cover triage only, not this post-triage clinic + patient web flow, and
the repo has no pytest harness. Add a small **standalone verification script**
(e.g. `tests/test_confirmation.py`, runnable with `python -m`) that exercises
`SessionStore` against a temporary DB:

1. `mark_booked` → `pending`, token present, phone returned.
2. `confirm_by_token(token)` → `confirmed`, `confirmed_at` set.
3. Second `confirm_by_token(token)` → `already_confirmed`.
4. Expiry: a `pending` row with `sent_at` older than the TTL reads as `expired`
   and `confirm_by_token` returns `expired`.
5. Unknown token → `invalid`.

Plus a manual click-through of `/confirm/{token}` covering success/expired/invalid.

## Out of scope (demo)

- Real SMS provider integration (Twilio) — documented slot only.
- Scheduled expiry sweep and SMS reminders.
- Inbound SMS ("reply to confirm").
- Cancelling/releasing slots in the clinic's external booking system.
- Re-confirmation of already-confirmed appointments.

## Affected files

- New: `triage/notifications.py`, `templates/confirm.html`,
  `tests/test_confirmation.py`,
  `docs/superpowers/specs/2026-06-24-booking-confirmation-design.md`.
- Modified: `triage/session_store.py`, `triage/api.py`,
  `static/js/inbox-board.js`, `templates/inbox.html`, `static/css/style.css`,
  `.env.example` (or docs) for new env vars, `CLAUDE.md` (document the flow).
