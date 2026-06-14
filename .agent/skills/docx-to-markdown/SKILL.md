---
name: docx-to-markdown
description: Converts C2C lesson .docx files to Markdown while preserving all content and mapping resource links to local files. Use this skill when converting Queensland C2C lesson plans, teaching sequences, or any Word document containing a structured lesson plan table.
---

# Docx To Markdown

## Overview

Converts Queensland C2C lesson plans from Word (.docx) to clean Markdown (.md). The documents are structured as a two-column table:

- **Left column** — lesson concepts, language, objectives, monitoring, differentiation
- **Right column** — learning sequence body, Resources, Safety, Helpful information

All cell text from both columns is preserved in document order. Section headings are automatically inserted for all recognised C2C section labels.

## Supported Lesson Types

| Type | Main heading in document |
|---|---|
| Standard lesson | `Example learning sequence` |
| Review / extend | `Review, reinforce and extend learning` |
| Assessment block | `Example assessment sequence` / `Assessment purpose` |

The cleaner handles all three types without any manual configuration.
26: 
27: ### 4. General Document Conversion (Structure-Aware)
28: 
29: For documents that are NOT C2C lesson plans (e.g., Unit Plans, Assessment Tasks, Rubrics), use the structure-aware converter. This prioritises structural fidelity and complex table reconstruction.
30: 
31: ```powershell
32: python .agent/skills/docx-to-markdown/scripts/structure_aware_convert.py `
33:   "<path/to/Document.docx>" `
34:   "<path/to/output/Document.md>"
35: ```

## Workflow

### 1. Convert a Single Lesson

```powershell
python .agent/skills/docx-to-markdown/scripts/convert_lesson.py `
  "<path/to/Lesson.docx>" `
  "<path/to/output/Lesson.md>" `
  "<path/to/Resources/>" `
  "<relative-path-from-md-to-resources>"   # optional, default: ../../Resources
```

The script:
- Runs `pandoc --wrap=none` for clean table output
- Extracts **all hyperlinks** from the Word zip directly (no disk unpacking)
- Scans the `Resources/` folder recursively and matches URL basenames to local files
- Rewrites `learningplace.eq.edu.au` (and similar) URLs to local relative paths
- Extracts ALL cell text from both table columns
- Injects `##` headings and `---` dividers at any recognised C2C section name
- Injects YAML frontmatter listing resolved local resources and any external links kept

### 2. Batch Convert a Full Unit

Write a small batch script:

```python
import os, subprocess, sys

UNIT_ROOT   = r"path/to/Unit"
LESSONS_DIR = os.path.join(UNIT_ROOT, "Teaching Sequence")   # or "Lessons"
OUTPUT_DIR  = os.path.join(LESSONS_DIR, "Lessons")           # output subfolder
RESOURCES   = os.path.join(UNIT_ROOT, "Resources")
SCRIPT      = r".agent/skills/docx-to-markdown/scripts/convert_lesson.py"
REL         = "../../Resources"  # adjust to match output dir depth

os.makedirs(OUTPUT_DIR, exist_ok=True)
for fname in sorted(f for f in os.listdir(LESSONS_DIR) if f.endswith('.docx')):
    subprocess.run([sys.executable, SCRIPT,
                    os.path.join(LESSONS_DIR, fname),
                    os.path.join(OUTPUT_DIR, fname.replace('.docx', '.md')),
                    RESOURCES, REL], check=True)
```

### 3. Build Resource Map

After all lessons are converted:

```powershell
python .agent/skills/docx-to-markdown/scripts/build_resource_map.py "<Unit Root or Lessons folder>"
```

Creates `resource_map.json` verifying `"exists": true` for every internal resource link.

## Resource Link Resolution

The default strategy requires no special configuration:

1. **Scan `Resources/`** recursively — build a normalised filename index
2. **Extract URL basename** from each hyperlink (URL-decoded last path segment)
3. **Exact match** → rewrite to local relative path
4. **Suffix match** fallback → for files whose online name differs from local name (e.g. different prefix added by the publisher)
5. **No match** → keep as genuine external URL in `external_links` frontmatter

## Notes

- **`resources_rel_path`** must be set correctly for links to resolve. If your `.md` files sit in `Lessons/` inside `Teaching Sequence/`, the relative path to `Resources/` is `../../Resources`. If `.md` files sit directly in the unit root beside `Resources/`, use `../Resources`.
- All extracted content text preserves inline Markdown (bold, italic, hyperlinks).
- ACARA logos and C2C concept icons with no useful label are silently dropped to avoid clutter.

## Scripts

| Script | Purpose |
|---|---|
| `convert_lesson.py` | Main C2C converter — pandoc + table extraction + link rewriting |
| `structure_aware_convert.py` | General-purpose converter — structure-aware table reconstruction |
| `build_resource_map.py` | Build unit-level `resource_map.json` verifying all links |
| `extract_links.py` | Low-level tool to inspect raw hyperlinks in a .docx |
