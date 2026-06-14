# Classroom Voice Notes  
## Local Wake-Phrase Capture, Transcription, Obsidian Storage, and Ollama-Based Routing

**Version:** 1.0  
**Prepared for:** Douglas Sutherland  
**Platform target:** Windows-first  
**Primary environment:** Local desktop app, local microphone input, Ollama local LLM server, Obsidian vault  
**Core principle:** Private classroom information stays local by default.

---

## 1. Product Summary

**Classroom Voice Notes** is a local-first desktop application for teachers. It allows a teacher to walk around the classroom wearing a lavalier or headset microphone and capture short spoken notes hands-free.

The application listens for a wake phrase such as:

> “Joshua note”

It then records a short voice note, transcribes the note locally, uses a local Ollama model to classify the transcript, and routes it to the correct destination.

The main destination is an **Obsidian vault**, where notes are saved as Markdown files. Some non-sensitive work requests may optionally be routed to a Telegram-based agent conversation, but only after a local classifier and hard-coded safety gate confirm that the content is safe to leave the device.

This is not a general classroom recording system. It is a hands-free teacher note-taking tool for short professional reflections, observations, reminders, and workflow capture.

---

## 2. Core User Story

As a classroom teacher, I want to capture short spoken notes hands-free during lessons, so that I can remember teaching observations, misconceptions, behaviour patterns, student reminders, and follow-up tasks without interrupting my teaching flow.

---

## 3. Product Positioning

The app should be described as:

> A hands-free teacher note-taking tool for short professional reflections and observations.

Avoid describing it as:

- classroom surveillance,
- student monitoring,
- behaviour tracking software,
- automatic classroom recording,
- student profiling software.

The design should make clear that the teacher is deliberately capturing short professional notes, not recording the classroom continuously.

---

## 4. High-Level Workflow

```text
Teacher wears lavalier microphone
        ↓
App listens locally for wake phrase
        ↓
Teacher says: “Joshua note”
        ↓
App starts recording
        ↓
Teacher speaks a short note
        ↓
Teacher says: “Joshua save”
        ↓
App stops recording
        ↓
Audio is transcribed locally
        ↓
Transcript is classified by local Ollama model
        ↓
Hard-coded privacy policy gate checks the result
        ↓
Note is routed to Obsidian, local reminder queue, local email draft, review queue, or optional Telegram agent task
        ↓
Audit log records what happened
```

---

## 5. Key Product Principles

### 5.1 Local-first by default

The app should operate without cloud dependencies for its core workflow.

Core local components:

- local microphone capture,
- local wake-word detection,
- local audio file storage,
- local transcription,
- local Ollama classification,
- local Obsidian Markdown output,
- local audit log.

### 5.2 Sensitive information never leaves the computer by default

Any note that contains student names, behaviour information, achievement information, welfare information, absence details, early pickup details, family details, or other private school-related information must remain local.

### 5.3 The LLM suggests, but policy decides

The local LLM can classify and recommend a route, but the final routing decision must be controlled by hard-coded policy rules.

```text
LLM suggests.
Policy gate decides.
Router acts.
```

### 5.4 When unsure, keep it local

If the classifier is uncertain, if the transcript is unclear, if Ollama is unavailable, or if the note may contain sensitive information, the app should save the note locally to an Obsidian review queue.

### 5.5 Short recordings only

The app should be designed around short voice notes, not long recordings.

Recommended default:

```text
Hard recording cap: 60 seconds
```

The user should be able to adjust the cap in the settings interface.

### 5.6 Visible recording state

When the app is recording, it should make that visible.

The first version can use:

- a flashing desktop indicator,
- a changed system tray icon,
- optional start and stop beeps,
- a small always-on-top corner widget.

The visible indicator should be able to be switched on or off in settings.

---

## 6. Major System Components

```text
app/
  main.py

  config/
    settings.py
    defaults.py

  audio/
    microphone.py
    recorder.py
    wav_writer.py

  wakeword/
    porcupine_listener.py
    command_router.py

  transcription/
    transcriber.py
    whisper_cpp_runner.py

  ollama_router/
    ollama_client.py
    classifier.py
    schema.py
    prompts.py
    policy_gate.py

  destinations/
    obsidian_writer.py
    reminder_store.py
    telegram_sender.py
    email_draft_writer.py
    review_queue_writer.py

  audit/
    audit_logger.py

  ui/
    main_window.py
    settings_window.py
    tray_icon.py
    recording_indicator.py

  utils/
    paths.py
    time_utils.py
    sanitise.py
```

---

## 7. Recommended Technology Stack

### 7.1 Application language

Recommended for MVP:

```text
Python
```

Reason:

- fast prototyping,
- strong audio libraries,
- simple file handling,
- easy Ollama HTTP integration,
- good desktop UI options,
- suitable for a junior developer.

A later version could be rewritten in C#/.NET if a more Windows-native product is desired.

### 7.2 Desktop UI

Recommended:

```text
PySide6
```

Use PySide6 for:

- main settings window,
- microphone dropdown,
- vault folder picker,
- system tray support,
- floating recording indicator,
- app state display.

### 7.3 Wake-word detection

Recommended:

```text
Picovoice Porcupine
```

Use it for:

- “Joshua note”,
- “Joshua save”,
- “Joshua cancel”,
- “Joshua maths note”,
- “Joshua behaviour note”,
- “Joshua reminder”,
- “Joshua task”,
- “Joshua research”,
- “Joshua email”.

Important implementation note:

Porcupine wake phrases are not just typed strings. Each custom phrase may need a trained keyword file. The app should represent each command as:

```text
display phrase + keyword model file + action
```

### 7.4 Audio recording

Recommended initial format:

```text
WAV
```

WAV should be used first because it is simple, reliable, and widely supported by transcription engines.

MP3 export can be added later as a storage-saving option.

### 7.5 Transcription

Recommended:

```text
whisper.cpp
```

Suggested starting models:

```text
base.en
small.en
```

For short teacher notes, `base.en` or `small.en` should be a reasonable starting point. Larger models may improve accuracy but increase processing time.

### 7.6 Local LLM classification

Use:

```text
Ollama
```

The app should call Ollama locally through:

```text
http://localhost:11434
```

The classifier should request structured JSON output from a local model.

### 7.7 Optional external task route

Telegram should be treated as optional and off by default.

