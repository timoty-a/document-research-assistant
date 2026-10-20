# Implementation plan

Milestones 1–3 are **complete** for their agreed local scope; milestone 4 is **in progress** pending its PDF manual trial; milestone 5 is the user-authorized active prototype increment, **in progress**; milestones 6–8 remain **planned**. Development authentication migration is a separate, unexecuted operator step. Implement one agreed milestone at a time.

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

Milestone 2 has no remaining implementation work. Milestone 3 authentication work and its successful user manual trial are recorded below. Authentication, PDFs, AI, and public deployment are outside this milestone; keep both applications local.

## Milestone 3 — authentication and ownership (complete — local scope)

The user selected the local defaults in [AUTH_DESIGN.md](AUTH_DESIGN.md) and authorized backend implementation first, then the frontend integration. The user confirmed the remaining manual checks after retrying the file picker fix.

Implemented backend:

- `0002_auth`: users, opaque server-side sessions, atomic PostgreSQL rate counters, nullable document ownership/FK and `(owner_id, created_at, id)` index. Historical documents stay null/unassigned and invisible to accounts; no reset, deletion or reassignment.
- `pwdlib` Argon2id (64 MiB, three iterations, four lanes), two-operation process concurrency bound, canonical case-insensitive email identity, generic registration followed by explicit login, profile upgrade on login.
- Register/login/logout/me/CSRF endpoints, pre-session CSRF, exact Origin checks, HttpOnly local cookies, absolute/idle expiry, rotation and revocation, no-store responses and public session-context headers.
- Authentication before multipart parsing; document services lock/revalidate the session and derive ownership from it inside their transactions. Owner-filtered metadata lists retain the previous response format and ordering.
- Bounded, lock-aware cleanup and synthetic hash benchmark commands; dependency lock and private backup/migration instructions. The frontend integration is recorded separately below.

Backend automated verification on 17 October 2026:

- Full PostgreSQL-enabled suite: **154 passed, 0 failed/skipped/warnings** (74.08 seconds), with deprecation warnings treated as errors. HTTPX ASGI transport exercises the real app and real PostgreSQL, not a browser or TCP server.
- Live migration/model/default/constraint consistency and actual `alembic check` passed in isolated migrated schemas; offline SQL generation, compilation, installation and `pip check` passed.
- Coverage: legacy migration preservation/rollback/resume/refused downgrade, credential limits/normalization/hash upgrades, concurrent registrations/logins, session lifecycle and fresh-app restoration, CSRF/Origin, atomic HTTP/SQL throttles, two-user isolation/forged ownership, pre-parser/pre-body unauthorized rejection, rollback/commit failures, locked write/logout/expiry ordering and bounded cleanup preserving live activity. Existing authenticated document behaviour remains covered.
- Argon2id benchmark: two concurrent operations, eight hash/verify pairs; median hash 0.258 s, verification 0.276 s, total 2.184 s, peak process RSS 328.0 MiB. This is a local measurement, not a total memory bound or production load test.
- Initial runs found old tests coupled to schema/commit details and a client-side malformed-Unicode encoding failure; fixed. Deprecated TestClient usage was replaced by existing HTTPX ASGI transport. Final suite has no unresolved failures or skips.
- `git diff --check` passed; changed/new files contain no configured credential-value matches. Private `.env`, environments and generated dependencies remain ignored. No frontend changes, staging, commit or push.

 All migrations and mutations use generated schemas in guarded `dra_test`; shared `public` and development are not migrated. Development was checked read-only and remains at `0001_documents`, without auth tables.

Frontend implemented and verified on 17 October 2026:

- Paper/teal Login/Register forms, correct autocomplete/labels, validation/errors/pending states, generic registration with explicit login, session restoration, account header/Logout, local verification/recovery notice.
- In-memory CSRF, same-origin cookies, `/auth` Vite proxy, runtime response validation, session-context headers and generation guards. Private library state unmounts on logout/revalidation/account changes; stale responses (including `401`) cannot populate another session. Failed logout keeps the view hidden with explicit retry; no mutation is automatically replayed. Focus revalidation hides the library while retaining its mounted file input for an unchanged session; changed/expired/unavailable sessions still clear private data.
- Updated trial launcher guards `dra_test`, runs real migrations only in its generated schema with a private search path, disables proxy headers and removes only that schema on exit. No backend application changes were needed.

