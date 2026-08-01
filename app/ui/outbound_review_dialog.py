"""Outbound Review Dialog - PySide6 UI for reviewing and approving outbound items."""
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.destinations.outbound_review_store import OutboundReviewStore


class OutboundReviewDialog(QDialog):
    """Dialog for inspecting, editing, approving, or rejecting outbound captures."""

    def __init__(
        self,
        review_store: OutboundReviewStore,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.review_store = review_store
        self.current_item_id: Optional[str] = None
        self.items_data: Dict[str, Dict[str, Any]] = {}
        self.init_ui()
        self.load_items()

    def init_ui(self) -> None:
        self.setWindowTitle("Outbound Sharing Review Queue")
        self.resize(900, 600)

        main_layout = QVBoxLayout(self)

        # Splitter for Left List & Right Detail View
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Panel: List of Pending Items
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("<b>Pending Outbound Items</b>")
        left_layout.addWidget(list_label)

        self.item_list = QListWidget()
        self.item_list.currentItemChanged.connect(self._on_item_selected)
        left_layout.addWidget(self.item_list)

        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.load_items)
        left_layout.addWidget(self.refresh_btn)

        splitter.addWidget(left_widget)

        # Right Panel: Detail and Editor
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        form_layout = QFormLayout()

        self.id_label = QLabel("-")
        form_layout.addRow("Item ID:", self.id_label)

        self.risk_label = QLabel("-")
        form_layout.addRow("Risk Level:", self.risk_label)

        self.findings_label = QLabel("-")
        self.findings_label.setWordWrap(True)
        form_layout.addRow("Privacy Findings:", self.findings_label)

        self.title_edit = QLineEdit()
        form_layout.addRow("Outbound Title:", self.title_edit)

        self.summary_edit = QTextEdit()
        self.summary_edit.setMaximumHeight(80)
        form_layout.addRow("Summary:", self.summary_edit)

        self.transcript_edit = QTextEdit()
        self.transcript_edit.setMaximumHeight(100)
        form_layout.addRow("Transcript:", self.transcript_edit)

        self.instructions_edit = QTextEdit()
        self.instructions_edit.setMaximumHeight(80)
        form_layout.addRow("Agent Instructions:", self.instructions_edit)

        self.item_kind_combo = QComboBox()
        self.item_kind_combo.addItems(["record_only", "agent_task"])
        form_layout.addRow("Item Kind:", self.item_kind_combo)

        self.target_agent_combo = QComboBox()
        self.target_agent_combo.addItems(["openclaw", "hermes", "auto"])
        form_layout.addRow("Target Agent:", self.target_agent_combo)

        self.note_path_label = QLabel("-")
        self.note_path_label.setWordWrap(True)
        form_layout.addRow("Local Note Path:", self.note_path_label)

        right_layout.addLayout(form_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.apply_redactions_btn = QPushButton("Apply Suggested Redactions")
        self.apply_redactions_btn.clicked.connect(
            self._on_apply_redactions_clicked
        )
        btn_layout.addWidget(self.apply_redactions_btn)

        self.open_note_btn = QPushButton("Open Local Note")
        self.open_note_btn.clicked.connect(self._on_open_note_clicked)
        btn_layout.addWidget(self.open_note_btn)

        self.save_edits_btn = QPushButton("Save Edits")
        self.save_edits_btn.clicked.connect(self._on_save_edits_clicked)
        btn_layout.addWidget(self.save_edits_btn)

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setStyleSheet("color: red;")
        self.reject_btn.clicked.connect(self._on_reject_clicked)
        btn_layout.addWidget(self.reject_btn)

        self.approve_btn = QPushButton("Approve & Send")
        self.approve_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold;"
        )
        self.approve_btn.clicked.connect(self._on_approve_clicked)
        btn_layout.addWidget(self.approve_btn)

        right_layout.addLayout(btn_layout)
        splitter.addWidget(right_widget)

        splitter.setSizes([300, 600])
        main_layout.addWidget(splitter)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        main_layout.addWidget(close_btn)

    def load_items(self) -> None:
        """Reloads items awaiting review from database."""
        self.item_list.clear()
        self.items_data.clear()
        self.current_item_id = None

        awaiting = self.review_store.get_awaiting_review()
        if not awaiting:
            self.item_list.addItem("No items awaiting review")
            self._clear_detail()
            return

        for item in awaiting:
            item_id = item["item_id"]
            self.items_data[item_id] = item

            assessment = {}
            try:
                assessment = json.loads(item.get("assessment_json", "{}"))
            except Exception:
                pass

            risk = assessment.get("risk_level", "low").upper()
            draft = {}
            try:
                draft = json.loads(item.get("draft_json", "{}"))
            except Exception:
                pass

            title = (
                draft.get("content", {}).get("title")
                or draft.get("task", {}).get("title")
                or "Untitled"
            )
            display_text = f"[{risk}] {title} ({item['item_kind']})"

            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.item_list.addItem(list_item)

        if self.item_list.count() > 0:
            self.item_list.setCurrentRow(0)

    def _clear_detail(self) -> None:
        self.id_label.setText("-")
        self.risk_label.setText("-")
        self.findings_label.setText("-")
        self.title_edit.clear()
        self.summary_edit.clear()
        self.transcript_edit.clear()
        self.instructions_edit.clear()
        self.note_path_label.setText("-")

    def _on_item_selected(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        if not current:
            self._clear_detail()
            return

        item_id = current.data(Qt.ItemDataRole.UserRole)
        if not item_id or item_id not in self.items_data:
            self._clear_detail()
            return

        self.current_item_id = item_id
        item = self.items_data[item_id]

        assessment = {}
        try:
            assessment = json.loads(item.get("assessment_json", "{}"))
        except Exception:
            pass

        draft = {}
        try:
            draft = json.loads(item.get("draft_json", "{}"))
        except Exception:
            pass

        self.id_label.setText(item_id)
        self.risk_label.setText(assessment.get("risk_level", "low").upper())

        findings = assessment.get("findings", [])
        self.findings_label.setText(
            ", ".join(findings) if findings else "None"
        )

        content = draft.get("content", {})
        task = draft.get("task", {}) or {}

        self.title_edit.setText(content.get("title", ""))
        self.summary_edit.setText(content.get("summary", ""))
        self.transcript_edit.setText(content.get("transcript") or "")
        self.instructions_edit.setText(task.get("instructions", ""))

        kind_idx = self.item_kind_combo.findText(item.get("item_kind", "record_only"))
        if kind_idx >= 0:
            self.item_kind_combo.setCurrentIndex(kind_idx)

        agent_idx = self.target_agent_combo.findText(item.get("target_agent", "openclaw"))
        if agent_idx >= 0:
            self.target_agent_combo.setCurrentIndex(agent_idx)

        self.note_path_label.setText(item.get("note_path", "-"))

    def _get_edited_draft(self) -> Dict[str, Any]:
        """Collects current field values into a draft structure."""
        if not self.current_item_id or self.current_item_id not in self.items_data:
            return {}

        existing_item = self.items_data[self.current_item_id]
        existing_draft = {}
        try:
            existing_draft = json.loads(existing_item.get("draft_json", "{}"))
        except Exception:
            pass

        content = existing_draft.get("content", {})
        content["title"] = self.title_edit.text().strip()
        content["summary"] = self.summary_edit.toPlainText().strip()

        transcript_val = self.transcript_edit.toPlainText().strip()
        content["transcript"] = transcript_val if transcript_val else None

        item_kind = self.item_kind_combo.currentText()
        target_agent = self.target_agent_combo.currentText()

        task = None
        if item_kind == "agent_task":
            instructions = self.instructions_edit.toPlainText().strip()
            task = {
                "title": content["title"],
                "instructions": instructions,
                "priority": "normal",
            }

        return {
            "item_kind": item_kind,
            "target_agent": target_agent,
            "content": content,
            "task": task,
        }

    def _on_save_edits_clicked(self) -> None:
        if not self.current_item_id:
            return
        draft_dict = self._get_edited_draft()
        self.review_store.update_draft(self.current_item_id, draft_dict)
        QMessageBox.information(self, "Saved", "Draft edits saved successfully.")
        self.load_items()

    def _on_apply_redactions_clicked(self) -> None:
        if not self.current_item_id:
            return
        item = self.items_data.get(self.current_item_id, {})
        assessment = {}
        try:
            assessment = json.loads(item.get("assessment_json", "{}"))
        except Exception:
            pass

        redactions = assessment.get("suggested_redactions", [])
        if not redactions:
            QMessageBox.information(
                self, "Redactions", "No deterministic redactions available."
            )
            return

        QMessageBox.information(
            self,
            "Suggested Redactions",
            "Suggestions:\n" + "\n".join(redactions),
        )

    def _on_open_note_clicked(self) -> None:
        if not self.current_item_id:
            return
        item = self.items_data.get(self.current_item_id, {})
        note_path = item.get("note_path", "")
        if note_path and os.path.exists(note_path):
            if sys.platform == "win32":
                os.startfile(note_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", note_path])
            else:
                subprocess.run(["xdg-open", note_path])
        else:
            QMessageBox.warning(self, "Error", f"File does not exist: {note_path}")

    def _on_reject_clicked(self) -> None:
        if not self.current_item_id:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Rejection",
            f"Are you sure you want to reject item '{self.current_item_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.review_store.reject(self.current_item_id, "User rejected via UI")
            self.load_items()

    def _on_approve_clicked(self) -> None:
        if not self.current_item_id:
            return

        item = self.items_data[self.current_item_id]
        assessment = {}
        try:
            assessment = json.loads(item.get("assessment_json", "{}"))
        except Exception:
            pass

        risk = assessment.get("risk_level", "low")

        # Save edits first
        draft_dict = self._get_edited_draft()
        self.review_store.update_draft(self.current_item_id, draft_dict)

        # High risk confirmation
        if risk == "high":
            confirm = QMessageBox.warning(
                self,
                "HIGH RISK CONFIRMATION",
                "This item contains high-risk privacy findings or restricted content.\n\n"
                "Are you sure you want to approve and transmit this item externally?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self.review_store.approve(self.current_item_id, approval_method="manual_ui")
        QMessageBox.information(
            self, "Approved", f"Item '{self.current_item_id}' approved for queueing."
        )
        self.load_items()
