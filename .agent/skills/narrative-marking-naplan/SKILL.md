---
name: narrative-marking-naplan
description: Comprehensive NAPLAN narrative writing assessment tool. Analyzes narrative texts against 10 criteria (Audience, Text Structure, Ideas, Character/Setting, Vocabulary, Cohesion, Paragraphing, Sentence Structure, Punctuation, Spelling) and provides detailed feedback with scores (0-47 total), specific quotes, strengths, weaknesses, and targeted recommendations. Use when the user needs to grade, assess, evaluate, or provide feedback on narrative writing according to Australian NAPLAN standards.
allowed-tools: Read, Write
---

# NAPLAN Narrative Marking

> Systematic assessment of narrative writing using official NAPLAN criteria.

This skill provides comprehensive analysis of narrative texts according to the National Assessment Program – Literacy and Numeracy (NAPLAN) marking guide. It evaluates 10 distinct criteria and produces detailed, evidence-based feedback.

---

## Quick Start

When the user provides a narrative text for assessment:

1. **Confirm the task** - Verify you understand they want NAPLAN-based narrative assessment
2. **Follow the step-by-step workflow** (see below)
3. **Generate comprehensive report** with all required components

---

## Assessment Workflow

Follow this systematic, step-by-step approach:

### Step 1: Initial Reading & Overview

**Action:** Read the narrative text carefully and note:
- Length (word count estimate)
- Overall impression
- Obvious strengths/weaknesses

**Output to user:** Brief acknowledgment that assessment is beginning.

---

### Step 2: Structure Assessment (Criteria 1-3)

Analyze the foundational narrative elements in this order:

#### 2A. Text Structure (0-4 points)
**Focus:** Organisation of narrative features (orientation, complication, resolution)

**Read reference:** `references/02-text-structure.md`

**Assess:**
- Is there a clear beginning (orientation)?
- Is there a complication that drives the story?
- Is there a resolution?
- Are plot devices used effectively?

**Record:**
- Score (0-4)
- Specific quotes showing structure elements
- Feedback explaining the score

---

#### 2B. Audience (0-6 points)
**Focus:** Writer's capacity to orient, engage and affect the reader

**Read reference:** `references/01-audience.md`

**Assess:**
- Does the text orient the reader?
- Are narrative devices used to engage?
- Does language choice affect the reader?

**Record:**
- Score (0-6)
- Quotes demonstrating engagement techniques
- Feedback on audience awareness

---

#### 2C. Ideas (0-5 points)
**Focus:** Creation, selection and crafting of ideas

**Read reference:** `references/03-ideas.md`

**Assess:**
- Are ideas elaborated or predictable?
- Is there a central storyline?
- Is there an underlying theme?

**Record:**
- Score (0-5)
- Quotes showing idea development
- Feedback on idea quality

---

### Step 3: Content Assessment (Criterion 4)

#### 3A. Character and Setting (0-4 points)
**Focus:** Character portrayal AND/OR setting development

**Read reference:** `references/04-character-setting.md`

**Important:** Stories may focus on character OR setting - both are not required for high scores.

**Assess:**
- How are characters developed? (actions, speech, thoughts, descriptions)
- How is setting established? (place, time, atmosphere)
- Is there effective characterisation or atmosphere?

**Record:**
- Score (0-4)
- Quotes showing character/setting development
- Feedback on which aspect is stronger

---

### Step 4: Language Assessment (Criteria 5-6)

#### 4A. Vocabulary (0-5 points)
**Focus:** Range and precision of language choices

**Read reference:** `references/05-vocabulary.md`

**Assess:**
- Are words mostly simple or precise?
- Is figurative language used effectively?
- Does vocabulary enhance meaning/mood?

**Look for:**
- Precise verbs, adjectives, adverbs
- Similes, metaphors, personification
- Technical, formal, or colloquial language appropriate to context

**Record:**
- Score (0-5)
- Multiple quotes showing vocabulary range
- Feedback on language sophistication

---

#### 4B. Cohesion (0-4 points)
**Focus:** Control of text flow through referring words, substitutions, connectives

**Read reference:** `references/06-cohesion.md`

**Assess:**
- Are sentences linked correctly?
- Are referring words (pronouns) accurate?
- What connectives are used? (then, meanwhile, although, because, etc.)
- Is there word association to avoid repetition?

**Record:**
- Score (0-4)
- Quotes showing effective (or missing) connections
- Feedback on text flow

---

### Step 5: Presentation Assessment (Criteria 7-10)

#### 5A. Paragraphing (0-2 points)
**Focus:** Segmenting text into paragraphs

**Read reference:** `references/07-paragraphing.md`

**Assess:**
- Is paragraphing present?
- Are paragraphs focused on single ideas?
- Do paragraphs enhance narrative pacing?

**Note:** Paragraphs can be indicated by indentation, spacing, or student annotations.

**Record:**
- Score (0-2)
- Description of paragraphing strategy
- Feedback on effectiveness

---

#### 5B. Sentence Structure (0-6 points)
**Focus:** Grammatically correct, structurally sound sentences

**Read reference:** `references/08-sentence-structure.md`

**Assess:**
- Are simple sentences correct?
- Are compound/complex sentences correct?
- Is there variety in sentence structure?

**Important:**
- Read intended sentences even if punctuation is poor
- Run-on sentences with repeated 'and'/'so' are NOT successful
- Verb control and preposition errors are sentence errors

