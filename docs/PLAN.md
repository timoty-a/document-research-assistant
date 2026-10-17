# Implementation plan

Milestones 1 and 2 are **complete**. Milestones 3–8 remain **planned**. Implement one agreed milestone at a time.

## Milestone 1 — local document API (complete)

Use Python, FastAPI, and PostgreSQL in one backend application. Separate API handling, validation, document operations, and persistence into clear modules. Add no further infrastructure without a concrete requirement. Use FastAPI's API documentation interface for manual trials; the frontend comes later.

### API contract

- `POST /documents`: accept one multipart file with a `.txt` extension and valid UTF-8 content, with a maximum size of 1,048,576 bytes (1 MiB). Return `201` with document ID, original filename, byte size, and creation timestamp after committing the record.
- `GET /documents`: return a list containing those metadata fields, without document content; return an empty list when no documents exist.
- Store the decoded content and metadata together in PostgreSQL. Use an atomic transaction so validation or persistence failures leave no partial document record.
- Agreed validation conventions: reject zero-byte files and decoded whitespace-only content as empty; accept `.txt` extensions case-insensitively. Preserve accepted text without trimming it.
- Reject NUL characters in content or filenames because PostgreSQL text cannot store them. Treat filenames only as metadata and validate the existing `TEXT` storage bound without inventing a filesystem filename limit.
- Return clear client errors identifying the cause: `400` for empty content, unsupported extensions, invalid UTF-8, NUL characters, or invalid filenames; `413` for files exceeding the limit; standard FastAPI `422` for a missing file. Database failures return a sanitized `503` without sensitive details or exception logging.
- Enforce the byte limit while reading, even if the client omits or misstates its declared size. Multipart parsing precedes this check and can buffer/spool data; no total HTTP request-size limit is claimed.
- List metadata only, selecting no content column, ordered by creation timestamp and UUID ascending.

### Acceptance criteria

- A valid upload returns a document ID and the expected metadata, with content and metadata saved in PostgreSQL.
- Empty files, unsupported extensions, invalid UTF-8, and files larger than 1 MiB produce clear client errors. Test the exact size boundary as well.
- The list endpoint returns document metadata without full content, including an empty list before any uploads.
- Saved documents remain available after restarting the backend against the same PostgreSQL database.
- Rejected uploads and simulated persistence failures leave no partial document record; verify transaction rollback against PostgreSQL.
- Automated tests cover important success and failure behavior; record actual check results and a manual trial through the API documentation interface.

Local development only: bind the API for local access and document that limitation. Authentication and per-user authorization are required before public document access. Use synthetic test documents; never commit secrets or uploaded files. Treat document content as untrusted data, never as instructions.

### Next milestone

Milestone 1 has no remaining work: automated checks and the user-reported manual API trial provide its completion evidence. Milestone 2, the React upload/list interface using the polished refined prototype, is also complete; its evidence is recorded below.

### Milestone 1 progress

Implemented:

- Minimal FastAPI application with `GET /health` (liveness only; no database query).
- Project-local virtual environment; runtime/test/build dependencies resolved for Python 3.14.7 and pinned in `backend/requirements.lock`.
- Validated configuration, ignored private `.env`, and tracked placeholder `.env.example`.
- Synchronous SQLAlchemy/psycopg setup, document mapping, and initial Alembic migration with database constraints.
- Database identity guard and provisioning script that refuses existing names. Dedicated development/test roles and databases were provisioned privately; no unrelated database, role, or server configuration was changed by this verification.
- Setup, migration, local run, and test instructions.
- Synchronous upload and metadata-listing handlers, bounded file reads, strict validation, metadata-only responses/SQL projection, deterministic ordering, and atomic commit-before-success storage.
- Only the multipart parser dependency was added, pinned as `python-multipart==0.0.32` in the resolved lock. No schema migration was needed.

Milestone 1 automated verification:

- Application import and liveness checks passed; health remains independent of database readiness. OpenAPI now includes both document endpoints.
- Dependency compatibility: installation on Python 3.14.7 and `pip check` passed.
- Real HTTP request on loopback: `/health` returned `200 {"status":"ok"}`; temporary verification server stopped afterward.
- Offline Alembic SQL generation: passed; this is not live PostgreSQL execution.
- Initial sandbox test run stalled at the HTTP test and was interrupted. Tests are run outside the sandbox because of its socket restrictions.
- Database authentication: passed for `dra_dev` and `dra_test`, each with the matching database name and owner. Role and database markers matched `document-research-assistant:development` and `document-research-assistant:test`, respectively. Both roles lack superuser, database creation, role creation, replication, and RLS bypass privileges. No credentials were displayed.
- Development migration: `alembic upgrade head` passed; current revision is `0001_documents (head)`.
- Development live schema check: passed for project identity, column types/nullability, primary key, timezone-aware timestamp, all five check constraints, and migration revision.
- Full suite with `--database` and deprecation warnings treated as errors: **69 passed, 0 failed, 0 skipped, 0 warnings**. All test mutations used only the verified `dra_test` database. Foundation rows were rolled back; API tests used unique schemas cloned from the migrated table, performed real commits, and removed only their own schemas afterward.
- Upload/list checks cover exact persisted text (including whitespace, CRLF and BOM), metadata-only responses and SQL selection, empty lists and ordering ties, uppercase extensions, invalid filenames/UTF-8/NUL, whitespace-only text, multibyte byte counts, exactly 1 MiB and one byte over, missing files, duplicate uploads, bounded reads and file closure.
- Failures injected after a write and at commit returned sanitized `503` responses, exposed no partial row to a separate connection, rolled back the row, and allowed a subsequent successful upload. A committed document remained available through a fresh application and physical database connection.
- The initial feature run had 68 passes and one test failure: HTTPX percent-escaped the synthetic filename's NUL. The test was corrected to send literal invalid multipart metadata; the final suite passed. No invalid-filename exception was waived.
- Earlier foundation checkpoint: added `path_separator = os`, matching the installed Alembic 1.20.0 template. `alembic current` reported `0001_documents (head)`; `alembic check` reported no new upgrade operations; the live schema check passed. Its then-current PostgreSQL suite passed all 36 tests without warnings.
- Git review: `.env`, virtual environments and caches are excluded; no configured credential values were found in tracked/index files or proposed nonignored files. Nothing was staged. The existing local `.vscode/settings.json` was preserved and narrowly ignored for the checkpoint.
- The earlier database-access blocker is resolved by private provisioning and configuration; administrator access was not needed for this verification.

