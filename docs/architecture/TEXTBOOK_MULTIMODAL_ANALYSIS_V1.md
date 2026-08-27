# Textbook Multimodal Knowledge Analysis V1

Status: Design accepted for additive implementation

Date: 2026-08-27 UTC

## 1. Responsibility and boundary

This design makes every selected textbook page image a mandatory Codex input. The educational
document service owns canonical PDF and derived analysis-bundle pointers. The Orchestrator alone
resolves, authorizes, materializes, and attaches page images. A worker receives only the bounded
page range selected by the request and never reads NAS or another worker workspace.

The end-to-end transformation is explicitly:

```text
canonical textbook PDF
  -> exact page PNGs (mandatory visual evidence) + extracted page text (auxiliary evidence)
  -> Codex multimodal analysis
  -> Codex-authored normalized Markdown + typed knowledge proposal
  -> validated, deterministic Markdown views + graph-ready JSONL members
```

The extracted page Markdown is not the analysis product and is never accepted as a substitute for
Codex analysis. It is only an OCR/text-layer aid presented alongside the mandatory PNG.

The change is additive. Historical text-only bundle `1.0`, Knowledge Analysis request `5.0`,
worker proposal `3.0`, result `5.0`, resolved plan `4.0`, and workflow-role `1.7.0` bytes retain
their original meaning. Text-only V4--V7 executions remain historical evidence and are not eligible
as the current source for the multimodal textbook graph.

## 2. Canonical source and revision model

The original purchased PDF remains the one canonical source Artifact Revision. A derived textbook
source bundle is one immutable Artifact Revision containing:

- `analysis/index.md`;
- one extracted Markdown member per physical page;
- one lossless PNG member per physical page; and
- a manifest that pins both members, their SHA-256 hashes, byte sizes, dimensions, render settings,
  and the original PDF revision.

The PNG is a reproducible materialization, not a second source identity. Batch manifests and
Knowledge Analysis requests contain typed pointers only. They never copy PDF, PNG, or Markdown
bytes into PostgreSQL.

An accepted analysis result is a separate immutable Artifact Revision. Its canonical authored
members are `normalized/document.md` and the typed anchor, node, edge, claim, component, ambiguity,
and page-image-observation members. The platform may deterministically project additional readable
views such as `views/concepts.md`, `views/visual-materials.md`, `views/curriculum-map.md`, and
`views/question-use.md`. These views are derived materializations whose manifest pins the accepted
result revision and projection version; they are not independent copies or competing sources of
truth.

An exact source coverage is identified by the tuple
`(document_revision_id, first_physical_page, last_physical_page)`. A compatible accepted analysis
must be reused. A later extractor, protocol, or reviewed correction creates a superseding analysis
revision for the same coverage; it does not create a second current coverage. A graph snapshot may
select at most one analysis revision for an exact coverage.

## 3. Required pointers and resolution checks

For each selected physical page the immutable source contract carries one Markdown pointer and one
PNG pointer. Resolution validates:

- logical Artifact ID and pinned Artifact Revision ID;
- approved lifecycle and pointer relationship;
- canonical NAS root and safe member path;
- manifest schema, media type, byte size, and SHA-256;
- PNG signature, regular-file/non-symlink status, bounded dimensions and bytes;
- physical-page identity and deterministic ordering; and
- exact one-to-one Markdown/PNG coverage of the requested page interval.

The job-local image-input manifest repeats only the typed identity, page number, relative path,
size, dimensions, and SHA-256. The worker launcher re-hashes each PNG immediately before invoking
Codex and passes every verified path through one `--image` option. Missing, duplicate, extra, stale,
or reordered inputs fail before model execution.

## 4. Access patterns and data structures

Dominant operations are exact page lookup, ordered iteration, membership validation, and immutable
snapshot assembly. Page members therefore use an ordered tuple plus maps keyed by physical page
for validation. Duplicate checks use sets. Exact coverage lookup uses an indexed database key, not
repeated JSON scans. Graph publication builds one map from coverage key to selected analysis run
and rejects a second value.

For a maximum 32-page analysis request, validation and materialization are O(p) time and O(p)
auxiliary metadata, where `p <= 32`. PNG bytes are streamed or copied once at the explicit
workspace boundary. They are not decoded into PostgreSQL or deep-copied in application memory.

## 5. Protocol line

The additive protocol line uses new immutable identities:

