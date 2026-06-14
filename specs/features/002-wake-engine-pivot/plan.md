# Implementation Plan: Local Wake Engine Abstraction & openWakeWord Pivot

**Branch**: `002-wake-engine-pivot` | **Date**: 2026-06-14 | **Spec**: [spec.md](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/specs/features/002-wake-engine-pivot/spec.md)

**Input**: Feature specification from `specs/features/002-wake-engine-pivot/spec.md`

## Summary

This feature replaces Picovoice Porcupine with `openWakeWord` and optionally integrates `Vosk` for spoken control commands during active recording. The goal is to fully decouple the classroom note-taking pipeline from cloud services and commercial key requirements. 

To achieve high reliability, prevent audio device conflicts, and keep the application responsive:
1. A single `AudioInputManager` owns the microphone stream (16 kHz mono PCM) for the lifetime of the application and maintains a 1.5-second pre-roll ring buffer.
2. An `AppController` acts as a central coordinator that manages state transitions (`IDLE_LISTENING`, `RECORDING`, `TRANSCRIBING`, `CLASSIFYING`, `ROUTING`, `ERROR`) and coordinates the workers.
3. Dedicated worker threads consume audio chunks via queues to ensure that heavy model inferences (wake-word detection and Vosk spoken commands) do not block the audio capture callback or the PySide6 UI event loop.
4. Settings are reorganised into a clean, nested structure in `settings.json`.

---

## Technical Context

**Language/Version**: Python 3.11, PySide6

**Primary Dependencies**: `openwakeword`, `onnxruntime`, `vosk`, `sounddevice`, `numpy`, `scipy`

**Storage**: Local JSON settings (`settings.json`), Local audit log (`audit.log`), Local folders for models (`models/wakewords/` and `models/vosk/`), Local Obsidian Markdown files.

**Testing**: `pytest`, `pytest-qt` (mocking / stubbing PySide signals and engines)

**Target Platform**: Windows 10/11 desktop, local microphone

**Project Type**: PySide6 Desktop Application

**Performance Goals**:
* Callback enqueue time: < 1ms
* State transition latency: < 50ms
* Wake-phrase and spoken command detection latency: < 500ms
* Voice commands debounce cooldown: 2.0 seconds

**Constraints**:
* Fully offline-capable.
* Zero silent automatic downloads of model files on startup.
* Lightweight audio callback thread.
* Strict local storage and Australian spelling throughout user-facing text and documentation.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

1. **Private Classroom Information Stays Local**: Passed. By pivoting to `openWakeWord` and `Vosk`, all audio processing is done entirely offline on the local machine.
2. **Hard-Coded Policy Gate**: Checked. Note routing remains guarded by the privacy policy gate.
3. **Floating Widget Responsiveness**: Passed. `AppController` coordinates state transitions and immediately emits PySide signals to the UI, guaranteeing sub-50ms visual updates.
4. **Short Recording Cap**: Passed. The 60-second recording cap remains strictly enforced and is managed by `AppController`.
5. **Language & Formatting**: Passed. All documents, user notifications, and code comments will use Australian spelling conventions (e.g., *initialisation*, *customisation*, *organisation*, *behaviour*).

---

## Project Structure

### Documentation (this feature)

```text
specs/features/002-wake-engine-pivot/
├── spec.md              # Feature specification
├── plan.md              # This file (workspace copy)
└── tasks.md             # Task breakdown (to be created by /speckit.tasks)
```

### Source Code