Telegram should only receive non-sensitive work requests, such as:

- research prompts,
- lesson planning requests,
- resource finding,
- AI agent tasks,
- professional workflow requests.

Telegram should not receive:

- student information,
- parent information,
- behaviour notes,
- assessment information,
- early pickup details,
- welfare details,
- sensitive school operations information.

---

## 8. Installed Ollama Models

Current installed local models supplied by user:

```text
NAME                  ID              SIZE      MODIFIED
glm-5.1:cloud         59472abf9d0a    -         2 months ago
gemma4:26b            5571076f3d70    17 GB     2 months ago
qwen3.5:latest        6488c96fa5fa    6.6 GB    2 months ago
mistral:latest        6577803aa9a0    4.4 GB    4 months ago
phi4-mini:3.8b        78fad5d182a7    2.5 GB    5 months ago
phi3:3.8b             4f2222927938    2.2 GB    5 months ago
llama3.2:latest       a80c4f17acd5    2.0 GB    5 months ago
olmo-3:7b-think       b8d4c92ac9c1    4.5 GB    5 months ago
ministral-3:latest    a5e54193fd34    6.0 GB    6 months ago
gpt-oss:120b-cloud    569662207105    -         6 months ago
phi4:14b              ac896e5b8b34    9.1 GB    6 months ago
qwen3:8b              500a1f067a9f    5.2 GB    8 months ago
```

### 8.1 Recommended model use

| Purpose | Recommended model |
|---|---|
| Fast routing/classification | `qwen3.5:latest` |
| More careful second-pass classification | `phi4:14b` |
| Lightweight fallback | `llama3.2:latest` or `mistral:latest` |
| Avoid for classroom-sensitive routing | cloud models |

### 8.2 Suggested router strategy

Use a two-pass strategy.

#### Pass 1: Fast router

```text
qwen3.5:latest
```

This handles most routing decisions.

#### Pass 2: Careful review

```text
phi4:14b
```

Use the careful model only when:

- confidence is low,
- the transcript may include student information,
- the proposed route is external,
- the transcript asks to email, message, send, contact, or notify someone,
- the transcript includes names,
- the classification is ambiguous.

### 8.3 Do not use cloud models for private routing

Avoid using these for classroom-sensitive classification:

```text
glm-5.1:cloud
gpt-oss:120b-cloud
```

The point of the system is to keep sensitive classification local.

---

## 9. Spoken Command System

### 9.1 Core commands

| Spoken command | Action |
|---|---|
| “Joshua note” | Start general local note |
| “Joshua save” | Stop, transcribe, classify, route |
| “Joshua cancel” | Stop and delete temporary audio |
| “Joshua maths note” | Start note with maths context |
| “Joshua behaviour note” | Start note with behaviour context |
| “Joshua reminder” | Start note as reminder |
| “Joshua task” | Start possible external agent task |
| “Joshua research” | Start possible external agent task |
| “Joshua email” | Start possible email draft |

### 9.2 Commands are hints, not final routing decisions

A command should provide context, but the classifier and policy gate should still decide the final destination.

Example:

```text
Teacher says: “Joshua task.”
Transcript: “At 2:00, Alex needs to go home early.”
```

Even though the teacher said “task”, this must not go to Telegram.

Final route:

```text
local_reminder
```

Reason:

```text
Contains student-sensitive information.
```

### 9.3 Manual fallback controls

Every spoken command needs a manual fallback.

| Action | Backup control |
|---|---|
| Start recording | Ctrl + Alt + N |
| Stop and save | Ctrl + Alt + S |
| Cancel | Ctrl + Alt + C |
| Pause listening | Ctrl + Alt + P |
| Show app | Tray icon double-click |

Classrooms are noisy. Spoken stop commands may fail. Manual fallback must remain permanently available.

---

## 10. App State Machine

```text
STARTING
  ↓
IDLE_LISTENING
  ↓ wake phrase detected
RECORDING
  ↓ save command / hotkey / hard cap / cancel command
TRANSCRIBING
  ↓
CLASSIFYING
  ↓
POLICY_CHECKING
  ↓
ROUTING
  ↓
WRITING_OUTPUT
  ↓
IDLE_LISTENING
```

### 10.1 Error states

```text
MICROPHONE_ERROR
WAKE_ENGINE_ERROR
TRANSCRIPTION_ERROR
OLLAMA_UNAVAILABLE
CLASSIFICATION_ERROR
POLICY_GATE_ERROR
OBSIDIAN_PATH_ERROR
TELEGRAM_BLOCKED
TELEGRAM_ERROR
REMINDER_ERROR
UNKNOWN_ERROR
```

### 10.2 State descriptions

| State | Description | User-visible indicator |
|---|---|---|
| Starting | App is loading settings and services | “Starting…” |
| Idle listening | Listening for wake phrases only | Neutral tray icon |
| Recording | Capturing audio after deliberate trigger | Flashing recording indicator |
| Transcribing | Converting local audio to text | “Transcribing…” |
| Classifying | Local LLM is deciding note type | “Classifying…” |
| Policy checking | Hard rules are checking sensitivity | “Checking privacy…” |
| Routing | Sending to local or approved destination | “Routing…” |
| Writing output | Writing Markdown/log/reminder | “Saving…” |
| Error | Something failed | Warning state |

---

## 11. Recording Behaviour

### 11.1 Recording start

When a start phrase is detected:

1. create a session ID,
2. record start time,
3. set command context,
4. play optional beep,
5. show recording indicator,
6. begin recording audio,
7. write audit log entry.

### 11.2 Recording stop and save

When “Joshua save” or the save hotkey is triggered:

1. stop recording,
2. save temporary WAV file,
3. transcribe locally,
4. classify locally,
5. apply policy gate,
6. route output,
7. write audit log entry,
8. return to idle.

### 11.3 Recording cancel

When “Joshua cancel” or the cancel hotkey is triggered:

1. stop recording,
2. delete temporary audio,
3. do not transcribe,
4. do not create a note,
5. write audit log entry,
6. return to idle.

### 11.4 Hard cap

The app must always enforce a hard recording cap.

Default:

```text
60 seconds
```

User-configurable range:

```text
10 seconds to 300 seconds
```

Recommended classroom setting:

```text
30 to 90 seconds
```

If the hard cap is reached:

