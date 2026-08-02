"""Outbound Review Dialog - PySide6 UI for reviewing and approving outbound items."""
import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
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
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import SettingsManager
from app.destinations.canonical_json import compute_canonical_content_hash
from app.destinations.outbound_review_store import OutboundReviewStore


@dataclass(frozen=True)
class OutboundDraft:
    """Deeply immutable representation of editable outbound draft fields."""

    item_kind: str
    target_agent: str
    content: Dict[str, Any]
    task: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", copy.deepcopy(self.content or {}))
        object.__setattr__(
            self,
            "task",
            copy.deepcopy(self.task) if self.task is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_kind": self.item_kind,
            "target_agent": self.target_agent,
            "content": copy.deepcopy(self.content),
            "task": copy.deepcopy(self.task) if self.task is not None else None,
        }

    def validate(self) -> None:
        """Explicit validation for item kind, target, content, task, and size limits."""
        if self.item_kind not in ("record_only", "agent_task"):
            raise ValueError(
                f"Invalid item_kind '{self.item_kind}'. Must be 'record_only' or 'agent_task'."
            )

        if self.target_agent not in ("openclaw", ""):
            raise ValueError(
                f"Unpermitted target_agent '{self.target_agent}'. Must be 'openclaw'."
            )

        if not isinstance(self.content, dict) or not str(self.content.get("title", "")).strip():
            raise ValueError("Draft content must contain a non-empty string title.")

        if self.item_kind == "agent_task":
            if not isinstance(self.task, dict):
                raise ValueError("agent_task draft requires a valid task dictionary.")
            if not str(self.task.get("instructions", "")).strip():
                raise ValueError("agent_task draft requires non-empty agent instructions.")
        elif self.item_kind == "record_only":
            if self.task and len(self.task) > 0:
                raise ValueError("record_only draft must not contain task instructions.")

        serialized = json.dumps(self.to_dict())
        if len(serialized.encode("utf-8")) > 524288:
            raise ValueError("Draft payload exceeds maximum allowed size limit of 512 KB.")


class OutboundPreviewDialog(QDialog):
    """Scrollable, read-only confirmation modal displaying every outbound field prior to approval."""

    def __init__(
        self,
        item_id: str,
        draft: OutboundDraft,
        assessment: Any,
        metadata: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self.draft = draft
        self.assessment = assessment
        self.metadata = metadata
        self.init_ui()

    def init_ui(self) -> None:
        self.setWindowTitle(f"Final Outbound Preview — {self.item_id}")
        self.resize(700, 550)

        layout = QVBoxLayout(self)

        risk = str(getattr(self.assessment, "risk_level", "low")).lower()
        if risk == "high":
            alert = QLabel("⚠️ HIGH RISK WARNING — EXTERNAL TRANSMISSION REVIEW")
            alert.setStyleSheet(
                "color: white; background-color: #c62828; padding: 8px; font-weight: bold; font-size: 13px;"
            )
            alert.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(alert)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)

        form.addRow("<b>Item ID:</b>", QLabel(self.item_id))
        form.addRow("<b>Item Kind:</b>", QLabel(self.draft.item_kind))
        form.addRow("<b>Target Agent:</b>", QLabel(self.draft.target_agent or "openclaw"))

        content = self.draft.content
        form.addRow("<b>Title:</b>", QLabel(str(content.get("title", "-"))))

        summary_edit = QTextEdit()
        summary_edit.setReadOnly(True)
        summary_edit.setPlainText(str(content.get("summary", "-")))
        summary_edit.setMaximumHeight(70)
        form.addRow("<b>Summary:</b>", summary_edit)

        transcript_val = content.get("transcript")
        if transcript_val:
            tr_edit = QTextEdit()
            tr_edit.setReadOnly(True)
            tr_edit.setPlainText(str(transcript_val))
            tr_edit.setMaximumHeight(110)
            form.addRow("<b>Transcript:</b>", tr_edit)
        else:
            form.addRow("<b>Transcript:</b>", QLabel("<i>Not included</i>"))

        cat = content.get("category", "-")
        tags_val = content.get("tags")
        tags_str = ", ".join(tags_val) if isinstance(tags_val, list) else "-"
        s_fields = json.dumps(content.get("structured_fields") or {}, indent=2)

        form.addRow("<b>Category:</b>", QLabel(str(cat)))
        form.addRow("<b>Tags:</b>", QLabel(tags_str))

        sf_edit = QTextEdit()
        sf_edit.setReadOnly(True)
        sf_edit.setPlainText(s_fields)
        sf_edit.setMaximumHeight(60)
        form.addRow("<b>Structured Fields:</b>", sf_edit)

        if self.draft.item_kind == "agent_task" and self.draft.task:
            task_dict = self.draft.task
            form.addRow("<b>Task Title:</b>", QLabel(str(task_dict.get("title", "-"))))
            inst_edit = QTextEdit()
            inst_edit.setReadOnly(True)
            inst_edit.setPlainText(str(task_dict.get("instructions", "-")))
            inst_edit.setMaximumHeight(80)
            form.addRow("<b>Task Instructions:</b>", inst_edit)
            form.addRow("<b>Task Priority:</b>", QLabel(str(task_dict.get("priority", "normal"))))

        rec_at = self.metadata.get("created_at") or self.metadata.get("recorded_at") or "-"
        dur = self.metadata.get("duration_seconds") or "-"
        form.addRow("<b>Recorded Time:</b>", QLabel(str(rec_at)))
        form.addRow("<b>Duration:</b>", QLabel(f"{dur} sec" if dur != "-" else "-"))

        classification = getattr(self.assessment, "automatic_classification", "non_sensitive")
        findings = getattr(self.assessment, "findings", [])
        findings_str = ", ".join(findings) if findings else "None"

        form.addRow("<b>Classification:</b>", QLabel(str(classification)))
        form.addRow("<b>Risk Level:</b>", QLabel(risk.upper()))
        form.addRow("<b>Privacy Findings:</b>", QLabel(findings_str))
        form.addRow("<b>Release Basis:</b>", QLabel("human_approval"))

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel / Keep Awaiting Review")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("Confirm & Authorize Release")
        confirm_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 6px;"
        )
        confirm_btn.clicked.connect(self.accept)
        btn_layout.addWidget(confirm_btn)

        layout.addLayout(btn_layout)


