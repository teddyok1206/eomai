# ADR 0055: Graph-grounded evidence usage attestation

Status: Proposed

## Responsibility and boundary

The workflow protocol records a bounded, machine-checkable claim that a content-team authoring
worker used the exact Evidence Bundle staged for its workflow. The worker reads only job-local
`references/evidence/context.md` and `references/evidence/manifest.json`; it never resolves Catalog,
database, or NAS state. The orchestrator remains the authority that resolves the immutable plan,
materializes verified bytes, validates the returned claim, and commits an Artifact. The review
worker independently checks the same citations and returns a typed attestation before human review.

## Canonical source and revision model

Catalog's published Evidence Bundle manifest is canonical. A resolved execution plan pins the
logical Evidence Bundle ID, immutable Evidence Bundle revision ID, retrieval request ID and hash,
Graph Snapshot revision and hash, manifest Artifact member and hash, and context Artifact member and
hash. A worker result is a small immutable value that cites those pins; it is not a new copy of the
manifest and does not become a competing source of truth.

The semantic `manifest_sha256` (the canonical manifest-body self-hash pinned as
`evidence_manifest_sha256` by the plan) is distinct from the manifest Artifact member's `sha256`
(the hash of the stored full member bytes). Worker evidence usage carries the semantic hash and
context member hash exposed by the staged manifest. The orchestrator's typed validation receipt
carries the exact manifest pointer (including its member-byte hash) and both values without
conflating them.

The relationship is:

```text
Evidence Bundle logical ID -> immutable Evidence Bundle revision
                           -> manifest Artifact revision + manifest hash
                           -> context Artifact revision + context hash
                           -> selected evidence IDs -> selected anchor IDs
authoring result revision  -> evidence-usage value + draft JSON paths
review result revision     -> exact citation-set attestation
job success event          -> typed validation receipt + canonical citation-set hash
```

Logical IDs, revision IDs, Artifact IDs, Artifact revision IDs, and SHA-256 hashes remain separate.

## Pointer resolution and failure rules

Before worker execution, the orchestrator resolves the plan's manifest and context pointers and
validates existence, approval/lifecycle state, authorization, schema reference, media type, canonical
storage location, byte count, SHA-256, manifest self-hash, and exact agreement with every plan pin.
It stages the already validated manifest and context as read-only job-local files. Every value the
worker must attest is present in the manifest. The orchestrator's validation receipt binds the result
to the remaining exact resolved-plan identity and immutable Artifact pointers.

Manifest staging is gated to the exact `generic-item-development/1.10.0` workflow identity. Older
resolved-plan V3 executions retain their historical context-only workspace, member count, byte
accounting, and event semantics. The trusted validator still re-resolves canonical manifest bytes at
the orchestrator boundary; it never broadens an older worker's staged inputs.

Before authoring Artifact commit, the orchestrator requires Graph-grounded output to contain the
exact bundle logical/revision IDs, semantic manifest hash, retrieval request ID, Graph Snapshot
revision ID, and context Artifact member hash exposed by the manifest. The validation receipt binds
these claims to the resolved plan ID/hash, retrieval request hash, Graph Snapshot hash, and exact
manifest/context Artifact member pointers.
Every cited evidence ID must exist in the pinned manifest and every cited anchor ID must be a
nonempty subset of that entry's anchors. Citation application is closed by the manifest entry's
declared use: `GROUNDING -> CONCEPT_GROUNDING`, `REFERENCE_PATTERN -> STRUCTURE_PATTERN`, and
`AVOID_COPY -> AVOID_COPY_CHECK`. Answer-bearing entries may only be used for
`AVOID_COPY_CHECK`, which cannot support an answer or other positive draft claim. At least one
positive `CONCEPT_GROUNDING` or `STRUCTURE_PATTERN` citation is required. The generic protocol does
not require a particular source class such as `PAST_EXAM`.

