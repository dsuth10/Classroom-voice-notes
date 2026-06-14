# Lesson Design Patterns

This document defines the visual, structural, and interactive standards for classroom lesson materials.

---

## 1. Visual Identity (Brand Guidelines)

To maintain consistency and high visual impact, all digital and print materials use a premium "Deep Navy and Vibrant Orange" theme.

| Element            | Hex Code  | Purpose                                    |
| :----------------- | :-------- | :----------------------------------------- |
| **Deep Navy**      | `#112d4e` | Backgrounds, heavy text, primary branding  |
| **Vibrant Orange** | `#f96d00` | Headings, highlights, interactive elements |
| **Off-White**      | `#f9f7f7` | Body backgrounds, secondary text           |
| **Soft Blue**      | `#3f72af` | Accents, boxes, emphasis                   |
| **Green Success**  | `#2e7d32` | Correct quiz selections, positive alerts   |
| **Red Error**      | `#c62828` | Incorrect quiz selections, warning states  |

---

## 2. Material Specifications

### A. Lesson Plan (Markdown)

- **File naming**: `Lesson_X.Y_Plan.md` (stored within `Lesson_Plans/Lesson_X.Y/` or standard unit path)
- **Structure**:
  1. Pedagogical Contemplation (Outline of Cognitive Goal, Interactive Alignment, Surfacing Student Thinking, and Pedagogical vs. Engagement goals)
  2. Learning Intention
  3. Success Criteria
  4. Introduction (Warm-up)
  5. Core Activities (3+ parts, including the Interactive Design Thinking Matrix and specific CFU checkpoints)
  6. Conclusion (Consolidation)
  7. Differentiation (Support/Extension)

### B. Student Handout (DOCX)

- **Library**: `docx-js`
- **Typography**: Arial or Inter (11pt/12pt body, 16pt+ headings)
- **Layout**:
  - Standard Australian-style metadata block (Name, Date, Class).
  - Clear sections (Part 1, Part 2, etc.) using shaded table headers.
  - Generous margins (2.54cm outer margins) and double-width tables (DXA units) for Google Docs compatibility.
  - Integration of lesson graphics (e.g., timeline PNGs) under each relevant word problem, leaving blank horizontal bands for manual student sketches.

### C. Interactive HTML Presentation (Default)

Interactive presentations are compiled as a single standalone HTML file (`Lesson_X.Y_Presentation.html`) containing the entire slide array injected into the `presentation_template.html` wrapper.

#### 1. Year 5 Spacing & Typography (10-Year-Old Baseline)
* **Whole-Class Sizing**: Slide body text defaults to **`26px`** and slide titles default to **`46px`** to ensure crystal-clear readability from the back of the classroom.
* **Padding & Layout Control**: Slide padding is set to **`40px 70px 80px`**. The deep `80px` bottom padding is mandatory to prevent content from being covered by the floating presenter toolbar.
* **Content Simplification Strategy**: Slides should avoid dense text or academic vocabulary. Complex background descriptions or verbose teaching instructions should be placed inside the hidden `<div class="teacher-notes">` drawer, which dynamically populates the sidebar notes panel.

#### 2. Universal Lightbox Canvas Drawing
All slide images are interactive. Clicking any image scales it into a fullscreen lightbox overlay (`z-index: 1000`) for closer inspection.
* **Synchronized Sketching**: An absolute overlay canvas (`#lightboxCanvas`) sits over the zoomed image, allowing teachers to annotate, circle, and highlight directly on the graphic using the presenter toolbar.
* **Precision Pointer Coordinate Calibration**: Because stretching a canvas via CSS creates coordinate offsets, the template programmatically resizes the canvas and maps mouse/touch events mathematically using ratios of the bounding client rect:
  $$\text{Scale Factor } X = \frac{\text{Canvas Pixel Width}}{\text{Rendered Client Width}}$$
  $$X_{\text{calibrated}} = (X_{\text{client}} - \text{Rect}_{\text{left}}) \times \text{Scale Factor } X$$
* **Session Skecth Caching**: Lightbox annotations are saved in-session via an image URL key cache (`lightboxDrawings = {}`), allowing drawings to be seamlessly restored if a teacher closes and reopens the same slide graphic.

#### 3. Interactive Quiz Component Classes
Master stylesheet templates incorporate dedicated Option A "press-the-button" quiz classes to provide immediate visual feedback:
* `.quiz-container` — Center-aligned, vertically flexible flexbox holding the question and answers.
* `.quiz-question-box` — Large `32px` font box with a distinct navy border and orange drop shadow.
* `.quiz-grid` — Two-column CSS grid (`gap: 24px`) displaying four choices side-by-side.
* `.quiz-option-btn` — Large `28px` buttons with bold Outfit typography, navy shadows, and custom hover states.
* `.quiz-option-btn.correct` / `.quiz-option-btn.incorrect` — Green and red success/error backgrounds that animate instantly upon click. Incorrect answers trigger a horizontal `.shake` micro-animation.
* `.quiz-explanation-box` — Sliding explanation drawer (`24px` text, animated via `.slideUp`) that details why a choice was correct or incorrect.

