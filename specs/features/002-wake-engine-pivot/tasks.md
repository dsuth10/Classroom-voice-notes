# Tasks: Local Wake Engine Abstraction & openWakeWord Pivot

**Input**: Design documents from `specs/features/002-wake-engine-pivot/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), constitution.md

**Organisation**: Tasks are grouped by phase and user story to ensure clean, decoupled development, adhering to a strict Test-Driven Development (TDD) cycle (writing failing tests first, then implementing).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Python project dependency configuration.

- [x] T001 Configure project dependencies in [pyproject.toml](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/pyproject.toml) to include `openwakeword`, `vosk`, and `onnxruntime`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Nested configuration settings and base class initialisation.

- [x] T002 Refactor `SettingsManager` in [settings.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/config/settings.py) to support nested configurations (wake-word, spoken commands, audio, and recording parameters) with dot-notation path helpers (`get` and `set`).
- [x] T003 [P] Write unit tests in [test_settings.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/unit/test_settings.py) to verify nested settings loading, saving, and dot-notation access.
- [x] T004 Create base engine interfaces (`WakeEngine` and `CommandEngine`) in [engine.py (wakeword)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/wakeword/engine.py) and [engine.py (commands)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/commands/engine.py).
- [x] T005 Create stub `AppController` in [controller.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/controller.py) exposing PySide6 signals and state lifecycle variables.
- [x] T006 Write initial unit tests in [test_controller.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/unit/test_controller.py) to verify basic state transitions of the controller.

---

## Phase 3: User Story 2 - Background Audio Input Manager (Priority: P2)

**Goal**: Continuous microphone capture, 1.5s pre-roll buffer, and thread-safe chunk distribution.

**Independent Test**: Mock sounddevice callback stream, subscribe multiple listeners, verify they receive raw PCM chunks, and verify that `get_pre_roll()` returns exactly 1.5s of audio.

### Tests for User Story 2
- [x] T007 [P] Write integration tests in [test_input_manager.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/integration/test_input_manager.py) to verify stream capture, subscriber queue distribution, and pre-roll buffers.
- [x] T008 [P] Write unit tests in [test_audio_worker.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/unit/test_audio_worker.py) verifying that `RecorderWorker` consumes queue chunks and writes out correct WAV files.

### Implementation for User Story 2
- [x] T009 Implement `AudioInputManager` in [input_manager.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/audio/input_manager.py) running a sounddevice stream and maintaining the 1.5s ring buffer.
- [x] T010 Implement `RecorderWorker` in [worker.py (audio)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/audio/worker.py) to write PCM chunks from queue to WAV.
- [x] T011 Update `AppController` in [controller.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/controller.py) to spin up `AudioInputManager` and subscribe/unsubscribe the recorder worker.

---

## Phase 4: User Story 1 - Local Wake-Phrase Detection via openWakeWord (Priority: P1)

**Goal**: Local wake-phrase detection of "Joshua note" via openWakeWord.

**Independent Test**: Feed audio containing the wake phrase to `WakeWordWorker` queue, verify `wake_word_detected` signal is emitted, and verify that no triggers happen on noise.

### Tests for User Story 1
- [x] T012 [P] Write unit/integration tests in [test_wakeword.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/unit/test_wakeword.py) mocking `openwakeword.model.Model` prediction outputs, testing worker signal emissions.

### Implementation for User Story 1
- [x] T013 Implement `OpenWakeWordEngine` and `ManualOnlyEngine` in [engine.py (wakeword)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/wakeword/engine.py).
- [x] T014 Implement `WakeWordWorker` in [worker.py (wakeword)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/wakeword/worker.py) running as a PySide QThread consuming queue audio chunks.
- [x] T015 Integrate `WakeWordWorker` lifecycle and subscription inside `AppController` in [controller.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/controller.py) to manage transitions to `IDLE_LISTENING` and `RECORDING`.

---

## Phase 5: User Story 3 - Spoken Save/Cancel Commands via Vosk (Priority: P3)

**Goal**: Hands-free save/cancel command parsing during active recording.

**Independent Test**: Feed "save" audio chunk to `VoskCommandWorker` queue, verify transition trigger signal is emitted, and verify the 2-second command debounce is enforced.

### Tests for User Story 3
- [x] T016 [P] Write unit tests in [test_commands.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/unit/test_commands.py) to mock `vosk.KaldiRecognizer` and test grammar parsing, signal emissions, and debounce checks.

### Implementation for User Story 3
- [x] T017 Implement `VoskCommandEngine` in [engine.py (commands)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/commands/engine.py).
- [x] T018 Implement `VoskCommandWorker` in [worker.py (commands)](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/commands/worker.py) running as a PySide QThread.
- [x] T019 Integrate `VoskCommandWorker` inside `AppController` in [controller.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/controller.py) to run during the `RECORDING` state.

---

## Phase 6: UI Integration & Settings Panels

**Goal**: Wire the central coordinator to PySide GUI elements and update settings panels.

- [x] T020 Refactor [main_window.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/ui/main_window.py) to expose settings for wake-word engine type, Vosk command toggles, thresholds, and local model file selector dialogues.
- [x] T021 Implement a graceful model validation dialog fallback if model files are missing from the `models/` folder.
- [x] T022 Wire the frameless [recording_indicator.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/ui/recording_indicator.py) state display and timers directly to `AppController` signals.
- [x] T023 Update application launch sequence in [run.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/run.py) to instantiate the `AppController` and link it with the main window.

---

## Phase 7: Polish & Quality Gates

**Purpose**: Static verification, formatting, and performance auditing.

- [x] T024 Validate code alignment with Australian spelling guidelines across comments, UI labels, and docstrings.
- [x] T025 Run strict static type checking with `mypy app/` and ensure all tests pass.
- [x] T026 Audit codebase using checklist runner (`python .agent/scripts/checklist.py .`).
