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
