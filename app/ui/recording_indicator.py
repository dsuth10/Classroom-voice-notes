from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame, QMenu
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

class RecordingIndicator(QWidget):
    open_settings_requested = Signal()

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
        self.setFixedSize(160, 45)
        
        # Style sheet for dark glassmorphic card design
        self.background_frame = QFrame(self)
        self.background_frame.setGeometry(0, 0, 160, 45)
        self.background_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 210);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
            }
        """)
        
        layout = QHBoxLayout(self.background_frame)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Visual flashing dot
        self.dot = QFrame()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet("background-color: rgb(150, 150, 150); border-radius: 6px;")
        layout.addWidget(self.dot)
        
        # State label
        self.label = QLabel("Idle Listening")
        self.label.setStyleSheet("color: white; font-family: Outfit, Inter, Arial; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.label)
        
        self.set_state("IDLE")

    def set_state(self, state: str) -> None:
        """Transitions widget state and updates UI immediately."""
        self.state = state.upper()
        self.indicator_visible = True
        self.dot.setVisible(True)
        
        if self.state in ("IDLE", "IDLE_LISTENING"):
            self.flash_timer.stop()
            self.label.setText("Idle Listening")
            self.dot.setStyleSheet("background-color: rgb(120, 120, 120); border-radius: 6px;")
        elif self.state == "RECORDING":
            self.elapsed_seconds = 0.0
            self.label.setText("Recording... 0s")
            self.dot.setStyleSheet("background-color: rgb(0, 220, 0); border-radius: 6px;")
            self.flash_timer.start(500)  # flash every 500ms
        elif self.state == "TRANSCRIBING":
            self.flash_timer.stop()
            self.label.setText("Transcribing...")
            self.dot.setStyleSheet("background-color: rgb(220, 180, 0); border-radius: 6px;")
        elif self.state == "CLASSIFYING":
            self.flash_timer.stop()
            self.label.setText("Classifying...")
            self.dot.setStyleSheet("background-color: rgb(220, 100, 0); border-radius: 6px;")
        elif self.state in ("SAVING", "ROUTING"):
            self.flash_timer.stop()
            self.label.setText("Saving Note...")
            self.dot.setStyleSheet("background-color: rgb(0, 120, 220); border-radius: 6px;")
        elif self.state == "ERROR":
            self.flash_timer.stop()
            self.label.setText("Pipeline Error")
            self.dot.setStyleSheet("background-color: rgb(220, 0, 0); border-radius: 6px;")

    def update_recording_time(self, elapsed: float) -> None:
        """Updates duration counter and visual warning cap."""
        self.elapsed_seconds = elapsed
        self.label.setText(f"Recording... {int(elapsed)}s")
        
        # Warning: pulse red if approaching the 60s cap (e.g. >= 50s)
        if elapsed >= 50.0:
            # Flashes red/black rapidly
            self.dot.setStyleSheet("background-color: rgb(255, 0, 0); border-radius: 6px;")
            self.flash_timer.setInterval(200)  # faster warning flash
        else:
            self.flash_timer.setInterval(500)

    def toggle_indicator_visibility(self) -> None:
        """Toggles the visibility of the indicator dot to create flashing effect."""
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

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        settings_action = menu.addAction("Open Settings")
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        action = menu.exec(event.globalPos())
        if action == settings_action:
            self.open_settings_requested.emit()
        elif action == quit_action:
            QApplication.quit()
