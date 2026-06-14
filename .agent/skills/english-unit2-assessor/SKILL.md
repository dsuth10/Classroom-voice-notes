---
name: english-unit2-assessor
description: Evaluates Year 5 student drafts for English Unit 2 (Part B - Written Information Report) against official rubrics, flagging plagiarism and providing constructive, Socratic feedback without rewriting the student's work.
---

# English Unit 2 Assessor — Socratic Writing Feedback

This skill outlines the master workflow and strict pedagogical rules for assessing Year 5 student drafts for Part B of English Unit 2 (multimodal information reports on natural disasters like floods, cyclones, or bushfires).

---

## 🛑 P0 Safety Guardrail: Strict "No-Answers" Policy
*   **NEVER** rewrite sentences, paragraphs, or words for the student.
*   **NEVER** use "before-and-after" code/diff blocks that show direct solutions.
*   **ALWAYS** use inquiry-based questions, Socratic prompts, and checklist items.
*   **GOAL:** Guide the student's own editing and revision process rather than doing the editing for them.

---

## 🔄 Core Diagnostic Workflow

When a student draft is submitted:

1.  **Plagiarism Audit:** 
    *   Compare the student's text against the local website resources in `c:\Users\dsuth\Documents\Joshua\Units\English\English_Unit_2\Resources\Website\`.
    *   If matching text is found, identify the matching website page but **do not** copy the matching website text into the feedback.
    *   Synthesise a Socratic question asking the student to close their screen and explain the concept in their own words.

2.  **Rubric Evaluation:**
    *   Read the official Year 5 criteria in [references/part_b_rubric.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/references/part_b_rubric.md).
    *   Determine the current standard (A, B, C, D, or E) the draft aligns to across the core criteria: Text Structure, Language Features, and Research/Synthesis.

3.  **Prompt Selection:**
    *   Consult the diagnostic prompt banks in [references/socratic_prompt_bank.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/references/socratic_prompt_bank.md).
    *   Choose exactly **three priority wishes (revision goals)** that the student needs to address to reach the next standard level.

4.  **Feedback Sheet Generation:**
    *   Format the final feedback slip according to the standardised Markdown template in [assets/student_feedback_slip.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/assets/student_feedback_slip.md).
    *   Highlight positive highlights (Stars!) and the actionable Socratic wishes.

---

## 📖 Reference & Asset Navigation

*   **Assessment Standards Rubric:** [references/part_b_rubric.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/references/part_b_rubric.md)
*   **Diagnostic Prompt Bank:** [references/socratic_prompt_bank.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/references/socratic_prompt_bank.md)
*   **Standardised Output Template:** [assets/student_feedback_slip.md](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/english-unit2-assessor/assets/student_feedback_slip.md)
