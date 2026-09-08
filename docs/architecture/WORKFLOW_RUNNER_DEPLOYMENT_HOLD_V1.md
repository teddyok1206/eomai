# Workflow-runner deployment hold v1

## Decision

The exceptional mock-exam retirement deployment uses a persistent systemd drop-in for the locally
installed `eom-workflow-runner.service`.  A runtime mask under `/run/systemd/system` is not a valid
hold for this unit because the complete unit in `/etc/systemd/system` has higher load-path
precedence. The drop-in sets `RefuseManualStart=yes` and the deterministic false condition
`ConditionPathExists=!/` (the root directory necessarily exists). Manual starts are rejected and
dependency starts are skipped before `ExecStart`. Acquisition first disables the already-stopped
unit with `--no-reload` as a reboot fence, installs the exact hold, and re-enables with
`--no-reload` only after that hold is durable on disk. One subsequent reload exposes the enabled
hold without garbage-collecting the stopped unit or erasing its prior invocation identity.
Release disables it again before the hold is moved, so every interruption and reboot remains
non-runnable until a separate explicit enable-and-start action.

The installed hold is one canonical, root-owned regular file at
`/etc/systemd/system/eom-workflow-runner.service.d/zzzz-eom-deployment-hold.conf`. Code pins its exact
SHA-256 and verifies the loaded fragment, singleton drop-in path, file type, owner, group, mode,
content hash, `RefuseManualStart`, `NeedDaemonReload=no`, and quiescent process state. Acquisition
pins `InvocationID` and `ActiveEnterTimestampMonotonic` through its one reload. Release keeps that
identity through `disable --no-reload`; after the disabled unit can legitimately be garbage-collected,
it accepts only the exact old identity or systemd's empty `:0` baseline together with a clean journal
fence derived from the immutable retirement time. An unrelated or tampered path is never overwritten
or removed. The ineffective legacy runtime-mask symlink may be removed only after it is proven to be
the exact root-owned `/dev/null` symlink and the persistent hold has already been loaded and
verified. The local base unit must match the canonical `infra/systemd` bytes and pinned SHA-256,
not merely retain the same hash across release.

## Required design procedure

1. **Responsibility and boundary.** The privileged release adapter installs and releases the host
   systemd hold.  The read-only Workflow-runner infrastructure adapter observes the same hold for
   the retirement application.  Retirement business rules consume immutable evidence and do not
   execute `systemctl` or inspect paths directly.
2. **Canonical source.** The versioned drop-in bytes in `infra/systemd` are canonical.  The
   installed root-owned copy is the active materialization; the loaded systemd properties and its
   exact file metadata/hash are runtime evidence.
3. **Entity and revision model.** The systemd unit name is the logical service identity.  The exact
   drop-in path and pinned SHA-256 identify this hold revision independently of the base unit and
   its enabled state.  No mutable "latest hold" lookup exists.
4. **Pointers and resolution.** Observation resolves the exact base fragment and exactly one
   drop-in.  It rejects missing, extra, symlinked, non-root-owned, writable, hash-mismatched, or
   unloaded hold materializations. The retirement rule
   also requires `loaded/inactive/dead/MainPID=0`, an empty systemd Job,
   `UnitFileState=enabled`, and `RefuseManualStart=yes` while held. Release proves the corresponding
   disabled, unheld, inactive state before a later explicit enable-and-start action.
5. **Access patterns.** Activation, deployment checkpoints, retirement, and release perform a
   constant-size keyed lookup of one unit and one file.  Evidence is a frozen value object; no
   large payload, scan, queue, or cache is involved.
6. **Structures and indexes.** An exact property map detects missing and duplicate `systemctl show`
   keys in O(1).  The singleton drop-in tuple preserves systemd's loaded identity.  Persistent DB
   structures and indexes are unchanged.
7. **Scale and complexity.** Time and space are O(1).  The drop-in is below one KiB and the bounded
   service-manager output is capped at 4096 bytes.
