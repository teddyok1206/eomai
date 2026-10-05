# ADR 0196: Native SDXL training admission and truthful composition conditioning

## Status

Contract and numerical-geometry source candidate verified, 2026-10-05 UTC.
Native sources/CPU target delivery already exist. The successor schemas and frozen
models, explicit native numerical adapter and geometry regression tests now exist.
Metadata-first multi-batch admission, isolated successor runner/entry point, installed
runtime and actual GPU execution remain pending. This is not an operational training
acceptance, model activation, released micro budget expansion or cohort approval.

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

## Closed source candidate and review — 2026-10-05 UTC

Independent command/result/adapter schemas are
`local-image-sdxl-native-lora-{command,result,adapter-manifest}/1.0`.
They are JSON Schema2020-12 with closed fields, packaged byte/hash equality and
frozen Pydantic models in `eom_image_contracts.sdxl_native_lora`.
Released micro schema bytes, run namespace, adapter identity derivation, canonical
adapter configuration and SSD checkpoint behavior remain unchanged. A shared
adapter-identity function reuses the existing rule without manifest-class aliasing.

| Declared profile | Samples | Optimizer steps | Meaning |
| --- | ---: | ---: | --- |
| NATIVE_RESOLUTION_PILOT | 12–64 | 20–200 | Numeric/runtime evidence only |
| FULL_STYLE_TRAINING | 100–200 | 200–1000 | Full TRAIN cohort, still evaluation-only |

Both profiles pin at most8 native1.2 target batches and allow only1024x1024,
768x1024 and1024x768 canvases. Admission declarations are sorted unique tuples;
sample ID, target ID and target PNG SHA cannot repeat. Global declared concentration
is at most3 sources/PDF and4/group. The subsequent resolver must still validate
those declarations against full frozen TRAIN lineage and physical-source variants.
The present types alone do **not** certify those claims by trusting supplied IDs.

Reviewed subject/expression/composition compiles a content-hashed final conditioning
caption. `ISOLATED_ON_WHITE` and `AUTHORED_SCENE` are explicit; no scene is silently
given a white-background instruction. The original target caption is not rewritten.
Review scope is own cohort screening, not independent blind quality approval.

The recipe remains fp16, UNet-only rank8/alpha8, frozen VAE/text encoders, AdamW8bit,
learning rate1e-4, batch1/accumulation4 and no random flips. Explicit terminal-only
checkpoint policy means no resume or intermediate checkpoint acceptance. Duration
is capped1h, declared peak GPU allocation16GiB and input PNG total128MiB. Actual
input-byte and resource checks still belong to the admission/runner boundaries.

The shared numerical owner now uses admitted per-sample tensor geometry and SDXL
time IDs, cached for at most four sizes including legacy768x512. It never resizes
native input. Native RGB enforcement is separate from legacy color conversion;
the micro wrapper explicitly rejects native canvases. Native and micro wrappers
remain distinct entry points over the same Diffusers numerical implementation.
No dependency, database, migration, queue, background service or production
configuration was added. No worker dispatch or GPU training was executed here.

Verification: focused regression368 PASS; strict mypy5 core files PASS;
Ruff/format/bash/diff PASS. Follow-up affected contract/backend tests are recorded
separately from that aggregate. Schema cases cover both profile bounds, canonical
identity/hash, scene captions, pointers, duplicate/concentration declarations,
exact terminal cohort/recipe/runtime, failed/cancelled evidence and no accepted
failure adapter. Numerical tests cover all three native canvases, exact tensor
reshape/time-ID values, RGB/geometry rejection, non-resume, shared configuration
and predecessor checkpoint behavior. These use synthetic/stub execution, not
actual SDXL GPU or visual-quality acceptance.

Repository architecture/release audit9 PASS /1 existing failure:
`source_page_crop_expansion_inputs.py` imports Catalog planning modules.
This pre-existing ownership issue remains explicit; neither its audit nor source
was weakened or hidden. Contract-to-runtime dependency and cycle tests PASS.

Next: implement metadata-first multi-batch admission and isolated terminal runner
over the existing owners, test frozen partition/physical-source duplicate checks,
then build/install/identity-verify before a frozen bounded GPU pilot. Evaluation
consumers must explicitly support the new adapter schema before comparison.
Full-data, four-arm, independent review, Item/HWPX and activation gates remain open.
