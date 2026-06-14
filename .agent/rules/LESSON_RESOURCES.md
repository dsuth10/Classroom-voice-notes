---
trigger: always_on
---

# LESSON_RESOURCES.md - Lesson-Resource Relationship Protocol

> This rule defines the system for maintaining and documenting the links between lesson plans and their supporting resources (PDFs, worksheets, videos, etc.).

---

## 🏗️ Architecture of the Mapping System

To ensure that lesson plans remain usable even after conversion to Markdown, a structured mapping system is used to track all internal and external dependencies.

### 1. Central Registry: `resource_map.json`
Every instructional unit (e.g., "Unit 1 Biology Mould") should contain a `resource_map.json` file in its root folder.
- **Goal**: Provides a machine-readable index of all lesson-to-resource connections.
- **Structure**: Includes filenames, source DOCX files, and a validated list of resources with an `exists` status.
- **Verification**: This file serves as the source of truth for checking if a unit is "complete" (all linked files are present on disk).

### 2. Embedded Metadata (YAML Frontmatter)
Each lesson plan in Markdown format must include a YAML frontmatter block that explicitly lists its resources.
- **`source`**: The name of the original Word document.
- **`resources`**: A list of relative paths to internal resource files (typically in `../Resources/`).
- **`external_links`**: A list of URLs for websites, inter-actives, or policy documents.

### 3. Verification & Maintenance
- **Conversion Workflow**: Use the `docx-to-markdown` skill to convert Word documents. This ensures frontmatter is correctly injected.
- **Updating the Map**: After any change to files or folders, run the `build_resource_map.py` script from the `docx-to-markdown` skill to regenerate the unit-level JSON registry.
- **Integrity**: Always verify that `"exists": true` in the JSON map before distributing or deploying a unit.

---

## 📖 Source of Truth Protocol

To maintain consistency and leverage the improved accessibility of digital formats, the following priority system applies:

1. **Markdown is Primary**: If a lesson exists in both `.docx` and `.md` formats, the **Markdown document is the primary source of truth**. All questions, analysis, and further development should reference the Markdown version.
2. **Resource Dependency**: This priority applies only as long as the Markdown file maintains valid links to its resources (verified via `resource_map.json`).
3. **Word as Archive**: The original `.docx` file serves as a structure/formatting archive and should only be consulted if the Markdown conversion is suspect or missing content.

---
