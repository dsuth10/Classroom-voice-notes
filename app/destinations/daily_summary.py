from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime
from app.audit.audit_logger import log_audit_event
from app.destinations.telegram_dispatcher import TelegramDispatcher

class DailySummaryBuilder:
    def __init__(self, vault_path: str, settings_manager: Any) -> None:
        self.vault_path = Path(vault_path)
        self.settings_manager = settings_manager
        self.summary_dir = self.vault_path / "Classroom Voice Notes" / "Daily Summaries"

    def _parse_note(self, file_path: Path) -> Dict[str, Any]:
        """Simple helper to extract YAML frontmatter from a markdown note."""
        frontmatter = {}
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---")
                if len(parts) >= 3:
                    yaml_str = parts[1]
                    current_key = None
                    for line in yaml_str.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("-") and current_key:
                            if not isinstance(frontmatter.get(current_key), list):
                                frontmatter[current_key] = []
                            frontmatter[current_key].append(line[1:].strip())
                        elif ":" in line:
                            key, val = line.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if val == "":
                                frontmatter[key] = []
                                current_key = key
                            else:
                                if val.lower() == "true":
                                    frontmatter[key] = True
                                elif val.lower() == "false":
                                    frontmatter[key] = False
                                else:
                                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                        val = val[1:-1]
                                    frontmatter[key] = val
                                current_key = None
        except Exception as e:
            log_audit_event("SUMMARY_PARSE_NOTE_ERROR", "session", f"Failed to parse note {file_path.name}: {e}")
        return frontmatter

    def generate_daily_summary(self, target_date_str: str = None) -> Tuple[str, bool]:
        """Scans the vault for notes matching the target date, builds markdown summary, and dispatches to Telegram."""
        if target_date_str is None:
            target_date_str = datetime.now().strftime("%Y-%m-%d")
            
        log_audit_event("DAILY_SUMMARY_START", "session", f"Generating daily summary for {target_date_str}")
        
        folders_to_scan = [
            "Student Notes",
            "Behaviour Notes",
            "Maths Notes",
            "English Notes",
            "Science Notes",
            "HASS Notes",
            "Digital Technologies Notes",
            "Design Technologies Notes",
            "Reminders",
            "Email Drafts",
            "Agent Task Archive",
            "Inbox",
            "Review Queue"
        ]
        
        notes_found: List[Dict[str, Any]] = []
        category_counts: Dict[str, int] = {}
        
        base_dir = self.vault_path / "Classroom Voice Notes"
        for folder in folders_to_scan:
            target_folder = base_dir / folder
            if not target_folder.exists():
                continue
                
            for md_file in target_folder.glob("*.md"):
                fm = self._parse_note(md_file)
                note_date = fm.get("date")
                
                if note_date == target_date_str:
                    category = fm.get("category", "general_note")
                    title = fm.get("title", md_file.stem)
                    
                    try:
                        rel_path = md_file.relative_to(self.vault_path).as_posix()
                    except ValueError:
                        rel_path = md_file.name
                        
                    notes_found.append({
                        "path": rel_path,
                        "title": title,
                        "category": category
                    })
                    
                    category_counts[category] = category_counts.get(category, 0) + 1
                    
        # Parse date for display
        try:
            dt = datetime.strptime(target_date_str, "%Y-%m-%d")
            date_display = dt.strftime("%d %B %Y")
            telegram_date = dt.strftime("%d %b %Y")
        except ValueError:
            date_display = target_date_str
            telegram_date = target_date_str
            
        # Format Markdown File
        now_str = datetime.now().strftime("%I:%M %p")
        lines = [
            f"# Daily Summary: {date_display}",
            "",
            f"**Generated at**: {now_str}",
            "",
            "## Summary of Activity",
            ""
        ]
        
        if not notes_found:
            lines.append("No notes were recorded on this day.")
        else:
            for cat, count in sorted(category_counts.items()):
                cat_display = cat.replace("_", " ").title()
                lines.append(f"- **{cat_display}**: {count}")
            lines.append("")
            
            lines.append("## Notes Created Today")
            lines.append("")
            for note in sorted(notes_found, key=lambda x: x["path"]):
                cat_display = note["category"].replace("_", " ").title()
                lines.append(f"- [[{note['path']}|{note['title']}]] ({cat_display})")
                
        # Save markdown file
        try:
            self.summary_dir.mkdir(parents=True, exist_ok=True)
            summary_file = self.summary_dir / f"Summary_{target_date_str}.md"
            with open(summary_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            log_audit_event("DAILY_SUMMARY_SAVE_SUCCESS", "session", f"Saved daily summary: {summary_file}")
        except Exception as e:
            log_audit_event("DAILY_SUMMARY_SAVE_ERROR", "session", f"Failed to save daily summary file: {e}")
            return "", False

        # Format and dispatch Telegram message
        telegram_lines = [
            f"📅 *Daily Summary - {telegram_date}*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        if not notes_found:
            telegram_lines.append("No voice notes were recorded today.")
        else:
            telegram_lines.append("Activity Breakdown:")
            for cat, count in sorted(category_counts.items()):
                cat_display = cat.replace("_", " ").title()
                telegram_lines.append(f"• {cat_display}: {count}")
            telegram_lines.append("")
            telegram_lines.append(f"*Total Notes*: {len(notes_found)}")
            
        telegram_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        telegram_msg = "\n".join(telegram_lines)
        
        dispatcher = TelegramDispatcher(self.settings_manager)
        default_agent = self.settings_manager.get("agents.default_agent") or "hermes"
        telegram_success = dispatcher.send_raw_message(telegram_msg, agent=default_agent)
        
        return str(summary_file), telegram_success
