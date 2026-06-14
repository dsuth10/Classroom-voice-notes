---
name: homework-creator
description: Creates a complete differentiated weekly homework pack for primary students. Generates three reading-level texts (DOCX) and three combined question documents in Microsoft Forms format — one per reading level — each containing comprehension questions answerable only from that level's text, plus a differentiated maths set. Follows a multi-step interactive dialogue to select the week number, units of work, and specific topics before generating any content. Use this skill whenever the user asks to create, build, or generate homework.
skills:
  - curriculum-master
  - text-analysis
  - microsoft-forms-assessment
  - docx
  - homework-print
---

# Homework Creator Skill

Generates a complete, differentiated weekly homework pack through a structured multi-step dialogue. No content is generated until the user has confirmed all topic selections.

---

## Colour Group Levels

All files and documents use colour group names, not level numbers:

| Colour Group | Level | Target Age  | Curriculum |
|--------------|-------|-------------|------------|
| **Red**      | L1    | 12–13 yrs   | Year 5+    |
| **Blue**     | L2    | 10–11 yrs   | Year 5     |
| **Green**    | L3    | 8–9 yrs     | Year 3/4   |

---

## Output Structure

Every session produces the following folder and files:

```
Joshua/Homework/Week_[N]/
├── Week_[N]_Reading_Red.docx        ← Reading text — Red Group (12–13 yrs)
├── Week_[N]_Reading_Blue.docx       ← Reading text — Blue Group (10–11 yrs)
├── Week_[N]_Reading_Green.docx      ← Reading text — Green Group (8–9 yrs)
├── Week_[N]_Questions_Red.docx      ← Red comprehension + Year 5 maths (Forms-ready)
├── Week_[N]_Questions_Blue.docx     ← Blue comprehension + Year 5 maths (Forms-ready)
├── Week_[N]_Questions_Green.docx    ← Green comprehension + Year 3/4 maths (Forms-ready)
├── Week_[N]_Print_Red.docx          ← Two-page student printable for Red Group
├── Week_[N]_Print_Blue.docx         ← Two-page student printable for Blue Group
├── Week_[N]_Print_Green.docx        ← Two-page student printable for Green Group
└── images/                          ← Optional: maths diagram PNGs (if required)
    └── q[N]_description.png
```

**Reading DOCX files** — formatted for print; contain only the article text with a clear heading.

**Questions DOCX files** — one per reading level, formatted strictly for Microsoft Forms import (see `microsoft-forms-assessment` skill). Each contains comprehension questions for that level's text, followed immediately by the appropriate maths questions, numbered continuously.

**Print DOCX files** — Student-ready printable two-page documents generated using the `homework-print` skill.

**Maths pairing rule:**
- Red questions document → Year 5 maths
- Blue questions document → Year 5 maths
- Green questions document → Year 3/4 maths

---

## Step 0: Session Start

**Ask the following two questions before anything else:**

1. "What week number are we creating homework for?"
2. "What is the current Reading/Writing unit topic, and what is the current Maths unit topic?"

Do not suggest topics or generate content until both answers are received.

---

## Step 1: Topic Suggestions

Once you have the units of work, present topic suggestions as numbered lists in three clearly labelled sections.

### Reading Topics
Generate **15 topic suggestions** based on the Reading/Writing unit:

```
INFORMATIONAL TEXT IDEAS
1. [Topic]
2. [Topic]
3. [Topic]
4. [Topic]
5. [Topic]

PERSUASIVE TEXT IDEAS
6. [Topic]
7. [Topic]
8. [Topic]
9. [Topic]
10. [Topic]

NARRATIVE TEXT IDEAS
11. [Topic]
12. [Topic]
13. [Topic]
14. [Topic]
15. [Topic]
```

### Maths Topics
Generate **5 maths homework focus suggestions** based on the Maths unit.

Before suggesting topics, query the curriculum:
```bash
python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area mathematics --year_level 5 --format text
python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area mathematics --year_level 3 --format text
```

Present the 5 suggestions as:
```
MATHS FOCUS IDEAS
A. [Focus — mapped to AC v9 descriptor code]
B. [Focus — mapped to AC v9 descriptor code]
C. [Focus — mapped to AC v9 descriptor code]
D. [Focus — mapped to AC v9 descriptor code]
E. [Focus — mapped to AC v9 descriptor code]
```

**Wait for the user to select one reading topic (by number) and one maths topic (by letter) before proceeding.**

---

## Step 2: Reading Text Generation

Write the chosen topic as three distinct texts. The core content and theme must be identical across all three; only the complexity changes.

| Group  | Target Age | Word Count  | Avg Sentence Length | Vocabulary              |
|--------|-----------|-------------|---------------------|-------------------------|
| Red    | 12–13 yrs | 350–450 wds | 18–25 words         | Subject-specific terms  |
| Blue   | 10–11 yrs | 250–350 wds | 12–18 words         | Moderate complexity     |
| Green  | 8–9 yrs   | 150–250 wds | 8–12 words          | Simple, decodable words |

### Validation Protocol (using `text-analysis` skill)

After writing each text:

1. Save the plain text to a temporary file: `Homework/Week_[N]/tmp_Red.txt` (or `tmp_Blue.txt`, `tmp_Green.txt`)
2. Run the readability check:
   ```bash
   python .agent/skills/text-analysis/scripts/analyse_text.py Homework/Week_[N]/tmp_Red.txt --level Red
   ```
