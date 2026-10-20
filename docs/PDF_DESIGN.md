# Milestone 4: selectable-text PDF support

Selected design and implementation record, 17 October 2026 — **implementation in progress; manual trial pending**. The user authorized implementation after approving the mixed-page policy. Remaining defaults were adopted as stated before editing. Keep one local FastAPI application, synchronous persistence, and the approved React library. No OCR, PDF viewer, document-reading endpoint, retrieval, or AI in this milestone.

## Current contract and evidence

Repository inspection started with a clean `main`, synchronized with `origin/main`. Milestones 1–3 have recorded automated, agent-browser, and user trial evidence in [PLAN.md](PLAN.md). That evidence does not verify PDF support. Development remains documented at `0001_documents`, without authentication migration; no database inspection or migration was performed for this design.

- Authenticated `POST /documents` accepts exactly one multipart `file`; Origin/session-bound CSRF checks run before parsing. Storage revalidates the locked session inside its transaction and derives ownership from it. Legacy ownerless rows remain inaccessible.
- TXT uploads are case-insensitive, strict UTF-8, nonblank, NUL-free, and at most 1,048,576 bytes. Reads stop at limit + 1. Accepted text, including whitespace and line endings, is preserved exactly.
- The schema currently requires `.txt`, nonblank content, and equality between UTF-8 content bytes and original file bytes. PDF extraction cannot satisfy that equality: source bytes and extracted text are different representations.
- Upload/list return only `id`, `original_filename`, `byte_size`, `created_at`. Lists select metadata columns and filter by owner, ordered by timestamp then ID. The frontend currently rejects non-TXT metadata as well as non-TXT selections.
- Multipart parsing can buffer/spool data before the file validator. There is currently no total request-body cap. The frontend timeout is 20 seconds; aborting a request cannot undo a committed upload.

## 1. Extraction approach

Start with maintained **pypdf**, using `PdfReader` and per-page `extract_text()` in plain mode. Its pure-Python approach fits the existing backend without an external extraction service. Check the selected release's Python 3.14 compatibility, advisories and dependency resolution before installation; pin the tested version in the existing lockfile. Implementation pins pypdf 6.21.1; dependency compatibility and verification are recorded below. Reject encrypted inputs, so no crypto extra is needed for decryption. The implementation subclasses the pinned reader at its `_handle_encryption` hook to reject before the constructor attempts an empty password; a regression test forbids password verification. This private hook must be reviewed on pypdf upgrades.

