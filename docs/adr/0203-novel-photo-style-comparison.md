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
