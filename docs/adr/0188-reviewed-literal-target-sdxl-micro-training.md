# ADR 0188: Train SDXL from reviewed literal-source targets

Date: 2026-10-04 UTC

Status: implementation; live training and quality acceptance not yet recorded.

## Boundary and decision

1. Responsibility: extend the existing isolated SDXL micro trainer, not a second
   trainer, queue, or production image provider. The successor command/result are
   `local-image-sdxl-lora-micro-{command,result}/1.1`. Released 1.0 bytes and its
   exact sixteen original micro inputs retain their meaning.
2. Canonical source: registered literal source crop set/review, authorization,
   preparation commands/results, and their 768×512 target PNGs. Own screening is
   preparation for an evaluation-only experiment, not independent quality approval.
3. Identity: source selection, target logical/revision identity, preparation
   Artifact revision, raw PNG SHA, command semantic SHA, and resulting adapter
   logical/revision identity remain separate. The existing adapter manifest 1.0
   still describes the same two immutable UNet adapter files and needs no successor.
4. Resolution: pin every preparation command/result and target member. Revalidate
   source lineage, frozen TRAIN assignment, chronology, recipe, target identity,
   caption, dimensions, media, lifecycle, permission, and SHA before GPU admission.
   No latest substitution or historical repair. Workers receive only metadata and
   selected target PNGs; they do not resolve NAS/DB pointers themselves.
5. Access patterns: keyed source/target membership, ordered immutable training
   iteration, bounded indexed Artifact reads, and idempotent terminal replay.
6. Structures: sorted tuples for batches/samples, maps/sets for membership and
   duplicate checks, existing batched Artifact resolver. No new persistent table,
   dataset registry, cache, or index. The command is the frozen dataset manifest.
7. Scale: 1–96 targets and 1–8 preparation batches; O(n) validation/staging memory
   and work, bounded metadata and PNG reads. The initial cohort has 38 sources;
   rejected first revisions are not independent training examples.
8. Concurrency: existing exclusive workspace creation, GPU file lock, isolated
   systemd template, sole Orchestrator Artifact commit, and content-addressed replay.
   Installation holds the same GPU lock; no concurrent production GPU mutation.
9. Direction: contracts contain pure models/validation; Orchestrator resolves and
   stages; trainer securely reads and trains; numerical backend has no DB/NAS or
   orchestration behavior. No external model API or new dependency.
10. Failure: successor inputs are already transformed. Training uses their exact
    bytes with no second resize, masking, or PNG rewrite. Result realized hashes
    equal admitted target hashes. Failure/cancellation preserves partial evidence
    and never admits an adapter; replay verifies referenced targets and adapter
    members without training again. The old exhausted 12-image diagnostic budget
    is not reused; each new experiment must pin a bounded, distinct cohort first.
11. Alternative: relabeling 38 targets as old sixteen crop inputs or copying the
    runner would obscure provenance or duplicate lifecycle rules. A closed
    successor plus shared runner/numerical backend keeps the genuine boundary.

## Acceptance

Source gates must cover old/new schema isolation, caption/pointer/revision/hash
mismatch, TRAIN-only lineage, duplicate inputs, secure staging, exact-byte replay,
failure/cancellation, dependency direction, and frozen numerical recipe. Live
evidence must distinguish actual 200-step training from CPU test stubs, report
resource usage, preserve historical results, and leave production V6 unchanged.
Matched evaluation and independent blind review remain separate quality gates.

## Source checkpoint

Focused successor, legacy micro runner/admission/contract/backend, target
preparation, workspace and publication tests: **189 PASS**. Strict type check of
eight core/operator source files and formatter/linter PASS. Released command,
result and adapter-manifest 1.0 schemas remain byte-identical. No new dependency,
schema migration, service, or production provider activation.

Initial actual execution is bounded to one new 38-source cohort, one 200-step
training run, maximum 3,600,000ms and 16GiB peak allocated GPU memory. Comparison
is a separate pinned command, not reuse of the exhausted old 12-image diagnostic
allowance. Operational lab installation and actual numerical result are still
pending at this source checkpoint.

## First comparison boundary

The initial follow-up is an explicitly named **legacy TRAIN reference diagnostic**,
not holdout or generalization acceptance. An evaluation command/result 1.1 pins
the new training command/result while retaining the existing baseline command,
its prompts, original reference PNGs, seeds, model and numerical settings. Exact
historical BASE pixels may be reused only when those pins match. Released 1.0
evaluation still requires its original sixteen TRAIN inputs; it is not loosened.

The Orchestrator re-admits the new training metadata's full source lineage without
re-reading/staging all 38 training PNGs, and separately re-admits the baseline's
original TRAIN references. The worker resolves neither source independently.
One successor execution generates only the baseline's declared case/seed outputs;
the command fixes this new cohort's usage before inference. Original validation
and holdout pixels remain unopened. A quality result on damaged legacy inputs
must retain that limitation and does not replace later clean target/held-out review.

Successor diagnostic + original micro/evaluation/learned-comparison/target/
workspace/publication regression: **290 PASS**, formatter/linter and strict types
of six affected source files PASS. Shared read-only training-source admission
returns typed metadata/targets; evaluation does not materialize training PNGs.
These remain source/CPU gates, not independent image-quality acceptance.

## Replay ownership correction

Actual installed-worker replay exposed a boundary mismatch: prepared targets are
Orchestrator-staged, root-owned 0440 inputs; the original runner's regenerated
`runtime-dataset` crops are worker-owned outputs. Successor replay incorrectly
required the worker UID for both. Match successor replay to the first-use staged
input reader, retaining pinned hash, bounded regular-file read, no symlinks/hard
links, non-group/world-writable modes and unchanged worker ownership checks on
results/adapter outputs. Do not chown input files, regenerate targets, retrain or
alter the committed terminal receipt to pass replay.

The ownership regression reproduced before the fix; changed hash, writable target
and symlink negatives remain mandatory. Focused successor/legacy runner/admission/
contract/evaluation tests: **102 PASS**, formatter/linter and strict runner types
PASS. Broader training/evaluation/target/workspace/publication regression: **298
PASS**; overlapping suites are not added together. Actual installed replay after
the corrected wheel is a separate live check,
not inferred from same-owner developer fixtures.
