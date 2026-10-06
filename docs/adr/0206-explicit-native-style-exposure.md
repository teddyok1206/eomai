# ADR 0206 — Explicit native style exposure without changing the target cohort

Status: implementation candidate; not deployed, not a quality acceptance.
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
