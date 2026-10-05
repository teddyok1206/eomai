# ADR 0198: Native adapter in the existing source-initialized comparison

## Decision and current evidence

Protocol-first successor, 2026-10-05 UTC. The native23 adapter's four-arm diagnostic
rejected24/24 publication outputs. Six additional source-derived targets are now
prepared and inspected; they are not generated examples or proof of model quality.
The already implemented source-initialized Canny path preserved composition better,
but its released reference1.0 consumer selects only the historical micro adapter.
Add explicit reference-command/result1.1 support for native adapters to compare
these factors without retraining first or silently relabeling old training output.

## Boundary, canonical source and identity

Reuse the existing reference command's exact spatial command/result pins, reviewed
TRAIN cases, source initializer, Canny controls, prompts, seed, timestep recipe,
six-output/resource caps and paired inference owner. Add one pinned native
evaluation-command1.2 pointer. It supplies already closed native training/result/
adapter-manifest pointers and strength; it does not authorize its old evaluation
cases or consume their pixels. Native and historical base-model pointers must
match. Historical spatial cases remain the actual comparison cases and are not
called a holdout evaluation. This is an adapter substitution, not a new framework.

Logical run/revision/raw SHA/semantic SHA remain distinct. Successor results bind
the native evaluation command and native adapter manifest hashes in addition to
the inherited source/conditioning/initializer/output hashes. Old schemas, receipts,
adapter files and model activation remain unchanged. Canonical source is registered
Artifact revisions, never filenames or implicit latest references.

## Admission, structures and ownership

Before any source/control/adapter binary reads, the Orchestrator validates complete
historical metadata and native training lineage through their existing owners:
existence, permission, immutable lifecycle, exact revision/member/media/schema,
canonical serialization/raw/semantic hashes, chronology, successful training,
authorized use and matching frozen corpus basis. Only the chosen native adapter
files are materialized; old adapter metadata stays as history but its weights and
native training PNGs are not copied into the comparison workspace.

Use keyed metadata maps, sets for exact closure and immutable typed source records.
At most three existing cases/six outputs; native training metadata remains bounded
by its existing cohort contract. Metadata traversal is linear in distinct pinned
members; indexed resolution and bounded batches own I/O. No DB/index/queue changes.
Domain/contracts do not import adapters. Orchestrator owns full-lineage admission,
staging and canonical publication; the existing isolated provider validates staged
metadata, owns local numerical work only and never writes NAS/DB.

## Failure, replay and simpler alternatives

Reuse command-keyed workspace, shared GPU lease, paired inference, stable errors,
FAILED receipts and transform/model/write-free terminal replay. Unknown completion
blocks redispatch. Invalid native metadata must fail before binary materialization;
no fallback to the old adapter. Reuse the existing CLI/systemd entry point and
backend, with closed schema dispatch. No numerical dependency or service is added.

Silently replacing micro weights would falsify provenance. Copying the inference
runner creates a competing owner. Generalizing every predecessor contract is
unnecessary: one explicit successor preserves the actual comparison inputs and
changes only the selected adapter. Independent quality, broader corpus/families,
held-out evaluation and Item/HWPX/activation remain separate unfulfilled gates.

## Required evidence

Schema2020-12/Pydantic equivalence and old schema bytes, missing/stale/hash/time/
model/basis/native-family rejection, metadata-before-media, native-only weight
staging, exact workspace closure, successful/failed paired output and immutable
terminal replay, existing legacy/validation paths, packaging/RECORD/source-free
role import, then one frozen bounded comparison. No live model run is implied by
source tests or this design note.

## Source implementation checkpoint

Reference1.1 schemas were defined before behavior and mirrored into release packages.
The closed consumer, metadata-first native lineage admission, native-only adapter
materialization, existing runner/CLI handoff, native result identity and terminal
replay are implemented. Focused/compatibility regression163 PASS, including21 new
native-reference cases. Strict mypy7, Ruff/format8, shell syntax and diff checks PASS.
Initial fixture failures (missing inherited fixture metadata and counting setup
reads) were corrected without relaxing admission; the rerun also uses distinct
native Artifact identities so old/native weight provenance cannot be confused.

The full dependency audit remains5 PASS/1 pre-existing Catalog planning import
violation in `source_page_crop_expansion_inputs.py`. No new cross-layer import or
cycle is introduced; do not report a whole-repository PASS or suppress the failure.
Actual wheel-only Python3.11 import, installation, bounded GPU execution and image
quality remain subsequent evidence. Production binding and lab runtime are unchanged
at this source checkpoint. The6 prepared new targets have not been trained here;
the next adapter diagnostic may use the already completed native23 training result.
