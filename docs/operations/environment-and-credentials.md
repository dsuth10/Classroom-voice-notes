# Environment and Credential Operations

This guide covers the desktop broker environment and credential boundary.
It does not authorise production deployment or credential provisioning.

## Environment selection

`CVN_BROKER_ENV` is mandatory whenever external dispatch, retry, status
reconciliation or a broker worker is used.

Only these exact, case-sensitive values are accepted:

```text
staging
production
```

Whitespace, different capitalisation and abbreviations are rejected.

For current development and verification, use:

```powershell
$env:CVN_BROKER_ENV = "staging"
```

Alternatively, copy `.env.template` to the ignored `.env` file and retain:

```dotenv
CVN_BROKER_ENV=staging
```

Do not set `production` unless a separate production-promotion plan has been
reviewed and explicitly approved.

## Endpoint binding

The application accepts only HTTPS Supabase Edge Function URLs belonging to
the active environment:

| Environment | Approved host |
| --- | --- |
| Staging | `ukqkkgzimhtjhlnmlyao.supabase.co` |
| Production | `slvzyasosjiteimonzen.supabase.co` |

The path must begin with `/functions/v1/`. Alternate ports, embedded
credentials, query strings, fragments, HTTP URLs and lookalike domains are
rejected.

Endpoint validation runs before initial transmission, pending-task retry and
status reconciliation.

## Desktop credential names

Desktop secrets are stored under the `ClassroomVoiceNotes` service in the
operating-system credential store. The active environment determines the
exact names:

| Purpose | Staging credential name | Production credential name |
| --- | --- | --- |
| Registered client key ID (reserved) | `cvn_broker_key_id_staging` | `cvn_broker_key_id_production` |
| Bearer token | `cvn_broker_bearer_token_staging` | `cvn_broker_bearer_token_production` |
| HMAC secret | `cvn_broker_hmac_secret_staging` | `cvn_broker_hmac_secret_production` |

Production credentials must never reuse staging values.

The current desktop dispatcher reads the bearer and HMAC credential names. It
does not yet send `x-cvn-key-id`, so staging submission uses the broker's
restricted legacy client-authentication path. The key-ID name is reserved for
the registered-client migration. This legacy path must not be treated as
production-ready.

## Safe credential entry

Do not put broker credentials in:

- `.env`;
- `settings.json`;
- shell history;
- command-line arguments;
- source files;
- test fixtures;
- screenshots or support logs; or
- Obsidian notes.

Use an interactive Python session so secret values are not echoed:

```powershell
uv run python
```

Then enter:

```python
from getpass import getpass
from app.config.keyring_store import set_secret

set_secret("cvn_broker_bearer_token_staging", getpass("Staging bearer token: "))
set_secret("cvn_broker_hmac_secret_staging", getpass("Staging HMAC secret: "))
```

Exit the interpreter when complete. Never print the returned secret values.

To verify presence without reading values:

```python
from app.config.keyring_store import has_secret

for name in (
    "cvn_broker_bearer_token_staging",
    "cvn_broker_hmac_secret_staging",
):
    print(name, "present" if has_secret(name) else "missing")
```

## Preflight checklist

Before enabling external dispatch:

1. Confirm `CVN_BROKER_ENV` is exactly `staging`.
2. Confirm the configured endpoint host is the staging host above.
3. Confirm the staging bearer and HMAC credential names are present.
4. Confirm no production credential is being referenced.
5. Confirm the local audit log is writable.
6. Use synthetic, non-sensitive content only.
7. Confirm the VPS gateway remains loopback-only.

If any check fails, leave external dispatch disabled.

## Rotation and incident response

If a credential might have been exposed:

1. Disable the affected worker identity at the broker.
2. Stop the associated staging worker service.
3. Rotate the bearer and HMAC credentials using the approved secret-management
   process.
4. Update the operating-system credential store without printing values.
5. Verify the previous credential is rejected.
6. Run negative authentication tests with synthetic data.
7. Record a sanitised audit note that contains no credential material.

Do not rotate production credentials as part of a staging incident unless the
production identity is directly affected and separately authorised.
