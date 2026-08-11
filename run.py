import sys
import faulthandler
import traceback
from pathlib import Path

# Write C-level crash traces to a log file
_crash_log = open(Path(__file__).parent / "crash.log", "w", buffering=1)
faulthandler.enable(file=_crash_log)

def _excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(f"UNCAUGHT EXCEPTION:\n{msg}", file=_crash_log, flush=True)
    print(f"UNCAUGHT EXCEPTION:\n{msg}", flush=True)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt
from app.config.settings import SettingsManager
from app.ui.main_window import MainWindow, prompt_first_launch_vault_picker
from app.controller import AppController
from app.ui.recording_indicator import RecordingIndicator

def build_tray_icon(state: str) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    color_map = {
        "IDLE": "#34C759",          # Green
        "IDLE_LISTENING": "#34C759",# Green
        "RECORDING": "#FF3B30",     # Red
        "TRANSCRIBING": "#FFCC00",  # Yellow
        "CLASSIFYING": "#FFCC00",   # Yellow
        "SAVING": "#FFCC00",        # Yellow
        "ERROR": "#FF9500"          # Orange
    }
    hex_color = color_map.get(state.upper(), "#34C759")
    
    painter.setBrush(QColor(30, 30, 30))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    
    painter.setBrush(QColor(hex_color))
    painter.drawEllipse(6, 6, 20, 20)
    
    painter.end()
    return QIcon(pixmap)

