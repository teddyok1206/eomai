# Native INDEX handoff and result publication

2026-10-13 UTC. Implements the approved incremental-embedding execution boundary.

1. **Responsibility:** Orchestrator stages one authorized owned encoding batch;
   root prepare creates the fixed three-descriptor handoff; the existing isolated
   CPU entrypoint computes; Orchestrator validates and publishes the result.
2. **Canonical source:** the approved `IncrementalEmbeddingInput` Artifact and
   existing `LocalEmbeddingLaunchAssociation`. Staging is temporary materialization.
3. **Identity:** execution ID, native launch Job, owned encoding Jobs and their
   allocations, input Artifact/revision/raw SHA, request SHA and association SHA
   stay separate. Original all-demand Workflow request is preserved.
4. **Resolution:** strict canonical schema parsing and exact association/input
   closure precede root output allocation. The trusted owner must freshly admit
   source/session/command before writing its launch marker. Root prepare checks
   the fixed owner UID and files; it never interprets an audit actor as authority.
5. **Access:** fixed execution-ID lookup, retained ancestor/member FDs, bounded
   sequential input/output reads, and exact-key no-clobber creation.
6. **Structures:** reuse the existing CPU handoff's protected directory/member
   primitives through named public functions. One immutable prepared value pins
   the input and association; existing schemas and file-set publisher suffice.
7. **Scale:** 1–1,024 owned encodings, schema-defined input bound and 16 MiB binary
   output bound. Staging/readback is O(input + output bytes), with bounded memory.
8. **Concurrency:** O_EXCL files and execution directories; prepare/replay never
   overwrite a partial handoff. No SQL transaction spans inference. Timeout or
   stale observation preserves launch identity for later inspection.
9. **Dependencies:** filesystem/systemd remain Orchestrator infrastructure; native
   numerical execution stays Catalog infrastructure. No ML dependency in domain
   code and no new third-party dependency. CPU installation remains c2f8eef8.
10. **Failure/retry:** validate held and named identities before/after readback;
    materialize once only after confirmed exact-unit termination. Interrupted
    output publication reuses the same Artifact key and bytes. Never re-run a
    model because a status query timed out.
11. **Alternative:** direct owner-process inference would bypass the installed
    isolated worker and its limits. A second queue/publisher would duplicate the
    existing ownership and recovery logic. Extend the fixed handoff and publisher.

The CPU unit requires its root prepare unit. Root prepare code is installed in a
separate protected owner release, using the existing protected interpreter and
explicit root-owned overlay. This does not modify the numerical prefix or its
installation receipt. Runtime installation, fixed-unit/permission checks and an
actual bounded run remain separately verifiable milestones.

Initial scope is INDEX. QUERY retains its existing distinct input/result schema
and fixed unit; it is connected after the owned INDEX path is working.

The original source plan and the separately owned numerical input have distinct
canonical Artifacts. `LocalEmbeddingControlArtifactPublisher.publish_owned_input`
validates the existing input1.0 schema and publishes only `input.json` through the
same file-set owner. The caller's current admission/reservations precede this
leaf; its receipt is not authority. The returned raw member pin can then close
the existing launch association. This resolves the pointer before bind without
putting text/rows into Job metadata or editing the all-demand Workflow request.
Key reuse is exact-content replay; changed input conflicts and preserves the
first Artifact. No wire schema, queue, DB migration or dependency is added.
The pure `build_owned_incremental_embedding_input` closes current plan/profile
values with sorted unique reserved encoding Jobs, preserving the original
request/plan. It materializes exact view text without truncation or stripping,
uses maps/set for source lookup and deduplication, and validates the existing
input1.0 schema/hash. Empty/foreign/ambiguous subsets, incomplete profile closure,
mixed device and reused allocations fail explicitly. Neither this builder nor
input publication grants source/command authority or completes an index.

## Source and actual OS verification

The implementation uses public protected handoff functions from the existing CPU
adapter. Native INDEX uses its own fixed input/association, stage directory and
root prepare/main units. Its filesystem lock serializes owners; active unit and
kernel cgroup checks preserve capacity after an owner crash. Transport timeout
reobserves the same execution. A completed execution reuses validated output.