1. stop recording automatically,
2. save the audio,
3. process it as normal,
4. mark in metadata that the hard cap stopped the recording.

---

## 12. Visual Recording Indicator

### 12.1 Purpose

The indicator makes recording status obvious even if the main app is minimised.

### 12.2 MVP indicator

A small always-on-top window in the corner of the desktop.

Example:

```text
● Recording
```

### 12.3 Indicator behaviour

| App state | Indicator behaviour |
|---|---|
| Idle | Hidden |
| Recording | Flashing |
| Transcribing | Static “Transcribing…” |
| Error | Warning icon/message |

### 12.4 Indicator settings

| Setting | Type | Default |
|---|---|---|
| Show recording indicator | Toggle | On |
| Indicator position | Dropdown | Top-right |
| Indicator size | Dropdown | Medium |
| Indicator opacity | Slider | 85% |
| Flash while recording | Toggle | On |
| Show while transcribing | Toggle | On |

---

## 13. Obsidian Vault Design

### 13.1 Recommended folder structure

```text
Obsidian Vault/
  Classroom Voice Notes/
    Inbox/
    Student Notes/
    Behaviour Notes/
    Maths Notes/
    Reminders/
    Email Drafts/
    Agent Task Archive/
    Review Queue/
    Daily Summaries/
    Audio/
    Logs/
    Templates/
```

### 13.2 Folder purposes

| Folder | Purpose |
|---|---|
| Inbox | General uncategorised notes |
| Student Notes | Student-specific achievement, support, wellbeing, pickup or learning notes |
| Behaviour Notes | Behaviour and classroom management observations |
| Maths Notes | Maths teaching observations and misconceptions |
| Reminders | Local time-based reminders |
| Email Drafts | Drafted communications requiring review |
| Agent Task Archive | Local archive of safe tasks sent externally |
| Review Queue | Ambiguous or risky notes |
| Daily Summaries | Optional daily roll-up files |
| Audio | Local WAV/MP3 files |
| Logs | Audit logs |
| Templates | Editable Markdown templates |

---

## 14. Markdown Note Format

### 14.1 General note template

```markdown
---
type: classroom-voice-note
route: local_obsidian
sensitivity: teacher_private
created: 2026-06-14 09:15:22
date: 2026-06-14
time: 09:15
category: general_note
status: captured
source: local-voice-note-app
duration_seconds: 34
audio_file: "../Audio/2026-06-14_09-15-22_general_note.wav"
transcription_engine: whisper.cpp
router_model: qwen3.5:latest
telegram_allowed: false
tags:
  - classroom-note
  - teaching-reflection
---

# Teaching Note — 14 June 2026, 9:15 am

## Transcript

Group three has misunderstood the fraction model. Revisit equivalent fractions tomorrow using visual fraction strips before moving back to number-line examples.

## Router Decision

- Route: local_obsidian
- Sensitivity: teacher_private
- Category: general_note
- Telegram allowed: false
- Confidence: 0.91

## Follow-up

- [ ] Review this note.
- [ ] Convert into planning action if needed.

## Review Status

- [ ] Checked transcript
- [ ] Edited for accuracy
- [ ] Added context if needed
```

### 14.2 Student-sensitive note template

```markdown
---
type: classroom-voice-note
route: local_student_note
sensitivity: student_sensitive
created: 2026-06-14 13:15:22
category: reminder
status: active
source: local-voice-note-app
telegram_allowed: false
tags:
  - classroom-note
  - student-sensitive
  - reminder
  - early-pickup
---

# Early Pickup Reminder

## Transcript

At 2:00 pm, Alex needs to go to the office for early pickup.

## Reminder

- [ ] Send Alex to the office at 2:00 pm.

## Privacy

This note contains student-sensitive information and was kept local.

## Review Status

- [ ] Completed
- [ ] Archive when no longer needed
```

### 14.3 Agent task archive template

```markdown
---
type: agent-task
route: telegram_agent_task
sensitivity: non_sensitive
created: 2026-06-14 10:05:12
category: research_task
telegram_allowed: true
sent_to: hermes-agent
status: sent
tags:
  - agent-task
  - maths
  - planning
---

# Agent Task — Fraction Warm-Ups

## Sent Task

Find three Year 5 fraction misconception warm-ups and return practical classroom examples.

## Router Decision

- Route: telegram_agent_task
- Sensitivity: non_sensitive
- Telegram allowed: true
- Confidence: 0.94

## Local Archive

This task was classified as non-sensitive professional planning content and was sent to the configured Telegram agent.
```

### 14.4 Email draft template

```markdown
---
type: email-draft
route: email_draft
sensitivity: teacher_private
created: 2026-06-14 15:20:00
category: email
status: draft
requires_review: true
telegram_allowed: false
tags:
  - email-draft
  - review-required
---

# Email Draft

## Intended recipient

Not yet confirmed.

## Draft purpose

Draft an email based on the captured instruction.

## Draft

[Draft email text goes here.]

## Review Required

- [ ] Check recipient.
- [ ] Check student names/details.
- [ ] Check tone.
- [ ] Check accuracy.
- [ ] Send manually if appropriate.
```

---

## 15. Auditability

The app should maintain a local audit log of significant actions.

### 15.1 Audit log folder

```text
Obsidian Vault/Classroom Voice Notes/Logs/
```

### 15.2 Audit log file naming

```text
audit-log-2026-06.csv
```

### 15.3 Audit log fields

| Field | Example |
|---|---|
| session_id | 20260614-091522-a8f3 |
| start_time | 2026-06-14 09:15:22 |
| end_time | 2026-06-14 09:15:56 |
| duration_seconds | 34 |
| trigger_phrase | Joshua maths note |
| action | saved |
| category | maths |
| sensitivity | teacher_private |
| route | local_obsidian |
| audio_file | Audio/2026-06-14_09-15-22_maths_note.wav |
| markdown_file | Maths Notes/2026-06-14_09-15-22_maths_note.md |
| transcription_status | success |
| classification_status | success |
| policy_gate_result | allowed_local |
| external_send_attempted | false |
| error_message | |

### 15.4 Events to log

