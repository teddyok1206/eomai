# PDF document review V1 implementation plan

## Product contract

An authenticated user uploads an immutable PDF, selects `N제`, `주간지`, or `모의고사`, and may add
natural-language review guidance. EOM produces structured, page-anchored review findings. EOM never
edits the source PDF and V1 produces no corrected PDF.

## Delivery slices

### Slice A — protocol and fixed review policy

- add JSON Schema 2020-12 worker input/result contracts for `workflow-role/1.25.0`;
- add frozen Pydantic models and semantic validation;
- add immutable preset files and a deterministic preset resolver/prompt compiler;
- add the one-step `pdf-document-review@1.0.0` workflow and support-role prompt;
- add schema/admission/runner packaging and focused tests.

Exit: valid fixtures pass both JSON Schema and Pydantic; malformed pointers, regions, hashes,
candidate/finding sets, prompt injection, and any mutation claim fail.

### Slice B — immutable PDF intake and page rendering

- add a typed authenticated intake command with bounded `application/pdf` streaming;
- spool only to a private staging directory while hashing and validating the PDF signature;
- send the staged file through the authoritative Artifact application boundary;
- render deterministic page PNGs and optional text-layer JSON in an isolated adapter;
- commit original PDF + page members + manifest as one immutable intake revision;
- store only identities, pointers, state, sizes, and hashes in PostgreSQL.

Exit: duplicate/replay, concurrent intake, unsafe filename/path, symlink, size, encrypted PDF,
renderer failure, and partial-commit tests pass in a disposable environment.

### Slice C — review application and orchestrator materialization

- resolve an immutable preset snapshot and normalize/hash additional guidance;
- create an actor-scoped idempotent review workflow pinned to one intake revision;
- materialize exact page members and `request.json` into the worker workspace;
- bound the single-worker V1 to 32 pages, 16 MiB per page PNG, and 128 MiB of PNG payload; retain
  larger intake revisions but require a future chunked successor for their review;
- validate the result against source pages and commit only through the orchestrator;
- expose bounded list/detail application views.

Exit: missing/stale/hash/media/lifecycle/permission negatives, exact replay, concurrent creation,
lease recovery, and no-binary-in-DB persistence tests pass.

Current implementation checkpoint: resolved plan V13, the dedicated reviewed preset bootstrap,
and exact page/image-manifest materialization are implemented. The authenticated public upload
intent and workflow-start application boundary remain before Slice C can be declared complete.

### Slice D — Scientific Studio

- add a PDF upload control, preset selector, optional additional-guidance field, and progress state;
- render page images through an authenticated same-origin media route;
- display findings in a side list and highlight all anchor rectangles on selection;
- show quoted text, recommendation, severity, and verification status without exposing internal IDs
  by default;
- preserve admin IDs in an expandable detail panel.

Exit: upload/review/list/detail/refresh, A→B stale-response prevention, session expiry, permission
denial, and responsive overlay alignment tests pass in a real browser.

### Slice E — bounded live canary

- deploy one reviewed compatible release set;
- submit one non-sensitive test PDF through the public Studio path;
- verify immutable source hash, page count/order, preset/guidance provenance, anchored findings,
  authenticated display, and zero corrected-PDF output;
- require human visual confirmation before broader activation.

## Test matrix

| Boundary | Required tests |
|---|---|
| Schema/model | Draft 2020-12, mirror parity, canonical serialization, strict hashes, bounds |
| Preset/guidance | all three presets, deterministic hashes, normalization, injection isolation |
| Intake | MIME/signature, size/page limits, encrypted/corrupt PDF, replay/concurrency, cleanup |
| Pointer resolution | missing/stale/unauthorized/wrong schema/media/hash/member/lifecycle |
| Orchestrator | exact staging, no worker NAS write, idempotent result commit, lease recovery |
| Result | region containment, quote hash, sorted unique IDs, candidate/finding equivalence |
| API/Web | RBAC, CSRF, streaming limits, refresh, stale response, redaction, pagination |
| Persistence | no PDF/PNG/long result bytes in DB rows; immutable Artifact lineage |

## Activation and rollback

The feature remains unavailable until all slices required by the live route are installed as one
compatible release set. Rollback disables new admission and restores the previous API/Web/runner
release set. It never deletes uploaded documents, review Artifacts, Jobs, events, or failure
evidence.

## Initial implementation boundary

Slice A is implemented in commit `622c309`: JSON Schema/Pydantic, immutable presets, guidance
normalization, workflow admission, runner/orchestrator validation, and deployment packaging are
present and tested.

Slice B now has its Catalog-owned core: `catalog/1.16` validates an immutable intake manifest,
safe-opens and hashes one bounded PDF, rejects encryption and invalid page counts, renders ordered
PNG pages with root-owned Poppler executables, and commits the source, pages, and manifest through
the existing Artifact owner. Exact replay verifies every committed member hash. The private
Application API→Catalog streaming protocol is also implemented: JSON Schema validates a bounded
header, the PDF remains raw streamed bytes, both endpoints verify stable file identity and SHA-256,
and the Catalog receiver rejects truncation, excess bytes, and hash drift before intake. The public
authenticated upload-intent route remains pending and therefore browser upload is not yet active.

Slices C–D must consume these frozen contracts rather than inventing local dictionaries or
prompt-only semantics. This ordering is a protocol gate, not a claim that PDF review is already
available in Scientific Studio.
