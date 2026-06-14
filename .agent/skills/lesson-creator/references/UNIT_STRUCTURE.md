# Standard Unit Architecture

This document defines the mandatory file and folder structure for all instructional units to ensure brand consistency, resource integrity, and ease of automated conversion.

## 📁 Directory Structure

```
[Unit_Name]/
├── Unit_Plan/          # Unit overview, assessment descriptions, and mapping
├── Resources/          # ALL media, documents, and interactives
│   ├── Manifest.md     # MANDATORY: Markdown index of all resources (Inventory)
│   ├── Documents/      # PDFs, DOCX, etc.
│   ├── Video/          # MP4, MOV, etc.
│   ├── Images/         # PNG, JPG, SVG, etc.
│   └── Website/        # Developed websites or HTML interactives
├── Lesson_Plans/       # Per-lesson consolidated folders
│   ├── Lesson_01/
│   │   ├── scripts/    # Build scripts for this lesson
│   │   ├── Lesson_01_Plan.md
│   │   └── ...
│   └── Lesson_02/
│       └── ...
├── Research/           # Background information, curriculum extracts
└── _scripts/           # Shared unit-level utilities and automation
```

> [!NOTE]
> **No Separate Student Documents Folder**: To ensure clean organisation, all student-facing materials (such as worksheets, templates, exemplars, and activities) must reside either directly inside their specific lesson plan directory (under `Lesson_Plans/Lesson_XX/`) or in the central `Resources/` folder if they are general to the unit. The legacy `Student_Documents/` folder is deprecated and must not be used, keeping all relevant materials fully integrated into their pedagogical context.


## 📜 Resource Manifest (`Manifest.md`)

Every unit MUST contain a `Manifest.md` in the `Resources/` folder. This file serves as the source of truth for available assets.

### Requirements:
- **Categorization**: Group resources by type (Documents, Video, etc.).
- **Metadata**: Include filename, description, and intended lesson usage.
- **Inconsistency Check**: If a lesson references a file not in the manifest, it is considered a breaking inconsistency.

## 🛠️ Implementation Protocol

1.  **Creation**: If a `Resources/` folder or `Manifest.md` is missing when starting a new unit or lesson, the agent MUST suggest their creation.
2.  **Discovery**: Before generating content, run `ls -R Resources/` to verify what is actually available.
3.  **Summarization**: Always provide the user with a summary of discovered assets (e.g., "I've identified 12 documents and 2 websites in your Resources folder").