User-reported manual verification:

- Document listing works.
- A valid `.txt` upload returns `201` and metadata.
- The uploaded document appears in the list without its content.
- Empty files and unsupported extensions return `400`.
- The document remains listed after restarting the backend.

Together with the automated checks above, these manual results complete milestone 1. Authentication and per-user authorization remain mandatory before public access; they are future work, not part of this local milestone. Milestone 2 progress is recorded separately below.

## Milestone 2 — React document library (complete)

Acceptance criteria:

- Real single-file selection, explicit upload, metadata listing/count, Refresh, and expandable Details match the refined prototype. No synthetic records or preview toolbar in the application.
- Show TXT/UTF-8/1 MiB limits, client extension/zero-byte/size checks, and authoritative backend errors. Render filenames as text.
- Relative `/documents` requests through a loopback Vite proxy; no frontend dotenv loading or database credentials in public configuration.
- Separate initial loading/empty/refresh/upload/success/rejection/uncertain states; never automatically retry POST. Only validated `201` metadata confirms saving.
- Preserve rows, open Details, and confirmed uploads during refresh/failure; reconcile by ID in backend order and guard against stale responses.
- Keyboard controls, visible focus, status announcements, long filenames, and usable 320px/mobile/desktop layouts.
- Meaningful component tests, TypeScript/build checks, isolated real PostgreSQL/browser upload-list-reload trial, and a user manual trial before completion.

Implemented:

- React/TypeScript/Vite in `frontend/`; exact dependencies and reproducible npm lockfile. Node 22.23.1/npm 10.9.8 satisfy package engines; no system replacements or global installs.
- Small API module with runtime response validation and sanitized errors; library hook for request ordering, confirmed IDs, duplicate submission prevention, and explicit uncertain-outcome recovery; separate metadata-list component.
- Refined warm-paper design, serif heading, sans-serif filenames, 13px metadata, responsive aligned rows, native file picker, compact upload form, and stronger empty-state upload emphasis.
- Fixed local proxy and isolated trial launcher using a guarded temporary schema in `dra_test`. Backend source and behaviour unchanged.

Verification on 15 October 2026:

- **32 frontend component tests passed**, 0 failed/skipped. HTTP is mocked: success, FormData boundary handling, exact client byte boundary, validation, duplicate filenames, HTML-like filename escaping, keyboard order, stale list/initial responses, failed refresh after upload, malformed success/list responses, ambiguous network/server failures, refresh-before-explicit-retry, and timestamp/ID ordering.
- TypeScript checks and production build passed. `npm ls --depth=0` passed; npm installation audit reported 0 known vulnerabilities.
- Existing backend suite with PostgreSQL enabled: **69 passed**, 0 failed/skipped. Fixtures restricted mutations to verified `dra_test` schemas.
- Real built-in browser: native file picker, four real synthetic uploads (including duplicate and long names), metadata listing, and persistence after page reload passed. Invalid UTF-8 produced a clear rejection and left the count at four. A fresh PostgreSQL connection independently verified committed rows, byte sizes, and exact synthetic text.
- Browser inspection passed at 1440px, 390px, and 320px: wrapping, expanded Details, keyboard activation/focus, and no horizontal overflow. Generated captures remain local in ignored screenshot folders and are excluded from Git.
- Type checking initially failed on an unsupported test-query option; corrected. The first component run had one faulty filename-length assertion (27 passed/1 failed); corrected to compare the full filename. Final runs passed. The first check started before dependency installation completed and could not find `tsc`; rerun successfully afterward.
- Browser raw network instrumentation was declined by browser security policy and was not bypassed. Ordinary browser file upload worked; real HTTP status instrumentation was not separately captured. Race/failure injection is mocked, not real-browser fault injection. Native zoom and screen-reader behaviour remain unverified for React.

User-reported manual verification on 17 October 2026:

- Uploading and document listing worked.
- Refresh and expandable Details worked.
- Documents remained available after page reload.
- No errors or layout problems were reported.

This confirms the manual trial separately from the automated and agent-operated browser evidence above. The user did not report a separate screen-reader, zoom, or injected-failure audit; the previously recorded verification limits remain. Tests were not rerun for this documentation-only update.

Milestone 2 has no remaining implementation work. Milestone 3 remains planned and has not started. Authentication, PDFs, AI, and public deployment are outside this milestone; keep both applications local.

## Later milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| 2 | Minimal React and TypeScript interface for uploading and listing documents | Complete |
| 3 | User accounts and per-user document access | Planned |
| 4 | PDF extraction with explicit handling of unsupported scanned PDFs | Planned |
| 5 | Retrieval and document questions with verifiable citations | Planned |
| 6 | Saved conversations and explicit user preferences | Planned |
| 7 | Bounded agent workflows for comparing documents | Planned |
| 8 | Deployment, monitoring, and recovery | Planned |

Define acceptance criteria for each later milestone when it becomes the agreed focus. Any public deployment must follow the access-control milestone.
