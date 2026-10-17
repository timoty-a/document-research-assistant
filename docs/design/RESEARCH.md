# Milestone 2: document-library research and design brief

Research date: 15 October 2026. This is the pre-implementation design brief; current milestone status and verification are recorded in [docs/PLAN.md](../PLAN.md). This report records design proposals, not implementation evidence.

## 1. User, task, and scope

A student or professional gathers multiple sources to investigate a question and support an assignment, report, or literature review. The eventual workflow is **organize sources → ask a question → inspect passages → compare evidence → save findings**. The immediate task is narrower: add a text document, confirm it was saved, and recognize it in a persistent library.

The existing API supports one UTF-8 `.txt` upload at a time, up to 1,048,576 bytes, and metadata listing (`id`, `original_filename`, `byte_size`, `created_at`). There is no document-reading endpoint, PDF support, accounts, AI answering, collection management, or saved findings. No preview, open-document link, chat composer, or comparison action belongs in the first working interface.

## 2. Evidence and competitor comparison

**Method:** reviewed public official help pages. No signed-in product was used, and no user study was conducted. An Adobe screenshot could not be fetched; browser inspection was also blocked. No screenshot or demo was visually verified. Panel descriptions below are documentation claims, not observations of a live interface. Availability can vary by platform and plan; feature presence does not establish accuracy or usability.

Google's original NotebookLM help URLs currently redirect to pages titled “Gemini Notebook”; this report retains the requested NotebookLM name. Elicit's current documentation says its standalone Find Papers, Extract Data, and Chat with Papers tools moved into Research Agent on 30 September 2026; older separate-tool navigation should not be copied. [Google chat help][N2]; [Elicit workflow update][E3].

| Product | Source management | Evidence verification | Cross-document comparison | Navigation |
| --- | --- | --- | --- | --- |
| **NotebookLM** | Notebook-scoped imported sources; select a subset for a question. [Sources][N1] | Hover a citation for quoted text; select it to inspect context. [Chat][N2] | Multiple selected sources provide question context; the guide recommends naming sources for focused questions. [Sources][N1] | Documented left source viewer and Chat panel; responses can be saved to notes with citations. [Sources][N1], [Chat][N2] |
| **Adobe Acrobat AI Assistant / PDF Spaces** | Group files, links, or pasted text in a named space. [Create a space][A1] | Citation references expose document title, section, and page; selecting references opens source content. [Citations][A2] | Adobe documents multi-document analysis/comparison; PDF Spaces supplies the shared content context. [Use cases][A3], [Spaces][A1] | Documented Files/Creations area, central Overview, and Assistant panel; panels can be expanded or closed. [Layout][A1] |
| **Elicit** — chosen for literature-review relevance | Library with uploaded/saved papers, tags, and collections, accessible from the sidebar. [Library][E1] | Research Agent citations open the originating paper/page; this is a vendor-described verification path, not an independent correctness assessment. [Agent][E2] | Agent can produce comparison tables; Systematic Reviews provide controlled screening and extraction workflows. [Agent][E2], [Workflow guide][E4] | Persistent Library plus conversational sessions and an Artifacts menu; current home entry points distinguish Agent, Reports, and Systematic Reviews. [Library][E1], [Agent][E2], [Workflows][E4] |

## 3. Patterns worth adapting

- **Keep source identity visible.** NotebookLM makes the selected source set explicit. Now: show recognizable filenames, byte sizes, upload times, and distinguishable IDs. Later: explicit source selection for questions. [Google sources][N1]
- **Put provenance beside the claim.** Acrobat exposes reference details at the point of inspection. Now: keep metadata attached to each row and avoid a badge implying content was analyzed. Later: passages with surrounding context and a return path to the answer. [Adobe citations][A2]
- **Use consistent columns for comparison.** Elicit's structured tables suggest a stable scanning pattern. Now: compare filename, size, and upload time only. Later: evidence columns backed by excerpts, with missing evidence explicit. [Elicit Agent][E2]
- **Separate collection from interpretation.** Elicit's Library persists beyond a research conversation. Give our library a stable home; introduce questions and saved findings only when supported. This is a design inference from the documented separation. [Elicit Library][E1]

## 4. Friction and opportunities — hypotheses

These are untested hypotheses about our users, not established competitor defects.

| Hypothesis | Design opportunity now | Later validation |
| --- | --- | --- |
| Several panels may overwhelm someone who only wants to add sources. | One primary library view and upload action. | Ask users to upload and locate a source without guidance. |
| Familiar research products may create expectations of PDF support or instant answers. | State “UTF-8 .txt only · maximum 1 MiB”; explain that this version stores and lists sources. | Ask users what they expect after upload. |
| Similar filenames may make sources difficult to distinguish. | Preserve full names; expose size, time, and full ID in metadata details. Do not merge by filename. | Test a library containing duplicate names and long names. |
| A timeout may prompt a duplicate upload even if the original committed. | Separate definite rejection from an unknown outcome; offer list refresh before a deliberate retry. | Simulate lost upload responses and observe recovery. |

## 5. Three visual directions for our library

All directions use real metadata only, with no generated thumbnails, excerpts, or fake research controls. Font choices are proposed system stacks, not installation requirements; palettes still need contrast verification.