**Record:**
- Score (0-6)
- Quotes showing sentence variety (or lack thereof)
- Feedback on grammatical control

---

#### 5C. Punctuation (0-5 points)
**Focus:** Correct and appropriate punctuation

**Read reference:** `references/09-punctuation.md`

**Assess:**
- Sentence punctuation (capitals, full stops, question marks)
- Noun capitalisation (names, places, titles)
- Other punctuation (apostrophes, commas, quotation marks, etc.)

**Critical rule:** Splice commas joining two sentences are INCORRECT.
Example: "The dog ate my homework, it was hungry." ❌

**Record:**
- Score (0-5)
- Description of punctuation accuracy
- Feedback on punctuation control

---

#### 5D. Spelling (0-6 points)
**Focus:** Accuracy of spelling and difficulty of words used

**Read reference:** `references/10-spelling.md`

**Assess:**
- Simple words (bad, shop, will, school)
- Common words (middle, jumped, wrong, between)
- Difficult words (chocolate, invisible, community)
- Challenging words (responsibility, physically, guarantee)

**Important:** 
- Count at least 10 difficult words for scores 5-6
- For score 6, allow 1-2 minor errors (first draft consideration)

**Record:**
- Score (0-6)
- Count of difficult/challenging words spelled correctly
- List of spelling errors (if significant)

---

### Step 6: Synthesis & Overall Assessment

**Action:** Review all criterion scores and identify patterns.

**Compile:**

1. **Overall Strengths (3-5 items)**
   - What does the writer do well?
   - Look across all criteria for standout elements
   - Be specific, not generic

2. **Overall Weaknesses (3-5 items)**
   - What needs most improvement?
   - Focus on actionable areas
   - Prioritize high-impact improvements

3. **Total Score**
   - Sum all criterion scores
   - Maximum possible: 47 points
   - Calculate percentage if helpful

---

### Step 7: Generate Comprehensive Report

**Use the report template:** `assets/report-template.md`

**Report must include:**

1. **Executive Summary**
   - Total score (X/47)
   - Overall strengths (3-5 bullet points)
   - Areas for development (3-5 bullet points)

2. **Detailed Assessment by Criterion** (all 10 criteria)
   For each criterion:
   - Score (X/max)
   - Assessment paragraph explaining the score
   - Evidence from text (2-4 specific quotes)
   - Recommendations (2-4 actionable items)

3. **Score Summary Table**
   - All 10 criteria with scores
   - Total score

4. **Original Narrative Text**
   - Include the full text in a code block for reference

**Formatting requirements:**
- Use clear headings and structure
- Quote actual text, don't paraphrase
- Make recommendations specific and actionable
- Ensure feedback is constructive and encouraging

**Optional:** Use `scripts/generate_report.py` to format the report programmatically if needed.

---

## Quality Standards

### Scoring Accuracy
- Each score must align with the category descriptor in the reference
- Justify scores with specific evidence from the text
- Be consistent across criteria (e.g., sophisticated vocabulary should align with high audience score)

### Evidence Quality
- Quote exactly from the text
- Select quotes that clearly demonstrate the point
- Include both positive examples and areas needing work

### Feedback Quality
- Be specific, not generic ("Uses varied sentence structure" ✅ not "Good writing" ❌)
- Be constructive and encouraging
- Focus on what the writer is doing and what to improve
- Use professional language appropriate for educational assessment

### Recommendations Quality
- Make recommendations actionable and specific
- Link recommendations to evidence
- Prioritize high-impact improvements
- Provide examples where helpful

---

## Important Notes

### Assessment Philosophy
- **Digital text only** - No OCR or handwriting interpretation required
- **First draft consideration** - Minor typos allowed at higher scores
- **Context matters** - Read complications, character development, etc. in context
- **AND/OR flexibility** - Character and Setting can be strong in one area only

### Common Pitfalls to Avoid
1. **Don't penalize age-appropriateness** - Year 3 vs Year 9 expectations differ
2. **Don't require both character AND setting** - Either can carry the score
3. **Don't count splice commas as correct** - They are punctuation errors
4. **Don't ignore intended sentences** - Read past poor punctuation to assess structure
5. **Don't inflate scores** - Be rigorous but fair

### When Multiple Interpretations Exist
- Choose the interpretation most favorable to the student
- Note ambiguity in feedback
- Explain your reasoning

---

## Reference Files

Load these as needed during assessment:

- `references/01-audience.md` - Audience criterion (0-6)
- `references/02-text-structure.md` - Text structure criterion (0-4)
- `references/03-ideas.md` - Ideas criterion (0-5)
- `references/04-character-setting.md` - Character and setting criterion (0-4)
- `references/05-vocabulary.md` - Vocabulary criterion (0-5)
- `references/06-cohesion.md` - Cohesion criterion (0-4)
- `references/07-paragraphing.md` - Paragraphing criterion (0-2)
- `references/08-sentence-structure.md` - Sentence structure criterion (0-6)
- `references/09-punctuation.md` - Punctuation criterion (0-5)
- `references/10-spelling.md` - Spelling criterion (0-6)

---

## Example Usage

**User:** "Can you grade this narrative according to NAPLAN standards? [provides text]"

**Your workflow:**
1. Acknowledge the task
2. Read the narrative carefully
3. Follow Steps 1-7 systematically
4. Read each reference file as you assess that criterion
5. Generate the comprehensive report with all components
6. Present the report to the user

**Key principle:** Be thorough, evidence-based, and constructive. The goal is to provide valuable feedback that helps writers improve.