```text
app/
├── main.py              # Main application initializer
├── controller.py        # NEW: AppController (Central coordinator)
├── audio/
│   ├── input_manager.py # NEW: AudioInputManager (owns microphone stream & pre-roll)
│   ├── worker.py        # NEW: RecorderWorker (handles writing audio chunks to WAV)
│   └── recorder.py      # Refactored: Legacy code adapted or deprecated
├── config/
│   └── settings.py      # Modified: SettingsManager handles nested JSON keys
├── wakeword/
│   ├── __init__.py
│   ├── engine.py        # NEW: WakeEngine, OpenWakeWordEngine, ManualOnlyEngine
│   └── worker.py        # NEW: WakeWordWorker (dedicated QThread for wake detection)
├── commands/
│   ├── __init__.py
│   ├── engine.py        # NEW: CommandEngine, VoskCommandEngine
│   └── worker.py        # NEW: VoskCommandWorker (dedicated QThread for Vosk commands)
├── ui/
│   ├── main_window.py   # Modified: UI updated for wake-word and Vosk settings
│   └── recording_indicator.py # Modified: UI transitions wired to controller signals
```

---

## Proposed Changes

### Configuration Migration

The legacy flat configuration keys in `settings.json` will be migrated to the following nested structure:

```json
{
  "obsidian_vault_path": "",
  "whisper_bin_path": "bin/whisper/whisper.exe",
  "whisper_model_path": "bin/whisper/ggml-base.en.bin",
  "ollama_url": "http://localhost:11434",
  "fast_model": "qwen3.5:latest",
  "careful_model": "phi4:14b",
  "telegram_token": "",
  "telegram_chat_id": "",
  "telegram_enabled": false,
  "wake_word": {
    "engine": "openwakeword",
    "enabled": true,
    "phrase": "Joshua note",
    "model_path": "models/wakewords/joshua_note.onnx",
    "threshold": 0.5,
    "cooldown_seconds": 2.0
  },
  "spoken_commands": {
    "enabled": false,
    "engine": "vosk",
    "model_path": "models/vosk/vosk-model-small-en",
    "grammar_keywords": ["save", "cancel", "stop", "discard"],
    "command_cooldown_seconds": 2.0
  },
  "audio": {
    "sample_rate": 16000,
    "channels": 1,
    "chunk_size": 1280,
    "pre_roll_seconds": 1.5
  },
  "recording": {
    "hard_cap_seconds": 60,
    "manual_controls_enabled": true
  }
}
```

To support this in `SettingsManager` and preserve backward-compatibility with flat keys (if referenced elsewhere), the `get(key)` and `set(key, value)` methods will be updated to handle dot-separated paths (e.g. `settings_manager.get("wake_word.engine")`).

---

### Component Specifications

#### 1. AudioInputManager (`app/audio/input_manager.py`)
* Runs as a separate execution context/thread that handles PyAudio/sounddevice setup.
* Opens a single `sounddevice.InputStream` at 16000 Hz, mono PCM (`numpy.int16` format).
* Uses an audio callback to push incoming raw audio buffers into a thread-safe `collections.deque` (acting as the 1.5-second pre-roll ring buffer) and publishes chunks to a list of active subscriber queues.
* Exposes methods:
  * `subscribe(queue)`: Adds a queue to receive real-time audio chunks.
  * `unsubscribe(queue)`: Removes a queue from receiving chunks.
  * `get_pre_roll()`: Returns the concatenated contents of the 1.5-second ring buffer.
* Automatically catches microphone disconnections, logs them in `audit.log`, and attempts to reconnect to the system's new default audio input device.

#### 2. Wake-Phrase Engine (`app/wakeword/engine.py` and `app/wakeword/worker.py`)
* **`WakeEngine`**: Abstract base class defining `predict(chunk: np.ndarray) -> float` and `detect(chunk: np.ndarray) -> bool`.
* **`OpenWakeWordEngine`**: Implementation wrapping `openwakeword.model.Model`. Loads the local ONNX model file from `models/wakewords/`.
* **`ManualOnlyEngine`**: A stub engine that never triggers, used when wake-word detection is disabled or models are missing.
* **`WakeWordWorker`**: A QThread that:
  * Creates and manages the active `WakeEngine`.
  * Subscribes to the `AudioInputManager` stream via a queue.
  * Continuously pulls chunks, invokes the engine's inference, and emits a `wake_word_detected` signal if the output score exceeds the threshold.

