# Implementation Plan: Classroom Voice Notes Core Pipeline & Desktop UI

**Branch**: `001-core-pipeline-desktop-ui` | **Date**: 2026-06-14 | **Spec**: [specs/features/001-classroom-voice-notes/spec.md](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/specs/features/001-classroom-voice-notes/spec.md)

**Input**: Feature specification from `specs/features/001-classroom-voice-notes/spec.md`

## Summary
Implement the core Classroom Voice Notes desktop application using Python and PySide6. The application will listen locally for the "Joshua note" wake phrase, trigger a recording session with a floating widget UI, transcribe the audio using a subprocess-based `whisper.cpp` engine, run privacy-routing checks using local Ollama model instances (`qwen3.5:latest` and `phi4:14b`), and write the resulting note to the local Obsidian vault inbox/folders.

---

## Technical Context

* **Language/Version**: Python 3.11+ (with strict type hinting)
* **Primary Dependencies**: PySide6, picovoice-porcupine, httpx (for Ollama HTTP API), whisper.cpp (pre-compiled binary)
* **Storage**: Local filesystem, settings stored in `settings.json`, output stored as Obsidian vault Markdown files
* **Testing**: pytest (with pytest-qt and pytest-asyncio)
* **Target Platform**: Windows 10/11 Desktop
* **Project Type**: Desktop Application (GUI / System Tray)
* **Performance Goals**: Floating widget UI update latency < 50ms, background threads for processing to prevent main thread blocking, transcription pipeline latency < 5s for short notes.
* **Constraints**: Offline-capable, strict local-only data processing for student sensitive information, no external dependencies except optional Telegram (disabled by default).

---

## Constitution Check
* **Local-first by default**: Verified. Core transcription and Ollama processes run entirely locally.
* **Australian Spelling**: Verified. All file names, variables, strings, and logs will adhere to Australian spelling.
* **Strict Type hints**: Verified. Enforce type checking.

---

## Proposed Changes

```text
app/
├── main.py                          # Application entry point, configures asyncio loop and PySide6
├── config/
│   └── settings.py                  # Settings management, saves/loads settings.json
├── audio/
│   └── recorder.py                  # Audio input handler, manages PySide6 QThread recording session
├── wakeword/
│   └── porcupine_listener.py        # Listens for Porcupine wake words, loads custom .ppn files
├── transcription/
│   └── transcriber.py               # Runs whisper.cpp via asynchronous subprocess
├── ollama_router/
│   ├── classifier.py                # Interacts with local Ollama http endpoint
│   └── policy_gate.py               # Runs final hard-coded privacy/routing check on LLM results
├── destinations/
│   └── obsidian_writer.py           # Writes frontmatter-metadata markdown notes to directories
├── audit/
│   └── audit_logger.py              # Appends state transition history to audit.log
├── ui/
│   ├── main_window.py               # Settings and configuration GUI window
│   ├── recording_indicator.py       # Frameless, always-on-top, draggable floating widget
│   └── tray_icon.py                 # System tray context menu and quick actions
└── utils/
    └── paths.py                     # Configures paths and ensures settings directory exists
```

### 1. PySide6 Background Threading (`QThread` / `QThreadPool`)
Create a background worker system so transcription, recording, and Ollama calls do not block the UI.
* **Class**: `AudioRecorderThread(QThread)`: Captures raw audio input and writes to a temporary `.wav` file.
* **Class**: `PipelineWorker(QRunnable)`: Dispatched to `QThreadPool` for executing whisper.cpp transcription, Ollama classification, and Obsidian writing.

### 2. whisper.cpp Subprocess Integration
* **File**: `app/transcription/transcriber.py`
* Interface with the compiled whisper.cpp command-line executable using Python's async subprocess:
  ```python
  import subprocess
  # Execution string: whisper.exe -m <model_path> -f <audio_path> -otxt
  ```

### 3. Frameless Draggable Widget UI
* **File**: `app/ui/recording_indicator.py`
* Set window flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`.
* Override mouse events (`mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`) to track cursor offset and support dragging the widget anywhere on the screen.
* Implement a state tracker showing recording states (Recording, Transcribing, Saving) and use a QTimer to flash/pulse the widget red once recording exceeds 50 seconds.

### 4. Local Ollama Routing & Safety Gate
* **File**: `app/ollama_router/classifier.py`
* Interface with `http://localhost:11434` to classify the transcript text.
* **File**: `app/ollama_router/policy_gate.py`
* Double-checks the classifier's output. If the note is classified as containing student names, achievement details, behaviour observations, or early pickups, external routing is blocked and `telegram_allowed` is hardcoded to `false`.

---

## Verification Plan

### Integration Tests
* **File**: `tests/integration/test_ollama_connection.py`
  - Before executing tests, send an HTTP check to `http://localhost:11434/api/tags`.
  - Validate that the Ollama service is active.
  - Verify that the models `qwen3.5:latest` and `phi4:14b` are loaded. If not loaded, fail the test setup early.
  - Test routing outcomes for mock transcripts containing student names.

### Manual Verification
1. Launch the application. Verify that a settings setup folder picker appears asking for the Obsidian vault path.
2. Open the settings UI, load a custom `.ppn` wake-phrase file, and save settings. Verify that `settings.json` is updated.
3. Test drag-and-move functionality of the floating widget.
4. Record for 55 seconds and verify the floating widget pulses red. Verify that at 60 seconds the recording terminates, saves, and transcribes.
