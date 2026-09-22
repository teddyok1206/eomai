# ADR 0102: Immutable PDF document review with anchored findings

- Status: Accepted
- Date: 2026-09-22

## Context

EOM needs a product workflow in which an authenticated user supplies a PDF, chooses a review
context (N제, 주간지, or 모의고사), optionally adds natural-language review guidance, and receives
review findings whose exact location can be shown in Scientific Studio. The existing item reviewer
already has useful verification-planning, candidate re-check, Graph-evidence, and bounded
escalation semantics. Its item-specific result schemas and authoring pointers are not valid PDF
review contracts.

The product does not edit PDFs. A suggestion such as “이 문장을 …로 바꾸어 주세요” is advice
attached to an immutable page region; it is never an instruction for EOM to rewrite, patch, or
silently replace the uploaded document.

## Decision

### Responsibility and boundary

Add a distinct `pdf-document-review` workflow and `workflow-role/1.25.0` support-role protocol.
The worker reads only an orchestrator-staged request and exact rendered page inputs, then returns a
schema-valid review result. The worker cannot write NAS, contact another worker, change the PDF, or
approve publication. The orchestrator validates and commits the JSON review Artifact.

The first implementation is split into explicit boundaries:

1. intake registers the original PDF as one immutable Artifact Revision and renders immutable page
   PNGs plus optional text-layer members;
2. review pins that source revision, its page members, one review-preset revision, and the normalized
   additional guidance;
3. the orchestrator stages only those pinned members into an isolated worker workspace; and
4. Scientific Studio resolves the committed result and draws highlights over a page image.

There is no corrected-PDF endpoint, field, Artifact type, or workflow step.

The first executable review protocol is intentionally bounded to one worker invocation: at most 32
ordered page PNGs, at most 16 MiB per PNG, and at most 128 MiB of PNG payload. Catalog intake may
retain larger immutable PDFs, but those documents require a future chunked successor workflow; V1
fails closed instead of claiming that one Codex invocation can review 2,000 pages.

The Catalog intake Artifact uses the otherwise unused immutable protocol identity `catalog/1.16`;
it does not reuse the existing `catalog/1.14` item-review publication or `catalog/1.15` solution
analysis identities.

The Application API does not base64-encode a PDF into JSON. Its authenticated upload boundary
spools a bounded stream to private local state, then sends a small schema-validated header followed
by exactly the declared raw bytes over the existing private Catalog Unix socket. The receiver
hashes while writing a fresh mode-0600, single-link staging file, requires EOF at the exact declared
length, and only then calls the Catalog intake service. The response is a typed immutable document
pointer, not the PDF or page bytes. This is an explicit materialization boundary between the API
transport and the Catalog Artifact owner.

### Canonical source, logical entities, and revisions

The original uploaded PDF Artifact Revision is the canonical document source. Page PNG and text
members are reviewed derivations in the same immutable intake manifest; OCR text is an aid, not a
replacement source identity.

```text
document logical ID -> immutable document revision
                    -> original PDF Artifact Revision + SHA-256
                    -> ordered page render pointers + SHA-256
                    -> optional page text pointers + SHA-256

review logical ID   -> immutable review revision
                    -> exact document revision
                    -> exact preset revision
                    -> normalized guidance + SHA-256
                    -> structured anchored finding Artifact Revision
```

Filesystem paths are locations only. Reproducible review history pins document, Artifact, Artifact
Revision, member, media type, schema reference, content length, and SHA-256 separately.

### Pointer resolution

Before any source is staged or displayed, resolution verifies:

- logical and immutable revision existence;
- the authenticated actor's read permission;
- expected lifecycle state;
- exact schema reference and media type;
- regular-file, no-symlink, bounded-size metadata;
- member path containment and manifest membership; and
- content hash equality before and after a stable read.

Missing, stale, unauthorized, or hash-mismatched pointers fail with stable errors. They never fall
back to a mutable latest revision.

### Location model

Each anchor pins an exact rendered page member and uses integer parts-per-million coordinates in
the normalized, rotation-applied page coordinate space:

```text
x_ppm, y_ppm, width_ppm, height_ppm in [0, 1_000_000]
```

The rectangle must remain inside the page. Integer coordinates make canonical JSON stable and
avoid floating-point drift. A text anchor also carries a bounded exact quote and its SHA-256. A
finding may carry multiple anchors for a statement, answer, explanation, table, or figure that must
be interpreted together.

### Review presets and additional guidance

Three immutable preset families are initially supported:

- `PROBLEM_SET` (`problem-set/1.0`): independent problem quality, answer uniqueness, solution
  correctness, difficulty and originality;
- `WEEKLY_WORKBOOK` (`weekly-workbook/1.0`): lesson continuity, weekly workload, scaffolding,
  repeated terminology, answer and explanation consistency; and
