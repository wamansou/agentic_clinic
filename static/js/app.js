/**
 * Kvinde Klinikken Triage — Chat UI Controller
 * Manages WebSocket connection, message routing, and live triage panel updates.
 */

(function () {
    'use strict';

    // DOM refs
    const chatMessages = document.getElementById('chatMessages');
    const chatEmpty = document.getElementById('chatEmpty');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatInputArea = document.getElementById('chatInputArea');
    const sendBtn = document.getElementById('sendBtn');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const startBtn = document.getElementById('startBtn');
    const sessionLabel = document.getElementById('sessionLabel');
    const typingIndicator = document.getElementById('typingIndicator');
    const triageStatus = document.getElementById('triageStatus');
    const resultCard = document.getElementById('resultCard');
    const resultCardHeader = document.getElementById('resultCardHeader');
    const resultTitle = document.getElementById('resultTitle');
    const resultCardBody = document.getElementById('resultCardBody');

    const consentOverlay = document.getElementById('consentOverlay');
    const consentAcceptBtn = document.getElementById('consentAcceptBtn');
    const consentDeclineBtn = document.getElementById('consentDeclineBtn');

    let ws = null;
    let sessionId = null;
    let isConnected = false;
    let consentGiven = false;

    // =========================================================================
    // GDPR Consent
    // =========================================================================

    function showConsentPrompt() {
        consentOverlay.style.display = 'flex';
    }

    function handleConsentAccept() {
        consentGiven = true;
        consentOverlay.style.display = 'none';
        doCreateSession();
    }

    function handleConsentDecline() {
        consentOverlay.style.display = 'none';
        // Show declined state in the chat area
        chatEmpty.innerHTML = '<div class="consent-declined">' +
            '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' +
            '<p>You have declined data processing consent. We cannot proceed with the triage without your consent.</p>' +
            '<p>If you change your mind, click the button below.</p>' +
            '<button class="btn btn-primary" id="retryConsentBtn">Review Consent Again</button>' +
            '</div>';
        document.getElementById('retryConsentBtn').addEventListener('click', showConsentPrompt);
    }

    consentAcceptBtn.addEventListener('click', handleConsentAccept);
    consentDeclineBtn.addEventListener('click', handleConsentDecline);

    // =========================================================================
    // Session Management
    // =========================================================================

    function createSession() {
        // Always require consent before starting a session
        if (!consentGiven) {
            showConsentPrompt();
            return;
        }
        doCreateSession();
    }

    async function doCreateSession() {
        try {
            const resp = await fetch('/api/sessions', { method: 'POST' });
            const data = await resp.json();
            sessionId = data.session_id;
            sessionLabel.textContent = sessionId;
            connectWebSocket();
            showChatUI();
            resetTriagePanel();
        } catch (e) {
            console.error('Failed to create session:', e);
        }
    }

    function showChatUI() {
        // Clear all previous messages
        const messages = chatMessages.querySelectorAll('.message');
        messages.forEach(m => m.remove());

        // Hide empty state, show input area
        chatEmpty.style.display = 'none';
        chatInputArea.style.display = 'block';

        // Reset input state (may be disabled from a completed session)
        chatInput.disabled = false;
        chatInput.value = '';
        chatInput.placeholder = 'Type a message as the patient...';
        sendBtn.disabled = false;

        // Hide typing indicator
        typingIndicator.style.display = 'none';

        // Hide result card
        resultCard.style.display = 'none';

        chatInput.focus();

        // Add multilingual welcome message
        addMessage('agent', 'Welcome to Kvinde Klinikken. How can I help you today?\n\nVelkommen til Kvinde Klinikken. Hvordan kan jeg hjælpe dig i dag?\n\nЛаскаво просимо до Kvinde Klinikken. Чим я можу вам допомогти сьогодні?');
    }

    // =========================================================================
    // WebSocket
    // =========================================================================

    function connectWebSocket() {
        if (ws) {
            ws.close();
        }

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws/${sessionId}`);

        ws.onopen = () => {
            isConnected = true;
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        };

        ws.onclose = () => {
            isConnected = false;
            console.log('WebSocket disconnected');
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };
    }

    // =========================================================================
    // Message Routing
    // =========================================================================

    function handleMessage(msg) {
        switch (msg.type) {
            case 'chat':
                hideTyping();
                addMessage('agent', msg.data.message);
                break;

            case 'triage_update':
                updateTriagePanel(msg.data);
                break;

            case 'complete':
                hideTyping();
                handleCompletion(msg.data);
                break;

            case 'status':
                if (msg.data.state === 'thinking') {
                    showTyping();
                } else {
                    hideTyping();
                }
                break;
        }
    }

    // =========================================================================
    // Chat Messages
    // =========================================================================

    function addMessage(role, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message message-${role}`;

        const label = document.createElement('div');
        label.className = 'message-label';
        label.textContent = role === 'agent' ? 'Triage Agent' : 'Patient';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.textContent = text;

        msgDiv.appendChild(label);
        msgDiv.appendChild(bubble);
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function showTyping() {
        typingIndicator.style.display = 'flex';
        sendBtn.disabled = true;
        chatInput.disabled = true;
    }

    function hideTyping() {
        typingIndicator.style.display = 'none';
        sendBtn.disabled = false;
        chatInput.disabled = false;
        chatInput.focus();
    }

    // =========================================================================
    // Send Message
    // =========================================================================

    function sendMessage(text) {
        if (!ws || !isConnected || !text.trim()) return;

        addMessage('patient', text.trim());
        ws.send(JSON.stringify({
            type: 'chat',
            data: { message: text.trim() }
        }));
    }

    // =========================================================================
    // Triage Panel
    // =========================================================================

    const FIELD_MAP = {
        patient_name: 'Patient',
        phone_number: 'Phone',
        language: 'Language',
        insurance_type: 'Insurance',
        has_referral: 'Referral',
        condition_name: 'Condition',
        condition_id: null,
        category: 'Category',
        doctor: 'Doctor',
        duration_minutes: 'Duration',
        priority_window: 'Priority',
        escalate: null,
        escalation_reason: null,
    };

    const DOCTOR_NAMES = { HS: 'Dr. Skensved (HS)', LB: 'Dr. Bech (LB)' };
    const CATEGORY_LABELS = { A: 'A — Urgent', B: 'B — Semi-urgent', C: 'C — Standard' };

    function formatFieldValue(key, value) {
        if (value === null || value === undefined) return null;
        if (key === 'doctor') return DOCTOR_NAMES[value] || value;
        if (key === 'category') return CATEGORY_LABELS[value] || value;
        if (key === 'has_referral') return value ? 'Yes' : 'No';
        if (key === 'insurance_type') return value === 'public' ? 'Public (sygesikring)' : value === 'dss' ? 'DSS / Private' : value;
        if (key === 'duration_minutes') return value + ' min';
        if (key === 'language') return value === 'en' ? 'English' : value === 'da' ? 'Danish' : value === 'uk' ? 'Ukrainian' : value;
        return String(value);
    }

    function updateTriagePanel(data) {
        triageStatus.textContent = 'Active';
        triageStatus.className = 'triage-status active';

        for (const [key, value] of Object.entries(data)) {
            const el = document.getElementById(`tf-${key}`);
            if (!el) continue;
            const formatted = formatFieldValue(key, value);
            if (formatted !== null) {
                el.textContent = formatted;
                el.closest('.triage-field').classList.add('filled');
            }
        }
    }

    function resetTriagePanel() {
        triageStatus.textContent = 'Waiting';
        triageStatus.className = 'triage-status';

        document.querySelectorAll('.triage-field-value').forEach(el => {
            el.textContent = '—';
        });
        document.querySelectorAll('.triage-field').forEach(el => {
            el.classList.remove('filled');
        });
    }

    // =========================================================================
    // Completion
    // =========================================================================

    function handleCompletion(data) {
        const isHandoff = data.result_type === 'handoff';

        // Update triage status
        triageStatus.textContent = isHandoff ? 'Escalated' : 'Completed';
        triageStatus.className = `triage-status ${isHandoff ? 'escalated' : 'completed'}`;

        // Show result card
        resultCard.style.display = 'block';
        resultCardHeader.className = `result-card-header ${isHandoff ? 'handoff' : 'booking'}`;
        resultTitle.textContent = isHandoff ? 'Staff Handoff' : 'Booking Request';

        let html = '';
        const result = data.result || {};

        if (isHandoff) {
            html += renderField('Reason', result.reason);
            html += renderField('Urgency', result.urgency);
            html += renderField('Summary', result.conversation_summary);
            if (result.suggested_action) {
                html += renderField('Suggested Action', result.suggested_action);
            }
        } else {
            if (result.cycle_dependent) html += renderField('Cycle Dependent', 'Yes');
            if (result.valid_booking_window) html += renderField('Booking Window', result.valid_booking_window);
            if (result.lab_required) html += renderField('Lab Required', result.lab_details || 'Yes');
            if (result.questionnaire) html += renderField('Questionnaire', result.questionnaire);
            if (result.partner_questionnaire) html += renderField('Partner Quest.', result.partner_questionnaire);
            if (result.guidance_document) html += renderField('Guidance Doc', result.guidance_document);
            if (result.self_pay) html += renderField('Self-Pay', result.self_pay_price_dkk ? `${result.self_pay_price_dkk} DKK` : 'Yes');
            if (result.provera_recommended) html += renderField('Provera', 'Recommended');
        }

        // Confirmation message
        if (data.confirmation) {
            html += `<div class="result-confirmation">${escapeHtml(data.confirmation)}</div>`;
        }

        resultCardBody.innerHTML = html;

        // Add confirmation as agent message
        if (data.confirmation) {
            addMessage('agent', data.confirmation);
        }

        // Disable input
        chatInput.disabled = true;
        chatInput.placeholder = 'Session complete';
        sendBtn.disabled = true;
    }

    function renderField(label, value) {
        if (!value) return '';
        return `<div class="result-field"><span class="result-field-label">${escapeHtml(label)}</span><span class="result-field-value">${escapeHtml(String(value))}</span></div>`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // =========================================================================
    // Event Listeners
    // =========================================================================

    startBtn.addEventListener('click', createSession);
    newSessionBtn.addEventListener('click', createSession);

    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = chatInput.value;
        if (text.trim()) {
            sendMessage(text);
            chatInput.value = '';
        }
    });

})();
