# Feature Specification: Classroom Voice Notes Core Pipeline & Desktop UI

**Feature Branch**: `001-core-pipeline-desktop-ui`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Local Wake-Phrase Capture, Transcription, Obsidian Storage, and Ollama-Based Routing"

---

## Executive Summary
This feature defines the initial core system of the **Classroom Voice Notes** application. The desktop application runs locally on Windows, captures audio hands-free when triggered by a wake phrase, transcribes the speech locally using `whisper.cpp`, classifies the text using a local Ollama instance (`qwen3.5:latest` and `phi4:14b`), and routes the resulting note to either a local Obsidian vault or an external destination (Telegram) based on a strict local LLM classification gate.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Local Voice Capture & Obsidian Storage (Priority: P1)
As a teacher, I want to say the wake phrase and record a short note that gets automatically transcribed and saved to my Obsidian vault, so that I can capture classroom observations without using my hands.

**Why this priority**: This is the core MVP of the product. The system must be able to record, transcribe, and save notes locally to be useful.

**Independent Test**: Say "Joshua note", speak a 10-second observation, say "Joshua save", and verify that a markdown file appears in the configured Obsidian vault with the correct transcript.

**Acceptance Scenarios**:
1. **Given** the app is in `IDLE_LISTENING` state, **When** the microphone detects "Joshua note", **Then** the app transitions to `RECORDING` and plays a start beep.
2. **Given** the app is in `RECORDING` state, **When** the microphone detects "Joshua save", **Then** the app transitions to `TRANSCRIBING`, transcribes the audio, and saves it as a markdown file under `Obsidian Vault/Classroom Voice Notes/Inbox/`.

---

### User Story 2 - Responsive Floating UI Widget & State Feedback (Priority: P2)
As a teacher walking around the classroom, I want a clear, lightweight visual indicator of the app's recording state that is responsive and warns me when I am running out of recording time, so that I can monitor note-taking status at a glance.

**Why this priority**: Provides critical visual feedback in a noisy classroom. It must be highly responsive to make the hands-free workflow usable.

**Independent Test**: Verify that the floating widget changes visual states within 50ms of any recording state change and begins pulsing red after 50 seconds of recording time.

**Acceptance Scenarios**:
1. **Given** the app starts recording, **When** the state transitions to `RECORDING`, **Then** the floating widget appears flashing green/red (depending on preference) in under 50ms.
2. **Given** the recording time reaches 50 seconds, **When** the 60-second limit approaches, **Then** the floating widget begins pulsing red to notify the user.
3. **Given** the recording reaches 60 seconds, **When** the hard limit is hit, **Then** the app stops recording automatically, transcribes, and saves the note.

---

### User Story 3 - Privacy Gate and Local Ollama Routing (Priority: P3)
As a teacher, I want the system to classify my transcribed note and determine if it contains sensitive student or school data, so that personal data is never routed externally.

**Why this priority**: Safeguards student privacy, ensuring compliance with school data protection policies.

**Independent Test**: Record a note containing "Alex is absent today" and verify that it is routed to the local Obsidian vault's `Student Notes` directory, and that external Telegram routing is blocked.

**Acceptance Scenarios**:
1. **Given** a transcript contains student achievement or behaviour details, **When** the local LLM classifies the note, **Then** the route is set to `local_student_note` or `local_behaviour_note`, and the `telegram_allowed` parameter is set to `false`.
2. **Given** a transcript contains general lesson research requests (e.g. "Find three fraction warm-ups"), **When** the local LLM classifies the note, **Then** the route is set to `telegram_agent_task` and it is permitted to route externally.

---

### User Story 4 - First Launch Customisation & Settings (Priority: P4)
As a teacher launching the application for the first time, I want to configure my Obsidian vault directory and custom wake-phrase keyword files, so that the application integrates with my local workspace.

**Why this priority**: Necessary for initial setup and flexibility of different microphone environments or wake-phrase compilation models.

**Independent Test**: Launch the app with no configuration, verify the folder picker appears, select an Obsidian vault, load custom wake-phrase files via settings, and verify they are saved to `settings.json`.

**Acceptance Scenarios**:
1. **Given** the application has no saved settings, **When** launched, **Then** the app prompts the user with a PySide6 folder picker to select the Obsidian vault path.
2. **Given** the settings window is open, **When** a user clicks "Load Keyword", **Then** they can load custom Picovoice Porcupine `.ppn` files for custom wake-word triggers.

---

## Edge Cases & Fail-safes

### Noise Fail-safe (Wake Word Blocked)
* **Problem**: Background classroom noise blocks the wake word engine from detecting "Joshua save" or "Joshua cancel".
* **Solution**: 
  1. **Visual Cue**: The floating widget pulses red starting at 50 seconds to warn the teacher that the recording is approaching the 60-second hard limit.
  2. **Auto-Save**: The recording automatically stops and saves at the 60-second limit (no data is lost).
  3. **Global Hotkeys**: Permanent global keyboard shortcut fallbacks (`Ctrl + Alt + S` for save, `Ctrl + Alt + C` for cancel) are bound and active at all times.

### LLM Offline / Low Confidence Fail-safe
* **Problem**: Local Ollama server is offline, returns an error, or the LLM classification confidence is low.
* **Solution**: 
  1. If Ollama is offline or fails, the policy gate intercepts the error, categorises the note as `sensitive`, and routes the Markdown file directly to the local Obsidian vault review queue (`Obsidian Vault/Classroom Voice Notes/Review Queue/`) with a `review-required` tag.

---

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: The system MUST prompt the user for an Obsidian vault path on first launch and save it to `settings.json`.
* **FR-002**: The settings panel MUST allow dynamic loading of custom Picovoice Porcupine `.ppn` keyword files for wake-word triggers.
* **FR-003**: The app MUST enforce a 60-second hard limit on voice recordings, configurable via settings.
* **FR-004**: State machine transitions MUST update the floating visual widget state with a latency of less than 50ms.
* **FR-005**: The floating widget MUST begin pulsing red when the recording time reaches 50 seconds.
* **FR-006**: The local LLM classifier (`qwen3.5:latest` and `phi4:14b`) MUST evaluate all transcripts for student-sensitive information.
* **FR-007**: Any note containing achievement, behaviour, absences, achievement, early pickup, or welfare information MUST be classified as sensitive and blocked from external routing.
* **FR-008**: An audit log entry MUST be created for every recording session recording transition timestamps, transcript character count, classification decisions, and output path.

### Key Entities

* **VoiceNoteSession**: Represents an active recording instance. Includes Session ID, audio buffer path, start/end timestamps, transcript, classification metadata, and routing outcome.
* **Configuration**: Represents the local app state in `settings.json` (Obsidian path, Porcupine keys/keywords, recording limits, model names).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: Floating widget state changes reflect PySide6 UI state transitions within 50ms.
* **SC-002**: The local privacy gate correctly intercepts 100% of student-sensitive transcripts in simulated tests and forces local-only routing.
* **SC-003**: Average local transcription and Ollama classification pipeline latency is under 5 seconds for a standard 15-second voice note.
* **SC-004**: No temporary audio files are left on disk after transcription is finalised or when a recording session is cancelled.
