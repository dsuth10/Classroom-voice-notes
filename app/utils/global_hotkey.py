"""Global Hotkey Listener — Windows system-wide hotkey toggle for background note capture."""

import ctypes
import os
from typing import Optional, Tuple
from PySide6.QtCore import QThread, Signal
from app.audit.audit_logger import log_audit_event

# Windows API Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Virtual Key Codes
VK_MAP = {
    "SPACE": 0x20,
    "RETURN": 0x0D,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
}
for i in range(1, 13):
    VK_MAP[f"F{i}"] = 0x70 + (i - 1)


def parse_hotkey_sequence(sequence: str) -> Tuple[int, int]:
    """Parses a hotkey string like 'Win+Shift+V' into (modifiers, vk_code).

    Returns:
        Tuple[int, int]: (fsModifiers bitmask, virtual key code integer)
    """
    parts = [p.strip().lower() for p in sequence.split("+") if p.strip()]
    modifiers = MOD_NOREPEAT
    vk_code = 0

    for part in parts:
        if part in ("win", "windows", "super", "meta"):
            modifiers |= MOD_WIN
        elif part in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part == "alt":
            modifiers |= MOD_ALT
        else:
            # Main key part
            upper_part = part.upper()
            if upper_part in VK_MAP:
                vk_code = VK_MAP[upper_part]
            elif len(part) == 1:
                vk_code = ord(upper_part)
            else:
                raise ValueError(f"Unrecognised key '{part}' in hotkey sequence '{sequence}'")

    if vk_code == 0:
        raise ValueError(f"No valid trigger key found in hotkey sequence '{sequence}'")

    return modifiers, vk_code


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_void_p),
        ("lParam", ctypes.c_void_p),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class GlobalHotkeyWorker(QThread):
    """Background worker thread running a Windows message pump to intercept global hotkeys."""

    hotkey_triggered = Signal()
    registered = Signal(str)
    registration_failed = Signal(str)

    def __init__(self, sequence: str = "Win+Shift+V", hotkey_id: int = 1001) -> None:
        super().__init__()
        self.sequence = sequence
        self.hotkey_id = hotkey_id
        self._thread_id: Optional[int] = None
        self._is_running = False

    def run(self) -> None:
        if os.name != "nt":
            self.registration_failed.emit("Global hotkeys are only supported on Windows.")
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id = kernel32.GetCurrentThreadId()

        try:
            modifiers, vk_code = parse_hotkey_sequence(self.sequence)
        except Exception as e:
            log_audit_event("HOTKEY_PARSE_ERROR", "global_hotkey", f"Invalid hotkey sequence '{self.sequence}': {e}")
            self.registration_failed.emit(str(e))
            return

        # Register global hotkey associated with this thread's message queue
        success = user32.RegisterHotKey(None, self.hotkey_id, modifiers, vk_code)
        if not success:
            last_err = kernel32.GetLastError()
            err_msg = f"Failed to register global hotkey '{self.sequence}' (Win32 Error: {last_err}). The shortcut may be in use by another application."
            log_audit_event("HOTKEY_REGISTRATION_FAILED", "global_hotkey", err_msg)
            self.registration_failed.emit(err_msg)
            return

        self._is_running = True
        log_audit_event("HOTKEY_REGISTERED", "global_hotkey", f"Registered global hotkey '{self.sequence}' (id={self.hotkey_id})")
        self.registered.emit(self.sequence)

        msg = MSG()
        try:
            # Standard Win32 Message Loop
            while self._is_running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0 or msg.message == WM_QUIT:
                    break

                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    log_audit_event("HOTKEY_TRIGGERED", "global_hotkey", f"Global hotkey '{self.sequence}' triggered")
                    self.hotkey_triggered.emit()

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)
            self._is_running = False
            log_audit_event("HOTKEY_UNREGISTERED", "global_hotkey", f"Unregistered global hotkey '{self.sequence}'")

    def stop(self) -> None:
        """Stops the message loop and terminates the worker thread cleanly."""
        self._is_running = False
        if self._thread_id and os.name == "nt":
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        self.quit()
        self.wait(1000)
