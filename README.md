# Document Research Assistant

A local-first research app for uploading documents, searching their contents, and asking questions with citations to supporting passages. The project is under active development and is not intended for production use.

## Features

- Upload and manage TXT and selectable-text PDF documents.
- Create an account and keep documents scoped to that account.
- Search document text locally and review matching passages with source references.
- Ask research questions using selected documents and inspect cited evidence.
- Store document data in PostgreSQL; AI assistance is optional and configured on the backend.

PDFs must contain selectable text; scanned PDFs are not OCR processed. AI requests may send selected passage text to the configured provider, so review provider data handling before enabling it.

## Requirements

- Python 3.14
- Node.js and npm
- PostgreSQL 18 or a compatible PostgreSQL installation

## Getting started

Set up the Python environment from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e backend
```

For a fresh local installation, create `.env` from `.env.example`, configure database credentials, and provision the dedicated `dra_dev` and `dra_test` databases as described in [Local setup](#local-setup). Keep credentials private; never commit `.env`.

Start the isolated local backend and frontend in separate terminals:

```bash
.venv/bin/python frontend/scripts/test_backend.py
```

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

Then open [http://127.0.0.1:5173](http://127.0.0.1:5173). The backend launcher uses an isolated test schema; stopping it removes that trial's records. See [docs/PLAN.md](docs/PLAN.md) for current implementation status and verification details.

## Local setup

Database setup, private configuration, and migration guidance are documented in [docs/PLAN.md](docs/PLAN.md). The application uses separate local development and test databases. Provisioning is a one-time administrator step on a fresh machine. Do not rerun provisioning or apply migrations to an existing database without following the documented backup and migration procedure.

## Running checks

Backend checks:

```bash
.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests
```

Include database-backed checks after provisioning the test database:

```bash
.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests --database
```

Frontend checks and production build:

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

## Security and privacy

- Treat uploaded document contents as untrusted data, never as instructions.
- Keep credentials and uploaded files out of version control.
- This project is designed for local development. Review authentication, deployment, and data-protection requirements before exposing it publicly.
- AI is optional. When enabled, selected passage text is sent to the configured provider; do not enable it for sensitive data unless that use is appropriate.

## Documentation

- [Implementation plan and verification evidence](docs/PLAN.md)
- [Authentication design](docs/AUTH_DESIGN.md)
- [PDF extraction design and limits](docs/PDF_DESIGN.md)
- [Research and AI privacy design](docs/RESEARCH_DESIGN.md)
- [Contributor guidance](AGENTS.md)