| Direction | Layout | Typography and palette | Interaction and trade-off |
| --- | --- | --- | --- |
| **A. Research ledger** | Single wide column; title/count and Upload button; compact upload form above an aligned metadata table. Stack row fields on small screens. | System sans, 16px body and 28px heading; tabular numerals. Warm background `#FAF9F6`, white surfaces, ink `#20252B`, teal action `#0F635B`, red error `#A12622`. | Explicit choose-file and submit buttons, inline status, quiet row dividers. Dense enough for many sources while remaining approachable. No row click suggesting a reader. |
| **B. Technical catalogue** | Narrow desktop identity rail with the current Library location; dense table and upload strip. Rail becomes a header on mobile. | System sans, 15–16px body; monospace IDs and sizes. Cool background `#F1F5F9`, white table, navy `#172033`, blue `#1D4ED8`, red `#B91C1C`. | Compact metadata disclosure and a persistent Refresh action; precise focus outlines. Suits repeated metadata inspection, but the rail consumes space with only one destination today. |
| **C. Source shelf** | Generous heading, upload block, then two-column document cards; one column on narrow screens. Cards contain filenames and metadata, not content previews. | Georgia headings, system sans metadata, 16px body. Paper `#FFF9F0`, dark brown `#30251F`, rust `#9A3412`, pale dividers `#E4D8C8`, red `#A12622`. | Large controls and native expandable metadata details; restrained motion. Welcoming for a small collection, but fewer sources fit on screen and comparison requires more scanning. |

## 6. Recommendation

Choose **A, Research ledger**. It maps directly to the metadata endpoint, makes errors and saved status legible, and adapts to mobile without an empty navigation rail. It provides a consistent place for future source selection while avoiding a premature multi-panel research workspace. This is a reasoned design recommendation, not a user-tested winner.

Start with upload, listing, refresh, and metadata details. Defer folders, tags, filename search, custom sorting, bulk upload, deletion, and reading. Use relative `/documents` requests through a local frontend development proxy to the existing backend; plan that integration without changing backend behavior. Keep the entire application local until authentication and per-user access exist.

## 7. Acceptance criteria for the first working interface

These are proposed milestone 2 criteria, not completed checks:

1. **Honest scope:** show the TXT/UTF-8/1 MiB limits before selection. No PDF affordance, answer box, document-content preview, or unsupported reading/navigation control. Library rows expose only returned metadata; filenames render as text, never HTML or filesystem links.
2. **Upload:** native single-file picker plus explicit Upload button; `.txt` acceptance hint is not treated as validation. Check extension case-insensitively and byte size locally; backend validation remains authoritative. Submit multipart `file` without manually inventing its boundary.
3. **Loading:** distinguish initial list loading, list refresh, and upload in progress. Preserve existing rows during refresh. Prevent duplicate submission while uploading; use indeterminate status unless actual progress is measured. Reject stale list responses that would hide an acknowledged upload.
4. **Empty:** show the first-upload prompt only after a successful `GET` returns `[]`; a failed request must never look like an empty library.
5. **Success:** only `201` confirms saving. Announce success, show returned metadata, reconcile rows by ID, and retain backend ordering (timestamp then ID ascending). If the following list refresh fails, retain the successful upload acknowledgement and offer Refresh separately.
6. **Errors:** show actionable messages for `400`, `413`, `422`, and `503`; never show raw exceptions or SQL. On network failure, distinguish an unknown upload outcome from definite rejection. Never automatically retry POST; suggest refreshing the library before explicitly retrying. Preserve a usable file-selection/reselection path.
7. **Keyboard:** picker, submit, refresh, and metadata disclosure work using Tab/Shift+Tab and native activation keys. Provide visible focus, logical order, labels, no keyboard trap, and no hover-only information. Announce asynchronous status politely and associate errors with the upload form; do not steal focus when rows refresh.
8. **Responsive/accessibility:** usable at 320px and 1440px widths and 200% zoom without horizontal page scrolling or lost controls. Long filenames wrap; full names/IDs remain available. Use semantic headings/table or labelled stacked metadata; target 4.5:1 normal-text contrast, 3:1 control/focus contrast, and 44px touch targets. Status must include text, not color alone.
9. **Verification:** cover loading/empty/success/error states with component tests and a browser trial; exercise keyboard use, long/duplicate names, failed refresh after success, uncertain upload outcome, and narrow layout. An end-to-end synthetic upload/list/reload trial must show persistence. Keep test mutations in the dedicated test environment; no secrets or document contents in logs.

[N1]: https://support.google.com/gemininotebook/answer/16215270?hl=en "Google: Add or discover sources"
[N2]: https://support.google.com/gemininotebook/answer/16179559?hl=en "Google: Use chat"
[A1]: https://helpx.adobe.com/acrobat/web/explore-pdf-spaces/create-pdf-spaces.html "Adobe: Create PDF Spaces on the web"
[A2]: https://helpx.adobe.com/acrobat/desktop/explore-pdf-spaces/view-citations.html "Adobe: View citations in responses"
[A3]: https://helpx.adobe.com/acrobat/desktop/use-acrobat-ai/get-started-with-generative-ai/explore-acrobat-ai.html "Adobe: Explore generative AI"
[E1]: https://support.elicit.com/en/articles/14757550-elicit-s-library "Elicit: Library"
[E2]: https://support.elicit.com/en/articles/14756886-elicit-s-research-agent "Elicit: Research Agent"
[E3]: https://support.elicit.com/en/articles/17220397-where-did-find-papers-extract-data-and-chat-with-papers-go "Elicit: Workflow transition"
[E4]: https://support.elicit.com/en/articles/14757543-getting-started-with-elicit-which-workflow-should-i-use "Elicit: Workflow guide"
