# ADR 0206 — Explicit native style exposure without changing the target cohort

Status: implemented in the isolated lab; one trial and matched outputs completed,
own quality NOT_ACCEPTED; frozen100 data audit completed, no production activation.
Date: 2026-10-06 UTC.

## Evidence and hypothesis

ADR 0205 records the completed, uniformly sampled FULL100/800-update run and
its own-review rejection. The 100 distinct targets contain 17 CLEAN_CONTOUR,
8 FINE_HATCHING and 75 RESTRAINED_TONE examples. Both matched photographic
and source-free outputs retain excessive shading/background detail. The
style trigger was present; more updates alone did not resolve the problem.
This supports testing exposure imbalance, not claiming that imbalance is the
proven cause or that legitimate agency shading/scenes must be removed.

## Responsibility and canonical source

The frozen training command owns the exposure policy. Image contracts describe
it; the trainer derives a numerical index schedule; the existing orchestrator
stages, dispatches and commits validated results. No worker persistence, queue,
database schema, dependency or production provider binding is added.

Keep the same admitted target revisions, pixels, captions, TRAIN membership,
100–200 unique targets, at most eight preparation results, three targets per
document and four per exam group. Those limits constrain the unique cohort,
not optimizer exposure. Do not reclassify tone as contour or duplicate images
to pad the cohort. Document/group/composition draw counts must be reported
alongside expression counts: changing expression exposure can also change
those correlated marginals. It is not a composition-controlled experiment.

## Closed successor and identity

Add `local-image-sdxl-native-lora-command/1.2` with required
`ALL_TARGETS_ONCE_THEN_STYLE_STRATIFIED_4_2_4/1.0` exposure. The policy's explicit
integer weights are CLEAN_CONTOUR=4, FINE_HATCHING=2, RESTRAINED_TONE=4. It is
FULL_STYLE_TRAINING only and requires all three existing expressions.
Released commands 1.0/1.1 retain their exact uniform epoch ordering.

The new command receives its own content-derived run identity and SHA. Target
logical/revision IDs, artifact member pointers and pixel/caption SHA remain
separate and unchanged. Existing resolution checks retain permission, schema,
media, lifecycle, chronology, cohort uniqueness and hash validation. Native
result/adapter 1.0 can still pin the exact command SHA; they do not assert a
uniform sampling policy. Their released bytes are not modified.

Existing evaluation pins accept exact training versions. They must reject
training 1.2 except through explicit successor evaluation protocols. No use of a
1.1 alias, implicit latest or silently broadened released consumer is allowed.
Do not run training until compatible training and evaluation wheels are staged
and installed identities/RECORD, role isolation and replay are verified.

The source candidate's closed chain is training command1.2 → geometry
command/result1.5 → native reference command/result1.3 → photo plan/command/
result1.5. Geometry/reference numerics, photographic prompts, reviewed retained
regions, initializer, control, seed and output treatment do not change. New
schemas reuse pinned predecessor fragments instead of duplicating their entire
definitions; repo/wheel copies and all referenced resources are verified.

## Schedule and data structures

For N unique samples and M=updates×accumulation microsteps:

1. The first N indices are the existing seed-based epoch-zero shuffle: each
   admitted target is encountered exactly once.
2. Allocate the remaining M−N draws in 4:2:4 proportions with integer largest
   remainder; ties use the fixed contour/hatching/tone order.
3. Shuffle the quota-sized expression sequence with a local seeded RNG. Each
   expression draws from its own seeded shuffle cycles; each member is used
   once per cycle, with per-expression member-count spread at most one.

Use a keyed expression bucket and per-bucket FIFO deque, not repeated target
scans. The immutable index tuple requires O(N+M) time/space and at most 4,000
indices. It is a numerical value, not a second canonical dataset or persistent
registry. Global random state is untouched. Reordering native geometries also
changes the numerical noise stream; a fixed seed is not a claim that each
sample receives identical noise to the uniform run.

