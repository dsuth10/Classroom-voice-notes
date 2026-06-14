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

from PySide6.QtWidgets import QApplication
from app.config.settings import SettingsManager
from app.ui.main_window import MainWindow, prompt_first_launch_vault_picker
from app.controller import AppController
from app.ui.recording_indicator import RecordingIndicator

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
    
    # Set initial state and position indicator in top-right of screen
    indicator.set_state(controller.state)
    screen = app.primaryScreen()
    if screen:
        screen_geom = screen.geometry()
        margin = 20
        x = screen_geom.width() - indicator.width() - margin
        y = margin
        indicator.move(x, y)
    # Don't quit when Settings window closes — the floating indicator owns the app lifetime
    app.setQuitOnLastWindowClosed(False)

    indicator.show()
    print("Indicator shown OK", flush=True)

    # 5. Open the Settings Main Window GUI, passing the controller
    window = MainWindow(settings_manager, controller)
    window.show()
    print("MainWindow shown OK", flush=True)

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
