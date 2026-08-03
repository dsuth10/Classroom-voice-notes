"""Inter-process file lock utility supporting Windows (msvcrt) and POSIX (fcntl)."""

import os
from pathlib import Path
import time
from typing import Any, Optional


class ProcessFileLock:
    """Cross-platform inter-process file lock.

    Uses msvcrt locking on Windows and fcntl locking on POSIX systems.
    """

    def __init__(self, lock_path: Path, timeout: float = 10.0) -> None:
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd: Optional[int] = None

    def __enter__(self) -> "ProcessFileLock":
        start_time = time.monotonic()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        while True:
            try:
                fd = os.open(str(self.lock_path), flags, 0o666)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore
                self._fd = fd
                return self
            except (OSError, IOError):
                if "fd" in locals() and fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if time.monotonic() - start_time >= self.timeout:
                    raise TimeoutError(
                        f"Could not acquire process file lock on {self.lock_path}"
                    )
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fd, fcntl.LOCK_UN)  # type: ignore
            except OSError:
                pass
            finally:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
