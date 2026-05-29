# Clinic Dashboard: Tester Notes + Patient Inbox — Design

**Date:** 2026-05-29
**Status:** Approved (pending spec review)

## Summary

Two related additions to the Kvinde Klinikken triage web app, delivered together because they
share the session-detail modal:

1. **Tester notes** — testers leave timestamped, authored comments on a chat session to record
   how the chat went. Multiple comments per session; each comment is editable and deletable.
2. **Patient inbox** — a new staff-facing work queue where finished patients (completed bookings
   and staff escalations) land for further processing, with a workflow status, urgency sorting,
   and export-to-clinic actions.

Both surface in a **shared session-detail modal** reused by the existing History page and the new
Inbox page.

## Background / current state

When a chat completes, `triage/api.py`'s WebSocket handler (`/ws/{session_id}`) already persists the
session to `dashboard.db` via `SessionStore`:

- `status` becomes `"completed"` (booking) or `"escalated"` (handoff). Unfinished chats stay
  `"active"`.
- `result_type` is `"booking"` or `"handoff"`.
- `result_json` holds the full `BookingRequest` / `HandoffRequest` dump.

The **History** page (`templates/history.html`) lists *all* sessions (including abandoned `active`
ones) in a table; clicking a row opens a detail modal that renders the conversation transcript and
the structured booking/handoff result. The modal's rendering logic is currently inline JS in
`history.html`.

There is one shared demo login (`DEMO_USER`/`DEMO_PASS`), so the app cannot distinguish individual
testers/staff from auth alone — authorship is captured by a typed name remembered in the browser.

## Decisions (from brainstorming)

| Topic | Decision |
| --- | --- |
| Notes granularity | Multiple timestamped comments per session (a comment log) |
| Comment authorship | Tester types a name per comment; remembered in `localStorage` |
| Comment edit/delete | Both edit and delete supported |
| Comment storage | New `comments` table in `dashboard.db` (not a JSON blob on the session row) |
| Inbox delivery model | In-app work queue **plus** export |
| Inbox workflow states | `new` → `in_progress` → `done`, plus `followup` (Needs follow-up) |
| Inbox page placement | New `/inbox` page; History stays as the raw all-sessions log |
| Urgency surfacing | One unified queue, urgent sorts to top + red "Urgent" badge |
| Export format | Copy-to-clipboard (formatted text) and Print/PDF (browser print) |

## Architecture

### 1. Data model — `triage/session_store.py` (`dashboard.db`)

**New `comments` table**, created in `_init_db`:

```sql
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    author      TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,   -- ISO UTC
    updated_at  TEXT             -- ISO UTC, NULL until first edit
);
CREATE INDEX IF NOT EXISTS idx_comments_session ON comments(session_id);
```

**New columns on the existing `sessions` table** for the inbox workflow:

```
processing_status      TEXT DEFAULT 'new'   -- 'new' | 'in_progress' | 'done' | 'followup'
processed_by           TEXT                 -- staff name
processing_updated_at  TEXT                 -- ISO UTC
urgency                TEXT                 -- 'immediate' | 'high' | 'normal'
```

Because existing `dashboard.db` files already have a `sessions` table, `_init_db` runs an idempotent
migration helper: read existing columns via `PRAGMA table_info(sessions)`, then
`ALTER TABLE sessions ADD COLUMN ...` for any that are missing. (SQLite `ADD COLUMN` with a constant
default is safe and fast.)

**New `SessionStore` methods:**

- `add_comment(session_id, author, body) -> dict` — inserts, returns the created comment row
  (including its new `id` and `created_at`).
- `list_comments(session_id) -> list[dict]` — oldest-first.
- `update_comment(comment_id, body) -> dict | None` — sets `body` + `updated_at`; returns the
  updated row, or `None` if no such comment.
- `delete_comment(comment_id) -> bool` — returns whether a row was deleted.
- `list_inbox() -> list[dict]` — sessions where `status IN ('completed','escalated')`, ordered by
  urgency rank (`immediate` < `high` < `normal` < NULL) then `created_at DESC`. Includes the new
  processing columns.
- `set_processing(session_id, processing_status, processed_by) -> dict | None` — updates
  `processing_status`, `processed_by`, `processing_updated_at`; returns the updated row or `None`.
- `set_urgency(session_id, urgency)` — sets the `urgency` column (called at completion).
- Extend `delete_inactive()` to also delete `comments` rows for the deleted sessions (no orphans).

Urgency sort rank is implemented in SQL with a `CASE` expression so `done` items still sort by
urgency within the queue.

### 2. Completion path change — `triage/api.py` WebSocket handler

The only change to the live triage path: when a triage completes, also record urgency.

- Handoff → `urgency = result_data["urgency"]` (the `HandoffRequest.urgency`).
- Booking → map from triage category: `B` → `"high"`, anything else (`C`) → `"normal"`.
  (Category `A` always escalates, so it arrives as a handoff with its own urgency.)

`processing_status` relies on its column default `'new'`, so no extra write is needed for it.

### 3. API routes — `triage/api.py` (behind existing `AuthMiddleware`)

