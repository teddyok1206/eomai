# ADR 0097: Graph-grounded independent item review

## Status

Accepted for successor-contract implementation. Historical workflow, Content Pack, result-schema,
receipt, and production-plan revisions remain immutable.

## Context

The released `generic-item-development@1.10.0` review step receives the exact authoring Artifact and
the resolved Graph Evidence Bundle. `review-result@10.0` proves that the reviewer rechecked the
authoring citations, and the Orchestrator validates those citations against the immutable plan,
manifest, context, Graph snapshot, Artifact revision, and canonical draft leaves before commit.

That is a strong provenance boundary, but it does not retain enough information to distinguish a
substantive scientific review from a citation-integrity check. In particular, it does not require a
bounded independent answer, per-statement and per-choice diagnostics, explanation coverage,
curriculum-scope assessment, prior-item originality assessment, or visual/content consistency
assessment.

The retired EOMIS implementation obtained useful review performance by combining a direct solve,
deterministic answer/choice/statement checks, curriculum checks, source-variant checks, and a
production gate. EOM must preserve that useful decomposition without importing EOMIS, calling an
external LLM API, exposing hidden chain-of-thought, weakening the current Graph provenance model,
or letting a worker become an orchestration or persistence authority.

## Decision

Introduce a successor workflow-role family whose review result contains an
`independent_review_report`. The report is a bounded, auditable verification record, not a private
scratchpad or hidden reasoning transcript. It contains:

- an independently derived answer and an explicit comparison with the authored answer;
- short verification claims bound to canonical scalar leaves in the draft;
- exactly five choice diagnostics and, for statement-combination items, exactly three statement
  diagnostics;
- explanation, curriculum-scope, originality, and visual/content assessments;
- review-selected Graph evidence references for scientific validation, curriculum scope,
  originality, and visual validation; and
- deterministic blocking findings when a required assessment fails.

The reviewer still repeats the exact authoring citation set in the existing attestation shape. The
new review-selected evidence set is separate because it answers a different question: authoring
citations explain what influenced the draft, while review evidence explains what the reviewer used
to challenge the draft. The Orchestrator validates both sets against the same pinned manifest and
context before committing the review Artifact.

The successor uses new immutable identities:

- `workflow-role/1.23.0`;
- `authoring-result@11.0`, `image-result@11.0`, `review-result@11.0`, and
  `registration-result@11.0`;
- `evidence-usage-validation-receipt/2.0`;
- `generic-item-development@1.11.0`; and
- `generated-knowledge-item@1.17.0`.

Authoring, image, and registration V11 results are protocol wrappers around the V10 content
contracts. Review V11 is the only role with new product semantics. A successor Standard and
Graph-grounded preset pins the new role schema bundle and instructions. A future mock-exam
production-plan successor may pin the same workflow and pack; released V5 remains unchanged.

## Responsibility and boundary

- The Content Pack and reviewed role instruction define the reviewer task and output shape.
- The worker reads staged local instructions/evidence and writes only its local `result.json`.
- The Orchestrator validates result structure, exact upstream pointers, plan pins, draft paths,
  evidence identities/anchors/use, report consistency, and blocking-finding invariants before the
  sole Artifact commit.
- Catalog registration resolves the trusted authoring/review receipt chain and refuses a missing,
  stale, duplicate, or mismatched successor receipt.
- Human approval remains the publication decision. A model review cannot self-publish an Item.

No worker communicates with another worker or writes to NAS.

## Canonical source and pointer model

The canonical sources are the exact authoring Artifact Revision, its `AssessmentItemContentV3`
draft, the resolved execution plan, the Evidence Bundle manifest/context Artifact members, and the
pinned Graph snapshot. The review result points to the authoring Artifact and evidence entries; it
does not copy source documents or evidence bytes.

Logical Artifact ID, Artifact Revision ID, content hash, result schema, Evidence Bundle ID/revision,
retrieval request ID, Graph revision/hash, and receipt hash remain distinct. Resolution checks
existence, lifecycle, schema, media type, authorization, revision, and hash. No implicit latest
resolution is allowed.

## Access patterns and data structures

The dominant operations are bounded keyed lookup, membership validation, ordered diagnostics, and
append-only receipt history.

- manifest entries are indexed in an in-memory map by `evidence_id`;
- allowed anchors and cited paths use sets for membership and duplicate checks;
- choices and statements retain immutable authored order in tuples;
- finding codes and assessment keys use enums/literals rather than naming conventions; and
- persistent uniqueness and event ordering continue to use existing DB constraints and monotonic
  event sequences.

Validation is O(E + C + P), where E is at most 128 evidence entries, C is the bounded citation and
review-reference count, and P is the bounded number of draft pointers. Space is O(E + C). No new
database table, binary column, queue, cache, or index is required.

## Transaction, concurrency, retry, and idempotency

The new trusted review receipt is built before NAS commit and is stored in the same successful
Artifact transaction/event boundary already used by V10. A validation failure produces no canonical
Artifact. Idempotent replay must resolve the same worker input, authoring Artifact, plan, manifest,
Graph revision, result bytes, and receipt. A changed input conflicts; it is not silently retried with
a new identity.

## Fail-closed rules

At minimum, validation rejects:

- a derived answer inconsistent with the declared answer-alignment value;
- choice or statement diagnostics that do not exactly cover the canonical draft;
- a `PASS` assessment that has a blocking finding for the same axis, or a failed axis without its
  required stable blocking finding;
- missing or non-scalar/noncanonical draft pointers;
- unknown evidence or anchors, answer-bearing evidence used positively, or an evidence purpose
  incompatible with the manifest use;
- originality marked `DISTINCT` without a comparison reference;
- visual assessment marked `NOT_APPLICABLE` when the draft contains visuals, or vice versa;
- a review citation/authoring pointer differing from the exact authoring result; and
- a Graph-grounded successor result without exactly one trusted receipt.

For general-model-knowledge workflows, evidence fields are empty/null and no Graph claim may be
invented.

## Simpler alternatives considered

### Edit only the review prompt

This is insufficient because a worker can omit the direct solve or return a generic summary while
still satisfying `review-result@10.0`; no machine-verifiable record remains.

### Store a free-form reasoning transcript

This is rejected because it is difficult to validate, encourages hidden-chain-of-thought storage,
copies unnecessary text, and does not bind claims to canonical Item/evidence pointers.

### Reuse authoring citations as the only review evidence

This is insufficient because it proves that the reviewer repeated the authoring provenance, not that
the reviewer independently challenged scientific correctness or originality.

### Add a second worker-to-worker review channel

This violates the Orchestrator-only communication boundary and introduces avoidable state. All
handoff remains through immutable Artifacts and the workflow graph.

## Verification

JSON Schema 2020-12 is defined before behavior. Tests cover schema/Pydantic parity, exact coverage,
answer mismatch, statement/choice diagnostics, evidence purpose/use compatibility, unknown anchors,
answer-bearing evidence, stale authoring pointers, receipt self-hash, idempotent replay, historical
V10 byte immutability, package resource inclusion, dependency direction, and the absence of large
payloads in persistence.

Live activation is a separate bounded canary after source gates, release/bootstrap, and installed
wheel verification. The canary must stop before human approval until the independent review report
and trusted receipt are audited.
