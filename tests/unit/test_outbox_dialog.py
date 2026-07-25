import sys
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.destinations.external_outbox import ExternalOutbox
from app.ui.outbox_dialog import OutboxDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv)
    return app


def build_dead_letter_outbox(tmp_path: Path) -> ExternalOutbox:
    outbox = ExternalOutbox(tmp_path / "outbox.db")
    local_id = outbox.enqueue(
        task_id="CVN-DIALOG",
        endpoint_url=(
            "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/"
            "cvn-submit-task"
        ),
        payload_json="{}",
        payload_hash="hash",
        idempotency_key="idem-dialog",
        nonce="nonce-dialog",
        target_agent="openclaw",
    )
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Synthetic failure", max_attempts=1)
    return outbox


def test_outbox_dialog_retries_only_selected_dead_letter(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    outbox = build_dead_letter_outbox(tmp_path)

    with mock.patch("app.ui.outbox_dialog.ExternalOutbox", return_value=outbox):
        dialog = OutboxDialog()
        assert dialog.table.rowCount() == 1
        assert not dialog.retry_btn.isEnabled()

        dialog.table.selectRow(0)
        qapp.processEvents()
        assert dialog.retry_btn.isEnabled()

        with (
            mock.patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            mock.patch.object(QMessageBox, "information"),
        ):
            dialog.retry_selected()

        assert outbox.get_stats()["pending"] == 1
        assert outbox.get_stats()["dead_letter"] == 0
        assert dialog.table.rowCount() == 0
        dialog.close()


def test_outbox_dialog_archives_only_selected_dead_letter(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    outbox = build_dead_letter_outbox(tmp_path)

    with mock.patch("app.ui.outbox_dialog.ExternalOutbox", return_value=outbox):
        dialog = OutboxDialog()
        dialog.table.selectRow(0)
        qapp.processEvents()
        assert dialog.archive_btn.isEnabled()

        with (
            mock.patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            mock.patch.object(QMessageBox, "information"),
        ):
            dialog.archive_selected()

        assert outbox.get_stats()["archived"] == 1
        assert outbox.get_stats()["dead_letter"] == 0
        assert dialog.table.rowCount() == 0
        dialog.close()
