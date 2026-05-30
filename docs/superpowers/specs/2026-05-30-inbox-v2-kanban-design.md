# Inbox v2 (Kanban) + Copy/Conversation Fixes — Design

**Date:** 2026-05-30
**Status:** Approved (pending spec review)
**Builds on:** `2026-05-29-clinic-dashboard-notes-and-inbox-design.md` (the original inbox + tester notes).

## Summary

Three changes to the clinic dashboard, delivered together:

1. **Fix the Copy button** in the shared session-detail modal — it silently fails in non-secure
   browsing contexts.
2. **Make the conversation transcript collapsible** in the detail modal — collapsed by default in
   the Inbox, expanded by default in History.
3. **Rebuild the Inbox as a Kanban board** — a 3-column active board (New / In progress / Needs
   follow-up) with a separate **Done** tab, card-based stage moves, filter chips, and search.

## Background / current state

- The Inbox (`templates/inbox.html`) is a flat table of actionable sessions
  (`status IN ('completed','escalated')`) from `SessionStore.list_inbox()`. Rows open a shared
  modal rendered by `static/js/session-detail.js`. Status changes happen inside the modal via
  `PATCH /api/sessions/{id}/processing`; the modal calls `window.InboxPage.refreshRow(id, proc, by)`
  to update the table live.
- `list_inbox()` returns `session_id, created_at, patient_name, status, condition_name,
  result_type, processing_status, processed_by, processing_updated_at, urgency`. It does **not**
  return phone or doctor (those live inside `result_json`), so the table's Phone/Doctor cells show
  "—".
- The processing vocabulary is fixed: `new | in_progress | followup | done` (validated by
  `ALLOWED_PROCESSING` in `triage/api.py`).
- **Copy bug:** `session-detail.js` `bindExport()` calls `navigator.clipboard.writeText(text)`
  directly. When the page is served over a non-secure context (e.g. opened via the host's LAN IP
  rather than `localhost`; the server binds `0.0.0.0`), `navigator.clipboard` is `undefined`, so the
  call throws synchronously and the `.then(...)` rejection fallback never runs — the button appears
  dead.

## Decisions (from brainstorming)

| Topic | Decision |
| --- | --- |
| Copy fix | Robust `copyText()` helper: Clipboard API when available + secure, else `<textarea>` + `execCommand('copy')`, else `prompt()`, all in try/catch |
| Conversation transcript | Native `<details>`; collapsed by default in Inbox, `<details open>` in History |
| Inbox layout | Kanban board replaces the table |
| Active board columns | 3: New, In progress, Needs follow-up |
| Done | Separate tab (hidden from the active board) |
| Card moves | `▸` advance to next stage + `⋯` menu to jump to any stage (incl. Done / reopen); no drag-and-drop |
| Filters | Type chips (All / Booking / Handoff), "Urgent only" toggle, search (name / condition / phone) |
| Doctor filter | Not included |
| Backend | Enrich `list_inbox()` to also surface `phone` and `doctor` from `result_json` (fixes "—", powers phone search) |

## Architecture

### 1. Backend — `triage/session_store.py`

Enrich `list_inbox()` so each row also carries `phone` and `doctor`, parsed from the session's
stored `result_json`:

- Add `result_json` to the existing `SELECT` in `list_inbox()`.
- For each row, parse the JSON (guarding against `None`/malformed). Pull
  `result["triage"]["phone_number"]` → `phone` and `result["triage"]["doctor"]` → `doctor`.
- Drop the raw `result_json` from the returned dict (keep the payload lean); add `phone` and
  `doctor` keys (default to `None` when absent).

No new columns, no migration, no API-signature change — `GET /api/inbox` simply returns two more
fields per row. `PATCH /api/sessions/{id}/processing` is unchanged.

### 2. Detail modal — `static/js/session-detail.js`

**Copy fix.** Introduce a module-level helper:

```
function copyText(text) -> Promise/sync best-effort
  - if navigator.clipboard && window.isSecureContext: use clipboard.writeText, on reject fall through
  - else create an off-screen <textarea>, select(), document.execCommand('copy'), remove()
  - if all else fails: window.prompt('Copy this text:', text)
  - wrap in try/catch; never throw to the caller
```

`bindExport()` calls `copyText(buildExportText(d))` and flashes "Copied!" on success.

**Collapsible conversation.** `renderConversation(d)` returns a `<details class="conv-details">`
wrapper with a `<summary>Conversation (N messages)</summary>`. The `open` attribute is present only
in History mode (`mode === 'history'`), absent in Inbox mode. The existing `.conversation-display`
markup stays inside.

No change to the `window.InboxPage.refreshRow(sessionId, proc, by)` contract — the board reimplements
that hook (below).

### 3. Inbox board — `templates/inbox.html` + new `static/js/inbox-board.js`

