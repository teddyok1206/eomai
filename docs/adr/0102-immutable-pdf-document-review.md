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

### Transactions, concurrency, retry, and idempotency

Intake commits the PDF and derived page manifest atomically through the existing authoritative
Artifact owner. Review creation pins the committed intake revision and uses an actor-scoped
idempotency key. Concurrent identical submissions adopt the exact existing workflow; a reused key
with different source, preset, guidance hash, or permissions fails closed.

Existing atomic command claim, lease, workflow step-attempt, Job, Artifact Revision, and event
constraints remain authoritative. Retry preserves the exact document/preset/guidance identity.
Timeout does not authorize a new key or a duplicate review.

### Dependency direction and adapters

JSON Schema and frozen value models define the contract. Application services own intake/review
use cases, validation, idempotency, and transactions. PostgreSQL, NAS, PDF rendering, HTTP upload,
and Codex execution remain infrastructure adapters. Scientific Studio calls application endpoints;
it does not resolve NAS paths or implement review invariants.

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
- V1 requires an intake/render adapter and Studio overlay UI before it is live.
- Future textbook review may add Graph retrieval through a successor contract without changing V1
  history or weakening source-page identity.
