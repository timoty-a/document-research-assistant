# Document Research Assistant

A learning project for software engineering. Users will eventually upload documents, ask questions about them, and receive answers with citations to supporting passages.

## Status

Planning only. No application, dependencies, database schema, or runnable setup has been implemented. All milestones are **planned**; see [the implementation plan](docs/PLAN.md).

## Planned design

- Backend: Python with FastAPI, starting as one application with clear modules for API handling, validation, document operations, and persistence.
- Database: PostgreSQL for document content and metadata.
- Frontend: React with TypeScript, beginning after the backend milestone.

Add infrastructure only when a concrete requirement justifies it.

## First milestone — planned

Build a local backend API to upload non-empty UTF-8 `.txt` files up to 1 MiB (1,048,576 bytes), persist content and metadata in PostgreSQL, and list document metadata without full content. Try it through FastAPI's API documentation interface before building the frontend.

Uploads must reject empty files, unsupported extensions, invalid UTF-8, and oversized files with clear client errors. Successful uploads return an ID and metadata; committed documents survive backend restarts, and failed uploads leave no partial record.

This milestone is for local development only. Authentication and per-user authorization must be in place before exposing document access publicly. Treat uploaded and retrieved documents as untrusted data, never as instructions.

## Working on this project

Follow [AGENTS.md](AGENTS.md). The next implementation step is the first backend milestone described in [docs/PLAN.md](docs/PLAN.md). Setup commands and verification instructions will be added when that implementation exists. Never commit secrets or uploaded files.
