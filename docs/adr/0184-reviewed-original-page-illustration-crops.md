# ADR 0184: Recover reviewed illustrations from immutable original pages

## Status and observed defect

Accepted for CPU-only, evaluation-data implementation on 2026-10-04 UTC. This is not a model
activation or a training approval. Original TRAIN pages were resolved through the Orchestrator
and visually compared with all sixteen micro-training inputs. The original telescope was captioned
as a microscope; a cold pack was captioned as a protective glove; an electrolysis crucible/power
supply was captioned as a flask/delivery tube. Automatic OCR rectangles in the earlier discovery
pipeline can erase object contours. Original page PNGs are separately preserved and undamaged.

## Responsibility and canonical source

An additive reviewed source-page crop manifest selects literal, text-free rectangles in those
original published page PNGs. It does not repair an old candidate, revise its suitability decision,
or replace its bytes. The existing crop-set lineage admits the approved corpus, campaign plans,
results and original partitions. A selection pins its parent candidate hash, exact page Artifact
Revision/member/hash, PDF pointer, page dimensions, exam group and reviewed morphology caption.
It may extend outside the discovered candidate box to recover a complete object on the same page.
That choice is explicit in the new review, not a change to the old candidate-crop semantics.

The Orchestrator alone resolves and publishes. The existing deterministic trainer crop adapter
processes staged bytes in a CPU-only subprocess with no database, NAS or GPU access. It makes
literal rectangular crops: no OCR masking, thresholding, resize, interpolation, inpainting,
contour reconstruction or inferred labels. Later training normalization remains a separate,
versioned boundary. Labels, axes and authoritative scientific geometry stay Python/SVG/native.

## Identity, pointers and compatibility

```text
approved original crop-set lineage / immutable campaign pages
  -> new reviewed page-coordinate selections and corrected captions
  -> new crop-set Artifact Revision with literal PNG members
  -> existing document/duplicate-group split
  -> separately pinned future training/evaluation command
```

Crop logical identity binds document, page revision/hash and pixel rectangle. Caption/expression
changes produce new review/crop-set revision content, not fabricated new source diversity. The
crop-set logical ID binds ordered selection IDs; its revision ID and semantic hash are distinct
from PNG hashes and the committed primary file's raw SHA. Generic PNG members retain the existing
`local-image-science-visual-crop/1.0` media contract so the existing style split can reference them
without a parallel split framework. Both new JSON Schema 2020-12 metadata families are additive.
Original pilot, crop-set, training, target-preparation and failure records stay immutable.

## Access, scale and complexity

At most 512 selections per revision, three per document and four per exam group. Candidate/page
lookup uses maps; exact duplicates and group membership use sets/counters. Ordered wire members
are immutable tuples. Admission is O(C + P + S) for campaign candidates/pages/selections. Only
selected unique pages are materialized, in batches bounded by 128 MiB. Literal crop work is linear
in selected pixels. Existing Artifact indexed resolution, file-set publication and idempotency
locks suffice: no database schema, queue, cache, new daemon or dependency.

Partition must equal the original PDF/exam group. TRAIN recovery never consumes VALIDATION/HOLDOUT
pixels. Recovered old drawings are not counted as new independent documents. Exact PNG duplicates
are rejected. Perceptual hashes are carried for the existing reviewed duplicate-group/split step,
not represented as a scientific guarantee of nonduplication.

## Transactions, retries and failure

Admit all metadata before any PNG reads. Resolve existence, lifecycle, schema, media, member,
revision, byte count and hash through existing public adapters. Decode PNG with bounded pixels;
validate actual dimensions against the pinned page; reject out-of-bounds/empty crops. Materialize
only at the input/workspace boundary and commit manifest+PNG closure atomically with the existing
Orchestrator publisher. Same review and deterministic output replay with the same identity/key;
drift conflicts. Partial work is not a successful crop set. Do not replace missing sources with
latest, move partitions, promote a worker receipt to quality approval, or retry a failed GPU cohort.

## Simpler alternative

Enlarging old masked candidates cannot recover missing pixels or correct wrong captions. Changing
the released pilot's automatic-redaction policy or existing crop-set bytes would reinterpret
history. A narrow reviewed literal-page derivative reuses the original page storage, CPU crop
processing, Orchestrator publisher and split; another extraction framework or GPU repair model is
unnecessary.
