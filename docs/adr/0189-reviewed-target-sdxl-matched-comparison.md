# ADR 0189: Compare reviewed target references with one isolated SDXL pair

Date: 2026-10-04 UTC

Status: implemented and actual six-output GPU comparison/publication/replay verified;
all six native outputs own-REJECTED; independent review NOT_PERFORMED.

## Boundary and decision

1. Responsibility: extend the existing isolated paired-comparison owner. New
   `local-image-sdxl-target-comparison-{command,result}/1.0` contracts describe
   actual prepared-target inputs, not a rewritten historical baseline. Reuse the
   existing paired systemd template, GPU lease, secure handoff and publication.
2. Canonical source: the pinned successful reviewed micro command/result 1.1,
   adapter manifest/files and exact approved preparation target PNG revisions.
   Prepared targets are reviewed derivatives of literal institutional source
   pixels; they are not claimed to be unprocessed originals or new AI drawings.
3. Identity: each case retains source logical ID, target logical/revision ID,
   target Artifact/revision/member/SHA, expression and prompt hashes. New command,
   run, generated conditioning and output hashes remain distinct. The old baseline
   command is numerical/prompt provenance only; its historical outputs are not
   claimed to have used these new references.
4. Resolution: metadata admission precedes any target/adapter materialization.
   Re-admit the full approved source lineage and TRAIN-only target preparation.
   Cases must exactly match training target identities/revisions/hash/expression;
   this closed initial contract says `REVIEWED_TRAIN_TARGET_NOT_HOLDOUT` and cannot
   declare unseen-source/generalization or independent quality PASS. Later
   held-out source admission must be an explicit distinct boundary, not a flag
   that silently loosens this TRAIN contract.
5. Access patterns: keyed target membership, ordered immutable case/arm iteration,
   batched indexed Artifact resolution, deterministic handoff and terminal replay.
6. Structures: maps/sets for target membership and duplicate identities/pixels;
   sorted tuples for up to three case/seed inputs, two fixed BASE/LORA arms and
   at most six generated outputs. Existing metadata/Artifact stores; no new table,
   queue, persistent cache, registry or index.
7. Scale/complexity: O(n) bounded metadata and O(total admitted bytes) materialization;
   up to 96 existing training targets are read as metadata only. Stage only the
   selected target PNGs and two adapter files, not the whole training dataset.
8. Concurrency: one exclusive workspace and one existing GPU file lease per pair.
   Fresh independent BASE then LORA pipelines prevent adapter contamination.
   Only Orchestrator validates/commits output members; workers have no NAS/DB.
9. Direction: pure contracts own source/result invariants; Orchestrator owns
   resolution/staging; the existing numerical backend and a shared pair-inference
   function own generation/budgets. Legacy learned-conditioning comparison and
   new target-reference comparison keep their own truthful input/result models
   while sharing the numerical loop. No new dependency or external model API.
10. Failure/retry: protect canonical bytes, preserve partial failed evidence,
    refuse unreceipted output, never invent new identity on timeout. Replay checks
    command/source/input/conditioning/output hashes without model calls or writing
    files. Old diagnostic 12/12 and new legacy-cohort 12/12 remain exhausted; freeze
    a distinct small clean-input cohort before any fresh generation.
11. Simpler alternative: bypassing the resolver with paths, pretending targets are
    old crop-set members, loosening baseline 1.0/evaluation 1.1, or copying the
    inference lifecycle would obscure source meaning and weaken maintenance.
    A closed new input contract plus the existing shared execution owner preserves
    history and makes the actual clean-target comparison reproducible.

## Initial experiment and gates

Use at most three own-screened CLEAN_CONTOUR targets from separate source groups,
one fixed seed and the same approved model/settings/prompts on both arms. This is
an input/style diagnostic, not representative product quality or a substitute for
the goal's reserved-source independent evaluation. No new training in this step.
Scientific labels/units/axes/geometry remain Python/SVG/native HWPX responsibility;
raw generation and publication crop remain separate declared output members.

The initial frozen candidate cohort is PEDESTAL_FAN, FLOWERING_PLANT_WITH_ROOTS
and KICK_SCOOTER_WHEEL_LIGHTS from three different source documents/exam groups.
Direct target inspection preceded selection. Six outputs are the ceiling; no
training steps are added. These source derivatives belong to TRAIN and are not
used to claim generalization.

Source gate caveat: the repository-wide
`test_domain_and_platform_packages_do_not_import_catalog_infrastructure` test
already fails at the unchanged baseline because
`source_page_crop_expansion_inputs.py` imports two Catalog application modules.
The new contract/provider/admission files add no such imports. Keep the actual
failure evidence and a separate boundary-maintenance backlog; do not describe a
filtered regression run as an unqualified repository-wide PASS.

CPU evidence (2026-10-04): focused/new/legacy/provider/trainer/handoff plus six
unaffected dependency-boundary cases: 386 PASS, one explicitly deselected
pre-existing failing case. Strict mypy: nine changed source modules PASS.
Formatting, lint, shell syntax and diff checks are separate release gates.

Actual run: `imgsdxltargetcmprun_cc970021ebb2599641b46a761e3ea703`, 30,383ms,
peak allocated GPU 8,328,740,352 bytes; six outputs/three conditionings. Registered
result `artifact_566856b16d3f454a825b20aa37a40a8c` /
`rev_f9f58bc9073d4d66b04fd71cb5b4640d`; all 16 members match workspace bytes.
Grid artifacts decrease, but gray canvas/fills/rough contours remain, so the new
6/6 quota is exhausted without quality PASS. Installed new/legacy replay is
zero-model/zero-write/no-Torch. Operating V6 and all five services unchanged.

Schema-first tests must cover old/new isolation, missing/stale/hash/schema/media
pointers, duplicate identities/pixels, wrong source/target revision/expression,
scope/chronology/budget failures, full-lineage-before-pixels ordering, secure staging,
one GPU lease/two uncontaminated arms, partial failure, exact replay, wheel resources
and dependency direction. Metrics and direct native-output inspection are separate
from independent blind review. No activation or Item/HWPX canary before quality PASS.
