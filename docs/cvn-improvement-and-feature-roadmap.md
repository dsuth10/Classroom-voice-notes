# Classroom Voice Notes (CVN) — Comprehensive Improvement & Feature Roadmap

**Document Version:** 1.0  
**Status:** Living Document / Active Tracking  
**Target Platform:** Windows-First Desktop Application (PySide6, local Whisper, local Ollama, Obsidian, Supabase Broker)  
**Primary User:** Classroom Teachers (Hands-free professional reflection, observation, and workflow capture)  
**Core Safety Principle:** Private classroom records stay strictly local on the classroom device by default.

---

## 🧭 Executive Summary & Track Index

This document provides a systematic, prioritised roadmap for all future features, operational hardening, UX enhancements, and pedagogical workflows in Classroom Voice Notes.

Each item includes an **Objective**, **Technical Specification**, **Files Affected**, **Acceptance Criteria**, and **Status Tracking Checkbox**.

| Track | Focus Domain | Primary Impact | Status |
|---|---|---|---|
| **Track 1** | [Audio Capture, Acoustics & Classroom Experience](#track-1-audio-capture-acoustics--classroom-experience) | Hands-free reliability in noisy rooms | 🟡 In Progress |
| **Track 2** | [Pedagogical Intelligence & Australian Curriculum v9](#track-2-pedagogical-intelligence--australian-curriculum-v9) | High-value teaching & reporting insights | ⚪ Planned |
| **Track 3** | [Desktop UI, UX & Daily Usability Upgrades](#track-3-desktop-ui-ux--daily-usability-upgrades) | Frictionless classroom workflow | ⚪ Planned |
| **Track 4** | [Privacy, Security & Local Data Governance](#track-4-privacy-security--local-data-governance) | Strict compliance with Australian Privacy Principles | 🟡 In Progress |
| **Track 5** | [Outbound Sharing, Multi-Agent & Cloud Broker](#track-5-outbound-sharing-multi-agent--cloud-broker) | Verified agent tasks & record export | 🟡 Staging Ready |
| **Track 6** | [Testing, Performance & Observability](#track-6-testing-performance--observability) | Zero-regression automated quality gates | 🟡 In Progress |

---

## Track 1: Audio Capture, Acoustics & Classroom Experience

### 1.1 Non-Intrusive Audio Earcons (Sound Cues)
- [x] **Status:** Completed
- **Objective:** Give the teacher clear acoustic confirmation of state changes (e.g. recording started, saved, or discarded) so they can use the system without needing visual contact with the screen.
- **Specification:**
  - Create short, high-fidelity, non-intrusive sound cues (`.wav` format):
    - `cue_start.wav`: Low-latency double-tone when wake phrase is detected or recording begins.
    - `cue_saved.wav`: Soft confirmation chime when note is successfully written.
    - `cue_cancelled.wav`: Muted descending tone when note is discarded or cancelled.
    - `cue_error.wav`: Subtle low double-tone on pipeline failure.
  - Implement `AudioCueManager` using procedural in-memory WAV synthesis and non-blocking asynchronous playback.
  - Add volume control and toggle in Settings (`audio.earcons_enabled`, `audio.earcons_volume`).
- **Files Affected:**
  - `app/audio/cue_manager.py` (Created)
  - `app/controller.py` (Integrated)
  - `app/config/settings.py` (Integrated)
  - `app/ui/main_window.py` (Integrated with test button)
  - `tests/unit/test_cue_manager.py` (Tested)
- **Acceptance Criteria:**
  - Cues play instantaneously without blocking the main event loop or audio capture stream.
  - Cues do not feed back into the active recording stream.

---

### 1.2 Real-Time Classroom Acoustic Noise Suppression
- [ ] **Status:** Not Started
- **Objective:** Filter out ambient student chatter, HVAC noise, and chair rustling so Whisper transcribes the teacher's voice cleanly.
- **Specification:**
  - Implement a real-time spectral noise gate or lightweight filter (`rnnoise` or `webrtcvad`) in `AudioInputManager`.
  - Process raw 16 kHz PCM chunks before appending to the pre-roll and active recording buffers.
  - Expose a sensitivity toggle (`audio.noise_suppression_enabled`, `audio.noise_gate_threshold_db`) in Settings.
- **Files Affected:**
  - `app/audio/input_manager.py`
  - `app/audio/noise_filter.py` (New)
  - `app/ui/main_window.py`
- **Acceptance Criteria:**
  - Speech transcription accuracy in simulated 65 dB classroom background noise improves by $\ge 20\%$.
  - CPU overhead of the filter remains $< 3\%$ on typical teacher laptop hardware.

---

### 1.3 Australian Educational Vocabulary & Prompt Seeding in Whisper
- [ ] **Status:** Not Started
- **Objective:** Eliminate speech-to-text hallucinations and misspellings for Australian curriculum jargon, subject acronyms, and phonics terms.
- **Specification:**
  - Configure `WhisperTranscriber` to supply an initial prompt string to `whisper.cpp`:
    ```text
    "Classroom notes in Australian English: NAPLAN, HASS, DigiTech, DesignTech, subitising, phonemes, digraphs, working mathematically, C2C, QCAA."
    ```
  - Dynamically inject active student first names from `student_registry.json` into the prompt bias list (while keeping names strictly local).
- **Files Affected:**
  - `app/transcription/transcriber.py`
  - `app/transcription/worker.py`
- **Acceptance Criteria:**
  - Australian curriculum acronyms and phonetic terminology transcribe with $\ge 95\%$ accuracy.

---

## Track 2: Pedagogical Intelligence & Australian Curriculum v9

### 2.1 Australian Curriculum v9 (AC v9) Content Descriptor Auto-Tagging
- [ ] **Status:** Not Started
- **Objective:** Automatically classify subject observations into specific Australian Curriculum v9 strands and suggest relevant Content Descriptors (e.g. `AC9M5N01`, `AC9E5LY02`).
- **Specification:**
  - Build an offline taxonomy lookup table for Year 3–6 Australian Curriculum v9:
    - Mathematics (Number, Algebra, Measurement, Space, Statistics, Probability).
    - English (Language, Literature, Literacy).
    - Science (Understanding, Inquiry, Human Endeavour).
    - HASS (History, Geography, Civics & Citizenship, Economics & Business).
    - Technologies (Digital Technologies, Design & Technologies).
  - Expand `OllamaClassifier` prompt and schema to match curriculum content descriptors based on spoken context (e.g. "adding fractions with unlike denominators" $\rightarrow$ `AC9M5N04`).
  - Write suggested codes into note frontmatter under `curriculum_v9: ["AC9M5N04"]`.
- **Files Affected:**
  - `app/ollama_router/classifier.py`
  - `app/destinations/note_templates.py`
  - `app/curriculum/ac_v9_data.json` (New)
  - `app/curriculum/matcher.py` (New)
- **Acceptance Criteria:**
  - Subject notes contain accurate AC v9 codes in frontmatter without manual teacher lookup.

---

### 2.2 Longitudinal Student Growth & Formative Assessment Timeline
- [ ] **Status:** Not Started
- **Objective:** Allow teachers to instantly view a student's observation history and formative progress across terms.
- **Specification:**
  - Enhance `StudentIndexBuilder` to generate rich, Dataview-compatible student index cards inside Obsidian (`Classroom Voice Notes/Student Index.md` and individual student pages).
  - Categorise entries into: Academic Progress, Misconceptions Resolved, Behaviour & Wellbeing, Parent Communications.
- **Files Affected:**
  - `app/destinations/student_index.py`
  - `app/destinations/obsidian_writer.py`
- **Acceptance Criteria:**
  - Regenerated student index pages render chronological timelines with backlinks to original notes.

---

### 2.3 End-of-Week Teaching Reflection & Misconception Digest
- [ ] **Status:** Not Started
- **Objective:** Provide a Friday afternoon summary of common student misconceptions and curriculum coverage across the week to inform the following week's planning.
- **Specification:**
  - Create `WeeklyDigestBuilder` scanning the last 5 school days.
  - Group observations by learning area, highlighted misconceptions, and follow-up reminders.
  - Save as `Classroom Voice Notes/Weekly Digests/Week_XX_Digest.md`.
- **Files Affected:**
  - `app/destinations/weekly_digest.py` (New)
  - `app/ui/recording_indicator.py` (Context menu action)
- **Acceptance Criteria:**
  - Digest cleanly aggregates all logged misconceptions and tasks with links to source notes.

---

## Track 3: Desktop UI, UX & Daily Usability Upgrades

### 3.1 System Tray Minimisation & Background Daemon
- [x] **Status:** Completed
- **Objective:** Allow the app to run unobtrusively during teaching without occupying space in the Windows taskbar.
- **Specification:**
  - Implement `QSystemTrayIcon` in `MainWindow` and `run.py`.
  - Closing the main settings window minimises to tray rather than exiting.
  - Tray menu provides: *Status indicator, Outbox Review Queue, Today's Notes, Settings, Quit*.
- **Files Affected:**
  - `app/ui/main_window.py` (Added `closeEvent` and settings)
  - `run.py` (Integrated system tray)
- **Acceptance Criteria:**
  - Application survives window closure and continues listening for wake phrases in the background.

---

### 3.2 Global Hotkey Support (`Win+Shift+V`)
- [x] **Status:** Completed
- **Objective:** Provide instant manual toggle for recording when the teacher is at their desk or smartboard, even if another application is focused.
- **Specification:**
  - Register a native Windows global hotkey (e.g. `Win+Shift+V` or `Ctrl+Alt+Space`) via `ctypes` / Windows API hook.
  - Pressing hotkey toggles `RECORDING` $\leftrightarrow$ `IDLE_LISTENING`.
  - Configurable hotkey in Settings (`system.hotkey_enabled`, `system.hotkey_sequence`).
- **Files Affected:**
  - `app/utils/global_hotkey.py` (Created)
  - `app/controller.py` (Integrated `toggle_recording`)
  - `app/ui/main_window.py` (Integrated settings)
  - `tests/unit/test_global_hotkey.py` (Tested)
- **Acceptance Criteria:**
  - Hotkey reliably starts and stops recording from any active Windows application.

---

### 3.3 Quick-Capture Overlay HUD & 5-Second Undo Toast
- [ ] **Status:** Not Started
- **Objective:** Give the teacher an immediate glance at what was recognised, with a one-click undo if the note was captured by mistake.
- **Specification:**
  - Add an expanding toast notification attached to `RecordingIndicator`:
    - Displays: Category badge, recognised title, 1-line transcript summary.
    - Action buttons: `Undo / Delete`, `Edit in Obsidian`, `Dismiss`.
    - Auto-dismisses after 5 seconds if uninterrupted.
- **Files Affected:**
  - `app/ui/recording_indicator.py`
  - `app/controller.py`
- **Acceptance Criteria:**
  - Clicking "Undo" immediately deletes the generated note and audio file, logging a `USER_DISCARD_UNDO` audit event.

---

### 3.4 In-App Student Registry & Class Manager UI
- [ ] **Status:** Not Started
- **Objective:** Allow teachers to easily add/edit student first names, nicknames, and anonymised IDs directly in the GUI without manually editing JSON.
- **Specification:**
  - Add a dedicated **Student Registry** tab in `MainWindow`:
    - Table view of: *Anonymised ID, Display Name, First Name, Aliases/Nicknames, Active Status*.
    - Add, Edit, Delete, Import CSV, Export CSV actions.
    - Direct validation against reserved privacy keywords.
- **Files Affected:**
  - `app/ui/student_registry_widget.py` (New)
  - `app/ui/main_window.py`
  - `app/privacy/student_registry.py`
- **Acceptance Criteria:**
  - Modifying students instantly updates `student_registry.json` and updates the active policy gate matcher without restarting the application.

---

## Track 4: Privacy, Security & Local Data Governance

### 4.1 Automated Local Audio Retention & Auto-Purge Policy
- [ ] **Status:** Not Started
- **Objective:** Comply with privacy policies by automatically purging raw WAV audio files after transcripts have been verified, while keeping the Markdown notes.
- **Specification:**
  - Add setting `privacy.audio_retention_days` (Options: *Never, 7 Days, 14 Days, 30 Days*).
  - Background startup task checks `Vault/Classroom Voice Notes/Audio/` and deletes `.wav` files older than the retention threshold.
  - Log audit events for every purged audio file (`AUDIO_RETENTION_PURGE`).
- **Files Affected:**
  - `app/utils/retention_manager.py` (New)
  - `app/controller.py`
  - `app/ui/main_window.py`
- **Acceptance Criteria:**
  - Audio files older than retention period are deleted cleanly; corresponding markdown note files remain intact.

---

### 4.2 Windows DPAPI Local Registry Encryption at Rest
- [ ] **Status:** Not Started
- **Objective:** Protect the student name-to-ID lookup mapping on shared classroom workstations when the machine is locked.
- **Specification:**
  - Store sensitive cryptographic seed or encrypted registry blob using Windows Data Protection API (DPAPI) via `keyring` or `win32crypt`.
- **Files Affected:**
  - `app/config/keyring_store.py`
  - `app/privacy/student_registry.py`
- **Acceptance Criteria:**
  - `student_registry.json` cannot be decrypted under another Windows user account.

---

### 4.3 Pydantic Formal JSON Schema Enforcement for Ollama Classifier
- [ ] **Status:** Not Started
- **Objective:** Eliminate JSON parsing glitches and markdown backtick wrapping from Ollama by utilising Ollama's native structured outputs (`format: json_schema`).
- **Specification:**
  - Define `ClassificationResult` as a Pydantic `BaseModel`.
  - Pass `format: ClassificationResult.model_json_schema()` directly to the Ollama HTTP API endpoint.
- **Files Affected:**
  - `app/ollama_router/classifier.py`
  - `app/ollama_router/schemas.py` (New)
- **Acceptance Criteria:**
  - Classifier response is guaranteed to parse into structured fields without regular expression cleanup.

---

## Track 5: Outbound Sharing, Multi-Agent & Cloud Broker

### 5.1 Phase 2E Staging Acceptance & Gate B Execution
- [ ] **Status:** Staging Ready
- **Objective:** Execute the synthetic end-to-end acceptance run in the staging Supabase broker and complete Gate B documentation.
- **Specification:**
  - Run `scripts/run_staging_integration_tests.py` against staging endpoints.
  - Verify 1-enqueue $\rightarrow$ 1-claim $\rightarrow$ 1-execution $\rightarrow$ 1-completion $\rightarrow$ 1-reconciliation.
  - Audit remote database to verify zero raw classroom transcripts or audio paths appear in staging tables.
  - Complete [docs/gate-b-staging-evidence.md](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/docs/gate-b-staging-evidence.md).
- **Files Affected:**
  - `docs/gate-b-staging-evidence.md`
  - `docs/phase-2e-delivery-plan.md`
- **Acceptance Criteria:**
  - All staging acceptance criteria pass with zero security or data leakage findings.

---

### 5.2 Desktop Registered Client Identity (`x-cvn-key-id`)
- [ ] **Status:** Planned (Phase 3 Pre-requisite)
- **Objective:** Migrate desktop submission from the restricted legacy bearer/HMAC client path to cryptographic registered client identity.
- **Specification:**
  - Implement client key registration and header injection (`x-cvn-key-id: client_<id>`) in `OutboundSubmissionService`.
  - Update Supabase `cvn-submit-outbound-item` to enforce registered client entitlement lookup.
- **Files Affected:**
  - `app/destinations/outbound_submission_service.py`
  - `supabase/functions/cvn-submit-outbound-item/index.ts`
- **Acceptance Criteria:**
  - Desktop client proves its registered identity on every signed request.

---

### 5.3 Bi-directional Agent Deliverables in Obsidian
- [ ] **Status:** Planned
- **Objective:** Automatically render agent deliverables (e.g. generated maths quiz, lesson plan draft) directly into a dedicated section of the originating Obsidian note when completed by OpenClaw.
- **Specification:**
  - On status reconciliation, extract `result.deliverable_markdown` from the worker response.
  - Append to the note under `## Agent Deliverable` and update frontmatter `status: completed`.
- **Files Affected:**
  - `app/destinations/external_agent_dispatcher.py`
  - `app/destinations/obsidian_writer.py`
- **Acceptance Criteria:**
  - Completed agent outputs seamlessly integrate into the teacher's Obsidian vault without copy-pasting.

---

## Track 6: Testing, Performance & Observability

### 6.1 End-to-End Latency Benchmarking
- [ ] **Status:** Not Started
- **Objective:** Continuously profile pipeline latency (Mic stop $\rightarrow$ Whisper $\rightarrow$ Ollama $\rightarrow$ Obsidian write) to ensure hands-free response feels instantaneous.
- **Specification:**
  - Add granular timing telemetry in `PipelineWorker` (`t_transcribe_ms`, `t_classify_ms`, `t_write_ms`).
  - Target: Total processing time $< 2.5\text{ seconds}$ for a 15-second voice note.
- **Files Affected:**
  - `app/transcription/worker.py`
  - `app/audit/audit_logger.py`

---

### 6.2 Simulated Classroom Acoustic Test Fixtures
- [ ] **Status:** Not Started
- **Objective:** Automated integration tests with noisy audio samples to prevent regressions in wake-word detection and Vosk command accuracy.
- **Specification:**
  - Add synthetic test WAV fixtures in `tests/fixtures/audio/` containing:
    - Clean voice commands (`save`, `cancel`, `stop`).
    - Spoken commands mixed with 60 dB cafeteria/classroom background noise.
    - Phonetic distractors (`can`, `camera`, `candy`).
- **Files Affected:**
  - `tests/fixtures/audio/` (New)
  - `tests/unit/test_command_engine_noisy.py` (New)

---

## 📊 Priority Matrix & Delivery Roadmap

```text
[High Impact / Immediate]
 ├── 1.1 Audio Earcons / Sound Cues (Hands-free confidence)
 ├── 3.1 System Tray & 3.2 Global Hotkey (Daily workflow ease)
 ├── 4.3 Pydantic Structured JSON Schema for Ollama (Stability)
 └── 5.1 Phase 2E Staging Acceptance Run (Milestone completion)

[Medium Term / Pedagogical Value]
 ├── 1.2 Acoustic Classroom Noise Suppression
 ├── 2.1 Australian Curriculum v9 Content Descriptor Auto-Tagging
 ├── 3.4 In-App Student Registry Manager UI
 └── 4.1 Automated Local Audio Retention & Auto-Purge Policy

[Long Term / Cloud & Multi-Agent]
 ├── 5.2 Registered Client Identity Migration (x-cvn-key-id)
 ├── 5.3 Bi-directional Agent Deliverables in Obsidian
 └── 2.2 Longitudinal Student Growth & Formative Timeline
```

---

## 📝 Change Log & Progress Record

| Date | Track / Item | Change Description | Author | Status |
|---|---|---|---|---|
| 2026-08-17 | All | Created master improvement and feature tracking roadmap | Douglas Sutherland | Active |
| 2026-08-17 | Track 1.1, 3.1, 3.2 | Implemented Audio Earcons (`cue_manager`), Global Hotkey (`Win+Shift+V`), and System Tray minimisation | Antigravity Pair Programmer | Completed |