For the actual 17/8/75 cohort at 800 updates/accumulation four, expected total
draws are 1,257/628/1,315, including the initial coverage. These are scheduled
counts, not an independently recovered per-step execution journal. Final
stochastic loss is not a quality score.

## Numerical and concurrency boundary

The shared numerical adapter receives an optional immutable index schedule.
Only the admitted successor command derives it. Uniform recipes pass None and
retain exact predecessor ordering and SSD checkpoint behavior. Validate full
length, index range, strict integer values, coverage and terminal-only/no-resume
before importing model dependencies. Reject schedule/checkpoint mixtures.
The actual accumulation loop must consume the schedule and fail on under/overrun
rather than cycling or inventing a recovery. Test this through the real loop
with dependency fakes, not solely with a pure quota calculation.

Existing GPU lease, exclusive workspace, command-hash idempotency, terminal
result replay, permissions and bounded budgets remain authoritative. A failed
run preserves failure evidence; no automatic retry, new identity bypass or
model sweep is introduced. A STOP does not mutate previous accepted artifacts.

## Experiment and acceptance

After producer/consumer source and installed gates, allow one isolated matched
trial: the same FULL100 pixels/captions/base/dependencies/seed/800 updates,
changing only the explicit schedule policy. Use the same photographic and
source-free cases, report effective exposure and exact output hashes. Preserve
uniform 200/800 adapters and raw outputs. No HOLDOUT consumption, Item/HWPX
canary, activation or independent-review PASS is inferred from source tests.

Own rejection stops promotion and is not independent blind review. Actual
quality, fidelity, resource and independent review gates remain necessary.
The simpler alternative, more uniform updates, was already tested and rejected
at this checkpoint. An arbitrary weighting framework or physical duplication
of rare images would add maintenance/identity ambiguity without evidence.

## Source checkpoint — 2026-10-06 UTC

Implemented schema-first producer and exact consumer chain above, including
wheel-owned resources and release content checks. Focused regression: **581
PASS** in 197.67 seconds. It includes CPU dependency fakes exercising the actual
shared accumulation function through all 3,200 scheduled indices, predecessor
uniform ordering/checkpoint behavior, malformed schedules and accumulation
under/over-consumption refusal, native command/result identity, geometry
admission/execution/terminal replay, crossed-version rejection and photographic
plan/command recipe preservation. These are not GPU/quality acceptance results.

Ruff formatting/lint and strict focused mypy for the 11 changed source modules
PASS; mypy uses the explicit test interpreter and `--follow-imports=silent`.
A broader import-following invocation found ten existing Pillow PixelAccess
typing diagnostics in unchanged `reference_simplification.py`; do not represent
the focused result as repository-wide typing PASS. Shell release scripts parse.
No released schema bytes, numerical dependency pins, DB migration, model
generation, training updates or production activation were changed by this
checkpoint. Full-cohort canonical metadata and installed wheel/role validation
remain required before the one bounded trial.

## Actual lab admission and one dispatched trial — 2026-10-06 UTC

Implementation source `45d198539554460aef722166faf7ebbcc07c49a7` was built from
clean Git. Exactly three compatible contracts/provider/trainer wheels were
installed in `/srv/eom/conda/envs/eom-image-trainer` only. Installed RECORD/direct
wheel SHA and actual `eom-image` role imports PASS. Dependencies, systemd unit
bytes, permissions, production binding and five active production services did
not change; no service restart. The prior three wheels were hash-verified as
rollback inputs. Installed old uniform1.1, geometry1.4 and photo1.4 terminal
replays preserved all file SHA/stat without training, transforms, models or writes.

Actual full-cohort metadata admission verified 100 unique frozen targets from
eight preparation results, 66 PDFs and 55 exam groups, resolving 41 metadata
members without PNG/weight/reserved reads. Source Python3.12 and installed-role
Python3.11 schedules agree exactly. Scheduled counts are 1,257 contour /628
hatching /1,315 tone; 707 authored-scene /2,493 isolated-on-white draws. Maximum
draws per document/group are 231/296; these are exposures, not unique target
counts. They cannot be compared to the unique-cohort limits3/4 as a violation,
nor interpreted as composition-controlled sampling.

