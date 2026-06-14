---
name: lesson-creator
description: Manages the creation of high-quality, high-engagement lesson materials including lesson plans, handout (DOCX), interactive presentation (HTML), optional PowerPoint presentation (PPTX), and Microsoft Forms assessments. Use this skill when a user wants to build a new instructional unit or individual lesson for any subject (e.g. English, Maths, Science), especially those requiring a consistent visual and structural format.
---

# Lesson Creator Skill

This skill provides a structured workflow for generating a comprehensive set of instructional materials for lessons in any subject.

## Core Materials

A complete "Lesson Pack" consists of four primary components:

1.  **Lesson Plan (Markdown)**: The pedagogical foundation.
2.  **Student Handout (DOCX)**: Reusable worksheet for students.
3.  **Lesson Presentation (HTML)**: A standalone, standardised interactive presentation (`Lesson_X.Y_Presentation.html`) featuring an embedded classroom whiteboard, drawing pen, highlighter, dynamic teacher notes panel, and image lightbox.
4.  **Lesson Presentation (PPTX - Optional)**: A static PowerPoint presentation (`Lesson_X.Y_Presentation.pptx`) created ONLY if explicitly requested, containing the same content layers without interactive tools.
5.  **Microsoft Forms Assessment (DOCX)**: Import-ready quiz for data collection.

## Workflow

Follow these steps to generate a lesson:

### 1. Planning & Analysis

Identify the learning intention and core activities. 

- **Resource Discovery (MANDATORY)**: Check the `Resources/` folder for a `Manifest.md` or `Inventory.md`.
    - If no manifest exists, run `ls -R Resources/` to see available files.
    - If the `Resources/` folder or manifest is missing, suggest their creation following the [UNIT_STRUCTURE.md](references/UNIT_STRUCTURE.md) standard.
    - Summarize available assets for the user (e.g., "Found 5 PDFs, 2 Websites").
    - Attempt to match discovered resources to the specific lesson activities.
- **Reference Check**: Consult the [lesson_patterns.md](references/lesson_patterns.md) reference for visual and structural standards.

### 2. Interactive Design Thinking Phase

Before generating slide content, you must explicitly reason about the pedagogical purpose of any digital interaction. Interactivity must never be added solely for "engagement"; it must actively surface student thinking, check for understanding, or scaffold cognitive processing.

