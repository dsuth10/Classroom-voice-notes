---
name: microsoft-forms-assessment
description: Creates multiple-choice assessment documents in Word (.docx) format that are specifically structured for import into Microsoft Forms. Use this skill when a user wants to generate a quiz, test, or assessment that needs to follow the "Question, A, B, C, D Options, Correct Answer" format. This skill leverages the 'docx' skill for document creation.
---

# Microsoft Forms Assessment

This skill enables the creation of multiple-choice assessment documents optimized for Microsoft Forms import.

## Formatting Requirements

To ensure Microsoft Forms can correctly parse the document, follow these exact formatting rules:

### 1. Question Format
- Every question must start with a number followed by a period or closing parenthesis (e.g., "1." or "1)").
- The question text should be on the same line as the number or immediately follow it.

### 2. Multiple Choice Options
- Each question must have exactly four multiple-choice options.
- Options must be labelled **A**, **B**, **C**, and **D** followed by a period or closing parenthesis (e.g., "A." or "A)").
- Each option should be on its own line.

### 3. Correct Answer Notation
- Immediately following the last option (D), the correct answer must be specified.
- Use the exact format: `ANSWER: X` where `X` is the letter of the correct answer (A, B, C, or D).
- Immediately following the answer line, the point value must be specified.
- Use the exact format: `POINT: 1`
- **Note**: The colon and space in `ANSWER: ` and `POINT: ` are critical for the parser.

## Workflow

1. **Content Preparation**: Identify the questions, options, and correct answers.
2. **Document Creation**: Use the `docx` skill to create a new Word document.
3. **Drafting**: For each question, create a sequence of paragraphs:
   - Paragraph 1: Question (e.g., "1. What is the capital of Australia?")
   - Paragraph 2: Option A (e.g., "A. Sydney")
   - Paragraph 3: Option B (e.g., "B. Melbourne")
   - Paragraph 4: Option C (e.g., "C. Canberra")
   - Paragraph 5: Option D (e.g., "D. Brisbane")
   - Paragraph 6: Correct Answer (e.g., "ANSWER: C")
   - Paragraph 7: Point Value (e.g., "POINT: 1")
4. **Finalisation**: Save the document as a `.docx` file.

## Example

**Question 1**
1. What two basic states of matter are mentioned in the text?
A. Solids and gases
B. Liquids and plasmas
C. Solids and liquids
D. None of the above
ANSWER: C
POINT: 1

## Integration with Docx Skill

This skill depends on the `docx` skill for the actual document generation logic. When using this skill, you must also load the `docx` skill and follow its "Creating a new Word document" workflow using `docx-js`.

See [structure.md](references/structure.md) for detailed visual specifications.
