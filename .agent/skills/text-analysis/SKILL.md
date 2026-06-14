---
name: text-analysis
description: Analyses the readability of any text using the textstat Python library. Calculates Flesch Reading Ease, Flesch-Kincaid Grade Level, SMOG, ARI, Coleman-Liau, and Gunning Fog scores. Validates whether a text is appropriate for a specific reading level (L1: 12-13 yrs, L2: 10-11 yrs, L3: 8-9 yrs). Use whenever you need to verify or calibrate the reading level of student-facing texts, including homework reading passages, lesson handouts, and unit materials.
---

# Text Analysis Skill

Validates and reports on the readability of text using established linguistic metrics. This skill is a shared dependency — it is used by `homework-creator` and any other skill that generates student-facing texts at differentiated reading levels.

## Setup

Install the required dependency once per environment:

```bash
pip install textstat
```

## Reading Level Targets

| Level | Age        | F-K Grade Range | Flesch Reading Ease Range |
|-------|------------|-----------------|---------------------------|
| L1    | 12–13 yrs  | 6.5 – 8.5       | 55 – 72                   |
| L2    | 10–11 yrs  | 4.5 – 6.5       | 68 – 82                   |
| L3    | 8–9 yrs    | 2.5 – 4.5       | 78 – 92                   |

## Usage

```bash
# Analyse a file and print a full report
python .agent/skills/text-analysis/scripts/analyse_text.py path/to/text.txt

# Validate against a specific reading level
python .agent/skills/text-analysis/scripts/analyse_text.py path/to/text.txt --level L1

# Output raw JSON (useful for programmatic checks)
python .agent/skills/text-analysis/scripts/analyse_text.py path/to/text.txt --level L2 --json

# Pipe text directly
echo "Some student text." | python .agent/skills/text-analysis/scripts/analyse_text.py --level L3
```

## Workflow: Validating a Generated Text

1. Write the generated plain text to a temporary `.txt` file in the current task's output folder.
2. Run the script with the appropriate `--level` flag.
3. If `Overall Result: PASS` — proceed to DOCX creation.
4. If `Overall Result: FAIL` — read the suggestion output, revise the text, and re-run.
5. Repeat until the text passes, then delete the temporary `.txt` file.

## Key Metrics

| Metric                | What it measures                                             |
|-----------------------|--------------------------------------------------------------|
| Flesch Reading Ease   | 0–100; higher = easier. Standard text is around 60–70.      |
| Flesch-Kincaid Grade  | US school grade level equivalent.                            |
| SMOG Index            | Polysyllabic word density; reliable for educational texts.   |
| ARI                   | Character-based; accurate for shorter texts.                 |
| Coleman-Liau          | Character and sentence based; stable across text lengths.    |
| Gunning Fog           | Measures complex word usage; good for plain-English checks.  |

## Notes

- Run analysis on plain text, not on DOCX content.
- Minimum 100 words is recommended for reliable scores. Below 30 sentences, SMOG is unreliable — rely on F-K Grade and ARI instead.
- The L1 and L2 Flesch ranges overlap slightly by design; both are valid for mainstream upper-primary readers.
