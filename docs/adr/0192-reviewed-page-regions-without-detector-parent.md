# ADR 0192: Reviewed original-page regions without a detector parent

## Status and observed evidence

Accepted for CPU-only corpus/evaluation preparation on 2026-10-04 UTC. Production
image policy, model activation and training are not changed by this decision.

The admitted metadata inventory contains 270 uniquely pinned source PDFs with frozen
180 TRAIN / 45 VALIDATION / 45 HOLDOUT membership. A bounded inspection staged 20
VALIDATION pages from 20 documents/exam groups, with no HOLDOUT binary reads. Direct
page inspection found people, cars, a cityscape and a bag that do not intersect any
automatically discovered candidate rectangle on their own pages. The first crop
preflight rejected this condition before creating its workspace or processing pixels.
This is detector recall, not permission to invent a candidate or weaken released V1/V2.

## Responsibility, source and identities

Add crop review/set `1.2` (V3). A `REVIEWED_ORIGINAL_PAGE` selection pins the approved
PDF, original page Artifact Revision/member/hash, document/page number, dimensions,
literal pixel rectangle, original exam group/partition and reviewed caption hash.
It has no candidate ID/hash: a detector is a discovery aid, not the canonical original
page. Existing V1/V2 schemas, candidate intersection checks and published bytes remain
unchanged. Selection logical identity continues to bind the same page pointer/frame;
a new anchor policy or caption does not invent an independent illustration.

Complete original and, when present, supplemental lineage must be admitted through
existing Orchestrator resolvers before PNG reads. V3 permits original-only or an
explicit complete supplemental campaign of 2–4 shards, together with original lineage.
No new corpus, queue, database schema, worker protocol, dependency or daemon is added.

## Data structure, scale and resolution

Use document/PDF-hash/exam-partition maps, a `(document, page)` index and pointer identity
sets. Reject repeated documents/pages, mismatched page/PDF/partition/dimensions, unknown
pages, conflicting immutable pointers and newer source receipts. Lookup is O(D + P + S),
space O(D + P), with at most 512 selections, three per document/four per exam group and
at most eight admitted pilot shards. Unique page reads retain the existing 128 MiB
batch bound. Crop runtime is linear in selected pixels; no additional model inference.

Shared region/pointer/frame rules remain authoritative for V1/V2/V3. Candidate-specific
admission remains V1/V2-only. Reviewed regions are not automatically eligible training
targets or blind-quality acceptance. VALIDATION/HOLDOUT stay in their original partitions;
photographic texture and exact scientific diagrams are not relabelled as object line art.

## Ownership, transactions and failure

Contracts own frozen values/invariants and import no storage or subprocess modules.
Orchestrator application adapters admit/materialize; the existing fixed CPU worker
receives only page bytes and literal rectangles, never NAS/DB/auth access. Existing
publisher commits reviewed intent and the validated PNG/manifest closure with pinned
source commit and idempotency keys. PNGs/logs remain Artifact data, not Git payloads.

No OCR masks, resize, thresholding, contour repair or guessed labels are introduced.
Missing/stale/hash/schema/media/lifecycle errors reject rather than resolve latest.
Partial execution leaves intent/failure evidence, not a successful crop set. Same intent
and deterministic bytes retain publisher replay semantics; changed content conflicts.
Independent style review, a bounded generation successor and production canary remain
separate gates. A literal reconstruction of an existing exam drawing cannot prove new
photo/sketch conversion, LoRA style learning or institution-indistinguishable quality.

## Simpler alternative

Restricting crops to intersecting detector rectangles discards visible approved material.
Enlarging a rectangle just to touch a remote candidate corrupts provenance and includes
unrelated text. Relaxing V1/V2 reinterprets released history. One explicit page-region
successor reuses current lineage, crop processing, publication and split ownership.

## Source verification

Focused original/supplemental/region crop, source-target, reviewed training/evaluation,
split and dependency regression: 190 PASS, one explicitly deselected existing test
`test_domain_and_platform_packages_do_not_import_catalog_infrastructure`. Running it
still reports the unchanged Catalog infrastructure imports in
`source_page_crop_expansion_inputs.py`; this is not hidden or represented as fixed.
The full invocation before correct deselection recorded 190 PASS / that one failure.
Strict mypy passes five changed source files, Ruff and shell syntax/diff checks pass.
The new tests include source VAL/HOLD preservation, metadata-only admission, missing/
stale/hash refusal, direct CPU pixel equality without Torch, explicit anchor rejection,
duplicate/page indexes, mixed complete lineage and the existing publication receiver.
Wheel/runtime execution and own actual-crop visual disposition are separate evidence.
