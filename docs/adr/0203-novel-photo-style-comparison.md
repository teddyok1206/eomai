# ADR 0203: Novel-photo style evaluation through existing image owners

## Status and observed gap

Source admission implemented and verified; paired consumer not implemented yet,
2026-10-05 UTC. No new photo conversion, GPU dispatch or activation claimed.
The thirteen native44 reserved pairs are source-initialized reconstructions of
already styled exam drawings. Their small BASE/LoRA differences do not demonstrate
novel drawing ability or photographic-reference conversion. Do not call them
freshly authored drawings. Preserve the existing result and its exhausted budget.

The approved visual-reference store already contains photographic morphology
references. Reuse those immutable revisions rather than downloading duplicates,
relabeling photos as exam crops, or widening TRAIN/VALIDATION/HOLDOUT authority.

## Required design procedure

1. Responsibility: a small preparation plan and metadata admission connect the
   existing licensed visual-reference source to the existing SDXL paired evaluator.
   This is not a second queue, training dataset, production provider or framework.
2. Canonical source: approved visual-reference bundle, exact original intent and
   normalized PNG; native reference1.2 and its complete native training closure.
3. Identity: content-addressed plan ID/hash, pinned Artifact Revisions and separate
   bundle logical/revision identities. Old schemas and results remain immutable.
4. Resolution: existing Orchestrator resolver checks approval/lifecycle, identity,
   schema/media/hash and bounded reads. Contracts check intent/candidate/license,
   bundle/member identities, chronology, dimensions, unique original sources and
   normalized hashes. The source-kind review is an operator assertion bound to the
   exact normalized hash, not proof that schema validation can recognize a photo.
5. Access patterns: bounded keyed metadata reads, source membership/deduplication,
   ordered case iteration, immutable plan. At most six cases/twelve proposed outputs.
6. Structures: frozen values, tuples and sets; existing indexed pointer lookups.
   O(metadata bytes + TRAIN targets + cases), no new persistent cache/index/DB.
7. Transaction/concurrency: preparation is read-only; future staging/dispatch/result
   commit reuse Orchestrator owners, GPU lease and immutable command replay. No
   GPU dispatch is authorized merely by a valid preparation plan.
8. Dependency: contracts own source identity/permission meaning; Orchestrator owns
   canonical reads/materialization. Provider will read staged files only. No worker
   NAS/DB/repository/auth access or worker-to-worker communication.
9. Failure: stale/denied/missing/corrupt metadata, foreign intent, another primary,
   duplicate original or training-image collision reject before PNG/weight reads.
   Never invent latest pointers or silently fall back to a micro adapter.
10. Retry/idempotency: metadata readmission is side-effect free. Future bounded run
    must freeze inputs/budget before submission, query unknown status under its same
    identity and preserve failed results. No automatic parameter or seed sweep.
11. Simpler alternative: feed photo bytes to reserved1.1. Insufficient: its source
    authority is institutional VALIDATION crops. Changing filenames would lie about
    provenance. Extend current configuration/staging/numerical/publishing owners
    instead of loosening that contract or building a parallel evaluator.

## Proposed bounded experiment and evaluation meaning

Use three visually inspected, canonically approved non-exam photographs if fit:
one car, one trilobite and one ammonite. These are previously used morphology
references, NOT an untouched HOLDOUT, institutional originals or new TRAIN data.
Existing sources may contain unsuitable background; record it before dispatch.

One BASE/native44 matched pair per photo, seed104729, exactly six proposed outputs.
Pin SDXL/VAE/controller/adapter/runtime through reference1.2. Proposed photo
initializer strength0.70, thirty scheduler steps/twenty-one effective steps,
existing832x512 grayscale fitted canvas. Both arms use identical settings; the
stronger conversion is intentional and must not be compared to the old strength0.35
experiment as if LoRA were the only difference. No training, HOLDOUT access, new
weights/dependency, production activation or automatic retry.

Score morphology/composition preservation separately from removal of photographic
texture, controlled stroke/gray fill and print usability. Display ORIGINAL PHOTO,
BASE CONVERSION and LORA CONVERSION explicitly. Pixel difference and loss are not
quality scores; a copied photograph is not successful line-art conversion.

The first three-photo diagnostic has insufficient family/population coverage for
the independent four-family/32-depiction acceptance. Own review never substitutes
for independent human blind review. Item Preview/HWPX and activation stay pending.

## Implementation order

1. JSON Schema2020-12 preparation plan, frozen typed values and licensed source
   admission; actual source readmission and own photo inspection.
2. Exact command/result successor, existing paired worker/backend/staging/publisher
   integration; tests including replay/failure/adapter/resource/provenance.
3. Source-free wheels and isolated role verification, then one preregistered bounded
   run. A preparation plan is not a dispatch command; current loaders must reject it.
