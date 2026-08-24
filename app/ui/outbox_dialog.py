# app/ui/outbox_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QMessageBox, QLabel, QHeaderView, QWidget
)
from PySide6.QtCore import Qt
from app.destinations.external_outbox import ExternalOutbox

class OutboxDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Outbound Lifecycle and Safe Receipts")
        self.resize(1180, 480)
        self.outbox = ExternalOutbox()
        self.init_ui()
        self.refresh_tasks()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.info_label = QLabel(
            "Lifecycle metadata only: Submitted → Claimed → Completed or Blocked. "
            "No transcript or message content is shown."
        )
        layout.addWidget(self.info_label)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Local ID",
            "Task ID",
            "Lifecycle",
            "Submitted",
            "Claimed",
            "Completed / Blocked",
            "Safe receipt / reason",
            "Attempts",
            "Transport",
            "Last status check",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.update_button_states)
        layout.addWidget(self.table)

        # Action Buttons Layout
        btn_layout = QHBoxLayout()
        
        self.retry_btn = QPushButton("Retry Selected Task")
        self.retry_btn.clicked.connect(self.retry_selected)
        self.retry_btn.setEnabled(False)
        btn_layout.addWidget(self.retry_btn)

        self.archive_btn = QPushButton("Archive Selected Task")
        self.archive_btn.clicked.connect(self.archive_selected)
        self.archive_btn.setEnabled(False)
        btn_layout.addWidget(self.archive_btn)

        btn_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_tasks)
        btn_layout.addWidget(self.refresh_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def refresh_tasks(self) -> None:
        # Clear selection and retrieve privacy-safe lifecycle rows.
        self.table.setRowCount(0)
        self.retry_btn.setEnabled(False)
        self.archive_btn.setEnabled(False)

        tasks = self.outbox.get_lifecycle_tasks(limit=100)
        self.table.setRowCount(len(tasks))

        for row_idx, task in enumerate(tasks):
            finished_at = task.get("completed_at") or task.get("blocked_at") or ""
            receipt_or_reason = task.get("safe_receipt") or task.get("blocked_reason") or ""
            items = [
                str(task["local_id"]),
                str(task["task_id"]),
                str(task.get("lifecycle_state") or "").capitalize(),
                str(task.get("submitted_at") or ""),
                str(task.get("claimed_at") or ""),
                str(finished_at),
                str(receipt_or_reason),
                str(task["attempt_count"]),
                str(task["status"]),
                str(task.get("last_status_check_at") or ""),
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                # Make cells read-only
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

    def update_button_states(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.retry_btn.setEnabled(False)
            self.archive_btn.setEnabled(False)
            return

        row = selected_rows[0].row()
        status_item = self.table.item(row, 8)
        status = status_item.text() if status_item else ""

        # Enable actions ONLY if status is dead_letter
        is_dead = (status == "dead_letter")
        self.retry_btn.setEnabled(is_dead)
        self.archive_btn.setEnabled(is_dead)

    def retry_selected(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        local_id_item = self.table.item(row, 0)
        task_id_item = self.table.item(row, 1)
        if local_id_item is None or task_id_item is None:
            return

        local_id_str = local_id_item.text()
        local_id = int(local_id_str)
        task_id = task_id_item.text()

        confirm = QMessageBox.question(
            self,
            "Confirm Retry",
            f"Are you sure you want to retry task {task_id} (Local ID: {local_id})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            success = self.outbox.retry_dead_letter_task(local_id)
            if success:
                QMessageBox.information(self, "Success", f"Task {task_id} has been moved back to pending.")
                self.refresh_tasks()
            else:
                QMessageBox.warning(self, "Failed", "Failed to retry task. Verify environment matches task destination.")

    def archive_selected(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        local_id_item = self.table.item(row, 0)
        task_id_item = self.table.item(row, 1)
        if local_id_item is None or task_id_item is None:
            return

        local_id_str = local_id_item.text()
        local_id = int(local_id_str)
        task_id = task_id_item.text()

        confirm = QMessageBox.question(
            self,
            "Confirm Archive",
            f"Are you sure you want to archive task {task_id} (Local ID: {local_id})? This will prevent it from retrying.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            success = self.outbox.archive_dead_letter_task(local_id)
            if success:
                QMessageBox.information(self, "Success", f"Task {task_id} has been archived.")
                self.refresh_tasks()
            else:
                QMessageBox.warning(self, "Failed", "Failed to archive task.")
