"""Headless UI unit tests for OutboundReviewDialog and OutboundPreviewDialog."""
import json
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.destinations.outbound_review_store import OutboundReviewStore
from app.ui.outbound_review_dialog import (
    OutboundDraft,
    OutboundPreviewDialog,
    OutboundReviewDialog,
)


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


def test_outbound_draft_deep_immutability() -> None:
    """Verifies that OutboundDraft content and task dicts are deeply copied and immutable."""
    nested_content = {"title": "Test Title", "structured_fields": {"sub": [1, 2, 3]}}
    draft = OutboundDraft(
        item_kind="record_only",
        target_agent="openclaw",
        content=nested_content,
    )

    # Mutating original input dict does not affect draft
    nested_content["title"] = "Mutated Title"
    nested_content["structured_fields"]["sub"].append(4)  # type: ignore[attr-defined]

    assert draft.content["title"] == "Test Title"
    assert draft.content["structured_fields"]["sub"] == [1, 2, 3]

    # to_dict returns deep copy
    d_dict = draft.to_dict()
    d_dict["content"]["title"] = "New Title"
    assert draft.content["title"] == "Test Title"


def test_outbound_draft_validation() -> None:
    """Verifies draft validation logic for item_kind, target, title, and task."""
    # Invalid kind
    invalid_kind = OutboundDraft(
        item_kind="invalid_kind",
        target_agent="openclaw",
        content={"title": "Title"},
    )
    with pytest.raises(ValueError, match="Invalid item_kind"):
        invalid_kind.validate()

    # Empty title
    no_title = OutboundDraft(
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "   "},
    )
    with pytest.raises(ValueError, match="non-empty string title"):
        no_title.validate()

    # Missing task for agent_task
    missing_task = OutboundDraft(
        item_kind="agent_task",
        target_agent="openclaw",
        content={"title": "Task Title"},
        task=None,
    )
    with pytest.raises(ValueError, match="requires a valid task dictionary"):
        missing_task.validate()

    # Valid draft
    valid_draft = OutboundDraft(
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "Valid Note"},
    )
    valid_draft.validate()


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
        assessment_json=json.dumps({"risk_level": "low", "automatic_classification": "non_sensitive"}),
    )

    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text, *args, **kwargs: messages.append(("info", title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, text, *args, **kwargs: messages.append(("warning", title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, text, *args, **kwargs: messages.append(("critical", title, text)),
    )
    monkeypatch.setattr(
        OutboundPreviewDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog._on_approve_clicked()

    item = temp_store.get_by_id("CVNI-UI-3")
    assert item is not None
    assert item["status"] in ("queued", "approved_pending_enqueue", "enqueue_failed", "approved")
    assert item["approved_content_hash"] == item["content_hash"]


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
        OutboundPreviewDialog,
        "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    dialog = OutboundReviewDialog(temp_store)
    dialog._on_approve_clicked()

    item = temp_store.get_by_id("CVNI-UI-5")
    assert item is not None
    assert item["status"] == "awaiting_review"
