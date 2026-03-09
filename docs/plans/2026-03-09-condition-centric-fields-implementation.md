# Condition-Centric Fields Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 10 new structured fields to conditions (contraindications, age_range, visits_required, preparation_instructions, companion_required, estimated_recovery, equipment, followup_interval) plus expose existing lab and guidance_document in the editor — all editable via UI, all feeding the agent and confirmation flows.

**Architecture:** All new fields live in `conditions.yaml` per condition, exposed in the conditions editor UI, read by the agent via `fetch_condition_details`, and fed to the confirmation agent via `build_confirmation_context`. The `BookingRequest` model gains new fields so enrichment data reaches the result card and staff view.

**Tech Stack:** Python/FastAPI, Pydantic, YAML, vanilla JS, Jinja2 templates

---

### Task 1: Add new fields to conditions.yaml

**Files:**
- Modify: `conditions.yaml`

**Step 1: Add new fields to every condition**

Add these fields to all 53 conditions, defaulting to `null`/`false`:

```yaml
  contraindications: null
  age_range: null
  visits_required: null
  preparation_instructions: null
  companion_required: false
  estimated_recovery: null
  equipment: null
  followup_interval: null
```

Place them after the existing `questions` field (or after `special_instructions` if present), before the next condition entry.

**Step 2: Populate known data from existing special_instructions and domain knowledge**

Migrate these known values:

- **Condition 5 (Medical abortion):** `age_range: {min: 15, max: null}`
- **Condition 23 (Hysteroscopic IUD removal/insertion):** `equipment: [hysteroscope]`
- **Condition 41 (Hysteroscopy):** `equipment: [hysteroscope]`
- **Condition 42 (Cystoscopy):** `equipment: [cystoscope]`
- **Condition 44 (Polyp removal — uterine):** `equipment: [hysteroscope]`

**Step 3: Verify YAML loads correctly**

Run:
```bash
source .venv/bin/activate && python -c "from triage.config import get_conditions; c = get_conditions(); print(f'{len(c)} conditions loaded'); print(c[5].get('age_range')); print(c[23].get('equipment'))"
```
Expected: `53 conditions loaded`, `{'min': 15, 'max': None}`, `['hysteroscope']`

**Step 4: Commit**

```bash
git add conditions.yaml
git commit -m "Add new condition-centric fields to all 53 conditions"
```

---

### Task 2: Update BookingRequest model

**Files:**
- Modify: `triage/models.py`

**Step 1: Add new fields to BookingRequest**

Add after the existing `notes` field (line 52):

```python
    preparation_instructions: list[str] | None = None
    companion_required: bool = False
    estimated_recovery: str | None = None
    equipment: list[str] | None = None
    followup_interval: str | None = None
    visits_required: int | None = None
    contraindications: list[str] | None = None
```

**Step 2: Verify model loads**

Run:
```bash
source .venv/bin/activate && python -c "from triage.models import BookingRequest; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add triage/models.py
git commit -m "Add new condition-centric fields to BookingRequest model"
```

---

### Task 3: Update enrichment in orchestrator.py

**Files:**
- Modify: `triage/orchestrator.py:40-100` (enrich_booking function)
- Modify: `triage/orchestrator.py:103-128` (build_confirmation_context function)

**Step 1: Add new field enrichment to enrich_booking**

After the self-pay block (line 98), before `return booking`, add:

```python
    # New condition-centric fields
    if cond.get("preparation_instructions"):
        booking.preparation_instructions = cond["preparation_instructions"]
    if cond.get("companion_required"):
        booking.companion_required = True
    if cond.get("estimated_recovery"):
        booking.estimated_recovery = cond["estimated_recovery"]
    if cond.get("equipment"):
        booking.equipment = cond["equipment"]
    if cond.get("followup_interval"):
        booking.followup_interval = cond["followup_interval"]
    if cond.get("visits_required"):
        booking.visits_required = cond["visits_required"]
    if cond.get("contraindications"):
        booking.contraindications = cond["contraindications"]
```

**Step 2: Update build_confirmation_context to feed new fields to confirmation agent**

After the self-pay block (line 125) and before the final `parts.append(...)` line, add:

```python
    if booking.preparation_instructions:
        parts.append("Preparation before visit:")
        for instr in booking.preparation_instructions:
            parts.append(f"  - {instr}")
    if booking.companion_required:
        parts.append("IMPORTANT: Patient needs someone to drive them home after the procedure.")
    if booking.estimated_recovery:
        parts.append(f"Expected recovery: {booking.estimated_recovery}")
    if booking.visits_required and booking.visits_required > 1:
        parts.append(f"This typically requires {booking.visits_required} visits.")
```

