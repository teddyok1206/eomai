# Failed GPU batch controller recovery

2026-10-25 UTC. This closes an observed GPU goal defect, not a new execution backend.

The 64-target canary sent GRANT, then exhausted the original allocation channel.
The controller's bounded cleanup ended before the worker reached FAILED. PID1
retained one shared GPU-lease descriptor; no full READY snapshot survived. Do not
invent that observation, call the ungranted recovery path, retry the computation,
or classify this as pre-compute BUSY. Rollout returned to the previous 16-target
owner. The failed invocation and empty numerical outputs remain evidence.

1. Responsibility: the existing Catalog root unit-lifecycle boundary retires only
   an independently observed, ended, exact failed batch invocation. Existing
   schema-owner Workflow maintenance subsequently records its real failure.
2. Canonical source: protected original allocation/launch/GRANT metadata, fixed
   service/descriptor bytes, actual PID1 status/FDSTORE and kernel lease identity.
   Neither a DB RUNNING row nor an operator-supplied record proves termination.
3. Identity: original allocation ID, allocation message/raw SHA, unit invocation,
   exited PID/start and separate immutable intent/result hashes. No new job ID.
4. Resolution: root UID, canonical input, exact unit family/drop-in/template,
   pinned receipt/device, no owned cgroup processes, actual FAILED and retained
   lease inode/PID1 descriptor are checked before effects and after release.
5. Access: O(1) fixed-path and exact-unit reads; no corpus/source/Graph traversal.
6. Structure: frozen typed physical witness and one exclusive phase directory;
   the existing no-clobber record writer provides intent-before-effect ordering.
7. Scale: one record per original invocation, at most 256 KiB, constant work.
8. Concurrency: an exclusive retirement phase prevents competing cleanup. The
   same-inode released lease is held while proving zero FDSTORE. No SQL root is
   held over systemd effects. DB recovery uses the existing expired-claim fence.
9. Dependencies: contracts own the small result schema; Catalog owns Linux and
   fixed systemd effects; Runner maintenance owns workflow state. No ML import,
   new dependency, queue, schema migration or worker authority is introduced.
10. Failure/replay: retain FAILED before reset/clean of that exact dead unit.
    Completed recovery replay is read-only. An intent without a result remains
    uncertain and cannot silently repeat an effect. No model replay, CPU fallback
    grant or success receipt follows from retirement. The old 1.0 root pointer
    may resolve this explicitly versioned result only after validating its pinned
    intent and exact original FAILED witness; old retirement bytes stay supported.
11. Simpler alternatives: raw `reset-failed`/`clean`, fabricated historical READY,
    and pretending GRANT was absent discard the evidence needed for safe recovery.

For future failures persist the actual READY observation before source admission,
and use a cleanup-only wait independent of an expired numerical deadline. Neither
change extends computation, renews an allocation or authorizes new work. The
64-target shape is not activated while its bounded live acceptance is failed;
the already accepted 16-target bound is sufficient for initial continuous INDEX.

## Verification checkpoint

The typed result schema is mirrored in source/resources with raw SHA
`sha256:4e23e5b8438c5c9389d5061a5598c323e7873f93f02079fa41176377fb74c7ca`.
The root reader explicitly dispatches the new result and resolves its pinned
intent; old full-READY retirement records are unchanged. Current controller code
persists actual READY before source admission and waits at most 60 seconds for
cleanup independently of the expired compute clock.

Source final focused recovery/controller/schema/dependency gate: 67 PASS in
44.84 seconds (`/tmp/eom-gpu-failed-root-recovery-final-20261025-r6.log`). Previous
broader run: 264 PASS plus one incorrect exception-boundary failure; the new
contract now reports schema errors as stable ValueError and that negative case
passes in the focused gate. Initial parsing/fixture failures remain recorded.
Disposable PostgreSQL recovery, concurrent exact replay, late-fence rollback,
failed-history preservation and producer retry: 19 PASS in 19.73 seconds,
cleanup EXIT0 (`/tmp/eom-document-execution-pg-20261025-r49.log`). These tests use
synthetic root/IAM leaves; actual failed64 retirement has not yet run at this
source checkpoint. Final broader root/reader/controller/lifetime/resource and
maintenance-authority suite: 265 PASS in 51.53 seconds
(`/tmp/eom-gpu-failed-root-recovery-regression-20261025-r7.log`). Strict mypy four
production modules, scoped Ruff/format and diff checks PASS. No operating default
or numerical runtime was changed.