- textbook analysis bundle manifest `2.0`;
- educational-document Knowledge Source `4`;
- Knowledge Analysis request `6.0`;
- Knowledge Analysis worker proposal `4.0`;
- Knowledge Analysis accepted result `6.0`;
- resolved execution plan `5.0`;
- Codex image-input manifest `1.0`;
- workflow role protocol `1.8.0`; and
- knowledge-analysis workflow definition `5.0.0`;
- graph snapshot manifest `4.0`; and
- graph publication artifact protocol `catalog-knowledge-graph/1.2`.

Graph snapshot V4 is the first snapshot contract that may pin the multimodal Educational Document
source family. It remains dual-read with V2/V3 snapshots. Publication chooses V4 positively from a
V4 source pointer; it never coerces the source into the older text-only document type. Retrieval
accepts all three immutable snapshot schema identities and keeps the selected manifest revision and
hash pinned through Evidence Bundle V4.

The worker proposal contains a `page_image_observations` tuple. It must contain exactly one entry
for each selected physical page and repeat the pinned PNG SHA-256. This is a closed delivery and
result attestation: it proves that every page was attached to the invocation and that the worker
returned an observation for every attachment. It cannot reveal internal model attention, so it is
not described as neurological proof that a model “looked”; it is the strongest enforceable system
boundary available.

The proposal's `normalized_markdown` is authored by Codex from the combined visual and auxiliary
evidence. It must cite physical pages through typed anchors. OCR page Markdown is never copied into
this field unchanged merely to satisfy the output contract. Specialized Markdown views are rendered
after typed validation so the graph proposal remains the authoritative structured representation.

## 6. Transaction, concurrency, and idempotency

Bundle publication is content-addressed and idempotent. Knowledge Analysis creation derives a
coverage key and an analysis-contract key before insertion. A database uniqueness boundary prevents
two active or accepted executions for the same coverage and compatible contract, including
concurrent batch submissions. Exact accepted matches use `REUSE_ACCEPTED`. A protocol replacement
must explicitly identify the current accepted analysis it supersedes and atomically advance the
coverage head after acceptance.

Historical runs and Artifact Revisions remain immutable. Supersession changes only the current
pointer. No cleanup operation deletes historical evidence, and no graph publisher silently chooses
“latest”. Publication receives and validates one pinned revision per coverage.

## 7. Dependency direction and adapter ownership

- Contract packages define pointer, image-input, observation, and coverage value objects.
- Application services own eligibility, idempotency, coverage-head transitions, and graph selection.
- The educational-document adapter creates and commits derived bundle members.
- The Orchestrator materializer resolves Artifact pointers and writes the bounded workspace copy.
- The worker-exec adapter alone translates the reviewed image-input manifest into Codex CLI
  `--image` arguments.
- Workers neither render PDFs nor discover files by walking directories.

Domain and contract packages do not import Poppler, Tesseract, filesystem, subprocess, SQLAlchemy,
or Codex adapters.

## 8. Failure, retry, and acceptance

Stable failures distinguish bundle-image absence, unsafe PNG, pointer/hash mismatch, incomplete
image coverage, unsupported CLI image capability, and duplicate coverage. No failure automatically
submits a second model execution. A failed run may be retried only through the existing explicit
predecessor/idempotency contract after its cause is corrected.

Acceptance requires structurally valid ontology references when ontology content is present, plus:

1. every selected page has exactly one pinned PNG;
2. every pinned PNG was included in the immutable invocation manifest;
3. the launcher attached exactly that ordered set;
4. the proposal reports exactly that ordered set and hashes; and
5. all anchors remain within the selected physical-page range.

These are delivery and identity invariants, not an artificial content quota. A page observation may
explicitly be `OBSERVED`, `NO_RELEVANT_CONTENT`, or `UNCLEAR`; `UNCLEAR` may carry a non-blocking
ambiguity. A whole bounded range may be accepted with zero anchors, nodes, edges, claims, and
component observations when every page is honestly classified as having no relevant or sufficiently
clear content. The normalized Markdown remains a non-empty authored assessment of that outcome.
Acceptance does not require every page to yield a claim, concept, table, or figure, does not impose a
minimum extraction count, and does not reject an otherwise valid result merely because OCR is sparse.
It rejects fabricated certainty, missing visual delivery, unresolved pointer identity, and
structurally invalid references.

The acceptance boundary is therefore split deliberately:

- **hard delivery checks:** exact page set, ordered PNG attachments, hashes, pointer resolution,
  schema validity, safe paths, and internally valid references;