3. If `Overall Result: FAIL`, revise the text using the script's suggestions and re-run.
4. Repeat until all three texts pass their respective level checks.
5. Delete the temporary `.txt` files.
6. Create each reading text as a DOCX using the `docx` skill.

**DOCX Format for reading texts:**
- Title: "Week [N] Homework — [Text Type]" (bold, 16pt)
- Subtitle: student's reading group is NOT labelled on the student document
- Body text: standard paragraph formatting, 12pt, 1.15 line spacing

---

## Step 3: Comprehension Question Generation

Generate **three separate sets** of 15 comprehension questions, one for each reading group. Every question in a set must be answerable solely from the text at that level — do not draw on information that appears only in a higher-level version of the text.

| Set   | Paired text                       | Question style |
|-------|----------------------------------|----------------|
| Red   | Week_[N]_Reading_Red.docx        | Inference-heavy; students must read between the lines |
| Blue  | Week_[N]_Reading_Blue.docx       | Mix of literal and inferential; accessible for 10–11 yr olds |
| Green | Week_[N]_Reading_Green.docx      | Literal comprehension; simple question language |

**Critical rule:** Before writing a question, verify that its answer can be found in or logically inferred from the specific text level it is paired with. If a concept appears in Red but not in Green (e.g., "the Coriolis effect", "wind shear"), it must not appear in the Green question set.

All questions must be multiple choice with exactly four options (A, B, C, D).

Do not compile into DOCX yet — hold these for Step 5.

---

## Step 4: Maths Question Generation

Generate two differentiated sets of maths questions based on the chosen maths topic.

**Before writing questions**, confirm the relevant content descriptors:
```bash
python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area mathematics --year_level 5 --format text
python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area mathematics --year_level 3 --format text
```

| Set      | Curriculum Level  | Question Count | Question Type                      |
|----------|-------------------|----------------|------------------------------------|
| Year 5   | Y5 descriptors    | 15 questions   | Conceptually demanding, multi-step |
| Year 3/4 | Y3–4 descriptors  | 15 questions   | Foundational, single-step          |

All questions must be multiple choice with exactly four options (A, B, C, D).

Flag any question that requires a diagram with: `[DIAGRAM REQUIRED: brief description]`

Do not compile into DOCX yet — hold these for Step 5.

---

## Step 5: Compile Questions Documents

Compile three DOCX files using the `microsoft-forms-assessment` and `docx` skills — one per reading group.

**Week_[N]_Questions_Red.docx**
- Questions 1–15: Red comprehension questions (based on Red reading text)
- Questions 16–30: Year 5 maths questions
- Numbered continuously from 1 to 30

**Week_[N]_Questions_Blue.docx**
- Questions 1–15: Blue comprehension questions (based on Blue reading text)
- Questions 16–30: Year 5 maths questions
- Numbered continuously from 1 to 30

**Week_[N]_Questions_Green.docx**
- Questions 1–15: Green comprehension questions (based on Green reading text only)
- Questions 16–30: Year 3/4 maths questions
- Numbered continuously from 1 to 30

**Strict formatting for all files (Microsoft Forms import format):**
```
1. Question text here?
A. Option one
B. Option two
C. Option three
D. Option four
ANSWER: B
POINT: 1
```

Where a diagram is required, insert a text placeholder instead of an image:
```
[SEE IMAGE: q17_rectangle_area.png]
```

---

## Step 6: Diagram Generation (if required)

After compiling the question documents, check for any `[DIAGRAM REQUIRED]` flags.

For each flagged question:
1. Generate the diagram using the `generate_image` tool.
2. Save the image to `Homework/Week_[N]/images/` with a descriptive name matching the placeholder (e.g., `q17_rectangle_area.png`).
3. At the end of the session, list all generated images so the user knows which ones to insert manually into Microsoft Forms.

**Images are never embedded in the DOCX files.**

---

## Step 7: Print File Generation

After all content is generated and verified, execute the `homework-print` skill to generate the three two-page student printable files (`Week_[N]_Print_Red.docx`, `Week_[N]_Print_Blue.docx`, `Week_[N]_Print_Green.docx`). Follow the `homework-print` skill instructions exactly, which involves using a Node.js script to create the clean, formatted two-page layouts without answers.

---

## Session End Checklist

Before closing the session, confirm:

- [ ] Three reading DOCX files created and validated (Red, Blue, Green)
- [ ] Three questions DOCX files created in correct Microsoft Forms format (Red, Blue, Green)
- [ ] Three print DOCX files generated and verified (Red, Blue, Green) via homework-print skill
- [ ] All comprehension questions verified as answerable from their paired reading text
- [ ] Red and Blue questions documents use Year 5 maths
- [ ] Green questions document uses Year 3/4 maths
- [ ] All `ANSWER:` lines use the exact format `ANSWER: [X]` (capital ANSWER, colon, space, letter) followed immediately by `POINT: 1`
- [ ] Questions numbered continuously (1–30) within each document
- [ ] Any required diagram images generated and listed for the user
- [ ] Temporary `.txt` validation files deleted
- [ ] All files saved to `Homework/Week_[N]/`

---

## Example Triggers

- "Create this week's homework."
- "Let's make Week 7 homework."
- "I need homework for this week based on our natural disasters unit."
