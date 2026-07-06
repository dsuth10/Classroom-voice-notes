import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.destinations.daily_summary import DailySummaryBuilder

class MockSettingsManager:
    def __init__(self):
        self.vals = {
            "agents.telegram_token": "fake_token",
            "agents.default_agent": "hermes",
            "agents.agents.hermes.chat_id": "123456"
        }
    def get(self, key):
        return self.vals.get(key)

@patch("app.destinations.telegram_dispatcher.httpx.post")
def test_daily_summary_builder(mock_post: MagicMock, tmp_path: Path) -> None:
    """Verifies that DailySummaryBuilder aggregates today's notes and sends privacy-compliant Telegram counts."""
    # Mock Telegram server response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    
    vault_dir = tmp_path / "vault"
    cvn_dir = vault_dir / "Classroom Voice Notes"
    cvn_dir.mkdir(parents=True)
    
    # Write some dummy notes with date = 2026-07-06
    maths_dir = cvn_dir / "Maths Notes"
    maths_dir.mkdir()
    
    note1 = maths_dir / "note1.md"
    note1.write_text("""---
type: classroom-voice-note
category: maths_note
date: 2026-07-06
title: Multiplication Help
---
## Transcript
Struggled with 5x table.
""", encoding="utf-8")

    # Write a note from a different day
    note2 = maths_dir / "note2.md"
    note2.write_text("""---
type: classroom-voice-note
category: maths_note
date: 2026-07-05
title: Older Note
---
## Transcript
Old.
""", encoding="utf-8")

    # Write a behaviour note for today
    behaviour_dir = cvn_dir / "Behaviour Notes"
    behaviour_dir.mkdir()
    note3 = behaviour_dir / "note3.md"
    note3.write_text("""---
type: classroom-voice-note
category: behaviour_note
date: 2026-07-06
title: Running in Corridor
---
## Transcript
Ran.
""", encoding="utf-8")

    settings = MockSettingsManager()
    builder = DailySummaryBuilder(str(vault_dir), settings)
    
    summary_path_str, success = builder.generate_daily_summary(target_date_str="2026-07-06")
    
    assert success is True
    assert summary_path_str != ""
    
    summary_file = Path(summary_path_str)
    assert summary_file.exists()
    
    content = summary_file.read_text(encoding="utf-8")
    
    # Assert breakdown and links in Markdown
    assert "Daily Summary: 06 July 2026" in content
    assert "- **Maths Note**: 1" in content
    assert "- **Behaviour Note**: 1" in content
    assert "- [[Classroom Voice Notes/Maths Notes/note1.md|Multiplication Help]] (Maths Note)" in content
    assert "Older Note" not in content  # Ensure yesterday's note is excluded
    
    # Verify Telegram payload is safe (contains no names or transcript snippets)
    assert mock_post.called
    kwargs = mock_post.call_args[1]
    payload = kwargs["json"]
    assert payload["chat_id"] == "123456"
    assert "📅 *Daily Summary - 06 Jul 2026*" in payload["text"]
    assert "• Maths Note: 1" in payload["text"]
    assert "• Behaviour Note: 1" in payload["text"]
    assert "*Total Notes*: 2" in payload["text"]
    assert "Multiplication Help" not in payload["text"]  # No titles
    assert "Struggled" not in payload["text"]  # No transcripts