- `MOCK_EXAM` (`mock-exam/1.0`): exam-wide instructions, numbering, scoring, timing, balance,
  answer uniqueness, visual consistency, and publication readiness.

The selected preset snapshot is server-authored and self-hashed. User guidance is normalized,
bounded, separately hashed, and placed in a clearly marked untrusted-data block after the fixed
review policy. It can narrow emphasis or request extra checks. It cannot change the output schema,
permissions, sandbox, source pointers, mutation prohibition, or system instructions.

The prompt reuses the proven item-review research: target-first verification, visual-first checks
when relevant, independent answer/solution verification, Graph-grounded evidence where the
orchestrator explicitly supplies it, candidate confirmation/demotion, concise auditable rationale,
and no hidden chain-of-thought transcript. It does not reuse item-specific draft pointers or result
schemas.

### Output and non-mutation rule

The canonical result is structured JSON containing verification targets, candidate dispositions,
confirmed findings, page anchors, and recommendation-only operations (`REPLACE`, `INSERT`,
`DELETE`, `MOVE`, `REDRAW`, `VERIFY`, or `NONE`). `mutation_performed` is always `false`.

A future annotated viewing derivative may draw callouts over page images, but it must be a new
derived Artifact that references the untouched source. It must never be named or presented as a
corrected PDF. It is not part of V1.

### Access patterns and data structures

Dominant operations are ordered page iteration, ID lookup, membership, deduplication, and immutable
history:

- pages, verification targets, candidates, findings, and anchors are immutable tuples;
- page, target, candidate, and finding resolution uses dictionaries keyed by stable ID;
- duplicate IDs and references are rejected with sets;
- page-member membership is checked against a manifest map; and
- review/job history is append-only with existing monotonic event sequences.

For `P` pages, `T` verification targets, `C` candidates, `F` findings, and `A` anchors, validation
is `O(P + T + C + F + A)` time and linear bounded memory. V1 bounds are 2,000 pages, 256 targets,
512 candidates/findings, eight anchors per candidate/finding, and 256 MiB for an uploaded PDF.
No repeated list membership scans or N+1 page lookups are permitted.

The private upload transport performs `O(n)` sequential read/hash/write work in the PDF byte length
and uses `O(1)` streaming memory. The later public upload intent is indexed by owner/time and unique
idempotency identity; it is not a second document registry. No raw PDF or PNG bytes enter
PostgreSQL.

The public boundary is intentionally two-step. An authenticated JSON command creates a bounded
upload intent containing only the original filename, declared byte count, preset key, normalized
optional guidance, hashes, state, and timestamps. A second authenticated `application/pdf` PUT
materializes the declared bytes once in an API-private mode-0600 file. The API verifies exact byte
count, `%PDF-` signature, regular-file/single-link identity, and SHA-256 before Catalog intake. The
file is removed after the application command finishes; it is never canonical storage.

The upload-intent state machine is an explicit lookup table:

```text
AWAITING_UPLOAD -> PROCESSING -> STARTED
                            \-> FAILED_RETRYABLE -> PROCESSING
                            \-> FAILED_FINAL
```

An intent belongs to one operator. Its first accepted upload pins `upload_sha256`; subsequent
attempts must use the same byte count and hash. `STARTED` pins one Workflow ID. Key lookup is by the
primary intent ID; owner list order uses the B-tree `(operator_id, created_at DESC,
upload_intent_id)`; claim recovery uses a partial B-tree on processing lease expiry. These are O(1)
indexed identity lookups and O(log n + page-size) owner listings at a scale of thousands of intents,
not PDF-byte storage or a document search index.

The intent claim uses a fresh server-generated 128-bit lease token for every acquisition and a
compare-and-set finalization. A stale uploader cannot finalize after takeover. Catalog intake and
Workflow creation use stable domain idempotency keys derived from the immutable intent identity,
so a timeout or crash may replay the same effects but cannot create a second document or Workflow.
The intent transaction never spans socket upload/rendering. The simpler alternative—holding a
PostgreSQL row lock during PDF rendering—would cause long transactions and connection starvation;
using only the HTTP idempotency receipt would not expose durable upload state or fence a process
that dies between Catalog commit and Workflow creation.

### Transactions, concurrency, retry, and idempotency

Intake commits the PDF and derived page manifest atomically through the existing authoritative
Artifact owner. Review creation pins the committed intake revision and uses an actor-scoped
idempotency key. Concurrent identical submissions adopt the exact existing workflow; a reused key
with different source, preset, guidance hash, or permissions fails closed.

Existing atomic command claim, lease, workflow step-attempt, Job, Artifact Revision, and event
constraints remain authoritative. Retry preserves the exact document/preset/guidance identity.
Timeout does not authorize a new key or a duplicate review.

