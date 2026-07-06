from typing import Any, Dict

class NoteTemplates:
    @staticmethod
    def _build_yaml(frontmatter: Dict[str, Any]) -> str:
        """Converts a dictionary into a YAML frontmatter block."""
        lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            elif isinstance(v, bool):
                lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k}: {v}")
            elif v is None:
                lines.append(f"{k}: null")
            else:
                lines.append(f"{k}: {v}")
        lines.append("---")
        return "\n".join(lines)

    @classmethod
    def render(
        cls,
        category: str,
        title: str,
        now_str: str,
        transcript: str,
        base_frontmatter: Dict[str, Any],
        category_fields: Dict[str, Any]
    ) -> str:
        """Renders the complete Markdown document (Frontmatter + Body) for a category."""
        
        # Make a copy of base frontmatter so we don't mutate original
        frontmatter = dict(base_frontmatter)
        
        # Inject category-specific frontmatter fields
        for k, v in category_fields.items():
            if v is not None and k != "students_mentioned": # students_mentioned is processed to 'students' list
                frontmatter[k] = v
                
        # Resolve students field if anonymised IDs exist
        if "students" in category_fields:
            frontmatter["students"] = category_fields["students"]

        yaml_block = cls._build_yaml(frontmatter)
        
        # Default/common decision block at bottom
        decision_block = f"""
## Router Decision

- Route: {frontmatter.get("route")}
- Sensitivity: {frontmatter.get("sensitivity")}
- Category: {frontmatter.get("category")}
- Telegram allowed: {str(frontmatter.get("telegram_allowed", False)).lower()}
- Confidence: {frontmatter.get("confidence", 0.0)}

## Review Status

- [ ] Checked transcript
- [ ] Edited for accuracy
- [ ] Added context if needed
"""

        # Generate category-specific body layouts
        if category == "student_note":
            students_str = ", ".join(category_fields.get("students", [])) or "None"
            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Observation Details
- **Observation Type**: {category_fields.get("observation_type", "general")}
- **Students Involved (IDs)**: {students_str}
"""
        elif category == "behaviour_note":
            students_str = ", ".join(category_fields.get("students", [])) or "None"
            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Incident Details
- **Behaviour Type**: {category_fields.get("behaviour_type", "general")}
- **Action Taken**: {category_fields.get("action_taken", "none")}
- **Students Involved (IDs)**: {students_str}
"""
        elif category in ("maths_note", "english_note", "science_note", "hass_note", "digitech_note", "designtech_note"):
            subject_names = {
                "maths_note": "Mathematics",
                "english_note": "English",
                "science_note": "Science",
                "hass_note": "HASS",
                "digitech_note": "Digital Technologies",
                "designtech_note": "Design Technologies"
            }
            subject = subject_names.get(category, "General")
            
            # Form subject details block
            details = [
                f"- **Subject**: {subject}",
                f"- **Year Level**: {category_fields.get('year_level', 'Unknown')}",
                f"- **Strand**: {category_fields.get('strand', 'Unknown')}"
            ]
            if category == "maths_note" and category_fields.get("misconception_type"):
                details.append(f"- **Key Misconception**: {category_fields['misconception_type']}")
            elif category == "science_note" and category_fields.get("investigation_type"):
                details.append(f"- **Investigation Type**: {category_fields['investigation_type']}")
            elif category == "english_note" and category_fields.get("text_type"):
                details.append(f"- **Text Type**: {category_fields['text_type']}")
                
            if category_fields.get("students"):
                details.append(f"- **Students Involved (IDs)**: {', '.join(category_fields['students'])}")
                
            details_block = "\n".join(details)

            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Curriculum Context
{details_block}
"""
        elif category == "reminder":
            r_time = category_fields.get("reminder_time") or "Not scheduled"
            priority = category_fields.get("priority") or "normal"
            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Reminder Details
- **Scheduled Time**: {r_time}
- **Priority**: {priority}
"""
        elif category == "email_draft":
            recipient = category_fields.get("recipient") or "Unknown"
            subject = category_fields.get("subject_line") or "No Subject"
            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Draft Metadata
- **Recipient**: {recipient}
- **Suggested Subject**: {subject}
"""
        elif category == "agent_task":
            agent = category_fields.get("agent_target") or "auto"
            task_id = category_fields.get("task_id") or "Pending"
            body = f"""# {title} — {now_str}

## Transcript

{transcript}

## Task Details
- **Target Agent**: {agent}
- **Task Tracking ID**: {task_id}
"""
        else:
            # Default / general note
            body = f"""# {title} — {now_str}

## Transcript

{transcript}
"""

        return yaml_block + "\n" + body + "\n" + decision_block