#### Step A: The Contemplation Phase (Think Aloud)
Before completing the matrix, write a brief "Pedagogical Contemplation" block. You must reason through:
1.  **Cognitive Goal**: What cognitive skill are students practicing at this exact moment? (e.g., recalling vocabulary, categorising parts of speech, evaluating a writer's choice, synthesising arguments).
2.  **Interactive Alignment**: Why is this specific interactive mode the absolute best fit for this cognitive task? How does it help students visualise or manipulate the concept?
3.  **Surfacing Student Thinking**: How does this interaction show the teacher what the student is thinking? (e.g., *"The Two-Column Sort forces students to commit to a category, showing the teacher if they can distinguish between subordinating and coordinating conjunctions, rather than just guessing"*).
4.  **Pedagogical vs. Engagement Goal**: What is the pedagogical reason for this slide (e.g., formative check of clause types) versus the engagement design (e.g., dragging colourful cards)?

#### Step B: Pedagogical Type-to-Mode Mapping Standards
To ensure rigorous cognitive alignment, always map student tasks to digital modes using these pedagogical standards:

| Student Cognitive Task | Pedagogical Action | Best Digital Interactive Mode |
| :--- | :--- | :--- |
| **Categorising or Comparing** | Sorting items into distinct bins | **Two-Column Sort** (or multi-column grid) |
| **Ordering Steps or Chronology** | Placing narrative events or structural elements in sequence | **Sequencing** (Reorder List) |
| **Mapping Terms to Definitions** | Connecting vocabulary or structural features to meanings | **Matching** (Match Pairs) |
| **Recalling Specific Vocabulary** | Restoring missing words in sentences or key grammar rules | **Cloze** (Fill-in-the-Blank) |
| **Locating Information in a Text** | Highlighting evidence, finding figurative language in-context | **Hotspot/Highlight** (or targeted Cloze selection) |
| **Evaluating or Ranking** | Judging the quality of a paragraph or ordering arguments by strength | **Rank Order / Scale** |
| **Connecting Ideas or Concepts** | Visualising relationships between characters, causes, or themes | **Concept Mapping / Drag-Connect** |

#### Step C: Checks for Understanding (CFU) Standard
At each major concept transition or before moving from guided to independent practice, you **MUST** include a dedicated **Check for Understanding (CFU)** slide or moment.
- **Physical-Digital Whiteboard Protocol**: If a CFU's answer can easily be written on a mini-whiteboard, place a highly visible `.cfu-badge` or CFU note on the slide. This prompts the teacher to conduct a physical whiteboard check (having all students write and hold up their answers) before using the digital controls (clicking "Show Answer") to reveal and lock the correct answer on the smartboard. This provides the teacher with the flexibility of both modalities in all situations.
- **Goal**: Instantly assess if students have met the immediate sub-goal before introducing new cognitive load.

#### Step D: Interactive Design Thinking Matrix
Only after completing the Contemplation Phase should you construct the matrix in the lesson plan. You must include the **Cognitive Demand** column to enforce alignment:

| Core Concept / Learning Moment | Cognitive Demand | Best Interactive Mode | Pedagogical Rationale (Why & How it surfaces thinking) | Scaffolding Hint (Tier 2) | Placement in Lesson |
| :--- | :--- | :--- | :--- | :--- | :--- |
| *e.g., Simple vs. Complex clauses* | Analytical sorting & distinction | Two-Column Sort | Forces students to classify clauses based on conjunctions, exposing common misconceptions about coordinating vs. subordinating connectors. | *“Hint: Remember, a complex clause contains a subordinating conjunction like 'because'.”* | Guided Practice (Pre-CFU) |
| *e.g., Vocabulary Recall (Clause markers)* | Knowledge retrieval & recall | Cloze (Fill-in-the-Blank) | Evaluates whether students can retrieve coordinating conjunctions from memory and place them in semantic context. | *“Hint: Think about which conjunction joins two independent ideas of equal importance (FANBOYS).”* | Warm-up / Review |

#### Step E: Compiling Option B Interactive Slides
When compiling slides, generate unique, bespoke HTML/JS scripts directly inside the slide block. Always follow the premium styling guidelines in [lesson_patterns.md](references/lesson_patterns.md) and implement the **Two-Tier Feedback and Teacher Notes Drawer Override** standard:

1.  **Two-Column Sort (Tap-to-Select)**:
    *   **HTML**: Elements with `.sort-card` placed in the `.sort-deck`. Target `.sort-zone` containers have an `id` matching their category. Includes a `.hint-box`, `.interactive-feedback` container, and an optional `.cfu-badge` overlay.
    *   **JS**: Clicking a `.sort-card` adds `.selected`. Clicking a `.sort-zone` moves the selected card there. A "Check Answer" or instant validator runs. On a first wrong placement, trigger `.shake-error` (Tier 1). On the second wrong placement, display `.hint-box` (Tier 2). Register a `'show-answer'` listener on the slide element that instantly places all cards in their correct zones and applies `.correct-placed` classes.

2.  **Sequencing (Reorder List)**:
    *   **HTML**: A `.seq-container` holding list items styled as `.seq-strip` with numeric markers `.seq-number`, texts `.seq-text`, and swap controls `.seq-btn`. Includes a submit button, `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Clicking a `.seq-strip` highlights it. Clicking the up/down buttons swaps it with adjacent nodes. Clicking submit checks the order. Tier 1: shake incorrect strips. Tier 2: show `.hint-box` and highlight the first misplaced item. Register a `'show-answer'` listener to sort strips instantly into correct indices.

3.  **Matching (Match Pairs)**:
    *   **HTML**: Left-column items and right-column items inside `.match-cols-grid`. Items styled as `.match-card` with data attributes (e.g., `data-match="1"`). Includes `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Click left card (adds `.selected`), click right card. If they match, apply `.matched`. If wrong, Tier 1: shake and clear selection. Tier 2: display `.hint-box` and clear selection. Register `'show-answer'` to pair all items instantly.

4.  **Cloze (Fill-in-the-Blank)**:
    *   **HTML**: A `.cloze-container` holding text containing inline `.cloze-blank` span wrappers. An optional `.cloze-options-pool` at the bottom containing `.cloze-option` cards. Includes `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Clicking a blank selects it. Clicking a card from the pool places it in the active blank. Checking answers: Tier 1: shake incorrect blanks. Tier 2: show `.hint-box`. Register `'show-answer'` to fill blanks with correct values and lock them.

5.  **Hotspot/Highlight (Find and Tag)**:
    *   **HTML**: A `.highlight-container` framing text with individual words/phrases wrapped in `.highlight-word` (having data attributes like `data-correct="true"`). Includes `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Clicking a `.highlight-word` toggles `.highlighted`. Checking answers: Tier 1: shake and unhighlight incorrect selections. Tier 2: show `.hint-box` and highlight remaining correct targets. Register `'show-answer'` to instantly toggle all correct words to `.correct` and lock them.

6.  **Rank Order / Scale (Evaluative Ordering)**:
    *   **HTML**: A `.rank-container` holding cards styled as `.rank-item` with swap buttons or index fields, `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Controls allow users to swap or re-index items to rank them according to criteria. Submitting checks the ranking. Tier 1: shake incorrect items. Tier 2: display `.hint-box` and highlight the first out-of-order item. Register `'show-answer'` to sort all items instantly into the correct pedagogical order.

7.  **Concept Mapping / Drag-Connect (Visual Synthesis)**:
    *   **HTML**: A `.map-container` containing draggable node blocks `.concept-node` and connection indicators or SVG lines. Includes `.hint-box`, `.interactive-feedback` container, and optional `.cfu-badge` overlay.
    *   **JS**: Allows selecting two nodes and drawing a connection between them or placing nodes in correct relation to each other. Submitting validates connections. Tier 1: shake wrong nodes and break incorrect connections. Tier 2: show `.hint-box` and draw the first correct line. Register `'show-answer'` to draw all correct connection lines instantly and place all nodes in their optimized coordinates.


### 3. Lesson Plan Generation

Draft the lesson plan in Markdown following the structure in the patterns guide. Ensure it:
1.  **Starts with a mandatory `### Pedagogical Contemplation` block** outlining the 4 cognitive reasoning points from Step A.
2.  **Includes differentiation** for support and extension.
3.  **References the specific interactive activities** mapped in the Interactive Design Thinking Matrix (Step D), demonstrating tight alignment between cognitive demands and digital interactions.


### 4. Resource Generation (Scripts)

Use the [create_lesson_resources.js](scripts/create_lesson_resources.js) template as a foundation for your Node.js scripts.

> [!CAUTION]
> **P0 Presentation Compiler Integrity Mandate (CRITICAL)**:
> *   It is **STRICTLY FORBIDDEN** to generate `Lesson_X.Y_Presentation.html` by concatenating custom HTML page templates from scratch. You **MUST** load the standard wrapper template file [presentation_template.html](assets/presentation_template.html) and replace the placeholder `<!-- SLIDES GO HERE DURING DYNAMIC COMPILATION -->`.
> *   Do **NOT** write custom slideshow navigation, whiteboard canvas overlays, or floating toolbars from scratch. The standard wrapper contains all of these visual systems (Drawing Canvas, Pen, Highlighter, Whiteboard, Lightbox, Slide dots, Teacher notes sidebar). Replacing the wrapper with a custom HTML structure breaks classroom navigation, drawing tools, and smartboard compatibility.

- **Handout**: Use the `docx-js` library logic to build tables and sections.
- **Presentation**:
  - **Interactive HTML Slide Deck (Default)**: Generate a single unified `Lesson_X.Y_Presentation.html` file by injecting slide content arrays into the [presentation_template.html](assets/presentation_template.html) wrapper. Ensure teacher notes are embedded in `<div class="teacher-notes">` inside each slide, and all images are styled to support the lightbox. For interactive slides, compile unique Option B Vanilla JS scripts directly inside the slide block to handle tap-to-select interactions, custom two-tier feedback logic, and the `'show-answer'` Teacher Notes drawer listener.
  - **Static PowerPoint Fallback (Optional)**: If the user explicitly requests a PowerPoint, ALSO generate individual static HTML slides under a `Lesson_X.Y_Slides/` folder based on the [slide_template.html](assets/slide_template.html) asset (one file = one slide), and convert them to a static `.pptx` file using `html2pptx`. Do not attempt to add interactive tools (whiteboard, pens, sidebar) to the static PowerPoint.
  - **Crucial**: Keep content 0.5" from edges to prevent import errors.
- **Assessment**: Follow the strict `ANS: X` format for Microsoft Forms import.

### 5. Verification

Execute the scripts and verify the output files exist and match the high-engagement standards.

> [!IMPORTANT]
> **Mandatory Compiler Quality Gate Checklist**:
> You **MUST** open and audit the compiled `Lesson_X.Y_Presentation.html` file before completing the task. Verify that all of the following core wrapper IDs and components are present and unaltered:
> 1.  **Slide Container**: `<div class="presentation-container" id="presentationContainer">` (Check that generated slides are appended inside).
> 2.  **Drawing Toolbar**: `<nav class="presentation-toolbar" id="masterToolbar">` (Includes pen, highlighter, cursor).
> 3.  **Whiteboard Overlay**: `<div id="whiteboardOverlay">` and `<canvas id="whiteboardCanvas">`.
> 4.  **Teacher Notes drawer & Override button**: `<div id="teacherNotesPanel"` and `<button class="whiteboard-btn" id="teacherShowAnswerBtn"`.
> 5.  **Interactive Image Lightbox**: `<div id="imageLightbox"` and `<canvas id="lightboxCanvas"`.
> If any of these wrapper elements are missing, the slide presentation is corrupted and must be re-compiled using the correct wrapper asset.

## Reference Materials

- **[lesson_patterns.md](references/lesson_patterns.md)**: Visual identity and formatting rules.
- **[UNIT_STRUCTURE.md](references/UNIT_STRUCTURE.md)**: Standard unit architecture and file organization.
- **[create_lesson_resources.js](scripts/create_lesson_resources.js)**: Reusable Node.js boilerplate supporting both HTML slides compile and optional PPTX output.
- **[presentation_template.html](assets/presentation_template.html)**: Interactive standardised HTML presentation wrapper template (contains whiteboard, drawing overlay, notes sidebar, and lightbox).
- **[slide_template.html](assets/slide_template.html)**: Legacy/Static single HTML slide boilerplate for optional PPTX conversion.

## Mandatory File Structure (Per Lesson)

To maintain organization, every lesson MUST have its own dedicated folder within `Lesson_Plans/`. 

Example for **Week 3, Lesson 2**:
```text
Lesson_Plans/
└── Lesson_3.2/
    ├── scripts/
    │   └── build_lesson_3.2.js    # Node.js script to generate docs
    ├── Lesson_3.2_Plan.md         # The lesson plan
    ├── Lesson_3.2_Handout.docx    # The student handout
    ├── Lesson_3.2_Presentation.html # Standalone interactive classroom slides (Default)
    ├── Lesson_3.2_Presentation.pptx # PowerPoint presentation (Only if explicitly asked)
    └── Lesson_3.2_Slides/          # Individual slide HTML files for PPTX (Only if explicitly asked)
```

## Example Triggers

- "Create a lesson about metaphors for Year 8 students."
- "Build a lesson pack for Week 3 Lesson 2 of our HASS unit."
- "I need a handout and a PowerPoint for a lesson on character development."
