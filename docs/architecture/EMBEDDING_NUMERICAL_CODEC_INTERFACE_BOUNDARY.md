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