### Fixed worker execution ceiling

The released PDF-review preset pins a 3,600-second execution ceiling because one invocation may
inspect up to 32 ordered page images. Slot 06 therefore has a dedicated root-owned
`eom-worker-document-review-06@.service` template fixed at exactly 3,600 seconds. Runtime selection
is an O(1) lookup by the validated `(slot ID, role, timeout)` tuple. The existing 900-second
customer-support and 7,200-second analysis templates remain distinct and immutable.

All three templates share the same slot-06 Linux identity and the same unique capacity lease, so
the additional template adds no capacity or concurrent execution path. Readiness checks its exact
root ownership, mode, and SHA-256; polkit permits only `start` for a canonical job instance; and
recovery inspects every reviewed template for the job and fails closed if observations are
ambiguous. Rewriting the already-pinned preset to fit another template is insufficient because it
would invalidate reproducible history and could shorten a document review after admission.

### Dependency direction and adapters

JSON Schema and frozen value models define the contract. Application services own intake/review
use cases, validation, idempotency, and transactions. PostgreSQL, NAS, PDF rendering, HTTP upload,
and Codex execution remain infrastructure adapters. Scientific Studio calls application endpoints;
it does not resolve NAS paths or implement review invariants.

The browser uploads through the authenticated same-origin Studio BFF. JSON intent creation remains
small, while the raw `application/pdf` body is streamed through the BFF to the Application API
without base64 encoding or a PostgreSQL copy. The normal Studio JSON-body limit remains in force
for every other route. A single-consumer PDF stream is never transparently sent twice after an
authentication failure; the browser may re-authenticate and replay the same frozen idempotency
keys.

No external LLM API is introduced. Workers continue to run through the orchestrator and cannot
write NAS.

### Failure behavior

Invalid PDF signatures, encrypted/unsupported documents, page-count or byte limits, rendering
failure, malformed text layers, unsafe member paths, pointer drift, schema failure, invalid
coordinates, inconsistent candidate/finding sets, and worker timeout are explicit failures. A
partial review is not silently published as complete.

### Simpler alternatives rejected

Prompt-only free text is insufficient because a user could not reliably locate a finding and the
application could not validate source identity. Storing only page number and quote is ambiguous in
scans and repeated text. Storing only pixel coordinates is unstable across render sizes. Letting
the worker rewrite the PDF violates the product decision and destroys provenance. Reusing the item
review result would couple document review to AssessmentItemContent and create an unjustified
generic-review framework. A new vector database or queue is unnecessary; existing immutable
pointers, Artifact storage, Workflow, claim, and lease boundaries are sufficient.

### Existing review assets reused

The fixed policy is derived from, and must remain compatible in spirit with, the repository's
current independent-review work rather than a new free-form reviewer prompt:

- `content/packs/generated-knowledge-item/1.19.0/prompt-templates/review.md` supplies the
  target-first, visual-first, independently-solve, candidate re-check, and concise-audit pattern;
- `config/control-plane/standard-item-v15/instructions/review.md` supplies the immutable-source,
  untrusted-input, exact-pointer, and fail-closed evidence discipline; and
- ADR 0101 supplies the distinction between verification targets, candidate findings, confirmed
  findings, bounded escalation, and human decision.

PDF review deliberately copies none of their item-only draft paths, Item result schema, automatic
authoring rework, or approval semantics. The three preset snapshots specialize the fixed policy;
the optional user text is additive untrusted guidance and never replaces it.

## Consequences

- Users can see exactly which page regions a finding concerns.
- Preset policy and user emphasis are reproducible and independently auditable.
- The original PDF remains byte-for-byte immutable.
- V1 has repository-complete intake, application, and Studio overlay slices, but still requires a
  compatible release deployment and bounded live canary before it is called live.
- Future textbook review may add Graph retrieval through a successor contract without changing V1
  history or weakening source-page identity.

## Implementation checkpoint

The repository implementation now includes resolved plan V13, exact page staging, the bounded
Codex image manifest, a dedicated `pdf-document-review` preset bootstrap, durable upload intents,
raw PDF streaming, owner-scoped list/detail projection, private Catalog page-media resolution, and
the Scientific Studio anchored-review view. Studio exposes preset selection plus additive natural
language guidance, keeps internal identities behind an expandable detail, and draws every selected
finding rectangle over the exact immutable page PNG. It exposes no PDF mutation action.

The workflow reuses the authoritative fixed-host capacity V4 and therefore serializes with customer
support on slot06; it adds no queue, slot, worker-to-worker channel, external LLM API, or PDF/PNG
database payload. Repository completion is not runtime activation: deployment, authenticated media
smoke, and one non-sensitive human visual canary remain separate gates.