Draft locations are RFC 6901 JSON Pointers relative to the authored draft. The empty/root pointer is
forbidden. Each pointer is canonically escaped, arrays use canonical decimal indices without leading
zeroes, and every segment must resolve to a scalar leaf. Every citation application is limited to
worker-authored semantic roots: `stem`, `bottom_stem`, `labeled_blocks`, `statements`, `choices`,
`inquiry`, `visuals`, `answer`, or `explanations`. Administrative, provenance, and derived fields
such as `schema_version`, `item_number`, `score_display`, renderer/prompt/archive hashes,
`visual_layout`, and `equation_sources` cannot satisfy an evidence citation. Evidence IDs, anchor
IDs, citations, and draft pointers are
nonempty, sorted, and unique. Missing, unknown, duplicate, unordered, stale, unresolved, or
mismatched values fail closed. An ungrounded plan/output must carry no evidence usage.

Before review Artifact commit, the orchestrator resolves the exact authoring upstream Artifact,
repeats the plan/manifest checks, and requires the review attestation to pin its logical Artifact ID,
Artifact revision ID, content hash, and exact citations. It rejects a missing or different citation
set. Workers never submit or calculate a digest, and the orchestrator never repairs worker citation
content. Instead, it derives the canonical authoring and review citation-set hashes and persists a
typed, self-hashed validation receipt in the same transaction that records Artifact success. No
implicit latest revision or best-effort substitution is allowed.

The receipt has discriminated authoring/review shapes. Authoring carries its result pointer once;
review additionally pins the upstream authoring pointer and both equal citation-set hashes. Its
`receipt_sha256` is `content_sha256` over the canonical compact UTF-8 JSON object with sorted keys
and `receipt_sha256` omitted. A supplied digest is compared, never repaired.

## Access patterns and data structures

The dominant operations are immutable ordered iteration, key lookup, membership, and deduplication.
Validation builds one `dict[evidence_id, manifest_entry]` and one `set[anchor_id]` per used entry,
then walks citations once. Canonical tuples preserve stable output ordering; sets detect duplicate
IDs and paths. With `E` manifest entries and `U` used anchors/paths, validation is `O(E + U)` time and
`O(E + U)` transient memory. Evidence Bundles are bounded at 128 entries, so no persistent index or
database migration is required.

## Transaction, concurrency, and idempotency

Materialization uses the immutable plan and approved Artifact revisions in a read transaction.
Result validation happens before the existing Artifact commit boundary. The validated result is
committed using the existing job/revision transaction and content-addressed manifest flow. A replay
with the same workflow-step idempotency key resolves the same job and immutable plan; canonical
serialization produces the same evidence-usage/citation hash. A conflicting result or plan pin is
rejected, never merged.

## Dependency direction and ownership

JSON Schema 2020-12 and frozen Pydantic value models live in the workflow contracts package. The
workflow application/orchestrator owns plan-aware validation. Filesystem/NAS resolution remains in
the infrastructure materializer. Content Pack and control-preset instructions tell workers what to
read and return, but contain no validation business rules. Workers return structured results and do
not orchestrate, persist, communicate with other workers, or write to NAS.

## Versioning

Existing `workflow-role/1.19.0` and `authoring-result@9.0` bytes remain immutable. New
`workflow-role/1.20.0` role schemas use `authoring-result@10.0`, `image-result@10.0`,
`review-result@10.0`, and `registration-result@10.0`. A new workflow definition, generated content
pack revision, standard control bootstrap revision, and knowledge-grounded preset revision opt in as
one admitted family. Historical families remain readable without reinterpretation.

## Failure, retry, and observability

Schema failures, plan/manifest mismatches, unknown evidence or anchors, unresolved draft paths, and
review disagreement use stable fail-closed worker-result errors before Artifact commit. They do not
trigger an automatic semantic retry or silently strip citations. Existing job events retain only
bounded pointer/hash metadata; prompts, evidence text, and complete result content are not logged.

## Simpler alternative considered

Checking only that `context.md` was materialized proves availability, not consumption. Asking for a
boolean such as `used_rag=true` is self-asserted and cannot be reconciled to immutable evidence.
Recording only evidence IDs cannot prove which source anchors influenced which draft locations, and
review cannot independently compare the use. The selected typed citations are the smallest honest
contract that binds exact plan/context/manifest identity to nonempty evidence anchors and concrete
draft paths without copying source content or adding persistence.