def main() -> None:
    # 1. Initialise PySide6 Application
    app = QApplication(sys.argv)
    
    # 2. Initialise Settings Manager
    settings_manager = SettingsManager()
    
    # 3. Check first-launch folder picker
    vault_path = prompt_first_launch_vault_picker(settings_manager)
    if not vault_path:
        print("Initialisation cancelled: An Obsidian vault path is required.")
        sys.exit(0)
        
    print(f"Obsidian Vault Path configured: {vault_path}", flush=True)

    # 4. Initialise AppController and RecordingIndicator
    print("Creating AppController...", flush=True)
    controller = AppController(settings_manager)
    print("AppController created OK", flush=True)
    
    indicator = RecordingIndicator()
    
    # Wire controller signals to indicator slots
    controller.state_changed.connect(indicator.set_state)
    controller.recording_time_updated.connect(indicator.update_recording_time)
    
    # Wire indicator context menu requests to controller slots
    indicator.generate_daily_summary_requested.connect(controller.generate_daily_summary)
    indicator.rebuild_index_requested.connect(controller.rebuild_student_index)
    indicator.retry_outbox_requested.connect(lambda: controller._retry_pending_outbox(manual=True))
    indicator.start_recording_requested.connect(controller.start_recording)
    indicator.save_recording_requested.connect(controller.stop_and_save)
    indicator.cancel_recording_requested.connect(controller.cancel_recording)
    controller.error_occurred.connect(lambda msg: indicator.set_state("ERROR"))

    # Select primary active screen
    target_screen = app.primaryScreen()
    if not target_screen and app.screens():
        target_screen = app.screens()[0]

    # Set initial state and position floating indicator in top-right of target screen
    indicator.set_state(controller.state)
    indicator.show()
    indicator.adjustSize()

    if target_screen:
        avail = target_screen.availableGeometry()
        margin = 20
        x = avail.x() + avail.width() - indicator.width() - margin
        y = avail.y() + margin
        indicator.move(x, y)

    app.setQuitOnLastWindowClosed(False)

    indicator.raise_()
    indicator.activateWindow()
    print("Indicator shown OK", flush=True)

    # 5. Open the Settings Main Window GUI, passing the controller
    window = MainWindow(settings_manager, controller)
    if target_screen:
        avail = target_screen.availableGeometry()
        x = avail.x() + (avail.width() - 550) // 2
        y = avail.y() + (avail.height() - 650) // 2
        window.move(x, y)
    window.show()
    window.raise_()
    window.activateWindow()
    print("MainWindow shown OK", flush=True)

    # 6. System Tray Icon Setup
    tray_icon = QSystemTrayIcon(build_tray_icon(controller.state), app)
    tray_icon.setToolTip(f"Classroom Voice Notes: {controller.state}")

    tray_menu = QMenu()
    show_indicator_act = tray_menu.addAction("Show Recording Indicator")
    show_settings_act = tray_menu.addAction("Open Settings")
    tray_menu.addSeparator()
    start_rec_act = tray_menu.addAction("Start Recording")
    save_rec_act = tray_menu.addAction("Save Recording")
    cancel_rec_act = tray_menu.addAction("Cancel Recording")
    tray_menu.addSeparator()
    summary_act = tray_menu.addAction("Generate Daily Summary")
    index_act = tray_menu.addAction("Rebuild Student Index")
    tray_menu.addSeparator()
    quit_act = tray_menu.addAction("Quit")

    tray_icon.setContextMenu(tray_menu)

    def _update_tray_state(state: str) -> None:
        tray_icon.setIcon(build_tray_icon(state))
        tray_icon.setToolTip(f"Classroom Voice Notes: {state}")
        
        titles = {
            "IDLE": "Classroom Voice Notes",
            "IDLE_LISTENING": "Classroom Voice Notes: Listening",
            "RECORDING": "Recording Started",
            "TRANSCRIBING": "Transcribing Voice Note",
            "CLASSIFYING": "Classifying Voice Note",
            "SAVING": "Saving Note to Vault",
            "ERROR": "Classroom Voice Notes Error"
        }
        messages = {
            "IDLE": "App is idle and ready in system tray.",
            "IDLE_LISTENING": "Listening for voice recording hotkey...",
            "RECORDING": "Recording audio...",
            "TRANSCRIBING": "Converting audio recording to text...",
            "CLASSIFYING": "Analyzing note content with AI...",
            "SAVING": "Writing voice note to Obsidian vault...",
            "ERROR": "An error occurred in Classroom Voice Notes."
        }
        title = titles.get(state.upper(), "Classroom Voice Notes")
        message = messages.get(state.upper(), f"Status: {state}")
        icon_type = QSystemTrayIcon.MessageIcon.Warning if state.upper() == "ERROR" else QSystemTrayIcon.MessageIcon.Information
        tray_icon.showMessage(title, message, icon_type, 3000)

    controller.state_changed.connect(_update_tray_state)
    controller.error_occurred.connect(
        lambda msg: tray_icon.showMessage("Classroom Voice Notes Error", msg, QSystemTrayIcon.MessageIcon.Critical, 5000)
    )

    def _on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            window.show()
            window.raise_()
            window.activateWindow()
            indicator.show()
            indicator.raise_()

    tray_icon.activated.connect(_on_tray_activated)

    show_indicator_act.triggered.connect(lambda: (indicator.show(), indicator.raise_(), indicator.activateWindow()))
    show_settings_act.triggered.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
    start_rec_act.triggered.connect(controller.start_recording)
    save_rec_act.triggered.connect(controller.stop_and_save)
    cancel_rec_act.triggered.connect(controller.cancel_recording)
    summary_act.triggered.connect(controller.generate_daily_summary)
    index_act.triggered.connect(controller.rebuild_student_index)
    quit_act.triggered.connect(app.quit)

    tray_icon.show()
    tray_icon.showMessage(
        "Classroom Voice Notes Running",
        "App initialized. Listening in background and system tray icon ready.",
        QSystemTrayIcon.MessageIcon.Information,
        4000
    )
    print("System Tray Icon created OK", flush=True)

    # Double-clicking the indicator re-opens the settings window
    indicator.open_settings_requested.connect(window.show)
    indicator.open_settings_requested.connect(window.raise_)

    # Ensure clean thread/stream shutdown before Python garbage-collects everything
    app.aboutToQuit.connect(controller.cleanup)

    # 6. Start QApplication event loop
    print("Starting event loop...", flush=True)
    _crash_log.flush()
    result = app.exec()
    print(f"Event loop exited with code: {result}", flush=True)
    sys.exit(result)

if __name__ == "__main__":
    main()
