# Clinic Dashboard: Tester Notes + Patient Inbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tester-authored comments on chat sessions and a staff-facing patient inbox (work queue with workflow status, urgency sorting, and copy/print export) to the triage web app.

**Architecture:** All new persistence lives in `dashboard.db` via `SessionStore` (a new `comments` table plus four new columns on `sessions`, added with an idempotent migration). New FastAPI routes expose comment CRUD, the inbox list, and a processing-status update. A shared `static/js/session-detail.js` module renders one detail modal reused by both the existing History page and a new Inbox page; it carries the notes thread, copy/print export, and (inbox-only) processing controls.

**Tech Stack:** Python 3.14, FastAPI, SQLite (`sqlite3` stdlib), Jinja2 templates, vanilla JS, plain CSS. No new dependencies.

**Verification note:** This project has no unit-test framework (war games are the only suite and don't cover dashboard CRUD). Data-layer tasks are verified with throwaway Python scripts against a temp DB; HTTP tasks with FastAPI `TestClient`; UI tasks manually against a running server. This matches the approved spec's manual-verification decision.

**Conventions for every commit message:**
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## File Structure

- **Modify** `triage/session_store.py` — `comments` table + migration in `_init_db`; comment methods; inbox/processing methods; extend `delete_inactive`.
- **Modify** `triage/api.py` — comment routes, inbox routes, processing route; set `urgency` in the WebSocket completion handler.
- **Create** `static/js/session-detail.js` — shared detail-modal module (detail render + notes + export + processing).
- **Modify** `templates/history.html` — drop inline modal JS, load the shared module in `history` mode.
- **Create** `templates/inbox.html` — inbox queue page; loads the shared module in `inbox` mode.
- **Modify** `templates/base.html` — add the Inbox nav link + active block; bump CSS cache version.
- **Modify** `static/css/style.css` — styles for inbox table, urgency/processing badges, notes thread/form, export buttons, and a print stylesheet.

---

## Task 1: Comments table + comment methods (`SessionStore`)

**Files:**
- Modify: `triage/session_store.py`

- [ ] **Step 1: Add the `comments` table to `_init_db`**

In `triage/session_store.py`, edit `_init_db` so that after the existing `sessions` `CREATE TABLE` (and before `conn.commit()`) it also creates the comments table and index:

```python
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    patient_name TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    condition_name TEXT,
                    result_type TEXT,
                    result_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    author      TEXT NOT NULL,
                    body        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_session ON comments(session_id)"
            )
            conn.commit()
```

- [ ] **Step 2: Add the four comment methods**

Add these methods to the `SessionStore` class (place them after `get_conversation`, before `delete_inactive`):

```python
    def add_comment(self, session_id: str, author: str, body: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO comments (session_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (session_id, author, body, now),
            )
            conn.commit()
            comment_id = cur.lastrowid
        return {
            "id": comment_id, "session_id": session_id, "author": author,
            "body": body, "created_at": now, "updated_at": None,
        }

    def list_comments(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, session_id, author, body, created_at, updated_at "
                "FROM comments WHERE session_id = ? ORDER BY created_at ASC, id ASC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_comment(self, comment_id: int, body: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "UPDATE comments SET body = ?, updated_at = ? WHERE id = ?",
                (body, now, comment_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT id, session_id, author, body, created_at, updated_at "
                "FROM comments WHERE id = ?", (comment_id,),
            ).fetchone()
        return dict(row)

    def delete_comment(self, comment_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            conn.commit()
            return cur.rowcount > 0
```

- [ ] **Step 3: Verify against a temp DB**

Run from the project root (venv active):

```bash
source .venv/bin/activate && python - <<'PY'
import tempfile
from triage.session_store import SessionStore
s = SessionStore(tempfile.mktemp(suffix='.db'))
s.create_session('t1')
c = s.add_comment('t1', 'Alice', 'looks good')
assert c['id'] and c['author'] == 'Alice' and c['updated_at'] is None, c
assert len(s.list_comments('t1')) == 1
u = s.update_comment(c['id'], 'edited')
assert u['body'] == 'edited' and u['updated_at'], u
assert s.update_comment(999999, 'x') is None
assert s.delete_comment(c['id']) is True
assert s.delete_comment(c['id']) is False
assert s.list_comments('t1') == []
print('OK comments')
PY
```
Expected: prints `OK comments` and exits 0.

- [ ] **Step 4: Commit**

```bash
git add triage/session_store.py
git commit -m "feat: add comments table and CRUD methods to SessionStore

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Inbox columns, migration, and inbox/processing methods (`SessionStore`)

**Files:**
- Modify: `triage/session_store.py`

- [ ] **Step 1: Add the column-migration helper and call it from `_init_db`**

Add this method to `SessionStore`:

```python
    def _ensure_session_columns(self, conn):
        """Idempotently add inbox-workflow columns to an existing sessions table."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        migrations = {
            "processing_status": "TEXT DEFAULT 'new'",
            "processed_by": "TEXT",
            "processing_updated_at": "TEXT",
            "urgency": "TEXT",
        }
        for col, decl in migrations.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")
```

Then call it inside `_init_db`, right before `conn.commit()`:

```python
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_session ON comments(session_id)"
            )
            self._ensure_session_columns(conn)
            conn.commit()
```

(SQLite backfills existing rows of `processing_status` with the constant default `'new'`.)

- [ ] **Step 2: Add `list_inbox`, `set_processing`, and `set_urgency`**

Add to `SessionStore` (after `list_sessions`):

```python
    def list_inbox(self) -> list[dict]:
        """Actionable sessions (completed/escalated), urgent-first then newest."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, created_at, patient_name, status, condition_name, "
                "result_type, processing_status, processed_by, processing_updated_at, urgency "
                "FROM sessions WHERE status IN ('completed', 'escalated') "
                "ORDER BY CASE urgency "
                "  WHEN 'immediate' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
                "created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_processing(self, session_id: str, processing_status: str,
                       processed_by: str | None = None) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "UPDATE sessions SET processing_status = ?, processed_by = ?, "
                "processing_updated_at = ? WHERE session_id = ?",
                (processing_status, processed_by, now, session_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT session_id, processing_status, processed_by, processing_updated_at "
                "FROM sessions WHERE session_id = ?", (session_id,),
            ).fetchone()
        return dict(row)

    def set_urgency(self, session_id: str, urgency: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET urgency = ? WHERE session_id = ?",
                (urgency, session_id),
            )
            conn.commit()
