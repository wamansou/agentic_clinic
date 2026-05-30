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
    document.getElementById('copyBtn').onclick = () => copyText(buildExportText(d));
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
