# Classroom Voice Notes

**Classroom Voice Notes** is a local-first desktop application designed for teachers. It enables hands-free professional reflection, lesson observation capture, behaviour reflection, and quick workflow tasks using local wake-phrase detection, audio recording, local transcription (via `whisper.cpp`), and local LLM routing (via `Ollama`).

---

## 📖 Product Philosophy & Positioning
* **A hands-free teacher note-taking tool** for short professional reflections, observations, reminders, and workflow capture.
* **Local-first by design:** Teacher observations and sensitive school records remain entirely offline.
* **Privacy-preserving:** A strict policy gate ensures that student names, behaviour records, achievement logs, and welfare notes never leave the local machine.

---

## 🏗️ System Architecture & Workflow

```text
Teacher wears lavalier microphone
        ↓
App listens locally for wake phrase ("Joshua note")
        ↓
Teacher speaks a short note (max 60 seconds by default)
        ↓
Teacher speaks command ("Joshua save") or clicks Hotkey (Ctrl + Alt + S)
        ↓
App stops recording and transcribes audio locally via whisper.cpp
        ↓
Transcript is classified by a local Ollama model (e.g. qwen3.5:latest)
        ↓
Hard-coded Privacy Policy Gate evaluates sensitivity
        ↓
Note is saved locally to Obsidian vault in clean Markdown format
```

---

## 🛠️ Main Features
1. **Wake-Phrase Recognition:** Runs locally using `openWakeWord` to detect wake phrases like *"Joshua note"*.
2. **Spoken Command Controls:** Built-in `Vosk` engine handles hands-free voice commands (*"save"*, *"stop"*, *"cancel"*, *"discard"*).
3. **Manual Fallback Hotkeys:** Always-on keyboard shortcuts to override or assist in noisy classrooms:
   * **Start Recording:** `Ctrl + Alt + N`
   * **Stop and Save:** `Ctrl + Alt + S`
   * **Cancel Recording:** `Ctrl + Alt + C`
   * **Pause Listening:** `Ctrl + Alt + P`
4. **Local Transcription (`whisper.cpp`):** High-speed local transcription using `whisper.cpp` binaries.
5. **Automatic Model Bootstrapping:** If the `ggml-base.en.bin` Whisper model file is missing during first launch or transcription, it automatically downloads from Hugging Face without freezing the user interface.
6. **Obsidian Vault Integration:** Categorises notes automatically with YAML frontmatter, saving them into dedicated folders:
   * `Student Notes/` (achievement, support, wellbeing)
   * `Behaviour Notes/` (observations and classroom management)
   * `Maths Notes/` (misconceptions and teaching observations)
   * `Reminders/` (time-sensitive reminders)
   * `Email Drafts/` (comms drafts requiring review)
   * `Agent Task Archive/` (archived external prompts)
   * `Review Queue/` (uncertain or flagged logs)
   * `Inbox/` (uncategorised general notes)
7. **Privacy Policy Gate:** Evaluates LLM classifications and blocks any student-sensitive data from leaving the local machine. Only non-sensitive agent planning tasks may route to external channels like Telegram.

---

## 📂 Project Structure

```text
Classroom voice notes/
├── app/                        # Application Source Code
│   ├── audio/                  # Audio recording and microphone pipeline
│   ├── audit/                  # Security audit logging engine
│   ├── commands/               # Vosk spoken command recognition
│   ├── config/                 # Application settings manager (settings.json)
│   ├── destinations/           # Obsidian file writing and routing
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
Ensure you have the following installed on your machine:
* Python 3.9+ (Windows-first application)
* [Ollama](https://ollama.com/) (running locally)
* [Obsidian](https://obsidian.md/) (for vault storage)

### 2. Dependency Installation
This project uses `uv` for package management. To install all dependencies, run:
```bash
uv sync
```

### 3. Local LLM Initialisation
Pull the recommended routing and classification models:
```bash
ollama pull qwen3.5:latest
ollama pull phi4:14b
```

### 4. Running the Application
To launch the desktop application, run:
```bash
uv run run.py
```
On the first launch, you will be prompted to select your Obsidian vault path.

---

## 🧪 Running Tests
To execute the test suite (unit and integration tests), run:
```bash
uv run pytest
```
All tests are mocked to run safely without requiring external audio hardware or server calls.

---

## 🛡️ Audit & Security
All operations (state transitions, wake-word triggers, classification results, and privacy blocks) are written to a local `audit.log` file stored in your application data directory to ensure transparency.
