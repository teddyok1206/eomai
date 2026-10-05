# ADR 0203: Novel-photo style evaluation through existing image owners

## Status and observed gap

Current checkpoint2026-10-05 UTC: the photo consumer and white-initializer1.1
successor are implemented, lab-installed and numerically tested. Both controlled
photo conversions remain **NOT_ACCEPTED** for exam illustration quality. White
initialization produces unreadably faint marks. Current six-output budget is
exhausted; the next task is CPU-only coarse-control diagnosis, not another GPU
dispatch or activation. Detailed chronological evidence follows.

Initial preparation checkpoint (historical):
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

### Execution transport and shared implementation boundary

The execution command pins the registered preparation plan by logical plan ID,
semantic hash and exact Artifact member byte hash. Do not copy the plan's cases or
binary payloads into every command. A new small command/result family identifies
PHOTO_TO_EXAM_STYLE, not institutional VALIDATION. Its run ID uses the existing
paired unit's bounded `imgsdxlvalcmprun_` namespace; no new unit, queue or privileges.
Command source may succeed the frozen plan source; timestamps cannot precede it.

One common staged reference-metadata reader supplies the existing reserved consumer
and the new photo consumer. It reads complete native metadata before pixels/weights.
Share source initialization, paired inference, selected-adapter and pixel evidence
validation through current owners, while keeping institutional crop authority and
licensed photo authority separate. Do not implement photographic inputs by pretending
they are twelve reserved crops or silently accepting unsupported schemas.

Result pins command/plan/configuration/native evaluation/adapter semantic hashes,
exact ordered case/arm/seed prefix, initializer/control hashes and measured resource
usage. SUCCESS requires all two-arm outputs; failures preserve a valid prefix and
never become success on replay. Replay validates existing evidence without new
models/GPU/transforms/writes. CPU publication verification still recomputes pinned
transforms under the installed numerical runtime; source bytes and weights are not
copied into result Artifacts. Existing Orchestrator ownership, physical GPU lease,
read-only resolution, staging and commit idempotency remain unchanged.

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

## Photo execution consumer — source gates, 2026-10-05

Mirrored JSON Schema2020-12 command1.0 SHA
`281f56f8e3e9c18299c815b48b8f444c0b770138a159e0556109ae7b14231322`
and result1.0 SHA
`80d8cab8d0f0fe7959a0c262c4b5806529e223f1ef91b64d750d59474f10dee6`
precede the frozen Pydantic execution consumer. A small command pins the registered
plan revision/byte hash and plan logical identity/semantic hash, not another copy
of its cases. The original preparation plan bytes/hash remain unchanged.

Canonical metadata admission completes before bounded photograph/selected native
adapter reads. The staged handoff reparses the exact native metadata closure and
photo bundles/intents rather than trusting an injected derived DTO. The worker
checks the same native44 authority and selected adapter. Common metadata and
initializer/Canny evidence are shared with the existing reserved consumer; its
source authority and frozen initialization0.35 remain separate from photo0.70.
Paired inference, physical GPU lock, closed ordered failed-prefix results, CPU-only
read-only transform verification and existing Artifact publisher are reused.
No new queue, unit, privilege, dependency, production binding or activation policy.

Final source regression231 PASS/122.45s: photo execution34, photo authority28,
native/legacy reserved contract and worker, reference1.0/1.1/1.2 and test-environment
boundaries. New cases exercise registered plan identity, canonical/native source
closure, exact selected weights, bounded existing handoff, successful/failed-prefix
execution, zero-side-effect terminal replay, input/result/derived pixel tampering,
partial-workspace refusal and source-free publication after canonical readmission.
Initial invocation/fixture errors, an overbroad native metadata parse and a missing
test import were fixed before final PASS; no GPU dispatch/model retry occurred.
Ruff/format/diff and shell syntax PASS. Strict mypy15 source files/Python3.12 PASS,
3 contracts using the actual lab Python3.11 PASS. A broader Python3.11 provider
check lacks the existing jsonschema development stub; no numerical dependency
was installed to conceal that environment limitation.

Real protected-stack/tokenizer preflight for the original three-source plan PASS:
both pinned CLIP tokenizers report positive lengths61/68/67 and negative37 against
limit77. No prompt truncation or successor-plan mutation is necessary. Protected
model file hashes were checked, but no tensor/pipeline/GPU was loaded. One initial
read-only operator used a nonexistent tokenizer role; corrected BASE subdirectories
passed. Installed wheel/role/RECORD verification and the one six-output comparison
are still pending at this source checkpoint; this is not image-quality acceptance.

## Installed six-output photo diagnostic — 18:49 UTC

Consumer source `1a98a93acfd579eccc0d4c3571b080783427c1ce`; inspected wheel
contracts SHA `8b464b38f0824edc80d878cf58b279b62bfec94b014c5e670efccb3fb4a48044`,
provider SHA `aa3ea3cb522e64f0f2ba4669b494464546b326346d1a57340c24a8e68c529079`.
Lab-only install/RECORD/actual eom-image role/source-free import/pip check PASS.
Trainer, numeric dependencies, units, production binding and five services unchanged;
previous d1ba1151 wheels and hashes recorded for rollback.

Canonical thin command `artifact_7b0d9fab09554325a300ba311d63d788` /
`rev_4cd99a958af64be7adf5243424471253`; one dispatch
`imgsdxlvalcmprun_4faff836c8c5520b25711385c0a38777`,77 staged members,
3 licensed photographs/6 BASE-LORA conversions,30 scheduled/21 effective steps,
strength0.70/seed104729. SUCCEEDED/30897ms/10763099136 peak bytes. Result
`artifact_958c360472614301819c38d62f962a1b` /
`rev_801925edecfb474c8b6eb48d08c1fa31`,19 members; committed reread equality PASS.
Primary result byteSHA `3701e1e0b40d1db4362e18500c9028c5051e44171b7251ca8c540e36f09c69fd`.
CPU-only installed transform verification PASS; terminal replay96 unchanged files,
model/GPU/transform/write0 (read-only image validation still decodes PNGs). Current
six-output generation budget exhausted; no retry, training, HOLDOUT or activation.

Own actual contact/individual panel/native-wagon inspection:
**EXAM_LINE_ART_TARGET_NOT_MET**, not institutional quality PASS. Both arms remain
near monochrome photographs, with photographic texture/background/shadow. LoRA
trilobite adds faint repeated diagonal/grid-like background patterns. Partial shop
ammonite framing remains partial/cluttered. This is a genuine conversion diagnostic,
not drawings from scratch; SOURCE_PHOTO / BASE_PHOTO_CONVERSION / LORA_PHOTO_CONVERSION
labels must remain explicit. No independent review or morphology certification.