| Event | Log it? |
|---|---|
| App started | Yes |
| App closed | Yes |
| Wake phrase detected | Yes |
| Recording started | Yes |
| Recording saved | Yes |
| Recording cancelled | Yes |
| Hard cap reached | Yes |
| Transcription started | Yes |
| Transcription failed | Yes |
| Classification started | Yes |
| Classification failed | Yes |
| Policy gate blocked Telegram | Yes |
| Markdown written | Yes |
| Reminder created | Yes |
| Telegram task sent | Yes |
| Email draft created | Yes |
| Review queue item created | Yes |

---

## 16. LLM Router Design

### 16.1 Router input

The local classifier receives:

```json
{
  "trigger_command": "Joshua reminder",
  "transcript": "At two o'clock, send Alex to the office because he needs to go home early today.",
  "recorded_at": "2026-06-14 13:15:22",
  "duration_seconds": 8
}
```

### 16.2 Router output

The classifier must return strict JSON.

```json
{
  "route": "local_reminder",
  "sensitivity": "student_sensitive",
  "category": "reminder",
  "title": "Early pickup reminder",
  "summary": "Student needs to go to the office at 2:00 pm for early pickup.",
  "tags": ["reminder", "student-sensitive", "early-pickup"],
  "contains_student_information": true,
  "contains_external_task": false,
  "telegram_allowed": false,
  "requires_review": false,
  "recommended_destination": "Obsidian Reminders",
  "reminder_time": "2026-06-14 14:00:00",
  "confidence": 0.94
}
```

---

## 17. Router JSON Schema

```json
{
  "type": "object",
  "properties": {
    "route": {
      "type": "string",
      "enum": [
        "local_obsidian",
        "local_student_note",
        "local_reminder",
        "telegram_agent_task",
        "email_draft",
        "review_queue",
        "discard_cancelled"
      ]
    },
    "sensitivity": {
      "type": "string",
      "enum": [
        "non_sensitive",
        "teacher_private",
        "student_sensitive",
        "school_sensitive",
        "unknown"
      ]
    },
    "category": {
      "type": "string",
      "enum": [
        "general_note",
        "maths",
        "behaviour",
        "reminder",
        "assessment",
        "student_achievement",
        "planning",
        "research_task",
        "email",
        "unknown"
      ]
    },
    "title": {
      "type": "string"
    },
    "summary": {
      "type": "string"
    },
    "contains_student_information": {
      "type": "boolean"
    },
    "contains_external_task": {
      "type": "boolean"
    },
    "telegram_allowed": {
      "type": "boolean"
    },
    "requires_review": {
      "type": "boolean"
    },
    "recommended_destination": {
      "type": "string"
    },
    "reminder_time": {
      "type": ["string", "null"]
    },
    "tags": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "confidence": {
      "type": "number"
    }
  },
  "required": [
    "route",
    "sensitivity",
    "category",
    "title",
    "summary",
    "contains_student_information",
    "contains_external_task",
    "telegram_allowed",
    "requires_review",
    "recommended_destination",
    "reminder_time",
    "tags",
    "confidence"
  ]
}
```

---

## 18. Router Prompt

The classifier prompt should be short, strict, and repeat the safety rules.

Example system prompt:

```text
You are a local routing classifier for a teacher voice-note application.

Your job is to classify a transcript and return strict JSON only.

You must decide:
1. whether the content is sensitive,
2. whether it contains student or school information,
3. whether it can safely leave the device,
4. which local or external route is appropriate.

Hard rules:
- Student names, student achievement, behaviour, welfare, absence, pickup, family, medical, emotional, support or assessment information must stay local.
- If the transcript may contain student-sensitive information, telegram_allowed must be false.
- If the transcript asks for research, planning, or general professional work and contains no student-sensitive information, it may be routed to telegram_agent_task.
- If the transcript asks to email or contact someone, route to email_draft and require review.
- If uncertain, route to review_queue.
- Do not invent facts.
- Do not send normal classroom notes externally.
- Return JSON only.
```

Example user content sent to the model:

```json
{
  "trigger_command": "Joshua task",
  "transcript": "Find me three quick fraction warm-ups for Year 5 tomorrow.",
  "recorded_at": "2026-06-14 10:05:12",
  "duration_seconds": 9
}
```

---

## 19. Routing Categories

| Route | Use case | Destination |
|---|---|---|
| `local_obsidian` | General teacher note | Obsidian Inbox |
| `local_student_note` | Student achievement, support, behaviour, welfare, pickup, assessment | Obsidian Student Notes |
| `local_reminder` | Time-based or action-based reminder | Obsidian Reminders + local notification |
| `telegram_agent_task` | Non-sensitive task for external agent | Telegram agent + local archive |
| `email_draft` | Draft communication | Obsidian Email Drafts |
| `review_queue` | Ambiguous, risky, low confidence, or unclear content | Obsidian Review Queue |
| `discard_cancelled` | Cancelled note | No note, audit only |

---

## 20. Hard Privacy Rules

### 20.1 Never send to Telegram if the transcript includes or may include:

- student names,
- parent or carer names,
- behaviour notes,
- health information,
- wellbeing information,
- absence information,
- pickup information,
- custody or family logistics,
- assessment information,
- academic achievement tied to a student,
- classroom incidents,
- school-sensitive operational information,
- anything that sounds like a private school record.

### 20.2 Always route locally if sensitivity is unknown

```text
if sensitivity == "unknown":
    route = "review_queue"
    telegram_allowed = false
```

### 20.3 Policy gate pseudocode

```python
def apply_policy_gate(transcript, classification):
    if classification["confidence"] < 0.75:
        return force_review("Low classifier confidence")

    if classification["contains_student_information"]:
        return block_external("Contains student information")

    if classification["sensitivity"] in [
        "student_sensitive",
        "school_sensitive",
        "unknown"
    ]:
        return block_external("Sensitive or unknown sensitivity")

    if transcript_contains_student_like_terms(transcript):
        return block_external("Possible student reference detected")

    if classification["route"] == "email_draft":
        classification["requires_review"] = True
        classification["telegram_allowed"] = False
        return classification

    if classification["route"] == "telegram_agent_task":
        if classification["telegram_allowed"] is True:
            return classification
        return force_local("Telegram not allowed by classifier")

    return classification
```

---

## 21. Local Reminder System

### 21.1 Purpose

Some notes are not merely reflections. They are local reminders.

Example:

```text
At 2 o’clock, Alex needs to go to the office because he is going home early.
```

This should create:

