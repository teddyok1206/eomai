# ADR 0196: Native SDXL training admission and truthful composition conditioning

## Status

Proposed implementation design, 2026-10-05 UTC. Native sources/CPU target delivery
already exist; this successor training protocol, worker and GPU execution do not.
It does not activate a model, expand a released micro budget or approve a cohort.

## Evidence and protected boundary

The latest delivery added19 original TRAIN regions and three prepared native
targets. Coverage is46 native selection IDs /30 PDFs /29 groups; prepared native
candidates are23 /16 PDFs /15 groups. The union with earlier38 candidates is42
source identities, not an accepted population of independent drawings.
Evidence: `artifact_c62690ea1adb42af8e3f3dcf7f4c7862` /
`rev_261f871024b545ecbe3111ba01a7cdf8`, `reports/own-review.md`, raw SHA
`7e2d1c6d6f29be67393e1e22079364579269b658a2902a2b32366894001bfc6d`.

Direct native review found unsupported pocket/driver descriptions and a scene
background incompatible with released `plain white background` conditioning.
Only the new derived captions were corrected; historical sources remain immutable.
The scene remains a reference, not a wrongly captioned white-background target.
Existing native20 scene captions therefore also require explicit training admission,
not automatic pooling. This is a data/conditioning defect hypothesis, not proof
that it explains every earlier rejected GPU result.

Released micro1.0/1.1 remains fixed768x512/200 steps and its established sample
bounds. Native target1.2 is candidate preparation, not final training approval.
Do not route1024-sized assets through the old alias or reshape them back silently.

## Responsibility and canonical source

A successor native-training application owns cohort admission, reviewed training
conditioning and the explicit numerical recipe. CPU preparation continues owning
literal pixels/geometry and initial candidate captions. A reviewed final training
caption is a pinned derivative, not an edit of the source or prepared candidate.
Use this boundary rather than adding another image-normalization implementation.

Canonical inputs are immutable native target-result revisions and their PNG
members, plus their complete target-command/native-set/native-command/source-review/
authorization lineage. Source PDFs/annotations/old targets/weights remain intact.
Only Orchestrator registers validated local output; workers never write NAS/DB.

## Entity model and pointer resolution

Define JSON Schema2020-12 before worker behavior, followed by frozen Pydantic
command/result/adapter-manifest models and equivalent validation tests. Use a new
native-training run namespace, content-derived command identity and independent
adapter logical ID/revision/hash. Do not reinterpret a released micro receipt.

Pin each target batch's command/result/schema/media/raw SHA and each selected
target ID/revision/PNG hash. Review pins include literal subject, expression,
composition and resulting training-caption hash. Composition distinguishes an
isolated object on white from an authored scene; scene conditioning must not
append a false white-background instruction. No automatic image-based guess,
OCR cleanup, anatomical correction or label fabrication is introduced here.

Before PNG/model reads, resolve all metadata and check canonical bytes, raw and
semantic hashes, exact member/schema/media, lifecycle/access, chronology, target
recipe/geometry, same authorization, frozen TRAIN document/group membership,
exact selected coverage and duplication. Missing/stale/unknown fails explicitly.
Never substitute latest or read VALIDATION/HOLDOUT pixels as training inputs.
Refinement/caption/DPI variants of one source do not create independent examples.

## Access patterns, structures and scale

Frequent operations are pinned key lookup, membership/deduplication, stable
iteration, immutable history and exclusive GPU/workspace claim. Use indexed
bounded artifact resolution; cache immutable parsed metadata by full pointer
within one admission call, maps for source/target lookup, sets for uniqueness,
and sorted tuples for the admitted cohort/output manifest. No new registry/queue/DB.

Target composition must admit multiple distinct native batches without assuming
one common source-set identity. Validate concentration and source-variant reuse
across the whole cohort, not separately inside each batch. The eventual100–200
TRAIN population,24–40 VALIDATION and32 independent blind cases remain goal gates.
Any smaller numerical pilot is separately labeled and bounded, never counted as
full-data or publishing acceptance. Exact command budgets/caps must be closed in
the schema before an actual GPU submission, not inferred from this proposal.

Metadata is O(N+M), with N selected samples and M unique pinned metadata members;
pixel staging/training is bounded by admitted bytes/pixels/steps. Use one explicit
local worker materialization boundary, not copies in service messages or DB rows.
PNG/tensor memory and declared per-run budgets must be validated before dispatch.

## Numerical ownership and dependency direction

Reuse the existing Diffusers UNet-LoRA numerical adapter, frozen text encoders/VAE,
pinned local SDXL/VAE manifests, dependency/version checks and shared GPU lock.
Extend its immutable tensor-sample value with explicit admitted geometry. Per-sample
VAE tensor shape and SDXL time IDs must match that geometry. Legacy samples retain
their exact default768x512 behavior and numerical/checkpoint tests.

Keep contracts/pure cohort rules free of filesystem/Torch/SQLAlchemy. Orchestrator
owns resolution/staging/dispatch/commit; the isolated worker validates staged
metadata and performs local numeric work only. A closed successor entry point may
reuse the established sandbox/workspace infrastructure; do not build a parallel
training framework or import Catalog infrastructure into domain rules. No new
dependency is justified by this design; production inference remains unchanged.

## Transaction, failure, retry and replay

Reuse exclusive command-keyed workspace creation, explicit staged-input closure,
shared exclusive GPU lock, resource limit checks, terminal result receipts and
the existing unique idempotent artifact publisher. Resolve completed state before
redispatch. Terminal replay verifies identities/outputs without training, tensor
creation, PNG rewriting or new publication identity. Unreceipted output/unknown
processing blocks retry rather than inventing a new run. Preserve FAILED history.

Training output remains evaluation-only. A new adapter manifest must have explicit
consumer compatibility; the old comparison/provider must not accept a new manifest
by a loose alias. Extend the appropriate closed comparison contract before using
that artifact for four-arm evaluation. Rollback concerns lab/runtime selection,
not deletion of accepted source history or production model replacement.

## Implementation order and exit evidence

1. Closed schemas/Pydantic/pure cohort-caption/geometry rules and predecessor
   compatibility tests; no worker invocation until those agree.
2. Metadata-first multi-batch input owner and isolated worker/backend extension;
   focused tests, Ruff/format, strict mypy and dependency audit.
3. Build/RECORD/import tests in the actual lab identity; bounded CPU/preflight and
   read-only replay. Freeze the real selected cohort/recipe before one GPU pilot.
4. Actual bounded training and canonical result/adapter verification; report loss,
   duration and resource use as numerical evidence, never quality approval.
5. Compatible identical-input BASE/T2I/LoRA/combined comparison; independent blind
   review, then only a passing Item Preview/HWPX canary and reversible activation.

Test complete metadata-before-media closure, missing/stale/hash/schema/media
errors, TRAIN-only admission, concentration/duplicates/variant reuse, canonical
captions/semantic hashes, all three native canvases, exact SDXL time IDs, bounded
reads/GPU claims, failed receipts, no-write replay and installed package isolation.
Preserve prior test failures as failures; no dynamic-import audit evasion.

## Simpler alternative

Increasing old micro limits or resizing every target to768x512 is smaller code but
silently changes released semantics and defeats native geometry. Editing historic
caption bytes breaks provenance; stripping every background/annotation damages
useful reference data. One explicit training-admission successor over existing
owners is the smaller maintainable solution. Do not pre-build a generic bucketing,
plugin, distributed queue or experiment platform for this work.