Confirmed prompt mismatch: native training captions prepend the existing shared
`eom exam line art, ` phrase; this frozen plan used generic exam wording instead.
Causality is not isolated. Next bounded hypothesis is a **new plan identity/value**
in the same plan1.0 contract using the exact phrase, preserving this run/plan and
checking tokens before any new budget/dispatch. Do not reject historical generic
plans by retrofitting a new contract invariant. Dense Canny/photo initialization,
mixed tonal training targets and challenging source backgrounds are other hypotheses;
investigate independently before coarser-control recipe changes or larger training.
Technical gates PASS, style quality NOT_ACCEPTED, independent review NOT_PERFORMED,
four-family/32-case and Item Preview/HWPX/activation gates OPEN; goal ACTIVE.

Canonical25-member diagnostic evidence `artifact_9f1a3714c3324d70967c2d3c57c1c1f5` /
`rev_3909b2b06c2e4278b2e204beee679e43`, primary `reports/own-review.md`, SHA
`2fdf02b28aceb672bba0badf03642bf6996bd97cc7e0c1c4fdd21460fda2962b`;
all persisted evidence bytes reread equal. Includes one derived SOURCE_PHOTO/BASE/LORA
contact sheet, measured reports, source tests and initial failure logs, pinned install/
submit/publish/replay operators. No duplicate canonical source PNG/PDF/adapter bytes.
Initial evidence packaging rejected group-writable temporary logs before any commit;
only these exact task-local log permissions were tightened, and the failure was
preserved. It did not cause another model invocation or change an acceptance result.
Milestone Slack IN_PROGRESS sent HTTP200 as
`devreport_0d31edfa650f4b0782a3887c56a955dd`; quality shortfall and next bounded
hypothesis reported explicitly, not a whole-goal completion.

## Next bounded comparison: exact learned phrase, unchanged recipe

The next experiment changes only each positive prompt by prepending the existing
native caption phrase, using a new immutable plan value within plan1.0. It does not
change plan1.0 semantics or make generic historical plans invalid. Preserve the
old command/result and exhausted budget. Pin the same configuration1.2, licensed
photo revisions/review, negative text, seed104729, native44 adapter, strength0.70,
30 scheduled/21 effective steps and numeric runtime. Case IDs/prompts/hashes and
plan/command IDs change as required by content identity; compare by depiction key
and immutable reference hash, not by matching those newly derived IDs.

Budget: at most one separately identified dispatch, six outputs total (BASE/LORA
for the same three sources), no automatic retry, no sweep, no training/HOLDOUT,
no production change. Both CLIP tokenizers must accept the complete prompts before
command submission. Canonical plan/source readmission, installed code/dependency
identity, fixed worker/unit, source-free publication and read-only terminal replay
remain mandatory. A failed operator before submission is not a generation retry;
an unknown dispatched outcome must be observed using its existing unit, not resubmitted.

Primary judgment remains actual white-paper examination line art, not small pixel
differences or an edge score. Retain labelled SOURCE_PHOTO/GENERIC_BASE/GENERIC_LORA/
EXACT_PHRASE_BASE/EXACT_PHRASE_LORA views, declaring photo initialization. Analyze
BASE effects separately from LoRA effects: a generic-vs-prefix difference alone is
not proof of learned-adapter improvement. A positive result on these three difficult
references is still not independent blind review, untouched HOLDOUT, four-family/
32-case acceptance or readiness for Item/HWPX/production activation.

## Exact training phrase experiment — 2026-10-05 UTC

Plan value `imgsdxlphotoplan_b36592cfbc036e9a6d192bf08ed951e1`, registered as
`artifact_574b209143ff4931b3b2ef7b99341790` /
`rev_ea3c05508b8d495eaf6150b206045b93`. Existing contracts/provider consumer
`1a98a93a` RECORD and numeric dependencies reverified read-only; intervening source
`c8022341` changes are documentation-only on affected code paths. No reinstall.
Both pinned tokenizers accept positive67/74/73, negative37, limit77.

One six-output dispatch `imgsdxlvalcmprun_77d84cf2b76ea3c5008f88111b7a61d2`:
SUCCEEDED/31038ms/10763099136 peak bytes. Result
`artifact_8807bea31cea42fb8d965b788341faf9` /
`rev_4a9e18ce8a9c4128818cda85a6f91d09`,19 committed members reread equal,
primary byteSHA `06e909b8835c49baef46427aefe067ce73365679e91076ecdc79faae69f89f85`.
CPU transform proof and installed terminal replay PASS/96 unchanged files;
replay model/GPU/transform/write0, read-only PNG validation still decodes pixels.
Current budget exhausted, no training/HOLDOUT/sweep/retry/activation.

Registered generic/prefix plans/results and15 photo/output members re-resolved.
Depiction/source hash mapping preserves order independently of new case IDs;
all three conditioning and initializer RGB hashes are exactly equal. New labelled
five-column views distinguish source photograph from all four model conversions.
Actual contact, individual trilobite and native wagon own review:
**EXAM_LINE_ART_TARGET_NOT_MET**3/3. Photo texture, broad shadow/tones and scene
clutter remain; a different background texture is not examination-style success.
Exact-vs-generic grayscale MAE BASE/LORA: trilobite4.30/5.19, wagon7.57/6.24,
ammonite2.80/3.45 on0–255. BASE also changes. Pixel differences are not learned-
style proof; **the exact phrase alone is insufficient under this frozen recipe**,
not proof that the adapter learned nothing or one exclusive failure cause.

One early publication invocation rejected an activating unit before Artifact
mutation; same handle subsequently terminal, then publication PASS. One display
comparison invocation lacked source PYTHONPATH and failed on import before writes;
corrected invocation PASS. Preserve these logs, not extra generation. Existing
231 source-test PASS remains applicable to unchanged code; operators Ruff/format
PASS. Independent review/full32-case/four-family/Item/HWPX gates stay OPEN;
production binding and dependencies unchanged, goal ACTIVE.

Canonical21-member diagnostic evidence `artifact_9a8aec9cede041e5a85f2534e980675d` /
`rev_fb9c85b0aa164613967f7d1f75e05391`, primary `reports/own-review.md`, SHA
`c2b35c9eabcba9ebe7a0a39d2c8c3c63bcc3be3d164f93a94b64e3f40cfcde1c`;
all persisted evidence reread equal. Includes measured matched comparison, one
derived five-column contact sheet, frozen budget and failed invocation logs;
no duplicate canonical photographs/weights/output binaries. Initial packaging
rejected the group-writable temporary review file before Artifact mutation;
only that exact file was tightened to0600 and the failure log retained.
Postflight: five primary services active, numeric dependencies unchanged,
production binding SHA unchanged, fixed unit inactive/dead/success, GPU idle.

