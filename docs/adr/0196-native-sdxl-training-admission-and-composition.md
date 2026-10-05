# ADR 0196: Native SDXL training admission and truthful composition conditioning

## Status

Metadata admission, isolated native lab runtime, real cohort admission and the first
200-step native GPU pilot verified, 2026-10-05 UTC.
Native sources/CPU target delivery already exist. The successor schemas, frozen
models, numerical adapter, complete multi-batch admission, local terminal runner and
explicit CLI/systemd handoff now exist. The native lab contracts/trainer are installed
and the actual worker identity imports them successfully. The23-source/16-PDF/15-group
cohort passed full canonical admission; actual GPU training completed200/200 steps
in476,581ms. Installed-role no-model/no-write terminal replay and canonical four-member
result publication passed. Visual quality and compatible comparison consumers remain
pending. This is numerical pilot acceptance, not full training or model activation.

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

## Multi-batch admission implementation design — 2026-10-05 UTC

The contract package owns pure metadata decoding, explicit target→native-set→
native-command→source-review dependencies and cohort/recipe binding. The Orchestrator
owns bounded canonical reads and the existing complete source-provenance resolver;
the worker reads only the resulting closed local workspace. No new persistent
entity, database column, queue, generic graph framework or dependency is needed.

One metadata member path derives from the **whole pinned pointer**, not just its
location or raw hash. A per-call map caches parsed metadata and payload by that
pointer; a second keyed map rejects conflicting declarations for the same artifact/
revision/member. Shared authorization, reviews and native sets are materialized
once. A typed dependency frontier requires only metadata; selected PNG reads occur
after every batch and distinct review passes. Internal file maps are bounded by
2MiB/member and32MiB total; the admitted PNG budget remains the command's limit.
These are workspace materialization limits, not a new cross-service JSON protocol.

Different native source sets/reviews are supported, but their approved frozen basis
pointer must agree. This pins the existing document/group split without confusing
that common historical basis with one common native target source-set identity.
Full canonical provenance is resolved once per distinct review before media.
Every selected target binds exact ID/revision/hash/canvas, declared PDF/group and
prepared expression; final subject/composition remain explicit reviewed derivatives.

Global physical-source guard keys PDF SHA and physical page, then compares frames
within the already bounded3-source/PDF bucket. Equal/contained frames (intersection
at least80% of the smaller frame) cannot become separate examples by caption, DPI,
canvas or review revision. Disjoint actual drawings inside one detector candidate
remain permissible; candidate ID alone is not physical drawing identity. This is a
bounded source-variant guard, **not proof of semantic/perceptual independence**.
PDF aliases/conflicting source pointers or IDs fail explicitly. Complexity is
O(N+M): frame comparisons are constant per admitted PDF, not an unbounded N² scan.

Replay requires the same command, metadata closure and hashes; no latest lookup or
recovery is invented. Rejected metadata/lineage consumes zero PDF/page/target PNG
bytes and cannot dispatch a worker. Prepared input is a temporary materialization,
not canonical publication. The simpler per-batch-only check is insufficient because
it admits cross-batch variants and repeated source concentration.

## Source implementation verification — 2026-10-05 04:38 UTC

The pure metadata owner now caches the complete pinned closure and validates all
native batches before selected PNG reads. The Orchestrator reuses one admitted
frozen basis and complete canonical lineage per distinct review. A different native
set is permitted; a changed frozen basis or physical-source variant is not. Final
training conditioning is an explicit derivative; candidate captions are unchanged.
No original/VALIDATION/HOLDOUT PDF/page bytes or model weights are needed to reject
invalid metadata. Synthetic tests prove one decode per unique pointer and one root
lineage resolution; these are boundary/complexity evidence, not semantic uniqueness.

The local successor runner validates staged metadata, fixed input inventories,
actual PNG hash/size/RGB/native canvas and final conditioning before model work. It
never writes transformed training PNGs. It shares the numerical backend, GPU lock,
adapter output validation and protected workspace handoff with existing owners.
`sdxl-native-lora` and `eom-image-sdxl-native-lora@.service` are explicit lab entry
points, not aliases for micro1.0/1.1. Their source definition does not install/start
a service. The metadata-only operator preflight is labeled
`PREFLIGHT_METADATA_PASS`; it cannot claim pixel or GPU validation.

