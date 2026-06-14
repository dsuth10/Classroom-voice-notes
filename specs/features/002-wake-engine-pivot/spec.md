# Feature Specification: Local Wake Engine Abstraction & openWakeWord Pivot

**Feature Branch**: `002-wake-engine-pivot`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Replacing Picovoice Porcupine with openWakeWord, establishing a single background audio listener, and optionally routing recording chunks to Vosk during active recording"

---

## Executive Summary
This feature redesigns the wake-word and voice command layer of the **Classroom Voice Notes** application to remove any dependence on commercial, key-restricted services (such as Picovoice Porcupine). The application will pivot to `openWakeWord` for wake-word detection and optionally `Vosk` for short spoken control commands during recording. 

To ensure high reliability, low latency, and zero audio device conflicts (especially on Windows with Bluetooth/USB microphones), the application will use a single `AudioInputManager` thread that maintains ownership of the microphone. It will continuously capture audio at 16 kHz mono PCM and route chunks to active engine consumers dynamically based on the application state.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Local Wake-Phrase Detection via openWakeWord (Priority: P1)
As a teacher, I want to say "Joshua note" to trigger recording hands-free without needing an active internet connection or a paid commercial API key.

**Why this priority**: Essential to guarantee the application remains fully local-first, free, and decoupled from commercial licensing constraints.

**Independent Test**: Speak "Joshua note" while the application is in an idle state. Verify that the app transitions to `RECORDING` state and begins capturing observations without requiring a Porcupine access key.

**Acceptance Scenarios**:
1. **Given** the application is in `IDLE_LISTENING` state, **When** the microphone stream detects the wake-phrase "Joshua note" via the `openWakeWord` engine, **Then** the app transitions to `RECORDING` state and plays an activation tone.
2. **Given** the application is configured with `manual_only` wake engine in settings, **When** the user says "Joshua note", **Then** the application does not trigger recording automatically, and remains in `IDLE_LISTENING` state.

---

### User Story 2 - Background Audio Input Manager (Priority: P2)
As a teacher, I want the application to maintain a single active microphone session for the lifetime of the application, so that I do not experience device reconnection lag, audio conflicts, or clipped audio at the start of my notes.

**Why this priority**: Necessary for operational robustness, particularly when using Bluetooth or external USB microphones that take time to open and release.

**Independent Test**: Trigger recording via wake word multiple times and verify that the first 1.5 seconds of the recorded WAV note contain the speech spoken immediately prior to/during the wake phrase (captured from the pre-roll buffer).

**Acceptance Scenarios**:
1. **Given** the application is running, **When** transitioning from `IDLE_LISTENING` to `RECORDING` states, **Then** the microphone stream is never closed or reopened.
2. **Given** a wake-phrase is detected at timestamp `T`, **When** the recording WAV file is compiled, **Then** it includes audio starting from `T - 1.5` seconds to prevent start-of-recording clipping.

---

### User Story 3 - Spoken Save/Cancel Commands via Vosk (Priority: P3)
As a teacher recording a note, I want to speak the words "save" or "cancel" to control the recording session hands-free, without having to return to my computer.

**Why this priority**: Adds convenience for fully hands-free operation, but is an optional convenience layer; manual hotkeys and the hard recording cap remain the primary control fallbacks.

**Independent Test**: Start recording, speak "save" or "cancel", and verify that the recording stops, and that the command does not trigger multiple times due to a debounce cooldown.

**Acceptance Scenarios**:
1. **Given** the application is in `RECORDING` state and voice commands are enabled, **When** the user says "save", **Then** the app stops recording, transcribes the note, and routes it.
2. **Given** the application is in `RECORDING` state and voice commands are enabled, **When** the user says "cancel", **Then** the app stops recording, discards the audio, and returns to `IDLE_LISTENING`.
3. **Given** a spoken command is detected, **When** the state transition begins, **Then** further Vosk commands are ignored for a 2-second cooldown period to prevent double-firing.