### Next recipe decision: separate shape guidance from photographic tone

The current pixel owner fits a grayscale photograph for both Canny construction
and img2img initialization. The backend explicitly sends that RGB initializer
and separate control image. Source inspection establishes this coupling, not
its exclusive causal responsibility for the observed failure.

1. Boundary: extend the existing photo comparison contracts/pixel owner/backend/
   publication verifier; no parallel worker, queue, API, registry or framework.
2. Canonical source: same licensed photo/manifest/source-review revisions, native44
   adapter/configuration and exact-phrase plan/result; no new training images.
3. Identity: preserve all released1.0 bytes/meaning. An explicit successor recipe
   uses constant-white832×512 RGB initialization, not a photo-derived grayscale
   initializer falsely retaining the previous policy name. New plan/command/result
   revisions pin it; source/case/artifact/revision/SHA remain distinct.
4. Resolution: same schema/media/lifecycle/permission/hash/source-authority and
   TRAIN collision checks before bytes; exact initializer/control byte closure.
5. Access: bounded metadata batches, keyed case/arm/trace lookup, sorted frozen
   output, exclusive claim/terminal replay. No DB/query/index change.
6. Structures: frozen typed recipe/commands/results, discriminated contract family,
   existing maps/sets and GPU inode lock. No new persistent derived cache.
7. Complexity: O(total source pixels) Canny and constant O(832×512) initializer;
   three sources, one separately bounded six-output BASE/LORA diagnostic.
8. Concurrency: current Orchestrator commit/dispatch and physical lease; source-free
   worker, one identity/maxdispatch1, automatic retry/sweep0, activation FORBIDDEN.
9. Dependency direction: contracts define recipe; existing provider owns pixels/
   inference, Orchestrator stages/publishes. Reuse current numeric libraries.
10. Failure: missing scientific detail in inspected conditioning stops before GPU;
    white initializer proof/resource/closure/hash errors fail closed. Preserve
    failed history, observe ambiguous unit, replay without models/transforms/writes.
11. Simpler alternative: more prompt text already failed to produce line art.
    This one initializer-factor comparison retains prompt/negative/seed/Canny/
    control/steps/strength/adapter and tests whether tone transmission is material.
    Changing control detail and training simultaneously would confound that test.

This recipe is **not implemented/dispatched at this checkpoint**. Define successor
JSON Schema2020-12 before models/worker behavior, verify exact CPU transforms and
installed replay, then inspect the same Canny inputs before one GPU dispatch.
No generated-output whitening is permitted as a substitute for learned style.
If white initialization fails, preserve/report it before a separate coarse-contour
or style-data-balance decision; no automatic parameter search. Independent review
and full institution-style acceptance remain necessary for any activation.

## Constant-white initializer successor: source implementation checkpoint

Plan/command/result1.1 are now schema-first successors; the existing1.0 resources
and meanings are unchanged. New schemas reference unchanged predecessor fields
rather than cloning their large case/pointer contracts. White recipe has the same
strength0.70/30 scheduled/21 effective steps/Pillow11.3.0; only initializer policy
is `CONSTANT_WHITE_RGB_832X512/1.0`. Frozen Pydantic subclasses share the original
authority/identity/result rules. Closed version selection rejects mismatched
plan/command/result recipes, unsupported versions and invented fallback.

Existing pixel preparation now accepts the pinned initializer value: source canvas
still constructs identical Canny, while the successor supplies constant-white RGB
to the existing img2img backend. The historical default remains photo grayscale.
Initializer RGB SHA `2a1305062f642d1db1cc642ac56bd73710d20fa355a02cd84f31a90d23d4e106`
is required by both schema and result model; exact PNG/decoded RGB checks reinforce
it. CPU publication recomputes the same authoritative initializer function. Terminal
replay remains transform/model/GPU/write-free; nonwhite pixels/rehashed declarations
fail without another dispatch. Current staging, metadata/source admission, physical
lease, Artifact publisher, CLI/unit and numerical dependencies are reused.

Source gates:294 tests PASS/142.14s, including white success/failed prefixes,
constant pixels, version mismatch, cross-version pointers, closed recipe,
publication canonical/CPU/input negatives and historical photo/native/reserved
regressions. Initial focused test83 PASS/1 fixture directory collision; corrected
test uses separate old/white workspaces and final regression PASS. Ruff/format,
diff checks and both build-script syntax PASS. Strict changed-file mypy8/Python3.12
and2 contracts/Python3.11 PASS with unchanged imports followed silently. The broad
transitive run reports existing Pillow typing errors in unmodified
reference_simplification.py; initial API-interpreter invocation also lacked image
dependency stubs. No runtime dependency was added or unrelated source patched to
conceal those separate environment/baseline limitations.

New schema byteSHA plan `b5b504723e19eea420a1746cf4bcc2b14e507361597fd55fcfcbd76cab4746dc`,
command `f074df3113830a01ad91a3bb8f8b1d3ffcc257075548168117a9c5ae4c1f8cda`,
result `975413abde12fffcaba0a833db49137422dba4f4bc85b4f42dde4c9cc8035bab`.
Wheel resource gates require these explicit successors alongside all predecessors.
Installed lab verification, canonical successor plan, real conditioner inspection
and one separately bounded six-output diagnostic remain pending here. No new
training/HOLDOUT or quality/independent-review/activation acceptance is claimed.

## Constant-white1.1: installed execution and actual quality finding

Source/lab contracts-provider `1083fd4ec12c7cdf5e7b06f6abdf507a3feda589`.
Wheel RECORD, actual eom-image role import, installed dependencies/PIP check and
white RGB/old-schema checks PASS. Numeric dependencies, trainer, fixed units,
production binding and five main services unchanged; no restart. Previous
`1a98a93a` contracts/provider wheels retained as the bounded lab rollback set.

Canonical plan `artifact_67d57fbfb6164d4ebd11a720e4900657` /
`rev_708bba95bed24e27a967a3b5c3159f9d`, byteSHA
`e2837aac9421380790af8d41ced85d3bd483dff5702d5e1ba153094bbeeb5959`.
Same exact-phrase source/prompt/negative/config/runtime permits reuse of the
previous real two-tokenizer capacity proof; this is not a fresh token test.
71 metadata members readmitted before binary materialization;77 staged members.
Actual CPU view: same dense three Canny inputs, all-white832x512 initializer;
input proof is not final scientific/quality acceptance.