#### 3. Command Engine (`app/commands/engine.py` and `app/commands/worker.py`)
* **`CommandEngine`**: Abstract base class defining `accept_chunk(chunk: np.ndarray) -> str | None`.
* **`VoskCommandEngine`**: Wraps the `vosk` model. Parses incoming chunks using `vosk.KaldiRecognizer` configured with the list of grammar keywords (`save`, `cancel`, `stop`, `discard`).
* **`VoskCommandWorker`**: A QThread that runs during `RECORDING` state if spoken commands are enabled.
  * Feeds incoming chunks to the `CommandEngine`.
  * Emits `command_detected(command_name)` when a matching keyword is recognized.
  * Enforces a 2-second debounce cooldown during which it ignores further incoming speech.

#### 4. Recorder Worker (`app/audio/worker.py`)
* Consumes audio chunks from its queue when recording.
* When started, it gets the pre-roll chunk from `AudioInputManager` and writes it first.
* Appends subsequent stream chunks into a list, and on stop, writes them out to a WAV file using `scipy.io.wavfile.write`.

#### 5. AppController (`app/controller.py`)
* Coordinates the overall application lifecycle and state transitions.
* Manages references to the `AudioInputManager`, `WakeWordWorker`, `VoskCommandWorker`, and `RecorderWorker`.
* **State Logic**:
  * **Transition to `IDLE_LISTENING`**: Subscribes `WakeWordWorker` queue to `AudioInputManager`. Ensures Vosk and Recorder workers are inactive.
  * **Transition to `RECORDING`**: Unsubscribes `WakeWordWorker`. Subscribes `RecorderWorker` queue. If spoken commands are enabled, also subscribes `VoskCommandWorker`. Starts a timer matching the recording limit. Emits PySide signals to trigger the start chime/beep and update the UI.
  * **Transition to `TRANSCRIBING` / `SAVING` / `CLASSIFYING`**: Unsubscribes all workers. Stops the microphone routing to queues. Executes the legacy transcription, Ollama router, and policy gate pipeline.
* Handles manual overrides (UI button clicks, global hotkey triggers) to cancel or save recording, overriding any voice-activated events.
* Dispatches PySide signals to the settings/recording GUI windows to trigger smooth transitions.

---

## Verification Plan

### Automated Tests
* **Settings Tests**:
  * Verify `SettingsManager` successfully loads and saves nested structures.
  * Verify dot-notation property lookups (`settings.get("wake_word.engine")`).
* **Audio Input Manager Tests**:
  * Mock `sounddevice` stream to push mock PCM chunks.
  * Verify the pre-roll buffer maintains exactly `16000 * 1.5 = 24000` samples.
  * Verify subscribers receive audio chunks correctly.
* **Worker & Engine Mocks**:
  * Mock `OpenWakeWordEngine` and `VoskCommandEngine` to simulate predictions and triggers without requiring heavy local ONNX files.
  * Test that `WakeWordWorker` emits `wake_word_detected` signal on mock prediction triggers.
  * Test that `VoskCommandWorker` enforces a 2-second debounce cooldown.
* **State Machine Tests**:
  * Mock out the underlying hardware and verify that `AppController` state transitions occur under 50ms.
  * Verify that manual commands (`save`, `cancel`) bypass/override voice-activated processes.

### Manual Verification
* **Model Validation UI**:
  * Run the app without model files in `models/`. Verify that the UI displays a warning dialogue with clear download instructions, rather than crashing or downloading files silently.
  * Select a dummy path and verify the error handling.
* **Physical Device Integration**:
  * Plug/unplug a USB microphone while in `IDLE_LISTENING` and verify `audit.log` records the exception and successful device reconnection.
  * Say "Joshua note" and verify the app triggers recording.
  * Say "save" or "cancel" during recording and verify the action is executed.
