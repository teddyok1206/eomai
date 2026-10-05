# ADR 0194: Native PDF source crops before style-target preparation

## Status and evidence

Accepted for protocol-first, CPU-only data preparation on 2026-10-04 UTC.
Execution/install and target/training approval remain separate gates.

The latest seven-target SDXL adapter still produced six rejected illustrations;
gray canvas and scientific/artifact issues remain. A separate read-only audit
re-admitted the actual seven TRAIN regions from six PDFs/six pages. Twelve isolated
Poppler renders at 144/288 dpi and six embedded-image inventories were completed.
All 144 dpi page pixels exactly equal their canonical discovery-page pixels.
Own native-size inspection shows materially clearer fan, plant and several person
contours at 288 dpi, while a roughly 150-ppi embedded drawing remains soft. Some
pages contain approximately 600-ppi or higher embedded illustrations. Higher dpi
does not guarantee new detail in every source and is not proof of LoRA quality.

## Responsibility and canonical source

Add a native-PDF crop preparation command/set1.0. Reuse the approved original PDF,
the pinned existing crop review1.0/1.1/1.2 and its literal144-dpi frame. Do not edit
their schemas, pixels, captions, partitions or target revisions. Native rendering
is a different operation from cropping an already-rendered144-dpi PNG, so it must
not silently inherit that operation's identity or acceptance.

The new command selects existing region logical IDs from one immutable review,
pins Poppler identity/Pillow version and a closed576-dpi recipe. A frame's pixel
coordinates are on the original144-dpi grid (half-point PDF units); native crop
coordinates are exactly four times those values. Default MediaBox/orientation and
Poppler antialiasing are preserved. Render only the selected rectangles, not huge
576-dpi whole pages. No raster enlargement, OCR mask, thresholding, tracing,
inpainting, repainting or invented detail is allowed in this source step.

## Identities, pointers and resolution

The command has its own content-derived logical ID/semantic hash and raw Artifact
Revision pointer. The set has its own logical ID, immutable revision and semantic
hash; its PNG members retain the original selection IDs. Different dpi does not
create an additional independent drawing/document. Source review, source PDF,
document/page, exam group, partition, caption and expression remain recoverable
through the pinned command/review, not duplicated into DB binary columns.

Metadata admission precedes any PDF read: exact schema/Pydantic/canonical bytes,
raw hash, permissions, lifecycle and pinned revision, complete original/supplemental
lineage, selected-ID membership, TRAIN inheritance, timestamp and concentration.
Unknown/missing/stale/conflicting pointers reject; no implicit latest fallback.
This first recipe is TRAIN-only, not permission to open reserved pixels for tuning.

## Structures, scale and concurrency

Use keyed selection/document/page/pointer maps and uniqueness sets; preserve a
sorted immutable selection/output tuple. At most32 selections per command, each
native dimension at most4096, aggregate output bounds explicit, PDFs resolved once
per unique document with existing128MiB bounded indexed batches. Admission is
O(D+P+S), spaceO(D+P+S); rendering is linear in selected raster pixels. Reuse the
existing source-lineage owner, exposing selected PDF metadata alongside its page
read model rather than repeating independent lineage logic or N+1 DB queries.

## Ownership, transaction and failure

Contracts own frozen values and domain invariants only. Orchestrator owns admission,
local materialization, isolated CPU dispatch, result validation and canonical
file-set publication. The existing image identity reads only staged local inputs;
Poppler/Pillow operate offline without model/GPU/NAS/DB/auth access. Infrastructure
owns process/filesystem behavior; workers never commit canonical files.

Reuse current command/result Artifact registration and deterministic idempotency
keys. A failed/uncertain render is not a successful set and must not be retried
under a new identity to bypass history. Keep intent/diagnostic evidence; resolve
an existing output before replay. No DB migration, queue, daemon/framework or new
dependency is introduced. Poppler and Pillow already belong to the CPU renderer;
their exact identities are pinned instead of acquiring a new toolkit.

The set state is RENDERED_SOURCE_DERIVATIVES_PENDING_TARGET_REVIEW. It does not
authorize model training, independent quality acceptance or production activation.
Annotational remnants, low-resolution originals and caption uncertainty require
their own target review; high dpi alone cannot upgrade them. Future full-resolution
target/training input semantics must be explicitly supported, not coerced into
the released768x512 micro contract. V6/previous LoRA/VALIDATION/HOLDOUT remain intact.

## Simpler alternatives

Upsampling existing144-dpi crops cannot recover the PDF's fine contours. Rendering
all pages at576dpi wastes memory/I/O and duplicates canonical full-page rasters.
Changing the old144-dpi crop policy retroactively breaks reproducibility. One
bounded native-region preparation boundary reuses current provenance/publication,
leaves previous evidence immutable and supplies better source pixels where the
original actually contains them. It does not replace diverse corpus expansion,
full training, four-arm/independent blind study or the Item/HWPX canary.

## Implementation checkpoint