One six-output dispatch `imgsdxlvalcmprun_607c6537880956e3d373d53d9b24a85d`,
SUCCEEDED/33201ms/10763099136 peak GPU bytes. Actual unit journal completes at
2026-10-05T19:36:42.178902Z. A later unloaded systemd instance returns start
timestamp0; never interpret that alone as "not executed" and resubmit.
Canonical19-member result `artifact_4d4fe245f6e446bf919d1e6270de0a90` /
`rev_f0abb0af3d66476588b92b55c90a19d1`, primary byteSHA
`03bce93f5386784d27ca55fa6e6122c8bb7edbe38a5aa3a4cedf1bd8059ea0f9`.
CPU transform proof/committed reread equality PASS. Installed terminal replay
PASS/96 unchanged files, model/GPU/transforms/writes0. Previous generic and
exact-phrase terminal receipts also replay unchanged under the new consumer.

Both plans/results and15 canonical photo/output members re-resolved. Positive/
negative/config/runtime/seed unchanged, control hashes equal3/3, initializer
hashes different3/3. Viewed all six outputs, matched five-column contact, native
trilobite and final wagon. **EXAM_LINE_ART_TARGET_NOT_MET**3/3: nearly white
contours, pale native coloration and inadequate printed legibility. Source
photographs are explicitly not generated; all four output columns are photo-
edge-conditioned conversions, not from-scratch institutional drawings.

Foreground below245, rounded thousandths BASE/LORA: trilobite0/1,wagon0/0,
ammonite39/67; dark-fraction below96 reports0 in all six. Large white-vs-photo
MAE112.61/112.69,128.46/128.96,69.36/70.40 is not style improvement. BASE also
becomes faint; do not assign this outcome exclusively to LoRA or assert that
the adapter learned nothing. No output darkening/thresholding was used to
disguise this quality failure. Numerical success remains immutable and separate.

CPU-only polarity inversion of the three canonical Canny inputs was then
viewed: black pixels3.24/6.16/18.26% (ammonite/trilobite/wagon). Main shapes
remain, but shop clutter, stone texture, trees/grass and fit-frame borders also
remain. **RAW_CONTOUR_INPUT_TOO_CLUTTERED_FOR_EXAM**. This is input processing,
not an AI-generated illustration; no workspace mutation/model/GPU/HOLDOUT0.
Do not proceed directly to a raw-contour initializer GPU run.

Canonical34-member diagnostic evidence `artifact_66065d55950a42e5894d9f477008d2b7`
/ `rev_c4e9568f471047b69adc1ecaaddf6abc`, primary `reports/own-review.md`, SHA
`aaa1c6cb50e3db821dcf54d49d98a0e6e5e475660a1758353ab2db0c8c09ce2f`;
all persisted bytes reread equal. Source gates, initial test/type limitations,
install/dispatch/publication/replay/matched/input-only evidence retained. No
duplicate canonical photographs/PDFs/weights/generated output binaries. The
first non-tty sudo check lacked cached credentials while EOM:3 remained valid;
replay succeeded in that same pane without extra grants or model calls.

Independent blind review NOT_PERFORMED; four-family/32-case/HOLDOUT, Item/HWPX
and activation gates OPEN/FORBIDDEN. Production unaffected; goal ACTIVE.

### Next CPU-only diagnosis: suppress fine photo edges before any new recipe

1. Responsibility: one derived input inspection within existing source/pixel
   owners, not a new worker/queue/evaluator or production mode.
2. Canonical source: same approved photo, exact staged original and canonical
   Canny result pointers; no new acquisition/TRAIN/HOLDOUT or source replacement.
3. Identity: record original logical/revision/member/SHA and diagnostic RGB/PNG
   hashes. Do not overwrite1.0/1.1 initializer/control/output identities or receipts.
4. Resolution: re-resolve registered result/plan and validate staged photograph
   hashes/media/dimensions. Compare the actual old control, not guessed filenames.
5. Access: three indexed/pinned sources, one ordered derivation per source;
   read-only worker inputs and explicit temporary inspection output boundary.
6. Structure: existing typed pointer plus small immutable operation evidence;
   maps for case lookup and closed derived file set. No DB/cache/index change.
7. Cost: O(total source pixels) bounded CPU operations;3 inputs,0 GPU/model calls.
8. Concurrency: inspect only completed staged work, no workspace modification,
   dispatch/claim/lease or reopened generation budget.
9. Ownership: Orchestrator resolves/validates/archives; isolated numeric identity
   reads staged input, uses already installed pinned Pillow/OpenCV/NumPy only.
10. Failure: invalid pixels/hash/runtime/media/file closure reject; no automatic
    alternate blur/threshold search. Preserve both reduced-detail and lost-detail
    observations. Scientific contours, wheels and segment locations must remain.
11. Simpler alternative: raw Canny polarity inversion already inspected and too
    cluttered. Test **one** fixed5x5 Gaussian/sigma1.0/reflect101 before the same
    Canny100/200/aperture3/L2false. Same832x512 fit and all coordinates. No threshold,
    cropping/masking/frame removal/training/prompt/initializer changes in this test.

This CPU-only diagnostic is not yet executed at this checkpoint. Observe fine-
texture suppression, artificial fit-frame edges and structural-detail loss
separately. Merely reducing edge count is not acceptance. If this candidate loses
essential features or retains clutter, report it and choose the next factor before
any schema-first worker successor. Do not add an unused inference recipe or run
another GPU sweep merely to give the diagnostic a new version number.

## Fixed coarse-control CPU result — no new inference recipe

The declared one-candidate5x5/sigma1.0/reflect101 diagnostic was executed under
the installed isolated eom-image identity. Registered white command/plan/result
were resolved first; staged photo hashes and licensed metadata reader checks
reused. Original Canny bytes exactly reproduced under pinned Pillow11.3.0,
OpenCV4.11.0.86/NumPy2.4.6. Source-free/Torch-free/DB-free child, CPU single-thread
OpenCL off, closed seven derived files and96 unchanged workspace size/mtime
entries verified. This metadata snapshot is not a fresh all-byte SHA proof;
the preceding terminal replay supplies the separate96-file SHA/mtime evidence.

Viewed all three old/coarse input-only panels. Edge count ammonite13816->9428
(-31.8%),trilobite26238->12420(-52.7%),wagon77767->39778(-48.8%). Main placement
and silhouettes remain recognizable, but fossil internal marks become sparse/
interrupted while shop/trees/grass and fit-frame borders remain. Judgment:
**COARSE_CONTROL_ALONE_INSUFFICIENT_DETAIL_LOSS_AND_CLUTTER_REMAIN**. Reduced
edge counts are not semantic preservation or style acceptance. No stronger blur/
threshold sweep, new worker recipe, model/GPU dispatch, training or HOLDOUT.

