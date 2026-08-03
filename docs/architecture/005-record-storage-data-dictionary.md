# Outbound Record Storage & Generated Export Data Dictionary

## 1. Overview

This document specifies the authoritative schema, field data dictionary, security controls, inter-process locking, schema upgrade migrations, backup procedures, retention schedules, and deletion policies for local outbound record storage in Classroom Voice Notes (CVN).

Local record storage consists of two components:
1. **Authoritative Database (`outbound_records.db`)**: A versioned SQLite database storing structured records for all completed `record_only` outbound sharing items.
2. **Generated Spreadsheet Export (`outbound_records.csv`)**: An atomically generated CSV snapshot of the database for user consumption and reporting, synchronized via an inter-process file lock (`outbound_records.lock`).

---

## 2. SQLite Database Schema (`outbound_records`)

### Schema Version History
- **Version 1**: Initial release schema featuring `source_device` column.
- **Version 2**: Standardized v2 contract schema renaming `source_device` -> `source_device_id` and adding `export_status` column (`'pending'` or `'exported'`).

| Column Name | SQLite Type | Nullable | Primary Key | Description & Source Field |
| :--- | :--- | :--- | :--- | :--- |
| `item_id` | `TEXT` | No | Yes | Unique outbound sharing item identifier (`payload.item_id`). |
| `content_hash` | `TEXT` | No | No | SHA-256 canonical RFC 8785 hash of content and task (`payload.content_hash`). |
| `schema_version` | `TEXT` | No | No | Payload contract version (e.g. `cvn.outbound_item.v2`). |
| `source_device_id` | `TEXT` | Yes | No | Unique identifier for originating desktop client (`payload.source_device_id`). |
| `created_at` | `TEXT` | No | No | ISO 8601 timestamp of item creation (`payload.created_at`). |
| `recorded_at` | `TEXT` | Yes | No | ISO 8601 timestamp when classroom note was recorded (`payload.content.recorded_at`). |
| `received_at` | `TEXT` | Yes | No | ISO 8601 timestamp when server/worker received item. |
| `completed_at` | `TEXT` | No | No | ISO 8601 timestamp when consumer transactionally stored record. |
| `duration_seconds` | `REAL` | Yes | No | Duration of classroom recording in seconds (`payload.content.duration_seconds`). |
| `title` | `TEXT` | No | No | Sanitized title of note/record (`payload.content.title`). |
| `summary` | `TEXT` | Yes | No | Summarized overview of note (`payload.content.summary`). |
| `category` | `TEXT` | Yes | No | Pedagogical or administrative category (`payload.content.category`). |
| `tags_json` | `TEXT` | Yes | No | JSON array of sorted tags (`payload.content.tags`). |
| `structured_fields_json` | `TEXT` | Yes | No | JSON object of key-value attributes (`payload.content.structured_fields`). |
| `transcript` | `TEXT` | Yes | No | Full transcript text. **Only stored if explicitly included in payload content.** |
| `classification` | `TEXT` | Yes | No | Privacy classification (`payload.privacy.automatic_classification`). |
| `risk_level` | `TEXT` | Yes | No | Risk assessment flag (`payload.privacy.risk_level`). |
| `release_basis` | `TEXT` | Yes | No | Authorization policy basis (`payload.privacy.release_basis`). |
| `approval_metadata_json` | `TEXT` | Yes | No | JSON object containing human/policy approval metadata (`payload.privacy.approval`). |
| `safe_processing_ref` | `TEXT` | Yes | No | Reference identifier for processing execution/audit. |
| `export_status` | `TEXT` | No | No | Export state flag (`'pending'` or `'exported'`). Default `'pending'`. |

---

## 3. Schema v1 -> v2 Migration Protocol

When an application instance opens an existing version 1 database:
1. `_init_db()` checks `schema_migrations` table for max version.
2. If `version < 2`, a transaction is executed:
   - `ALTER TABLE outbound_records RENAME COLUMN source_device TO source_device_id` (if present).
   - `ALTER TABLE outbound_records ADD COLUMN export_status TEXT NOT NULL DEFAULT 'pending'` (if missing).
   - `INSERT OR IGNORE INTO schema_migrations (version) VALUES (2)` is recorded.
3. Existing records are preserved and readable immediately under version 2 code.

---

## 4. CSV Spreadsheet Structure (`outbound_records.csv`)

The generated CSV contains a subset of high-level fields suitable for administrative export:

1. `item_id`
2. `created_at`
3. `title`
4. `category`
5. `summary`
6. `tags` (JSON string)
7. `structured_fields` (JSON string)
8. `release_basis`

### Formula Injection Safeguards
All values written to the CSV file undergo sanitization via `sanitize_csv_field()`. Any cell beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` is automatically prefixed with a single quote (`'`) to prevent formula execution in Microsoft Excel or Google Sheets. Non-printable ASCII control characters are stripped.

### Inter-Process File Locking
CSV generation acquires an OS-level file lock (`outbound_records.lock` via `msvcrt`/`fcntl`) to ensure multi-process safety when multiple consumer workers generate exports concurrently.

---

## 5. Operational Lifecycle & Governance

### Truthful Status & Standalone Export Retry
- Database insertion into `outbound_records.db` is performed first inside a SQLite transaction with `export_status = 'pending'`.
- If CSV export fails (e.g. disk I/O error), `RecordConsumer.process_record()` returns `{"status": "export_pending"}` without rolling back the committed SQLite record.
- Operative routines trigger `RecordConsumer.retry_pending_exports()` which regenerates the CSV snapshot if any rows are pending, if the CSV file is missing from disk, or if the previous export attempt failed.
- Once CSV export completes successfully, all included items transition to `export_status = 'exported'`.

### Retention & Deletion
- Records are retained locally in `outbound_records.db` according to school district data retention policies.
- Deletion requests (e.g. data purge or privacy deletion) delete the row from `outbound_records.db` and trigger `RecordConsumer.regenerate_csv()` to update the CSV snapshot atomically.
