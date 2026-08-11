# Gate B Staging Evidence Register

Use this register only in the approved staging Supabase project and only with
invented data. A local pre-flight result is not a substitute for an entry here.
Complete every field for every scenario; attach the immutable build/commit,
sanitised logs or metrics, and the related defect if one is found.

| Scenario | Required staging proof | Tester / date | Commit / environment | Expected / actual result | Sanitised logs or metrics | Defect link | Status |
|---|---|---|---|---|---|---|---|
| 1 | `off` creates no review, outbox, or remote item. | | | | | | Not run |
| 2 | Review-all record-only reaches SQLite, CSV, and local reconciliation. | | | | | | Not run |
| 3 | Review-all OpenClaw task completes through the staging gateway. | | | | | | Not run |
| 4 | Preview, stored, and remote canonical hashes match. | | | | | | Not run |
| 5 | Rejection creates no outbound item. | | | | | | Not run |
| 6 | Edited content is reassessed before release. | | | | | | Not run |
| 7 | Unauthorised trusted mode is rejected. | | | | | | Not run |
| 8 | Authorised low-risk trusted mode completes. | | | | | | Not run |
| 9 | High-risk, failed-assessment, and wrong-policy trusted items pause or reject. | | | | | | Not run |
| 10 | Network loss before submission retries without duplicate remote rows. | | | | | | Not run |
| 11 | Lost server submission response returns an exact idempotent result. | | | | | | Not run |
| 12 | Worker crash after claim safely reclaims. | | | | | | Not run |
| 13 | Lost completion response does not repeat side effects. | | | | | | Not run |
| 14 | Wrong worker capability and wrong or expired lease are rejected. | | | | | | Not run |
| 15 | Tampered content, hash, approval, signature, nonce, schema, or target is rejected. | | | | | | Not run |
| 16 | Oversized and deeply nested content is rejected. | | | | | | Not run |
| 17 | Dead letter is visible in monitoring and desktop state. | | | | | | Not run |
| 18 | Retention deletes only eligible terminal synthetic records. | | | | | | Not run |
| 19 | Emergency disable stops new submissions and claims. | | | | | | Not run |
| 20 | Credential rotation and rollback succeed. | | | | | | Not run |

Gate B is complete only when all twenty rows pass, evidence is attached, the
worktree is clean, and the release engineer records an approval below.

| Release engineer | Date | Commit | Decision | Notes |
|---|---|---|---|---|
| | | | Pending | |