Canonical6-member evidence `artifact_1b01579ea35e4be48aae83ff358a7ba3` /
`rev_16dc0a12d7ac4ac59afffd2f83a681e4`,primary `reports/own-review.md`, SHA
`8515c561dbee4f6197375c3a210fbea684d5e90bf2b5cd980d4a8b6d09fb2115`;
all persisted bytes reread equal. Report/admission/operator/log and one derived
input contact retained; no duplicate original photos/weights/generated outputs.
Numeric dependencies, binding and five services unchanged; GPU idle at postflight.

Next priority is to separate **subject structural evidence from irrelevant
exterior background**, not globally weaken all contours. Review against the
authoring/reference intent before any source-region operation: scene-dependent
background stays; optional exterior clutter may be suppressed only without
moving/reframing the main subject or touching protected scientific details.
Original/source/revision/member/hash remain pinned and unchanged. A future region
recipe must pin reviewed coordinates/protected regions, reject stale or mismatched
source/invalid boundaries/protected-region contact, share the current pixel owner
and CPU verifier, and be schema-first before worker execution. Start with CPU
examples and actual own inspection; no generic segmentation framework, permission
expansion, new dependencies or new GPU budget at this checkpoint.

Regression coverage was also added for valid PNGs containing only blank/too-faint
marks: raw metric serialization can succeed, but the existing blind-presentation
normalizer rejects absent foreground. This protects the existing evaluation
meaning rather than adding a new runtime heuristic or reclassifying historical
numerical results. It does not automatically certify every nonblank drawing.
Focused evaluation/white-recipe/test-environment regression47 PASS/30.24s;
Ruff/format/diff and strict test-file mypy PASS with explicit source MYPYPATH.
The initial type-check invocation treated the separately packaged trainer as an
untyped installed library; corrected source discovery, not runtime dependencies
or source annotations. Both invocation logs are preserved separately.
Canonical3-member regression evidence `artifact_27498c24c0284550af685e75067d5bbb`
/ `rev_1e9155d62f1c437f90a59521512a1398`,primary `logs/focused-regression.log`,
SHA `f20c11871ed90d830684ad0a193a6e869753b4bd29aac08b6e52cbed9fc93374`;
persisted reread equality PASS, source `f0862ba7`. Milestone Slack IN_PROGRESS
`devreport_feef983489ad48deb2363442d71ff665` SENT/HTTP2002026-10-05T19:59:24Z;
reported negative own-quality findings and no production change, not goal completion.

## Next input-only subject-region experiment

Use reviewed conservative rectangular regions in the normalized photograph's
800x504 coordinate system. The main wagon (body/roof/antenna/two visible wheels),
enrolled fossil and partial ammonite remain at their original fitted positions.
Do not infer a wall, unfolded fossil, missing chamber geometry or scientific fact
from old discovery text. The root experiment intent declares these as subject-
morphology diagnostics, not a scene-dependent production question. Raw old intent
and source-review assertions are retained separately; source pixels cannot prove
all originally requested features exist.

1. Responsibility/boundary: existing Canny pixel owner gets a pure region-retention
   primitive; contracts own rectangle/protected-region validation. No production
   worker recipe, dispatch command or provider activation added at this stage.
2. Canonical source: exact registered licensed reference/plan/result plus existing
   canonical Canny member. Diagnostic regions are reviewed against the actual PNG,
   with source SHA, source dimensions, selected bounds and rationale recorded.
3. Identity: keep logical source/revision/artifact/member/hash separate. Derived
   input RGB/PNG hashes are inspection evidence, not replacements for originals.
4. Resolution: re-resolve pinned plan/result/source metadata and bytes/media/hash;
   region coordinates outside the canvas or touching excluded protected marks fail.
5. Access: bounded three-source ordered derivation, maps for case/trace lookup,
   exact bounded rectangle/protected membership checks; no DB/index/cache change.
6. Structure: reuse frozen ImageEvaluationBoundingBox values, tuples/sets and
   existing artifact resolver/publisher. No polygon/segmentation framework needed.
7. Cost: O(W*H + protected regions), bounded832x512 RGB; no repeated image decode.
8. Transaction/concurrency: root Orchestrator CPU diagnosis only; read-only existing
   workspace, exclusive task-local display outputs, no GPU lease/queue/claim.
9. Dependency: contracts validate geometry; existing provider decodes/clips/encodes
   pixels; Orchestrator resolves/stages/archives. No new numeric dependency.
10. Failure/retry: require positive retained foreground and contained unique
    protected regions. Preserve all pixels inside retention, set only exterior
    control pixels to0, never create a rectangle stroke at the mask boundary.
    Unsupported or corrupt input fails, no alternate region auto-search/retry.
11. Simpler alternative: global Gaussian already removed relevant fine marks.
    Retain original Canny internally, without blur/retrace/rescale/morphology
    repair. Rectangle clipping may still leave clutter inside; inspect and record
    that limitation instead of claiming perfect object segmentation.

This is not a new cross-service protocol: the primitive is first exercised by
source tests and a bounded root CPU inspection, not by a changed worker message.
Before a future numerical worker can use it, define schema-first reviewed source/
region provenance and initializer semantics, install/replay verification and a
separate bounded generation command. Do not silently inject a region into1.0/1.1.
The existing old numeric recipes and canonical generated outputs remain unchanged.

Source-only checkpoint 2026-10-05T20:16Z: retention/old Canny/reference/white-
initializer/environment regressions135 PASS/42.62s. Ruff/format/diff and strict
three-file Python3.12 mypy PASS; the contract also passes Python3.11 checking
against the numerical environment. Tests cover exact protected/internal pixels,
zero exterior, no added boundary, byte-identity full-frame replay, one decode,
invalid/protected-contact coordinates and malformed/blank/nonbinary inputs.
No installed lab or production code changed; actual three-photo CPU inspection
is the next separate evidence boundary, not implied by these source-test results.

## Actual retained-region CPU checkpoint — 2026-10-05T20:24Z

Root source verification at `b933861f79e1f7c5a06aab15f65d76ff8ecc6a65`, not
installed-worker acceptance. Re-resolved registered1.1 command/plan/result and
six canonical photo/control members. The CPU child validated complete staged
source closure under Pillow11.3/OpenCV4.11/numpy2.4.6, retaining the worker
workspace's explicit UID ownership check. Root source imports do not justify
worker repository access; no privileges changed. Model/GPU/training/HOLDOUT0,
workspace writes0, old96 file size/mtime unchanged (not a fresh full-SHA replay).

Actual normalized800x504 fit794x500 centered at(19,6), canvas832x512. Conservative
reviewed source rectangles mapped without changing subject scale/placement:

| Source | Original edges | Retained edges | Removed exterior | Internal/protected pixel changes |
|---|---:|---:|---:|---:|
| Partial polished ammonite | 13,816 | 6,395 | 7,421 (53.7%) | 0 / 0 |
| Enrolled trilobite | 26,238 | 23,664 | 2,574 (9.8%) | 0 / 0 |
| Parked passenger wagon | 77,767 | 32,441 | 45,326 (58.3%) | 0 / 0 |