8. **Transaction and concurrency.** No wheel, migration, DB, worker, or model action begins until
   the installed drop-in has been atomically placed, `daemon-reload` has completed, and the exact
   hold is observed.  Once that boundary is reached, interruption is fail-closed across both
   process death and reboot. Release is a separate privileged action. Before any systemd/file
   mutation, an installed root-owned helper safely reads an explicit mode-0600 receipt file and the
   canonical current plus immutable-revision checkpoints for the expected execution. It takes the
   checkpoint store's nonblocking exclusive flock and re-reads `current.json` while holding it. It
   validates installed JSON Schema 2020-12 and Pydantic contracts, self-hashes, and exact execution,
   revision, request, plan, operator, and checkpoint pointers. The validated receipt's UTC
   `retired_at` supplies a retry-stable journal lower bound. Release derives and cross-checks the last
   journal cursor at or before that bound, proves the returned cursor value remains byte-exact around
   each query, then requires zero subsequent entries for the exact runner unit after reload and again
   before backup cleanup. Missing permission, malformed output, cursor rotation, or any unit activity
   fails closed. It admits only an ordered unique
   25-outcome receipt with exactly 24 `CANCEL_QUEUED` and one
   `UNSUCCESSFUL_TERMINAL_PRESERVED`; every queued cancellation must originate from an active
   Workflow state. The verifier retains the exclusive flock through an explicit completion
   handshake with the privileged release process. Release leaves the runner stopped and disabled;
   a later action must explicitly enable and start it. The recovery window also forbids unrelated
   mock-exam CLI commands from retirement through hold release.
9. **Dependency direction.** The deployment script owns privileged mutation.  The systemd adapter
   implements a read-only application port.  Domain retirement code depends only on the frozen
   evidence contract; no domain package imports filesystem or subprocess infrastructure.
10. **Failure, retry, and idempotency.** Exact existing hold bytes are accepted on retry. Partial,
    foreign, or tampered files fail without replacement.  The persistent hold remains installed on
    every deployment failure. Receipt/checkpoint validation uses same-file-descriptor, bounded,
    no-follow/nonblocking regular-file reads with exact owner, mode, link count, and pre/post
    identity checks; any failure occurs before hold mutation. Release removes only the verified
    canonical file, reloads systemd, and proves the still-quiescent disabled/unheld state; a failed
    release never starts the runner. The reviewed backup supports retry before or after reload; every
    retry with a backup derives the same receipt-time lower bound, while a retry after completed
    backup removal is an exact disabled-state no-op.
11. **Simpler alternative.** `systemctl mask --runtime` is insufficient for an `/etc`-local unit.
    `disable` does not block manual or dependency starts.  Moving/replacing the base unit would
    require backup identity and restoration logic.  The exact drop-in provides both activation
    barriers while preserving the canonical base unit and normal enablement.

## Operational sequence

1. Prove the runner is `loaded/inactive/dead/MainPID=0`; an exact disabled, unheld, synchronized
   snapshot is the recoverable state after an interrupted first acquisition.
2. Disable without reload, materialize the hold, re-enable without reload, then reload once and
   verify the persistent hold. Only then remove a proven ineffective runtime-mask
   residue and re-verify the hold.
3. Build/install while rechecking the hold at every consumer restart boundary.
4. Execute retirement and verify its self-hashed exact-cohort receipt.
5. As `eom-api`, publish the successful `retire-items` JSON envelope atomically to the fixed
   eom-api-owned mode-0600 receipt path. Run the explicit hold-release action with that path and all
   expected execution, revision, checkpoint, request, plan, operator, and receipt-hash pins. It
   removes only the exact hold and leaves the runner inactive and disabled. A systemd GC reset of
   historical invocation fields is accepted only with the clean receipt-time journal fence.
6. Explicitly enable and start the runner, then drain the already-fenced cancellation commands.