1. an Obsidian reminder note,
2. a local notification scheduled for 2:00 pm,
3. an audit log entry,
4. no Telegram message.

### 21.2 Reminder store

Use SQLite or JSON for MVP.

Recommended MVP file:

```text
Obsidian Vault/Classroom Voice Notes/Reminders/reminders.json
```

Example:

```json
{
  "id": "20260614-131522-a8f3",
  "title": "Early pickup reminder",
  "reminder_time": "2026-06-14 14:00:00",
  "message": "Send Alex to the office for early pickup.",
  "sensitivity": "student_sensitive",
  "source_note": "Reminders/2026-06-14_13-15-22_early_pickup.md",
  "completed": false
}
```

### 21.3 Reminder notification behaviour

Every 30 seconds, the app checks for due reminders.

When a reminder is due:

- show Windows notification,
- show tray notification,
- optionally play a soft sound,
- mark reminder as shown,
- allow user to mark complete.

---

## 22. Telegram Agent Task Route

### 22.1 Purpose

Telegram is used only for non-sensitive work tasks that need another agent to do something.

Examples:

```text
Find me three examples of Year 5 fraction misconceptions.
```

```text
Ask Hermes to create a 10-minute warm-up on equivalent fractions.
```

```text
Get me a short explanation of the difference between weathering and erosion for Year 5.
```

### 22.2 Telegram must be off by default

Settings:

```yaml
telegram:
  enabled: false
  bot_token: ""
  chat_id: ""
  send_only_after_policy_gate: true
  archive_sent_tasks_locally: true
```

### 22.3 Telegram safety rule

Even if the teacher says:

```text
Joshua task
```

The app must block Telegram if the content is sensitive.

### 22.4 Local archive

Every sent Telegram task should also be saved locally to:

```text
Classroom Voice Notes/Agent Task Archive/
```

---

## 23. Email Draft Route

### 23.1 Purpose

When the teacher says something like:

```text
Joshua email. Draft an email to parents explaining tomorrow’s excursion change.
```

The system should create a local email draft note.

### 23.2 Do not auto-send email

The app should not send email automatically in the MVP.

It should create a Markdown draft requiring review.

### 23.3 Email draft folder

```text
Classroom Voice Notes/Email Drafts/
```

### 23.4 Review checklist

Each draft should include:

```markdown
## Review Required

- [ ] Check recipient.
- [ ] Check names.
- [ ] Check dates and times.
- [ ] Check tone.
- [ ] Check school policy.
- [ ] Send manually if appropriate.
```

---

## 24. Settings File

Recommended location:

```text
%APPDATA%/ClassroomVoiceNotes/settings.yaml
```

Example:

```yaml
app:
  launch_on_startup: false
  minimise_to_tray: true
  start_listening_on_launch: true

audio:
  device_name: "Default Microphone"
  sample_rate: 16000
  channels: 1

recording:
  hard_cap_seconds: 60
  silence_detection_enabled: false
  silence_stop_seconds: 5
  keep_audio_files: true
  audio_format: wav

wakeword:
  enabled: true
  sensitivity: 0.6
  commands:
    joshua_note:
      phrase: "Joshua note"
      action: "start_general_note"
      keyword_file: "wakewords/joshua_note.ppn"
    joshua_save:
      phrase: "Joshua save"
      action: "save_current_note"
      keyword_file: "wakewords/joshua_save.ppn"
    joshua_cancel:
      phrase: "Joshua cancel"
      action: "cancel_current_note"
      keyword_file: "wakewords/joshua_cancel.ppn"
    joshua_task:
      phrase: "Joshua task"
      action: "start_possible_agent_task"
      keyword_file: "wakewords/joshua_task.ppn"

transcription:
  engine: "whisper_cpp"
  model_path: "models/ggml-small.en.bin"
  language: "en"

ollama:
  enabled: true
  base_url: "http://localhost:11434"
  fast_router_model: "qwen3.5:latest"
  careful_router_model: "phi4:14b"
  minimum_confidence: 0.75
  use_careful_second_pass: true
  when_uncertain: "review_queue"

obsidian:
  vault_path: "D:/Obsidian/Teacher Vault"
  notes_folder: "Classroom Voice Notes/Inbox"
  student_notes_folder: "Classroom Voice Notes/Student Notes"
  behaviour_notes_folder: "Classroom Voice Notes/Behaviour Notes"
  maths_notes_folder: "Classroom Voice Notes/Maths Notes"
  reminders_folder: "Classroom Voice Notes/Reminders"
  email_drafts_folder: "Classroom Voice Notes/Email Drafts"
  agent_archive_folder: "Classroom Voice Notes/Agent Task Archive"
  review_queue_folder: "Classroom Voice Notes/Review Queue"
  audio_folder: "Classroom Voice Notes/Audio"
  logs_folder: "Classroom Voice Notes/Logs"
  use_yaml_frontmatter: true

ui:
  show_recording_indicator: true
  indicator_position: "top_right"
  indicator_opacity: 0.85
  play_beeps: true

privacy:
  never_send_student_sensitive_content_externally: true
  route_unknown_sensitivity_to_review: true
  keep_audit_log: true
  save_original_transcript: true
  save_audio_file: true

telegram:
  enabled: false
  bot_token: ""
  chat_id: ""
  send_only_after_policy_gate: true
  archive_sent_tasks_locally: true

email:
  create_drafts_only: true
  auto_send_enabled: false
```

---

## 25. Settings Interface

### 25.1 General tab

| Setting | Type | Default |
|---|---|---|
| Launch on startup | Toggle | Off |
| Start listening when app opens | Toggle | On |
| Minimise to tray | Toggle | On |
| Play start/stop beep | Toggle | On |

### 25.2 Audio tab

| Setting | Type | Default |
|---|---|---|
| Microphone device | Dropdown | System default |
| Sample rate | Dropdown | 16000 Hz |
| Channels | Dropdown | Mono |
| Input gain | Slider | 100% |

### 25.3 Recording tab

| Setting | Type | Default |
|---|---|---|
| Hard cap | Number | 60 seconds |
| Minimum recording length | Number | 2 seconds |
| Save audio files | Toggle | On |
| Delete audio after transcription | Toggle | Off |
| Audio format | Dropdown | WAV |

### 25.4 Wake phrase tab

