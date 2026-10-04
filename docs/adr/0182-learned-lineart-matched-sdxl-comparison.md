# ADR 0182: Match SDXL base/LoRA against an explicit learned-conditioning receipt

Status: accepted design; installed execution and quality acceptance are separate gates.
Date: 2026-10-04 UTC.

## Responsibility and canonical source

Continue ADR 0181, not a new production renderer. The Orchestrator admits an immutable original
SDXL command, successful learned-extraction command/result and existing LoRA evaluation/training
provenance. An isolated provider runs the two actual BASE/LORA arms through the existing SDXL
backend. Only the Orchestrator commits validated outputs. No worker NAS/DB/network access,
service-to-service bypass, new queue/framework/migration or production binding is introduced.

The original approved TRAIN crop, prompt policy and baseline command remain canonical. The
extraction receipt owns the derived conditioning members. The existing training receipt owns
the adapter. A new comparison command pins these documents; it never calls a derived PNG an
original crop or changes the old FIT_GRAYSCALE_INVERT policy. Prompt text, seed, SDXL/T2I/VAE,
steps, CFG, T2I scale, fit/crop geometry and adapter strength stay the pinned baseline values.
Only conditioning extraction and the explicitly named BASE/LORA arm differ from older results.

## Identity, pointers and data structures

`imgsdxllearnedrun -> immutable command -> baseline/extraction/evaluation pointers` produces an
independent result with ordered arm/case/seed outputs and original/conditioning SHA provenance.
Up to three case IDs and one original seed give at most six outputs. The actual first cohort is
two existing TRAIN subjects x one original seed x two arms = four, inside the six remaining
follow-up outputs. No old generation/training is replayed to populate this cohort.

All documents use approved Artifact Revision/member/schema/media/raw SHA pointers. Original
logical model/revision/semantic manifest SHA and extraction semantic result SHA remain separate.
Metadata lookups and case/output selection use indexed queries and maps; membership uses sets;
execution order uses immutable tuples. The existing bounded batch member resolver reads only
selected conditioning PNGs and the two adapter members after all lineage is admitted. There is
no need to materialize original PNGs again in this worker. Scale is constant metadata, at most
three PNGs and one bounded adapter; complexity is O(metadata members + selected bytes).
The batch resolver's member bound extends from PNG-only 32 MiB to the existing LoRA file limit
64 MiB, with a new 128 MiB aggregate ceiling checked before queries/reads. This admits the real
46.6 MB adapter without removing bounded materialization or adding a parallel adapter reader.

## Concurrency, dependency direction and failure

Reuse the exclusive root-to-worker handoff in the trainer workspace root. The existing physical
GPU lease covers both ordered arms. Load one fresh pipeline per arm, not a mutable global model
or a LoRA-modified pipeline reused as BASE. Model resolution is shared once for the command;
separate per-arm tensor loads preserve clean policy isolation and bounded memory. Reuse current
offline trainer SDK, sandbox and fixed oneshot template; add no privileges or dependencies.

CLI -> comparison application -> pure source/result validation; existing SDXL numerical,
filesystem and Orchestrator persistence adapters retain their responsibilities. Share the
existing publication crop helper as a public provider function for these two real use cases.
No contract/domain import of numerical, DB, filesystem or subprocess adapters is permitted.

Success requires exact ordered coverage and matching conditioning/original hashes, model and
source identity plus measured time/memory budgets. Failure keeps a terminal prefix receipt;
historical failures are not reclassified. Check complete receipts before model/GPU access on
replay. Verify every output hash, PNG structure and publication crop. Unreceipted partial output
is an explicit error, never permission for an automatic rerun. An ambiguous dispatch is observed
under the existing identity; no new key is submitted. Existing control publication owns DB/NAS
idempotency and concurrency; no additional persistent aggregate is needed.

The simpler alternative of reusing the old command and replacing its PNG violates source
identity and conditioning semantics. A generic multi-arm experiment scheduler is unnecessary
for the fixed BASE/LORA pair. Runtime rollout/rollback remains trainer-contract/provider only;
the operating V6 renderer, prior artifacts and service release set remain untouched.

## Evidence and remaining goal

Require schema/Pydantic/source-hash agreement, invalid lineage/duplicate/seed/member negatives,
exact batching and handoff, source dependency gates, success/prefix/replay/time/memory tests,
wheel RECORD and protected worker identity, then one actual four-output comparison. Inspect all
new images against the pinned older same-seed results and keep diagnostic metrics separate from
own and independent blind review. Rejected outputs never authorize an Item/HWPX canary or model
activation. Full-data expansion, independent quality review and a passing canary remain open.

Source gate, 2026-10-04 UTC: isolated image suite 363 PASS; focused pure contract/admission/
handoff/compatibility suite 147 PASS; dependency boundaries 6 PASS; strict type check eight
changed runtime/contract modules PASS; formatter/linter and shell syntax PASS. These results do
not imply installed execution or visual quality acceptance. The first actual comparison remains
four planned outputs (MICROSCOPE/RADIO, original seed 104729), not a new training run.

Installed/actual gate subsequently passed: one four-output dispatch, 24,213 ms, 8,328,740,352
peak allocated CUDA bytes; nine validated committed members; installed no-model/no-GPU replay
verified all eight PNGs. Own direct inspection rejected all four for gray background, shadows,
texture and source-frame defects. Independent blind review is NOT_PERFORMED. Follow-up budget
is now 10/12, not a fresh budget. Operating V6 stays unchanged. Canonical pointers, exact wheel
identity, metrics and evidence archive are recorded in the
[image-quality operation plan](../operations/IMAGE_STYLE_IMPROVEMENT_PLAN_2026-10-03.md).
