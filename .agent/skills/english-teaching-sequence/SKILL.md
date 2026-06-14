---
name: english-teaching-sequence
description: Specialized skill for generating comprehensive 10-week, 40-lesson structured English teaching sequences. Integrates novel/text studies, assessment requirements, Australian Curriculum v9 mapping, and targeted differentiation strategies.
---

# English Teaching Sequence Generator

This skill provides a structured workflow for generating a 10-week English teaching sequence based on the Australian Curriculum v9, integrating novel studies with assessment tasks.

## 🎯 When to use
Use this skill when the user requests a detailed teaching sequence, unit plan, or lesson-by-lesson breakdown for an English unit spanning several weeks (typically 10 weeks, 40 lessons).

## 📋 The Workflow

Follow these steps faithfully to ensure the sequence meets the project's premium and holistic education standards.

### Step 1: Input Gathering & Context
Before generating any plans, ensure you have the following context. If you don't, ask the user:
1.  **Year Level**: Which Year level is this for?
2.  **Core Text**: What is the primary novel or text being studied?
3.  **Assessment Data**: Do you have a Unit Plan or Assessment Task description? (If the user provides `.docx` files, use the `docx-to-markdown` skill to read them).
4.  **Differentiation Profiles**: Are there specific student needs to consider? (e.g., Reluctant readers, Specific ICPs like 'Lucas' who needs simplified sentences).
5.  **Resource Integrity (MANDATORY)**: Check the `Resources/` folder for a `Manifest.md` or `Inventory.md`.
    - Verify that all resources mentioned in the unit plan or sequence exist in the folder.
    - If no `Resources/` folder or manifest exists, suggest creating them according to the [Standard Unit Architecture](file:///c:/Users/dsuth/Documents/Joshua/.agent/skills/lesson-creator/references/UNIT_STRUCTURE.md).

### Step 2: Socratic Gate (Mandatory)
Before writing the sequence, present the user with a Socratic Gate to confirm:
- **Focus Balance**: Should the sequence be **Assessment-Led**, **Novel-Led**, or **Balanced**?
- **Differentiation Method**: Standard (Support/Core/Extend) or Targeted (e.g., Reluctant Readers + Specific ICP)?
- **Output Format**: Single Markdown file, Multi-file Markdown, or exported to Word (`.docx`)?

*Wait for user confirmation before proceeding.*

### Step 3: Curriculum Mapping
Use the `curriculum-master` skill to query the Australian Curriculum v9.
- Run `python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area english --year_level <YEAR> --format text`
- Map the relevant reading, writing, and language descriptors to the unit.

### Step 4: Sequence Structure Design
Divide the 10 weeks (40 lessons) into 5 distinct two-week blocks (Sequences 1 through 5).
- **Sequences 1-3 (Weeks 1-6)**: Usually deeply focused on reading, exploring narrative themes, character arcs, settings, and language features.
- **Sequence 4 (Weeks 7-8)**: Climax of reading, transition to drafting the assessment task (e.g., narrative adaptation, exposition).
- **Sequence 5 (Weeks 9-10)**: Editing, publishing, presenting, and final assessment marking.

### Step 5: Content Generation (Markdown Table)
Draft the 40 lessons into a Markdown table. The table MUST include these exact columns:
| Week | Sequence | Lesson | Learning Intention | Teaching and Learning Sequence | Reading | Differentiation | Resources |

**Content Guidelines:**
- **Differentiation**: Be highly targeted. For instance, if 'Lucas' is an ICP student, detail exactly what he does (e.g., "Write 1 simple sentence", "Label a picture"). For 'Reluctant Readers', give strategies (e.g., "Audiobook Chapter 3", "Verbal check-in").
- **Reading**: Explicitly map which chapters or pages are read in which lesson.
- **Pacing**: Make sure to balance explicit teaching (grammar/sentence structure) with engagement activities.

### Step 6: Review and Formatting
1.  Ensure all 40 rows are complete.
2.  Ensure Australian spelling is used throughout (e.g., *colour*, *organisation*).
3.  Ensure metric measurements are used if numbers appear.
4.  If the user requested a Word document, use Pandoc to convert the generated `.md` file to `.docx` (e.g., `pandoc input.md -o output.docx`). Check `docx` skill for pandoc usage if needed.

## 📝 Example Output Pattern
```markdown
| Week | Sequence | Lesson | Learning Intention | Teaching and Learning Sequence | Reading | Differentiation | Resources |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **1** | **1** | [Specific ACv9 informed target] | **Introduction:** ... <br>**Explore:** ... <br>**Connect:** ... | Chapter 1 | **Reluctant Readers:** ... <br>**Lucas:** ... | Novel, Notebook |
```
