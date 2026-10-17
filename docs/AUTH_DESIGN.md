# Milestone 3: authentication and document ownership

Selected design, 17 October 2026. **Milestone 3 is complete for its agreed local scope, with backend/frontend verification and a successful user manual trial.** Milestones 1–2 are complete. The user selected the documented local defaults for this backend task. This milestone stays local-only; email delivery, recovery, PDFs, AI and deployment are outside scope. Policy values below are project decisions, not claims that every value is prescribed by OWASP.

## 1. Fit with the current application

Keep one FastAPI application, synchronous SQLAlchemy/psycopg, PostgreSQL and Alembic. Add a small `app/auth/` module for schemas, password operations, session persistence and routes/guards. Keep document validation and transactional storage in `app/documents/`. No identity service, Redis, routing framework or frontend state library is needed now.

Before this change, `GET /documents` listed every document and `save_document` had no owner. The backend now requires a session and filters by its owner. The React `useLibrary` hook now lives inside a confirmed session generation and unmounts on session boundaries: hiding the library screen alone is not authorization. `/health` stays public and remains liveness-only.

## 2. Recommended approach and dependencies

Use **opaque server-side sessions stored in PostgreSQL, carried in HttpOnly cookies**, with a small application-owned session lifecycle. This uses maintained FastAPI/Starlette request/cookie APIs, existing SQLAlchemy, Python's standard security primitives, and `pwdlib[argon2]` for passwords. It is not a claim that FastAPI supplies a complete account/session system. Our expiry, CSRF, revocation and authorization policy will need explicit tests and review.

