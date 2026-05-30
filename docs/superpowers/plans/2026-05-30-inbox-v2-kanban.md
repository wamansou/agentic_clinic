# Inbox v2 (Kanban) + Copy/Conversation Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the modal Copy button, make the conversation transcript collapsible, and rebuild the Inbox as a 3-column Kanban board (New / In progress / Needs follow-up) with a separate Done tab, card stage-moves, filter chips, and search.

**Architecture:** One small backend change enriches `SessionStore.list_inbox()` with phone/doctor from the stored result JSON. The shared `static/js/session-detail.js` gets a robust clipboard helper and a `<details>`-based conversation. The Inbox board logic moves into a new `static/js/inbox-board.js` (mirroring the `session-detail.js` split), driven by re-render-on-state-change; `templates/inbox.html` becomes markup + a thin bootstrap. New CSS styles the board, tabs, filters, cards, and the menu.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`sqlite3` stdlib), Jinja2, vanilla JS, plain CSS. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-30-inbox-v2-kanban-design.md`

**Verification note:** No unit-test framework exists. The backend task is verified with a temp-DB Python script and an authenticated FastAPI `TestClient`. JS/CSS tasks are verified with file-presence/`grep` sanity checks plus `TestClient` page-serve checks, and a manual browser pass (the spec's stated approach). Activate the venv first: `source .venv/bin/activate`.

**Every commit message ends with:**
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## File Structure

- **Modify** `triage/session_store.py` — enrich `list_inbox()` with `phone` + `doctor`.
- **Modify** `static/js/session-detail.js` — `copyText()`/`fallbackCopy()` helpers, rewire `bindExport`, `<details>` conversation.
- **Create** `static/js/inbox-board.js` — the Kanban board (tabs, filters, cards, moves, `InboxPage.refreshRow`).
- **Modify** `templates/inbox.html` — board markup + bootstrap (load both JS files).
- **Modify** `static/css/style.css` — board/tabs/filters/card/menu/collapsible-conversation styles.
- **Modify** `templates/base.html` — bump CSS cache version.

---

## Task 1: Enrich `list_inbox()` with phone + doctor

**Files:**
- Modify: `triage/session_store.py`

- [ ] **Step 1: Replace the `list_inbox` method**

In `triage/session_store.py`, replace the entire existing `list_inbox` method with:

```python
    def list_inbox(self) -> list[dict]:
        """Actionable sessions (completed/escalated), urgent-first then newest.
        Each row is enriched with phone and doctor parsed from the stored result JSON."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, created_at, patient_name, status, condition_name, "
                "result_type, processing_status, processed_by, processing_updated_at, urgency, "
                "result_json "
                "FROM sessions WHERE status IN ('completed', 'escalated') "
                "ORDER BY CASE urgency "
                "  WHEN 'immediate' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
                "created_at DESC"
            ).fetchall()
        enriched = []
        for r in rows:
            row = dict(r)
            raw = row.pop("result_json", None)
            phone, doctor = None, None
            if raw:
                try:
                    triage = (json.loads(raw) or {}).get("triage") or {}
                    phone = triage.get("phone_number")
                    doctor = triage.get("doctor")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass
            row["phone"] = phone
            row["doctor"] = doctor
            enriched.append(row)
        return enriched
```

(`json` is already imported at the top of `session_store.py`.)

- [ ] **Step 2: Verify enrichment against a temp DB**

```bash
source .venv/bin/activate && python - <<'PY'
import tempfile, json
from triage.session_store import SessionStore
s = SessionStore(tempfile.mktemp(suffix='.db'))
s.create_session('p1'); s.update_session('p1', status='completed')
s.save_result('p1', json.dumps({"triage": {"phone_number": "12345678", "doctor": "HS"}}))
s.create_session('p2'); s.update_session('p2', status='escalated')  # no result saved
rows = {r['session_id']: r for r in s.list_inbox()}
assert rows['p1']['phone'] == '12345678' and rows['p1']['doctor'] == 'HS', rows['p1']
assert 'result_json' not in rows['p1'], rows['p1']
assert rows['p2']['phone'] is None and rows['p2']['doctor'] is None, rows['p2']
print('OK list_inbox enrichment')
PY
```
Expected: prints `OK list_inbox enrichment`.

- [ ] **Step 3: Verify `/api/inbox` returns the new fields**

```bash
source .venv/bin/activate && python - <<'PY'
import json
from fastapi.testclient import TestClient
from triage.api import app, store
from triage.auth import DEMO_USER, DEMO_PASS
store.create_session('p_api'); store.update_session('p_api', status='completed')
store.save_result('p_api', json.dumps({"triage": {"phone_number": "99", "doctor": "LB"}}))
c = TestClient(app); c.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})
rows = c.get('/api/inbox').json()
row = next(r for r in rows if r['session_id'] == 'p_api')
assert row['phone'] == '99' and row['doctor'] == 'LB', row
# cleanup
import sqlite3
from triage.config import DB_DIR
conn = sqlite3.connect(str(DB_DIR / 'dashboard.db'))
conn.execute("DELETE FROM sessions WHERE session_id = 'p_api'"); conn.commit(); conn.close()
print('OK /api/inbox phone+doctor')
PY
```
Expected: prints `OK /api/inbox phone+doctor`.

- [ ] **Step 4: Commit**

```bash
git add triage/session_store.py
git commit -m "feat: enrich inbox rows with phone and doctor from result JSON

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Copy fix + collapsible conversation (`session-detail.js`)

**Files:**
- Modify: `static/js/session-detail.js`

- [ ] **Step 1: Add `copyText` + `fallbackCopy` helpers**

In `static/js/session-detail.js`, find the `esc` helper near the top of the IIFE:

```javascript
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
```

Immediately after it, add:

```javascript
  function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
          () => flash('copyBtn', 'Copied!'),
          () => fallbackCopy(text)
        );
        return;
      }
    } catch (e) { /* fall through to legacy path */ }
    fallbackCopy(text);
  }

  function fallbackCopy(text) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) { flash('copyBtn', 'Copied!'); return; }
    } catch (e) { /* fall through to prompt */ }
    window.prompt('Copy this text:', text);
  }
```

- [ ] **Step 2: Rewire `bindExport` to use `copyText`**

Replace the existing `bindExport` function:

```javascript
  function bindExport(d) {
    document.getElementById('copyBtn').onclick = () => {
      const text = buildExportText(d);
      navigator.clipboard.writeText(text).then(
        () => flash('copyBtn', 'Copied!'),
        () => { window.prompt('Copy this text:', text); }
      );
    };
    document.getElementById('printBtn').onclick = () => window.print();
  }
```

with:

```javascript
  function bindExport(d) {
    document.getElementById('copyBtn').onclick = () => copyText(buildExportText(d));
    document.getElementById('printBtn').onclick = () => window.print();
  }
```

- [ ] **Step 3: Make the conversation collapsible**

Replace the existing `renderConversation` function:

```javascript
  function renderConversation(d) {
    if (!d.conversation || !d.conversation.length) return '';
    let h = '<div class="detail-result"><h4>Conversation</h4><div class="conversation-display">';
    for (const m of d.conversation) {
      const role = m.role === 'user' ? 'patient' : 'agent';
      h += `<div class="conv-msg conv-msg-${role}"><div class="conv-bubble conv-bubble-${role}">${esc(m.content)}</div></div>`;
    }
    h += '</div></div>';
    return h;
  }
```

with:

```javascript
  function renderConversation(d) {
    if (!d.conversation || !d.conversation.length) return '';
    const openAttr = mode === 'history' ? ' open' : '';
    const n = d.conversation.length;
    let h = `<details class="detail-result conv-details"${openAttr}>` +
      `<summary class="conv-summary">Conversation (${n} message${n !== 1 ? 's' : ''})</summary>` +
      '<div class="conversation-display">';
    for (const m of d.conversation) {
      const role = m.role === 'user' ? 'patient' : 'agent';
      h += `<div class="conv-msg conv-msg-${role}"><div class="conv-bubble conv-bubble-${role}">${esc(m.content)}</div></div>`;
    }
    h += '</div></details>';
    return h;
  }
```

(`mode` is the module-level variable already set by `open(id, m)`. `flash` is already defined in the module and is hoisted, so `copyText` may reference it.)

- [ ] **Step 4: Sanity-check the edits and that pages still serve**

```bash
grep -q "function copyText" static/js/session-detail.js \
  && grep -q "function fallbackCopy" static/js/session-detail.js \
  && grep -q "conv-details" static/js/session-detail.js \
  && grep -q "copyText(buildExportText" static/js/session-detail.js \
  && echo "OK session-detail edits present"
source .venv/bin/activate && python -c "
from fastapi.testclient import TestClient
from triage.api import app
from triage.auth import DEMO_USER, DEMO_PASS
c = TestClient(app); c.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})
assert c.get('/history').status_code == 200
assert c.get('/static/js/session-detail.js').status_code == 200
print('OK pages serve')
"
```
Expected: prints `OK session-detail edits present` and `OK pages serve`.

- [ ] **Step 5: Manual browser check (deferred-to-human if running headless)**

With `python main.py` running and logged in:
- Open a **History** session → the Conversation section is **expanded** by default.
- Open an **Inbox** session → the Conversation section is **collapsed** (click the summary to expand).
- Click **Copy** while viewing the app over `http://localhost:8000` **and** over the machine's LAN IP (e.g. `http://192.168.x.x:8000`) → both show "Copied!" and paste a clean labelled summary (the LAN-IP case is the bug this fixes).

- [ ] **Step 6: Commit**

```bash
git add static/js/session-detail.js
git commit -m "fix: robust clipboard copy and collapsible conversation in detail modal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Inbox Kanban board (`inbox-board.js` + `inbox.html`)

**Files:**
- Create: `static/js/inbox-board.js`
- Modify: `templates/inbox.html`

- [ ] **Step 1: Create `static/js/inbox-board.js`**

Create the file with this exact content:

```javascript
// Patient Inbox board: 3-column active Kanban (New / In progress / Needs follow-up)
// plus a separate Done tab, with type/urgent/search filters and stage-move actions.
// Re-renders the board region from in-memory state on every change.
(function () {
  const NAME_KEY = 'triage_tester_name';
  const PROC = { new: 'New', in_progress: 'In progress', followup: 'Needs follow-up', done: 'Done' };
  const ACTIVE_COLS = ['new', 'in_progress', 'followup'];
  const ORDER = ['new', 'in_progress', 'followup', 'done'];

  let rows = [];
  let tab = 'active';
  const filters = { type: 'all', urgentOnly: false, search: '' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function statusOf(r) { return r.processing_status || 'new'; }
  function isUrgent(r) { return r.status === 'escalated' || r.urgency === 'immediate'; }

  function urgencyFlag(r) {
    if (isUrgent(r)) return '<span class="card-flag card-flag-urgent" title="Urgent">●</span>';
    if (r.urgency === 'high') return '<span class="card-flag card-flag-high">High</span>';
    return '';
  }

  function passesFilters(r) {
    if (filters.type !== 'all' && (r.result_type || '') !== filters.type) return false;
    if (filters.urgentOnly && !isUrgent(r)) return false;
    const q = filters.search.trim().toLowerCase();
    if (q) {
      const hay = [r.patient_name, r.condition_name, r.phone].map(x => (x || '').toLowerCase()).join(' ');
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  function sortCards(a, b) {
    const ua = isUrgent(a) ? 0 : 1, ub = isUrgent(b) ? 0 : 1;
    if (ua !== ub) return ua - ub;
    return (b.created_at || '').localeCompare(a.created_at || '');
  }

  function cardHtml(r) {
    const proc = statusOf(r);
    const next = ORDER[Math.min(ORDER.indexOf(proc) + 1, ORDER.length - 1)];
    const canAdvance = proc !== 'done';
    const t = r.result_type || '';
    return `<div class="inbox-card" data-session="${esc(r.session_id)}">
      <div class="card-main">
        <div class="card-top">${urgencyFlag(r)}<span class="card-name">${esc(r.patient_name) || '—'}</span></div>
        <div class="card-cond">${esc(r.condition_name) || '—'}</div>
        <div class="card-meta">
          ${t ? `<span class="type-badge type-${esc(t)}">${esc(t)}</span>` : ''}
          ${r.processed_by ? `<span class="card-by">${esc(r.processed_by)}</span>` : ''}
        </div>
      </div>
      <div class="card-actions">
        ${canAdvance ? `<button class="card-advance" data-to="${next}" title="Move to ${PROC[next]}">▸</button>` : ''}
        <button class="card-menu-btn" title="Move to…">⋯</button>
        <div class="card-menu" hidden>
          ${ORDER.map(s => `<button class="card-menu-item" data-to="${s}"${s === proc ? ' disabled' : ''}>${PROC[s]}</button>`).join('')}
        </div>
      </div>
    </div>`;
  }

  function columnHtml(status, cards) {
    const inner = cards.length ? cards.map(cardHtml).join('') : '<div class="col-empty">None</div>';
    return `<div class="inbox-col" data-col="${status}">
      <div class="col-head">${PROC[status]} <span class="col-count">${cards.length}</span></div>
      <div class="col-body">${inner}</div>
    </div>`;
  }

  function render() {
    const visible = rows.filter(passesFilters);
    const activeRows = visible.filter(r => statusOf(r) !== 'done');
    const doneRows = visible.filter(r => statusOf(r) === 'done');

    document.getElementById('tabActiveCount').textContent = activeRows.length;
    document.getElementById('tabDoneCount').textContent = doneRows.length;

    const board = document.getElementById('boardArea');
    if (tab === 'active') {
      board.innerHTML = '<div class="inbox-board">' +
        ACTIVE_COLS.map(s =>
          columnHtml(s, activeRows.filter(r => statusOf(r) === s).sort(sortCards))
        ).join('') + '</div>';
    } else {
      const done = doneRows.slice().sort(sortCards);
      board.innerHTML = '<div class="done-list">' +
        (done.length ? done.map(cardHtml).join('') : '<div class="col-empty">No completed patients.</div>') +
        '</div>';
    }
    bindCards();
  }

  function bindCards() {
    document.querySelectorAll('.inbox-card').forEach(card => {
      const sid = card.dataset.session;
      card.querySelector('.card-main').onclick = () => SessionDetail.open(sid, 'inbox');
      const adv = card.querySelector('.card-advance');
      if (adv) adv.onclick = (e) => { e.stopPropagation(); moveCard(sid, adv.dataset.to); };
      const menuBtn = card.querySelector('.card-menu-btn');
      const menu = card.querySelector('.card-menu');
      menuBtn.onclick = (e) => {
        e.stopPropagation();
        document.querySelectorAll('.card-menu').forEach(m => { if (m !== menu) m.hidden = true; });
        menu.hidden = !menu.hidden;
      };
      menu.querySelectorAll('.card-menu-item').forEach(item => {
        if (item.disabled) return;
        item.onclick = (e) => { e.stopPropagation(); menu.hidden = true; moveCard(sid, item.dataset.to); };
      });
    });
  }

  function moveCard(sessionId, toStatus) {
    const by = localStorage.getItem(NAME_KEY) || null;
    fetch(`/api/sessions/${sessionId}/processing`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ processing_status: toStatus, processed_by: by }),
    }).then(r => {
      if (!r.ok) { showError('Could not update status.'); return; }
      const row = rows.find(x => x.session_id === sessionId);
      if (row) { row.processing_status = toStatus; if (by) row.processed_by = by; }
      render();
    }).catch(() => showError('Could not update status.'));
  }

  function showError(msg) {
    const el = document.getElementById('boardError');
    if (!el) return;
    el.textContent = msg;
    setTimeout(() => { el.textContent = ''; }, 2500);
  }

  function bindControls() {
    document.querySelectorAll('.tab-btn').forEach(b => b.onclick = () => {
      tab = b.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(x => x.classList.toggle('active', x === b));
      render();
    });
    document.querySelectorAll('.type-chip').forEach(c => c.onclick = () => {
      filters.type = c.dataset.type;
      document.querySelectorAll('.type-chip').forEach(x => x.classList.toggle('active', x === c));
      render();
    });
    document.getElementById('urgentToggle').onchange = (e) => { filters.urgentOnly = e.target.checked; render(); };
    document.getElementById('searchBox').oninput = (e) => { filters.search = e.target.value; render(); };
    // Click anywhere else closes any open card menu.
    document.addEventListener('click', () => {
      document.querySelectorAll('.card-menu').forEach(m => { m.hidden = true; });
    });
  }

  async function load() {
    try {
      const resp = await fetch('/api/inbox');
      rows = await resp.json();
    } catch (e) {
      showError('Failed to load the inbox.');
      rows = [];
    }
    render();
  }

  // Called by session-detail.js after a status change inside the detail modal.
  window.InboxPage = {
    refreshRow(sessionId, proc, by) {
      const row = rows.find(x => x.session_id === sessionId);
      if (!row) return;
      row.processing_status = proc;
      if (by) row.processed_by = by;
      render();
    }
  };

  document.addEventListener('DOMContentLoaded', () => { bindControls(); load(); });
})();
```

- [ ] **Step 2: Replace `templates/inbox.html`**

Overwrite `templates/inbox.html` with:

```html
{% extends "base.html" %}
{% block title %}Inbox{% endblock %}
{% block nav_inbox_active %}active{% endblock %}

{% block content %}
<div class="history-page">
    <div class="history-header">
        <h2>Patient Inbox</h2>
    </div>

    <div class="inbox-tabs">
        <button class="tab-btn active" data-tab="active">Active <span class="tab-count" id="tabActiveCount">0</span></button>
        <button class="tab-btn" data-tab="done">Done <span class="tab-count" id="tabDoneCount">0</span></button>
    </div>

    <div class="inbox-filters">
        <div class="filter-chips">
            <span class="filter-label">Type</span>
            <button class="type-chip active" data-type="all">All</button>
            <button class="type-chip" data-type="booking">Booking</button>
            <button class="type-chip" data-type="handoff">Handoff</button>
        </div>
        <label class="urgent-toggle"><input type="checkbox" id="urgentToggle"> Urgent only</label>
        <input type="search" id="searchBox" class="inbox-search" placeholder="Search name, condition, phone…">
    </div>

    <p class="board-error" id="boardError"></p>
    <div id="boardArea"><div class="loading-spinner"></div></div>
</div>

<!-- Detail modal (shared with History via session-detail.js) -->
<div class="modal-overlay" id="detailModal" style="display: none;">
    <div class="modal-card">
        <div class="modal-header">
            <h3>Patient Detail</h3>
            <button class="modal-close" id="modalClose">&times;</button>
        </div>
        <div class="modal-body" id="modalBody">
            <div class="loading-spinner"></div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script src="/static/js/session-detail.js"></script>
<script src="/static/js/inbox-board.js"></script>
{% endblock %}
```

- [ ] **Step 3: Sanity-check files exist and the page serves**

```bash
test -f static/js/inbox-board.js && echo "OK board file exists"
grep -q "inbox-board.js" templates/inbox.html && echo "OK template wires board"
source .venv/bin/activate && python -c "
from fastapi.testclient import TestClient
from triage.api import app
from triage.auth import DEMO_USER, DEMO_PASS
c = TestClient(app); c.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})
assert c.get('/inbox').status_code == 200
assert c.get('/static/js/inbox-board.js').status_code == 200
print('OK /inbox serves with board script')
"
```
Expected: `OK board file exists`, `OK template wires board`, `OK /inbox serves with board script`.

- [ ] **Step 4: Manual browser check (deferred-to-human if running headless)**

With `python main.py` running, after completing a booking chat and an escalation chat:
- **Active** tab shows 3 columns; the new patients sit in **New**; the escalation card shows a red ● and sorts above non-urgent cards.
- Click a card's **▸** → it moves to the next column and both the column count and Active tab count update without reload.
- Open a card's **⋯** menu → pick **Done** → the card leaves the board; the **Done** tab count increments; switch to **Done** tab → the card is there with a **⋯** to reopen it to an active stage.
- **Type** chips (Booking/Handoff), **Urgent only**, and **Search** (try a name, condition, and phone) narrow visible cards and update counts.
- Click a card body (not the buttons) → the detail modal opens; change status inside the modal → the board reflects it (card moves).

- [ ] **Step 5: Commit**

```bash
git add static/js/inbox-board.js templates/inbox.html
git commit -m "feat: rebuild inbox as kanban board with tabs, filters, and stage moves

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Board styles + CSS cache bump

**Files:**
- Modify: `static/css/style.css`
- Modify: `templates/base.html`

- [ ] **Step 1: Append board styles to `static/css/style.css`**

Append this block to the end of `static/css/style.css`:

```css
/* ===== Inbox v2: tabs, filters, kanban board ===== */
.inbox-tabs { display: flex; gap: 4px; margin: 8px 0 12px; border-bottom: 1px solid var(--gray-200); }
.tab-btn { background: none; border: none; padding: 8px 14px; cursor: pointer; font: inherit; color: var(--gray-600); border-bottom: 2px solid transparent; }
.tab-btn.active { color: var(--gray-800); border-bottom-color: var(--gray-800); font-weight: 600; }
.tab-count { display: inline-block; min-width: 18px; padding: 0 6px; border-radius: 999px; background: var(--gray-100); font-size: 12px; }

.inbox-filters { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-chips { display: flex; align-items: center; gap: 6px; }
.filter-label { font-size: 12px; color: var(--gray-500); }
.type-chip { padding: 4px 10px; border: 1px solid var(--gray-300); border-radius: 999px; background: #fff; cursor: pointer; font-size: 13px; }
.type-chip.active { background: var(--gray-800); color: #fff; border-color: var(--gray-800); }
.urgent-toggle { font-size: 13px; color: var(--gray-600); display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.inbox-search { padding: 6px 10px; border: 1px solid var(--gray-300); border-radius: 6px; font: inherit; min-width: 220px; margin-left: auto; }

.board-error { color: #c0392b; font-size: 13px; min-height: 16px; margin: 0 0 6px; }

.inbox-board { display: flex; gap: 14px; align-items: flex-start; overflow-x: auto; }
.inbox-col { flex: 1 1 0; min-width: 240px; background: var(--gray-50); border: 1px solid var(--gray-200); border-radius: 10px; padding: 10px; }
.col-head { font-weight: 600; font-size: 13px; color: var(--gray-700); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.col-count { background: var(--gray-200); border-radius: 999px; padding: 0 7px; font-size: 12px; }
.col-body { display: flex; flex-direction: column; gap: 8px; max-height: 65vh; overflow-y: auto; }
.col-empty { color: var(--gray-400); font-size: 13px; font-style: italic; padding: 8px; text-align: center; }

.done-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }

.inbox-card { background: #fff; border: 1px solid var(--gray-200); border-radius: 8px; padding: 10px; display: flex; justify-content: space-between; gap: 8px; }
.inbox-card:hover { border-color: var(--gray-400); }
.card-main { cursor: pointer; flex: 1; min-width: 0; }
.card-top { display: flex; align-items: center; gap: 6px; }
.card-name { font-weight: 600; }
.card-cond { font-size: 13px; color: var(--gray-600); margin: 2px 0 6px; }
.card-meta { display: flex; align-items: center; gap: 8px; }
.card-by { font-size: 11px; color: var(--gray-500); }
.card-flag-urgent { color: #c0392b; font-size: 12px; }
.card-flag-high { background: #fff4e5; color: #b35900; border-radius: 999px; padding: 1px 6px; font-size: 11px; font-weight: 600; }

.card-actions { position: relative; display: flex; align-items: flex-start; gap: 4px; }
.card-advance, .card-menu-btn { background: none; border: 1px solid var(--gray-300); border-radius: 6px; width: 26px; height: 26px; cursor: pointer; line-height: 1; color: var(--gray-700); }
.card-advance:hover, .card-menu-btn:hover { background: var(--gray-100); }
.card-menu { position: absolute; top: 30px; right: 0; z-index: 10; background: #fff; border: 1px solid var(--gray-200); border-radius: 8px; box-shadow: var(--shadow-md, 0 4px 14px rgba(0,0,0,0.12)); display: flex; flex-direction: column; min-width: 150px; padding: 4px; }
.card-menu-item { background: none; border: none; text-align: left; padding: 7px 10px; border-radius: 6px; cursor: pointer; font: inherit; }
.card-menu-item:hover:not([disabled]) { background: var(--gray-100); }
.card-menu-item[disabled] { color: var(--gray-400); cursor: default; }

/* Collapsible conversation in the detail modal */
.conv-details > .conv-summary { cursor: pointer; font-weight: 600; padding: 6px 0; }
.conv-details[open] > .conv-summary { margin-bottom: 6px; }
```

- [ ] **Step 2: Bump the CSS cache version in `templates/base.html`**

Change:
```html
    <link rel="stylesheet" href="/static/css/style.css?v=20260529a">
```
to:
```html
    <link rel="stylesheet" href="/static/css/style.css?v=20260530a">
```

- [ ] **Step 3: Sanity-check the CSS and cache bump**

```bash
grep -q "inbox-board" static/css/style.css && grep -q "conv-details" static/css/style.css && echo "OK css present"
grep -q "v=20260530a" templates/base.html && echo "OK cache bumped"
```
Expected: `OK css present` and `OK cache bumped`.

- [ ] **Step 4: Manual browser check (deferred-to-human if running headless)**

Hard-reload `/inbox` (to bypass cached CSS). Confirm: the tabs, filter chips, and search render cleanly; the 3 columns lay out side-by-side with scrollable bodies; cards show the urgency ●/High tag, name, condition, type badge; the ▸ and ⋯ buttons are aligned; the ⋯ menu pops over correctly and closes on outside click; the Done tab shows a grid; and the conversation summary in the modal looks like a clickable disclosure row.

- [ ] **Step 5: Commit**

```bash
git add static/css/style.css templates/base.html
git commit -m "style: inbox kanban board, filters, and collapsible conversation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** Copy fix (T2 S1–S2), collapsible conversation collapsed-in-inbox/open-in-history (T2 S3 + T4 CSS), `list_inbox` phone/doctor enrichment (T1), kanban 3-column active board (T3), separate Done tab (T3), ▸ advance + ⋯ stage menu incl. Done/reopen (T3 `cardHtml`/`moveCard`), type/urgent/search filters with live counts (T3 `passesFilters`/`render`), urgent-first sort + flag (T3 `sortCards`/`urgencyFlag`), modal↔board live sync via `InboxPage.refreshRow` (T3), styles + cache bump (T4). All spec sections map to a task ✓.
- **Type/name consistency:** processing vocabulary `new|in_progress|followup|done` consistent across `ORDER`, `PROC`, `ACTIVE_COLS`, and the API's `ALLOWED_PROCESSING`. `SessionDetail.open(id, mode)` and `window.InboxPage.refreshRow(sessionId, proc, by)` match the contract `session-detail.js` already calls. CSS class names (`inbox-board`, `inbox-col`, `inbox-card`, `card-menu`, `conv-details`, `tab-btn`, `type-chip`) match between `inbox.html`, `inbox-board.js`, `session-detail.js`, and the CSS ✓.
- **Placeholder scan:** no TBD/TODO; every code step is complete ✓.
- **YAGNI:** no drag-and-drop, no doctor filter, no filter persistence, Done uncapped — all per spec's Out of Scope ✓.