```
GET    /inbox                            -> inbox.html page
GET    /api/inbox                        -> store.list_inbox()
PATCH  /api/sessions/{id}/processing     {processing_status, processed_by} -> updated row | 404
GET    /api/sessions/{id}/comments       -> store.list_comments(id)
POST   /api/sessions/{id}/comments       {author, body} -> created comment | 400
PUT    /api/comments/{id}                {body} -> updated comment | 400 | 404
DELETE /api/comments/{id}                -> {deleted: true} | 404
```

**Validation:** `author` and `body` are trimmed and must be non-empty → `400` otherwise.
`processing_status` must be one of the four allowed values → `400` otherwise. Missing
comment/session IDs → `404`. Export needs **no** server route — it is built client-side from the
existing `GET /api/sessions/{id}` payload.

### 4. UI

**Shared detail modal — `static/js/session-detail.js` (new).**
Extract the inline modal-rendering JS from `history.html` into a shared module that both History and
Inbox load. It renders the session detail (meta, conversation, booking/handoff result) and adds:

- **Tester Notes** section: the comment list (author • relative/ISO timestamp • body, each with
  Edit and Delete controls) and an add-comment form with a "Your name" field. The name is persisted
  to `localStorage` (key e.g. `triage_tester_name`) and pre-filled on next use. Add/edit/delete call
  the comment API and re-render the list in place — no page reload.
- **Export buttons:** *Copy* (assembles a clean labelled text summary — patient, phone, insurance,
  condition, category, doctor, prep/lab/questionnaire/self-pay or handoff reason/urgency/summary —
  and writes it to the clipboard via `navigator.clipboard`) and *Print* (a `@media print`
  stylesheet scopes printing to the modal card so the browser print dialog produces a clean
  one-patient sheet / PDF).
- **Processing controls** (shown when opened from the Inbox): the four status buttons and the
  processed-by name, calling `PATCH /api/sessions/{id}/processing`.

**Inbox page — `templates/inbox.html` (new).**
A table of `list_inbox()` rows: urgency badge (red "Urgent" for `immediate`/escalations), patient,
phone, condition, doctor, type badge (booking/handoff), processing-status control, processed-by,
date. Unified queue sorted urgent-first; `done` rows are dimmed but remain. Row click opens the
shared modal in inbox mode (with processing controls + export + notes).

**History page — `templates/history.html` (edit).**
Replace the inline modal JS with a load of `static/js/session-detail.js`, opening the modal in
history mode (notes + export available; processing controls hidden). Existing table and
clear-inactive behaviour unchanged.

**Nav — `templates/base.html` (edit).**
Add an "Inbox" nav item alongside Chat / History / Conditions, with an active-state block matching
the existing pattern.

**Styles — `static/`.**
Add styles for the inbox table, urgency/processing badges, the notes thread + form, export buttons,
and the print stylesheet, following the existing CSS conventions (bump the CSS cache version as the
project already does).

## Data flow

```
Patient finishes chat
  → WebSocket handler saves session (status, result_type, result_json) + urgency   [api.py]
  → session_status defaults processing_status='new'

Staff opens /inbox
  → GET /api/inbox  → urgent-sorted actionable sessions                            [SessionStore.list_inbox]
  → click row → GET /api/sessions/{id} → shared modal renders detail + notes + export
  → change status → PATCH /api/sessions/{id}/processing                            [SessionStore.set_processing]
  → Copy / Print → client-side from the fetched session JSON

Tester (History or Inbox) opens a session
  → notes thread loads → GET /api/sessions/{id}/comments
  → add/edit/delete → POST/PUT/DELETE comment routes                               [SessionStore comment methods]
```

## Error handling

- Comment create/edit with empty `author`/`body` → `400`; UI disables submit until both filled.
- Edit/delete of a missing comment, or processing update of a missing session → `404`; UI shows an
  inline error and leaves the list unchanged.
- `processing_status` outside the four allowed values → `400`.
- Clipboard failure (e.g. permissions) → fall back to a text selection / alert so the staffer can
  copy manually.
- The column migration is wrapped so a partially-upgraded DB re-runs cleanly (each `ADD COLUMN` is
  guarded by the `PRAGMA table_info` check).

## Testing

No unit-test harness exists; the project's test suite is the war games (AI-vs-AI). These features are
dashboard/CRUD and outside the triage conversation, so war games don't cover them. Verification is
manual against a running server:

- Complete a booking and a handoff chat; confirm both appear in `/inbox`, escalation sorts above the
  booking with the Urgent badge.
- Move a patient New → In progress → Needs follow-up → Done; reload and confirm persistence and that
  `done` rows dim.
- Add, edit, and delete comments on a session from both History and Inbox; confirm the author name
  persists across reloads via `localStorage`.
- Copy a patient and paste it; Print a patient and confirm a clean single-patient sheet.
- Run `clear-inactive` and confirm comments on deleted sessions are gone, completed/escalated
  sessions and their comments remain.
- Confirm an existing (pre-migration) `dashboard.db` upgrades without error on startup.

## Out of scope

- External integrations (email/webhook/PMS push) — export is copy/print only.
- Per-tester logins / real authentication — single shared demo login stays.
- CSV export — not requested.
- Surfacing comments in the live patient chat UI (`index.html`) — review-only.
- Editing the triage `status` taxonomy (`active`/`completed`/`escalated`) — `processing_status` is a
  separate dimension layered on top.
