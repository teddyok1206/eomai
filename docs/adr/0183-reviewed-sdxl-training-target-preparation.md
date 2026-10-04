# ADR 0183: Prepare reviewed SDXL TRAIN targets without rewriting source crops

Status: accepted design; runtime, target inspection and subsequent training are separate gates.
Date: 2026-10-04 UTC.

## Boundary, source and identity

The 16 actual micro targets are small on their canvas and include heterogeneous source marks,
cropping and expression types. A CPU-only preparation step produces inspectable candidates,
not final illustrations or an automatically eligible training dataset. Do not reinterpret the
old `GRAYSCALE_REDACT_FIT_768X512/1.0` policy or edit its images, command, masks or result.

The canonical sources are the pinned successful SDXL micro command/result and their reviewed
crop set/authorization. A new command records one explicit prepare/defer decision for every
original TRAIN sample. Prepared entries pin reviewed framing, source-coordinate white masks and
expression class. Deferred entries have a reason, no pixel-transform fields and no output PNG.
Source captions, document/group partitions and original sample identity stay unchanged.

`preparation run -> immutable command -> original command/result pointers -> source crop`
produces `target logical ID -> target revision -> PNG hash` inside one immutable result Artifact.
Target logical identity binds source pointer and preparation recipe; revision binds pixels and
caption. Raw document hash, semantic command/result hash and Artifact revision remain distinct.
Pointer admission checks exact member/schema/media/hash, lifecycle and original TRAIN ownership.
No VAL/HOLDOUT pixels are materialized. Missing source parts are deferred, never reconstructed.

## Transformation and data structures

The new policy retains grayscale/white canvas, an explicitly reviewed rectangular crop and exact
white masks. Fit into 768x512 with 32-pixel margin, LANCZOS and a pinned 1x–4x maximum enlargement.
Preserve aspect ratio using integer rational geometry. No thresholding, inpainting, edge detector,
shape invention or automatic annotation removal. Caption expression is explicit; dense texture or
scientific geometry may be deferred without claiming the original institutional image is wrong.

Dominant access: immutable ordered 16-entry snapshot, indexed pointer lookup, set membership,
one source map and one bounded batch of only prepared PNGs. O(n + selected bytes), n <= 16;
linear sequential image memory and no new DB table/index/cache/queue. Output placement is a small
frozen value object. Existing Orchestrator metadata publication and file-set commit own persistence.

## Concurrency, dependencies and failure

Contracts/pure geometry and source/result validation contain no filesystem, Pillow, DB or subprocess
imports. Orchestrator admits full existing lineage then stages bounded source members. The trainer
CPU application owns pixel decoding/materialization and emits a terminal local receipt. A fixed
isolated oneshot has no GPU/model/network/NAS/repository/secret access. CLI only composes the use case.
No new dependency. Pin Pillow version in the command and verify it before transforming pixels.

Exclusive workspace creation prevents a second writer. Canonical receipts and every output hash
are checked before replay, without transformations. Partial/unreceipted outputs are explicit errors;
an ambiguous dispatch is observed under the same identity, never automatically resubmitted. Failure
preserves an execution-prefix receipt and the declared deferred population. Only Orchestrator commits
validated declared members, using existing idempotent Artifact publication. No production activation.

The simpler in-place resize/mask change would invalidate the old training evidence. An arbitrary
image-editor framework, second registry or unbounded target repair is unnecessary. Subsequent SDXL
training must explicitly pin and admit the new target revision; the released trainer cannot silently
consume it. Eight prepared examples are not 100–200 independent examples or a quality acceptance.

## Gates

Define JSON Schema 2020-12 before worker code. Test canonical identity, original TRAIN membership,
duplicate/stale/hash/source failures, exact rational fit/mask containment, cap/geometry, unchanged
legacy pixels, decode/runtime failures, terminal-prefix/replay and handoff/packaging boundaries.
Then execute one CPU preparation and inspect each real candidate. Report source/data shortages and
rejected/deferred members honestly. No inference uses the exhausted 12-output diagnostic cohort.