**Step 3: Verify enrichment works with a condition that has new fields**

Run:
```bash
source .venv/bin/activate && python -c "
from triage.models import TriageData
from triage.orchestrator import enrich_booking
td = TriageData(condition_id=23, doctor='HS', condition_name='Hysteroscopic IUD', category='C')
b = enrich_booking(td)
print('equipment:', b.equipment)
"
```
Expected: `equipment: ['hysteroscope']`

**Step 4: Commit**

```bash
git add triage/orchestrator.py
git commit -m "Enrich bookings with new condition-centric fields and feed to confirmation agent"
```

---

### Task 4: Update triage agent prompt for contraindications and age_range

**Files:**
- Modify: `triage/agents.py:77-81` (step 5 in conversation flow)
- Modify: `triage/config.py:80-112` (build_condition_reference)

**Step 1: Update conversation flow step 5 in agents.py**

Replace the existing step 5 block (around lines 77-80):

```
5. CONDITION-SPECIFIC QUESTIONS — Only if the condition has questions (from fetch_condition_details result):
   - Ask each question from the condition's "questions" list, one at a time
   - Follow the special_instructions for that condition (shown with ⚠ in the CONDITION REFERENCE below)
   - If no questions → use the condition's default doctor
```

With:

```
5. CONDITION-SPECIFIC CHECKS — After calling fetch_condition_details, check the result for:
   - "questions": Ask each question from the list, one at a time
   - "age_range": If min or max is set and you don't know the patient's age yet, ask their age. If outside range → escalate with reason "Patient age outside eligible range for [condition]"
   - "contraindications": Review what the patient has told you so far. If any contraindication applies, inform the patient and escalate with reason "Contraindication: [detail]"
   - "visits_required": If > 1, mention to the patient that this typically requires multiple visits
   - Follow the special_instructions for that condition (shown with ⚠ in the CONDITION REFERENCE below)
   - If no questions and no routing instructions → use the condition's default doctor
```

**Step 2: Update build_condition_reference in config.py to include new structured fields**

In the `build_condition_reference()` function, after the `special_instructions` block (lines 98-102), add display of key new fields:

```python
            if c.get("contraindications"):
                lines.append(f"    ⛔ Contraindications: {', '.join(c['contraindications'])}")
            if c.get("age_range"):
                ar = c["age_range"]
                parts = []
                if ar.get("min"):
                    parts.append(f"min {ar['min']}")
                if ar.get("max"):
                    parts.append(f"max {ar['max']}")
                if parts:
                    lines.append(f"    🔢 Age range: {', '.join(parts)}")
```

**Step 3: Verify prompt includes new fields**

Run:
```bash
source .venv/bin/activate && python -c "
from triage.config import get_condition_reference
ref = get_condition_reference()
# Check condition 5 shows age range
for line in ref.split('\n'):
    if 'Age range' in line or 'abortion' in line.lower():
        print(line)
"
```
Expected: Should show age range line for condition 5.

**Step 4: Commit**

```bash
git add triage/agents.py triage/config.py
git commit -m "Update triage prompt to use structured contraindications and age_range fields"
```

---

### Task 5: Add new fields to conditions editor HTML

**Files:**
- Modify: `templates/conditions.html:92-114` (inside the form, before special_instructions)

**Step 1: Add new form sections**

After the existing "Condition-Specific Questions" block (line 96) and before the "Questionnaires" block (line 97), add three grouped sections. Insert after the closing `</div>` of the questions block:

