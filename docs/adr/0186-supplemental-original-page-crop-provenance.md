# ADR 0186: Supplemental original-page crop provenance

## Status and boundary

Accepted for bounded internal data preparation on 2026-10-04 UTC. The supplemental V1.3
discovery campaign is staged from 162 previously unselected PDFs / 737 pages, with the
original whole-corpus seed and partitions unchanged. Discovery is not illustration approval,
training, model activation, or independent visual acceptance.

Orchestrator owns metadata resolution, local materialization and immutable publication. A
fixed CPU adapter crops the reviewed rectangle; it does not mask, redraw, resize or access
models. Contracts own frozen review/selection/output invariants, and Catalog owns deterministic
source selection. Workers receive no NAS, DB, network or orchestration permission.

## Canonical source and identities

Keep the original approved corpus, authorization, complete predecessor plans and literal page
Artifacts canonical. Add review/set V1.1 only for supplemental plan/result pointers. Do not add
new candidates to an old inventory or fabricate old candidate IDs. Review V1.0 and its published
bytes remain valid and strict. Both versions reuse the same selected-rectangle identity, corrected
caption content, expression classification and literal CPU processing.

The new review pins its original authorization/basis plus the complete supplemental plan/result
pairs. Logical crop identity remains page revision + rectangle; caption corrections do not count
as independent drawings. Review hash, set logical/revision IDs, raw member SHA and Artifact
Revisions remain separate. A crop-set successor is required because its review schema changes;
the crop PNG schema and general dataset split contract need not change.

## Resolution and data flow

Admit the existing full basis first. Batch-resolve the supplemental plans/results and the same
whole-corpus metadata through indexed immutable pointer resolution. Validate schema/media/member,
canonical bytes/raw SHA, full shard coverage, original authorization, seed, predecessor pointers,
source selection, chronology, result closure and document/hash/group partition consistency before
reading page pixels. Reuse Catalog's authoritative selection function. Missing/stale/conflicting
or rehashed-but-false lineage fails explicitly; do not resolve latest or substitute an old page.

Every reviewed selection must match its candidate, page, PDF, dimensions, DPI and frozen partition,
and intersect the candidate it declares. Reuse one selection-lineage check for V1.0 and V1.1.
Group selected rectangles by unique page pointer and reuse the existing bounded page resolver
(64 pages / 128 MiB per batch). Publish one intent Artifact then one literal crop-set file set.
The main author inspects TRAIN pixels only; deterministic data preparation for reserved sources
is not a blind human review or permission to tune from reserved pixels.

## Structures, scale and concurrency

Dominant operations are key lookup, set uniqueness, ordered immutable snapshots and append-only
history. Maps index sources/pages/candidates, sets enforce identity/hash/partition uniqueness,
tuples preserve shard and output order. Metadata admission is O(n log n + p + c), with n at most
5,000 corpus documents, at most four pilots, 1,536 pages and 2,048 candidates; memory is bounded
metadata, followed by one bounded page batch. Selection remains the existing deterministic
whole-corpus algorithm. No new DB table/index, queue, cache, dependency, daemon or plugin framework.

Existing Artifact publisher transactions/idempotency own commits. A fresh exclusive workspace
owns processing; replay does not create another independent sample. Failure preserves intent and
local evidence, publishes no successful set, and requires inspection before retry. Existing source
crops, unsuccessful model outputs and accepted product history are never rewritten or deleted.

## Dependency direction and simpler alternative

Contracts import no adapters; the Orchestrator application composes existing Catalog selection
and pointer adapters. The publisher selects one of two closed protocol specifications rather
than duplicating business rules or adding version flags to each layer. Fixed CPU processing and
PNG publication stay shared. Broad inventory, suitability, worker, GPU and training protocol
successors are unnecessary for this boundary. Silently passing new selections through V1.0
would falsely claim provenance from its old 108-source inventory, so a small explicit successor
is the simpler correct alternative.

## Required verification and rollback

Test canonical/packaged JSON Schema 2020-12, frozen typed models, old-byte preservation, duplicate
and missing pilots, mixed campaigns, authorization/seed/predecessor/hash/chronology mismatch,
wrong selection source/partition/rectangle, zero PNG reads before failed metadata admission,
bounded grouped page reads, literal output coverage, publication closure and exact idempotent
replay. Verify no domain-to-infrastructure imports or generated binaries in DB/Git. Rollback
stops the supplemental worker or withdraws the experimental candidate, not historical data.

At this ADR's creation extraction is in progress; V1.1 live publication and corrected-data
training/independent evaluation are not yet claimed PASS.
