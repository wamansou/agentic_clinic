/**
 * Conditions Editor — CRUD interface for conditions.yaml
 */
(function () {
    'use strict';

    const tbody = document.getElementById('conditionsBody');
    const editModal = document.getElementById('editModal');
    const editModalTitle = document.getElementById('editModalTitle');
    const editModalClose = document.getElementById('editModalClose');
    const editCancelBtn = document.getElementById('editCancelBtn');
    const conditionForm = document.getElementById('conditionForm');
    const reloadBtn = document.getElementById('reloadBtn');
    const addConditionBtn = document.getElementById('addConditionBtn');

    const CATEGORY_LABELS = { A: 'A — Urgent', B: 'B — Semi-urgent', C: 'C — Standard' };
    const DOCTOR_LABELS = { HS: 'Dr. Skensved', LB: 'Dr. Bune' };
    const PRIORITY_LABELS = {
        same_day: 'Same day', '1_2_days': '1-2 days', '1_week': '1 week',
        '2_weeks': '2 weeks', '4_weeks': '4 weeks'
    };

    let isNew = false;

    async function loadConditions() {
        try {
            const resp = await fetch('/api/conditions');
            const conditions = await resp.json();
            renderTable(conditions);
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--rose);">Failed to load conditions</td></tr>';
        }
    }

    function renderTable(conditions) {
        if (!conditions.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:40px; color:var(--gray-400);">No conditions found</td></tr>';
            return;
        }
        tbody.innerHTML = conditions.map(c => {
            const doctor = Array.isArray(c.doctor) ? c.doctor.join(', ') : (c.doctor || '—');
            const doctorDisplay = Array.isArray(c.doctor)
                ? c.doctor.map(d => DOCTOR_LABELS[d] || d).join(', ')
                : (DOCTOR_LABELS[c.doctor] || c.doctor || '—');
            const hasRules = c.special_instructions ? ' <span title="Has special instructions" style="cursor:help;">⚠</span>' : '';
            return `<tr class="cond-row" data-id="${c.id}">
                <td class="cond-id">${c.id}</td>
                <td>${escapeHtml(c.name)}${hasRules}</td>
                <td><span class="status-badge status-cat-${c.category}">${CATEGORY_LABELS[c.category] || c.category}</span></td>
                <td>${doctorDisplay}</td>
                <td>${c.duration ? c.duration + ' min' : '—'}</td>
                <td>${PRIORITY_LABELS[c.priority] || c.priority || '—'}</td>
            </tr>`;
        }).join('');

        document.querySelectorAll('.cond-row').forEach(row => {
            row.addEventListener('click', () => openEdit(parseInt(row.dataset.id)));
        });
    }

    async function openEdit(id) {
        isNew = false;
        editModalTitle.textContent = `Edit Condition #${id}`;
        try {
            const resp = await fetch(`/api/conditions/${id}`);
            const c = await resp.json();
            populateForm(c);
            editModal.style.display = 'flex';
        } catch (e) {
            alert('Failed to load condition.');
        }
    }

    function openNew() {
        isNew = true;
        editModalTitle.textContent = 'Add New Condition';
        populateForm({
            id: '', name: '', description: '', category: 'C', doctor: null,
            duration: null, priority: '', keywords: [], cycle_days: null,
            routing_question: null, self_pay_price_dkk: null, referral_required: false,
        });
        editModal.style.display = 'flex';
    }

    function populateForm(c) {
        document.getElementById('cf-id').value = c.id || '';
        document.getElementById('cf-name').value = c.name || '';
        document.getElementById('cf-description').value = c.description || '';
        document.getElementById('cf-category').value = c.category || 'C';
        document.getElementById('cf-doctor').value = Array.isArray(c.doctor) ? '' : (c.doctor || '');
        document.getElementById('cf-duration').value = c.duration || '';
        document.getElementById('cf-priority').value = c.priority || '';
        document.getElementById('cf-keywords').value = (c.keywords || []).join(', ');
        const cd = c.cycle_days;
        document.getElementById('cf-cycle-days').value = cd ? (Array.isArray(cd) ? cd.join(',') : cd) : '';
        document.getElementById('cf-routing-question').value = c.routing_question || '';
        document.getElementById('cf-self-pay').value = c.self_pay_price_dkk || '';
        document.getElementById('cf-referral-required').checked = !!c.referral_required;
        document.getElementById('cf-special-instructions').value = c.special_instructions || '';
    }

    function collectForm() {
        const data = {
            name: document.getElementById('cf-name').value.trim(),
            description: document.getElementById('cf-description').value.trim(),
            category: document.getElementById('cf-category').value,
            doctor: document.getElementById('cf-doctor').value || null,
            duration: parseInt(document.getElementById('cf-duration').value) || null,
            priority: document.getElementById('cf-priority').value || null,
            keywords: document.getElementById('cf-keywords').value.split(',').map(s => s.trim()).filter(Boolean),
            routing_question: document.getElementById('cf-routing-question').value.trim() || null,
            self_pay_price_dkk: parseFloat(document.getElementById('cf-self-pay').value) || null,
            referral_required: document.getElementById('cf-referral-required').checked,
            special_instructions: document.getElementById('cf-special-instructions').value.trim() || null,
        };

        const cdRaw = document.getElementById('cf-cycle-days').value.trim();
        if (cdRaw === 'just_before_next_period') {
            data.cycle_days = cdRaw;
        } else if (cdRaw && cdRaw.includes(',')) {
            data.cycle_days = cdRaw.split(',').map(Number);
        } else {
            data.cycle_days = null;
        }

        if (isNew) {
            const idVal = document.getElementById('cf-id').value.trim();
            if (idVal) data.id = parseInt(idVal);
        }

        return data;
    }

    conditionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = collectForm();
        const id = document.getElementById('cf-id').value;

        try {
            let resp;
            if (isNew) {
                resp = await fetch('/api/conditions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
            } else {
                resp = await fetch(`/api/conditions/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
            }
            if (!resp.ok) throw new Error('Save failed');
            editModal.style.display = 'none';
            loadConditions();
        } catch (e) {
            alert('Failed to save condition: ' + e.message);
        }
    });

    reloadBtn.addEventListener('click', async () => {
        try {
            await fetch('/api/conditions/reload', { method: 'POST' });
            loadConditions();
        } catch (e) {
            alert('Failed to reload.');
        }
    });

    addConditionBtn.addEventListener('click', openNew);
    editModalClose.addEventListener('click', () => { editModal.style.display = 'none'; });
    editCancelBtn.addEventListener('click', () => { editModal.style.display = 'none'; });
    editModal.addEventListener('click', (e) => { if (e.target === editModal) editModal.style.display = 'none'; });

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    loadConditions();
})();