```html
                    <!-- Triage Fields -->
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label class="form-label">Contraindications</label>
                        <div id="cf-contraindications-list" class="dynamic-list"></div>
                        <button type="button" class="btn btn-outline btn-sm" id="addContraindicationBtn" style="margin-top: 6px;">+ Add Contraindication</button>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-age-min">Min Age</label>
                        <input type="number" class="form-input" id="cf-age-min" min="0" max="120" placeholder="No minimum">
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-age-max">Max Age</label>
                        <input type="number" class="form-input" id="cf-age-max" min="0" max="120" placeholder="No maximum">
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-visits-required">Visits Required</label>
                        <input type="number" class="form-input" id="cf-visits-required" min="1" placeholder="1">
                    </div>

                    <!-- Patient Preparation Fields -->
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label class="form-label">Preparation Instructions</label>
                        <div id="cf-preparation-list" class="dynamic-list"></div>
                        <button type="button" class="btn btn-outline btn-sm" id="addPreparationBtn" style="margin-top: 6px;">+ Add Instruction</button>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-companion-required">
                            <input type="checkbox" id="cf-companion-required"> Companion / Driver Required
                        </label>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-estimated-recovery">Estimated Recovery</label>
                        <input type="text" class="form-input" id="cf-estimated-recovery" placeholder="e.g. 1-2 days of light discomfort">
                    </div>

                    <!-- Clinic / Scheduling Fields -->
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label class="form-label">Equipment Required</label>
                        <div id="cf-equipment-list" class="dynamic-list"></div>
                        <button type="button" class="btn btn-outline btn-sm" id="addEquipmentBtn" style="margin-top: 6px;">+ Add Equipment</button>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="cf-followup-interval">Follow-up Interval</label>
                        <input type="text" class="form-input" id="cf-followup-interval" placeholder="e.g. 4-6 weeks">
                    </div>

                    <!-- Lab Requirements (existing in YAML, now editable) -->
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label class="form-label">Lab Requirements</label>
                        <div class="cond-form-grid" style="gap: 8px;">
                            <div class="form-group">
                                <label class="form-label form-label-sm" for="cf-lab-test">Test(s)</label>
                                <input type="text" class="form-input" id="cf-lab-test" placeholder="e.g. chlamydia, blood panel">
                            </div>
                            <div class="form-group">
                                <label class="form-label form-label-sm" for="cf-lab-condition">Condition</label>
                                <select class="form-input" id="cf-lab-condition">
                                    <option value="">No lab required</option>
                                    <option value="always">Always</option>
                                    <option value="age_under_30">Under 30 only</option>
                                    <option value="age_under_45">Under 45 only</option>
                                </select>
                            </div>
                            <div class="form-group" style="grid-column: 1 / -1;">
                                <label class="form-label form-label-sm" for="cf-lab-description">Description</label>
                                <input type="text" class="form-input" id="cf-lab-description" placeholder="e.g. Negative chlamydia test required">
                            </div>
                        </div>
                    </div>

                    <!-- Guidance Document (existing in YAML, now editable) -->
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label class="form-label" for="cf-guidance-document">Guidance Document</label>
                        <input type="text" class="form-input" id="cf-guidance-document" placeholder="URL or document name">
                    </div>
```

**Step 2: Commit**

```bash
git add templates/conditions.html
git commit -m "Add new condition-centric fields to editor HTML"
```

---

### Task 6: Update conditions.js to handle new fields

**Files:**
- Modify: `static/js/conditions.js`

**Step 1: Add generic dynamic list helper**

After the existing `addQuestionRow` function (line 140), add:

```javascript
    function addDynamicRow(containerId, text) {
        const container = document.getElementById(containerId);
        const row = document.createElement('div');
        row.className = 'question-row';
        row.innerHTML = `
            <input type="text" class="form-input dl-text" value="${escapeAttr(text)}">
            <button type="button" class="btn btn-outline btn-sm q-remove" title="Remove">&times;</button>
        `;
        row.querySelector('.q-remove').addEventListener('click', () => row.remove());
        container.appendChild(row);
    }

    function collectDynamicList(containerId) {
        const items = [];
        document.querySelectorAll(`#${containerId} .question-row`).forEach(row => {
            const text = row.querySelector('.dl-text').value.trim();
            if (text) items.push(text);
        });
        return items.length ? items : null;
    }

    function renderDynamicList(containerId, items) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        (items || []).forEach(text => addDynamicRow(containerId, text));
    }
```

**Step 2: Update populateForm to load new fields**

After line 99 (`document.getElementById('cf-special-instructions').value = c.special_instructions || '';`), add:

```javascript
        // New condition-centric fields
        renderDynamicList('cf-contraindications-list', c.contraindications);
        document.getElementById('cf-age-min').value = (c.age_range && c.age_range.min) || '';
        document.getElementById('cf-age-max').value = (c.age_range && c.age_range.max) || '';
        document.getElementById('cf-visits-required').value = c.visits_required || '';
        renderDynamicList('cf-preparation-list', c.preparation_instructions);
        document.getElementById('cf-companion-required').checked = !!c.companion_required;
        document.getElementById('cf-estimated-recovery').value = c.estimated_recovery || '';
        renderDynamicList('cf-equipment-list', c.equipment);
        document.getElementById('cf-followup-interval').value = c.followup_interval || '';

        // Lab (existing, now editable)
        if (c.lab) {
            const testVal = Array.isArray(c.lab.tests) ? c.lab.tests.join(', ') : (c.lab.test || '');
            document.getElementById('cf-lab-test').value = testVal;
            document.getElementById('cf-lab-condition').value = c.lab.condition || '';
            document.getElementById('cf-lab-description').value = c.lab.description || '';
        } else {
            document.getElementById('cf-lab-test').value = '';
            document.getElementById('cf-lab-condition').value = '';
            document.getElementById('cf-lab-description').value = '';
        }

        // Guidance document (existing, now editable)
        document.getElementById('cf-guidance-document').value = c.guidance_document || '';