Frontend automated evidence: **60 mocked component/API tests passed**, 0 failed/skipped; TypeScript and production build passed. Tests cover auth flows/errors, pending/duplicate prevention, restoration and unavailable states, logout failure/retry, CSRF/context mismatch, cross-tab/focus boundaries, session races, stale login/upload/list/401 responses, same-user rotation, no credential persistence and existing library behavior. Initial type/test-fixture issues and an old mutation’s pending flag crossing a session boundary were fixed; the final suite passed. Earlier backend evidence remains **154 passed**; it was not rerun for unchanged backend application code.

Agent-operated real browser evidence (not the user’s manual trial): A/B registration and explicit login, native picker uploads, reload restoration, logout/account switching and cross-tab propagation passed against isolated PostgreSQL. A saw three owned records (including duplicate/long names); B started empty and saw only its separate same-named upload; switching back restored A’s three. A fresh SQL connection confirmed ownership, four committed rows, exact synthetic text and `0002_auth`. Desktop 1440px, mobile 390px and narrow 320px wrapping, expanded metadata, keyboard access/focus and no horizontal overflow were checked. Empty-credential login/library screenshots remain ignored; no passwords or tokens were captured. A terminated Vite trial process was restarted; browser verification recovered in a fresh localhost tab. Both servers were stopped afterward and test-schema removal was independently confirmed. `git diff --check` and changed-file credential scans passed; generated/private files remain ignored, and nothing was staged, committed or pushed.

User manual trial feedback and correction — 17 October 2026: login worked, but selecting a file reset the library. The focus handler was remounting the file input when the native picker closed. A failing regression reproduced that behavior; the fix preserves the input and selected file for an unchanged session while keeping the view hidden during verification. Six new test cases cover before/after change-event timing, upload success after focus, in-flight confirmation retention, stale focus checks and expired/unavailable session clearing. Final frontend checks: **60 passed**, TypeScript/build passed. A fresh isolated real browser trial confirmed selection, upload appearing in the list and persistence after reload. Native OS timing is covered by mocked event orderings rather than a claim that every native dialog was exercised. Backend behavior is unchanged; development was not migrated. The user subsequently confirmed the upload fix works.

User-reported manual verification — 17 October 2026:

- Login works.
- Selecting and uploading a document works after the file picker fix.
- The session is restored after refreshing the page.
- Logout works.
- Switching between two accounts shows only the respective account’s documents.

These confirmations are separate from the 154 backend tests, 60 mocked frontend tests and agent-operated browser checks above. Together they complete milestone 3’s agreed local implementation and manual trial. The user did not report a separate registration, keyboard/mobile, screen-reader, native-zoom or fault-injection audit; do not extend the confirmation to those checks. No tests were rerun for this documentation-only status update; `git diff --check` passed.

Operational follow-up, not performed or authorized by this confirmation: development migration and a private backup/restore drill. `dra_dev` remains at `0001_documents`; historical documents remain unassigned. Real browser fault injection, screen-reader/native-zoom and long-duration expiry checks retain their recorded limits. HTTPS cookies, email verification/recovery and public deployment remain outside the completed local scope.

## Milestone 4 — selectable-text PDFs (in progress)

The selected design and its corrections are in [PDF_DESIGN.md](PDF_DESIGN.md). The user approved accepting mixed PDFs with explicit textless-page warnings, then authorized implementation. Keep the source library design and existing TXT/auth behaviour.

Implemented:

- pypdf 6.21.1, reproducible backend lock; strict page-by-page extraction in a fresh minimal child process, with 1 MiB input, 100 pages, bounded extracted text/IPC, one process slot, CPU/wall/address-space limits and cleanup. Encrypted, malformed and entirely textless inputs are rejected; mixed pages retain physical positions and warnings.
- `0003_pdf_documents`, preserving existing TXT/ownership data, retained original PDF bytes, immutable extraction profile, page rows and computed text-presence metadata. Source/document/pages commit together after locked session revalidation. No raw source/content is returned by upload or listing.
- Authenticated pre-parser 2 MiB multipart body cap; original 1 MiB file limit remains independently enforced while reading. Fixed PDF rejection codes/messages, sanitized worker/store failures, and no automatic retry.
- React accepts TXT/PDF, validates actual metadata shapes, exposes format/page/warning details, and preserves existing session, picker/focus, refresh and uncertain-save handling. Images/layout/OCR limitations are visible.

