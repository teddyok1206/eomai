# Keep additive row validation outside the numerical codec fingerprint

2026-10-16 UTC. Design before implementation; no runtime activation.

1. Boundary: native float32 packing/reading is a numerical implementation; validation
   of an already materialized row is an additive contract-package consumer API.
2. Canonical numerical bytes remain the installed CPU codec3487cae0 and its existing
   exact descriptor. The new GPU candidate currently has73b796b1 because C5 exposed
   a validator in that same file; encoder f667e54d and HOST_L2 440d7406 are identical.
3. Preserve all existing model/bundle/space/Artifact identities and hashes. A source
   successor deliberately restores the unchanged numerical codec bytes; never patch
   a protected prefix or relabel its previous audit as covering different bytes.
4. Keep benchmark1.0's exact three-implementation family check. Different module
   hashes must not be declared equivalent, excluded from the family or accepted by
   a special-case allowlist to make the comparison succeed.
5. Access: one O(d) finite/norm validation over an existing tuple; no vector search,
   storage, normalization, float32 packing or binary materialization belongs here.
6. Add one small public `embedding_vector_validation` facade inside the SAME
   contracts package. It delegates shape/norm checks to that package's existing
   private codec primitives. There is one authoritative numeric rule, not copied
   math or a second serializer. External services import only the public facade.
7. Space O(1), same tuple and stable errors; no repeated binary copying. Native
   codec serialization/rounding, bounds and ordered rows remain byte-for-byte old.
8. No DB, queue, claim, lease or transaction change. Source relocation is shipped
   with all its source consumers in the same wheel. Existing installed e132 services
   retain their own unchanged code; no mixed Python module installation is allowed.
9. Contracts remain pure and infrastructure-free. The new facade may use private
   primitives within its own package; no external package reaches private code.
   No module attribute injection, import hook, monkeypatch or mutable registry.
10. Wrong dimensions, bool/nonfinite/bad norm, malformed binary and hashes retain
    explicit errors. No recovery or re-encoding. New CUDA package/source/bootstrap
    pins must pass fresh complete prefix audit before any candidate instruction.
11. Widening the benchmark gate hides drift; updating the active CPU implementation
    would invalidate its current space or require avoidable corpus re-encoding.
    A tiny public facade preserves the canonical codec and current CPU operation.

The public validator added for the still-disabled C5 consumer moves to its own
module; all known source imports move together. Its Python import location is not
a serialized schema/worker protocol. Existing wire schemas, checks and resources
are unchanged. The exact historical codec SHA is a regression requirement, not
permission to bypass the whole-prefix source/archive auditor.

Verify codec raw3487cae0e2f21dbe2f95c58a278c083a181bea2255f023e00e53484ee2ebdb79,
unchanged native pack/read and negative cases, facade parity/no binary allocation,
native model-family equality for the three real implementation pins, C5 semantics,
dependency boundaries and wheel contents. Keep CPU config/space/index/outputs.
Actual GPU group/device/probe/seal, all-entrypoint leasing, six numerical launches
and C1–C5 activation remain separate full-goal requirements.

## Source verification checkpoint

Fresh combined regression: **2149 PASS, one SKIP, 85.43s**. The skip is the
explicitly opt-in real protected OLD-pip/tiny synthetic-wheel test, not a model
or GPU test. Inventory: the previous34 native/CUDA/installation/wheel/dependency
suites plus codec, numerical-family, C5 observation and benchmark-contract tests.
This combined run includes earlier suites; counts are not added together.
Strict mypy for the two production consumers, Ruff check/format for all five
Python files and `git diff --check` PASS. An earlier invocation used a nonexistent
benchmark test filename and collected no tests; the corrected combined run above
is the actual evidence. The previous lost output handle is not counted as PASS.

The new family test reads the actual three source files, checks their frozen CPU
raw hashes, then uses synthetic CPU/CUDA runtime values with those real pins.
It confirms the old exact family rule accepts matching pins and rejects73b796b1.
This is source/contract evidence, not an installed GPU performance measurement.

## Actual protected installation and whole-prefix audit