| Setting | Type | Default |
|---|---|---|
| Wake phrase enabled | Toggle | On |
| Wake sensitivity | Slider | Medium |
| Keyword files folder | Folder picker | App wakewords folder |
| Test wake phrase | Button | N/A |

### 25.5 Obsidian tab

| Setting | Type | Default |
|---|---|---|
| Vault path | Folder picker | Required |
| Notes folder | Text field | Classroom Voice Notes |
| Validate vault | Button | N/A |
| Open vault folder | Button | N/A |

### 25.6 Ollama tab

| Setting | Type | Default |
|---|---|---|
| Enable Ollama router | Toggle | On |
| Ollama URL | Text | http://localhost:11434 |
| Test connection | Button | N/A |
| Fast router model | Dropdown | qwen3.5:latest |
| Careful router model | Dropdown | phi4:14b |
| Minimum confidence | Slider | 0.75 |
| When uncertain | Dropdown | Review queue |

### 25.7 Routing tab

| Setting | Type | Default |
|---|---|---|
| Route general notes to Obsidian | Toggle | On |
| Route reminders locally | Toggle | On |
| Route email requests to drafts | Toggle | On |
| Enable Telegram task routing | Toggle | Off |
| Archive sent tasks locally | Toggle | On |
| Require review for external routes | Toggle | Optional, recommended On |

### 25.8 Privacy tab

| Setting | Type | Default |
|---|---|---|
| Never send student-sensitive content externally | Locked toggle | On |
| Unknown sensitivity goes to review | Locked toggle | On |
| Keep audit log | Toggle | On |
| Show recording indicator | Toggle | On |
| Delete cancelled audio | Toggle | On |

---

## 26. Development Roadmap

## Stage 0: Project Setup

### Goal

Create the repository, project structure, settings format, and basic run process.

### Tasks

- Create GitHub repository.
- Create Python virtual environment.
- Create project folders.
- Add `README.md`.
- Add `requirements.txt`.
- Add `.gitignore`.
- Add sample `settings.yaml`.
- Add logging setup.
- Add basic command-line entry point.

### Deliverables

- App launches from command line.
- Settings load from YAML.
- Logs write to local app folder.

### Acceptance criteria

```bash
python app/main.py
```

Expected output:

```text
Classroom Voice Notes started
Settings loaded successfully
```

---

## Stage 1: Basic Local Audio Recording

### Goal

Record audio from the selected microphone and save it locally.

### Tasks

- List available microphone devices.
- Select default microphone.
- Record a fixed 10-second WAV file.
- Save file to local test folder.
- Add timestamped filenames.
- Add error handling for missing microphone.

### Deliverables

```text
recordings/test_2026-06-14_09-15-22.wav
```

### Acceptance criteria

- User can record 10 seconds.
- File can be played back.
- App handles no microphone gracefully.
- Audio file has correct timestamp.

---

## Stage 2: Manual Start/Stop Recording

### Goal

Create a recording session that can be manually started, stopped, saved, or cancelled.

### Tasks

- Add `RecordingSession` class.
- Add session ID.
- Add start time/end time.
- Add duration calculation.
- Add save command.
- Add cancel command.
- Add hard-cap timer.
- Add audit log entries.

### Deliverables

Manual command-line prototype:

```text
N = start note
S = save note
C = cancel note
Q = quit
```

### Acceptance criteria

- Recording starts when user presses N.
- Recording saves when user presses S.
- Recording deletes temp audio when user presses C.
- Recording automatically stops at hard cap.
- Audit log records all events.

---

## Stage 3: Local Transcription

### Goal

Transcribe saved audio locally.

### Tasks

- Install/configure whisper.cpp.
- Download/select local model.
- Create `Transcriber` interface.
- Create `WhisperCppTranscriber`.
- Pass WAV file to whisper.cpp.
- Capture transcript output.
- Save transcript as text.
- Add transcription error handling.

### Deliverables

```text
transcripts/2026-06-14_09-15-22.txt
```

### Acceptance criteria

- Audio file is transcribed locally.
- No internet is required.
- Transcript is saved beside audio.
- Failed transcription creates clear error log.
- App does not crash if transcription fails.

---

## Stage 4: Obsidian Markdown Writer

### Goal

Write each transcript into an Obsidian vault as a Markdown file.

### Tasks

- Add vault path setting.
- Validate vault folder exists.
- Create notes folder if missing.
- Create audio folder if missing.
- Create logs folder if missing.
- Generate Markdown note.
- Add YAML frontmatter.
- Link audio file relative to note.
- Add category tags.
- Add follow-up checklist section.

### Deliverables

```text
Obsidian Vault/Classroom Voice Notes/Inbox/2026-06-14_09-15-22_general_note.md
```

### Acceptance criteria

- Markdown file appears inside vault.
- Obsidian can open it immediately.
- Note has frontmatter.
- Note has transcript section.
- Note has review checklist.
- Note has relative audio link if audio is kept.

---

## Stage 5: Ollama Connection

### Goal

Connect to the local Ollama server and list available models.

### Tasks

- Add Ollama client module.
- Check Ollama base URL.
- Add timeout handling.
- List installed models.
- Allow model selection in settings.
- Add test connection button.

### Deliverables

- App can test Ollama connection.
- App can show installed models.

### Acceptance criteria

- If Ollama is running, models are listed.
- If Ollama is not running, app shows useful error.
- App does not crash if Ollama is unavailable.
- If Ollama fails, note routes to review queue or local Obsidian.

---

## Stage 6: LLM Classification Only

### Goal

Classify transcripts but do not route externally yet.

### Tasks

- Create router prompt.
- Create JSON schema.
- Send transcript to Ollama.
- Parse JSON response.
- Validate against schema.
- Add classification result to Markdown note.

### Deliverables

Markdown note includes:

```markdown
## Router Decision

- Route: local_obsidian
- Sensitivity: teacher_private
- Category: maths
- Telegram allowed: false
- Confidence: 0.91
```

### Acceptance criteria

- App receives structured JSON from Ollama.
- App rejects invalid JSON safely.
- App saves classification results locally.
- No external routing happens yet.

---

## Stage 7: Policy Gate

### Goal

Apply hard-coded privacy and routing rules after LLM classification.

### Tasks

- Add policy gate module.
- Block external routing for student-sensitive content.
- Block external routing for unknown sensitivity.
- Route low-confidence notes to review queue.
- Mark email drafts as review required.
- Log policy decisions.

