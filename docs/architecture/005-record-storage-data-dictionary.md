# Outbound Record Storage & Generated Export Data Dictionary

## 1. Overview

This document specifies the authoritative schema, field data dictionary, security controls, backup procedures, retention schedules, and deletion policies for local outbound record storage in Classroom Voice Notes (CVN).

Local record storage consists of two components:
1. **Authoritative Database (`outbound_records.db`)**: A versioned SQLite database storing structured records for all completed `record_only` outbound sharing items.
2. **Generated Spreadsheet Export (`outbound_records.csv`)**: An atomically generated CSV snapshot of the database for user consumption and reporting.

---

## 2. SQLite Database Schema (`outbound_records`)

| Column Name | SQLite Type | Nullable | Primary Key | Description & Source Field |
| :--- | :--- | :--- | :--- | :--- |
| `item_id` | `TEXT` | No | Yes | Unique outbound sharing item identifier (`payload.item_id`). |
| `content_hash` | `TEXT` | No | No | SHA-256 canonical RFC 8785 hash of content and task (`payload.content_hash`). |
| `schema_version` | `TEXT` | No | No | Payload contract version (e.g. `cvn.outbound_item.v2`). |
| `source_device` | `TEXT` | Yes | No | Identifying string or token for originating desktop client. |
| `created_at` | `TEXT` | No | No | ISO 8601 timestamp of item creation (`payload.created_at`). |
| `recorded_at` | `TEXT` | Yes | No | ISO 8601 timestamp when classroom note was recorded. |
| `received_at` | `TEXT` | Yes | No | ISO 8601 timestamp when server/worker received item. |
| `completed_at` | `TEXT` | No | No | ISO 8601 timestamp when consumer transactionally stored record. |
| `duration_seconds` | `REAL` | Yes | No | Duration of classroom recording in seconds. |
| `title` | `TEXT` | No | No | Sanitized title of note/record (`payload.content.title`). |
| `summary` | `TEXT` | Yes | No | Summarized overview of note (`payload.content.summary`). |
| `category` | `TEXT` | Yes | No | Pedagogical or administrative category (`payload.content.category`). |
| `tags_json` | `TEXT` | Yes | No | JSON array of sorted tags (`payload.content.tags`). |
| `structured_fields_json` | `TEXT` | Yes | No | JSON object of key-value attributes (`payload.content.structured_fields`). |
| `transcript` | `TEXT` | Yes | No | Full transcript text. **Only stored if explicitly included in payload.** |
| `classification` | `TEXT` | Yes | No | Privacy classification level (`payload.privacy.classification`). |
| `risk_level` | `TEXT` | Yes | No | Risk assessment flag (`payload.privacy.risk_level`). |
| `release_basis` | `TEXT` | Yes | No | Authorization policy basis (`payload.privacy.release_basis`). |
| `approval_metadata_json` | `TEXT` | Yes | No | JSON object containing human or policy approval metadata. |
| `safe_processing_ref` | `TEXT` | Yes | No | Reference identifier for processing execution/audit. |

---

## 3. CSV Spreadsheet Structure (`outbound_records.csv`)

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

---

## 4. Operational Lifecycle & Governance

### Access Control
- Access to `outbound_records.db` and `outbound_records.csv` is restricted to the operating system user running the CVN application.
- Encryption-at-rest is provided via OS-level disk encryption (BitLocker / FileVault / LUKS).

### Backup Procedures
- `outbound_records.db` is the authoritative source. Backups should copy the SQLite database using SQLite online backup API or file copy when no write transaction is open.
- `outbound_records.csv` is disposable and can be regenerated on demand from `outbound_records.db` at any time.

### Retention & Deletion
- Records are retained locally in `outbound_records.db` according to school district data retention policies.
- Deletion requests (e.g. data purge or privacy deletion) must delete the corresponding row from `outbound_records.db` and trigger `RecordConsumer.regenerate_csv()` to update the CSV export snapshot atomically.
