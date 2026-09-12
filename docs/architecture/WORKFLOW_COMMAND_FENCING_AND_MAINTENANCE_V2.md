# Workflow command fencing and maintenance v2

## Decision

Workflow command execution uses a per-acquisition fencing identity composed of the command ID, the
runner instance ID, a cryptographically random lease token, and a monotonically increasing lease
generation.  The runner renews that exact identity while a command is executing and validates it at
the beginning and end of every Workflow-runner database transaction.  A transaction whose lease was
reclaimed or expired is rolled back before commit.

Worker-capacity and worker-lease expiry reconciliation plus automatic observation of idle Codex
bindings also have a maintenance-only entry point.  It never claims Workflow or operator control
commands and may remain active while the command runner is deliberately held inactive.

## Required design procedure

1. **Responsibility and boundary.** The Workflow runner owns command claim, renewal, fencing, and
   terminalization.  The maintenance loop owns expiry reconciliation and bounded automatic
   observation of due, idle Codex bindings.  Workers and Catalog do not inspect or mutate Workflow
   command leases.
2. **Canonical source.** `workflow_commands` is the canonical command/lease record.  The systemd
   runner and maintenance units are runtime materializations of the repository-owned unit files.
3. **Entity and revision model.** `command_id` is the logical command.  `lease_generation` is its
   monotonic claim revision.  `lease_token` is an unguessable identity for one acquisition; it is not
   a command ID or a runner ID.
4. **Pointers and resolution.** A lease pointer contains command ID, runner ID, generation, and token.
   Resolution requires the row to exist, be `LEASED` or `PROCESSING`, match all fields, and remain
   unexpired.  Missing, stale, expired, or mismatched identities fail with
   `WORKFLOW_CONCURRENCY_CONFLICT`.
5. **Access patterns.** Claim is FIFO ordered iteration over a partial queue with `FOR UPDATE SKIP
   LOCKED`.  Renewal and fencing are primary-key lookups with constant-size comparisons.  Expiry
   reconciliation is an indexed range scan by expiry time.
6. **Structures and indexes.** The database primary key serves fencing lookups.  A partial unique
   index protects non-null lease tokens; the existing claim index remains the FIFO access path.
   In-memory heartbeat state is a frozen lease value plus two thread events, not a shared registry.
7. **Scale and complexity.** Claim is O(log n + 1) with the queue index; fencing and renewal are O(1)
   row operations.  One bounded heartbeat thread exists per active runner command, currently one per
   runner process.  Persistent space is two scalar fields per command.
8. **Transaction and concurrency.** Claim increments the generation and writes a fresh token in the
   same transaction that enters `LEASED`.  The transition to `PROCESSING`, each workflow mutation,
   and terminalization compare the exact claim.  The heartbeat uses independent short transactions.
   Losing the lease prevents later Workflow-runner commits; already committed idempotent Artifact
   work is recovered by its owning service.
9. **Dependency direction.** Lease value objects and repository operations remain in the Workflow
   runner.  The CLI invokes application methods.  The systemd unit is an infrastructure adapter and
   contains no domain rules.
10. **Failure, retry, and idempotency.** A renewal database error fails the acquisition closed; the
    runner does not guess whether ownership survived.  A mismatched row is terminal lease loss.
    Reclaim always generates a different token and higher generation.  A stale executor cannot mark
    the command succeeded or failed.  Maintenance reconciliation and automatic idle-binding
    observation are idempotent and never dispatch work or claim operator commands.
11. **Simpler alternative.** A longer fixed lease or a process-wide runner ID does not fence a stale
    executor.  Holding one database transaction during model execution would exhaust connections and
    retain locks for up to hours.  Per-acquisition fencing plus short heartbeats gives the required
    safety without long-lived database locks.

## Operational boundary

The maintenance unit may be active while `eom-workflow-runner.service` is under a deployment hold.
Releasing a deployment hold remains a separate reviewed operation; maintenance may refresh due,
idle capability evidence but does not start, approve, cancel, or otherwise execute queued commands.