| Option | Decision and trade-off |
| --- | --- |
| PostgreSQL session row + opaque cookie | Recommended: immediate revocation, persistence across backend restarts, one existing database. Adds a session lookup and activity update per authenticated request. |
| Starlette `SessionMiddleware` | Its signed client-side session data is readable by the client; it does not provide our database-backed revocation model. Do not treat it as the recommended opaque session store. [Official middleware documentation](https://starlette.dev/middleware/#sessionmiddleware). |
| JWT bearer tokens / refresh tokens | Useful for other clients, but unnecessary token lifecycle complexity for this single browser app. Do not put authentication tokens in localStorage or implement refresh-token rotation here. FastAPI's JWT tutorial is used for its password guidance, not adopted wholesale. [FastAPI security tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/). |
| Full account-management library | Reassess if requirements grow. FastAPI Users currently declares maintenance mode, with security/dependency maintenance but no new features; do not select it assuming active feature development or a drop-in fit for our synchronous access. [Official project notice](https://fastapi-users.github.io/fastapi-users/latest/). |

Selected new runtime dependencies: **`pwdlib[argon2]`** (including its Argon2 implementation) and **`email-validator`**. No JWT or frontend authentication dependency. Use standard `secrets.token_urlsafe(32)` output unchanged as the opaque session value: 32 random bytes, no user claims or custom token serialization/signature. Store only its standard SHA-256 digest for lookup; a fast digest is appropriate for random high-entropy tokens, never for passwords. Use independently generated CSRF values and `secrets.compare_digest` for their comparison. Bound incoming session/CSRF strings to 128 ASCII characters before lookup/comparison; reject malformed values without logging them. [Python 3.14 secrets documentation](https://docs.python.org/3.14/library/secrets.html).

Before implementation, verify maintained releases and Python 3.14/platform compatibility without replacing Python; pin exact resolved dependencies in the backend lock. The original design did not install dependencies; backend implementation installed pwdlib 0.3.1, argon2-cffi 25.1.0 and email-validator 2.3.0 on Python 3.14.7. See verification below. Cookie APIs are provided by [FastAPI response cookies](https://fastapi.tiangolo.com/advanced/response-cookies/) and [Starlette responses](https://starlette.dev/responses/#set-cookie).

## 3. User flows

1. **Open/refresh:** React shows a session-loading screen with no private rows. Fetch CSRF context and current user. A valid session restores the library; missing/expired session shows Log in. A database/network failure shows Retry, not an empty library or a false logged-out result.
2. **Register:** enter email and password; submit JSON after acquiring pre-login CSRF protection. A new valid address creates a user; duplicates do not change the existing password/account. Both produce the same generic acknowledgement, then offer Log in. Registration does not automatically authenticate.
3. **Log in:** verify credentials, revoke the browser's prior session/pre-session, and issue a completely new authenticated session and CSRF value after commit. Show the user's own library; a new account sees an empty library. Unassigned historical documents are not claimed implicitly.
4. **Upload/list:** each direct API request must authenticate. Ownership comes exclusively from the session's user ID. The browser cannot choose an owner. A login screen or hidden controls are additional UX, never the security boundary.
5. **Log out:** immediately hide/clear the local private view and disable document requests, then send protected POST logout. On success the server revokes the session and expires its cookie. On transport/DB failure show “Logout could not be confirmed; retry”; local hiding alone must not be reported as server logout. Keep only the in-memory CSRF value needed to retry, not private records. A page refresh may restore a still-valid session after a failed logout.
6. **Expiry/account switch:** clear all private React state, file selections, confirmations and errors; ask the user to log in. Never silently replay a document upload after reauthentication.

## 4. Credentials and abuse controls

### Passwords

Use Argon2id through the high-level `pwdlib` hashing/verification API, not a custom hash. Selected profile: **64 MiB (`memory_cost=65536` KiB), `time_cost=3`, `parallelism=4`**, with library-managed salts and encoded hashes. Benchmark bounded concurrent hashing on this machine before accepting these settings; do not silently weaken parameters to solve throughput. OWASP's minimum Argon2id configuration is 19 MiB, two iterations, one lane. Rehash on successful login when the chosen library/profile requires it. [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [pwdlib guide](https://frankie567.github.io/pwdlib/guide/), [Argon2 parameter guidance](https://argon2-cffi.readthedocs.io/en/stable/parameters.html).

Selected password policy: 15–128 Unicode code points, at most 512 UTF-8 bytes; spaces allowed, no forced character categories or silent truncation. Never trim, case-fold or normalize a password. Bound JSON credential requests to 8 KiB before parsing; password fields use secret-aware validation. Perform hashing and synchronous DB work in worker threads with bounded hashing concurrency, never on the async event loop.

### Email identity

Use `email-validator`, not a handwritten email regex. Strip surrounding input whitespace, validate with deliverability/DNS checks disabled for this local version, allow internationalized domains via the library's IDNA handling, and initially reject internationalized local parts (`allow_smtputf8=False`). Bound raw input to 320 characters/1024 UTF-8 bytes; the canonical ASCII address must fit 254 bytes. Store the library-normalized display address and a canonical comparison key. [Library normalization documentation](https://github.com/JoshData/python-email-validator).

**Selected product policy:** lowercase the canonical ASCII local part as well as the domain for account lookup/uniqueness. This deliberately treats case variants as one account; SMTP local parts can technically be case-sensitive. Do not remove dots, plus suffixes, or otherwise apply provider-specific aliases. Use the same policy on register and login, backed by a unique database constraint, including concurrent registrations. The user selected this policy before account implementation. [OWASP email guidance](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html).

### Enumeration, throttling and logging

Unknown email and wrong password return the same `401` body. Verify against a precomputed dummy Argon2 hash for unknown users; avoid obvious timing shortcuts, without promising perfect timing indistinguishability. Registration always performs comparable bounded hashing work for syntactically valid new/duplicate requests; handle unique-constraint races without revealing existence. A duplicate registration never overwrites an account. No `409 email exists` response.

Selected initial throttle budgets: login 20 attempts per IP/5 minutes and 5 per canonical email/15 minutes; registration 5 per IP/hour; CSRF bootstrap 60 per IP/minute. Count attempts whether accounts exist or not. Use atomic PostgreSQL fixed-window counters before expensive hashing (small `auth_rate_limits` table, no extra service); return generic `429` with `Retry-After`. Counter keys may contain normalized identifiers and IPs: restrict DB access, never log them, remove expired windows within 24 hours and cap/prune growth. Use the actual peer address locally; do not trust arbitrary forwarded headers. Reject auth operations with sanitized `503` if the limiter/store fails; do not bypass protection. Rate limiting can temporarily block legitimate users behind one IP and can be abused against a known email; these are reviewable local defaults, not production-ready abuse defence. [OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).

Never log request bodies, passwords/hashes, Cookie/Set-Cookie/Authorization headers, session/CSRF values, SQL parameters or uploaded content. Auth validation errors must not use FastAPI's default response fields that echo invalid input (including passwords). Return only fixed error codes/messages and safe request IDs; internal logs use redacted event codes, not raw exceptions or emails. Minimize password lifetime in request memory; clear frontend password state after submission/navigation. Python cannot guarantee erasure of immutable strings or request buffers. Session credentials remain browser-managed cookies; no credentials or CSRF values in URLs, localStorage, sessionStorage, IndexedDB or persisted React caches. CSRF values live only in React memory. [OWASP logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

**Deferred email verification/recovery:** email is an unverified account identifier, not proof of mailbox ownership. No email sending, reset, email-change or “verified” claims. A person can reserve someone else's address, and forgotten passwords have no self-service recovery. This is an explicit local-only exception to OWASP's recommendation to verify ownership before account use. Do not rely on email for trust, sharing or recovery; do not reset a password just because someone claims an address. Add verified ownership and safe recovery before any public rollout. No reset UI until it works.

## 5. Session and cookie policy

Selected authenticated session limits: **8-hour absolute lifetime and 30-minute idle timeout**, checked against server UTC time on every request. Each successful authenticated request updates activity; no background keepalive. Browser refresh/backend restart preserves a still-valid stored session, but never extends its absolute deadline. Anonymous pre-sessions last 10 minutes. Clean expired/revoked rows with a bounded local maintenance command; cleanup is not what enforces expiry. Multiple browsers may have separate sessions; logout revokes the current browser session only.

On login, discard the previous pre-session/authenticated token and CSRF value, then create fresh independent values in one transaction. Set the new cookie only after commit; rollback must leave no half-authenticated state. Invalid/expired/revoked sessions fail closed. A raw token must never be returned in JSON. Server-side deletion/revocation makes a copied old cookie unusable; simply clearing a browser cookie is insufficient. [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

| Attribute | Selected local HTTP policy | Future HTTPS requirement (not deployment work) |
| --- | --- | --- |
| Name | `dra_session` | `__Host-dra_session` |
| HttpOnly | `true` | `true` |
| SameSite | `Lax` | `Lax` for a same-origin application |
| Secure | `false`, permitted only in explicit development/test mode on loopback HTTP | `true`; never silently downgrade |
| Path / Domain | `/`, omit Domain (host-only) | `/`, omit Domain (required by `__Host-`) |
| Expiry | Max-Age bounded by remaining server lifetime (600 seconds for pre-session, at most 8 hours authenticated) | Same bound; server timeout remains authoritative |

Expire/delete with the same name/path/domain attributes. Never use `SameSite=None` here. HttpOnly reduces JavaScript token theft; it does not stop injected scripts making requests. SameSite is defence in depth, not the CSRF mechanism. Cookies are not isolated by port: 127.0.0.1:5173 and :8000 share a cookie host, and other local apps on that host are not a security boundary. Use one hostname consistently; `localhost` is not interchangeable with `127.0.0.1`. [Browser cookie semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).

## 6. CSRF and request boundary

Use OWASP's **synchronizer-token pattern**, backed by the pre-session/authenticated session row. `GET /auth/csrf` supplies a random session-bound CSRF value in JSON and creates a short anonymous pre-session only when needed. It does not authenticate. Preserve the existing token within a session so two tabs do not invalidate each other on bootstrap; rotate on successful login. A repeated value without its matching session cookie is not sufficient.

Require `X-CSRF-Token` and an exact allowed `Origin` on every state-changing browser endpoint: registration, login, logout and document upload. Login CSRF matters even before authentication; never promote the pre-session into the authenticated session. Accept only JSON for login/register and multipart for document upload. Never accept a token in query parameters. Compare through the standard constant-time helper. All failures use generic `403` before side effects. [OWASP CSRF guidance, including pre-login sessions](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Selected local Origin allowlist: `http://127.0.0.1:5173` for React and `http://127.0.0.1:8000` for explicit API-doc/testing use. Reject `Origin: null`, missing Origin on POST, and other schemes/hosts/ports; no credentialed wildcard CORS. Direct non-browser tests/clients must provide the documented Origin and CSRF header too. For CSRF bootstrap, reject cross-site Fetch Metadata and any supplied disallowed Origin; without either header require an explicit allowed Origin from non-browser clients. Return auth/CSRF/document responses with `Cache-Control: no-store` and no shared-cache validators. No state-changing GET, except creation of an anonymous CSRF context; a cross-site page cannot read it through CORS/SOP and is rejected at the bootstrap boundary.

Auth guards must run **before the upload form parser**: return `401` for unauthenticated document requests, then check CSRF for authenticated POSTs. Existing FastAPI `File` parsing may precede ordinary dependencies; do not assume a new sync dependency alone prevents unauthenticated multipart buffering. Implement the header/session guard at an earlier request boundary, running DB lookups in a worker when invoked from async ASGI code. Continue bounded file validation afterward. This is still not a transport-level HTTP body limit.

Perform password hashing and bounded file validation before acquiring transaction locks; keep locked transactions limited to session revalidation and DB writes, with no external calls. A protected write revalidates/locks the session row in its database transaction before insertion, deriving owner from that row. Logout locks/revokes the same row, so a write either commits before logout or is rejected after revocation. A list request already in progress can still return an earlier snapshot; client session boundaries must discard it.

## 7. Data model and migration plan

Implemented by `0002_auth` (verified only in isolated test schemas; not applied to development):

| Table/change | Columns, constraints and indexes |
| --- | --- |
| `users` | UUID PK, normalized display email, ASCII `email_key` with deterministic C collation and unique constraint, encoded `password_hash`, UTC `created_at`, nullable `email_verified_at` (always null this milestone). Nonempty fields and canonical key byte-length/lowercase checks. No user deletion endpoint; ownership FK uses `ON DELETE RESTRICT`. |
| `auth_sessions` | Unique fixed-length binary SHA-256 `token_digest`, nullable FK `user_id` (null only for pre-session), independently random `csrf_token`, public UUID `session_context` (not a credential), UTC `created_at`, `last_seen_at`, `expires_at`, nullable `revoked_at`. Checks for valid date ordering and token lengths; indexes on user ID and expiry. Session context changes on every login. |
| `documents.owner_id` | Nullable UUID FK to `users.id`, **no default**. Composite B-tree `(owner_id, created_at, id)` supports per-user filtering in existing order. Existing content/metadata/validation constraints stay intact. |
| `auth_rate_limits` | Unique `(scope, key, window_start)`, nonnegative attempt count, UTC expiry indexed for cleanup. Short-lived operational data, never password or bearer-token storage. |

PostgreSQL unique/FK constraints protect concurrent identity creation and references; FKs do not create every referencing-column index automatically. Authorization still requires explicit predicates. No RLS migration in this initial design; a forgotten filter remains a real application risk and must be covered by direct API isolation tests. [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html).

### Existing ownerless documents: preserve and quarantine logically

Recommend leaving existing rows unchanged with `owner_id = NULL`, retaining IDs, exact text, byte sizes and timestamps. Once the authenticated application is enabled, those rows are excluded by `WHERE owner_id = current_user.id` for every account. They remain recoverable by the local operator, not accessible through an “unclaimed documents” API. Never assign them to the first registrant, a shared account, a guessed email, or a database role.

After review, an optional one-off operator action may assign **explicit document UUIDs to an explicit existing user UUID**, with dry-run counts, confirmation of provenance, a backup, a transaction and an audit of IDs/counts only. It must refuse missing targets or already-owned documents and must not print content. No bulk implicit assignment or database reset. This assignment is not authorized by the design document.

Nullable ownership is a deliberate transitional exception for historical rows. Every new application insert requires an authenticated non-null owner; tests enforce it. A later `NOT NULL` migration is blocked until all historical rows have explicitly reviewed owners or an approved archival destination. Do not delete data just to make that constraint pass.

### Ordering and rollback limitations

1. In a maintenance window, stop the old backend (its unfiltered list would expose all rows) and take a private recoverable backup. Verify the existing database/role/project guard and `0001_documents` state. No development migration is authorized in this backend task.
2. New Alembic revision(s): create users/sessions/rate counters, add the nullable owner FK/index, preserve legacy rows as null. Test upgrade from a populated `0001_documents` database and schema validation. Do not rewrite the original migration or use model `create_all` at startup.
3. Enable the ownership-filtered API and session-aware frontend together; update fixture/trial-schema setup to include all new tables and FKs. Tests and the trial launcher now run actual migrations in private schemas rather than cloning only the old document table. Do not restart the old unauthenticated application against mixed-owner data.
4. Any reviewed legacy assignment is a separate operator operation after accounts exist. Tightening nullability can be a later revision.

Transactional PostgreSQL DDL rolls back a failed revision; separately committed revisions/operator assignments need their own recovery plan. Dropping users/session tables or `owner_id` after real use destroys credentials/ownership/revocation evidence. Do not offer a blind destructive downgrade. Prefer a forward fix; restore a consistent backup/application version only in a reviewed maintenance window, acknowledging loss of later writes. Never reset `dra_dev`, `dra_test`, roles or unrelated projects. Expired sessions are not revived by a rollback.

## 8. Proposed API contract

All paths retain the current direct naming; extend Vite's proxy with `/auth` alongside `/documents`, with no rewriting and no frontend dotenv loading. Browser requests explicitly use same-origin credentials; do not return a cookie value to JavaScript. Reject unknown auth JSON fields; redact all validation responses. All shapes below are proposals.

Shared user shape: `{"id":"<UUID>","email":"<normalized display address>"}`.
Authenticated context shape: `{"user":<user>,"expires_at":"<UTC ISO-8601>","session_context":"<public UUID>"}`. Context is only a client correlation label, never accepted as authentication or ownership proof. Authenticated document responses also carry `X-Session-Context` for stale-session detection without changing their JSON metadata.

| Endpoint | Input / preconditions | Response |
| --- | --- | --- |
| `GET /auth/csrf` | Same-origin bootstrap checks above; optional existing cookie. Reuse valid session; replace invalid cookie with anonymous pre-session. | `200 {"csrf_token":"<opaque CSRF value>"}` plus cookie when creating context; `429`/`503` on limiter/store failure. |
| `POST /auth/register` | JSON `{"email":"…","password":"…"}`, anonymous pre-session + Origin + CSRF. Already authenticated callers receive fixed `400` asking them to log out first. | `202 {"message":"Registration request processed. Try signing in with your credentials."}` for new or duplicate valid accounts; no user/token/automatic login. `422` safe field-validation message, `403` CSRF, `415` media type, `413` body limit, `429`, `503`. |
| `POST /auth/login` | Same JSON, valid anonymous or authenticated context + Origin + CSRF. Verify credentials before replacing a current authenticated session; failed credentials do not silently switch it. | `200` authenticated context plus fresh `csrf_token` and Set-Cookie after commit. `401 {"error":"invalid_credentials","message":"Email or password is incorrect."}` for unknown user/wrong password; `422`, `403`, `415`, `413`, `429`, `503` as applicable. |
| `POST /auth/logout` | No body; Origin + CSRF. With a valid authenticated/pre-session cookie, revoke it and delete cookie. | `204` no body. Already missing/expired/revoked cookies: Origin still required, expire cookie and return idempotent `204` without an identifiable active session to revoke. Valid-session CSRF failure: `403`; DB unavailability: `503`, never false confirmed logout. |
| `GET /auth/me` | Cookie authentication; no CSRF needed for this read. | `200` authenticated context; otherwise `401 {"error":"unauthenticated","message":"Please log in."}`; sanitized `503` when identity cannot be checked. Anonymous pre-session is not authentication. |
| `GET /documents` | Authenticated identity required. | Existing `200` metadata-only array/`[]`, ordered by creation timestamp then UUID, filtered in SQL by owner. `401` for missing/invalid/expired/revoked session; existing sanitized `503`. |
| `POST /documents` | Cookie + Origin + CSRF, multipart **only** `file`. Owner is read from the validated session inside the transaction. | Existing `201 {"id","original_filename","byte_size","created_at"}` after commit, no content or owner field. Existing upload `400`/`413`/`422`, plus `401`/`403` and sanitized `503`. Reject extra owner/user fields (form/query) with fixed `400`; do not echo or trust them. |

No new document-reading, delete, profile-edit, recovery or administrative assignment endpoint. Missing/invalid sessions are uniformly unauthenticated; expired `401` is not a reason to retry POST. A document/upload `503` or lost response remains potentially ambiguous to the browser. CSRF `403` allows refreshing auth context and a **manual** retry only, never automatic POST replay. Logout's invalid-session no-op exception does not authorize any other state-changing operation.

## 9. Frontend design and session boundaries

Preserve the approved paper/teal palette, serif heading, sans-serif fields, spacing, responsive rows and native Details. Use small Log in/Register forms in the same page shell; no sidebar or chat UI. Label Email/Password; use `autocomplete="email"`, `current-password` for login and `new-password` for registration, visible focus and live errors. Provide a concise local-only notice that email verification and password recovery are unavailable. Registration acknowledgement offers login without revealing duplicate addresses.

Add a small auth provider/hook with explicit states: checking, anonymous, authenticated, unavailable, and logout-pending. Load `/auth/csrf`, then `/auth/me`; never flash an old library during checking. Only mount a library for a known authenticated context, keyed by `session_context`, not just user ID. Keep the user's normalized email and Logout control in the existing header.

Every login/logout/account transition increments a client generation, aborts outstanding requests where possible, and clears **documents, the confirmed-ID map, selected File/input value, open detail state, success/error messages and CSRF memory** (retain CSRF only for a failed-logout retry). Each async completion checks both captured generation and session context before updating UI. On ordinary document responses, require the server's `X-Session-Context` to match; discard mismatches and recheck identity. Aborting alone is insufficient: a response may already be resolving. Update API errors so `401` and `403` are not both flattened into today's generic upload uncertainty.

Serialize auth mutations within a tab. Broadcast only non-secret “auth changed” events across tabs (e.g. BroadcastChannel); other tabs immediately hide/clear and revalidate. Revalidate `/auth/me` on window focus before restoring private UI. An in-flight response from user A must not populate user B's new library, even when A's upload committed. Browser cookie changes from another tab/direct login are handled by response context checks, not trusted client user IDs. Logout cannot erase a screen already observed, nor revoke a transaction that committed before it; it must stop subsequent access and clear in-app state.

## 10. Verification requirements

Use synthetic accounts/documents and only the guarded `dra_test` database, with unique isolated schemas containing all auth/document tables. No test writes to development and no clearing unrelated records. Inspect cookies/headers without logging their values.

| Area | Required evidence |
| --- | --- |
| Registration | New user created with Argon2id hash, not plaintext; canonical email cases/IDN/limits/aliases; duplicate and concurrent duplicate requests give identical public `202` shapes and one account; duplicate registration cannot replace password; no automatic session. Safe validation never reflects password. |
| Login | Correct credentials create cookie/session; wrong password/unknown email share status/body and dummy-hash work; profile parameters/rehash tested; oversized inputs bounded; limiter applies identically to known/unknown accounts and atomic counters work across concurrent requests/restarts. |
| Session lifecycle | Missing, malformed, expired (idle and absolute), unknown and revoked cookies all return `401` for protected reads/writes. Inject time; cookie lifetime does not override server expiry. Backend restart preserves valid sessions. DB failure returns sanitized `503`, not anonymous success. |
| Rotation/logout | Old pre-session, old authenticated session and old CSRF fail after successful login; context changes even for the same user. Logout revokes replayed cookies, expires matching cookie attributes, is idempotent, and respects concurrent-write ordering. A failed transaction cannot set a success cookie or revoke only half the transition. |
| CSRF | Missing/wrong/token-from-other-session, forged/missing/null Origin and cross-site bootstrap rejected without effects; cover login/register/logout and multipart upload. SameSite alone must not pass tests. Valid same-origin requests succeed; OPTIONS/read endpoints cannot mutate identity/documents. |
| Two-user isolation | Through direct HTTP requests, A and B upload different and duplicate filenames; each list contains only its own IDs/counts, never the other's metadata or content. Query assertions prove ownership predicates and metadata-only projection. Anonymous sessions cannot upload/list. |
| Forged ownership | Cookie of A plus B's ID in `owner_id`/`user_id` form, query or JSON cannot create a B-owned row; extra fields rejected, all existing records unchanged. Public session context is not a bearer credential. |
| Migration | Populated `0001_documents` upgrade preserves exact IDs/text/bytes/timestamps; legacy rows remain null/invisible to both accounts; first registration claims nothing; invalid FK blocked. Test failed revision rollback, repeated operator-plan validation, and refusal of unsafe destructive downgrade. Never run assignment automatically. |
| Frontend | Session-loading/unavailable versus anonymous; private state cleared on logout, expiry, failed logout hiding, account switch and cross-tab notice. Deferred A list/upload/login responses cannot enter B state; same-user new-session remount clears confirmed IDs. Test response context mismatches, stale `401`, CSRF refresh/manual retry, and no automatic POST after login. |
| Browser/manual | Real cookie acceptance through Vite proxy, same-origin CSRF header, refresh restoration, login/register/logout, two-user switching, keyboard/focus/mobile layouts, logout replay via direct API, and no credentials in storage/logs. HTTPS Secure/__Host behaviour needs a future HTTPS test; local HTTP cannot prove it. |

Completion requires these automated results plus a recorded manual trial; this design and the earlier milestone's tests do not establish that authentication works.

## 11. Selected defaults and implementation corrections

The user selected the composed PostgreSQL session approach, generic `202` registration with explicit login, case-insensitive ASCII email identity, the password/session/throttle values above, and preservation of inaccessible ownerless documents. No reassignment, deletion, verification or recovery is authorized.

Implementation details and corrections:

- `AuthBoundary` is a pure ASGI middleware, before FastAPI body parsing. Header-only authorization runs in a worker. It does not refresh activity before a CSRF rejection. Document services revalidate under a row lock and update activity inside their own transactions. Login hashes outside that lock, then rechecks/rotates atomically; logout uses the same lock. Queueing cannot bypass expiry: the clock is read after lock acquisition.
- Credential JSON is read to an 8 KiB accumulator regardless of Content-Length. Invalid JSON, Unicode, types and fields return fixed errors. Auth code does not log exceptions or SQL parameters. Passwords are transient `SecretStr` inputs; Python cannot guarantee erasure of strings or request buffers from memory.
- Argon2id hashing/verification has a two-operation **per-process** semaphore; a worker may wait for a slot. The dummy hash is warmed during lifespan startup. This is not a total process-memory bound or a public abuse defence.
- The PostgreSQL UPSERT and row-lock APIs were checked against the installed SQLAlchemy 2.0 line’s [official PostgreSQL documentation](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert) and [locking reference](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.GenerativeSelect.with_for_update).
- Limiter UPSERTs are atomic, saturating at budget + 1; rejected attempts are committed. IP accounting occurs before credential parsing/hashing; canonical-email accounting follows cheap validation. The actual ASGI peer is used, with no forwarded-header middleware. Run Uvicorn with `--no-proxy-headers` as documented.
- Cleanup removes at most 1,000 rows per table per invocation, using expiry predicates and `FOR UPDATE SKIP LOCKED`. Expired counters are eligible immediately, rather than retained for a further day. Run bounded batches at least daily, repeating deliberately for a backlog; counters have no hard global row cap. Cleanup never deletes users or documents and is not needed to enforce session expiry.
- Local settings only support development/test; cookies are host-only `dra_session`, HttpOnly, SameSite=Lax, Secure=false. Production settings/cookies are requirements for future work, not implemented options. Use loopback HTTP only.
- Public response `X-Session-Context` identifies a session generation; it cannot authenticate. `me`/login also return it in JSON. Auth/document responses, including errors, use `Cache-Control: no-store`.
- Only `file` is accepted in multipart uploads; extra form/query fields return fixed `400`. Missing/wrongly typed files, including JSON pretending to be an upload, return sanitized `422`; the normal missing-file location/status remains. No content or ownership is added to metadata responses.
- Migration tests use actual Alembic revisions in unique `dra_test` schemas, not clones of `public` tables. No development migration or public test-schema migration is performed. `0002_auth` downgrade always refuses; restoring a consistent backup or a forward fix needs operator review.

Frontend/session-bound UI, the updated Vite proxy/trial launcher and real browser cookie/account isolation checks are now implemented and agent-verified; see README and PLAN for the 60 mocked frontend tests and separate browser evidence. The user subsequently confirmed login/upload, session restoration, logout and two-user isolation. Development migration, backup recovery drill and future HTTPS behaviour remain pending.

## 12. Backend verification record

Executed on 17 October 2026:

- Python 3.14.7 installation and editable project metadata update passed; `pip check` passed. Exact new dependencies are pinned in `backend/requirements.lock`. Application/scripts/migrations compile successfully.
- Final command: `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests --database -W error::DeprecationWarning -q`: **154 passed, 0 failed, 0 skipped, 0 warnings** (74.08 seconds). HTTP requests use HTTPX ASGI transport against the real app and PostgreSQL; these are not mocked persistence tests, TCP/browser tests, or a user manual trial.
- Live schema/model comparison including defaults and named check constraints passed in migrated isolated schemas. Actual `alembic check` passed with no upgrade operations. Offline migration SQL generation also passed; it does not establish development migration readiness by itself.
- Real tests cover exact legacy migration preservation/null ownership, FK enforcement, injected DDL failure/rollback/resume, unsafe downgrade refusal, concurrent duplicate registration, password preservation/canonical email/IDN/limits, hash profile upgrades and dummy verification, session expiry/rotation/revocation/restore through a fresh app/connection, Origin/CSRF failures, HTTP throttle budgets, atomic concurrent counters, sanitized store/commit failures, forged ownership and two-user metadata isolation.
- Existing document tests now use persisted authenticated sessions. Upload/list validation, bounded byte reads, exact text, metadata-only SQL/owner predicates, ordering, rollback observed through another connection and committed-document persistence still pass. Separate tests prohibit both parser invocation and ASGI body receipt for unauthorized uploads.
- Controlled-time transaction tests prove write-before-logout commits first, logout-before-write rejects the write, expiry is checked after acquiring a queued lock, and cleanup skips a row whose concurrent activity update keeps it valid. Cleanup deletes bounded expired/revoked records only; all test data is in generated `dra_test` schemas.
- Final synthetic benchmark, with the suite stopped: two concurrent operations, eight hash/verify pairs; median hash **0.258 s**, verify **0.276 s**, total **2.184 s**, process peak RSS **328.0 MiB**. Profile remains Argon2id m=65536 KiB/t=3/p=4. This is one machine measurement, not a public-service capacity guarantee or a total memory cap.
- Read-only development identity check passed; `dra_dev` remains `0001_documents` with no `auth_sessions` table. No development migration, operational cleanup, role/configuration change or reset was performed.
- `git diff --check` passed. Changed/new project files contain no configured credential-value matches; private configuration and generated dependencies remain ignored. Frontend is unchanged; nothing staged/committed/pushed.

Earlier runs found two existing tests coupled to the old transaction/schema arrangement, and one malformed-Unicode test that HTTPX rejected before sending. These tests were corrected. Starlette’s deprecated HTTPX TestClient adapter produced a warning; tests now use the already-installed HTTPX ASGI transport directly. Final verification above has no failures, warnings or skips.

Subsequent frontend work verified session cache boundaries in 60 mocked tests and real cookie/proxy/account switching in an agent-operated browser trial (see README/PLAN). The user’s core manual trial is now confirmed. Real browser fault injection, screen-reader/zoom and long-duration expiry checks, future HTTPS cookies and a private restore drill remain pending. Development migration has deliberately not been attempted; the earlier milestone 2 manual trial does not verify authentication.


Frontend focus correction (17 October 2026): the user’s manual trial found that native picker focus could clear the selected file. Unlike logout/account changes, an ordinary focus check now retains the existing library/input while hiding it until `/auth/me` confirms the same user and session context. A changed/expired/unavailable identity clears the cached view; superseded checks cannot restore it. This replaces the original conservative reset on every focus. Six regression cases and the 60-test frontend suite passed, with an isolated real upload/list/reload trial; the user subsequently confirmed the retry works.


Completion record — 17 October 2026: the user confirmed login, the corrected upload flow, restoration after refresh, logout and per-account document isolation. This completes the local milestone with the separately recorded automated/agent-browser evidence. It does not authorize development migration, ownership assignment or public deployment, and does not expand the manual report into registration/accessibility/fault-injection checks. Only documentation changed for this status update; tests were not rerun.
