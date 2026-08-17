"""Unit tests for Global Hotkey Parser and Worker."""

import os
from unittest.mock import MagicMock, patch
import pytest

from app.utils.global_hotkey import (
    GlobalHotkeyWorker,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    parse_hotkey_sequence,
)


def test_parse_hotkey_sequence_win_shift_v() -> None:
    """Verifies default Win+Shift+V sequence parsing."""
    mods, vk = parse_hotkey_sequence("Win+Shift+V")
    assert mods == (MOD_WIN | MOD_SHIFT | MOD_NOREPEAT)
    assert vk == ord("V")


def test_parse_hotkey_sequence_ctrl_alt_space() -> None:
    """Verifies Ctrl+Alt+Space sequence parsing."""
    mods, vk = parse_hotkey_sequence("Ctrl+Alt+Space")
    assert mods == (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
    assert vk == 0x20


def test_parse_hotkey_sequence_f_keys() -> None:
    """Verifies function key parsing."""
    mods, vk = parse_hotkey_sequence("F8")
    assert mods == MOD_NOREPEAT
    assert vk == 0x77  # VK_F8


def test_parse_hotkey_sequence_invalid() -> None:
    """Verifies invalid hotkey sequences raise descriptive ValueError."""
    with pytest.raises(ValueError, match="Unrecognised key"):
        parse_hotkey_sequence("Win+Shift+InvalidKeyName")

    with pytest.raises(ValueError, match="No valid trigger key"):
        parse_hotkey_sequence("Win+Shift")


def test_global_hotkey_worker_non_windows() -> None:
    """Verifies worker emits registration_failed on non-Windows platforms."""
    with patch("os.name", "posix"):
        worker = GlobalHotkeyWorker("Win+Shift+V")
        failed_msgs = []
        worker.registration_failed.connect(failed_msgs.append)

        worker.run()
        assert len(failed_msgs) == 1
        assert "Windows" in failed_msgs[0]


def test_global_hotkey_worker_registration_failure() -> None:
    """Verifies worker emits registration_failed if RegisterHotKey returns False."""
    with patch("os.name", "nt"), \
         patch("ctypes.windll.user32.RegisterHotKey", return_value=0), \
         patch("ctypes.windll.kernel32.GetLastError", return_value=1409), \
         patch("ctypes.windll.kernel32.GetCurrentThreadId", return_value=1234):

        worker = GlobalHotkeyWorker("Win+Shift+V")
        failed_msgs = []
        worker.registration_failed.connect(failed_msgs.append)

        worker.run()
        assert len(failed_msgs) == 1
        assert "Failed to register" in failed_msgs[0]
        assert "1409" in failed_msgs[0]
