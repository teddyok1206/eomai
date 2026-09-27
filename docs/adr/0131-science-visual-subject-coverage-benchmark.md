# ADR 0131: Science visual subject inventory and coverage benchmark

## Status

Accepted for protocol-first implementation on 2026-09-27 UTC. This decision does not authorize
production adapter activation.

## Context and responsibility

The science visual campaign already has two different, immutable views of the approved material:

- 520 occurrence-backed accepted past-exam analyses containing 537 visual-pattern observations;
- 768 rendered visual candidates classified by structural pattern family and rendering route.

Those views answer *where the visual came from* and *how it is structurally rendered*. They do not
provide a stable subject index for questions such as "have cars, beakers, fossils, cells, and
orbital scenes all been exercised?" `APPARATUS` and `OTHER` are intentionally too broad to answer
that question. This ADR adds an additive subject inventory and benchmark protocol. It does not
rewrite the accepted analyses, the 768-candidate inventory, the training crop set, or the completed
LoRA run.

The Orchestrator owns source resolution, inventory publication, staging, result validation, and NAS
commit. The isolated image worker may read staged adapter/model inputs and write bounded local
outputs. It does not query PostgreSQL, read NAS, communicate with another worker, or activate an
adapter.

## Canonical source and revision model

The canonical source is the exact accepted analysis target set pinned by its training-authorization
revision, plus the exact 768-candidate visual-pattern inventory revision. A subject inventory is a
new immutable Artifact Revision. Each subject entry points back to one or more exact legacy visual
observations through:

```text
Item Revision
  -> accepted knowledge-analysis result
  -> legacy extraction Artifact Revision
  -> item proposal + visual pattern + source anchor IDs
  -> subject inventory entry
```

The inventory stores bounded labels, aliases, route decisions, and hashes of the two source
descriptions. It does not copy source pages, complete items, analysis results, or image bytes.
Benchmark plans, commands, and results pin the inventory Artifact Revision. They never resolve an
implicit latest inventory or adapter.

## Subject routes

- `LORA_RASTER`: non-authoritative natural texture or realistic non-human subject for which the
  adapter may improve the raster layer.
- `PYTHON_SVG`: authoritative geometry, apparatus, labels, axes, circuits, human figures, and other
  content that must remain deterministic and editable.
- `HYBRID`: a non-authoritative raster layer plus authoritative Python/SVG overlay.
- `BLOCKED`: no production render is permitted under the current policy. This is reserved for
  inputs that cannot be represented safely by an allowed route; human figures themselves are not
  blocked because an anonymous deterministic SVG route exists.

GPU human-subject prompts are represented as negative-control cases with the expected outcome
`POLICY_REJECTED`. They are not quality-generation cases. A successful human raster generation is
a failure.

## Primary access patterns and data structures

The dominant operations are subject-key lookup, source-observation membership, deduplication, and
stable ordered iteration. The publisher builds maps keyed by subject key and source observation ID,
and sets for aliases and references. It then emits sorted frozen tuples. For `V` source visual
observations, `S` subjects, and `R` references, construction and validation are `O(V + S + R)` time
and `O(V + S + R)` memory. Expected scale is fewer than 1,024 observations and fewer than 256
subjects, so the immutable JSON Artifact is sufficient; a new database table or index is not
justified.

Benchmark cases are keyed by case ID and subject ID. Output lookup is a map keyed by
`(case_id, variant)`, preventing repeated scans and enforcing exact cardinality. Ordered output is a
tuple sorted by case ID and variant.

## Transaction, concurrency, retry, and idempotency

Inventory and benchmark publication use the existing Orchestrator Artifact transaction. A semantic
self-hash and a stable idempotency key make byte-identical replay return the same published result;
different content under the same key fails closed. Workers receive one immutable command in a local
workspace. A retry reuses the same command and seeds and must produce the same declared output set;
it does not invent new subject or output identities.

The first pass uses exactly one fixed seed for each raster-generating subject. Additional seeds are
allowed only in a successor plan for cases whose first result exposes variance or a defect. This
keeps GPU work bounded while giving every inventoried subject an explicit outcome.

## Validation and activation gate

JSON Schema 2020-12 is authoritative at the wire boundary and Pydantic models enforce semantic
invariants:

- every eligible visual observation is covered once or has one explicit omission;
- subject keys, aliases, source references, cases, and outputs are sorted and unique;
- every source reference binds exact Item/extraction/pattern/anchor identities and description
  hashes;
- route-specific fields are closed (`LORA_RASTER` needs raster prompts, `PYTHON_SVG` needs a
  primitive, `HYBRID` needs both, `BLOCKED` needs a reason);
- GPU output is forbidden for deterministic, blocked, and policy-rejection cases;
- raster-generating cases have exactly `BASE` and `ADAPTER` outputs with the same seed and prompt;
- hashes, dimensions, media types, model revision, adapter revision, and inventory revision match
  the staged command.

Representative `LORA_RASTER`, `PYTHON_SVG`, and `HYBRID` cases proceed through the existing image
composition and HWPX path only after the subject benchmark is valid. This is a compatibility test,
not a reason to generate an HWPX per subject.

No benchmark result activates the adapter. Activation still requires a successor provider-binding
contract, a bounded live canary, and an atomic rollback to the current base-only binding.

## Failure behavior

Missing or stale pointers, schema/media/hash mismatch, uncovered observations, duplicate subjects,
wrong routes, unexpected output variants, human raster generation, or output-set mismatch fail
closed with stable errors. The Orchestrator preserves failed attempts and never substitutes latest
revisions. Existing training/evaluation history remains unchanged.

## Simpler alternative rejected

A hand-written list of nouns with unpinned sample prompts would be smaller, but it could not prove
that the list came from the accepted 520-item corpus, would omit multi-subject observations, and
would drift independently of the 768-candidate inventory. Reusing structural pattern families alone
would also leave `APPARATUS` and `OTHER` semantically opaque. The additive pointer-bound inventory
is the smallest design that gives complete, reproducible subject coverage without a new database or
workflow framework.