Opened actual combined source/old-control/region-control contact. The original
main outlines/visible wagon wheels and fossil markings remain; exterior source
frames/sky/clutter decrease. Internal grass/neighboring cars, shop objects and
stone texture remain. Truncated clutter can make the rectangular support boundary
visible even though no rectangle stroke was added. Thus own decision
**REGION_PIXEL_PRESERVATION_PASS_STYLE_SIMPLIFICATION_NOT_COMPLETE**. These
inverted Canny displays are processing inputs, NOT generated exam illustrations.
No claim of perfect segmentation, full anatomy, independent review or style PASS.

The first root wrapper incorrectly invoked the worker-specific command loader,
which requires the caller UID to own the staged workspace. It created only an
admission receipt and empty task-local view directory before failure. Preserved
failed operator/log/receipt, then used existing explicit-owner directory adapter
and public schema/canonical command parser in distinct R2 paths. Production
guards, core source and worker permissions were not weakened to fit a root
diagnostic. No model retry or overwrite of the failed attempt.

Canonical12-member evidence `artifact_15f4fdc19413494f9072976a4ccabf09` /
`rev_815ab05317324c1ea45ccd166ad41381`,primary `reports/own-review.md`, SHA
`deb85ec3a77888d3766c46db0be7dfe3aa594dc641943c878cf77b2060cc0d58`;
all persisted bytes reread equal. Review/admission/inspection/source tests/types,
operators/logs including first failure and one derived contact retained. No copy
of canonical source photos, generated outputs or weights; no region worker-input
artifact promoted under an old recipe. Numerical lab remains1083fd4e; dependencies,
production binding and five services unchanged, postflight GPU0%/2MiB.

Milestone Slack IN_PROGRESS `devreport_577ed9e2caa3490ebc39ccd49dc178e4`
SENT/HTTP2002026-10-05T20:26:27Z, phase `Image goal / retained-region CPU
checkpoint`; reported source135 PASS, actual internal/protected-pixel invariants,
remaining style limitations and no model/production change. This is not goal
completion or institutional quality acceptance.

## Next isolated numerical hypothesis: white initializer and denoising

The region experiment does not explain the near-blank **BASE and LORA**1.1
outputs. Existing white img2img initialization uses strength0.70 and21 effective
steps out of30. Test full-noise strength1.00/30 effective steps as one hypothesis,
not as an established root cause or completed fix. Use old full-frame Canny
controls initially; do not change prompt/seed/LoRA/regions/noise together.

1. Boundary: extend existing photo-style contract/pixel/backend/verification
   owners; same offline img2img pipeline and paired executor, not a new framework.
2. Source: immutable registered1.1 plan/result and exact licensed photographs,
   controller/base/VAE/LoRA configuration; previous negative findings preserved.
3. Revisions: schema-first successor1.2 plan/command/result, exact named
   initialization policy. Do not mutate released1.0/1.1 bytes or semantics.
4. Resolution: existing source/revision/member/media/hash/permission/lifecycle
   checks plus exact prompt/control equality and declared initializer/timestep
   receipts. Reject wrong versions, forged effective-step counts or stale pins.
5. Access: ordered3 cases x2 arms; keyed trace/output maps, one model load per
   existing paired lifecycle; no DB/index/search/cache changes.
6. Structures: existing frozen policy/plan/result/pointer values and manifests;
   closed version mapping and shared pixel owner, not boolean option growth.
7. Scale: at most6 outputs in one bounded dispatch, existing16GiB/600s ceiling;
   record actual resource use separately. No parameter/seed sweep or training.
8. Concurrency: existing isolated service identity/workspace and GPU lock;
   Orchestrator resolves/stages/validates/commits; no workers writing NAS/DB.
9. Dependencies: no new runtime/model/library, existing installed numerical
   interpreter/RECORD gates. Source tests alone do not authorize lab invocation.
10. Failure/replay: keep terminal result/exhausted-budget meanings; old receipt
    replay is read-only, no implicit rerun. New command needs its own bounded
    admission and installed-consumer/CPU transform verification.
11. Alternative: changed prompts, output darkening or more blur confound the
    matched result and may conceal failures. Separate numerical factor first,
    preserve unenhanced generated bytes and own-vs-independent review boundary.

This checkpoint does not implement/admit the1.2 recipe or spend generation
budget. First define JSON Schema2020-12, frozen Pydantic and negative/replay tests;
then implement and verify the shared consumer before any new dispatch. Region
provenance remains a separate future contract if that input variant is needed.

## Full-denoising successor source checkpoint — 2026-10-05

Added schema-first photo-style plan/command/result1.2, with immutable predecessor
schema bytes preserved. The named policy is
`CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0`: fixed strength1.00, scheduler30,
effective30, Pillow11.3 and the same white RGB hash. No region, prompt, LoRA,
controller/scale, seed or source changes. Source/command/result parsers use
explicit model lookup; no inferred latest or mixed-version acceptance.

Reused the existing initializer, numerical backend, step-count guard, paired
executor, Orchestrator staging/commit owner and CPU verifier. No new worker unit,
backend, dependency, permissions, production configuration or queue. Added v3
wheel-resource requirements to the existing build gate. The new class inherits
white-pixel validation; historical1.0 remains photo-initialized and1.1 remains
strength0.70/effective21. Numerical success still means NOT_REVIEWED quality.

Focused full-denoising/white/photo/source/environment regression122 PASS/72.61s;
Ruff/format/diff/bash syntax PASS; strict core4-file Python3.12 and contract2-file
Python3.11 mypy PASS. New tests cover exact new policy, old resource hashes,
cross-version pointers, undeclared factors/region/retry/activation, forged result
recipe/lineage/coverage/quality, actual backend strength/timestep handoff,
terminal failure/success read-only replay and shared publication/CPU verification.

Initial gate120 PASS/2 FAIL was a synthetic backend test fixture: changing its
scheduled steps without resealing its command hash correctly triggered the
existing hash guard. Corrected the test fixture, not the production invariant;
the full122-test gate then passed. Both logs are preserved separately. This
source checkpoint is not installed-worker or new generation acceptance. Next:
build/RECORD, numerical-role source-free import, retained rollback, old receipt
replay and one separately admitted matched six-output comparison, never a hidden
repeat of the exhausted1.1 command.

## Actual full-denoising matched checkpoint — 2026-10-05T20:53Z