class OutboundReviewDialog(QDialog):
    """Dialog for inspecting, editing, approving, or rejecting outbound captures."""

    def __init__(
        self,
        review_store: OutboundReviewStore,
        settings_manager: Optional[SettingsManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.review_store = review_store
        self.settings_manager = settings_manager
        self.current_item_id: Optional[str] = None
        self.items_data: Dict[str, Dict[str, Any]] = {}
        self.init_ui()
        self.load_items()

    def init_ui(self) -> None:
        self.setWindowTitle("Outbound Sharing Review Queue")
        self.resize(900, 600)

        main_layout = QVBoxLayout(self)
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
        self.target_agent_combo.addItems(["openclaw"])
        form_layout.addRow("Target Agent:", self.target_agent_combo)

        self.note_path_label = QLabel("-")
        self.note_path_label.setWordWrap(True)
        form_layout.addRow("Local Note Path:", self.note_path_label)

        right_layout.addLayout(form_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.apply_redactions_btn = QPushButton("Apply Suggested Redactions")
        self.apply_redactions_btn.clicked.connect(self._on_apply_redactions_clicked)
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
        self.findings_label.setText(", ".join(findings) if findings else "None")

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

    def _get_edited_draft(self) -> Optional[OutboundDraft]:
        """Reads editable fields once into a deeply immutable OutboundDraft value."""
        if not self.current_item_id or self.current_item_id not in self.items_data:
            return None

        existing_item = self.items_data[self.current_item_id]
        existing_draft = {}
        try:
            existing_draft = json.loads(existing_item.get("draft_json", "{}"))
        except Exception:
            pass

        content = copy.deepcopy(existing_draft.get("content", {}))
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

        draft = OutboundDraft(
            item_kind=item_kind,
            target_agent=target_agent,
            content=content,
            task=task,
        )

        try:
            draft.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Draft", str(exc))
            return None

        return draft

    def _on_save_edits_clicked(self) -> None:
        if not self.current_item_id:
            return
        draft = self._get_edited_draft()
        if not draft:
            return

        vault_path = ""
        if self.settings_manager:
            vault_path = str(self.settings_manager.get("obsidian_vault_path") or "")

        from app.ollama_router.policy_gate import PolicyGate

        gate = PolicyGate()
        try:
            assessment = gate.assess_v2_item(
                item_kind=draft.item_kind,
                target_agent=draft.target_agent,
                content=draft.content,
                task=draft.task,
                vault_path=vault_path,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Assessment Failed",
                f"Policy gate assessment failed for draft edits: {exc}\nItem remains awaiting review.",
            )
            return

        assessment_dict = {
            "automatic_classification": assessment.automatic_classification,
            "risk_level": assessment.risk_level,
            "findings": assessment.findings,
            "checks_passed": assessment.checks_passed,
            "suggested_redactions": assessment.suggested_redactions,
            "safe_auto_allowed": assessment.safe_auto_allowed,
        }
        assessment_json = json.dumps(assessment_dict)
        self.review_store.update_draft(
            self.current_item_id, draft.to_dict(), assessment_json=assessment_json
        )

        self.risk_label.setText(assessment.risk_level.upper())
        self.findings_label.setText(
            ", ".join(assessment.findings) if assessment.findings else "None"
        )
        QMessageBox.information(self, "Saved", "Draft edits saved successfully.")
        self.load_items()

    def _on_apply_redactions_clicked(self) -> None:
        if not self.current_item_id:
            return

        email_pat = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
        phone_pat = re.compile(r"\b\d{8,15}\b")
        path_pat = re.compile(r"([A-Za-z]:\\[^\s\n]+|[A-Za-z]:/[^\s\n]+|/Users/[^\s\n]+|\\Users\\[^\s\n]+)")

        text = self.title_edit.text()
        text = email_pat.sub("[REDACTED_EMAIL]", text)
        text = phone_pat.sub("[REDACTED_PHONE]", text)
        text = path_pat.sub("[REDACTED_PATH]", text)
        self.title_edit.setText(text)

        for text_edit in (self.summary_edit, self.transcript_edit, self.instructions_edit):
            t = text_edit.toPlainText()
            t = email_pat.sub("[REDACTED_EMAIL]", t)
            t = phone_pat.sub("[REDACTED_PHONE]", t)
            t = path_pat.sub("[REDACTED_PATH]", t)
            text_edit.setText(t)

        self._on_save_edits_clicked()

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

        draft = self._get_edited_draft()
        if not draft:
            return

        vault_path = ""
        if self.settings_manager:
            vault_path = str(self.settings_manager.get("obsidian_vault_path") or "")

        from app.ollama_router.policy_gate import PolicyGate

        gate = PolicyGate()
        try:
            assessment = gate.assess_v2_item(
                item_kind=draft.item_kind,
                target_agent=draft.target_agent,
                content=draft.content,
                task=draft.task,
                vault_path=vault_path,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Assessment Error",
                f"Policy gate assessment error: {exc}\nItem remains in awaiting review.",
            )
            return

        assessment_dict = {
            "automatic_classification": assessment.automatic_classification,
            "risk_level": assessment.risk_level,
            "findings": assessment.findings,
            "checks_passed": assessment.checks_passed,
            "suggested_redactions": assessment.suggested_redactions,
            "safe_auto_allowed": assessment.safe_auto_allowed,
        }
        assessment_json = json.dumps(assessment_dict)

        # Persist draft edits & assessment together
        self.review_store.update_draft(
            self.current_item_id, draft.to_dict(), assessment_json=assessment_json
        )

        item_metadata = self.items_data.get(self.current_item_id, {})

        # Display full scrollable read-only preview dialog
        preview_dialog = OutboundPreviewDialog(
            item_id=self.current_item_id,
            draft=draft,
            assessment=assessment,
            metadata=item_metadata,
            parent=self,
        )
        if preview_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Calculate exact canonical approved content hash from immutable draft
        c_str, approved_hash = compute_canonical_content_hash(
            item_kind=draft.item_kind,
            target_agent=draft.target_agent,
            content=draft.content,
            task=draft.task,
        )

        # Transition state to approved_pending_enqueue with approved_content_hash
        self.review_store.approve(
            self.current_item_id,
            approval_method="manual_ui",
            approved_content_hash=approved_hash,
        )

        # Submit via OutboundSubmissionService
        try:
            from app.destinations.outbound_submission_service import (
                OutboundSubmissionService,
            )

            submission_service = OutboundSubmissionService(
                settings_manager=self.settings_manager,
                review_store=self.review_store,
            )
            submission_service.submit_approved_item(self.current_item_id)
            QMessageBox.information(
                self,
                "Queued for delivery",
                f"Item '{self.current_item_id}' approved and queued for delivery.",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Enqueue Warning",
                f"Item approval saved but outbox enqueue failed: {exc}",
            )

        self.load_items()
