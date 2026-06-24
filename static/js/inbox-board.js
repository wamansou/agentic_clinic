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

  const CONF = { none: '', pending: 'Awaiting confirmation', confirmed: 'Confirmed ✓',
                 expired: 'Unconfirmed — follow up', cancelled: 'Cancelled' };
  function confOf(r) { return r.confirmation || 'none'; }
  function isBooking(r) { return (r.result_type || '') === 'booking'; }
  function needsAttention(r) { return isUrgent(r) || confOf(r) === 'expired'; }
  function isClosed(r) { return statusOf(r) === 'done' || confOf(r) === 'cancelled'; }
  function confBadge(r) {
    const c = confOf(r);
    if (!isBooking(r) || c === 'none') return '';
    let txt = CONF[c];
    if (c === 'pending' && r.confirmation_hours_left != null) {
      txt += ' · ' + Math.ceil(r.confirmation_hours_left) + 'h left';
    }
    return `<span class="conf-badge conf-${c}">${esc(txt)}</span>`;
  }
  function confActions(r) {
    if (!isBooking(r)) return '';
    const c = confOf(r);
    if (c === 'none') return `<button class="conf-book" title="Mark booked & send SMS">Mark booked</button>`;
    if (c === 'expired') return `<button class="conf-cancel" title="Mark cancelled">Cancelled</button>`;
    return '';
  }

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
      const hay = [r.patient_name, r.condition_name, r.phone, r.cpr].map(x => (x || '').toLowerCase()).join(' ');
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  function sortCards(a, b) {
    const ua = needsAttention(a) ? 0 : 1, ub = needsAttention(b) ? 0 : 1;
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
          ${confBadge(r)}
          ${r.processed_by ? `<span class="card-by">${esc(r.processed_by)}</span>` : ''}
        </div>
      </div>
      <div class="card-actions">
        ${confActions(r)}
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
    const activeRows = visible.filter(r => !isClosed(r));
    const doneRows = visible.filter(r => isClosed(r));

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
      const bookBtn = card.querySelector('.conf-book');
      if (bookBtn) bookBtn.onclick = (e) => { e.stopPropagation(); bookCard(sid); };
      const cancelBtn = card.querySelector('.conf-cancel');
      if (cancelBtn) cancelBtn.onclick = (e) => { e.stopPropagation(); cancelCard(sid); };
      const menuBtn = card.querySelector('.card-menu-btn');
      const menu = card.querySelector('.card-menu');
      menuBtn.onclick = (e) => {
        e.stopPropagation();
        const willOpen = menu.hidden;
        document.querySelectorAll('.card-menu').forEach(m => { m.hidden = true; });
        if (willOpen) {
          // Position as a fixed popover so the column's overflow can't clip it.
          const rect = menuBtn.getBoundingClientRect();
          menu.style.top = (rect.bottom + 4) + 'px';
          menu.style.left = Math.max(8, Math.min(rect.right - 150, window.innerWidth - 158)) + 'px';
          menu.hidden = false;
        }
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

  function bookCard(sessionId) {
    fetch(`/api/sessions/${sessionId}/book`, { method: 'POST' }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { showError(data.error || 'Could not send confirmation.'); return; }
      if (data.confirm_url) window.prompt('Confirmation SMS sent. Demo link:', data.confirm_url);
      load();
    }).catch(() => showError('Could not send confirmation.'));
  }

  function cancelCard(sessionId) {
    if (!window.confirm('Mark this booking cancelled? Release the slot in the clinic system first.')) return;
    fetch(`/api/sessions/${sessionId}/cancel`, { method: 'POST' }).then(async r => {
      if (!r.ok) { const d = await r.json().catch(() => ({})); showError(d.error || 'Could not cancel.'); return; }
      load();
    }).catch(() => showError('Could not cancel.'));
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
    // Click anywhere else, or any scroll, closes any open card menu.
    const closeMenus = () => document.querySelectorAll('.card-menu').forEach(m => { m.hidden = true; });
    document.addEventListener('click', closeMenus);
    document.addEventListener('scroll', closeMenus, true);
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