Automated verification — 17 October 2026:

- Final full backend command with `--database -W error::DeprecationWarning -q`: **202 passed, 0 failed/skipped/warnings**, 110.56 seconds. Uses real PostgreSQL in generated, guarded `dra_test` schemas and HTTPX ASGI transport. Covers existing TXT/auth behaviours plus PDF source/page persistence, metadata-only SQL, boundaries, malformed/encrypted/image-only/mixed inputs, actual subprocess limits/lifecycle, pre-parser body counting/file cleanup, ownership, rollback, logout/expiry during extraction, and legacy migration preservation/failed-DDL resume/refused downgrade. Actual Alembic/model checks pass in isolated schemas.
- **74 frontend component/API tests passed**, 0 failed/skipped, with mocked HTTP. Command: `npm --prefix frontend test -- --maxWorkers=1 --testTimeout=15000`. Includes PDF warning/error/metadata cases, stale/failed refresh and uncertain outcomes, duplicate filenames, and the existing session/picker regressions. TypeScript and production build passed. No frontend dependency/lock changes.
- `pip check`, Python compilation and offline Alembic SQL generation passed. pypdf 6.21.1 installed successfully on Python 3.14.7; its declared requirement is Python >=3.9. PyPI reported zero advisory entries for that release when checked; that is not a comprehensive security audit.
- Real-child benchmark: three small synthetic samples (mixed, rotated and image/text overlay), median 2.652 seconds, maximum 2.778 seconds. Address-space and CPU/output-file enforcement are exercised with controlled child programs; output-size branches also use reduced test limits. This is not a hostile-corpus or production capacity guarantee.
- Initial 256 MiB address-space checks rejected valid small PDFs during import; increased to 512 MiB after measuring Python/pypdf virtual memory. Fixed a synthetic exact-byte fixture's serialization overhead and a columns test that incorrectly expected an inserted newline; saved extraction remains unchanged. A generated-column reflection warning was corrected without suppressing warnings. An initial frontend run had five 5-second timeouts during overlapping resource checks; all 74 passed with the explicit single-worker/15-second settings above. An earlier backend run's final terminal result was unavailable and was not counted; the final retained complete run above passed.

Real TCP API trial — separate from mocked frontend/browser evidence:

- Started the existing isolated trial launcher, registered/logged in two synthetic accounts, saved a three-page mixed PDF with real `201`, checked textless page 2, listing and persistence through a new HTTP client. The other account saw an empty library. Image-only and encrypted uploads returned `400`.
- Fresh guarded SQL verified the exact original PDF bytes, exact aggregate text, owner, three page records and revision `0003_pdf_documents`. The real HTTP upload took 3.754 seconds. The launcher stopped and removal of only its generated schema was independently confirmed. This is API/client verification, not React or browser verification.
- Read-only development check passed: `dra_dev` still reports `0001_documents`, with no auth table. No development migration, historical assignment, operational cleanup or database reset was performed.
- `git diff --check`, changed-file configured-credential scans and ignored private/generated-path checks passed. Nothing is staged, committed or pushed.
- Final read-only cleanup inventory: zero frontend trial schemas remain; three generated integration-test schemas remain with unconfirmed originating runs. They were preserved, not broadly deleted. Their provenance/cleanup requires review; do not claim all historical test schemas are removed. The retained full suite completed successfully and the separately identified TCP trial schema was removed.

The real browser trial is blocked by the built-in browser URL policy: selecting the existing `http://127.0.0.1:5173/` tab returned “requested URL protocol is not allowed”, despite listing HTTP/HTTPS as allowed. No workaround or alternate browser surface was attempted. No PDF screenshots or visual inspection are claimed.

User manual verification: **pending** for PDF upload/list/reload, mixed-page warnings, rejection of unsupported PDFs, account isolation and responsive/keyboard behaviour. Prior TXT/auth manual confirmations do not verify PDFs. Milestone 4 stays in progress.