Source `d1b79a91ba45293af652aeb1695fe3707c6f8c04` was built from an immutable
Git archive. Wheel contents/RECORD and source-free installed simulation PASS.
Only contracts/provider were installed in the existing numerical lab; trainer,
numerical dependencies, unit templates, permissions and production unchanged.
Contracts wheel SHA `1ef60064a199a366e08bda4b2fc5f085bc1233792040831cf0878a9e61c45578`;
provider SHA `af6cd7519d9ec505b1f5e669f782d0d7a1fafe12f4278544d5297a7fbb564a65`.
Build directory
`/tmp/eom-image-trainer-build/d1b79a91ba45293af652aeb1695fe3707c6f8c04.5d2FnJ/dist`.
Prior lab1083fd4e rollback wheels/RECORD were checked and retained; not rolled back.

One separately admitted existing paired worker run
`imgsdxlvalcmprun_be156686116230dc48669327c82df967` completed6 outputs in35,858ms,
peak10,763,033,600 bytes, terminal inactive/dead/success/exit0. No retry, parameter
sweep, mask/blur, changed prompt/controller/LoRA/seed, new training or HOLDOUT.
Only strength0.70->1.00 changed; effective21->30 steps follow the declared recipe.
White RGB hash, original full-frame Canny and all source/prompt pins stayed equal.

Pinned plan `artifact_f7adb670b2b14127be482fe0423b5ee0` /
`rev_8fc561bf92db48228b2a68c7af1fc2a0`, primary
`manifests/sdxl-photo-style-plan.json`, byte SHA
`51c8dd5633fb68490a3401aee4afae66986054fca340d1defb6224d380ac3b6a`.
Command `artifact_50ef9249d1b94807bebbd179a652cb01` /
`rev_7fc9e97951224455a6f08cbfff0edf02`, primary
`manifests/sdxl-photo-style-command.json`, byte SHA
`41c94401c06c0cc9fc4421cc196470acd08a0bedb86cb0b844deef36628b89ef`.
Result `artifact_3c89768b8764486c9caabdcfe73a5941` /
`rev_dab70204b49242e6a114493a5f6a8549`, primary
`manifests/sdxl-photo-style-result.json`, byte SHA
`da7c05c61e3625339b0921379ee6416484b7237a05dccab4f64c2dd9055382ae`,
semantic SHA `d8ab4e4d248c0b3ad57aec6b3490cee0719a07d85052d9251c045a652ad3f538`.
All19 canonical members reread equal after source readmission and installed-role
CPU transform verification. Root matched comparison reread15 pinned source/old/
new members. Measured peak memory is an observation, not a conditioning variable.

Opened new and matched contacts plus all6 original-resolution native RGB outputs,
without darkening/repairing output. Source-photo panels explicitly say
SOURCE_PHOTO_NOT_GENERATED; four subsequent columns are actual old/new model
outputs, reference-controlled rather than drawn from scratch.

| Source | BASE foreground0.70->1.00 (per thousand) | LORA foreground0.70->1.00 |
|---|---:|---:|
| Partial polished ammonite | 39->286 | 67->289 |
| Enrolled trilobite | 0->383 | 1->426 |
| Parked passenger wagon | 0->540 | 0->433 |

Near-blank output decreased on this fixed three-source/one-seed comparison, but
this is **not exam-style acceptance**. Wagon remains pale photographic/pencil
texture with trees/ground/background cars; native LORA has a slight color cast.
Trilobite is pale/embossed with weak structural contrast and frame artifacts.
Ammonite's partial outline is recognizable but internal markings soften/change,
shop clutter remains and native backgrounds contain unwanted glyph-like strokes.
Scientific pattern fidelity NOT_VERIFIED; own exam-style acceptance fails both
arms for all3. Own decision
**NEAR_BLANK_REDUCED_BUT_GRAY_PHOTO_STYLE_AND_FIDELITY_NOT_ACCEPTED**.
LoRA superiority NOT_ESTABLISHED; independent blind review NOT_PERFORMED.

Installed numerical identity replayed old generic1.0, exact-phrase1.0, white1.1
and new1.2 terminal receipts: all4 PASS, each96 files SHA/mtime unchanged and
model/GPU/transform/write0, no Torch or repository import. The first queued generic
read-only console invocation yielded no log; after no active execution remained,
a distinct explicit R2 read-only replay was observed PASS. This was not a model
failure, generation retry or justification to resubmit a terminal command.

Canonical32-member diagnostic evidence `artifact_ae6fce2acb5048dca3b222016dbd5198`
/ `rev_c7fcac42c18b4ab7ad88b2b84c752f19`, primary `reports/own-review.md`, SHA
`3186509122c7daa38ee127cc99c5073c0ecd0434cbfbc63bc0b6547b091e22a6`;
all persisted bytes reread equal. Includes initial fixture-hash failure, successful
source122-test/types, build/install/rollback records, dispatch/publication/matched
records,4 replay logs, bounded operators and one derived contact. No duplicate
canonical source photographs, generated PNGs or weights. Initial frozen-budget/
pre-dispatch records remain historical intent; actual terminal receipts establish
execution. Archive itself makes0 model/GPU/training/HOLDOUT calls. Production
binding SHA remainsf96eda84…, five services active, GPU0%/2MiB at postflight.

Next: one reviewed **positive-prompt contrast/stroke variation** within existing
1.2, explicitly black contours/white paper rather than pale pencil/relief/photo
shading. Preserve observed subject anatomy/composition, negative prompt, seed,
controller, LoRA and numerical recipe; pin new prompt/case/plan revisions and
check both tokenizers before any bounded matched dispatch. Do not edit original
content-team prompt files or add another schema/backend/framework for a permitted
prompt variation. Do not combine region masking into this experiment. Broader
native-family and independent review follow only after a promising result.
Goal ACTIVE; current generation budget exhausted; production activation and
Item/HWPX canary NOT_STARTED, quality NOT_ACCEPTED.

Milestone Slack IN_PROGRESS `devreport_1f5e243107394b018879c888ccd0a82a`
SENT/HTTP2002026-10-05T20:53:41Z, phase `Image goal / white denoising matched
checkpoint`. Reported numerical success separately from failed own style/fidelity
acceptance, preserved predecessors and unchanged production; not goal completion.

## Actual positive ink-prompt comparison — 2026-10-05T21:08Z

Previous goal turn classified PROGRESS: full-denoising implementation, installed
gates and actual negative six-output evidence changed the next action. This turn
used existing1.2, source `a02f788c3870ecad553e997770a9af2e25973543`, with **only
reviewed positive-prompt wording** changed toward black contours/white interiors.
No core/schema/install changes; existing lab remainsd1b79a91. No original team-
prompt edit, new framework/dependency, region/blur/postprocessing/training/HOLDOUT.
Original negative prompt, photographed facts/composition, seed104729, white RGB,
full-frame Canny, controller/LoRA/configuration and full-denoising recipe unchanged.
New positive hashes propagate to new case IDs/staged names/plan/command identities.

