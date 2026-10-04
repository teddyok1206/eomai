# ADR 0187: SDXL targets from reviewed literal source crops

Date: 2026-10-04 UTC. Status: Accepted for CPU-only implementation; no training or activation approval.

## Boundary and decision

Target preparation owns a temporary, deterministic materialization of reviewed TRAIN pixels.
The Orchestrator resolves registered source revisions and their original corpus lineage, stages
only explicitly selected PNGs, and owns publication. The existing isolated image trainer owns
CPU transforms and local results. It acquires neither database/NAS access nor model capacity.

The released target preparation 1.0 remains the exact historical 16-sample micro-run protocol.
A successor command/result 1.1 references **one** literal source crop-set revision (1.0 or 1.1)
and the unchanged authorization. Its ordered decisions cover every selection, including DEFER.
Separate crop sets can be prepared separately; a multi-set registry is unnecessary at this boundary.

## Canonical source, identities and resolution

Canonical inputs are the registered crop set, its pinned review and authorization, not a workspace
path or a previous training result. Selection identity, target identity, target revision, Artifact
revision, raw SHA-256 and semantic JSON hash remain distinct. Caption corrections do not create
another independent source drawing. A target revision includes output bytes, caption and geometry.

Root admission verifies existence, permission, lifecycle, exact released schema/media/member,
canonical JSON/raw hash, review/set coverage, chronology, original source document/candidate,
authorized frozen partition and duplicate-group inheritance before reading selected PNGs.
The worker rechecks the staged metadata closure and hashes; it cannot independently query NAS.
Every selection must be TRAIN, even when deferred. No implicit latest pointer or source ID rewriting.

## Access patterns and data structures

Bounded ordered iteration (1–512 selections), keyed selection/member lookup, set membership for
PREPARE and exact output closure. Tuples preserve ordering; dict/set provide O(n) validation and
lookup. Metadata is resolved once and selected PNGs in one bounded indexed batch. No DB schema,
index, queue or derived persistent counter is added. Space is O(n) metadata plus explicit bounded
workspace materialization; pixels are absent from DB rows and messages.

## Ownership, transactions and failure

Contracts remain pure. Existing source-lineage adapters perform root admission; filesystem and
Pillow remain worker infrastructure. The existing stage/dispatch/result-publication boundaries
are reused. No new framework or service is introduced. The existing rational fit, grayscale,
explicit white masks and 768×512/32px margin operation is shared without changing 1.0 semantics.

Content-addressed commands, exclusive workspace/output writes and exact terminal receipt replay
prevent overwrites. Replay verifies all output hashes and closure without transforming pixels.
Pillow drift fails before transformation; a failure records only its actual ordered output prefix.
Failed work is not rewritten as success. Unreceipted output, stale pointers, conflicting metadata
or hashes fail explicitly. Results are UNREVIEWED_TRAIN_TARGET_CANDIDATES and activation FORBIDDEN.

## Simpler alternative and gates

Relabeling these drawings as the old 16 samples would falsify history; preparing unregistered loose
PNGs would bypass source and partition checks. Conversely a generalized trainer/dataset framework
would duplicate existing ownership. Two closed wire versions and one CPU runner meet the current need.

Required tests: old bytes and behavior, successor schema/model agreement, missing/stale/hash/schema/
partition/chronology/coverage negatives before pixels, selected-only staging, exact replay, failure
prefix, runtime drift, canonical result/target revision and installed wheel/sandbox support.
Actual target pixels need own review and near-duplicate assessment before a separate corrected-data
training/evaluation cohort and usage authorization. Source publication and CPU preparation grant
no fresh GPU allowance; the old diagnostic 12/12 remains exhausted. Independent review, quality
comparison, Item/HWPX canary and activation/rollback remain later goal gates.

## Source verification checkpoint (2026-10-04 UTC)

Focused successor + legacy target/source/admission/workspace/micro-run/control-publication suite:
**207 PASS**. Formatter, linter and strict type checks of five core files pass. These are CPU
fixtures, not installed-runtime or actual drawing-quality acceptance. No dependency was added.
Both released 1.0 schemas remain byte-for-byte unchanged.

Own comparison of nine proposed outside-object masks rejected the monkey recipe because the
rectangle interrupted its shoulder contour. Its registered literal pixels and prior source review
are preserved. The initial actual successor preparation will therefore use 41 PREPARE and
31 DEFER decisions covering the exact 72-source snapshot, rather than pretending all 42 source
candidates already passed target review. Eight retained mask recipes require actual target review.

## Actual installed CPU verification (2026-10-04 UTC)

Source `965022f307c95d9ad85a31a09e37d93b4614e5f3` was built and installed only in the experimental
trainer (contracts/trainer wheels; provider distribution, production V6 binding and service units
unchanged). Installed RECORD, actual worker import/Pillow 11.3.0 and pip check PASS. No service restart.

Initial command produced 41 PNGs in 2,252ms; a separate 3-source correction command produced 3 PNGs
in 234ms. Both used the existing isolated CPU unit and full Orchestrator source admission, then
committed one result + its exact output members. Actual installed reconstruction was byte-identical;
terminal replay had zero transforms and Torch remained unloaded. Committed bytes equal workspace bytes.

Own viewing of all 41 initial and 3 corrected targets selected **38 sources = 35 initial + 3 corrected**,
from **26 PDFs / 25 exam groups**. The 3 corrections are new target revisions, not independent drawings.
The initial six flagged targets and all source/failed evidence remain immutable. Duplicate hash flags=0;
existing bounded average-hash/Hamming≤2 index flags=0; PDF/group maximum=3/3. This is not exhaustive
semantic duplicate proof or training admission. Expressions: contour 10 / restrained gray 23 / hatching 5.

Canonical results are `artifact_d50bd600731e4072aeb2237e6fa6730d` /
`rev_222b8ae8c8fb48b197774439183ca585` and `artifact_8f75cf7851b6470eaef0831b46e307ca` /
`rev_b84fd533d5b84f7aa911b452ec1a1798`, primary `manifests/sdxl-training-target-result.json`.
26-member metadata/log/operator evidence is `artifact_3bce4fee87f141febad135f790eaa3a2` /
`rev_b4846e18f23f49c0952b4ea5e9e328ac`, primary `reports/own-target-review.md`, raw SHA
`sha256:8f87b5bca79b77052eccd8c07f519fa6b2eb121aaf3ec6552f6436b795ddcc93`.
It includes the temporary publisher's initial wrong-count assertion failure before publication;
the same successful CPU run/result was validated and published after correcting the caller's
expectation, without resubmitting worker work or changing DB rows. Evidence contains zero duplicate PNG/PDFs.

New GPU calls=0, training updates=0, training admissions=0, reserved-pixel views=0, activation FORBIDDEN.
The reviewed candidate list is operational evidence, not a new dataset wire contract. Formal corrected-data
dataset/training/evaluation successors and bounded usage remain next; old exhausted diagnostics stay closed.