---

## Edge Cases & Fail-safes

### Noise interference (Wake phrase or commands missed)
- **Problem**: Classroom noise or distance prevents `openWakeWord` or `Vosk` from detecting voice triggers.
- **Solution**: 
  1. Manual controls (UI buttons, tray menu, and global hotkeys: `Ctrl + Alt + S` for save, `Ctrl + Alt + C` for cancel) remain fully active and must bypass/override voice engine states.
  2. The 60-second hard recording duration cap is always active and will automatically save the note when reached.

### Audio device unplugged
- **Problem**: The default system input device is disconnected while the app is running.
- **Solution**: The `AudioInputManager` must catch disconnection exceptions, attempt to fall back to the new default system input device, and log an error to `audit.log`.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run a single `AudioInputManager` thread that opens and maintains the microphone stream (16 kHz mono PCM) for the lifetime of the application.
- **FR-002**: The `AudioInputManager` MUST maintain a 1.5-second pre-roll ring buffer of audio chunks to prevent clipping at the beginning of notes.
- **FR-003**: The wake-word layer MUST support an abstract `WakeEngine` interface to allow swapping engines (e.g., `openWakeWord`, `local-wake`, `manual_only`).
- **FR-004**: In `IDLE_LISTENING` state, the shared audio manager MUST pipe captured audio chunks to the active `WakeEngine` only. Vosk and the WAV recorder MUST remain inactive.
- **FR-005**: In `RECORDING` state, the shared audio manager MUST write audio chunks to the WAV recording buffer, and optionally pipe them to the `Vosk` command engine if enabled. The `WakeEngine` MUST remain inactive.
- **FR-006**: The local `models/` directory in the project root MUST store all model dependencies under `models/wakewords/` and `models/vosk/`.
- **FR-007**: The settings GUI window MUST be updated to allow configuring:
  - Wake-word engine type, threshold, ONNX model path, and trigger phrase.
  - Spoken command engine toggle, Vosk model path, and grammar keyword list (default: `save`, `cancel`, `stop`, `discard`).
- **FR-008**: The `Vosk` command engine MUST only consume audio chunks during the `RECORDING` state and MUST enforce a 2-second debounce cooldown after detecting any command.
- **FR-009**: The audio stream callback MUST stay lightweight, placing audio chunks into queues/buffers without performing transcription or classification tasks directly on the capture thread.

### Key Entities

- **AudioInputManager**: The thread that owns the microphone stream, handles device fallback, and fans out audio chunks.
- **WakeEngine (Interface)**: Abstraction for wake-word engines (`OpenWakeWordEngine`, `ManualOnlyEngine`).
- **CommandEngine**: Interface for parsing spoken control phrases (`VoskCommandEngine`) during recording.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Changing states between `IDLE_LISTENING` and `RECORDING` has a latency of less than 50ms and does not close or re-open the audio device.
- **SC-002**: Audio pre-roll contains exactly the 1.5 seconds of audio captured prior to wake-word detection.
- **SC-003**: The `openWakeWord` engine successfully detects "Joshua note" and triggers the recording session locally and offline.
- **SC-004**: When voice commands are enabled, the `Vosk` engine processes chunks concurrently during recording and triggers "save" or "cancel" actions within 500ms of utterance.
- **SC-005**: Static type checking checks (`mypy app/`) return success after implementation.
- **SC-006**: The audit logger records all wake engine transitions, model paths loaded, and any device fallback events in `audit.log`.

---

## Assumptions

- **Target OS**: The primary deployment target is Windows 10/11 running PySide6.
- **Hardware capabilities**: The teacher's PC has a microphone connected, and the CPU has sufficient resources to run `onnxruntime` inference for openWakeWord.
- **Vosk footprint**: The Vosk command engine uses a small, lightweight model (`vosk-model-small-en-us`) to limit RAM usage.
