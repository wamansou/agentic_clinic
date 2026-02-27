# AI Triage Conversation Chain
### Kvinde Klinikken — Patient Intake via WhatsApp / Web Chat

> **How to read this document:**
> Each numbered step is something the AI does or asks. Indented sub-items show branching logic.
> `→ HANDOFF` means transfer to a human. `→ CONTINUE` means proceed to next step.
> Items marked with ⚠️ are edge cases to validate with the clinic.

---

## Step 0: Language & Channel Setup

0. Patient sends first message (WhatsApp / web chat)
1. Detect language (Danish expected, but could be English)
2. Respond in detected language
3. Set greeting:
   > "Welcome to Kvinde Klinikken. I'm an AI assistant that can help you book an appointment. I'll ask you a few questions to find the right time and doctor for you. You can type 'speak to staff' at any time to be connected to a person."

---

## Step 1: GDPR Consent

4. Ask for consent to process health data:
   > "Before we begin, I need your consent to process your health information for booking purposes. Your data is handled according to GDPR and Danish health data regulations. Do you consent?"
   1. **Yes** → CONTINUE to Step 2
   2. **No** → "I understand. Unfortunately I need your consent to help with booking. You can call the clinic directly at [phone number] instead." → END
   3. ⚠️ **Open question for clinic:** Do we need separate consent for AI processing vs. the existing 4 consent items in their questionnaire? Or is this covered by the questionnaire they already send?

---

## Step 2: Insurance Check

5. Ask about insurance:
   > "Are you covered by Danish public health insurance (sygesikring), or do you have private health insurance (e.g. Dansk Sundhedssikring / DSS)?"
   1. **Private / DSS** → Flag as DSS patient
      - All DSS patients MUST see Dr. LB regardless of condition
      - Mark booking with "DSS"
      - → HANDOFF to staff: "Private insurance patients need individual handling. Let me connect you with our staff."
      - ⚠️ **Reason for handoff:** DSS has variable time, priority, lab, and questionnaire requirements. Too many unknowns for AI to handle safely in Phase 1.
   2. **Public (sygesikring)** → CONTINUE to Step 3
   3. **Not sure** → "No problem — most patients in Denmark have public health insurance (the yellow health card). If you have a separate private policy like Dansk Sundhedssikring, please let me know. Otherwise we'll continue with standard booking." → Assume public, CONTINUE

---

## Step 3: Referral Check

6. Ask about referral:
   > "Do you have a referral (henvisning) from your doctor for this visit?"
   1. **Yes, I have a referral** → CONTINUE to Step 4
   2. **No, I don't have a referral**
      - → "Most gynaecological consultations in Denmark require a referral from your GP. I'd recommend contacting your doctor first to get a referral, then coming back to book."
      - → "If you believe your situation is urgent (heavy bleeding, severe pain, or pregnancy complications), please call us directly at [phone number]."
      - → END
      - ⚠️ **Open question:** Are there any services the clinic offers without referral? (e.g. contraception counselling, smear tests?) Validate with clinic.
   3. **I'm an existing patient / follow-up** → CONTINUE to Step 4
      - Mark as follow-up — routing may differ (e.g. menopause follow-up must go to same doctor who started treatment)

---

## Step 4: Identify the Condition

7. Ask what they need help with:
   > "Can you briefly describe why you need to see us? For example: bleeding, pain, pregnancy, fertility, contraception, IUD (spiral), smear test, etc."

