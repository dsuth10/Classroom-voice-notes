---
name: leveled-text-creator
description: Generates educational reading passages calibrated for specific Australian Curriculum Year levels (Prep/Year 1 to Year 10). It employs the textstat Python library to analyse readability (Flesch-Kincaid Grade Level and Flesch Reading Ease) and runs an iterative drafting process to refine complexity. Simplification prioritises shortening sentences and adopting simple grammatical structures while retaining key subject-specific technical terminology and explaining abstract terms inline. Outputs Markdown, a detailed audit report, and a professionally designed Word (.docx) document.
skills:
  - text-analysis
  - docx
---

# Leveled Text Creator Skill

This skill enables the creation and calibration of educational reading texts mapped to specific Australian Curriculum Year levels and target word counts. It uses an iterative analysis-and-refinement process to adjust text difficulty, shifting complexity via sentence length and syntax while retaining curriculum content knowledge and domain-specific terminology.

---

## Readability & Year-Level Mapping

All text generation and validation must align with the following calibration thresholds:

| Year Level | Target Age | F-K Grade Range | Flesch Reading Ease Range | Target Word Count | Avg Sentence Length |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Year 1** | 6–7 yrs | 0.5 – 1.8 | 90 – 100 | 50 – 100 wds | 5 – 8 words |
| **Year 2** | 7–8 yrs | 1.8 – 2.8 | 85 – 95 | 100 – 150 wds | 8 – 10 words |
| **Year 3** | 8–9 yrs | 2.8 – 3.8 | 80 – 90 | 150 – 250 wds | 10 – 12 words |
| **Year 4** | 9–10 yrs | 3.8 – 4.8 | 75 – 85 | 200 – 300 wds | 12 – 14 words |
| **Year 5** | 10–11 yrs | 4.8 – 5.8 | 70 – 80 | 250 – 350 wds | 14 – 16 words |
| **Year 6** | 11–12 yrs | 5.8 – 6.8 | 65 – 75 | 300 – 400 wds | 15 – 18 words |
| **Year 7** | 12–13 yrs | 6.8 – 7.8 | 60 – 70 | 350 – 450 wds | 16 – 20 words |
| **Year 8** | 13–14 yrs | 7.8 – 8.8 | 55 – 65 | 400 – 500 wds | 18 – 22 words |
| **Year 9** | 14–15 yrs | 8.8 – 9.8 | 50 – 60 | 450 – 550 wds | 18 – 24 words |
| **Year 10** | 15–16 yrs | 9.8 – 11.0 | 40 – 55 | 500 – 600 wds | 18 – 25 words |

---

## Technical Content & Simplification Rules

To simplify readability without degrading the educational value of the text, follow these strict guidelines:

1. **Retain Technical Terminology**: Never replace or remove domain-specific vocabulary (e.g. *photosynthesis*, *evaporation*, *parliament*, *kinetic energy*).
2. **Inline Explanations**: Provide a brief definition of abstract or technical terms in parentheses immediately after the term is first introduced, e.g. *"evaporation (when water turns into a gas and goes into the air)"*.
3. **Syntax Modification over Content Removal**:
   - Shorten sentences by breaking compound or complex sentences into separate, simple sentences.
   - Prefer active voice (*"Green plants capture sunlight"* instead of *"Sunlight is captured by green plants"*).
   - Minimise subordinate clauses (avoiding terms like *whereas*, *although*, *consequently*, or *nevertheless* at lower year levels).
4. **Preserve Logic**: Ensure the logical steps in a process or arguments in an explanation remain intact. Simplify how they are explained, not what is explained.

---

## Outputs

Every creation run outputs the following files saved to a dedicated folder:

```
[output_dir]/
├── [Topic]_Y[N].md             ← The clean reading text in Markdown
├── [Topic]_Y[N]_Report.txt     ← The step-by-step audit log of all drafts and statistics
└── [Topic]_Y[N].docx           ← The professionally styled Word document for student use
```

---

## Workflow: Agent-Guided Execution

When executing this skill as an agent in the workspace:

### Step 1: Initial Draft
Draft the text based on the topic, year level, and target word count, keeping the *Simplification Rules* in mind.

### Step 2: Readability Assessment
Save the text to a temporary file (`tmp_text.txt`) and run the analyzer script to compute readability metrics:
```bash
python .agent/skills/leveled-text-creator/scripts/create_leveled_text.py --file tmp_text.txt --year_level [N] --analyse_only
```
Examine the output metrics (Flesch-Kincaid Grade Level, Flesch Reading Ease, average sentence length).

### Step 3: Iterative Revision
- **If too complex (F-K Grade is above range)**: Shorten sentences, break up clauses, and ensure abstract terms have inline explanations.
- **If not complex enough (F-K Grade is below range)**: Gradually combine short sentences using simple coordinators (e.g. *and*, *but*), use slightly longer phrasing, and introduce descriptive detail.
- Repeat the assessment until the text falls within the desired ranges.

### Step 4: Output Compilation
Write the final text to the output directory as Markdown and compile it into a Word document:
```bash
python .agent/skills/leveled-text-creator/scripts/create_leveled_text.py --text "[Pass Text]" --topic "[Topic]" --year_level [N] --output_dir "[Dir]"
```
Verify the output files are generated. Clean up any temporary files.

---

## Resources

- **`scripts/create_leveled_text.py`**: Python script that runs the analysis using the `textstat` library and coordinates the iterative refinement.
- **`scripts/create_docx.js`**: Node.js script that compiles the text into an attractively formatted `.docx` file using the `docx` library.
