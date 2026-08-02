"""Headless UI unit tests for OutboundReviewDialog."""
import json
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

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
    qapp: QApplication, temp_store: OutboundReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-2",
        note_path="/notes/science.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Plant Biology"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    info_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text, *args, **kwargs: info_messages.append((title, text)),
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog.title_edit.setText("Updated Plant Biology")
    dialog._on_save_edits_clicked()

    updated = temp_store.get_by_id("CVNI-UI-2")
    assert updated is not None
    draft = json.loads(updated["draft_json"])
    assert draft["content"]["title"] == "Updated Plant Biology"
    assert ("Saved", "Draft edits saved successfully.") in info_messages


def test_dialog_approve_and_reject(
    qapp: QApplication, temp_store: OutboundReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-3",
        note_path="/notes/art.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Color Theory"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    info_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text, *args, **kwargs: info_messages.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda parent, title, text, *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog._on_approve_clicked()

    item = temp_store.get_by_id("CVNI-UI-3")
    assert item is not None
    assert item["status"] == "queued"
    assert item["approved_content_hash"] == item["content_hash"]


def test_dialog_edit_triggers_reassessment_before_approval(
    qapp: QApplication, temp_store: OutboundReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-4",
        note_path="/notes/email.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Clean Note"}}),
        assessment_json=json.dumps({"risk_level": "low", "findings": []}),
    )

    warning_titles = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, text, *args, **kwargs: warning_titles.append(title) or QMessageBox.StandardButton.No,
    )

    dialog = OutboundReviewDialog(temp_store)
    # Edit title to contain PII email address
    dialog.title_edit.setText("Contact teacher@school.edu")
    dialog._on_approve_clicked()

    # Verify reassessment flagged high risk and triggered HIGH RISK CONFIRMATION warning box
    assert "HIGH RISK CONFIRMATION" in warning_titles
    # Since user clicked No, item remains awaiting_review
    item = temp_store.get_by_id("CVNI-UI-4")
    assert item is not None
    assert item["status"] == "awaiting_review"


def test_dialog_cancel_preview_keeps_awaiting_review(
    qapp: QApplication, temp_store: OutboundReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_store.create_review_item(
        item_id="CVNI-UI-5",
        note_path="/notes/cancel.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Cancel Test"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda parent, title, text, *args, **kwargs: QMessageBox.StandardButton.No,
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog._on_approve_clicked()

    item = temp_store.get_by_id("CVNI-UI-5")
    assert item is not None
    assert item["status"] == "awaiting_review"