### Deliverables

Policy-gated classification result.

### Acceptance criteria

- Sensitive notes stay local.
- Unknown notes go to review queue.
- Low-confidence notes go to review queue.
- Telegram is blocked unless content is non-sensitive and allowed.
- All policy decisions are logged.

---

## Stage 8: Obsidian Folder Routing

### Goal

Use the classification result to choose the correct local folder.

### Tasks

- Map routes/categories to folders.
- Save student-sensitive notes to Student Notes.
- Save behaviour notes to Behaviour Notes.
- Save maths notes to Maths Notes.
- Save reminders to Reminders.
- Save ambiguous notes to Review Queue.

### Acceptance criteria

- General note goes to Inbox.
- Student-sensitive note goes to Student Notes.
- Behaviour note goes to Behaviour Notes.
- Reminder goes to Reminders.
- Ambiguous note goes to Review Queue.

---

## Stage 9: Desktop UI

### Goal

Create the basic Windows desktop interface.

### Tasks

- Create main window.
- Add status display.
- Add Start Listening button.
- Add Stop Listening button.
- Add Start Recording button.
- Add Save Recording button.
- Add Cancel Recording button.
- Add microphone dropdown.
- Add Obsidian vault picker.
- Add hard-cap setting.
- Add recording indicator toggle.
- Add Ollama model selection.
- Add save settings button.

### Acceptance criteria

- User can configure vault path.
- User can configure hard cap.
- User can manually test recording.
- User can manually test transcription.
- User can test Ollama connection.
- Settings persist after restart.

---

## Stage 10: System Tray and Minimized Mode

### Goal

Allow the app to run unobtrusively during teaching.

### Tasks

- Add tray icon.
- Add right-click menu.
- Add “Show app”.
- Add “Start listening”.
- Add “Pause listening”.
- Add “Start recording”.
- Add “Save current note”.
- Add “Cancel current note”.
- Add “Quit”.
- Minimise to tray instead of closing.

### Acceptance criteria

- App can be minimised.
- App keeps listening while minimised.
- Tray icon reflects state.
- User can quit from tray.
- User can pause listening quickly.

---

## Stage 11: Floating Recording Indicator

### Goal

Show a visible recording indicator when the app is recording.

### Tasks

- Create always-on-top floating indicator.
- Add flashing animation.
- Add position settings.
- Add opacity setting.
- Add enable/disable setting.
- Ensure it does not steal keyboard focus.
- Ensure it hides after recording stops.

### Acceptance criteria

- Indicator appears during recording.
- Indicator disappears when recording ends.
- Indicator can be turned off.
- Indicator works when main app is minimised.

---

## Stage 12: Wake Phrase Start

### Goal

Start recording when the teacher says a wake phrase.

### Tasks

- Add Porcupine SDK.
- Add keyword file loading.
- Add wake-word listener thread.
- Connect wake phrase to command router.
- Trigger recording from “Joshua note”.
- Trigger tagged recording from “Joshua maths note”.
- Trigger tagged recording from “Joshua behaviour note”.
- Log wake phrase detections.

### Acceptance criteria

- Saying “Joshua note” starts recording.
- Saying “Joshua maths note” starts tagged maths note.
- False triggers are rare in quiet testing.
- App remains responsive while listening.
- Wake listener can be paused.

---

## Stage 13: Spoken Save and Cancel

### Goal

Allow hands-free stop/save/cancel.

### Tasks

- Add save keyword.
- Add cancel keyword.
- Ensure save/cancel detection works during recording.
- Prevent save phrase from polluting transcript where possible.
- Add manual fallback if wake listener fails.
- Add hard-cap fallback.

### Acceptance criteria

- “Joshua save” saves the note.
- “Joshua cancel” deletes temporary audio.
- Hard cap still works.
- Manual controls still work.
- App does not get stuck recording.

Important: this is one of the trickiest stages. Stop commands must be highly reliable. Keep keyboard fallback permanently.

---

## Stage 14: Local Reminder Engine

### Goal

Create local reminders from notes.

### Tasks

- Extract reminder time from classifier output.
- Store reminders in JSON or SQLite.
- Check due reminders periodically.
- Show Windows notification.
- Allow mark as completed.
- Link reminder back to Obsidian note.

### Acceptance criteria

- Reminder note creates a local reminder.
- Notification appears at correct time.
- Reminder can be marked complete.
- Sensitive reminders are never sent externally.

---

## Stage 15: Optional Telegram Agent Task Route

### Goal

Send only non-sensitive agent tasks to Telegram.

### Tasks

- Add Telegram settings.
- Add Telegram sender module.
- Keep Telegram disabled by default.
- Require policy gate approval.
- Archive sent task locally.
- Log send result.
- Handle Telegram failure gracefully.

### Acceptance criteria

- Telegram sends only when enabled.
- Telegram sends only non-sensitive tasks.
- Sensitive tasks are blocked.
- All sent tasks are archived locally.
- Failure does not lose original note.

---

## Stage 16: Email Draft Route

### Goal

Create local email drafts from voice instructions.

### Tasks

- Detect email intent.
- Route to local email draft folder.
- Generate Markdown draft.
- Add review checklist.
- Do not auto-send.

### Acceptance criteria

- Email instructions create local drafts.
- Drafts require review.
- No email is sent automatically.

---

## Stage 17: Templates and Daily Summaries

### Goal

Improve Obsidian usefulness.

### Tasks

- Add editable templates.
- Add template variables.
- Add daily summary option.
- Add backlinks from individual notes to daily notes.
- Add category-specific templates.

### Template variables

```text
{{title}}
{{date}}
{{time}}
{{category}}
{{tags}}
{{duration_seconds}}
{{audio_file}}
{{transcript}}
{{session_id}}
{{route}}
{{sensitivity}}
{{confidence}}
```

### Acceptance criteria

- Teacher can edit templates.
- Notes are generated with templates.
- Daily summary can be enabled.
- Bad templates fail safely.

---

## Stage 18: Packaging and Installer

### Goal

Make the app easy to install and run.

### Tasks

- Package with PyInstaller.
- Include default templates.
- Include icons.
- Include sample settings.
- Create first-run setup wizard.
- Create portable build option.
- Test on clean Windows machine.