`inbox.html` becomes markup + a thin bootstrap that loads `session-detail.js` and `inbox-board.js`.
All board logic lives in `inbox-board.js` (keeps the template small, mirrors the `session-detail.js`
split).

**Layout:**

```
[ Active (6) | Done (5) ]        Type:[All][Booking][Handoff]  [ ] Urgent only   🔍 search

ACTIVE tab — 3 columns:
┌ New (3) ─────┐ ┌ In progress (2) ┐ ┌ Needs follow-up (1) ┐
│ card         │ │ card             │ │ card                │
└──────────────┘ └──────────────────┘ └─────────────────────┘

DONE tab — list/grid of done cards (each with ⋯ → reopen).
```

**Tabs.** Two views, `active` (default) and `done`, with live counts. The filter bar applies to the
currently visible tab.

**Card.** Renders: urgency flag (red dot for `escalated`/`immediate`, "High" tag for `high`,
nothing for `normal`), patient name, condition, a type badge (booking/handoff), and "handled by"
when set. Card body click → `SessionDetail.open(sessionId, 'inbox')`. Card footer has `▸` (advance)
and `⋯` (stage menu). Within a column, urgent cards sort first, then newest `created_at`.

**Stage order & moves.** Advance order is `['new','in_progress','followup','done']`. `▸` moves to
the next stage in that order (a `followup` card advances to `done`). `⋯` opens a small menu listing
all four stages (the current one disabled) — selecting one sets that status. Done-tab cards use `⋯`
to reopen to `new`/`in_progress`/`followup`. Both call
`PATCH /api/sessions/{id}/processing` with `{processing_status, processed_by}`, where `processed_by`
is the name from `localStorage['triage_tester_name']` (same key notes/processing already use; may be
empty/null). On success the card's DOM node is relocated to the destination column (or pulled to the
Done tab / back onto the board) and both tab counts + column counts are recomputed — no full reload.

**Filters.** Type chips (`All`/`Booking`/`Handoff`, mutually exclusive, default `All`), an
"Urgent only" checkbox (keeps cards with `status==='escalated' || urgency==='immediate'`), and a
search box matching `patient_name`, `condition_name`, or `phone` (case-insensitive substring). A
card is shown only if it passes all active filters. Column/tab counts reflect **visible** cards.
Empty columns show a muted placeholder.

**Live sync with the modal.** `window.InboxPage.refreshRow(sessionId, proc, by)` is reimplemented by
the board to relocate the matching card to the `proc` column / Done tab and update counts, so a
status change made inside the detail modal stays consistent with the board.

### 4. Styles — `static/css/style.css`

Add: board layout (flex row of columns, independent vertical scroll), column header + count, card,
urgency flag/tag, card action buttons + `⋯` menu, the tab switcher, filter chips + Urgent toggle +
search box, and the `<details>`/`<summary>` styling for the collapsible conversation. Bump the CSS
cache version in `templates/base.html` (current `?v=20260529a`).

## Data flow

```
Inbox page load
  → GET /api/inbox  (now includes phone + doctor)        [list_inbox enrichment]
  → inbox-board.js groups rows by processing_status:
       new/in_progress/followup → Active board columns
       done → Done tab
  → filter bar narrows visible cards + recomputes counts

Move a card (▸ or ⋯, on board or modal)
  → PATCH /api/sessions/{id}/processing {status, processed_by}
  → relocate card DOM + update counts (no reload)
```

## Error handling

- `copyText()` degrades Clipboard API → execCommand → prompt; wrapped in try/catch; the button
  never throws.
- A `PATCH` that returns non-2xx leaves the card where it was and surfaces a brief inline error;
  no optimistic move is committed until the request succeeds.
- `list_inbox()` JSON parse is guarded — a malformed/empty `result_json` yields `phone=None`,
  `doctor=None` rather than raising; the row still appears.
- Empty board/tab states render a muted placeholder, not an error.

## Testing

- **`list_inbox()` enrichment:** temp-DB Python script — create a completed session, save a
  `result_json` containing `triage.phone_number`/`triage.doctor`, assert the `list_inbox()` row
  surfaces `phone` and `doctor`; and that a row with no result still returns with `phone=None`.
- **`GET /api/inbox`:** authenticated `TestClient` — assert 200 and that rows include the `phone`
  and `doctor` keys.
- **Board / filters / copy / collapsible conversation:** manual, against a running server
  (`python main.py`), covering: cards land in the right columns; `▸` and `⋯` move cards and update
  counts; moving to Done removes from the board and appears under the Done tab; reopen works; type
  chips / Urgent toggle / search narrow correctly with live counts; Copy works over both `localhost`
  and the LAN IP; conversation is collapsed in the Inbox modal and expanded in History.

## Out of scope

- Drag-and-drop card moves (buttons + menu only).
- Persisting filter/tab state across reloads.
- Doctor filter.
- Capping/paginating the Done tab (it scrolls; newest first).
- Any change to the triage conversation, the `processing_status` vocabulary, or the notes feature.