Development remains unmigrated at the documented `0001_documents`; only guarded isolated `dra_test` schemas may be migrated here. No ownerless documents are assigned/deleted. Development migration and private backup recovery verification remain separate outstanding operator work. Local completion will not establish production readiness.

## Milestone 5 — questions and inspectable evidence (in progress)

The user authorized autonomous increments toward a TXT/PDF → research question → synthesized answer → passage/page-citation prototype, then selected Groq's free API plan. They initially deferred key configuration; their later authorization, private enablement and successful manual AI report are recorded below. See [RESEARCH_DESIGN.md](RESEARCH_DESIGN.md). Milestone 4's implementation is preserved and its manual trial remains pending; neither milestone is marked complete.

Implemented:

- One small backend research module: owner-filtered selection, bounded lexical retrieval, original Unicode-code-point quote offsets, physical PDF pages, exact provenance and bounded authenticated context. No migration, backfill, ownership reassignment or additional infrastructure.
- Separate local search and AI endpoints, pre-body authentication/Origin/CSRF, session-context/no-store responses, pre/post-generation session checks, persistent account/project attempt budgets, two per-process slots, bounded JSON/prompt/output and a 25-second total provider deadline. Blocking SQL/search and the provider adapter run in workers without holding database locks during network calls.
- Groq strict JSON claims with server-resolved evidence IDs, fixed endpoint/model, minimized payload, no tools/history/retries/provider fallback. `AI_ENABLED=false` by default; real calls remain disabled. Citation integrity checks do not prove semantic entailment, and lexical retrieval is not comprehensive.
- Approved paper/teal library with source selection, explicit local-search/Ask-AI controls, pending/no-match/error states, citation/context focus navigation, plain-text rendering and generation/session guards. Logout/source/question changes discard private results; old failures cannot invalidate a new session. No saved conversations or browser credential storage.

Automated verification — 18 October 2026:

- Final full PostgreSQL suite: **257 passed, 0 failed/skipped**, 50.92 seconds with `--database -W error::DeprecationWarning -q`. Includes PDF/auth/migration regression checks, exact Unicode windows/pages, ownership/CSRF/pre-body rejection, range/version checks, budgets/concurrency, sanitized failures and logout/expiry during generation. Mutations use generated isolated schemas in guarded `dra_test`.
- Provider HTTP is mocked, including strict schema payload, minimized disclosure, unknown/fabricated/missing references, truncation/refusal/invalid output, bounded response/total timeout, upstream failures and no retry. No key check or real provider call was made.
- **96 frontend tests passed**, 0 failed/skipped, 17.74 seconds, `--maxWorkers=1 --testTimeout=15000`; TypeScript/production build passed. Includes duplicate names, selection limits, local-only mode, explicit submission, source/question/context/session races, malformed responses, plain-text rendering, citation focus and logout clearing alongside existing picker/session regressions.
- Initial test-only errors were corrected: a user-isolation assertion requested AI despite disabled configuration, and typed fetch mocks needed accurate signatures. The final complete runs above passed. Earlier partial results are not counted as final evidence.

Separate real TCP API trial: synthetic registration/login, exact Unicode TXT and mixed three-page PDF uploads, local search, physical page/context inspection, fresh-client persistence, two-user list/research/context isolation and disabled-AI rejection all passed. SQL confirmed two committed rows and `0003_pdf_documents` in the single generated trial schema. The launcher stopped, and removal of exactly that schema was confirmed; pre-existing schemas were preserved. No external service or React/browser trial is implied by this API check.

Final hygiene checks: `pip check`, Python compilation and `git diff --check` passed. Changed-file scans found no configured database credential values or key-pattern matches; `.env`, virtual environments, dependencies and build output remain ignored/untracked. A fresh read-only `dra_dev` check confirmed `0001_documents` without auth tables. Nothing was staged, committed or pushed.

Outstanding: user PDF/research trial; live synthetic Groq connectivity/strict-model compatibility, answer usefulness and live quota/failure behavior; current desktop/mobile/keyboard browser inspection (blocked by the previously recorded built-in browser URL-policy rejection, no workaround or screenshots); private backup/restore drill and any separately authorized development migration. Three historical integration schemas of unconfirmed provenance remain preserved for review. `dra_dev` remains unmigrated. No commit/push, deployment or production-readiness claim.

