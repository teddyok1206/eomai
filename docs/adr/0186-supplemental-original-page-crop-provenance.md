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

TRAIN-only discovery and reviewed crop admission share this read-only lineage resolver. Discovery
does not fabricate a reviewed crop recipe or caption merely to read metadata. Crop admission adds
selection-specific checks after that shared boundary; neither path reads page pixels on metadata
failure. Its two real callers use the same completeness/authorization/selection rule.

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

## Actual validation checkpoint — 2026-10-04 UTC

All three extraction results subsequently committed 162 new PDFs / 737 pages / 1,536 detected
regions. TRAIN-only inspection covered 1,005 candidates / 360 unique original pages, followed by
95 context views and 72 provisional plus 72 corrected literal crops. Own screening corrected
49 frames and seven captions. Independent review and training admission remain separate.

At 08:33:56 UTC, the existing publisher committed a V1.1 review and a 73-member set (72 PNGs plus
manifest). Review `artifact_87740cab1a024143a78eab86f5537b5b` /
`rev_d1d74dc15c894636b43d58652f4f1055`; set `artifact_1629e2ef829f46b3b258ee97e429843e` /
`rev_bcab8901313a4d998fee64601eb06cfb`. Bounded canonical resolution reproduced the exact
own-inspected preflight bytes for every PNG. Existing 23 candidates were not changed; aggregate
95 candidates / 58 PDFs / 48 groups passed exact-ID/hash uniqueness, frozen TRAIN inheritance
and the existing concentration bounds. These counts are not approved training-target counts.

Latest combined applicable source suite is 174 PASS; corpus-contract regression is separately
59 PASS. No new DB/migration/dependency, worker privilege, production runtime activation or GPU
call. The existing CPU child uses pinned Pillow 11.3.0 and literal recipes only. Forty-two new
sources are ready for explicit target preparation with notes; thirty remain deliberate repair,
reference or native-drawing candidates. The old 16-source micro command is not reused with
invented sample IDs or implicitly replaced data.

Thirty-nine bounded metadata/log/operator evidence members, including invocation failures, are
archived at `artifact_5eb67225f2874fc890281b9fa650ddbb` /
`rev_6fc6f9f415734f2389cd5475c75f8227`; no duplicate PNG/PDF members. The operating V6 binding
remains unchanged and five production services were active. Full-data readiness INSUFFICIENT,
independent blind review NOT_PERFORMED, whole quality goal ACTIVE.