```

**Step 3: Update collectForm to save new fields**

In the `collectForm` function, after the `special_instructions` line (line 174), add:

```javascript
        // New condition-centric fields
        const contraindications = collectDynamicList('cf-contraindications-list');
        if (contraindications) data.contraindications = contraindications;
        else data.contraindications = null;

        const ageMin = parseInt(document.getElementById('cf-age-min').value) || null;
        const ageMax = parseInt(document.getElementById('cf-age-max').value) || null;
        data.age_range = (ageMin || ageMax) ? { min: ageMin, max: ageMax } : null;

        data.visits_required = parseInt(document.getElementById('cf-visits-required').value) || null;

        const prepInstructions = collectDynamicList('cf-preparation-list');
        if (prepInstructions) data.preparation_instructions = prepInstructions;
        else data.preparation_instructions = null;

        data.companion_required = document.getElementById('cf-companion-required').checked;
        data.estimated_recovery = document.getElementById('cf-estimated-recovery').value.trim() || null;

        const equipment = collectDynamicList('cf-equipment-list');
        if (equipment) data.equipment = equipment;
        else data.equipment = null;

        data.followup_interval = document.getElementById('cf-followup-interval').value.trim() || null;

        // Lab
        const labCondition = document.getElementById('cf-lab-condition').value;
        if (labCondition) {
            const labTestRaw = document.getElementById('cf-lab-test').value.trim();
            const labTests = labTestRaw.includes(',')
                ? labTestRaw.split(',').map(s => s.trim()).filter(Boolean)
                : labTestRaw;
            data.lab = {
                test: Array.isArray(labTests) ? undefined : labTests,
                tests: Array.isArray(labTests) ? labTests : undefined,
                condition: labCondition,
                description: document.getElementById('cf-lab-description').value.trim() || '',
            };
            // Clean up: only use test or tests, not both
            if (data.lab.test) delete data.lab.tests;
            else delete data.lab.test;
        } else {
            data.lab = null;
        }

        // Guidance document
        data.guidance_document = document.getElementById('cf-guidance-document').value.trim() || null;
```

**Step 4: Register event listeners for new dynamic list buttons**

After the existing `addQuestionBtn` listener (line 239), add:

```javascript
    document.getElementById('addContraindicationBtn').addEventListener('click', () => {
        addDynamicRow('cf-contraindications-list', '');
    });
    document.getElementById('addPreparationBtn').addEventListener('click', () => {
        addDynamicRow('cf-preparation-list', '');
    });
    document.getElementById('addEquipmentBtn').addEventListener('click', () => {
        addDynamicRow('cf-equipment-list', '');
    });
```

**Step 5: Update the cache-busting version on the script tag**

In `templates/conditions.html`, update the script tag version:
```html
<script src="/static/js/conditions.js?v=20260309a"></script>
```

**Step 6: Commit**

```bash
git add static/js/conditions.js templates/conditions.html
git commit -m "Add JS handling for new condition-centric fields in editor"
```

---

### Task 7: Manual integration test

**Step 1: Start the server**

```bash
source .venv/bin/activate && python main.py
```

**Step 2: Test the editor**

1. Go to http://localhost:8000/conditions
2. Click on condition 23 (Hysteroscopic IUD)
3. Verify `equipment: [hysteroscope]` shows in the equipment list
4. Verify lab fields are empty (condition 23 has no lab)
5. Add a preparation instruction: "Take ibuprofen 1 hour before"
6. Check "Companion / Driver Required"
7. Save — verify YAML file updated

**Step 3: Test condition with lab**

1. Click on condition 19 (IUD insertion)
2. Verify lab shows: test=chlamydia, condition=Under 30 only, description populated
3. Save without changes — verify YAML unchanged

**Step 4: Test condition with age_range**

1. Click on condition 5 (Medical abortion)
2. Verify age_range shows min=15
3. Save without changes — verify preserved

**Step 5: Run existing war games to check nothing broke**

```bash
source .venv/bin/activate && python -m tests.war_games.run_war_games
```

Expected: All scenarios pass (same as before).

**Step 6: Commit any fixes if needed**

---

### Task 8: Final commit and version bump

**Step 1: Update conditions.js cache version**

Ensure `conditions.html` script tag has updated version string.

**Step 2: Final commit**

```bash
git add -A
git commit -m "Complete condition-centric fields expansion: YAML, editor, enrichment, agent prompt"
```
