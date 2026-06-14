import sys
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app.ui.recording_indicator import RecordingIndicator

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app

def test_recording_indicator_flags(qapp: QApplication) -> None:
    """Verifies that the indicator has the correct frameless and always-on-top window flags."""
    indicator = RecordingIndicator()
    flags = indicator.windowFlags()
    
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.Tool)
    indicator.close()

def test_recording_indicator_states(qapp: QApplication) -> None:
    """Verifies that the indicator updates its label and visual style depending on state."""
    indicator = RecordingIndicator()
    
    # Test idle/recording transitions
    indicator.set_state("IDLE")
    assert "listening" in indicator.label.text().lower()
    
    indicator.set_state("RECORDING")
    assert "recording" in indicator.label.text().lower()
    
    indicator.set_state("TRANSCRIBING")
    assert "transcribing" in indicator.label.text().lower()
    
    indicator.close()