Acceptance before prototype completion: user can upload TXT/PDF under their own account, select sources, search and inspect exact context/page citations, then—after private free-plan key setup—receive a real synthetic grounded answer with inspectable references. Confirm empty/pending/rejected/uncertain states, account isolation and session clearing, keyboard/mobile operation and no automatic replay. Record automated, API, browser, live-provider and user evidence separately. Do not mark completion based on mocked AI alone.

### Repeat verification — 20 October 2026

At the user's request, reran the current implementation: **257 backend tests passed**, 0 failed/skipped (51.06 s), with PostgreSQL enabled and deprecation warnings as errors; **96 mocked frontend tests passed** (17.84 s), TypeScript and production build passed. Dependency checks passed. No application code changed during this verification.

A separate real HTTP trial in one generated, guarded `dra_test` schema passed registration/login, empty listing, TXT/PDF upload and metadata-only listing, duplicate filenames, mixed-page metadata, exact Unicode quote offsets and physical PDF citation/context inspection, no-match search, fresh-client session/list restoration, logout and unauthenticated rejection. Empty/whitespace, unsupported extension, invalid UTF-8, NUL, scanned and encrypted inputs were rejected. A second account could neither list nor inspect/research the first account's sources. AI was explicitly disabled for the trial; relevant AI requests were rejected without provider calls. Three committed synthetic documents were confirmed by SQL; only the trial schema was removed, with pre-existing schemas preserved.

This is automated/API evidence, not a new browser trial or proof of real AI synthesis. The prior browser URL-policy limitation remains; no current visual inspection or screenshots are claimed. The user reported testing the prototype without specifying individual outcomes; do not expand that report into detailed manual acceptance evidence or mark either milestone complete. Live Groq and the recorded operational/accessibility gaps remain outstanding. No development migration, historical ownership assignment, commit or push.

### Manual AI trial and checkpoint review — 20 October 2026

The user requested live AI use, privately configured `GROQ_API_KEY` and `AI_ENABLED=true`, and reported “everything works now.” Record successful manual AI use separately from the 257 backend/96 mocked frontend tests and the local-only real HTTP trials above. The agent's configuration check made no provider request and exposed no credentials. No independently inspected real answer, specific trial contents, citation-quality audit, live quota/fault test or current visual/accessibility check is claimed.

Reviewed the uncommitted PDF extraction/storage/migration, research retrieval/provider/API, React library/research integration, test updates and pinned dependencies. The checkpoint includes intended source, tests, migration, lockfile and documentation; local secrets, uploads, dependencies, build output and captures are excluded. Updated stale disabled/deferred AI wording while preserving default-off tracked configuration and historical evidence. Application code is unchanged since the successful 20 October verification, so tests were not repeated solely for documentation changes.

Checkpoint hygiene: `git diff --check` passed; configured-credential scans passed for changed/new files and found no Groq key in tracked/nonignored files or the existing frontend build. An initial broad scan flagged database-password substrings inside unchanged CSS colour literals; inspected these as incidental matches without displaying credentials. Private `.env`, environments, dependencies and build output remain ignored/untracked; no backups or screenshots are included. The index remains unstaged.

Milestones 4/5 remain in progress: detailed PDF/research manual acceptance, current browser accessibility/visual verification, independent live synthetic answer/citation-quality checks and real provider failure behavior retain their recorded gaps. Development remains unmigrated; backup recovery and review of the three historical test schemas remain outstanding. No staging, commit, push, historical ownership assignment or production-readiness claim.

## Later milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| 2 | Minimal React and TypeScript interface for uploading and listing documents | Complete |
| 3 | User accounts and per-user document access | Complete — agreed local scope and user manual trial |
| 4 | PDF extraction with explicit handling of unsupported scanned PDFs | In progress — implementation and verification; user PDF trial pending |
| 5 | Retrieval and document questions with verifiable citations | In progress — local flow tested and manual AI success reported; detailed acceptance gaps remain |
| 6 | Saved conversations and explicit user preferences | Planned |
| 7 | Bounded agent workflows for comparing documents | Planned |
| 8 | Deployment, monitoring, and recovery | Planned |

Define acceptance criteria for each later milestone when it becomes the agreed focus. Any public deployment must follow the access-control milestone.