4. Own output inspection, independent review when eligible, then conditional product
   canary/activation only after the full quality gate.

No claim of a new photograph conversion, LoRA advantage or production improvement
is made by step1 alone.

## Source implementation and actual photo inspection

JSON Schema2020-12 mirrored preparation plan1.0 has SHA
`5353213249c2dfecc4144e4e1e3f1e99dff96184a43f2aea422df275e23fcc24`.
Frozen models pin exact bundle/member/review/case/configuration, source-kind own
observation and initialization0.70. The plan explicitly is NOT a worker command;
the current numerical command loader rejects it. Full native configuration admission
is reused; licensed bundles/intents follow two bounded batched metadata reads before
any photograph/weight. Shared candidate-selection validation remains owned by the
existing visual-reference contract, not a duplicate rule in a new adapter.
Only the existing control-artifact publisher can commit a plan; source mismatch
is rejected. No new dependency, migration, queue/unit/privilege or runtime install.

Focused tests118 PASS/41.54s: new photo authority28, existing acquisition/coordinator,
native reserved, legacy reserved, test environment boundary and control publication.
They cover mirrored schema/hash, no dispatch/scope widening, exact member/revision,
normalized dimension, source review hash/UTC, seeds/initialization, noncanonical or
corrupt metadata, foreign intent/primary/license, duplicate original/training collision,
metadata-before-binary, admitted native closure reuse/read-only replay and publisher
source/hash binding. Missing/stale/permission failures are resolver-injected, not
substitutes for actual infrastructure/RBAC tests. Initial fixture default/hash/time,
loader invocation and one temporary syntax error were corrected before final PASS;
no model retry took place.

Actual approved bundle inventory found15 revisions, read-only metadata, binary0.
Three selected references were canonically re-admitted with their exact intent and
normalized PNG hashes before own inspection. They are source material, NOT generated
images. Automobile is a foreground right-facing station wagon with background cars,
trees/sky and ground texture. Trilobite is an enrolled side/oblique fossil, not an
unrolled dorsal anatomy illustration. The file titled `Gfp-large-fossilized-ammonite-shell`
visually shows clustered shells rather than the intended individual ammonite; reject
this candidate for morphology mismatch, preserving its canonical revision/history.

One existing CC0 alternate, `Polished fossil ammonite 06.jpg`, was readmitted/viewed:
a polished partial cross-section amid shop reflections/background, not a clean
isolated shell. Its suture/cross-section observation must not be generalized to a
complete external spiral. No fresh download, source cropping, dataset inclusion or
HOLDOUT access. A three-source diagnostic may explicitly retain these challenging
compositions but cannot be advertised as ideal isolated-object source quality.

## Canonical preparation checkpoint

Source10c309e5, frozen plan `imgsdxlphotoplan_a4344171f5d12cc2075313f8c8593670`,
semantic SHA `da7cd8a58c9cbd11079d7289fec724177ac28be1f5edd986a4ba8bb298f22a35`.
Canonical plan `artifact_80daa088a3a44325a55929fe8ea0b55b` /
`rev_64c4f5e26ee84d49ab3e10ad025708b2`, member
`manifests/sdxl-photo-style-plan.json`, byteSHA
`a4182e5997721fe8adb16c8b51bdd641b41a156973656a13446bb2036ba86173`.
Canonical metadata admission/re-admission equality PASS:71 metadata members,
full native44 closure,3 photo references. Binary-open guard confirms0 PNG/PDF/weight
opens during both metadata passes; prior own inspection separately read4 existing
PNGs. The registered plan was read back with identical bytes. No worker dispatch,
model/GPU call, new training, download or activation. Prospective comparison6 outputs
is not a produced result. Complete installed numerical successor, prompt-token
preflight and bounded paired result remain pending.

Ruff/format/diff PASS; strict mypy5 core files Python3.12 PASS and2 contracts using
the actual Python3.11 lab interpreter PASS. Including the schema registry in the
Python3.11 check found absent `types-jsonschema` in the numerical environment;
the registry passed strict checking in the explicit API/test environment. No runtime
dependency was installed to work around missing development stubs. Do not call this
an installed-runtime/wheel acceptance or visual-quality gate.

Canonical17-member text evidence `artifact_a957201a8d41434c994253890cf45c03` /
`rev_1010e8f789174105ac38c25403a15af9`, primary `reports/own-review.md`, SHA
`78d8489464e162bbefbb761f52bb65f42ffddf89db3908c9962257507e9d5cef`; all persisted
members reread equal. No duplicate source PNG/PDF/weight members. Source operators
and logs are explicit temporary materializations; current lab consumer remains
d1ba1151, production binding unchanged. The overall goal is still ACTIVE.
