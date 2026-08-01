"""Headless UI unit tests for OutboundReviewDialog."""
import json
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from app.destinations.outbound_review_store import OutboundReviewStore
from app.ui.outbound_review_dialog import OutboundReviewDialog


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Fixture ensuring a single QApplication exists for UI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def temp_store(tmp_path: Path) -> OutboundReviewStore:
    return OutboundReviewStore(tmp_path / "test_review_ui.db")


def test_dialog_loading_and_selection(
    qapp: QApplication, temp_store: OutboundReviewStore
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-1",
        note_path="/notes/maths.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Fractions Lesson"}}),
        assessment_json=json.dumps({"risk_level": "low", "findings": []}),
    )

    dialog = OutboundReviewDialog(temp_store)
    assert dialog.item_list.count() == 1
    assert "Fractions Lesson" in dialog.item_list.item(0).text()

    # Check detail field population
    assert dialog.current_item_id == "CVNI-UI-1"
    assert dialog.title_edit.text() == "Fractions Lesson"
    assert dialog.risk_label.text() == "LOW"


def test_dialog_save_edits_and_approve(
    qapp: QApplication, temp_store: OutboundReviewStore
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-2",
        note_path="/notes/science.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Plant Biology"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog.title_edit.setText("Updated Plant Biology")
    dialog._on_save_edits_clicked()

    updated = temp_store.get_by_id("CVNI-UI-2")
    assert updated is not None
    draft = json.loads(updated["draft_json"])
    assert draft["content"]["title"] == "Updated Plant Biology"
