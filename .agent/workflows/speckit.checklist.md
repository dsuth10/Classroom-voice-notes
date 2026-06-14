---
description: Generate a quality checklist for the current task.
---

# /speckit.checklist

Use this command to generate a project-specific quality checklist in the feature directory (`specs/features/<feature-name>/checklist.md`), based on the template at `specs/templates/checklist-template.md`.

## Workflow

1.  **Context Check**: Review the current task and progress.
2.  **Generate List**: Create a checklist of items to verify (e.g., unit tests, visual indicator check, audit log checks) based on the feature's implementation plan.
3.  **Integrate**: Usually appended to `specs/features/<feature-name>/tasks.md` or saved as `specs/features/<feature-name>/checklist.md`.