Source preparation command/set schemas, frozen domain validation, canonical
review parsing and metadata-first native-PDF admission are implemented. Legacy
PNG and new PDF admission share one provenance resolver. Binary handoff rechecks
TRAIN membership, exact selection/PDF closure and byte bounds before any read.
The schemas are mirrored into the package and checked by both build inspectors.
Focused regression 269 PASS; strict mypy 5 source files and Ruff PASS.

The CPU audit actually ran at 144/288 dpi. The closed 576-dpi renderer, isolated
worker handoff and source-set publication have not been implemented or installed
at this checkpoint; no actual 576-dpi result or model-quality PASS is claimed.
The next implementation must test clipped render coordinates, rotated/fractional
pages, bounded output, renderer identity, exact result closure and replay before
dispatch. Full-resolution target/training semantics remain a further boundary.

On 2026-10-05 UTC, live metadata-only admission under source487a1364 accepted the
seven original TRAIN regions/six PDFs and froze one canonical command (no binary
source reads or576-dpi dispatch). Three candidate wheels built/inspected; wheel-only
schema/command import passed without repository sys.path or runtime installation.
Pointers and exact identities are recorded in the operations plan. This closes
the preparation/intention gate only, not the pending renderer/worker/target gates.

## CPU render handoff design

Use one closed render request/result value contract per unique PDF, reusing the
source's existing metadata and existing PNG member value. A request pins the
parent command logical ID/semantic hash, tool/Pillow identity and at most three
literal frames. Its content hash binds the result to the exact request; it is a
bounded value, not another registry/entity. The parent application constructs the
request from admitted provenance, checks PDF bytes once per source, invokes the
fixed CPU adapter and validates all returned members before set publication.

The installed image worker receives that small canonical request and PDF bytes
on stdin, checks the PDF SHA and sizes before Poppler, and returns a closed ZIP of
typed metadata and PNGs. No worker path, query, NAS resolution, queue or database
behavior is introduced. Clip coordinates are exactly four times the original
144-dpi grid. Each result binds the request hash, ordered selection IDs, native
dimensions and PNG hashes. This remains O(S + selected pixels), bounded by the
existing per-document concentration and batch pixel/byte limits. A transient
systemd sandbox uses the existing image identity, private network/devices/tmp,
read-only system, inaccessible secrets/NAS/source and bounded memory/tasks/time.
The orchestration adapter owns process/sandbox behavior; the worker owns only
offline rendering. Canonical file-set publication, unique commit/replay and
failed history remain with the existing Orchestrator publisher. An uncertain
process observation is not permission to redispatch. Tests separate mock/synthetic
process checks from opt-in installed-role sandbox execution and source-quality
inspection. No new dependency or persistent framework is needed.

Publication is keyed by the pinned command's semantic SHA, not the output's
timestamp-dependent identity. The existing unique job/commit boundary therefore
rejects a different delivery for the same command instead of creating duplicate
canonical sets. Request/output hashes, exclusive local workspace and read-only
canonical replay remain separate from that durable commit identity.

The expanded dependency audit also exposed an unchanged predecessor violation:
`source_page_crop_expansion_inputs.py` imports two pure planning interfaces from
`eom_catalog_service` (present at HEAD9239624b, last changed in400f1c09). The new
domain/worker/publication modules do not add that dependency. Do not hide it with
dynamic imports or weaken the repository-wide check. Extract the shared frozen
selection rule to an appropriate contract/domain owner in a separate focused
maintenance change; its current global audit failure is not a native-render PASS.

## Native worker source gate, 2026-10-05 UTC

The closed render request/result schemas were defined before worker behavior and
are mirrored/hashed in the release inspectors. The CPU worker, fixed transient
sandbox adapter, full PNG/ZIP validation, command-keyed canonical publication and
read-only replay are now implemented. Focused regression304 PASS (including two
opt-in real-Poppler synthetic rotated/fractional-page cases), strict mypy8 source
files, Ruff/format/bash syntax and diff checks PASS. The repository-wide dependency
audit remains5 PASS /1 unchanged predecessor violation; it is not suppressed or
reclassified. New native-source domain/worker/publication boundary tests PASS.

These source tests do not establish installed-role sandbox execution, actual
corpus576 output, training-target approval or model quality. The frozen seven-
region command remains the intended first bounded CPU application execution;
production V6 and reserved source partitions remain outside that installation
and render scope. No new model call, training or framework is required for it.

## Installed-role source execution, 2026-10-05 UTC

The lab-only contracts/CPU worker install from93b8361d and the frozen command's
actual576 execution passed. Six transient image-identity CPU requests rendered
seven source regions, committed one eight-member canonical set and passed read-
only replay. Original source PNGs/PDFs, numerical dependencies, inference provider,
production binding and permanent units/privileges remain unchanged. Separate own
native-size inspection and a15-member evidence archive record both contour gains
and persistent source-resolution/annotation/caption limitations. No target has
been automatically approved, old artifact revised, training run started or model
quality gate closed. Exact pointers and remaining work are in the operations plan.