Terminal success requires the complete requested cohort/steps, exact dependencies,
bounded duration/memory and validated evaluation-only adapter. FAILED/CANCELLED
receipts cannot carry an accepted manifest. Nonfinite loss cannot corrupt JSON
receipts. Replay checks pinned inputs/output identity but performs no PNG decode,
model resolution, training, output rewrite or new identity. Unreceipted partial
output blocks resubmission. Existing result/adapter schema bytes are unchanged.

Verification: focused source regression442 PASS; final affected runner/handoff
rerun44 PASS after two additional boundary cases (overlapping evidence, not486
distinct tests). Strict mypy11 core/CLI files PASS; Ruff/format14 files,
`systemd-analyze verify`, bash syntax and diff whitespace checks PASS.
Architecture/release9 PASS /1 unchanged Catalog planning-owner dependency failure.
That failure remains explicit and was neither hidden nor weakened. Initial runner
test failures and fixture corrections preceded the recorded final passes.

These are source/stub tests, not installed worker-role/GPU/visual-quality acceptance.
At04:38 UTC the five main production services were active; GPU usage2MiB/0%.
No model/dependency/runtime installation, unit activation, production config change,
training, artifact publication or reserved binary read occurred in this checkpoint.
Next: immutable build/RECORD/non-source Python3.11 checks, supported lab install and
actual source/cohort preflight before one bounded pilot. The eventual100–200 TRAIN,
24–40 VALIDATION, four-arm/four-family comparison,32 independent blind cases and
passing Item/HWPX canary/activation/rollback remain open. Goal ACTIVE.

## Immutable build and actual lab install — 2026-10-05 04:46 UTC

Source`ba13157c39f1a6b8c3c69664c4f6fa678bcf9892` was committed with a clean tree.
Its immutable archive built all three wheels with complete schema/module inventory.
Wheel SHA/RECORD and source-free Python3.11.15 simulation passed. New native metadata,
runner/adapter-output and old/new CLI imports use wheel bytes, not repository source;
offline schema validation imports no Torch or SQLAlchemy and reads no PNG/model.

Only lab contracts and trainer were installed:

| Component | Raw wheel SHA-256 | Installed |
| --- | --- | --- |
| contracts | `d1e3ff29afd0ef1c90fb20f3060a8fe2f39ffc6456be6ae24aad80b30071d78a` | yes, lab only |
| trainer | `f46fd33dc699a06ce81915f32f738415cf36bc578470e014ab44696d62d733b9` | yes, lab only |
| provider candidate | `c273655093baf6e717636dac7f2cd637ee708df76d3b628c395acc70ec649b7a` | no |

The install held the existing GPU lock and required no active image execution.
Existing installed wheel bytes and available rollback wheels were verified before
replacement. Actual `eom-image` identity import, installed RECORD and `pip check`
PASS. Numerical dependencies, existing provider/micro template, production binding
and all five service states were unchanged. No worker received sudo/groups/auth.
The new native template was installed/verified but not started/enabled; no polkit
rule or production service changed and no restart/model/PNG/GPU/training occurred.
This is installed role/import evidence, **not actual sandbox or numerical acceptance**.

Build directory:
`/tmp/eom-image-trainer-build/ba13157c39f1a6b8c3c69664c4f6fa678bcf9892.UFhPZS/dist`.
Private operators/evidence:
`/tmp/eom-native-lora-admission-wheel-verify-20261005.py` and
`/tmp/eom-native-lora-admission-install-20261005.{py,log}`.
Previous contracts/trainer wheels remain available in the03a542f build directory
listed by the install receipt. Rollback restores those exact wheels after stopping
any new lab execution; the previous native template was absent. No source data,
training result or old adapter is deleted or rewritten by that rollback.

Next: freeze the actually inspected pilot's final captions/composition and exact
native target pointers, resolve full canonical metadata before staging, then run
one bounded native GPU pilot. The current23 prepared candidates are not the eventual
100–200 TRAIN cohort or independent quality acceptance. Four-arm consumers must
explicitly support the new adapter schema before evaluation. All full-data,
VALIDATION, independent blind review, Item/HWPX and activation/rollback gates remain
open. Goal ACTIVE; this turn is concrete implementation/build/install progress.