The sole training command was admitted and dispatched through existing
Orchestrator staging and the existing isolated native trainer unit:

- run `imgsdxlnativetrainrun_82a0f4c763243b7123d0fcf26dd5dde3`;
- canonical command `artifact_1b3218bee2b744d28735d0a9d4068a0c` /
  `rev_56790c7b51544203b972294fd710b5e0`, member
  `manifests/sdxl-native-lora-command.json`, schema1.2, application/json;
- raw member SHA `sha256:283200c091348bb8c0098aefca6f33e024cddcc3c78457969d0ce7809bd17d54`;
- command semantic SHA `sha256:f9335bee943558c7e9ef20a21909626b71453fde802a55c37d494bef32bfe869`;
- schedule SHA `sha256:3ac789b36344a877518919b0298d98812a935a9613a35f5a6c1f2ec79f2868b0`;
- systemd start **05:16:12 UTC**, actual worker UID984, PID470010 at observation;
  the GPU process was present, not inferred from a dispatch return code;
- 142 staged files, same pixels/captions/base/seed/numerical budget, requested
  800 updates, maximum one dispatch, no retry/resume/extension or activation.

Start checkpoint, installed/admission/replay receipts and exact operator audit
texts are archived as **11 members/36,450 bytes**, all canonical rereads equal:
`artifact_c096b03b2a3a44a2999e472f5171e08c` /
`rev_d9c21055aaaf4ea69d9e376ef6a7b82d`, primary
`reports/start-checkpoint.json`, schema `operations/plain-text-log/1.0`,
text/plain, SHA `sha256:61ada668ea3d6d165bbe1410ceb5286a70986aefc6317a67bbd39c667bacf8a1`.
The JSON-formatted report is an operations log, not a new wire contract. No
command/dataset PNG/adapter binary was duplicated into the checkpoint. The
checkpoint describes an observed RUNNING trial, not completed optimizer steps.

Two read-only preflight invocation mistakes (metadata ownership and a nonexistent
local result path) were corrected without model/DB/runtime mutation. The first
archive invocation supplied a string instead of a datetime and failed inside
`_request`, before job creation, publication lock or NAS commit. The finish
operator reused the exact report bytes/idempotency key with a parsed UTC datetime;
failed logs and the original local report remain preserved. These invocations
are not extra training/model attempts or production implementation defects.

A finite operator handoff is prepared to observe this same unit once, **not
before05:50 UTC**. It does not poll progress using the language model, dispatch
training/evaluation, change a pending unit, retry or extend the run. It may
publish a validated terminal result using the existing owner once; if still
running/missing it retains the same handle without a new attempt. Seven CPU
guard scenarios PASS separately from the581 source tests. Post-implementation
Git differences are restricted to these three documentation paths; numerical
and worker source remain pinned to45d1985. The handoff is temporary operator
materialization, not a new production scheduler or permanent queue.

