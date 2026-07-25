# Classroom Voice Notes

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-yellow.svg)](https://www.python.org/)
[![Framework: PySide6](https://img.shields.io/badge/Framework-PySide6-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Platform: Windows First](https://img.shields.io/badge/Platform-Windows%20First-lightgrey.svg)](#platform-and-runtime)

Classroom Voice Notes (CVN) is a local-first Windows desktop application for
teachers. It captures short spoken notes, transcribes and classifies them
locally, and writes structured Markdown into an Obsidian vault.

Student-sensitive records stay on the classroom computer. A deliberately
generated, non-sensitive agent task may leave the device only after it passes
the hard-coded privacy gate.

## Project status

- **Phase 2C:** Supabase-to-OpenClaw broker lifecycle verified in staging.
- **Phase 2E:** Operational hardening in progress.
- **Production:** Not authorised. Current broker and worker operations are
  staging-only unless a separate production-promotion plan is approved.

The current delivery sequence and exit gates are tracked in
[docs/phase-2e-delivery-plan.md](docs/phase-2e-delivery-plan.md).

## Architecture

```text
Teacher voice
    |
    v
openWakeWord -> local audio capture -> whisper.cpp transcription
    |
    v
local Ollama classification -> student registry -> hard-coded PolicyGate
    |                                           |
    | local note                                | approved non-sensitive task only
    v                                           v
Obsidian vault                         local SQLite outbox
                                                |
                                                v
                                      Supabase staging broker
                                                |
                                                v
                                      VPS OpenClaw worker
                                                |
                                                v
                                  loopback-only OpenClaw gateway
                                                |
                                                v
                                  signed status reconciliation
                                                |
                                                v
                                      originating Obsidian note
```

The verified external route uses the Supabase broker and the OpenClaw staging
worker. Legacy Telegram-related modules remain for compatibility and summary
features, but they are not the current verified broker transport.

## Privacy boundary

The following data must remain local:

- raw classroom audio;
- raw transcripts containing classroom information;
- student names and identifiers;
- achievement, assessment and behaviour information;
- welfare, medical, family, absence and pickup information;
- identifiable parent or school communications; and
- local file paths and Obsidian metadata.

External dispatch is fail-closed. A task must be classified as `agent_task`,
marked `non_sensitive`, reduced to a safe task title and instruction set, and
pass registry, keyword, payload, path, contact-detail, target and endpoint
checks. Outbound requests are HMAC-signed, authenticated, idempotent and bound
to the exact broker environment.

Desktop submission currently uses the broker's restricted legacy bearer/HMAC
client path because the desktop does not yet send `x-cvn-key-id`. Registered
worker identities are implemented for claim and execution. Migrating the
desktop client to a registered identity remains a pre-production requirement.

## Core capabilities

### Local voice pipeline

- Local wake-phrase detection using `openWakeWord`.
- Continuous 16 kHz microphone capture with a pre-roll buffer.
- Optional offline `Vosk` commands: `save`, `stop`, `cancel` and `discard`.
- Local `whisper.cpp` transcription with model bootstrapping.
- PySide6 recording-state indicator and settings interface.

### Notes and classroom workflows

- Structured Obsidian notes with YAML frontmatter.
- Student observation, behaviour, subject, reminder, email-draft and
  agent-task templates.
- Local student-name registry and anonymised identifiers.
- Review queue and secondary local classification.
- Student index, daily summaries, reminder notifications and `.ics` output.

### External task reliability

- Local SQLite outbox with pending, sending, sent, processing, completed,
  failed, dead-letter and archived states.
- Bounded retry with exponential backoff and seven-day pending retention.
- Selective, confirmed retry or archive of dead-letter tasks.
- Environment-bound staging and production credential names.
- Signed status checks and safe result reconciliation into the originating
  Obsidian note.
- Separate worker identities and target allowlists.
- Loopback-only OpenClaw gateway access on the VPS.

## Platform and runtime

The desktop application is developed for Windows and requires:

- Python 3.11 or newer;
- [uv](https://docs.astral.sh/uv/);
- [Ollama](https://ollama.com/) running locally;
- [Obsidian](https://obsidian.md/); and
- a working microphone.

The staging worker runs separately on Linux under systemd. Its provisioning
runbook is [deploy/README.md](deploy/README.md).

## Getting started

### 1. Install dependencies

```powershell
uv sync
```

### 2. Install the local Ollama models

```powershell
ollama pull qwen3.5:latest
ollama pull phi4:14b
```

### 3. Configure the local environment

Copy `.env.template` to `.env`. Do not place broker bearer tokens or HMAC
secrets in `.env`; broker secrets belong in the operating-system credential
store.

For staging broker work, the environment value must be exact:

```dotenv
CVN_BROKER_ENV=staging
```

See [Environment and credential operations](docs/operations/environment-and-credentials.md)
before enabling external dispatch.

### 4. Run the application

```powershell
uv run run.py
```

On first launch, select the Obsidian vault that will store Classroom Voice
Notes. Configure the microphone, wake-word and spoken-command models from the
settings window.

External dispatch is disabled by default and should remain disabled until the
staging endpoint, environment and credentials have been verified.

## Local application data

On Windows, CVN writes local operational data under:

```text
%LOCALAPPDATA%\ClassroomVoiceNotes\
```

Important files include:

```text
settings.json
external_outbox.db
logs\audit.log
audio\
```

If `%LOCALAPPDATA%` is unavailable, the fallback is
`~/.classroom-voice-notes/`.

The Obsidian vault is selected separately and is not stored inside the
application-data directory unless the user explicitly chooses that location.

## Outbox operations

The settings window shows live pending, sent and stuck counts.

- **Retry Outbox Now** retries eligible pending tasks and reconciles known
  remote statuses.
- **View Outbox** shows dead-letter tasks using safe metadata only.
- Retrying or archiving a dead-letter task requires explicit selection and
  confirmation.
- Stored endpoints are revalidated against `CVN_BROKER_ENV` before retry or
  status access.

Use [Outbox recovery](docs/operations/outbox-recovery.md) when work is stuck.
Do not edit the SQLite database or replay stored payloads manually.

## Testing and quality checks

Run the local quality gates:

```powershell
uv run pytest tests
uv run ruff check app tests scripts run.py
uv run mypy app
```

Safe local and fake-gateway tests run without live credentials. Tests that
exercise Supabase staging, registered worker identities or a live OpenClaw
gateway are skipped unless their explicit environment variables and secrets
are supplied.

Never use real classroom data in tests.

## Repository structure

```text
app/
  audio/            local audio input and recording
  audit/            structured local audit logging
  commands/         offline spoken-command recognition
  config/           settings, environment and credential helpers
  destinations/     Obsidian, outbox, broker and summary integrations
  ollama_router/    local classification and privacy policy gate
  privacy/          local student registry
  transcription/    whisper.cpp pipeline
  ui/               settings and recording indicator
  wakeword/         openWakeWord integration
  worker/           Supabase broker worker
deploy/             staging VPS service and diagnostics
docs/               architecture, operations and delivery plans
scripts/            staging test and worker utilities
specs/              product specifications and task plans
supabase/           database migrations and Edge Functions
tests/              unit and integration tests
```

## Operational documentation

- [Phase 2E delivery plan](docs/phase-2e-delivery-plan.md)
- [Environment and credential operations](docs/operations/environment-and-credentials.md)
- [Outbox recovery](docs/operations/outbox-recovery.md)
- [Worker contract](docs/architecture/003-cvn-worker-contract.md)
- [Staging VPS runbook](deploy/README.md)

## Licence

Classroom Voice Notes is licensed under the [MIT License](LICENSE).