8. Classify response into one of these **condition categories** (AI uses the patient's description + referral info to match):

   ### Category A: URGENT — Same Day (→ immediate HANDOFF)
   If the patient describes any of the following, do NOT continue triage. Hand off to staff immediately.
   1. **Acute/heavy bleeding** (e.g. "heavy bleeding", "bleeding after procedure") → HANDOFF
   2. **Sudden severe pain** (e.g. "sudden pain", "can't stand up") → HANDOFF
   3. **Suspected ectopic pregnancy** (e.g. "pregnant + pain", "pregnant but no findings on scan") → HANDOFF
   4. **Pregnancy with bleeding/pain** (1st trimester) → HANDOFF
   5. **Medical abortion request** → HANDOFF (must be same day; doctor gives guidance directly)
   > "Based on what you've described, this sounds like it may need urgent attention. Let me connect you with our staff right away so we can get you seen today."

   ### Category B: HIGH PRIORITY — Within 1-2 Weeks
   6. **Cancer package referral** → Doctor: HS/LB, 30 min, within 1 week → CONTINUE to Step 5
   7. **Postmenopausal bleeding** → Doctor: HS, 30 min, within 1 week → CONTINUE to Step 5
   8. **Cone biopsy / conisation** → Doctor: HS, 30 min, within 14 days → CONTINUE to Step 5
   9. **Contact bleeding (cervical)** → Doctor: LB, 30 min, within 14 days → CONTINUE to Step 5

   ### Category C: STANDARD — Cycle-Dependent
   These are the bulk of bookings. AI continues to Step 5 to determine doctor, timing, and prerequisites.

   **Fertility:**
   10. Initial fertility consultation → LB, 45 min
   11. Insemination → LB, 15 min
   12. Follicle scanning → LB, 15 min
   13. HSU (tube exam) → LB, 15 min

   **Pregnancy (non-urgent):**
   14. Pregnancy scan without symptoms → LB, 15 min, within 1 week

   **Bleeding:**
   15. Premenopausal bleeding → LB (but HS if patient > 45 yrs), 30 min

   **Pain:**
   16. Pelvic pain / dyspareunia (NOT menstrual) → LB, 30 min
   17. Menstrual pain (possible endometriosis) → HS, 45 min

   **Endometriosis:**
   18. New referral → HS, 45 min

   **IUD (Spiral):**
   19. Insertion → LB, 30 min
   20. Standard removal (strings visible) → LB, 15 min
   21. Replacement → LB, 30 min
   22. Removal > 8 years old → HS, 30 min
   23. Hysteroscopic removal/insertion (no visible strings) → HS, 30 min

   **Contraception:**
   24. Contraception counselling → LB, 30 min
   25. Implant insertion → LB, 30 min
   26. Implant removal → LB, 30 min

   **Cysts:**
   27. Ovarian cysts → LB, 30 min, within 1 month
   28. Vulva/vaginal cysts (e.g. Bartholin) → LB, 15 min

   **Menopause:**
   29. New referral → HS (or LB if uncomplicated), 30 min
   30. Follow-up → Same doctor who started treatment, 15 min

   **Incontinence / Urinary:**
   31. New referral → LB, 30 min
   32. Follow-up → LB, 15 min
   33. Recurrent UTI → LB, 30 min

   **Prolapse:**
   34. Prolapse / cystocele / rectocele → LB, 30 min
   35. Prolapse ring: new → LB, 30 min
   36. Prolapse ring: change/fitting → LB, 15 min

   **Cervical:**
   37. Cell changes (abnormal smear) → LB, 30 min, within 1 month
   38. Smear test (routine) → LB, 15 min

   **PCOS:**
   39. New referral → LB, 30 min
   40. Follow-up → LB, 15 min

   **Procedures:**
   41. Hysteroscopy → HS, 30 min
   42. Cystoscopy → HS, 30 min
   43. Polyp removal (cervical) → HS, 45 min
   44. Polyp removal (uterine) → HS, 45 min

   **Skin:**
   45. Lichen sclerosus: new → LB, 30 min
   46. Lichen sclerosus: follow-up with symptoms → LB, 30 min
   47. Lichen sclerosus: annual check → LB, 15 min

   **Vulva/Vagina:**
   48. Birth tear damage → LB, 30 min
   49. Vaginal opening issues → LB, 30 min
   50. Itching/burning/discharge → LB, 30 min

   **Other:**
   51. Tamoxifen follow-up → LB, 20 min
   52. Second opinion → HS (LB if fertility), 30 min
   53. Fibroids → LB, 30 min

   ### If AI cannot classify:
   > "I want to make sure we book you correctly. Let me connect you with our staff who can help find the right appointment for you."
   → HANDOFF

---

## Step 5: Conditional Doctor Routing

9. For conditions where routing depends on additional factors, ask follow-up questions:

   **Premenopausal bleeding (item 15):**
   > "May I ask your age?"
   1. Over 45 → Route to Dr. HS instead of LB
   2. Under 45 → Stay with Dr. LB

   **IUD removal (item 20):**
   > "When we look at your IUD, can the strings (snorene) usually be seen at your check-ups?"
   1. Yes, strings visible → LB, 15 min (standard removal)
   2. No / not sure → HS, 30 min (hysteroscopic removal)

   **IUD replacement (item 21):**
   > Same strings question as above
   1. Strings visible → LB, 30 min
   2. Strings not visible → HS, 30 min

   **Menopause new referral (item 29):**
   > "Have you previously been seen by Dr. Skensved at our clinic?"
   1. Yes → Route to HS
   2. No + uncomplicated → LB acceptable (faster availability)

   **Menopause follow-up (item 30):**
   > "Which doctor did you see last time?"
   - Route to same doctor

   **Second opinion (item 52):**
   > "Is your second opinion related to fertility treatment?"
   1. Yes → LB
   2. No → HS

---

## Step 6: Cycle Data Collection

10. Check if the procedure has cycle-day constraints. If yes, ask:
    > "Some procedures need to be scheduled on specific days of your menstrual cycle. When was the first day of your last period?"

11. Patient provides date. Calculate valid booking windows:

    | Procedure | Valid Cycle Days | Example: Last period Feb 10 |
    |-----------|------------------|-----------------------------|
    | IUD insertion | CD 3-7 | Feb 12-16 |
    | PCOS blood panel | CD 3 | Feb 12 |
    | Follicle scanning | CD 2-4 | Feb 11-13 |
    | Hysteroscopy | CD 4-8 | Feb 13-17 |
    | Polyp removal (uterine) | CD 4-8 | Feb 13-17 |
    | Polyp removal (cervical) | CD 5-7 | Feb 14-16 |
    | HSU / fertility consult | CD 6-10 | Feb 15-19 |
    | Implant insertion | CD 1-5 | Feb 10-14 |
    | Endometriosis (ideal) | Just before next period | ~Mar 7-9 |

12. If the valid window has already passed this cycle:
    > "The best time for this procedure would be [cycle days] of your cycle. Based on your last period, that window has passed for this month. The next window would be around [calculated dates]. Shall I look for availability then?"

13. Also check restrictions:
    - "Not during menstruation" → Ask if currently menstruating
    - "Not during ovulation" → Calculate ~CD 14 and avoid
    - "Morning urine required" → Inform patient to bring morning urine sample

---

## Step 7: Lab Prerequisite Check

14. Check if the procedure requires lab work before booking can be confirmed:

    **IUD (any type) + patient under 30:**
    > "For patients under 30, we need a negative chlamydia test before IUD procedures. Have you had one recently, or would you like to have it done at the clinic?"
    1. Already have recent negative result → CONTINUE
    2. Need to get tested → "You can get tested at the clinic. We'll book a tentative appointment and confirm once results are in."

    **Fertility (initial consultation):**
    > "Before your first fertility appointment, we need some blood tests for both you and your partner:"
    > - "You: fertility blood panel"
    > - "Your partner: fertility blood panel + semen analysis (at hospital AND at clinic)"
    > - "Both: HIV, Hepatitis B & C tests (results must be less than 2 years old)"
    > "Do you already have these results?"
    1. Yes, all available → CONTINUE
    2. Partially / no → "Let's get these ordered. Your doctor should be available before your first treatment cycle."

    **PCOS (new referral):**
    > "We'll need a blood panel taken on day 3 of your cycle. If you haven't had a period recently or have very long cycles, the doctor may prescribe Provera for 10 days to bring on a period first."

    **Incontinence (new referral):**
    > "Before your appointment, please complete a voiding diary (fluid intake and urination log) for at least 3 days. We'll send you the form. Also, please bring a morning urine sample to your appointment."

    **Menopause (new, patient under 45):**
    > "Since you're under 45, we'll order a menopause blood panel before your appointment."

    **Medical abortion:** (already handed off in Step 4, but for reference)
    > Blood tests taken at clinic, must be before lunch for same-day courier pickup.

---

## Step 8: Questionnaire Dispatch

15. Based on the identified condition, automatically send the correct pre-visit questionnaire:

    | Condition matches | Questionnaire to send |
    |-------------------|-----------------------|
    | Ovarian cysts, vulva cysts, lichen sclerosus (new), menopause (new), PCOS, prolapse, prolapse ring (new), recurrent UTI, vulva/vagina issues (all 4), incontinence (both) | **"You & Your Gynaecological Problem"** |
    | Premenopausal bleeding, contact bleeding | **"Premenopausal Bleeding"** |
    | Endometriosis, pelvic pain, dyspareunia, menstrual pain | **"Pelvic Pain"** |
    | Cervical cell changes | **"Cell Changes"** |
    | Incontinence (new + follow-up) | **"Urinary Problems / Incontinence"** |
    | Fertility (initial) — for female patient | **"Infertility Questionnaire (UXOR)"** |
    | Fertility (initial) — for male partner | **"Infertility Questionnaire (VIR)"** |

16. Send message with questionnaire link:
    > "I'm sending you a questionnaire to fill out before your appointment. It helps the doctor prepare and means less time spent on paperwork during your visit. Please complete it at least 24 hours before your appointment."

17. For fertility patients, also send partner questionnaire:
    > "I'm also sending a separate questionnaire for your partner. Please have them fill it out as well."

18. If no questionnaire matches (e.g. smear test, fibroids, tamoxifen follow-up):
    → Skip this step, proceed to booking.

---

## Step 9: Patient Guidance Documents

19. Some procedures have specific patient information to send:

    | Procedure | Guidance document |
    |-----------|-------------------|
    | Cone biopsy | "Kegleoperation" (Cone operation info) |
    | Cervical cell changes / contact bleeding | "Tissue samples from cervix" |
    | Polyp removal (any) | "Removed polyp" info |
    | Medical abortion | Given directly by doctor (not sent in advance) |

20. Send with message:
    > "Here's some information about your upcoming procedure. Please read it before your appointment so you know what to expect."

---

## Step 10: Booking

21. Present available slots based on ALL collected constraints:
    - Correct doctor (HS or LB)
    - Correct duration (15, 20, 30, or 45 min)
    - Priority window (same day / 1 week / 14 days / 1 month / standard)
    - Valid cycle days (if applicable)
    - Restrictions respected (not during menstruation, etc.)
    - Lab results timeline (if needed, tentative booking)

22. Offer 2-3 options:
    > "Based on everything, here are available times with Dr. [Name]:"
    > "1. [Date, Time]"
    > "2. [Date, Time]"
    > "3. [Date, Time]"
    > "Which works best for you? Or would you like to see more options?"

23. Patient selects a slot:
    > "Your appointment is booked:"
    > "📅 [Date] at [Time]"
    > "👩‍⚕️ Dr. [Name]"
    > "⏱️ [Duration] minutes"
    > "[Any special instructions: bring morning urine, don't eat before, etc.]"

24. If lab work is still pending:
    > "Your appointment is tentatively booked for [date]. We'll confirm once your [test] results are in. If we don't receive them by [deadline], we'll reach out to reschedule."

---

## Step 11: Confirmation & Reminders

25. Send confirmation summary with:
    - Date, time, doctor
    - Clinic address
    - What to bring (if anything)
    - Reminder to complete questionnaire
    - How to cancel/reschedule

26. Schedule automated reminders:
    - 48 hours before: "Reminder: your appointment is in 2 days. Have you completed your questionnaire?"
    - 24 hours before: "Your appointment is tomorrow at [time] with Dr. [name]. [Any prep instructions]."
    - If questionnaire not completed: "Please fill out your questionnaire before tomorrow's visit: [link]"

---

## Escalation Rules (When to HANDOFF to Staff)

Always hand off if:
- Patient explicitly asks to speak to a person
- Any same-day urgent condition (Step 4, Category A)
- DSS / private insurance patient
- AI cannot confidently classify the condition
- Patient seems distressed, confused, or anxious
- Patient describes symptoms that don't match any of the 56 procedures
- Patient is in their 2nd or 3rd trimester with bleeding → direct to hospital, not clinic
- Anything involving medication changes or dosage questions

---

## Open Questions for Clinic Validation

1. **Referral-free services:** Can patients book contraception counselling, smear tests, or IUD procedures without a GP referral?
2. **Existing patients:** How should the AI handle existing patients who are calling for follow-ups? Do they still need a referral?
3. **Consent flow:** Is the GDPR consent for AI processing separate from the 4 consent items in the existing questionnaire?
4. **Novax integration:** Can we read appointment availability from Novax? Can we write bookings? Or does the AI just collect info and staff do the actual booking?
5. **Questionnaire delivery:** Can we send questionnaire links via WhatsApp? Or does it need to go through the Novax system?
6. **Partner booking (fertility):** Can we book partner appointments (semen analysis) through this system, or is that handled separately?
7. **Age collection:** Is it okay for the AI to ask the patient's age for routing purposes (premenopausal bleeding > 45)?
8. **Cycle tracking:** How should we handle patients with irregular cycles or no periods (e.g. amenorrhea, PCOS)?
9. **Language:** Should the AI support English as well, or Danish only?
10. **Operating hours:** Should the AI only offer booking during clinic hours, or 24/7 with confirmation the next business day?
