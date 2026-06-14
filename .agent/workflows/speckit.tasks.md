---
description: Breakdown implementation plan into actionable tasks.
---

# /speckit.tasks

Use this command to generate a `tasks.md` file from an approved `plan.md` in the feature directory (`specs/features/<feature-name>/tasks.md`), based on the template at `specs/templates/tasks-template.md`.

## Workflow

1.  **Read Plan**: Parse the `specs/features/<feature-name>/plan.md` file.
2.  **Decompose**: Break down each component into step-by-step tasks.
3.  **Order**: Ensure dependencies are respected (e.g., foundational infrastructure before specific user stories).
4.  **Output**: Write to `specs/features/<feature-name>/tasks.md`.

