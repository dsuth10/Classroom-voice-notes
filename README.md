# Classroom Voice Notes

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-yellow.svg)](https://www.python.org/)
[![Framework: PySide6](https://img.shields.io/badge/Framework-PySide6-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Platform: Windows First](https://img.shields.io/badge/Platform-Windows%20First-lightgrey.svg)]()

**Classroom Voice Notes** is a local-first, privacy-respecting desktop application designed for teachers. It enables hands-free lesson reflection, student observations, behaviour logs, reminders, and workflow automation. Using local wake-phrase detection, audio recording, local transcription (via `whisper.cpp`), and local LLM routing (via `Ollama`), teachers can document their classroom in real time without sacrificing student privacy.

---

## 📖 Product Philosophy & Positioning
* **Hands-Free Classroom Integration:** Designed for busy classrooms. Teachers wear a wireless/lavalier microphone and dictate thoughts as they happen.
* **Local-First & Offline Design:** Sensitive school records, student details, achievement logs, and behavioural observations remain strictly offline in a local Obsidian Vault.
* **Strict Privacy Policy Gate:** A hard-coded, zero-trust policy gate acts as the final arbiter for external transmission. Student-sensitive details are completely blocked from external integrations, while non-sensitive instructions can route to external agents.

---

## 🏗️ System Architecture & Workflow

```text
       [Teacher Voice]
              │
              ▼
   ┌──────────────────────────────────────────────┐
   │ 1. Local Wake-Word Engine (openWakeWord)     │  <── Listens for "Joshua note"
   └──────────────────────┬───────────────────────┘
                          │ (Triggered)
                          ▼
   ┌──────────────────────────────────────────────┐
   │ 2. Audio Capture & Spoken Command Recognition │  <── Listens for "save" / "cancel" via Vosk
   └──────────────────────┬───────────────────────┘
                          │ (Stopped & Saved)
                          ▼
   ┌──────────────────────────────────────────────┐
   │ 3. Local Transcription (whisper.cpp)          │  <── High-speed C++ Whisper implementation
   └──────────────────────┬───────────────────────┘
                          │ (Raw text transcript)
                          ▼
   ┌──────────────────────────────────────────────┐
   │ 4. Two-Pass LLM Router (Ollama - qwen3.5)    │  <── Generates title, category, metadata, tags
   └──────────────────────┬───────────────────────┘
                          │ (Classification Data)
                          ▼
   ┌──────────────────────────────────────────────┐
   │ 5. Local Student Privacy Registry             │  <── Maps real names to IDs (e.g. STU-001)
   └──────────────────────┬───────────────────────┘
                          │ (Anonymised Metadata)
                          ▼
   ┌──────────────────────────────────────────────┐
   │ 6. Hard-Coded Policy Gate Checks             │  <── Validates external transmission limits
   └──────────┬────────────────────────┬──────────┘
              │ (If Telegram Allowed)  │ (Local Save)
              ▼                        ▼
   ┌──────────────────────┐  ┌──────────────────────────────────────────────┐
   │ Telegram Task        │  │ 7. Obsidian Vault Writer (note_templates)    │
   │ Dispatcher           │  └──────────────────────────────────────────────┘
   │ (Hermes/OpenClaw)    │     (Saves formatted Markdown files in: Inbox,  
   └──────────────────────┘      Student Notes, Behaviour Notes, Maths, HASS...)
```

---

## 🛠️ Feature Set

### 1. Hands-Free Spoken Control & Manual Hotkeys
* **Wake-Phrase Recognition:** Runs locally using `openWakeWord` to detect wake phrases like *"Joshua note"*.
* **Spoken Command Controls:** Hands-free voice commands (*"save"*, *"stop"*, *"cancel"*, *"discard"*) managed via a lightweight, offline `Vosk` recognition thread.
* **Manual Override Hotkeys:** Global system-wide hotkeys override or assist in noisy classrooms:
  * **Start Recording:** `Ctrl + Alt + N`
  * **Stop and Save:** `Ctrl + Alt + S`
  * **Cancel Recording:** `Ctrl + Alt + C`
  * **Pause/Resume Listening:** `Ctrl + Alt + P`

### 2. High-Speed Local Transcription & Auto-Bootstrap
* Uses high-performance `whisper.cpp` binaries running locally.
* **Automatic Model Bootstrapping:** If the `ggml-base.en.bin` Whisper model file is missing during startup or transcription, it automatically downloads from Hugging Face asynchronously without freezing the user interface.

### 3. Subject-Specific Note Templates
Observations are generated using tailored Markdown templates with specific YAML metadata and bodies:
* **Student Observations (`student_note`):** Tracks general academic observations and welfare.
* **Behaviour Notes (`behaviour_note`):** Captures incident details (e.g., disruption type, action taken).
* **Subject Notes (`maths_note`, `science_note`, `english_note`, `hass_note`, `digitech_note`, `designtech_note`):** Extracts Australian Curriculum v9 Strands, misconceptions, text types, investigation details, and year levels.
* **Reminders (`reminder`):** Logs scheduled dates and priorities.
* **Email Drafts (`email_draft`):** Prepares communication drafts for review.
* **Agent Tasks (`agent_task`):** Standard task instructions targeting external developer agents.

### 4. Privacy Registry & Name Anonymisation
* **Local Student Registry (`student_registry.json`):** Tracks display names and maps them to unique IDs (e.g., `STU-001`). 
* **Metadata Anonymisation:** Real student names are only kept in the local notes and registry; they are completely stripped from metadata frontmatter, ensuring zero leak risk if metadata is shared or synced. Unknown names are auto-registered locally to avoid data loss.

### 5. Actionable Reminders & `.ics` Generation
* **Reminder Engine:** Scans files on a periodic 30-second timer.
* **Windows System Toast Alerts:** Sends native Windows notifications when a reminder is due.
* **iCalendar Sync (`ics_writer`):** Automatically generates standard `.ics` files saved in `Classroom Voice Notes/Calendar/` for easy syncing with Outlook, Google Calendar, or open-source calendars.

### 6. Review Queue & Life Cycle Management
* If the LLM routing confidence is low, or if the note requires validation, it is saved to the `Review Queue/` directory.
* **Review Manager:** Periodically scans the queue. If you edit a note and tick the review checkboxes (`- [x] Checked transcript`), the system automatically moves it out of the queue and into its appropriate directory. If a note remains unclassified, it utilizes a local `phi4:14b` model to perform a secondary reclassification.

### 7. Multi-Agent Task Dispatcher
* Integrates with external Telegram agents (**Hermes** for planning/instruction and **OpenClaw** for coding/analysis).
* If a note is categorized as an `agent_task` and sensitivity is `non_sensitive` (validated by the Policy Gate), it compiles a structured task payload and dispatches it via the Telegram Bot API.

### 8. Daily Summaries & Student Indexing
* **Student Index (`Student Index.md`):** Automatically scans Obsidian notes, groups files under each student's display name, and compiles a comprehensive local index of observations.
* **Daily Activity Summaries:** Generates `Summary_YYYY-MM-DD.md` listing files created today.
* **Safe Telegram Digest:** Sends a message to the teacher's Telegram at the end of the day with pure count statistics (e.g., *"Daily Summary: 3 Maths Notes, 1 Behaviour Note"*), keeping all PII offline.

---

## 📂 Project Directory Structure

```text
Classroom voice notes/
├── app/                        # Application Source Code
│   ├── audio/                  # Audio recording and microphone pipeline
│   ├── audit/                  # Security audit logging engine
│   ├── commands/               # Vosk spoken command recognition
│   ├── config/                 # Application settings manager (settings.json)
│   ├── destinations/           # Obsidian file writing, templates, index and daily summaries
│   │   ├── daily_summary.py    # Daily activity aggregator
│   │   ├── student_index.py    # Local student notes index compiler
│   │   ├── note_templates.py   # Markdown subject rendering engine
│   │   ├── reminder_engine.py  # Toast reminder worker
│   │   └── telegram_dispatcher.py # Task dispatcher
│   ├── privacy/                # Privacy and student database
│   │   └── student_registry.py # Maps names to STU-xxx IDs
│   ├── ollama_router/          # Ollama classifier & Policy Gate checks
│   ├── transcription/          # whisper.cpp transcription manager
│   ├── ui/                     # PySide6 MainWindow and Recording floating widget
│   └── utils/                  # Helper paths and automatic downloader
├── bin/                        # Binary Executables
│   └── whisper/                # whisper.cpp executables and DLLs
├── models/                     # Local AI Models
│   ├── vosk/                   # Vosk model directory
│   └── wakewords/              # openWakeWord ONNX files
├── specs/                      # Feature specifications and governing constitution
├── tests/                      # Unit and integration test suites
├── pyproject.toml              # Project dependencies and packaging configuration
├── run.py                      # Main entrypoint executable
└── uv.lock                     # UV dependency lockfile
```

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have the following installed on your Windows machine:
* **Python 3.9+**
* [Ollama](https://ollama.com/) (running locally)
* [Obsidian](https://obsidian.md/) (for vault storage)

### 2. Installation
This project uses `uv` for lightning-fast package management. Install dependencies:
```bash
uv sync
```

### 3. Local Model Setup
Pull the recommended routing and reclassification models inside Ollama:
```bash
ollama pull qwen3.5:latest
ollama pull phi4:14b
```

### 4. Running the Application
To launch the application:
```bash
uv run run.py
```
* **First Launch:** A file picker will appear. Select your local Obsidian Vault directory.
* **System Tray:** A glassmorphic widget will float on your screen, indicating current listening state ("Idle Listening", "Recording", "Transcribing"). Right-click it to access Settings, quit, or trigger summaries.

---

## 🧪 Testing
The project includes a robust suite of unit and integration tests. To run them:
```bash
uv run pytest tests/
```
All audio capturing, LLM classification, and Telegram API connections are mocked, allowing tests to run cleanly offline.

---

## 🛡️ Security, Privacy & Standards
* **Australian Spelling & Metric System:** The application is written following Australian English spelling conventions (e.g., *behaviour*, *anonymise*, *organise*) and uses the metric system throughout.
* **Data Locality:** Student achievements, behavioural logs, welfare records, absence reports, and medical information are hard-locked inside the local system.
* **Policy Gate Rules:** Even if the LLM classifier authorizes external routing, the `PolicyGate` rejects transmission if the category is student-sensitive or if transcript keywords suggest personal details.
* **Local Auditing:** All operations (such as classification outputs, state changes, policy block actions, and registry lookups) are written to local logs inside your user data directory (`C:\Users\<User>\.gemini\antigravity-ide\`).

---

## 📄 License
This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