- **soft content outcomes:** absence of relevant material, uncertainty, sparse OCR, low extraction
  count, or an intentionally empty graph proposal.

## 9. Security and capacity

PNG files remain read-only job-local materializations. Paths are allowlisted relative paths;
symlinks, hardlinks, special files, decompression bombs, oversized images, and unexpected media are
rejected. The worker sandbox remains read-only and ephemeral. Images are bounded to 32 pages per
job. The initial limits are 16 MiB per rendered PNG and 128 MiB for the complete ordered image set;
the analysis timeout is 7,200 seconds. These are denial-of-service and runaway-process bounds, not
content-quality quotas. They must be checked against a worst-case 32-page local render before
rollout and expanded additively if the measured headroom is inadequate. The CLI still uses the
fixed slot identity and its private authentication; no API key, token, PDF, or image bytes enter
Git, Slack, or PostgreSQL.

The host-side bundle producer has two explicit Ubuntu runtime dependencies. `poppler-utils` owns
PDF identity/page-count inspection, text-layer extraction, and lossless page rendering; Tesseract
plus the Korean and English language packs owns optional OCR fallback. They are infrastructure
adapter dependencies only and never enter a domain or contract package. Poppler is required because
Ghostscript-only rendering would create a second, unreviewed extraction implementation and different
reproducibility identity. Package versions and executable hashes are pinned into each bundle
manifest. Removing either dependency disables new bundle creation but does not affect reading or
resolving already registered immutable bundles.

## 10. Tests and rollout

Tests cover deterministic PNG generation, manifest/package byte equality, missing/extra/duplicate
pages, page/path/hash/dimension mismatch, symlink and unsafe media rejection, exact `--image`
ordering, old text-only protocol preservation, isolated CLI capability detection, compatible result
reuse, concurrent duplicate creation, superseding coverage heads, and graph publication rejection
of duplicate coverage.

Rollout first publishes new bundle revisions without deleting v1 bundles, then deploys the dual-read
application and worker runtime, runs a non-generating materialization/command-shape smoke, and only
then starts a separately authorized V8 multimodal batch. V7 may finish for diagnostics, but its
text-only results are not published as the final textbook corpus.

The long-running textbook batch operates as a bounded background lane. It has an explicit slot cap
and claim budget separate from interactive one-item production. GUI/API processes never wait for a
batch to drain, and item-production jobs are not queued behind textbook-analysis capacity. A runtime
deployment pauses only new textbook claims, lets already claimed jobs reach a durable boundary,
deploys the compatible dual-read release, and then resumes claims. Batch, item-production, and GUI
health are reported independently so a batch failure cannot make the product read model unavailable.
No batch worker receives permission to mutate item-production or GUI state.

The initial capacity partition reserves slots 01--04 for interactive item-production workflows and
uses slot 05 as the sole textbook-analysis support lane. Therefore at most one long analysis worker
runs concurrently, while four interactive slots remain available. The two-hour worker timeout is a
per-range safety ceiling; a 495-range batch has no aggregate wall-clock expiry and advances through
durable, idempotent range claims. A process restart may resume only an unsubmitted claim or reconcile
an already persisted job; it must never create a second analysis run for the same coverage key.

The pre-rollout capacity probe rendered physical pages 16--47 of the 184-page MiraeN volume I PDF
with the production Poppler/Tesseract fallback adapter at 180 DPI. All 32 PNGs totaled 21,232,796
bytes; the largest was 1,868,693 bytes and the 95th percentile was 1,460,472 bytes. This consumed
15.82% of the aggregate byte ceiling and 11.14% of the per-image ceiling. Bundle construction took
21.39 seconds with 102,860 KiB peak RSS. The existing byte and two-hour time ceilings therefore have
substantial measured headroom and remain unchanged. Re-measure before accepting a higher DPI,
different renderer, or more than 32 pages per range.

## 11. Rejected simpler alternatives

Prompting the worker to open PNG files without CLI attachment is insufficient because delivery is
not enforceable. Passing the original PDF is too broad, harder to bound, and does not pin the exact
rendered visual input. Re-running OCR at worker time breaks reproducibility and lets workers invoke
unreviewed infrastructure. Editing v1 bundle or v5 request schemas would reinterpret historical
evidence. Storing PNG bytes in PostgreSQL violates the artifact boundary. Allowing multiple current
analyses and relying on a later query to pick the newest is nondeterministic and cannot prevent
duplicate graph content.
