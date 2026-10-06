# ADR 0206 — Explicit native style exposure without changing the target cohort

Status: implemented and installed in the isolated lab; one trial started, not a quality acceptance or production activation.
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
