from typing import Any
from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame, QMenu, QApplication
from PySide6.QtGui import QMouseEvent

class RecordingIndicator(QWidget):
    open_settings_requested = Signal()
    generate_daily_summary_requested = Signal()
    rebuild_index_requested = Signal()
    retry_outbox_requested = Signal()
    start_recording_requested = Signal()
    save_recording_requested = Signal()
    cancel_recording_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.drag_position: QPoint = QPoint()
        self.state: str = "IDLE"
        self.elapsed_seconds: float = 0.0
        
        # Flash timer for recording animation
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.toggle_indicator_visibility)
        self.indicator_visible = True
        
        self.init_ui()

    def init_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Container frame for styling
        self.frame = QFrame(self)
        self.frame.setObjectName("containerFrame")
        frame_layout = QHBoxLayout(self.frame)
        frame_layout.setContentsMargins(8, 4, 8, 4)
        frame_layout.setSpacing(6)

        # Status Dot (Visual Indicator)
        self.dot = QFrame(self.frame)
        self.dot.setFixedSize(10, 10)
        self.dot.setObjectName("statusDot")
        frame_layout.addWidget(self.dot)

        # Status Label
        self.label = QLabel("Idle", self.frame)
        self.label.setObjectName("statusLabel")
        frame_layout.addWidget(self.label)

        layout.addWidget(self.frame)

        self.apply_style()

    def apply_style(self) -> None:
        self.setStyleSheet("""
            #containerFrame {
                background-color: rgba(30, 30, 30, 220);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
            }
            #statusLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: bold;
            }
            #statusDot {
                border-radius: 5px;
            }
        """)

    def set_state(self, state: str) -> None:
        self.state = state.upper()
        self.elapsed_seconds = 0.0
        
        if self.state in ("IDLE", "IDLE_LISTENING"):
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #34C759; border-radius: 5px;") # Green
            self.label.setText("Listening")
        elif self.state == "RECORDING":
            self.dot.setStyleSheet("background-color: #FF3B30; border-radius: 5px;") # Red
            self.label.setText("Recording 00:00")
            if not self.flash_timer.isActive():
                self.flash_timer.start(500)
        elif self.state == "TRANSCRIBING":
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #FFCC00; border-radius: 5px;") # Yellow
            self.label.setText("Transcribing...")
        elif self.state == "CLASSIFYING":
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #FFCC00; border-radius: 5px;") # Yellow
            self.label.setText("Classifying...")
        elif self.state in ("SAVING", "ROUTING", "WRITING_OUTPUT"):
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #FFCC00; border-radius: 5px;") # Yellow
            self.label.setText("Saving Note...")
        elif self.state == "ERROR":
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #FF9500; border-radius: 5px;") # Orange
            self.label.setText("Pipeline Error")
        else:
            self.flash_timer.stop()
            self.dot.setVisible(True)
            self.dot.setStyleSheet("background-color: #FFCC00; border-radius: 5px;")
            self.label.setText("Processing...")

    def update_recording_time(self, seconds: float) -> None:
        if self.state == "RECORDING":
            self.elapsed_seconds = seconds
            mins = int(seconds) // 60
            secs = int(seconds) % 60
            self.label.setText(f"Recording {mins:02d}:{secs:02d}")

    def toggle_indicator_visibility(self) -> None:
        self.indicator_visible = not self.indicator_visible
        self.dot.setVisible(self.indicator_visible)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_settings_requested.emit()
            event.accept()

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)

        start_action = None
        save_action = None
        cancel_action = None

        if self.state == "RECORDING":
            save_action = menu.addAction("Save Recording")
            cancel_action = menu.addAction("Cancel Recording")
            menu.addSeparator()
        else:
            start_action = menu.addAction("Start Recording")
            menu.addSeparator()

        settings_action = menu.addAction("Open Settings")
        summary_action = menu.addAction("Generate Daily Summary")
        index_action = menu.addAction("Rebuild Student Index")
        
        # Query local outbox stats
        try:
            from app.destinations.external_outbox import ExternalOutbox
            stats = ExternalOutbox().get_stats()
            pending = stats.get("pending", 0)
            sending = stats.get("sending", 0)
            dead_letter = stats.get("dead_letter", 0)
            
            menu.addSeparator()
            if pending > 0 or sending > 0:
                outbox_text = f"Outbox: {pending} pending"
                if sending > 0:
                    outbox_text += f" ({sending} sending)"
                menu.addSection(outbox_text)
                retry_action = menu.addAction("Retry Pending Tasks")
            elif dead_letter > 0:
                menu.addSection(f"Outbox: {dead_letter} stuck")
                retry_action = menu.addAction("Retry Stuck Tasks")
            else:
                menu.addSection("Outbox: Empty/Sent")
                retry_action = None
        except Exception:
            retry_action = None

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        
        action = menu.exec(event.globalPos())
        if start_action and action == start_action:
            self.start_recording_requested.emit()
        elif save_action and action == save_action:
            self.save_recording_requested.emit()
        elif cancel_action and action == cancel_action:
            self.cancel_recording_requested.emit()
        elif action == settings_action:
            self.open_settings_requested.emit()
        elif action == summary_action:
            self.generate_daily_summary_requested.emit()
        elif action == index_action:
            self.rebuild_index_requested.emit()
        elif retry_action and action == retry_action:
            self.retry_outbox_requested.emit()
        elif action == quit_action:
            QApplication.quit()
