# Tasks: Classroom Voice Notes Core Pipeline & Desktop UI

**Input**: Design documents from `specs/features/001-classroom-voice-notes/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), constitution.md

**Organisation**: Tasks are grouped by user story to enable independent implementation and testing of each story, following a strict Test-Driven Development (TDD) cycle (writing failing tests first, then implementing).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialisation and basic environment structure.

- `[x]` T001 Create project structure layout (`app/`, `tests/`) as planned.
- `[x]` T002 Initialise a modern `pyproject.toml` file containing dependencies: `PySide6`, `sounddevice`, `httpx`, `pvporcupine`, and development dependencies: `pytest`, `pytest-qt`, `pytest-asyncio`, `mypy`.
- `[x]` T003 [P] Configure strict `mypy` type checking parameters, black formatting, and linting rules in `pyproject.toml`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core local utilities that must be complete before any user interface or capture logic is built.

- `[x]` T004 Implement `app/utils/paths.py` to manage application data paths and guarantee local folders exist.
- `[x]` T005 [P] Implement `app/audit/audit_logger.py` to append structured state machine transition events to `audit.log`.
- `[x]` T006 Implement configuration manager `app/config/settings.py` to handle loading/writing configurations in `settings.json`.

---

## Phase 3: User Story 4 - First Launch & Configuration (Priority: P4)

**Goal**: Customise Obsidian vault path and load Porcupine keywords on initial startup.

**Independent Test**: Delete `settings.json`, start the app, select the vault folder via picker, load custom wake-phrase files, and verify configuration is persisted.

### Tests for User Story 4 (TDD)
- `[x]` T007 [P] [US4] Write failing unit tests for vault path resolution and config persistence in `tests/unit/test_settings.py`.

### Implementation for User Story 4
- `[x]` T008 [US4] Implement PySide6 settings window (`app/ui/main_window.py`) containing the Obsidian vault directory folder picker.
- `[x]` T009 [US4] Add dynamically loaded Picovoice Porcupine `.ppn` keyword selection controls to the settings panel.
- `[x]` T010 [US4] Verify loaded configurations successfully update `settings.json` and loaded keyword models are persisted.

---

## Phase 4: User Story 1 - Local Voice Capture & Obsidian Storage (Priority: P1)

**Goal**: Trigger hands-free voice notes, record to WAV, transcribe via whisper.cpp, and save locally.

**Independent Test**: Say "Joshua note", record a short note, say "Joshua save", and verify a markdown note with matching metadata is created in the vault.

### Tests for User Story 1 (TDD)
- `[x]` T011 [P] [US1] Write failing unit/integration tests for background audio recording and transcription outputs in `tests/integration/test_recorder.py` and `tests/integration/test_transcriber.py`.

### Implementation for User Story 1
- `[x]` T012 [US1] Implement background `AudioRecorderThread(QThread)` in `app/audio/recorder.py` using `sounddevice` to capture audio input to a WAV buffer without blocking the GUI.
- `[x]` T013 [US1] Implement transcription runner `app/transcription/transcriber.py` calling the compiled `whisper.cpp` command-line executable via Python's asynchronous subprocess.
- `[x]` T014 [US1] Implement Obsidian file writer `app/destinations/obsidian_writer.py` to generate YAML frontmatter-enabled Markdown notes.
- `[x]` T015 [US1] Verify core capture-to-Obsidian pipeline operates successfully end-to-end and cleans up temporary audio caches.

---

## Phase 5: User Story 2 - Responsive Floating UI Widget (Priority: P2)

**Goal**: Lightweight frameless UI widget showing state changes with <50ms latency and warning users when approaching the 60s cap.

**Independent Test**: Move the widget around the screen. Verify visual changes reflect transitions instantly and that it pulses red after 50 seconds.

### Tests for User Story 2 (TDD)
- `[x]` T016 [P] [US2] Write unit tests in `tests/unit/test_recording_indicator.py verifying state change widget renders and timing triggers are correct.

### Implementation for User Story 2
- `[x]` T017 [US2] Implement frameless always-on-top window widget (`app/ui/recording_indicator.py`) using flags `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`.
- `[x]` T018 [US2] Implement overridden mouse interaction handlers (`mousePressEvent`, `mouseMoveEvent`) to support custom drag-and-move widget positioning on the desktop.
- `[x]` T019 [US2] Implement state tracker updates and a `QTimer` to transition the widget to a pulsing red animation at 50 seconds, triggering auto-save at 60 seconds.
- `[x]` T020 [US2] Verify widget transitions execute within 50ms of state changes and that the auto-save hard cap triggers correctly.

---

## Phase 6: User Story 3 - Privacy Gate and Local Ollama Routing (Priority: P3)

**Goal**: Classify transcripts locally using Ollama and block external routing if sensitive student details are detected.

**Independent Test**: Route a mock transcript containing student details and ensure it stays local. Route a planning transcript and verify external route permission.

### Tests for User Story 3 (TDD)
- `[x]` T021 [P] [US3] Write integration tests in `tests/integration/test_router.py` verifying connection to `http://localhost:11434`, check loaded models (`qwen3.5:latest` and `phi4:14b`), and test privacy routing gates.

### Implementation for User Story 3
- `[x]` T022 [US3] Implement Ollama local connector `app/ollama_router/classifier.py` using `httpx` to retrieve JSON-structured classification tags.
- `[x]` T023 [US3] Implement `app/ollama_router/policy_gate.py` to inspect LLM output and block external paths if names or achievement keywords are flagged.
- `[x]` T024 [US3] Verify correct local vs. external routing decisions are made and audited in `audit.log`.

---

## Phase 7: Polish & Quality Gates

**Purpose**: Code cleanup, static typing verification, and validation checks.

- `[x]` T025 Run strict `mypy` type check verification on the entire codebase.
- `[x]` T026 Audit code against `specs/constitution.md` to ensure all strings and logs use Australian spelling.
- `[x]` T027 Run master checklist validations (`python .agent/scripts/checklist.py .`).