### Deliverables

```text
ClassroomVoiceNotes.exe
```

### Acceptance criteria

- App runs without Python installed.
- User can choose vault path on first launch.
- App handles missing models gracefully.
- App provides clear setup instructions.

---

## 27. Testing Plan

### 27.1 Unit tests

Test:

- filename creation,
- settings loading,
- settings saving,
- Markdown generation,
- audit logging,
- category mapping,
- policy gate decisions,
- JSON schema validation,
- hard-cap timer,
- transcript cleaning.

### 27.2 Integration tests

Test:

- record → save WAV,
- WAV → transcript,
- transcript → Ollama classifier,
- classifier → policy gate,
- policy gate → Obsidian note,
- policy gate → review queue,
- reminder transcript → local reminder,
- safe task → Telegram archive,
- email request → local email draft.

### 27.3 Classroom-style tests

Test under conditions such as:

- quiet room,
- aircon or fan noise,
- students talking,
- teacher walking around,
- lavalier rubbing on clothing,
- Bluetooth microphone disconnect,
- teacher facing away from laptop,
- laptop minimised,
- PowerPoint running,
- interactive whiteboard use.

### 27.4 Wake phrase tests

Track:

| Metric | Target |
|---|---|
| Wake phrase detection | Reliable at normal speaking volume |
| False starts | Very rare |
| Stop phrase detection | Reliable enough, but manual fallback required |
| Time from phrase to recording | Less than 1 second ideally |
| Time from save to Markdown note | Acceptable for short notes |
| External routing errors | Zero sensitive leaks |

---

## 28. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Classroom noise causes missed wake phrase | Medium | Medium | Manual hotkeys and tray controls |
| False wake trigger | Medium | Medium | Use unusual phrase; hard cap; visible indicator |
| Stop phrase fails | Medium | High | Hard cap and manual stop |
| Long accidental recording | Low | High | Hard cap always enabled |
| Poor transcription | Medium | Medium | Better mic, model choice, transcript review |
| Ollama unavailable | Medium | Low | Route to Obsidian/review queue |
| Classifier misroutes sensitive note | Medium | High | Hard-coded policy gate |
| Sensitive content sent to Telegram | Low if designed correctly | Very high | Locked privacy rules, default Telegram off |
| Obsidian path missing | Medium | Low | Validate path before recording |
| Audio files consume storage | Medium | Low | Delete-after-transcription option |
| App crashes during recording | Low/Medium | Medium | Temp file handling, recovery logs |
| Student name appears in transcript | Medium | Medium/High | Local-only route and review checklist |

---

## 29. Non-Goals for Early Versions

Do not include these in the MVP:

- cloud transcription,
- cloud LLM routing for classroom notes,
- automatic student profiling,
- automatic behaviour scoring,
- automatic parent emails,
- automatic school records,
- facial recognition,
- speaker identification,
- continuous whole-day recording,
- multi-teacher network sync,
- automatic upload of audio to third-party services.

---

## 30. MVP Definition

The first true MVP should include:

- Windows desktop app,
- manual recording,
- local transcription,
- Obsidian Markdown output,
- local audit log,
- adjustable hard recording cap,
- visible recording indicator,
- local Ollama classification,
- hard-coded privacy policy gate,
- Obsidian folder routing,
- review queue.

Wake phrase support should come after the complete pipeline works.

Telegram should come much later and remain optional, disabled by default, and limited to non-sensitive agent tasks.

---

## 31. Recommended Build Order

Build in this order:

```text
1. Manual recording
2. Local transcription
3. Obsidian Markdown output
4. Audit log
5. Ollama classifier
6. Policy gate
7. Obsidian folder routing
8. Desktop UI
9. System tray mode
10. Recording indicator
11. Wake phrase start
12. Spoken save/cancel
13. Local reminders
14. Optional Telegram task route
15. Email draft route
16. Templates and daily summaries
17. Packaging
```

The first major success milestone is:

```text
Press button → record note → transcribe locally → classify locally → save clean Markdown into Obsidian.
```

The second major success milestone is:

```text
Say “Joshua note” → record note → say “Joshua save” → transcribe locally → classify locally → route safely.
```

---

## 32. Developer Handoff Summary

Build a Windows-first local desktop app that allows a teacher to capture short spoken notes using a microphone. The app records only after a deliberate trigger, transcribes audio locally, classifies the transcript using a local Ollama model, applies hard-coded privacy rules, and routes the note safely.

Core destinations:

- Obsidian Markdown note,
- Obsidian student/private note,
- Obsidian reminder note plus local notification,
- Obsidian email draft,
- Obsidian review queue,
- optional Telegram agent task for non-sensitive content only.

The app must prioritise:

1. privacy,
2. local control,
3. reliability,
4. auditability,
5. simple teacher workflow.

The local LLM is useful, but it must not be trusted as the final safety layer. The final routing decision must be controlled by deterministic rules.

The guiding rule is:

```text
If it might involve a student, keep it local.
If it might be sensitive, keep it local.
If the system is unsure, keep it local.
```

---

## 33. Useful Reference Links

These references are useful starting points for implementation research:

- Ollama API documentation: <https://docs.ollama.com/api>
- Ollama structured outputs: <https://docs.ollama.com/capabilities/structured-outputs>
- Obsidian help: <https://help.obsidian.md/>
- Picovoice Porcupine: <https://picovoice.ai/products/porcupine/>
- whisper.cpp: <https://github.com/ggml-org/whisper.cpp>
- PySide6: <https://pypi.org/project/PySide6/>
- Python sounddevice: <https://python-sounddevice.readthedocs.io/>
- Telegram Bot API: <https://core.telegram.org/bots/api>

---

## 34. Final Product Vision

The finished version of Classroom Voice Notes should feel like a quiet teaching assistant that lives on the teacher’s computer.

It should let the teacher capture thoughts naturally:

```text
Joshua note. Group three needs another visual example before tomorrow’s independent task.
```

It should keep sensitive notes private:

```text
Joshua reminder. At 2:00, Alex needs to go to the office for early pickup.
```

It should route safe work tasks outward when allowed:

```text
Joshua task. Ask Hermes to find three short equivalent fraction warm-ups for Year 5.
```

And it should always remember:

```text
The classroom information belongs to the teacher and the school.
When in doubt, keep it local.
```