Source `69793b3edd5519dec56b7d9d60e821abed8d0460` is committed/pushed. Standard
build/RECORD/OpenAPI verification PASS; dist is
`/tmp/eom-api-build/69793b3edd5519dec56b7d9d60e821abed8d0460.BXplAg/dist`.
Platform wheel raw54705fa1acebf4725fea498376af78531e94989e35489ff3548a4deb43f7ff44
(3953105 bytes), API-contracts wheel
b7d6165fbcf13b1512b7e0854d3b51204a805eb1b5f7fce5ee40db12dc5a29f5.
The existing protected owner installer559ada51 installed this pair into a new
immutable owner69793b3e, without selecting it or modifying API/CPU services.
Actual protected OLD `-I -B` import under this owner confirmed all three CPU
implementation pins and the public facade, zero optional ML imports and zero
CUDA candidate-interpreter executions.

Dedicated0700 input root `/tmp/eom-cuda-codec-input-ImphiyIh` contains exact new
platform wheel/Git archive plus unchanged leasec9 wheel/source. New source raw
a3441b3bb36aaf1dcff4fc775058e004dcbd902d2913e34a529543424f0d509a
(61286400 bytes). Canonical input1.2 raw
cce6e34e5370daf3e41c52ba1540473208fa99c2db01b919a4a8efca3dfff241
changes only that private platform provenance. Existing protected installer
260808d0/helper79e22063 and the current CUDA host/cache remain unchanged. Public
wheels are reused; no download, public reinstall or candidate Python execution.

Actual unit `eom-cuda-codec-successor-69793b3e.service`, invocation
`64413c01db5948a79718d2a827fbfe1a`, PID3475755, started23:09:40 and completed
**successfully23:14:13 UTC**. Its own journal records Finished/Deactivated
successfully; later normal unit collection is not treated as separate evidence.
The existing installer checked predecessor treea7198a94, retained the complete
previous prefix and private overlay, prepared the new private code, then ran the
whole source/byte/ELF audit with OLD. Original CPU/models/OLD were readonly and
network/devices unavailable. Stdout explicitly reports AUDITED_NOT_ADMITTED and
NOT_PROBED. No failure retry, profile guard relaxation, row mutation or original
HTTP QUERY resubmission occurred.

Operation `/opt/eom/.embedding-index-install-mFHwtZlb` contains the new inventory:

| Actual new inventory fact | Verified value |
| --- | --- |
| Schema/state | inventory1.0 / CANDIDATE_NOT_ADMITTED |
| Raw bytes/SHA |8928061 / `f8badb1751d8d9de9577c2f7b62379c54a676fcfd15fa65b4846d89a6d22584a` |
| Semantic SHA | `af4366ffdc4fbfe6e1cd9d05228fb9d5e8a8bd30ec42302f2a9d49eca83d1321` |
| Entries/regular/links/ELF |31597 /28024 /1380 /287 |
| Payload bytes |7084887054 |
| Source closure | `73c51cd04fcf36577c5b42c0644015d819609d18e542a16637d4ae074ff7d75d` |

The protected owner697 parser independently validated that actual root inventory
against the original protected schema and exact new input pin. Its actual entries
contain codec3487cae0, HOST_L2 440d7406, encoderf667e54d and the new facade. The
read-only operator rawbe955719 is protected root:root0444/nlink1 and loaded no ML.
Logs/plan/summary: `/tmp/eom-cuda-codec-release-AUTDkmoU`. Full predecessor backup:
`/opt/eom/conda/envs/.embedding-index-prepublication-CUDA_INDEX_FP32-.embedding-index-install-mFHwtZlb`.
Nothing material was deleted. Active CPU service/config/space/index and earlier
failed history remain untouched. The initial local input's trailing LF was
correctly rejected, mechanically formatted before submission and parsed again;
a diagnostic access to nonexistent `plan.profile` and operator-only Ruff line
formatting were corrected before protected execution. No runtime guard changed.

This closes only the real installation/byte-audit side of the numerical-family
fix. Native CUDA proof/bundle/config, OS/device/shared-lease admission, no-model
probe/termination/seal, all GPU entrypoints, six actual numerical comparisons,
conditional default and C1–C5 live-consumer gates remain separate, unfinished
parts of the original goal. No new source framework is required by this fix.
