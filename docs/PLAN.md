# Implementation plan

All milestones are **planned, not implemented**. Implement one agreed milestone at a time.

## Milestone 1 — local document API (planned)

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

Create the minimal backend structure, dependency declarations, configuration, and database migration for documents. Implement the agreed validation conventions, transactional upload, and metadata listing. Add meaningful tests using PostgreSQL, verify restart persistence and rollback, and document reproducible local setup and checks.

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
