import sys
from typing import Any
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QMessageBox,
    QScrollArea,
)
from PySide6.QtCore import QTimer
from app.config.settings import SettingsManager

class MainWindow(QMainWindow):
    def __init__(self, settings_manager: SettingsManager, controller: Any = None) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.controller = controller
        self.init_ui()

    def init_ui(self) -> None:
        self.setWindowTitle("Classroom Voice Notes - Settings")
        self.resize(550, 650)
        
        # Main Layout wrapper with Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)
        
        central_widget = QWidget()
        scroll.setWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # ----------------------------------------------------
        # Group 1: General & System Settings
        # ----------------------------------------------------
        sys_group = QGroupBox("System & Obsidian Configuration")
        sys_layout = QVBoxLayout(sys_group)
        sys_layout.setSpacing(8)
        
        # Obsidian Vault Path
        vault_layout = QHBoxLayout()
        sys_layout.addLayout(vault_layout)
        vault_layout.addWidget(QLabel("Obsidian Vault Path:"))
        self.vault_edit = QLineEdit(self.settings_manager.get("obsidian_vault_path"))
        vault_layout.addWidget(self.vault_edit)
        vault_btn = QPushButton("Browse...")
        vault_btn.clicked.connect(self.browse_vault)
        vault_layout.addWidget(vault_btn)

        # Recording Limit
        limit_layout = QHBoxLayout()
        sys_layout.addLayout(limit_layout)
        limit_layout.addWidget(QLabel("Recording Limit (seconds):"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 300)
        # Check both nested and legacy key
        recording_limit = self.settings_manager.get("recording.hard_cap_seconds")
        if recording_limit is None:
            recording_limit = self.settings_manager.get("recording_limit_seconds") or 60
        self.limit_spin.setValue(recording_limit)
        limit_layout.addWidget(self.limit_spin)

        # Ollama Configuration
        ollama_layout = QHBoxLayout()
        sys_layout.addLayout(ollama_layout)
        ollama_layout.addWidget(QLabel("Ollama URL:"))
        self.ollama_edit = QLineEdit(self.settings_manager.get("ollama_url"))
        ollama_layout.addWidget(self.ollama_edit)

        # Models
        model_layout = QHBoxLayout()
        sys_layout.addLayout(model_layout)
        model_layout.addWidget(QLabel("Fast Model:"))
        self.fast_model_edit = QLineEdit(self.settings_manager.get("fast_model"))
        model_layout.addWidget(self.fast_model_edit)
        model_layout.addWidget(QLabel("Careful Model:"))
        self.careful_model_edit = QLineEdit(self.settings_manager.get("careful_model"))
        model_layout.addWidget(self.careful_model_edit)
        
        main_layout.addWidget(sys_group)

        # ----------------------------------------------------
        # Group 1.5: Audio Hardware Settings
        # ----------------------------------------------------
        audio_group = QGroupBox("Audio Input Configuration")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setSpacing(8)
        
        # Dropdown for input devices
        device_layout = QHBoxLayout()
        audio_layout.addLayout(device_layout)
        device_layout.addWidget(QLabel("Input Device:"))
        self.device_combo = QComboBox()
        device_layout.addWidget(self.device_combo)
        
        # Audio level progress bar
        level_layout = QHBoxLayout()
        audio_layout.addLayout(level_layout)
        level_layout.addWidget(QLabel("Audio Level:"))
        from PySide6.QtWidgets import QProgressBar
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setFixedHeight(12)
        level_layout.addWidget(self.level_bar)
        
        main_layout.addWidget(audio_group)

        # Query sound devices and populate dropdown
        import sounddevice as sd
        try:
            devices = sd.query_devices()
            input_devices = []
            for i, dev in enumerate(devices):
                if dev.get('max_input_channels', 0) > 0:
                    input_devices.append((i, dev))
        except Exception:
            input_devices = []

        current_idx = self.settings_manager.get("audio.device_index")
        self.device_mapping: list[Any] = []
        
        self.device_combo.addItem("System Default Input", None)
        self.device_mapping.append(None)
        
        selected_dropdown_idx = 0
        for idx, dev in input_devices:
            name = dev.get('name', f"Device {idx}")
            host_api = dev.get('hostapi', 0)
            try:
                api_name = sd.query_hostapis(host_api).get('name', '')
            except Exception:
                api_name = ''
            label = f"{idx}: {name} ({api_name})" if api_name else f"{idx}: {name}"
            
            self.device_combo.addItem(label, idx)
            self.device_mapping.append(idx)
            
            if current_idx is not None and int(current_idx) == idx:
                selected_dropdown_idx = len(self.device_mapping) - 1
                
        self.device_combo.setCurrentIndex(selected_dropdown_idx)

        if self.controller:
            self.controller.audio_level_updated.connect(self.update_audio_level)

        # ----------------------------------------------------
        # Group 2: Wake-Word Activation (openWakeWord)
        # ----------------------------------------------------
        wake_group = QGroupBox("Wake-Word Activation (openWakeWord)")
        wake_layout = QVBoxLayout(wake_group)
        wake_layout.setSpacing(8)
        
        # Engine Combobox
        engine_layout = QHBoxLayout()
        wake_layout.addLayout(engine_layout)
        engine_layout.addWidget(QLabel("Wake-Word Engine:"))
        self.wake_engine_combo = QComboBox()
        self.wake_engine_combo.addItems(["openwakeword", "manual_only"])
        self.wake_engine_combo.setCurrentText(self.settings_manager.get("wake_word.engine") or "openwakeword")
        engine_layout.addWidget(self.wake_engine_combo)
        
        # Enabled checkbox
        self.wake_enabled_chk = QCheckBox("Enable wake-phrase listening")
        self.wake_enabled_chk.setChecked(self.settings_manager.get("wake_word.enabled"))
        wake_layout.addWidget(self.wake_enabled_chk)

        # Trigger Phrase
        phrase_layout = QHBoxLayout()
        wake_layout.addLayout(phrase_layout)
        phrase_layout.addWidget(QLabel("Trigger Phrase:"))
        self.wake_phrase_edit = QLineEdit(self.settings_manager.get("wake_word.phrase") or "Joshua note")
        phrase_layout.addWidget(self.wake_phrase_edit)

        # Threshold Spinbox
        thresh_layout = QHBoxLayout()
        wake_layout.addLayout(thresh_layout)
        thresh_layout.addWidget(QLabel("Threshold (0.0 to 1.0):"))
        self.wake_threshold_spin = QDoubleSpinBox()
        self.wake_threshold_spin.setRange(0.0, 1.0)
        self.wake_threshold_spin.setSingleStep(0.05)
        self.wake_threshold_spin.setValue(self.settings_manager.get("wake_word.threshold") or 0.5)
        thresh_layout.addWidget(self.wake_threshold_spin)

        # ONNX Model Path
        onnx_layout = QHBoxLayout()
        wake_layout.addLayout(onnx_layout)
        onnx_layout.addWidget(QLabel("ONNX Model Path:"))
        self.wake_model_edit = QLineEdit(self.settings_manager.get("wake_word.model_path") or "")
        onnx_layout.addWidget(self.wake_model_edit)
        onnx_btn = QPushButton("Browse...")
        onnx_btn.clicked.connect(self.browse_onnx_model)
        onnx_layout.addWidget(onnx_btn)

        main_layout.addWidget(wake_group)

        # ----------------------------------------------------
        # Group 3: Spoken Voice Controls (Vosk)
        # ----------------------------------------------------
        cmd_group = QGroupBox("Spoken Commands (Vosk)")
        cmd_layout = QVBoxLayout(cmd_group)
        cmd_layout.setSpacing(8)

        # Enabled checkbox
        self.cmd_enabled_chk = QCheckBox("Enable spoken save/cancel commands")
        self.cmd_enabled_chk.setChecked(self.settings_manager.get("spoken_commands.enabled"))
        cmd_layout.addWidget(self.cmd_enabled_chk)

        # Model Path
        vosk_layout = QHBoxLayout()
        cmd_layout.addLayout(vosk_layout)
        vosk_layout.addWidget(QLabel("Vosk Model Directory:"))
        self.cmd_model_edit = QLineEdit(self.settings_manager.get("spoken_commands.model_path") or "")
        vosk_layout.addWidget(self.cmd_model_edit)
        vosk_btn = QPushButton("Browse...")
        vosk_btn.clicked.connect(self.browse_vosk_model)
        cmd_layout.addWidget(vosk_btn)

        # Grammar keywords
        grammar_layout = QHBoxLayout()
        cmd_layout.addLayout(grammar_layout)
        grammar_layout.addWidget(QLabel("Grammar Keywords:"))
        keywords_list = self.settings_manager.get("spoken_commands.grammar_keywords") or ["save", "cancel", "stop", "discard"]
        self.cmd_keywords_edit = QLineEdit(", ".join(keywords_list))
        grammar_layout.addWidget(self.cmd_keywords_edit)

        main_layout.addWidget(cmd_group)

        # ----------------------------------------------------
        # Group 4: Agent Dispatch (Telegram)
        # ----------------------------------------------------
        agent_group = QGroupBox("Agent Dispatch (Telegram)")
        agent_layout = QVBoxLayout(agent_group)
        agent_layout.setSpacing(8)

        # Enabled checkbox
        self.agent_enabled_chk = QCheckBox("Enable external agent task dispatching")
        self.agent_enabled_chk.setChecked(self.settings_manager.get("agents.enabled"))
        agent_layout.addWidget(self.agent_enabled_chk)

        # Telegram Token
        token_layout = QHBoxLayout()
        agent_layout.addLayout(token_layout)
        token_layout.addWidget(QLabel("Telegram Bot Token:"))
        self.agent_token_edit = QLineEdit(self.settings_manager.get("agents.telegram_token") or "")
        self.agent_token_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        token_layout.addWidget(self.agent_token_edit)

        # Default Agent Dropdown
        default_layout = QHBoxLayout()
        agent_layout.addLayout(default_layout)
        default_layout.addWidget(QLabel("Default Agent Target:"))
        self.agent_default_combo = QComboBox()
        self.agent_default_combo.addItems(["hermes", "openclaw"])
        current_default = self.settings_manager.get("agents.default_agent") or "hermes"
        self.agent_default_combo.setCurrentText(current_default)
        default_layout.addWidget(self.agent_default_combo)

        # Hermes Group Settings
        hermes_box = QGroupBox("Hermes Agent")
        hermes_layout = QVBoxLayout(hermes_box)
        hermes_layout.setSpacing(6)
        
        h_chat_layout = QHBoxLayout()
        hermes_layout.addLayout(h_chat_layout)
        h_chat_layout.addWidget(QLabel("Telegram Chat ID:"))
        self.hermes_chat_edit = QLineEdit(self.settings_manager.get("agents.agents.hermes.chat_id") or "")
        h_chat_layout.addWidget(self.hermes_chat_edit)
        
        self.hermes_enabled_chk = QCheckBox("Enable Hermes agent")
        self.hermes_enabled_chk.setChecked(self.settings_manager.get("agents.agents.hermes.enabled"))
        hermes_layout.addWidget(self.hermes_enabled_chk)
        
        agent_layout.addWidget(hermes_box)

        # OpenClaw Group Settings
        openclaw_box = QGroupBox("OpenClaw Agent")
        openclaw_layout = QVBoxLayout(openclaw_box)
        openclaw_layout.setSpacing(6)
        
        o_chat_layout = QHBoxLayout()
        openclaw_layout.addLayout(o_chat_layout)
        o_chat_layout.addWidget(QLabel("Telegram Chat ID:"))
        self.openclaw_chat_edit = QLineEdit(self.settings_manager.get("agents.agents.openclaw.chat_id") or "")
        o_chat_layout.addWidget(self.openclaw_chat_edit)
        
        self.openclaw_enabled_chk = QCheckBox("Enable OpenClaw agent")
        self.openclaw_enabled_chk.setChecked(self.settings_manager.get("agents.agents.openclaw.enabled"))
        openclaw_layout.addWidget(self.openclaw_enabled_chk)
        
        agent_layout.addWidget(openclaw_box)
        main_layout.addWidget(agent_group)

        # ----------------------------------------------------
        # Group 4.5: External Outbound Sharing Configuration
        # ----------------------------------------------------
        broker_group = QGroupBox("External Outbound Sharing Configuration")
        broker_layout = QVBoxLayout(broker_group)
        broker_layout.setSpacing(8)

        # Sharing Mode Combo
        mode_layout = QHBoxLayout()
        broker_layout.addLayout(mode_layout)
        mode_layout.addWidget(QLabel("Sharing Mode:"))
        self.sharing_mode_combo = QComboBox()
        self.sharing_mode_combo.addItem("Keep everything on this device (Off)", "off")
        self.sharing_mode_combo.addItem("Automatically send safe items (Safe Auto)", "safe_auto")
        self.sharing_mode_combo.addItem("Review every item before sending (Review All)", "review_all")
        self.sharing_mode_combo.addItem("Automatically send, pause on high risk (Trusted Auto)", "trusted_auto")

        current_mode = self.settings_manager.external_sharing_mode()
        self._set_sharing_mode_combo(current_mode)
        self._previous_mode_idx = self.sharing_mode_combo.currentIndex()
        self.sharing_mode_combo.currentIndexChanged.connect(self._on_sharing_mode_changed)
        mode_layout.addWidget(self.sharing_mode_combo)

        # Transcript Inclusion Checkbox
        self.include_transcript_chk = QCheckBox("Include full transcript in outbound payloads")
        self.include_transcript_chk.setChecked(bool(self.settings_manager.get("external_agent.include_full_transcript", False)))
        broker_layout.addWidget(self.include_transcript_chk)

        # Default Item Kind & Target Agent
        kind_layout = QHBoxLayout()
        broker_layout.addLayout(kind_layout)
        kind_layout.addWidget(QLabel("Default Item Kind:"))
        self.default_kind_combo = QComboBox()
        self.default_kind_combo.addItems(["record_only", "agent_task"])
        self.default_kind_combo.setCurrentText(self.settings_manager.get("external_agent.default_item_kind", "record_only"))
        kind_layout.addWidget(self.default_kind_combo)

        kind_layout.addWidget(QLabel("Default Target Agent:"))
        self.target_agent_combo = QComboBox()
        self.target_agent_combo.addItems(["openclaw"])
        self.target_agent_combo.setCurrentText(self.settings_manager.get("external_agent.target_agent_default", "openclaw"))
        kind_layout.addWidget(self.target_agent_combo)

        # High-risk pause checkbox
        self.pause_high_risk_chk = QCheckBox("Pause trusted mode on high-risk findings")
        self.pause_high_risk_chk.setChecked(bool(self.settings_manager.get("external_agent.trusted_pause_on_high_risk", True)))
        broker_layout.addWidget(self.pause_high_risk_chk)

        # Endpoint URL
        endpoint_layout = QHBoxLayout()
        broker_layout.addLayout(endpoint_layout)
        endpoint_layout.addWidget(QLabel("Endpoint URL:"))
        self.broker_endpoint_edit = QLineEdit(self.settings_manager.get("external_agent.endpoint_url") or "")
        endpoint_layout.addWidget(self.broker_endpoint_edit)

        # Outbox stats display label
        try:
            from app.destinations.external_outbox import ExternalOutbox
            stats = ExternalOutbox().get_stats()
        except Exception:
            stats = {"pending": 0, "sent": 0, "dead_letter": 0}
            
        pending = stats.get("pending", 0) + stats.get("sending", 0)
        sent = stats.get("sent", 0) + stats.get("completed", 0) + stats.get("processing", 0)
        stuck = stats.get("dead_letter", 0)

        self.outbox_status_label = QLabel(
            f"Local Outbox: {pending} pending, {sent} sent, {stuck} stuck"
        )
        self.outbox_status_label.setStyleSheet("color: #555; font-size: 11px;")
        
        # Retrying/Viewing outbox layout
        retry_layout = QHBoxLayout()
        retry_layout.addWidget(self.outbox_status_label)

        self.open_review_queue_btn = QPushButton("Review Queue")
        self.open_review_queue_btn.clicked.connect(self.open_review_queue)
        retry_layout.addWidget(self.open_review_queue_btn)
        self.update_review_queue_button_label()

        self.retry_outbox_btn = QPushButton("Retry Outbox Now")
        self.retry_outbox_btn.clicked.connect(self.retry_outbox_now)
        retry_layout.addWidget(self.retry_outbox_btn)

        self.view_outbox_btn = QPushButton("View Outbox")
        self.view_outbox_btn.clicked.connect(self.view_outbox)
        retry_layout.addWidget(self.view_outbox_btn)

        broker_layout.addLayout(retry_layout)

        if self.controller:
            self.controller.outbox_processed.connect(self.refresh_outbox_label)
            
        # Timer to refresh outbox status label automatically
        self.outbox_refresh_timer = QTimer(self)
        self.outbox_refresh_timer.timeout.connect(self.refresh_outbox_label)
        self.outbox_refresh_timer.start(10000) # every 10 seconds
        
        main_layout.addWidget(broker_group)

        # ----------------------------------------------------
        # Save Button
        # ----------------------------------------------------
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet("font-weight: bold; padding: 10px; background-color: #2b5c8f; color: white; border-radius: 4px;")
        save_btn.clicked.connect(self.save_all)
        main_layout.addWidget(save_btn)

    def browse_vault(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Obsidian Vault Directory")
        if dir_path:
            self.vault_edit.setText(dir_path)

    def browse_onnx_model(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select openWakeWord ONNX Model", "", "ONNX Models (*.onnx)"
        )
        if file_path:
            self.wake_model_edit.setText(file_path)

    def browse_vosk_model(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Vosk Model Directory")
        if dir_path:
            self.cmd_model_edit.setText(dir_path)

    def update_audio_level(self, peak_value: float) -> None:
        val = int((peak_value / 32768.0) * 100)
        self.level_bar.setValue(val)

    def save_all(self) -> None:
        vault_path = self.vault_edit.text().strip()
        limit_sec = self.limit_spin.value()
        ollama_url = self.ollama_edit.text().strip()
        fast_model = self.fast_model_edit.text().strip()
        careful_model = self.careful_model_edit.text().strip()
        
        wake_engine = self.wake_engine_combo.currentText()
        wake_enabled = self.wake_enabled_chk.isChecked()
        wake_phrase = self.wake_phrase_edit.text().strip()
        wake_threshold = self.wake_threshold_spin.value()
        wake_model = self.wake_model_edit.text().strip()
        
        cmd_enabled = self.cmd_enabled_chk.isChecked()
        cmd_model = self.cmd_model_edit.text().strip()
        cmd_keywords_str = self.cmd_keywords_edit.text().strip()
        cmd_keywords = [k.strip() for k in cmd_keywords_str.split(",") if k.strip()]

        # Graceful model validation dialogues
        if wake_enabled and wake_engine == "openwakeword":
            if not wake_model or not Path(wake_model).exists():
                confirm = QMessageBox.question(
                    self,
                    "Wake-Word Model Missing",
                    "The selected openWakeWord ONNX model file does not exist.\n\n"
                    "Would you like to fallback to manual-only mode instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if confirm == QMessageBox.StandardButton.Yes:
                    self.wake_engine_combo.setCurrentText("manual_only")
                    self.wake_enabled_chk.setChecked(False)
                    wake_engine = "manual_only"
                    wake_enabled = False
                else:
                    return  # Stop save, let user fix it

        if cmd_enabled:
            if not cmd_model or not Path(cmd_model).is_dir():
                confirm = QMessageBox.question(
                    self,
                    "Vosk Model Missing",
                    "The selected Vosk model directory does not exist or is invalid.\n\n"
                    "Would you like to save and disable spoken commands for now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if confirm == QMessageBox.StandardButton.Yes:
                    self.cmd_enabled_chk.setChecked(False)
                    cmd_enabled = False
                else:
                    return  # Stop save, let user fix it

        # Save to Settings Manager
        self.settings_manager.set("obsidian_vault_path", vault_path)
        self.settings_manager.set("recording_limit_seconds", limit_sec)
        self.settings_manager.set("recording.hard_cap_seconds", limit_sec)
        self.settings_manager.set("ollama_url", ollama_url)
        self.settings_manager.set("fast_model", fast_model)
        self.settings_manager.set("careful_model", careful_model)
        
        self.settings_manager.set("wake_word.engine", wake_engine)
        self.settings_manager.set("wake_word.enabled", wake_enabled)
        self.settings_manager.set("wake_word.phrase", wake_phrase)
        self.settings_manager.set("wake_word.threshold", wake_threshold)
        self.settings_manager.set("wake_word.model_path", wake_model)
        
        self.settings_manager.set("spoken_commands.enabled", cmd_enabled)
        self.settings_manager.set("spoken_commands.model_path", cmd_model)
        self.settings_manager.set("spoken_commands.grammar_keywords", cmd_keywords)

        # Save Audio Device Index
        selected_idx = self.device_combo.currentIndex()
        if selected_idx >= 0 and selected_idx < len(self.device_mapping):
            dev_idx = self.device_mapping[selected_idx]
            self.settings_manager.set("audio.device_index", dev_idx)

        # Save Agent settings
        self.settings_manager.set("agents.enabled", self.agent_enabled_chk.isChecked())
        self.settings_manager.set("agents.telegram_token", self.agent_token_edit.text().strip())
        self.settings_manager.set("agents.default_agent", self.agent_default_combo.currentText())
        self.settings_manager.set("agents.agents.hermes.chat_id", self.hermes_chat_edit.text().strip())
        self.settings_manager.set("agents.agents.hermes.enabled", self.hermes_enabled_chk.isChecked())
        self.settings_manager.set("agents.agents.openclaw.chat_id", self.openclaw_chat_edit.text().strip())
        self.settings_manager.set("agents.agents.openclaw.enabled", self.openclaw_enabled_chk.isChecked())

        # Save External Sharing Settings
        selected_mode = self.sharing_mode_combo.currentData() or "off"
        self.settings_manager.set("external_agent.sharing_mode", selected_mode)
        self.settings_manager.set("external_agent.enabled", selected_mode != "off")
        self.settings_manager.set("external_agent.include_full_transcript", self.include_transcript_chk.isChecked())
        self.settings_manager.set("external_agent.default_item_kind", self.default_kind_combo.currentText())
        self.settings_manager.set("external_agent.target_agent_default", self.target_agent_combo.currentText())
        self.settings_manager.set("external_agent.trusted_pause_on_high_risk", self.pause_high_risk_chk.isChecked())
        self.settings_manager.set("external_agent.endpoint_url", self.broker_endpoint_edit.text().strip())

        if self.controller:
            try:
                self.controller.reload_settings()
            except Exception:
                import traceback
                QMessageBox.critical(self, "Reload Error", f"Failed to reload settings:\n{traceback.format_exc()}")
                return

        QMessageBox.information(self, "Success", "Settings saved successfully.")
        self.close()

    def _set_sharing_mode_combo(self, mode: str) -> None:
        idx = self.sharing_mode_combo.findData(mode)
        if idx >= 0:
            self.sharing_mode_combo.setCurrentIndex(idx)

    def _on_sharing_mode_changed(self, index: int) -> None:
        selected_mode = self.sharing_mode_combo.itemData(index)
        if selected_mode == "trusted_auto":
            confirm = QMessageBox.warning(
                self,
                "TRUSTED AUTOMATIC MODE WARNING",
                "Trusted Auto mode automatically transmits captures externally without per-item human review.\n\n"
                "Are you sure you want to enable Trusted Auto mode?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                self.sharing_mode_combo.blockSignals(True)
                self.sharing_mode_combo.setCurrentIndex(self._previous_mode_idx)
                self.sharing_mode_combo.blockSignals(False)
                return
        self._previous_mode_idx = index

    def open_review_queue(self) -> None:
        """Opens the outbound review queue dialog."""
        from app.destinations.outbound_review_store import OutboundReviewStore
        from app.ui.outbound_review_dialog import OutboundReviewDialog
        store = OutboundReviewStore()
        dialog = OutboundReviewDialog(store, settings_manager=self.settings_manager, parent=self)
        dialog.exec()
        self.update_review_queue_button_label()


    def update_review_queue_button_label(self) -> None:
        """Updates the pending count badge on the Review Queue button."""
        try:
            from app.destinations.outbound_review_store import OutboundReviewStore
            awaiting = len(OutboundReviewStore().get_awaiting_review())
            self.open_review_queue_btn.setText(f"Review Queue ({awaiting} pending)")
        except Exception:
            self.open_review_queue_btn.setText("Review Queue")

    def retry_outbox_now(self) -> None:
        """Trigger outbox transmission retry manually from settings."""
        if self.controller:
            self.controller._retry_pending_outbox(manual=True)
            QMessageBox.information(
                self, 
                "Outbox Retry Started", 
                "Retry and status reconciliation started in the background. The counters will refresh automatically."
            )

    def view_outbox(self) -> None:
        """Opens the outbox task manager dialog."""
        from app.ui.outbox_dialog import OutboxDialog
        dialog = OutboxDialog(self)
        dialog.exec()
        self.refresh_outbox_label()

    def refresh_outbox_label(self) -> None:
        """Refreshes the outbox stats display label from the database state."""
        try:
            from app.destinations.external_outbox import ExternalOutbox
            stats = ExternalOutbox().get_stats()
            pending = stats.get("pending", 0) + stats.get("sending", 0)
            sent = stats.get("sent", 0) + stats.get("completed", 0) + stats.get("processing", 0)
            stuck = stats.get("dead_letter", 0)
            self.outbox_status_label.setText(
                f"Local Outbox: {pending} pending, {sent} sent, {stuck} stuck"
            )
        except Exception:
            pass

def prompt_first_launch_vault_picker(settings_manager: SettingsManager) -> str:
    """Checks if vault path is configured. If not, shows a folder dialog picker."""
    current_path = settings_manager.get("obsidian_vault_path")
    if current_path and Path(current_path).exists():
        return str(current_path)

    # Need a temporary QApplication to show dialog if one doesn't exist
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    QMessageBox.information(
        None,
        "Welcome",
        "Welcome to Classroom Voice Notes!\n\nPlease select your Obsidian Vault directory to get started."
    )
    
    dir_path = QFileDialog.getExistingDirectory(None, "Select Obsidian Vault Directory")
    if dir_path:
        settings_manager.set("obsidian_vault_path", dir_path)
    else:
        QMessageBox.critical(None, "Error", "An Obsidian vault path is required to run this application.")
        
    return str(dir_path)
