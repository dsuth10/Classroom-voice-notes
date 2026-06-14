# Classroom Voice Notes Constitution

## Core Principles

### I. Private Classroom Information Stays Local
All sensitive educational and student information MUST remain local on the teacher's device. Achievement data, behaviour notes, absences, welfare details, student names, and parent details are non-negotiable local-only content. Cloud services are strictly forbidden for sensitive data processing.

### II. Hard-Coded Policy Gate Superpowers LLM
The local Large Language Model (LLM) suggests the classification and routing of a transcribed note, but a hard-coded privacy policy gate makes the final decision. If a student name or sensitive keyword is present, external routes (like Telegram) are blocked, and the note is kept local.

### III. When in Doubt, Review Queue
If there is any uncertainty during classification, if the audio transcript is unclear, or if local services are offline, the app MUST default to writing the note to the local Obsidian review queue rather than failing or routing externally.

### IV. UX Consistency: Floating Widget Responsiveness & Voice-First Design
- **Floating Widget Responsiveness**: The floating recording widget is the primary visual feedback mechanism. Any changes in the state machine (e.g., wake phrase detected, recording started/ended, transcribing, routing) MUST reflect on the floating widget immediately (visual state transition latency should be sub-50ms).
- **Voice-First Navigation**: The user interface is designed with a roadmap toward 100% voice navigation (i.e. wake-phrase control for all state transitions). There are no strict traditional accessibility standards (such as keyboard-only navigation) required, though standard physical hotkey fallbacks are maintained purely as classroom noise fail-safes.

### V. Short Recording Cap
To prevent continuous or accidental recording in the classroom, a hard recording cap (defaulting to 60 seconds, configurable up to 300 seconds) is strictly enforced. The user must receive immediate visual indicator changes and optionally audio cues when recording begins and ends.

### VI. Language & Formatting Guidelines
All generated documentation, code comments, and user-facing text MUST adhere to:
- **Australian Spelling**: Standardise spelling using Australian conventions (e.g., *behaviour*, *organisation*, *customisation*, *optimisation*, *minimised*, *programme*).
- **Metric System**: Use metric measurements (e.g., Celsius, metres, grams).
- **Dual-Width Tables**: For exported reports/DOCX, ensure dual-width specifications.

---

## Technical Constraints

- **Technology Stack**: Python MVP, PySide6 desktop interface, Picovoice Porcupine wake-word engine, whisper.cpp transcription engine (`base.en`/`small.en` models), local Ollama server (`http://localhost:11434`).
- **Ollama Models**: Initial routing will use `qwen3.5:latest` for rapid first-pass classification, and `phi4:14b` for second-pass review when ambiguity or sensitivity is detected.
- **Latency Testing**: The system architecture must allow benchmarking and swap-testing of different local models to optimise latency once the basic pipeline is established.
- **Obsidian Vault Structure**: Notes must be output as markdown files with Frontmatter metadata under the configured vault subdirectory (`Classroom Voice Notes/`).

---

## Development Workflow & Coding Guidelines

1. **Strict Type Annotations**: To ensure robust, self-documenting code, Python static type hints are strictly enforced across the entire codebase. All functions, methods, and classes must pass `mypy` verification.
2. **Testing Standards**:
   - Core routing logic and the policy gate require comprehensive unit tests.
   - Integration tests are permitted (and encouraged) to run against actual running local instances of dependencies (such as the local Ollama server and local file system) to verify real-world pipeline performance.
3. **Audit Logging**: Every transition in the state machine (Starting, Idle listening, Recording, Transcribing, Classifying, Policy checking, Routing) must be recorded in a local audit log file for security compliance.

**Version**: 1.1.0 | **Ratified**: 2026-06-14