Numerical result, own visual quality and independent review remain **PENDING**.
After successful terminal validation/publication only, perform the frozen six
photographic and four source-free diagnostic comparisons through the new closed
consumer chain. Do not count these TRAIN diagnostics as untouched HOLDOUT,
infer quality from loss, rerun old exhausted comparisons or promote a model.
Production binding SHA remains
`sha256:f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
Goal ACTIVE; Item/HWPX canary and activation gates remain open.

## 2026-10-06 terminal result and file-entry-point routing correction

The same bounded balanced4:2:4 run completed **800/800 updates over100 frozen
targets** in1,866,798ms with6,166,987,776 measured peak GPU bytes. The terminal
result and adapter were committed as four members to
`artifact_e0da019b8fbe4d059c1095d99caf6cfe` /
`rev_5ce77a79d1bb4c4d8952806ec333f7a2`; raw result member SHA
`sha256:642466ac728423d282d031a164056dac9106fec1915f316562539e26f0914d0b`,
adapter weight SHA
`sha256:617a45b5a92ecefc80903cf778d753e41d2e94b861373cbceb5a87e6a81e89c2`.
All canonical rereads matched. Installed-role terminal replay preserved146
file SHA/stat identities with no model, transform, training, GPU lease or write.
Numerical completion and the final stochastic loss are **not quality acceptance**.

The first actual installed-role photo CPU preflight then rejected photo
command1.5 before model/GPU execution. The contracts already supported it, but
`sdxl_comparison_command` duplicated stale version tuples (photo through1.4,
reference through1.2). A file-loader regression reproduced exactly two failures
(photo1.5/reference1.3) while eight historical routes passed. Synthetic codec
construction and direct-worker tests had not covered this entry boundary.

Correction: the existing closed contract codecs own immutable version-to-model
maps; the filesystem adapter queries their public support predicates, then
performs the same JSON Schema/Pydantic/canonical-byte validation. No permissive
prefix matching, latest fallback, schema-byte change, dependency, numerical
recipe or protocol version is introduced. Dominant access is exact key lookup:
O(1) membership in a fixed immutable mapping (six photo/four reference entries),
with no new lifecycle, cache, persistence, queue or concurrency boundary.
The dependency remains provider adapter -> contracts, never the reverse.

The staged photo command remains pinned to source45d1985, run
`imgsdxlvalcmprun_471da2effb7da9cd4326ca60674f8350`, semantic SHA
`sha256:a455244f6a5fa4e078c43aff497a2e870afca21dc9ad0d67d04f80b83c7ec6ab`.
Its plan is `artifact_0de095cae0e64e5b92c0cef190fdd203` /
`rev_5ae6802b77734563a6262feeb034a336`; no model dispatch occurred at the
failed preflight. Recovery uses the same bytes/identity/workspace with the
compatible lab-only loader correction, not a new timestamp, retry training,
replacement plan, direct DB mutation or production activation. The original
failure evidence remains preserved. Remaining matched diagnostics and own /
independent visual review remain pending until actually executed and recorded.

## 2026-10-06 matched outputs and own review (06:11 UTC)

Correction219b9d65 was built and installed as three hash/RECORD-verified lab
wheels only. Numerical dependencies, systemd templates, identities/permissions,
production binding and five production services stayed unchanged. Previous
45d1985 wheels remain verified rollback inputs. The same photo command bytes,
run, plan and staged82 members were preserved. Installed-role CPU input
inspection reproduced all three predecessor conditioning/initializer hashes;
supported identical-key command publication replay recovered the existing pin.

The bounded handoff then dispatched each remaining comparison **once**:

- Photo1.5: six outputs,36,143ms; registered19 members in
  `artifact_a759c8975e6146cfad36d345ac9468b3` /
  `rev_c18fec600dac432882af20cdf2cca8af`, result raw SHA
  `sha256:9a3ab990fce5eaa068ef5585df4e698b9d89be08ce8f364e50ed9ac29bb4ab30`.
- Source-free geometry1.5: four raw outputs,28,099ms, peak9,217,375,744bytes;
  run `imgsdxlloraevalrun_deca42178c2daf5dc25bd1714c08ffda`, five members in
  `artifact_496cdf4c999b44e3b2f1c7a9dd4c6efa` /
  `rev_bc01935da4ef4f34915506a5249219a0`, result raw SHA
  `sha256:89d25bf0c33a1fd75e2bfc3ec2895398d148d594c3c2b2a1b395f50e781833fc`.

Canonical result/output rereads and installed-role terminal replays PASS.
Photo comparison checked27 members; source-free comparison checked four
metadata/eight raw PNG members. Both BASE final/native RGB results match the
uniform800 baseline exactly. LoRA pixel changes are measured, not quality
proof. Photo grayscale MAEs are2.40612 /2.272015 /2.2553025 over255 for
trilobite/wagon/ammonite respectively. Diagnostic resizes affect only viewing
sheets, never canonical pixels or result hashes.

Actual own view of both sheets and the full-size wagon comparison gives
**NOT_ACCEPTED**: photographic outputs preserve pose but retain washed gray
texture, shadows/background and weak contours. Source-free beaker outputs
change apparatus topology, add unsupported fixtures/curved or circular features
and retain large gray backgrounds. No institution-quality improvement is
established by this fixed small diagnostic set. These are not HOLDOUT results;
independent/blind review remains NOT_PERFORMED, and Item/HWPX canary/activation
remain closed by unmet quality gates, not a new operational permission gate.

Three canonically pinned TRAIN targets were materialized for direct inspection
without pixel edits. The heated-beaker FINE_HATCHING target combines mesh detail
with substantial gray gradients; the first sorted CLEAN_CONTOUR cart includes
gray faces and an arrow; the first RESTRAINED_TONE apparatus contains a gray
tabletop/hand scene. This motivates a whole-cohort visual/caption/style audit,
**not** automatic relabeling, exclusion or a proven causal defect. No additional
training run, inference sweep, HOLDOUT read, data deletion or production change.
Next authorized work: inspect all100 frozen TRAIN targets and training text
capacity/conditioning alignment, preserve all historical labels/pointers, and
write a bounded successor hypothesis only from actual findings. Do not assume
that more optimizer updates or different ratios are the next fix.

Own review, two comparative viewing sheets, result pointers, logs and exact
temporary operators are archived as **45 members/2,608,414bytes**, all rereads
equal: `artifact_1d79e594fe9a4d8aa7906cdf5a14ef67` /
`rev_8687192e73ce4448bcc5d88245fe9af4`, primary `reports/own-review.json`,
schema `operations/plain-text-log/1.0`, text/plain, SHA
`sha256:a8a2f9e9ea96f6bebb4e77b90d546e38799dc9be716a028a930aa54e000729cc`.
This is an operations record, not a new worker contract. Dataset PNGs, adapter
weights and raw model outputs are referenced, not recopied into the archive.
The first archive preflight rejected three group-writable local pytest logs
before publication/job creation; permissions were tightened only on those
named evidence files and the unchanged report/key was published. The original
failure is preserved in the45-member archive. Five services active, no active
image unit, production binding SHA unchanged, whole goal ACTIVE.

## 2026-10-06 whole-cohort visual/caption audit (06:31 UTC)

The follow-up actually read all100 frozen TRAIN PNGs through ten existing
bounded, indexed Orchestrator resolution calls. Ten explicitly headed contact
sheets are derived viewing assets, not model outputs or a replacement image
store. Root viewed all100; scientific correctness of every example is **not**
established by that screening. Existing measurement rows keep their original
`PENDING_OWN_VIEW` value; a separate own-review operations record records the
subsequent completed view, rather than rewriting that measurement snapshot.

Two actual installed slow AutoTokenizers performed200 CPU/offline checks:
31–54 tokens including special tokens, capacity77, overflow0. No tensor or
pipeline loads, training, inference, GPU call or HOLDOUT read. Protected model
stack file hashes were validated; this is not a claim that no weight-file bytes
were read. The current training `_prompt_embeddings` already uses
`truncation=False` and rejects overflow with `IMAGE_TRAINING_CAPTION_TOO_LONG`.
Silent caption truncation is not a reproduced defect; no redundant guard added.

The frozen cohort is17 contour /8 hatching /75 tone, with73 isolated-object /
27 authored-scene targets. Actual institutional images include flat gray,
gradients and meaningful backgrounds. CLEAN_CONTOUR does not guarantee binary
interiors; hatching examples can combine ink texture, solid details and tone.
Some preserved sources also contain leaders, arrows, lettering or a page cue;
captions often acknowledge them. The heated-beaker source/caption includes all
apparatus components, so the observed free-generation topology failure is not
explained by a visibly missing component in that target. These are reviewer
observations and selected examples, **not** an exhaustive annotation-count
inventory, automatic relabeling, exclusion or scientific-content approval.
Histogram bins only describe pixels; they are not rejection/quality thresholds.

All100 targets, labels, captions and pixels remain unchanged. The audit does
not prove that tone exposure is the unique cause of weak generated lines.
Balanced exposure also changed scene exposure. Photo control retains interior
texture, so another training run or wholesale binarization is not the next
evidence-backed action.

Evidence:22 members/4,370,987bytes, every canonical reread byte-equal:
`artifact_19bd6ca591b74eec9f100e4caf702a14` /
`rev_e036d30a73bd4721a5d3769f9451506a`, primary `reports/own-review.json`,
operations/plain-text-log/1.0, text/plain, raw SHA
`sha256:416dd0927dd9a3db13ea784969d9dea9e04268b5ec8d0bd4393eef90261067cc`.
No original PNG or adapter weights were duplicated into the archive. CPU
histogram/tokenizer harness guards and one positive/six negative own-record
guards PASS; these synthetic checks are distinct from the200 real token checks
and the100 actual views. Two local archive permission preflights stopped
**before publisher/job creation**: first a group-writable test log, then new
operator/test source files. Only named local evidence permissions were tightened;
the same frozen review bytes/key were published. Both failure logs are retained
in the22-member archive. No state/DB edits or relaxed security guard.

### Initial bounded prompt-only successor design

Use the existing photo-style plan/command1.5 with one licensed wagon case
`imgsdxlcase_b5ebe1d385727ab5f16a59bd56fda90e`. It is not a reserved corpus
example. Replace only the generic positive style sentence with the exact native
training cues `clean contour lines, plain white background`; retain the subject
instruction, negative prompt, reference revision, retained region, initializer,
control tensors/window/scale, seed, balanced adapter and numerical recipe.
This tests the **positive style prompt package**, not the causal effect of one
individual token, and is not a new training exposure/parameter sweep.

Ownership remains Orchestrator plan resolution/publication/staging -> isolated
comparison worker -> Orchestrator result validation/commit. Old plan/result/
adapter pins remain canonical and immutable; new prompt bytes require new
content-derived plan/command identities and hashes, never mutation or replay
under the old identity. Resolve exact existence, lifecycle, permission, media,
schema and hashes with existing typed readers. Dominant operations are exact
key lookup and ordered two-output manifests: O(1) lookup, O(input bytes) staging,
bounded O(2) output iteration. No queue/cache/DB/index/dependency/schema change.
Existing idempotent publication and GPU lease own concurrency/side effects.

Before dispatch, validate existing JSON Schema2020-12/Pydantic/canonical bytes,
actual positive/negative tokens with both installed tokenizers, and reproduce
unchanged conditioning/initializer/source hashes in installed-role CPU preflight.
One command, one seed, one dispatch, two new outputs (BASE and balanced LoRA),
zero training updates, no automatic retry. The protocol ceiling remains12;
this finite one-case execution admits only2 and must assert that count. Prior
canonical BASE/LoRA outputs are comparison inputs, not regenerated baselines.
Failure preserves history and stops; do not create another key to bypass it.

Compare each new variant against its own prior variant: clearer structural
contours and reduced irrelevant texture must not worsen silhouette, visible
wheels, proportions or position. Improvement in both BASE and LoRA is a prompt
effect, not proof that LoRA alone learned better style. No improvement means
reject this hypothesis, not blindly train longer or change several controls.
Simpler alternative: do not retrain. The two-output check is cheaper and avoids
discarding useful institutional images. Production binding stays unchanged;
own quality, independent review, HOLDOUT, Item/HWPX canary and activation gates
remain open. Goal ACTIVE.

## 2026-10-06 prompt-only successor executed and rejected (06:46 UTC)

The preceding design was actually executed, without changing core source,
dependencies, schema bytes, training data, numerical recipe or production.
Plan/command1.5 admit one case with fresh content-derived identities. Because
prompt bytes contribute to case identity, the wagon case became
`imgsdxlcase_108a56b944f518d9836938b8d98e1e72`. Its physical source and region
are unchanged; the successor own-review evidence explicitly carries the old
case/source review forward, not a new independent review. Configuration
anchor/adapter remains exactly the previous balanced trial.

Installed lab RECORD/role verification PASS;76 staged members were checked.
Both actual offline tokenizers read positive55/negative37 tokens, capacity77.
Installed-role CPU source/conditioning/white-initializer hashes match the old
wagon exactly. One dispatch, no retries or training, run
`imgsdxlvalcmprun_d9020837b6fc45afec18efb4afed73bf`, semantic command SHA
`sha256:5103b33dc2b602d561e787373d16e22f061b3d018a1caffdd68a1d056a9b0df4`.
Two outputs SUCCEEDED in20,359ms, peak10,763,033,600bytes. Result was committed
as seven members, all reread equal, `artifact_35b6a9a3403f49cfad78a86fa8d2abc2`
/ `rev_b1e55ed1b08c45abbc3dcf84b375b3ed`; result raw SHA
`sha256:fc798bf0c619f9252ffc2edfed8ab9ad6ca64491f05608bc023d9895c384678a`,
semantic SHA
`sha256:175747c1e3450948bc1a75eb024863ed7a8c61d0794662e9ee18b8e4e47d048d`.

Nine canonical image rereads cover one source photo, two historical final/two
raw results and two new final/two raw results. Comparison labels explicitly
separate the photograph from generated images. Source, control trace, adapter,
seed and negative instruction match; only the positive style sentence changed.
Installed-role terminal replay preserves83 file SHA/mtime identities with no
model call, GPU lease, source transform or write.

Actual own visual decision: **NOT_ACCEPTED**. The approximate right-facing
silhouette/two-wheel form remains recognizable, but new LoRA is paler and still
retains photographic ground/background texture. New BASE is not good exam ink
either. Dark-fraction milli BASE8->3 / LoRA4->1 and grayscale MAE4.639605 /
3.83109 are descriptive measurements, not quality scores. White outer borders
do not prove a clean internal background. Exact native style wording is not
a sufficient fix in this case; neither global quality nor LoRA-alone improvement
is established. No next sweep/training restart automatically follows.

Two positive/four negative pure fixture checks PASS. The first fixture used
`+00:00` instead of canonical `Z`, causing identity/hash mismatch; corrected
fixture passes, while the actual producer used `Z` from the first plan. The
first publication handoff lacked its saved local command value, so no publisher
ran; the same terminal run was then published, with no model redispatch.
An unused temporary dispatch-operator import was removed only **after** its
exact executed bytes were canonically archived. No worker/core workaround.

Own review, derived comparison view, exact execution operators, typed pointer
reports and logs:22 members/664,453bytes, every canonical reread equal,
`artifact_59b556e92b8b4f10becbac1d76c4ef98` /
`rev_0502ebe022934068b02c70a45b585923`, primary `reports/own-review.json`,
operations/plain-text-log/1.0, text/plain, raw SHA
`sha256:ee60b12e07e32c029e3c753eb65f11f2084ce8bffd5e9aaf4f977dc76f36e83d`.
Original source PNGs, adapter weights and raw generated outputs are referenced,
not duplicated into this operations archive.

Next authorized task is **read-only CPU spatial-input route inspection**: resolve
the existing source/conditioning/initializer pointers, view the actual control
edge map and reviewed region boundaries, and trace which interior details or
background cues survive rectangular retention. Check polarity/recipe against
the pinned controller configuration and preserved historical alternatives
before proposing a new bounded hypothesis. No new mask, automatic exclusion,
relabeling, training or inference is authorized by this diagnostic record.
The observed gray texture does not prove control or data tone is the sole cause.
Scientific overlays remain typed/deterministic, not GPU text. Five services
active, no active image unit, production binding unchanged. Independent/blind
review, untouched HOLDOUT, final Item/HWPX canary and activation remain open;
goal ACTIVE.