Both installed CLIP tokenizers PASS12 checks, maximum67/77 tokens, no truncation.
Source-free numerical CPU identity, no Torch/tensor/pipeline/GPU load. Existing
metadata admission44 targets with binary-open guard, staged77 explicit inputs,
CPU source/control/initializer verification exactly equal to old3. First root
preparation failed before commit/staging/dispatch because +00:00 timestamp text
was hashed before canonical Pydantic Z serialization. Preserved failed operator/
log, corrected the local wrapper to canonical Z and used distinct R2. No core
guard weakening, state repair or model retry. Bounded operators Ruff/format PASS.

Plan `artifact_e26be9c1c2d54ca5a386f3c56a20618b` /
`rev_3f98fbf8f7824f88ad33dbacd719643e`, primary
`manifests/sdxl-photo-style-plan.json`, byte SHA
`3444e66035ee3b675519b093eebadc4621b55be9aeaccb76422b816d0b6071d5`.
Command `artifact_4218b6f0fe7e4a31bbe85260ca3ee6f1` /
`rev_3da0f43f688a4181908d7815efcc3795`, primary
`manifests/sdxl-photo-style-command.json`, byte SHA
`49187cddab4910f5d2be211422591c1af82a4b7a77f059153396ec553783b164`.
One admitted run `imgsdxlvalcmprun_551d59f8c1ae23b4c89d99e348231413`,6 SUCCEEDED,
35,956ms, peak10,763,033,600 bytes; live activating/start and then terminal
inactive/dead/success/exit0 observed. No automatic retry/sweep or another dispatch.
Result `artifact_41fecb30ae5c4be488f91db7364afdc9` /
`rev_7fed4d700aad44ab90b113681d85afc9`, primary
`manifests/sdxl-photo-style-result.json`, byte SHA
`96099d5c642c2cdeb7f34c99f7622e0aeb1a344f0de3a63f78341a8c2f76a4d5`,
semantic SHA `c156b126c9388f51e55ea2d8760550e94825b6465177c4d1ebd56f0e2f59ca09`.
Canonical19 members reread equal after readmission and installed CPU verifier;
matched comparison re-resolved15 source/old/new members and proved all other
factors equal. Installed terminal replay PASS96 files SHA/mtime equal with model/
GPU/transform/write0 and no Torch/repository import. Unchanged source122 tests
and predecessor replay evidence are referenced, not falsely labelled new runs.

Opened new/matched contacts plus all6 native RGB outputs at original resolution.
All3 remain gray relief/pencil/photo texture rather than deliberate dark exam
contours. Raw LORA trilobite/wagon show cream/greenish casts; frame bars/clutter
remain. Main forms recognizable, but fossil pattern fidelity NOT_VERIFIED.
Foreground/dark per thousand old->new: trilobite BASE383/2->396/0,
LORA426/0->373/0; ammonite BASE286/22->245/5,LORA289/15->231/5;
wagon BASE540/1->472/2,LORA433/0->359/0. Pixel MAE4.24–11.09/255 proves an
output change, not quality gain. Own judgment
**POSITIVE_INK_PROMPT_ALONE_INSUFFICIENT_GRAY_RELIEF_AND_CLUTTER_REMAIN**.
Both arms fail own style acceptance for all3; LoRA superiority NOT_ESTABLISHED,
independent review NOT_PERFORMED. No contrast repair to make examples pass.

Canonical21-member diagnostic evidence `artifact_185ed70ae95b4a3a887c68f1edae01b7`
/ `rev_1895591c70324d72915215131d092e8b`, primary `reports/own-review.md`, SHA
`58a9ff7b6edd7fbe2e7f69d96a39b5b8166971e35bd199d051ddaaaf8053f68b`;
all persisted bytes reread equal. Contains preparation/token/CPU/dispatch/result/
matched/replay evidence, bounded operators, first root failure and one derived
contact, not duplicate canonical photos/outputs/weights. Publication/comparison
wrappers reuse pinned earlier root operators already archived in the preceding
32-member evidence. Bindingf96eda84… and numerical dependencies unchanged,
five services active, postflight GPU0%/2MiB. Goal ACTIVE, quality NOT_ACCEPTED,
current command budget exhausted, production/canary NOT_STARTED.

## Next causal experiment: declared spatial-control window

Registered spatial command fixes scale1.0,start0.0,end1.0; the shared backend
passes these explicitly for all timesteps and serializes actual model RGB, not
a gray reference placeholder. **Hypothesis**, not proven cause: dense full-frame
photo control may dominate style despite the new prompt. Test earlier termination
at proposed0.65 while retaining early placement constraints. Evaluate anatomy/
composition/detail loss separately; a simpler or darker image can still fail.

1. Boundary: extend current photo-style family and shared backend/verification,
   not another worker, dispatch service, queue, control model or framework.
2. Canonical source: exact registered ink-prompt1.2 plan/result, same licensed
   photos and native configuration/controller/LoRA; keep negative findings.
3. Identity: schema-first successor1.3 plan/command/result with a mandatory small
   frozen control-window value. Preserve released1.0/1.1/1.2 bytes and semantics.
4. Resolution: existing pointer/source/permission/schema/hash/lifecycle checks;
   new plan/result control equality and mixed-family negatives. No latest fallback.
5. Access: ordered3 cases x2 arms, keyed source/trace/output maps; no DB/cache/index.
6. Structure: reuse control value inheritance/public parameter handoff, frozen
   typed values and existing manifests; avoid boolean flags or mutable presets.
7. Scale: one bounded6-output dispatch under16GiB/600s; no sweep or training.
8. Concurrency: existing isolated worker identity/GPU lock; Orchestrator stages/
   validates/commits. Old terminal replay remains read-only, no resubmission.
9. Dependencies: no new library/download/permission; schema before worker behavior,
   installed RECORD/source-free gates and retained compatible rollback required.
10. Failure: only declared end value changes; start0/scale1/resource policy/pixels/
    prompt/negative/seed/LoRA fixed. Reject forged result or undeclared override.
    Observe native RGB and fine structure; no output repair/automatic parameter retry.
11. Alternative: more prompt wording did not establish dark lines in the actual
    comparison; more data/training or simultaneous region/scale changes would not
    isolate this factor. Do not weaken old fixed control values to run the test.

Use a bounded explicitly declared control end range in the successor rather than
creating a contract for every scalar value. The initial actual experiment is
only0.65; no runtime auto-selection, exhaustive search or hidden sweep. Source
regression, old compatibility/read-only replay, exact backend kwargs/result pins,
CPU transforms and matched quality review precede any activation. Broader native
family matrix and independent blind review still remain after a promising recipe.