`EmbeddingArtifactStore.publish_owned_batch` validates request1.1, original plan,
policy and the separately owned launch subset, then calls the same publication
leaf used by request1.0. Legacy publication keys and result members are preserved.

2026-10-13 source verification: focused8 suites188 PASS; strict mypy5 modules,
Ruff/format and systemd source verification PASS. Actual root/owner/worker UID/DAC
tests3 PASS used only test-owned temporary files: root0600 input, root0640 output,
owner read-only output, worker path denials, no-clobber prepare and validated
readback. No DB/NAS/model call was made by those OS tests.

The first OS replay case correctly rejected an existing handoff; its generic
directory error is now the stable `NATIVE_INDEX_HANDOFF_EXISTS`, preserving the
same rejection and original inode. Other source fixture fixes confined the
temporary parent permissions and asserted the unchanged public schema error.
Import guards now admit the four existing native domain contracts; forbidden
database/network/process imports in the Artifact store remain forbidden. The
INDEX-specific root dependency is asserted while all shared worker restrictions
remain under the original template test.

Owner release/units/polkit installation and actual numerical execution are the
next operational step. They are not proved by this source/OS test evidence.

## Installed authorization ordering

The initial actual start was denied before either unit or numerical process ran.
The installed `50-eom-worker-units.rules` intentionally returns NO for unmatched
owner starts; a separate `51-...` rule cannot override that earlier decision.
The native rule is therefore `49-eom-native-index.rules`: its exact start-only
exception runs first, while every unmatched action continues to the unchanged
existing deny rule. Tests evaluate both files in actual sorted order, including
prepare/query/restart/foreign-owner negatives and an existing worker positive.
The frozen numerical runtime, receipt and original 50-rule bytes are preserved.
The runtime smoke uses a fully dropped real/effective/saved owner UID; an
effective-only DAC test is not evidence of systemd start authorization.

Native INDEX actions by other identities are explicitly denied rather than
falling through to an interactive administrator challenge. The first authorized
start then stopped at PID1's `226/NAMESPACE`: the mandatory QUERY denial root
did not exist. No Python/model instruction ran. The fixed tmpfiles configuration
creates all three native handoff roots before sandbox construction; no denied
path is made optional and no worker receives new access. The failed invocation
remains immutable evidence; any subsequent synthetic smoke has a separately
recorded identity and predecessor cause, not a reset or restart of that unit.
The launcher also checks root ownership/type/group/mode of those fixed roots
before `StartUnit`, so a future missing root fails before consuming a handle.

An isolated no-forward diagnostic reproduced `EMBEDDING_BUNDLE_INVALID` at the
protected model ancestor open. The old probe directly read the eight model
members, while the runtime resolver retains directory FDs using O_RDONLY. Its
two namespace ancestors had search-only ACLs, so direct reads passed but that
directory open failed. The operational correction grants the fixed CPU UID r-x
on those two embedding namespace directories only. The selected revision was
already r-x and its files already r--; no model bytes/hash, runtime prefix,
receipt, group membership, write permission or source policy changes. A real
UID/DAC fixture reproduces both outcomes and continued write rejection. Existing
host `setfacl`/`getfacl` are used for the explicit ACL operation and backup; no
new Python dependency or generalized privilege adapter is introduced.

## Actual numerical checkpoint

2026-10-13 17:48 UTC: protected owner release28cfcfa0 plus frozen CPUc2f8eef8
completed two TEST_ONLY_SYNTHETIC inputs, each1024 dimensions. Exact readback
validated schema/input/result/float32/hash/finite/L2 and terminated empty cgroups.
Reobserving the same handle preserved both invocations/start-exit timestamps and
all output hashes, without any StartUnit. Installed polkit9 cases and real UID/DAC4
cases PASS. Final source15 suites430 PASS; strict mypy3 changed modules and
Ruff/format PASS. Earlier failures/diagnostics and rollback remain recorded.
This is numerical/OS acceptance, not corpus source/Job/index acceptance. The
new input builder/publication/layout preflight are source changes; the installed
owner remains28cfcfa0 until the next coherent owner release. Actual authenticated
provider/reservation/executor/receipt/registry, seed/delta/query and consumers
still need connection. CPU/GPU comparison/default activation remain unevaluated.
