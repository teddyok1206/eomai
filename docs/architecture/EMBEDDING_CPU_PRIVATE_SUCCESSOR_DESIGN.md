# CPU/CUDA private-code successor for fixed benchmark entrypoints

2026-10-17 UTC. Design before implementation; no installed/runtime grant.
Prerequisite: [actual missing entrypoints](../status/EMBEDDING_BENCHMARK_INSTALLED_ENTRYPOINT_GAP_2026-10-17.md).
Reuses the [complete execution composition](EMBEDDING_BENCHMARK_EXECUTION_COMPOSITION.md),
not a new benchmark, queue, launcher or model pipeline.

1. Responsibility: extend the existing fixed private-prefix installer to prepare
   CPU as well as CUDA private-code successors. Preparation is not admission,
   template activation, source authorization, model execution or a device default.
2. Canonical source: exact retained wheel/source archives, declared profile and
   pinned audit-input bytes. Existing immutable model payload, vector Artifacts,
   original Jobs, source/report/Graph/policy and numerical recipes remain canonical.
3. Revision model: retain the complete predecessor prefix and private overlay;
   produce a separately audited candidate. New source/archive/inventory/proof/
   configuration hashes must not be reported as the old accepted receipt.
4. Resolution: keep root ownership, independently accepted OLD Python, archive
   source/hash/commit/ZIP checks, full prefix/ELF/host audits and no candidate
   instructions before admission. CPU uses exactly one platform wheel/source and
   audit1.0/1.1. CUDA keeps platform+lease and audit1.2/1.3. CPU never accepts CUDA
   lease inputs or the CUDA host family; no schema bytes or dispatch guard waived.
5. Access: profile-key lookup, bounded archive iteration, private-namespace set
   membership, ordered RECORD generation, single publication claim and append-only
   phase evidence. Current native users/consumers must be drained before real use.
6. Structures: one closed profile→private-distribution tuple in the existing
   bootstrap. Existing maps/sets/unique paths and per-profile flock remain owners;
   no DB table, index, registry or global mutable plugin catalogue.
7. Scale: at most two private wheels, bounded namespace/member inventory. Archive/
   copy/audit cost is O(runtime bytes + members); bounded tuple/key work is O(1).
   The one quarantine runtime copy is the explicit installation/rollback boundary,
   not repeated cross-service corpus/model copying. Public dependencies and model
   weights are not installed/downloaded/recopied by the private pip step.
8. Transactions: assemble using accepted OLD pip with no-index/no-deps/no-compile,
   replace only private roots/wrappers, preserve pre-replacement and post-replacement
   phases. The existing filesystem swap is not a distributed atomic transaction.
   No application source/claim transaction spans this operation.
9. Dependency/ownership: shell validates presentation pins/profile; the existing
   bootstrap owns package tuple, wrapper interpreter and private bytes. Full audit
   owns runtime closure. Application/domain/worker interfaces gain no subprocess,
   DB or arbitrary import-path override. No new dependency.
10. Failure/replay: failed pip/preflight leaves original prefix unchanged; failure
    after swap retains predecessor and exact phase evidence. No replay into a
    partial workspace, model retry, implicit latest or automatic restore. Preserve
    legacy CUDA callers without `--profile` by its existing CUDA default; new shell
    callers always pass an explicit closed profile. Missing CUDA lease pins still
    fail before filesystem/archive effects. CPU lease pins must be absent/dash.
11. Alternatives: a CPU copy of the CUDA installer duplicates ownership/audit logic;
    root `python -c`, ambient source imports or repurposed installation probe lose
    the fixed benchmark/source/Job boundary. Merely removing the CUDA-only guard
    is insufficient: package arity, audit family, shebang/RECORD and absence of a
    CPU lease package must be positively enforced and tested.

Tests require CPU one-wheel assembly/wrapper/RECORD and public-byte preservation,
CUDA legacy behavior, wrong/missing profile/lease/arity/duplicate/foreign-wheel
rejection, both profiles' preparation-before-audit order, retained failure/partial
states and no candidate execution. Existing opt-in actual OLD pip tests may use
tiny inert wheels, with synthetic ownership explicitly distinguished from root
installation. Full static/privileged installed audit, fresh native admission,
image lifecycle gates, actual six frozen model runs and default policy remain
separate requirements; source PASS does not close them.

## Implemented source and verification — 2026-10-17

The existing `publish-private-successor` now accepts the two closed profiles.
CPU requires the platform wheel/source only and five dash lease fields; CUDA
retains both distributions and its audit1.2/1.3 guard. The existing OLD typed
host preflight owns CPU1.0/1.1/profile validation, including noncanonical JSON
formatting; no second CPU parser or formatting requirement was introduced.
The shared bootstrap checks exact package arity/dist-info, rejects CPU lease
payloads before pip, writes the selected fixed interpreter into wrapper RECORDs
and retains the old private roots/scripts. Legacy callers still select CUDA.

Final focused gate: **352 PASS, no skips, 30.69s** across private-successor,
runtime-installation, complete prefix closure, snapshot-input and dependency
boundary suites. Includes two opted-in **actual accepted OLD pip** assemblies
using tiny inert synthetic wheels, one per profile. Those tests substitute
ownership and do not establish root installation/admission/model execution.
JUnit: `/tmp/eom-cpu-private-successor-J6OYgqP1/focused.xml` (temporary gate
materialization, not a canonical runtime Artifact). Strict mypy of the bootstrap,
Ruff/check/format of three Python files, shell syntax and diff checks PASS.

The first expanded run found an existing snapshot-input baseline test still
counting two later additive contracts as predecessors (351 PASS/1 FAIL). Git
history identified `embedding-benchmark-cuda-ready` and
`general-chat-private-query-read` as the additions after the pinned baseline.
Exclude only those two from that historical projection: the original **318**,
aggregate SHA `69baab14da4b9fca83ea011f3daef1b846115a9fcd946213db06e54ccb50a24c`,
schema bytes and mirror checks remain unchanged. Its isolated25 and the final352
PASS are overlapping evidence, not added counts. No production guard was relaxed.

No numerical prefix, active config, service, database, model, vector or GPU
default was changed by this checkpoint. The operating installed API remains
4222ca9a; original HTTP delivery still needs actual authenticated verification.
Before real publication, build a new exact source archive/wheel: full auditing
also binds the installer helper bytes to that source archive. Reusing an older
archive with the changed helper is invalid. Preserve current numerical module
hashes and public wheels, then use supported drain/publication/audit/admission
and fixed benchmark templates. Actual six-run/device/default gates remain open.