```

- [ ] **Step 3: Extend `delete_inactive` to also delete those sessions' comments**

Replace the existing `delete_inactive` method body with:

```python
    def delete_inactive(self) -> int:
        """Delete all sessions with status 'active' and their comments. Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT session_id FROM sessions WHERE status = 'active'"
            ).fetchall()]
            cursor = conn.execute("DELETE FROM sessions WHERE status = 'active'")
            for sid in ids:
                conn.execute("DELETE FROM comments WHERE session_id = ?", (sid,))
            conn.commit()
            return cursor.rowcount
```

- [ ] **Step 4: Verify inbox methods and the migration against temp DBs**

```bash
source .venv/bin/activate && python - <<'PY'
import sqlite3, tempfile
from triage.session_store import SessionStore

# inbox ordering + processing
s = SessionStore(tempfile.mktemp(suffix='.db'))
for sid, st in [('a', 'completed'), ('b', 'escalated'), ('c', 'active')]:
    s.create_session(sid); s.update_session(sid, status=st)
s.set_urgency('a', 'normal'); s.set_urgency('b', 'immediate')
assert [r['session_id'] for r in s.list_inbox()] == ['b', 'a'], s.list_inbox()
r = s.set_processing('a', 'in_progress', 'Bob')
assert r['processing_status'] == 'in_progress' and r['processed_by'] == 'Bob', r
assert s.set_processing('zzz', 'done', None) is None

# migration of a pre-existing old-schema DB
db = tempfile.mktemp(suffix='.db')
conn = sqlite3.connect(db)
conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
             "patient_name TEXT, status TEXT NOT NULL DEFAULT 'active', condition_name TEXT, "
             "result_type TEXT, result_json TEXT)")
conn.execute("INSERT INTO sessions (session_id, created_at, status) VALUES "
             "('old', '2026-01-01T00:00:00', 'completed')")
conn.commit(); conn.close()
s2 = SessionStore(db)            # should migrate without error
assert s2.get_session('old')['processing_status'] == 'new', s2.get_session('old')
print('OK inbox + migration')
PY
```
Expected: prints `OK inbox + migration`.

- [ ] **Step 5: Commit**

```bash
git add triage/session_store.py
git commit -m "feat: add inbox columns, migration, and inbox/processing methods

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Comment API routes (`api.py`)

**Files:**
- Modify: `triage/api.py`

- [ ] **Step 1: Add the four comment routes**

In `triage/api.py`, add these routes immediately after the existing `api_delete_inactive` route (just before the `# WebSocket` section divider):

```python
@app.get("/api/sessions/{session_id}/comments")
async def api_list_comments(session_id: str):
    return store.list_comments(session_id)


@app.post("/api/sessions/{session_id}/comments")
async def api_add_comment(session_id: str, request: Request):
    from fastapi.responses import JSONResponse
    if not store.get_session(session_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    data = await request.json()
    author = (data.get("author") or "").strip()
    body = (data.get("body") or "").strip()
    if not author or not body:
        return JSONResponse({"error": "author and body required"}, status_code=400)
    return store.add_comment(session_id, author, body)


@app.put("/api/comments/{comment_id}")
async def api_update_comment(comment_id: int, request: Request):
    from fastapi.responses import JSONResponse
    data = await request.json()
    body = (data.get("body") or "").strip()
    if not body:
        return JSONResponse({"error": "body required"}, status_code=400)
    updated = store.update_comment(comment_id, body)
    if updated is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return updated


@app.delete("/api/comments/{comment_id}")
async def api_delete_comment(comment_id: int):
    from fastapi.responses import JSONResponse
    if not store.delete_comment(comment_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"deleted": True}
```

- [ ] **Step 2: Verify the routes end-to-end with an authenticated TestClient**

```bash
source .venv/bin/activate && python - <<'PY'
from fastapi.testclient import TestClient
from triage.api import app, store
from triage.auth import DEMO_USER, DEMO_PASS

store.create_session('sess_test_c')
client = TestClient(app)
client.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})

# create
r = client.post('/api/sessions/sess_test_c/comments', json={'author': 'A', 'body': 'hi'})
assert r.status_code == 200, r.text
cid = r.json()['id']
# list
r = client.get('/api/sessions/sess_test_c/comments'); assert len(r.json()) == 1, r.text
# validation
assert client.post('/api/sessions/sess_test_c/comments', json={'author': '', 'body': 'x'}).status_code == 400
# missing session
assert client.post('/api/sessions/nope/comments', json={'author': 'A', 'body': 'x'}).status_code == 404
# edit
r = client.put(f'/api/comments/{cid}', json={'body': 'edited'}); assert r.json()['body'] == 'edited', r.text
assert client.put('/api/comments/999999', json={'body': 'x'}).status_code == 404
# delete
assert client.delete(f'/api/comments/{cid}').status_code == 200
assert client.delete(f'/api/comments/{cid}').status_code == 404
print('OK comment routes')
PY
```
Expected: prints `OK comment routes`.

- [ ] **Step 3: Commit**

```bash
git add triage/api.py
git commit -m "feat: add comment CRUD API routes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Inbox/processing routes + completion urgency (`api.py`)

**Files:**
- Modify: `triage/api.py`

- [ ] **Step 1: Add the inbox page route, inbox list route, and processing route**

Add the page route after the existing `conditions_page` route (in the HTML-page section):

```python
@app.get("/inbox", response_class=HTMLResponse)
async def inbox_page(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("inbox.html", {"request": request, "user": user})
```

Add the API routes next to the comment routes (after `api_delete_comment`):

```python
ALLOWED_PROCESSING = {"new", "in_progress", "done", "followup"}


@app.get("/api/inbox")
async def api_inbox():
    return store.list_inbox()


@app.patch("/api/sessions/{session_id}/processing")
async def api_set_processing(session_id: str, request: Request):
    from fastapi.responses import JSONResponse
    data = await request.json()
    status = data.get("processing_status")
    if status not in ALLOWED_PROCESSING:
        return JSONResponse({"error": "invalid processing_status"}, status_code=400)
    processed_by = (data.get("processed_by") or "").strip() or None
    updated = store.set_processing(session_id, status, processed_by)
    if updated is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return updated
```

- [ ] **Step 2: Record urgency at completion in the WebSocket handler**

In the `websocket_endpoint` completion branch (the `else:` block that runs when triage is complete), find the two lines:

```python
                store.save_result(session_id, json.dumps(result_data))
```

Insert immediately after that line:

```python
                if is_handoff:
                    urgency = result_data.get("urgency") or "high"
                else:
                    category = (triage_data.get("category") or "").upper()
                    urgency = "high" if category == "B" else "normal"
                store.set_urgency(session_id, urgency)
```

(`is_handoff`, `result_data`, and `triage_data` are already defined just above in that block.)

- [ ] **Step 3: Verify inbox + processing routes and urgency mapping**

```bash
source .venv/bin/activate && python - <<'PY'
from fastapi.testclient import TestClient
from triage.api import app, store
from triage.auth import DEMO_USER, DEMO_PASS

store.create_session('sess_inbox_a'); store.update_session('sess_inbox_a', status='completed')
store.create_session('sess_inbox_b'); store.update_session('sess_inbox_b', status='escalated')
store.set_urgency('sess_inbox_a', 'normal'); store.set_urgency('sess_inbox_b', 'immediate')

client = TestClient(app)
client.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})

r = client.get('/api/inbox'); assert r.status_code == 200, r.text
ids = [row['session_id'] for row in r.json()]
assert ids.index('sess_inbox_b') < ids.index('sess_inbox_a'), ids  # immediate before normal

r = client.patch('/api/sessions/sess_inbox_a/processing',
                 json={'processing_status': 'in_progress', 'processed_by': 'Bob'})
assert r.json()['processing_status'] == 'in_progress', r.text
assert client.patch('/api/sessions/sess_inbox_a/processing',
                    json={'processing_status': 'bogus'}).status_code == 400
assert client.patch('/api/sessions/nope/processing',
                    json={'processing_status': 'done'}).status_code == 404
assert client.get('/inbox').status_code == 200       # page renders (template added in Task 6)
print('OK inbox routes')
PY
```
Expected: prints `OK inbox routes`. (If `/inbox` 500s because `inbox.html` does not exist yet, that line will fail — temporarily comment out the final assert until Task 6, or run Task 6 first then re-run. The other assertions must pass now.)

- [ ] **Step 4: Commit**

```bash
git add triage/api.py
git commit -m "feat: add inbox/processing routes and record urgency at completion

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Shared session-detail modal (JS module + History rewire + CSS)

**Files:**
- Create: `static/js/session-detail.js`
- Modify: `templates/history.html`
- Modify: `static/css/style.css`
- Modify: `templates/base.html` (CSS cache bump)

- [ ] **Step 1: Create the shared module `static/js/session-detail.js`**

Create `static/js/session-detail.js` with this exact content:

```javascript
// Shared session-detail modal used by History and Inbox pages.
// Usage: SessionDetail.open(sessionId, mode)  where mode is 'history' | 'inbox'.
// Requires #detailModal, #modalBody, #modalClose to exist on the page.
(function () {
  const NAME_KEY = 'triage_tester_name';
  const DOCTORS = { HS: 'Dr. Skensved (HS)', LB: 'Dr. Bune (LB)' };
  const CATS = { A: 'A — Urgent', B: 'B — Semi-urgent', C: 'C — Standard' };
  const PROC = { new: 'New', in_progress: 'In progress', followup: 'Needs follow-up', done: 'Done' };

  let sessionId = null;
  let mode = 'history';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function field(label, val) {
    return val ? `<div class="result-field"><span class="result-field-label">${label}</span>` +
      `<span class="result-field-value">${esc(val)}</span></div>` : '';
  }

  function renderMeta(d) {
    let h = '<div class="detail-grid">';
    h += `<div class="detail-item"><span class="detail-label">Session ID</span><span class="detail-value">${esc(d.session_id)}</span></div>`;
    h += `<div class="detail-item"><span class="detail-label">Patient</span><span class="detail-value">${esc(d.patient_name) || '—'}</span></div>`;
    h += `<div class="detail-item"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${esc(d.status)}">${esc(d.status)}</span></span></div>`;
    h += `<div class="detail-item"><span class="detail-label">Condition</span><span class="detail-value">${esc(d.condition_name) || '—'}</span></div>`;
    h += `<div class="detail-item"><span class="detail-label">Created</span><span class="detail-value">${esc(d.created_at)}</span></div>`;
    h += '</div>';
    return h;
  }

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

  function renderResult(d) {
    if (!d.result) return '';
    const r = d.result, t = r.triage || {}, isHandoff = !!r.reason;
    let h = '<div class="detail-result"><h4>' + (isHandoff ? 'Staff Handoff' : 'Booking Result') + '</h4>';
    h += field('Patient', t.patient_name);
    h += field('Phone', t.phone_number);
    h += field('Insurance', t.insurance_type === 'public' ? 'Public (sygesikring)'
      : t.insurance_type === 'dss' ? 'DSS / Private' : t.insurance_type);
    h += field('Condition', t.condition_name);
    h += field('Category', CATS[t.category] || t.category);
    h += field('Doctor', DOCTORS[t.doctor] || t.doctor);
    if (t.duration_minutes) h += field('Duration', t.duration_minutes + ' min');
    if (t.priority_window) h += field('Priority', t.priority_window);
    if (t.patient_age) h += field('Age', t.patient_age);
    if (t.last_period_date) h += field('Last Period', t.last_period_date);
    if (isHandoff) {
      h += '<div class="result-divider"></div>';
      h += field('Reason', r.reason);
      h += field('Urgency', r.urgency);
      h += field('Summary', r.conversation_summary);
      if (r.suggested_action) h += field('Suggested Action', r.suggested_action);
    } else {
      if (r.cycle_dependent) h += field('Cycle Dependent', 'Yes');
      if (r.valid_booking_window) h += field('Booking Window', r.valid_booking_window);
      if (r.lab_required) h += field('Lab Required', r.lab_details || 'Yes');
      if (r.questionnaire) h += field('Questionnaire', r.questionnaire);
      if (r.partner_questionnaire) h += field('Partner Quest.', r.partner_questionnaire);
      if (r.guidance_document) h += field('Guidance Doc', r.guidance_document);
      if (r.self_pay) h += field('Self-Pay', r.self_pay_price_dkk ? r.self_pay_price_dkk + ' DKK' : 'Yes');
      if (r.provera_recommended) h += field('Provera', 'Recommended');
    }
    h += '</div>';
    return h;
  }

  function renderExport() {
    return '<div class="export-actions">' +
      '<button class="btn btn-outline btn-sm" id="copyBtn">Copy</button>' +
      '<button class="btn btn-outline btn-sm" id="printBtn">Print</button></div>';
  }

  function renderProcessing(d) {
    if (mode !== 'inbox') return '';
    const cur = d.processing_status || 'new';
    const name = localStorage.getItem(NAME_KEY) || '';
    let btns = '';
    for (const k of ['new', 'in_progress', 'followup', 'done']) {
      btns += `<button class="proc-btn proc-${k} ${cur === k ? 'active' : ''}" data-proc="${k}">${PROC[k]}</button>`;
    }
    return '<div class="detail-result processing-controls"><h4>Processing</h4>' +
      `<div class="proc-btn-row">${btns}</div>` +
      `<label class="proc-name-label">Handled by <input type="text" id="procName" class="proc-name-input" value="${esc(name)}" placeholder="Your name"></label>` +
      '<span class="proc-saved" id="procSaved"></span></div>';
  }

  function renderNotes() {
    const name = localStorage.getItem(NAME_KEY) || '';
    return '<div class="detail-result notes-section"><h4>Tester Notes</h4>' +
      '<div class="notes-list" id="notesList"><div class="loading-spinner"></div></div>' +
      '<div class="note-form">' +
      `<input type="text" id="noteAuthor" class="note-author" value="${esc(name)}" placeholder="Your name">` +
      '<textarea id="noteBody" class="note-body" placeholder="How did this chat go?"></textarea>' +
      '<button class="btn btn-primary btn-sm" id="noteAddBtn">Add note</button>' +
      '</div><p class="note-error" id="noteError"></p></div>';
  }

  function noteItem(c) {
    const when = c.updated_at ? `${esc(c.created_at.slice(0,16))} (edited)` : esc(c.created_at.slice(0,16));
    return `<div class="note-item" data-id="${c.id}">` +
      `<div class="note-head"><span class="note-author-name">${esc(c.author)}</span>` +
      `<span class="note-when">${when}</span>` +
      `<span class="note-actions"><button class="note-edit" data-id="${c.id}">Edit</button>` +
      `<button class="note-del" data-id="${c.id}">Delete</button></span></div>` +
      `<div class="note-text">${esc(c.body)}</div></div>`;
  }

  function loadNotes() {
    const list = document.getElementById('notesList');
    fetch(`/api/sessions/${sessionId}/comments`).then(r => r.json()).then(rows => {
      list.innerHTML = rows.length ? rows.map(noteItem).join('')
        : '<p class="notes-empty">No notes yet.</p>';
      bindNoteActions();
    });
  }

  function bindNoteActions() {
    document.querySelectorAll('.note-del').forEach(b => b.onclick = () => {
      if (!confirm('Delete this note?')) return;
      fetch(`/api/comments/${b.dataset.id}`, { method: 'DELETE' }).then(loadNotes);
    });
    document.querySelectorAll('.note-edit').forEach(b => b.onclick = () => {
      const item = b.closest('.note-item');
      const cur = item.querySelector('.note-text').textContent;
      const next = prompt('Edit note:', cur);
      if (next == null || !next.trim()) return;
      fetch(`/api/comments/${b.dataset.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: next.trim() }),
      }).then(loadNotes);
    });
  }

  function bindNoteForm() {
    const author = document.getElementById('noteAuthor');
    const body = document.getElementById('noteBody');
    const err = document.getElementById('noteError');
    document.getElementById('noteAddBtn').onclick = () => {
      const a = author.value.trim(), b = body.value.trim();
      err.textContent = '';
      if (!a || !b) { err.textContent = 'Name and note are both required.'; return; }
      localStorage.setItem(NAME_KEY, a);
      fetch(`/api/sessions/${sessionId}/comments`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ author: a, body: b }),
      }).then(r => {
        if (!r.ok) { err.textContent = 'Failed to save note.'; return; }
        body.value = ''; loadNotes();
      });
    };
  }

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

  function buildExportText(d) {
    const r = d.result || {}, t = r.triage || {}, lines = [];
    const add = (k, v) => { if (v) lines.push(`${k}: ${v}`); };
    add('Patient', t.patient_name || d.patient_name);
    add('Phone', t.phone_number);
    add('Insurance', t.insurance_type);
    add('Condition', t.condition_name || d.condition_name);
    add('Category', t.category);
    add('Doctor', DOCTORS[t.doctor] || t.doctor);
    if (r.reason) {
      add('Type', 'Staff handoff');
      add('Reason', r.reason); add('Urgency', r.urgency); add('Summary', r.conversation_summary);
      add('Suggested action', r.suggested_action);
    } else {
      add('Type', 'Booking');
      add('Booking window', r.valid_booking_window);
      add('Lab required', r.lab_required ? (r.lab_details || 'Yes') : '');
      add('Questionnaire', r.questionnaire);
      add('Guidance doc', r.guidance_document);
      add('Self-pay', r.self_pay ? (r.self_pay_price_dkk ? r.self_pay_price_dkk + ' DKK' : 'Yes') : '');
    }
    add('Session', d.session_id);
    return lines.join('\n');
  }

  function bindProcessing() {
    if (mode !== 'inbox') return;
    const nameInput = document.getElementById('procName');
    document.querySelectorAll('.proc-btn').forEach(b => b.onclick = () => {
      const by = nameInput.value.trim() || null;
      if (by) localStorage.setItem(NAME_KEY, by);
      fetch(`/api/sessions/${sessionId}/processing`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ processing_status: b.dataset.proc, processed_by: by }),
      }).then(r => {
        if (!r.ok) return;
        document.querySelectorAll('.proc-btn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        flash('procSaved', 'Saved', true);
        if (window.InboxPage) window.InboxPage.refreshRow(sessionId, b.dataset.proc, by);
      });
    });
  }

  function flash(id, msg, isSpan) {
    const el = document.getElementById(id);
    if (!el) return;
    const prev = isSpan ? '' : el.textContent;
    el.textContent = msg;
    if (!isSpan) setTimeout(() => { el.textContent = prev; }, 1200);
    else setTimeout(() => { el.textContent = ''; }, 1200);
  }

  function render(d) {
    return renderMeta(d) + renderExport() + renderProcessing(d)
      + renderConversation(d) + renderResult(d) + renderNotes();
  }

  function open(id, m) {
    sessionId = id; mode = m || 'history';
    const modal = document.getElementById('detailModal');
    const body = document.getElementById('modalBody');
    modal.style.display = 'flex';
    body.innerHTML = '<div class="loading-spinner"></div>';
    fetch(`/api/sessions/${id}`).then(r => r.json()).then(d => {
      body.innerHTML = render(d);
      bindExport(d); bindProcessing(); bindNoteForm(); loadNotes();
    }).catch(() => { body.innerHTML = '<p class="error-text">Failed to load session details.</p>'; });
  }

  function bindClose() {
    const modal = document.getElementById('detailModal');
    const close = document.getElementById('modalClose');
    if (close) close.onclick = () => { modal.style.display = 'none'; };
    if (modal) modal.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });
  }

  document.addEventListener('DOMContentLoaded', bindClose);
  window.SessionDetail = { open };
})();
```

- [ ] **Step 2: Rewire `templates/history.html` to use the shared module**

Replace the entire `{% block scripts %}...{% endblock %}` at the bottom of `templates/history.html` (the inline `<script>` from `document.addEventListener('DOMContentLoaded', () => {` through its close) with:

```html
{% block scripts %}
<script src="/static/js/session-detail.js"></script>
<script>
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.history-row').forEach(row => {
        row.addEventListener('click', () => SessionDetail.open(row.dataset.session, 'history'));
    });

    const clearBtn = document.getElementById('clearInactiveBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', async () => {
            if (!confirm('Delete all inactive (active/abandoned) sessions?')) return;
            try {
                const resp = await fetch('/api/sessions/inactive', { method: 'DELETE' });
                const data = await resp.json();
                clearBtn.textContent = `Deleted ${data.deleted} session${data.deleted !== 1 ? 's' : ''}`;
                clearBtn.disabled = true;
                setTimeout(() => location.reload(), 800);
            } catch (e) {
                alert('Failed to clear sessions.');
            }
        });
    }
});
</script>
{% endblock %}
```

(The `<!-- Detail modal -->` markup block already in `history.html` stays as-is — the module targets those element IDs.)

- [ ] **Step 3: Append styles to `static/css/style.css`**

Append this block to the end of `static/css/style.css`:

```css
/* ===== Session-detail modal: export, notes, processing ===== */
.result-divider { height: 1px; background: var(--gray-200); margin: 10px 0; }

.export-actions { display: flex; gap: 8px; margin: 4px 0 12px; }

.notes-section .notes-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.note-item { background: var(--gray-50, #f8f8f8); border: 1px solid var(--gray-200, #e5e5e5); border-radius: 8px; padding: 8px 10px; }
.note-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--gray-500, #888); }
.note-author-name { font-weight: 600; color: var(--gray-700, #444); }
.note-actions { margin-left: auto; display: flex; gap: 8px; }
.note-actions button { background: none; border: none; color: var(--gray-500, #888); cursor: pointer; font-size: 12px; padding: 0; }
.note-actions button:hover { color: var(--gray-800, #222); text-decoration: underline; }
.note-text { margin-top: 4px; white-space: pre-wrap; }
.notes-empty { color: var(--gray-500, #888); font-style: italic; }
.note-form { display: flex; flex-direction: column; gap: 6px; }
.note-form .note-author { max-width: 220px; }
.note-form input, .note-form textarea { padding: 6px 8px; border: 1px solid var(--gray-300, #ccc); border-radius: 6px; font: inherit; }
.note-form textarea { min-height: 56px; resize: vertical; }
.note-error { color: #c0392b; font-size: 12px; min-height: 14px; margin: 4px 0 0; }

.proc-btn-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.proc-btn { padding: 4px 10px; border: 1px solid var(--gray-300, #ccc); border-radius: 999px; background: #fff; cursor: pointer; font-size: 13px; }
.proc-btn.active { background: var(--gray-800, #222); color: #fff; border-color: var(--gray-800, #222); }
.proc-name-label { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--gray-600, #666); }
.proc-name-input { padding: 4px 8px; border: 1px solid var(--gray-300, #ccc); border-radius: 6px; font: inherit; }
.proc-saved { margin-left: 8px; color: #2e7d32; font-size: 12px; }

/* ===== Inbox table ===== */
.inbox-row { cursor: pointer; }
.inbox-row.is-done { opacity: 0.55; }
.urgency-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.urgency-immediate, .urgency-escalated { background: #fdecea; color: #c0392b; }
.urgency-high { background: #fff4e5; color: #b35900; }
.urgency-normal { background: var(--gray-100, #eee); color: var(--gray-600, #666); }
.proc-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--gray-100, #eee); color: var(--gray-700, #444); }
.proc-badge.proc-done { background: #e8f5e9; color: #2e7d32; }
.proc-badge.proc-in_progress { background: #e3f2fd; color: #1565c0; }
.proc-badge.proc-followup { background: #fff4e5; color: #b35900; }

/* ===== Print: show only the open modal card ===== */
@media print {
  body * { visibility: hidden; }
  .modal-overlay, .modal-card, .modal-card * { visibility: visible; }
  .modal-overlay { position: absolute; inset: 0; display: block !important; background: #fff; }
  .modal-card { box-shadow: none; max-height: none; width: 100%; }
  .modal-close, .export-actions, .processing-controls, .note-form, .note-actions { display: none !important; }
}
```

- [ ] **Step 4: Bump the CSS cache version in `templates/base.html`**

In `templates/base.html`, change:

```html
    <link rel="stylesheet" href="/static/css/style.css?v=20260309b">
```
to:
```html
    <link rel="stylesheet" href="/static/css/style.css?v=20260529a">
```

- [ ] **Step 5: Manual verification (History page parity + notes + export)**

Start the server and check in a browser:

```bash
source .venv/bin/activate && python main.py
```
Then at `http://localhost:8000` (login with `DEMO_USER`/`DEMO_PASS`):
1. Complete at least one chat (booking and/or handoff) so History has rows.
2. Open **History**, click a row → modal shows meta, conversation, and result exactly as before (parity).
3. In the modal: add a note (name + text) → it appears in the list; reload the page, reopen → note persists and the name field is pre-filled.
4. Edit the note (Edit → change text) → shows "(edited)". Delete it (confirm) → it disappears.
5. Click **Copy** → paste into a text editor; confirm a clean labelled summary. Click **Print** → print preview shows only the patient card (no buttons/nav).
6. Confirm the processing controls are **not** shown in History mode.

Expected: all of the above behave as described with no console errors.

- [ ] **Step 6: Commit**

```bash
git add static/js/session-detail.js templates/history.html static/css/style.css templates/base.html
git commit -m "feat: shared session-detail modal with notes and copy/print export

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Inbox page (nav + template + table wiring)

**Files:**
- Modify: `templates/base.html`
- Create: `templates/inbox.html`

- [ ] **Step 1: Add the Inbox nav link to `templates/base.html`**

In `templates/base.html`, add this link inside `.nav-links`, immediately after the History `<a>` and before the Conditions `<a>`:

```html
                <a href="/inbox" class="nav-link {% block nav_inbox_active %}{% endblock %}">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
                    Inbox
                </a>
```

- [ ] **Step 2: Create `templates/inbox.html`**

Create `templates/inbox.html` with this content:

```html
{% extends "base.html" %}
{% block title %}Inbox{% endblock %}
{% block nav_inbox_active %}active{% endblock %}

{% block content %}
<div class="history-page">
    <div class="history-header">
        <h2>Patient Inbox</h2>
        <span class="history-count" id="inboxCount"></span>
    </div>

    <div class="history-table-wrap">
        <table class="history-table">
            <thead>
                <tr>
                    <th>Priority</th>
                    <th>Patient</th>
                    <th>Phone</th>
                    <th>Condition</th>
                    <th>Doctor</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Handled by</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody id="inboxBody">
                <tr><td colspan="9"><div class="loading-spinner"></div></td></tr>
            </tbody>
        </table>
    </div>
    <div class="history-empty" id="inboxEmpty" style="display:none;">
        <p>No patients waiting. Completed and escalated chats will appear here.</p>
    </div>
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
<script>
const PROC = { new: 'New', in_progress: 'In progress', followup: 'Needs follow-up', done: 'Done' };
const DOCTORS = { HS: 'Dr. Skensved (HS)', LB: 'Dr. Bune (LB)' };

function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function urgencyCell(row) {
    if (row.status === 'escalated') return '<span class="urgency-badge urgency-escalated">Urgent</span>';
    if (row.urgency === 'immediate') return '<span class="urgency-badge urgency-immediate">Urgent</span>';
    if (row.urgency === 'high') return '<span class="urgency-badge urgency-high">High</span>';
    return '<span class="urgency-badge urgency-normal">Normal</span>';
}

function rowHtml(row) {
    const t = row.result_type || '';
    const proc = row.processing_status || 'new';
    return `<tr class="inbox-row ${proc === 'done' ? 'is-done' : ''}" data-session="${esc(row.session_id)}">
        <td>${urgencyCell(row)}</td>
        <td>${esc(row.patient_name) || '—'}</td>
        <td>${esc(row.phone || '') || '—'}</td>
        <td>${esc(row.condition_name) || '—'}</td>
        <td>${esc(DOCTORS[row.doctor] || row.doctor || '') || '—'}</td>
        <td>${t ? `<span class="type-badge type-${esc(t)}">${esc(t)}</span>` : '—'}</td>
        <td><span class="proc-badge proc-${proc}">${PROC[proc] || proc}</span></td>
        <td>${esc(row.processed_by || '') || '—'}</td>
        <td class="history-date">${esc((row.created_at || '').slice(0, 16))}</td>
    </tr>`;
}

function bindRows() {
    document.querySelectorAll('.inbox-row').forEach(r => {
        r.addEventListener('click', () => SessionDetail.open(r.dataset.session, 'inbox'));
    });
}

async function loadInbox() {
    const body = document.getElementById('inboxBody');
    const resp = await fetch('/api/inbox');
    const rows = await resp.json();
    document.getElementById('inboxCount').textContent =
        `${rows.length} patient${rows.length !== 1 ? 's' : ''}`;
    if (!rows.length) {
        document.querySelector('.history-table-wrap').style.display = 'none';
        document.getElementById('inboxEmpty').style.display = 'block';
        return;
    }
    body.innerHTML = rows.map(rowHtml).join('');
    bindRows();
}

// Called by session-detail.js after a status change in the modal.
window.InboxPage = {
    refreshRow(sessionId, proc, by) {
        const row = document.querySelector(`.inbox-row[data-session="${sessionId}"]`);
        if (!row) return;
        row.classList.toggle('is-done', proc === 'done');
        const badge = row.querySelector('.proc-badge');
        badge.className = `proc-badge proc-${proc}`;
        badge.textContent = PROC[proc] || proc;
        row.children[7].textContent = by || '—';
    }
};

document.addEventListener('DOMContentLoaded', loadInbox);
</script>
{% endblock %}
```

Note: `phone` and `doctor` are not columns on the `sessions` table, so `row.phone`/`row.doctor` are absent from `/api/inbox` and render as `—`. The full phone/doctor are always visible in the detail modal (from `result_json`). This keeps the list query simple; the cells degrade gracefully.

- [ ] **Step 3: Manual verification (Inbox queue + processing + export)**

With the server running (`python main.py`) and logged in:
1. Complete one **booking** chat and one **escalation/handoff** chat.
2. Open **Inbox** → both appear; the escalation shows a red **Urgent** badge and sorts above the normal booking.
3. Click the booking row → modal opens in inbox mode showing **Processing** controls. Click **In progress** → "Saved" appears, the row's status badge updates live to "In progress" without reload.
4. Set a row to **Done** → row dims (`is-done`). Reload the page → status and "Handled by" name persist.
5. Add a note from the inbox modal → confirm it saves (same thread as History).
6. Copy and Print work from the inbox modal as in History.
7. Open the same session from **History** → the note added in the inbox is visible there too (shared thread).

Expected: all behaviors as described; no console errors; `done` rows dimmed but still listed.

- [ ] **Step 4: Re-run the Task 4 inbox route check (now that `inbox.html` exists)**

```bash
source .venv/bin/activate && python - <<'PY'
from fastapi.testclient import TestClient
from triage.api import app
from triage.auth import DEMO_USER, DEMO_PASS
client = TestClient(app)
client.post('/login', data={'username': DEMO_USER, 'password': DEMO_PASS})
assert client.get('/inbox').status_code == 200
print('OK /inbox renders')
PY
```
Expected: prints `OK /inbox renders`.

- [ ] **Step 5: Commit**

```bash
git add templates/base.html templates/inbox.html
git commit -m "feat: add patient inbox page with workflow queue

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** comments table + methods (T1), inbox columns/migration/methods (T2), comment routes (T3), inbox/processing routes + urgency mapping (T4), shared modal with notes + copy/print + history rewire + print CSS (T5), inbox page + nav + urgency sort/badge + live status + dimmed done (T6). Clear-inactive comment cleanup covered in T2. Export = copy + print only; no CSV/email (out of scope) ✓.
- **Type/name consistency:** `processing_status` values `new|in_progress|done|followup` consistent across `SessionStore`, `ALLOWED_PROCESSING`, JS `PROC`, and CSS. Module global `SessionDetail.open(id, mode)` matches both templates' calls. `window.InboxPage.refreshRow(sessionId, proc, by)` defined in `inbox.html` and called in `session-detail.js` with matching arity ✓.
- **Placeholder scan:** no TBD/TODO; every code step contains full code ✓.
- **Known graceful degradation (documented, not a gap):** `/api/inbox` rows lack `phone`/`doctor` (not session columns) → those list cells show `—`; full values appear in the modal.