PDF stores positioned drawing/text instructions rather than reliable paragraphs. Selectable text is a useful indication, not a guarantee of accurate reading order. Columns, tables, mathematical notation, ligatures and existing OCR layers can produce imperfect output. Do not claim faithful layout, table recognition, or extraction-quality scoring. See the official [extraction guide](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) and [installation guide](https://pypdf.readthedocs.io/en/stable/user/installation.html).

Use explicit `strict=True` initially: reject structural problems rather than silently attempting repairs. This deliberately rejects some PDFs a desktop reader can open. Do not silently switch to permissive parsing or another extractor; a later supported profile needs its own version and tests. See [pypdf strictness](https://pypdf.readthedocs.io/en/stable/user/robustness.html). Alternatives with layout/coordinate capabilities can be evaluated if synthetic representative documents demonstrate a concrete failure; do not add multiple extractors now.

## 2. Content policy

| Input | Proposed result |
| --- | --- |
| Digitally generated PDF with usable text | Extract every page, validate, then save atomically. Images/figures are not interpreted. |
| Image-only/scanned PDF with no usable text | `400`: no extractable text; scanned files without a text layer need OCR, which this version does not support. Do not diagnose scanning conclusively from empty extraction alone. |
| Mixed text-bearing and textless pages | Accept if at least one page has non-whitespace text; preserve all physical page positions and report textless page numbers. Warn that some content was not extracted. Do not silently omit those pages from provenance. |
| Text plus images on the same page | Accept its text layer, with a general PDF notice that images are not read. Text presence cannot establish complete coverage of the page. |
| Existing OCR text layer | Accept extractable text; do not claim to detect or correct OCR errors. |
| Encrypted PDF, including one opening with an empty password | Reject `400` whenever `reader.is_encrypted` is true, before extracting pages. No password prompt, decryption, or permissions bypass. See [reader API](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html). |
| Malformed/truncated PDF, failed page extraction, unsupported feature | Reject the whole upload with fixed `400`; never save a partially extracted document. Strict parsing is not a complete PDF conformance validator. |
| Zero pages, zero bytes, all blank/whitespace output | Reject `400`. Blank pages cannot reliably be distinguished from scanned/unextractable pages. |
| Extracted NUL or invalid Unicode for PostgreSQL UTF-8 | Reject `400`; do not silently remove or replace characters. |
| Resource limit exceeded | Fixed `413`, no document row. Unexpected worker/store failure returns sanitized `503`, never raw parser output. |

TXT validation and exact preservation remain unchanged. Preserve accepted PDF extractor output without trimming, whitespace normalization, dehyphenation or header removal; use whitespace checks only to classify content. A later search representation may normalize separately, with a mapping back to the saved extraction. Treat text, page labels, filenames and all PDF objects as untrusted data. Never execute scripts, open URLs, follow attachments or extract embedded files.

## 3. Bounded processing — selected local limits

These are conservative local limits, not production capacity guarantees. Keep the existing 1 MiB file limit for both formats initially; many real papers will exceed it. Measure representative synthetic inputs before proposing a higher PDF limit.

| Resource | Proposed limit / enforcement |
| --- | --- |
| Original file | 1,048,576 bytes; bounded 64 KiB reads, stop after overflow sentinel, independent of client size/MIME. |
| Total multipart body | 2,097,152 bytes including boundaries/fields; count actual ASGI bytes before they reach the parser, after the existing auth/CSRF boundary. Reject an oversized declaration early and enforce streaming count even if omitted/false. Return `413` before storage; clean parser temporary resources. This bounds body bytes delivered to parsing, not proxy/OS buffers or upload duration. |
| PDF pages | 100 physical pages, reject overflow before text extraction where possible; page-tree parsing itself still needs worker limits. |
| Extracted text | 256 KiB UTF-8 per page; 2 MiB for aggregate `content`, including separators. Check incrementally between pages; a single extraction may allocate before checking. |
| Child runtime | 5 CPU seconds and 10 seconds parent-measured wall time from spawn; terminate, kill if needed, and reap on timeout/cancellation. |
| Child memory | 512 MiB address-space ceiling using Linux `RLIMIT_AS`, set before parsing; not an RSS limit or a whole-application memory bound. Disable core dumps. Verify limits on this Fedora/Python setup and fail closed if unavailable. |
| Concurrency / IPC | One extraction child per backend process; reject a busy slot with `429` and `Retry-After`, without an unbounded queue. Bound worker output to 4 MiB of UTF-8 structured data; validate it in the parent. |

pypdf warns that compressed streams can expand greatly during extraction. Checking `len(page.get_contents().get_data())` already decompresses the stream, so that is not a safe pre-allocation memory guard. Put all parsing, page counting and extraction inside the constrained child. The process is justified by hostile-input resource isolation, not a background job system. A thread timeout does not stop a running parser. [pypdf memory warning](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

Launch a fresh minimal extraction entry point, without a shell, database connections, credential environment variables or application/config imports. Pass bounded bytes through controlled IPC; never use a user filename as a path or command. Suppress parser warning/exception output; return only allowlisted error codes. Keep temporary data private, unnamed where practical, and close/remove it in every exit path. Do not log document content, parser exceptions or worker stderr.

Use a parent watchdog plus platform resource limits; `subprocess` timeouts require explicit child cleanup when using `Popen`. Validate cancellation, child death and permit release. This is resource containment, **not** a security sandbox, malware scanner, network/filesystem permission boundary, or public deployment defence. See Python's [resource limits](https://docs.python.org/3.14/library/resource.html) and [subprocess lifecycle](https://docs.python.org/3.14/library/subprocess.html).

The body cap does not solve slow uploads or unlimited concurrent multipart parsing. Keep loopback-only; connection/time/rate limits and public upload scanning need separate deployment work. OWASP recommends layered type/signature/size controls; extension, MIME and a `%PDF-` header are not individually proof of a safe PDF. Require `.pdf` case-insensitively, a header at byte zero for this conservative profile, and successful strict parsing; ignore MIME as an authority. [OWASP upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

## 4. Storage and provenance

**Provenance means retaining where a passage came from.** A flat text string loses page boundaries; physical page numbers must survive even when a page has no text. An extractor upgrade may change text, so future citation offsets must identify the saved extraction version, not a newly generated string.

Use the new `0003_pdf_documents` migration after `0002_auth`; never edit applied migrations:

- Add `source_format` (`txt`/`pdf`, historical rows backfilled as `txt`), nullable `source_pdf` (`BYTEA`), `page_count`, and extraction-profile/version fields. Retain the original PDF bytes in PostgreSQL, limited to 1 MiB, for later human/source verification. No download route now. This increases private storage and backup size; it avoids a new filesystem/object-store lifecycle and commits source with extraction atomically.
- Keep `content` for compatibility with existing TXT storage/future retrieval. For PDF only, define it as page text joined with `\n\f\n`, preserving empty pages and extracted text exactly. Page rows, not separator searching, define provenance. Bound this aggregate to 2 MiB.
- Add `document_pages`: `(document_id, page_number)` primary key, document FK, 1-based physical `page_number`, and non-null extracted `text` (empty allowed). Store one row per PDF page. A stored generated `has_text` boolean derives from that text using the same Unicode whitespace set as TXT validation. It supports metadata-only queries and is not a claim about visual contents. Do not invent printed page labels, coordinates or OCR confidence. Future citations can use `(document_id, extraction_version, physical_page, start, end)` with offsets defined as Unicode code points into the saved page text; future JavaScript must account for UTF-16 indexing.
- Replace the TXT-only extension constraint with format/extension consistency. Keep the original size limit; retain UTF-8-byte equality **only for TXT**. PDF must have `octet_length(source_pdf) = original_byte_size`, nonblank aggregate text and valid page count/profile; TXT has no PDF bytes/profile/page count. Add page number and page text-size checks and the aggregate limit. Existing nonblank/filename/ownership rules still apply.
- Enforce complete contiguous page sets and aggregate equality in the atomic storage service, with integration tests; ordinary SQL CHECK constraints cannot verify child-table aggregates. Do not claim these are database-enforced cross-row invariants. The document FK/index supports page lookup; all future reads must join through the centralized ownership predicate. Parent ownership remains authoritative; do not duplicate it on page rows.

Store an immutable extraction version such as `pypdf:<tested-version>:plain-v1`; re-extraction is a separate future versioned operation. No automatic deduplication or overwrite: duplicate names remain distinct IDs. Do not turn a file digest into account-wide or cross-account existence disclosure.

Migration tests must preserve exact existing TXT IDs, owners (including NULL), bytes, text and timestamps. No historical assignment, deletion or re-extraction. Test only migrated isolated schemas in guarded `dra_test`. Development is still at `0001_documents`; any eventual development upgrade would include auth **and** PDF changes, after explicit authorization and a verified backup/recovery procedure. A restore drill remains outstanding. Refuse a destructive downgrade once PDF data exists; prefer a forward fix. Local milestone completion is not production readiness.

## 5. Request flow and API/UI changes

1. Existing header/session/Origin/CSRF authorization runs before multipart parsing. Enforce the new body cap, parse exactly one `file`, validate metadata and bounded file bytes.
2. TXT uses the existing validator. PDF goes through the bounded worker. No database transaction/session lock is held while extracting.
3. Validate the worker's structured output in the parent. In one database transaction, revalidate/lock the original session and CSRF, derive ownership, insert source/document/all pages, and commit. Logout/expiry during extraction prevents storage; a concurrent write/logout follows existing lock ordering.
4. Return `201` only after commit. Every error closes uploads/IPC/temporary resources and releases the worker slot. Failed writes roll back source, aggregate and pages together. A lost success response remains uncertain: never automatically retry.

Retain current metadata fields and meanings: `byte_size` remains **original uploaded bytes**, never extracted-text size. Add these metadata-only fields to both upload/list responses:

| Field | TXT | PDF |
| --- | --- | --- |
| `source_format` | `txt` | `pdf` |
| `page_count` | `null` | physical page count |
| `textless_pages` | `[]` | ordered physical page numbers without usable text |

Select page-status metadata without fetching page/document text or original PDF bytes during listing (e.g. a grouped metadata projection). Keep timestamp/UUID ordering, owner filtering, no-store, session-context headers, and existing `400`/`401`/`403`/`413`/`422`/`429`/`503` semantics. Extra ownership fields remain forbidden.

For clear PDF errors, propose allowlisted `error` codes plus fixed `detail` text, preserving existing TXT error shapes. Codes include `pdf_encrypted`, `pdf_no_text`, `pdf_invalid`, and `pdf_limit_exceeded`; display no raw parser messages/page text/filenames. Non-201 server/network failures still follow the existing conservative uncertain-save path unless a specific rejection contract proves no write.

Update frontend runtime metadata validation alongside backend support; it currently rejects PDFs. Preserve the visual design, native picker focus fix, explicit submission and all session-generation guards. Show “UTF-8 TXT or text-based PDF · maximum 1 MiB”; client checks extension/size/zero bytes, never claims to validate PDF text. During extraction show “Processing and saving…” rather than fake progress. Retain 20-second client timeout initially and test it against the bounded extraction time; timeout still cannot prove rejection. Display format/page count and textless-page warnings in Details, with an upload acknowledgement that clearly states incomplete extraction. Show a general PDF notice about images and extraction accuracy. No reader/open button, OCR action or fake citation UI.

## 6. Small implementation increments and acceptance evidence

Each increment needs explanation, reviewable changes, meaningful tests and recorded results before proceeding. The user has now authorized implementation; milestones still require evidence before completion.

1. **Extraction spike:** select/pin a compatible pypdf release; exercise plain/columns/rotated text and measure the worker limits on generated synthetic documents. Prove watchdog termination, memory failure, bounded IPC, slot/cancellation cleanup and quiet logs. Revise proposed budgets based on evidence before claiming them usable.
2. **Migration/storage:** isolated upgrade from populated old schemas, exact TXT/legacy-owner preservation, PDF/source/page invariants, metadata-only projections, transactional failures observed from another connection, fresh-connection persistence and model/migration consistency. No development migration.
3. **Protected API:** valid PDF and uppercase extension, multibyte extraction, exact original byte counts, duplicate names, all size/page/output boundaries, forged MIME/header/extension, encryption (including empty password), truncation, malformed page, empty/image-only, mixed and pre-OCRed samples. Verify unauthorized/CSRF rejection before body parsing and owner isolation; logout/expiry while extracting must prevent a later write.
4. **Library integration:** component tests for PDF metadata, warnings, clear versus uncertain failure, timeout/manual retry, refreshed/confirmed rows, stale responses and account changes; retain six picker/focus regressions. Run full backend PostgreSQL suite, dependency checks, migration checks, frontend tests, TypeScript and production build.
5. **Real trial:** built-in browser with isolated `dra_test`, real PDF upload/list/reload, duplicate names, mixed-page warning, rejected scan/encryption, two accounts, desktop/mobile/narrow layout, keyboard/focus and picker return. Independently inspect persisted pages/source without logging content. Record agent-browser results separately from the user's manual trial. Never infer completion from generated code or mocked tests alone.

Use only synthetic authored/generated PDF fixtures, with no uploaded/private files committed. Test error paths with controlled worker outcomes as well as real bounded child processes; label simulated resource failures separately from measured resource enforcement. A PDF parser is not a scanner detector or a correctness oracle; document these limitations in acceptance records.

## Decisions for review and verification status

**Agreed policy — 17 October 2026:** the user approved accepting mixed PDFs when at least one page contains usable text, with a clear warning identifying physical pages where no text was extracted. Preserve those pages in provenance. This approval selected the policy; the subsequent “implement” request authorized implementation. Neither establishes extraction completeness.

Selected implementation defaults: pypdf 6.21.1/plain/strict parsing, retained original PDF in PostgreSQL, physical-page provenance, rejection of all encryption, 1 MiB/100 pages and bounded local extraction. The 1 MiB usability limit remains a trade-off for the user trial; raising it needs separate measurements.

Implementation corrections and verification boundaries:

- The initial 256 MiB address-space proposal failed even on a tiny PDF: this Python 3.14 process reserved about 239 MiB before pypdf, and about 259 MiB after importing it (roughly 29 MiB resident). The selected ceiling is 512 MiB. Actual OS allocation failure and CPU/output-file limits are tested independently from simulated worker failures.
- CPU soft limit is 5 seconds with a 6-second hard backstop; the parent wall watchdog is 10 seconds. Killing/reaping happens in `finally`, including Python-level interruptions. A synchronous FastAPI worker is not interrupted immediately when a browser disconnects: extraction still ends within its watchdog, and a disconnected request may commit. No cancellation or timeout is presented as proof that saving failed.
- Resource ceilings are independent: satisfying file/page/text limits does not guarantee acceptance if extraction reaches its CPU/wall budget. Output boundary checks use controlled limits as well as parent validation; a very large single text operator may hit processing limits before its output-size check.
- Starlette's installed parser closes partial temporary files when its request stream raises. The new inner body limiter uses that cleanup and replaces FastAPI's generic parser `400` with `413`; the existing outer authentication middleware still rejects unauthorized requests before receiving their bodies. The cap counts actual bytes even with absent/false Content-Length.
- The generated page-status expression uses PostgreSQL's reflected literal/cast form in the model to avoid Alembic's false “computed default cannot be modified” warning. The immutable migration retains its independent expression; live consistency tests cover both.
- Extraction limits and worker orchestration live in `documents/pdf_worker.py` and `documents/pdf.py`; neither adds another service. Worker input/output uses private temporary files and a minimal environment. This is still not a security sandbox.

Verification results are recorded in [PLAN.md](PLAN.md) and README, separating real PostgreSQL/process tests, mocked frontend checks, browser limitations and the pending user trial. No development migration, historical assignment or backup recovery drill is performed by this milestone.
