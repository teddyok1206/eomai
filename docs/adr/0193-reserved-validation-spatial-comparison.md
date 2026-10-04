# ADR 0193: Reserved VALIDATION spatial comparison

## Status and boundary

Accepted for implementation on 2026-10-04 UTC; not a runtime activation or quality
acceptance. The 14 reviewed literal crops are VALIDATION, not TRAIN. Existing TRAIN
command/result bytes and their exhausted fallback budget remain unchanged. This
diagnostic does not replace the independent blind review's four-family requirement.

## Source, identity and resolution

Add `local-image-sdxl-validation-comparison-command/result/1.0`. The command pins an
existing source-initialized Canny command as **numerical configuration only**. Its
accepted predecessor history supplies the model, controller, LoRA, initialization,
prompt-source provenance and seed. Historical TRAIN cases are never generation inputs.
There are no new sampler values to tune on VALIDATION.

New case authority is an explicit collection of V3 (`1.2`) original-page crop review/
set pairs, plus selection IDs and pinned literal PNG pointers. Native crop dimensions
are preserved in the case; fitting is a declared workspace-only transformation. All
canonical metadata, original/supplemental lineage, permissions, lifecycle, schema,
hashes, temporal order and partition are admitted before any PNG or adapter read.
Training documents, PDF hashes and exam groups cannot occur in the reserved cases.
Only selected members may be read; neither TRAIN reference PNGs nor HOLDOUT pixels
are materialized by this use case. Logical run identity, Artifact Revision and raw/
semantic hashes remain distinct. No implicit latest or schema relabeling is allowed.

## Access patterns, structures and scale

At most four set pairs, 12–16 distinct case/depiction/PNG identities, one frozen seed,
six or more original exam groups and 24–32 matched BASE/LORA outputs. Use immutable
tuples and maps keyed by set hash, selection ID, case ID and source group. Admission
is O(metadata + cases), with bounded metadata and PNG reads; no persistent aggregate,
database index, migration, queue, cache or new dependency is required. Canonical PNGs
are materialized once per selected case at the existing isolated workspace boundary.

## Ownership, concurrency and failure

Contracts own deterministic identities, membership and result-prefix rules.
Orchestrator application admission owns canonical resolution and staging; the isolated
provider owns numerical execution and local output only. Existing fixed GPU lease,
paired inference, offline model resolvers and Artifact publisher are reused. Workers
get no NAS, database, root auth or Git access. A new immutable command pins the complete
batch before execution. No parameter sweep, automatic retry, activation or export.
Failure preserves the exact BASE-then-LORA output prefix. Terminal replay validates
committed local evidence without loading a model or repeating transformations.
Replays use the same command identity and publisher idempotency boundary, not a new
run or direct database edits. Publication must readmit the same command and sources.

## Alternative and remaining gates

Relaxing the TRAIN-only contract or inventing prepared TRAIN targets for the new crops
would corrupt experiment membership and historical reproducibility. A small explicit
successor reuses numerical and storage boundaries without building another framework.
Own source inspection and an executed spatial diagnostic cannot establish LoRA benefit,
conversion from a novel photograph or institutional indistinguishability. Independent
blind evaluation, the missing fourth source family, the larger training/four-arm study
and an accepted Item Preview/HWPX canary remain separate unfinished goal gates.

## First implementation checkpoint

The schema/Pydantic models, deterministic case/result-prefix validation, metadata-only
configuration resolver, reserved-source admission and bounded selected-input preparation
are implemented. Focused new and historical comparison/crop/training/workspace/publisher
regression: 334 PASS; strict mypy: four changed source files PASS; Ruff format/check,
shell syntax and diff checks PASS. No new dependency or migration.

The numerical worker, fixed service handoff, result publication and actual reserved GPU
comparison are **not implemented/executed in this checkpoint**. The result wire format
is defined first to protect those later boundaries. No production installation or
activation follows from this source verification.
