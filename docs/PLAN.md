# Implementation plan

Milestone 1 is **in progress**; later milestones remain **planned**. Implement one agreed milestone at a time.

## Milestone 1 — local document API (in progress)

Use Python, FastAPI, and PostgreSQL in one backend application. Separate API handling, validation, document operations, and persistence into clear modules. Add no further infrastructure without a concrete requirement. Use FastAPI's API documentation interface for manual trials; the frontend comes later.

### Proposed contract

- `POST /documents`: accept one multipart file with a `.txt` extension and valid UTF-8 content, with a maximum size of 1,048,576 bytes (1 MiB). Return `201` with document ID, original filename, byte size, and creation timestamp after committing the record.
- `GET /documents`: return a list containing those metadata fields, without document content; return an empty list when no documents exist.
- Store the decoded content and metadata together in PostgreSQL. Use an atomic transaction so validation or persistence failures leave no partial document record.
- Agreed validation conventions: reject zero-byte files and decoded whitespace-only content as empty; accept `.txt` extensions case-insensitively. Preserve accepted text without trimming it.
- Return clear client errors identifying the cause: `400` for empty content, unsupported extensions, or invalid UTF-8; `413` for files exceeding the limit. Enforce the byte limit while reading, even if the client omits or misstates its declared size.

### Acceptance evidence required

- A valid upload returns a document ID and the expected metadata, with content and metadata saved in PostgreSQL.
- Empty files, unsupported extensions, invalid UTF-8, and files larger than 1 MiB produce clear client errors. Test the exact size boundary as well.
- The list endpoint returns document metadata without full content, including an empty list before any uploads.
- Saved documents remain available after restarting the backend against the same PostgreSQL database.
- Rejected uploads and simulated persistence failures leave no partial document record; verify transaction rollback against PostgreSQL.
- Automated tests cover important success and failure behavior; record actual check results and a manual trial through the API documentation interface.

Local development only: bind the API for local access and document that limitation. Authentication and per-user authorization are required before public document access. Use synthetic test documents; never commit secrets or uploaded files. Treat document content as untrusted data, never as instructions.

### Next implementation step

The foundation and its PostgreSQL verification are complete. Next, implement upload validation, transactional upload, and metadata listing, with tests for the agreed API behavior. Milestone 1 remains in progress until all acceptance criteria are verified.

### Foundation progress

Implemented:

- Minimal FastAPI application with `GET /health` (liveness only; no database query).
- Project-local virtual environment; runtime/test/build dependencies resolved for Python 3.14.7 and pinned in `backend/requirements.lock`.
- Validated configuration, ignored private `.env`, and tracked placeholder `.env.example`.
- Synchronous SQLAlchemy/psycopg setup, document mapping, and initial Alembic migration with database constraints.
- Database identity guard and provisioning script that refuses existing names. Dedicated development/test roles and databases were provisioned privately; no unrelated database, role, or server configuration was changed by this verification.
- Setup, migration, local run, and test instructions.

Verification:

- Application import: passed; document endpoints are absent.
- Dependency compatibility: installation on Python 3.14.7 and `pip check` passed.
- Real HTTP request on loopback: `/health` returned `200 {"status":"ok"}`; temporary verification server stopped afterward.
- Offline Alembic SQL generation: passed; this is not live PostgreSQL execution.
- Initial sandbox test run stalled at the HTTP test and was interrupted. Tests are run outside the sandbox because of its socket restrictions.
- Database authentication: passed for `dra_dev` and `dra_test`, each with the matching database name and owner. Role and database markers matched `document-research-assistant:development` and `document-research-assistant:test`, respectively. Both roles lack superuser, database creation, role creation, replication, and RLS bypass privileges. No credentials were displayed.
- Development migration: `alembic upgrade head` passed; current revision is `0001_documents (head)`.
- Development live schema check: passed for project identity, column types/nullability, primary key, timezone-aware timestamp, all five check constraints, and migration revision.
- Automated checks with `--database`: **36 passed, 0 failed, 0 skipped**. Test migrations and synthetic row mutations used only the verified `dra_test` database; test rows were rolled back. Health tests verify document endpoints are absent and liveness never opens a database connection.
- Checkpoint review: added `path_separator = os`, matching the installed Alembic 1.20.0 template. `alembic current` reports `0001_documents (head)`; `alembic check` reports no new upgrade operations; the live schema check passed. The full PostgreSQL suite passed again with deprecation warnings treated as errors: **36 passed, 0 failed, 0 skipped, 0 warnings**.
- Git review: `.env`, virtual environments and caches are excluded; no configured credential values were found in tracked/index files or proposed nonignored files. Nothing was staged. The existing local `.vscode/settings.json` was preserved and narrowly ignored for the checkpoint.
- The earlier database-access blocker is resolved by private provisioning and configuration; administrator access was not needed for this verification.

Remaining:

- Implement upload and metadata-only listing with agreed validation and client errors.
- Verify all upload acceptance criteria, transaction failure behavior, restart persistence, and manual API documentation trials.
- Keep authentication and per-user authorization mandatory before public access. No frontend, AI features, containers, or public deployment are part of this foundation.

## Later milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| 2 | Minimal React and TypeScript interface for uploading and listing documents | Planned |
| 3 | User accounts and per-user document access | Planned |
| 4 | PDF extraction with explicit handling of unsupported scanned PDFs | Planned |
| 5 | Retrieval and document questions with verifiable citations | Planned |
| 6 | Saved conversations and explicit user preferences | Planned |
| 7 | Bounded agent workflows for comparing documents | Planned |
| 8 | Deployment, monitoring, and recovery | Planned |

Define acceptance criteria for each later milestone when it becomes the agreed focus. Any public deployment must follow the access-control milestone.