#### 4. Semantic CSS Layout Utilities
To maintain layout consistency without ad-hoc inline styles, the template stylesheet features built-in helper classes:
* `.intro-text` — Bold `28px` introductory lines used to frame slide activities.
* `.remember-box` — Styled rule container featuring a `6px` orange left border, light green background, and bold `24px` text for highlighting conversion rules or formulas.
* `.scenario-box` — Activity outline box with a `6px` orange left border and soft grey background for framing word problems.
* `.time-compare` & `.time-card` — Predefined card columns (e.g., `.time-card-12` in blue, `.time-card-24` in orange) to construct clean side-by-side comparison tables.

#### 5. Standardised Interactive Activity Classes
To build premium interactive slides that are fully responsive and touch-friendly, compile structures utilising these built-in classes:

*   **Universal Interactive Helpers**:
    *   `.hint-box` — Pedagogical hints drawer, hidden by default. Displays with a `0.3s` slide animation.
    *   `.interactive-feedback` — Dynamic text status container.
    *   `.interactive-submit-btn` — Premium action button with orange/navy offset shadow overlays.
    *   `.cfu-badge` — Floating, high-visibility orange badge overlay (contains text: "CFU - Whiteboard Option"). This indicates a Check for Understanding where the teacher should consider prompting physical whiteboard responses first before revealing the answer digitally.
*   **Two-Column Sort**:
    *   `.sort-container` — Layout flexbox centering the sorting elements.
    *   `.sort-deck` — Upper pool container for unsorted items with dashed navy borders.
    *   `.sort-card` — Clickable cards that translate and glow on selection (`.selected`).
    *   `.sort-zones-grid` & `.sort-zone` — Destination zones styled with distinct navy borders and orange glowing focus targets (`.active-target`).
*   **Sequencing**:
    *   `.seq-container` — Main vertical layout holder.
    *   `.seq-list` & `.seq-strip` — Sentence strips displaying numbers (`.seq-number`), clause texts (`.seq-text`), and swap controls (`.seq-btn`).
*   **Matching**:
    *   `.match-container` & `.match-cols-grid` — Multi-column grid containing left-side and right-side lists.
    *   `.match-card` — High-engagement card blocks that lock to green (`.matched`) on a correct pair.
*   **Cloze / Fill-in-the-Blank**:
    *   `.cloze-container` — Premium text container framing inline sentences.
    *   `.cloze-blank` — Inline boxes with orange dotted underlines, morphing into input dropdowns or cycling cards when clicked.
    *   `.cloze-options-pool` & `.cloze-option` — Bottom word choice bank.
*   **Hotspot / Highlight**:
    *   `.highlight-container` — Card border wrapper encasing interactive text sentences.
    *   `.highlight-word` — Tap-to-select word/phrase blocks that toggle state on selection (`.highlighted`) and transition to correct green (`.correct-highlight`) or incorrect red (`.incorrect`).
*   **Rank Order / Scale**:
    *   `.rank-container` — Rigid multi-card container.
    *   `.rank-item` — Individual rank rows containing numeric rankings, texts, and active swap triggers.
*   **Concept Mapping / Drag-Connect**:
    *   `.map-container` & `.map-canvas` — Canvas-like boundary box framing draggable nodes and connections.
    *   `.concept-node` — Draggable relative blocks glowing on select, connecting via dynamically drawn SVG lines.

##### Differentiated Scaffolding & Feedback Protocol
Every compiled interactive activity must adhere to this structured two-tier feedback standard:
*   **Tier 1 (First Mistake)**: Trigger a horizontal `.shake` animation on the selected element and set `.incorrect` styling. Display a simple "Try again!" status message. Do not show the detailed hint yet.
*   **Tier 2 (Second Mistake)**: If a student submits an incorrect configuration again, immediately display the slide's customised `.hint-box` featuring pedagogical hints and highlight the first incorrect item to guide their understanding.
*   **Teacher notes "Show Answer" Listener**: Every interactive slide's JS script must register an event listener for the custom `'show-answer'` event. When dispatched by the teacher's note drawer, the slide must transition all elements instantly into their correct, successfully validated visual state (`.correct`, `.correct-placed`, `.matched`, `.correct-seq`, `.correct-blank`, `.correct-highlight`, `.correct-rank`, `.correct-map`).

---

## 3. High-Engagement Strategies

* **Australian Context**: Incorporate local cultural references (slang, locations, landmarks) when relevant to the curriculum.
* **Australian Standards (P0 Mandatory)**:
  * **Spelling**: Always use Australian spelling (e.g., 'colour', 'organise', 'centre', 'modelling').
  * **Measurements**: Always use the metric system (e.g., kilograms, Celsius, meters, hours/minutes).
* **Graphic Organisers**: Prefer structured visual cards and grids over long lists of bullet points.
* **Socratic Questioning**: Include "Think about..." or "What if..." prompts in slide footers.
