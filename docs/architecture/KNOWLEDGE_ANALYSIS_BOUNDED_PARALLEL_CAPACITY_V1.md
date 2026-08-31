# Knowledge Analysis Bounded Parallel Capacity V1

Status: design approved for implementation

Date: 2026-08-28 UTC

## 1. Responsibility and system boundary

This change doubles textbook Knowledge Analysis throughput without weakening worker isolation or
reinterpreting an existing batch. It adds one dedicated fixed support identity, `slot06`, and an
additive bounded-parallel batch contract whose maximum in-flight range count is exactly two.

The Catalog application service remains the only batch scheduler. The workflow runner remains the
only owner of worker leases and fixed-unit activation. Workers still communicate only with the
orchestrator, read staged local inputs, return one schema-valid local result, and never write to
PostgreSQL or NAS.

The existing five-slot inventory, capacity-policy revision 1, Knowledge Analysis presets through
V12, and batch request versions through 1.2 remain immutable historical contracts. The running V12
batch is not rewritten or silently widened. A later continuation batch may reuse its exact accepted
run pointers and execute remaining ranges under the new preset after an explicit operator action.

## 2. Canonical sources and revision model

The canonical configuration chain is:

```text
fixed worker inventory v2
  -> immutable capacity-policy revision 2
  -> immutable Knowledge Analysis preset V13
  -> immutable resolved execution plan per range
  -> exact worker lease on slot05 or slot06
```

The canonical batch chain is:

```text
knowledge-analysis-batch-request/1.3
  -> one immutable batch row (scheduling_mode=BOUNDED_PARALLEL, max_in_flight=2)
  -> ordered immutable range rows
  -> one pinned analysis run per EXECUTE range
```

Slot identity, capacity-policy revision, preset revision, batch ID, range ID, analysis run ID,
Artifact Revision ID, and SHA-256 remain separate. A systemd unit or workspace path is a runtime
materialization location, not an identity.

## 3. Required pointers and resolution checks

Before a range acquires a worker, the existing resolver must still verify the pinned preset,
capacity-policy revision, pool, role, model, reasoning effort, authentication binding, capability
snapshot, workflow, step, job, and attempt. Slot 6 is eligible only when all of the following hold:

- the installed fixed inventory contains `slot06 -> eom-cdx-06 -> support`;
- the resolved plan pins capacity-policy revision 2;
- the support pool explicitly contains slot 6 and permits at most two active leases;
- the slot is enabled and has a READY, unexpired authentication binding;
- its current capability snapshot reports `gpt-5.6-terra/xhigh` AVAILABLE;
- no active or reconciling lease already owns slot 6; and
- the host-wide active Codex and Knowledge Analysis ceilings are not exceeded.

Missing, stale, mismatched, or expired pointers fail before worker activation. There is no fallback
to an implicit latest policy, preset, binding, capability snapshot, or slot.

## 4. Primary access patterns and data structures

| Operation | Structure | Expected cost |
| --- | --- | --- |
| select a batch with free in-flight capacity | partial/indexed batch state scan plus correlated active count | `O(log B + A)` with `A <= 2` |
| serialize concurrent claims for one batch | row lock on the batch header | one short transaction |
| select the next range | `(batch_id, state, ordinal)` B-tree | `O(log R)` |
| count in-flight ranges | `(batch_id, state)` B-tree | `O(log R + 2)` |
| select an eligible support worker | capacity-pool membership plus indexed slot/binding/capability joins | bounded by two slots |
| serialize host-wide lease admission | one transaction-scoped PostgreSQL advisory lock | `O(1)` lock acquisition |
| enforce slot exclusivity | unique held-lease constraint by slot | indexed `O(log L)` |
| reconstruct final coverage | ordered `(batch_id, ordinal)` index | `O(R)` |

The batch keeps one row per range instead of a mutable JSON list. The scheduler claims the lowest
pending ordinal while allowing completion order to differ. Final output and publication continue to
use ordinal order, so parallel completion does not alter deterministic coverage.

## 5. Capacity decision and expected scale

The host has 16 logical CPUs and 30 GiB RAM. Recent Slot 5 evidence showed only about 3--5 CPU
seconds and at most roughly 150 MiB per 3--6 minute multimodal range. The dominant latency is remote
multimodal `xhigh` inference, not host compute or orchestration.

Capacity V2 therefore sets:

- configured fixed slots: 6;
- host-wide active Codex ceiling: 3;
- host-wide active Knowledge Analysis ceiling: 2;
- per-slot active ceiling: 1;
- support pool: slot05 and slot06;
- support-pool active ceiling: 2; and
- GPU ceiling: 1, unchanged.

One global Codex position remains available for the standard item pipeline. The implementation
counts held leases across capacity-policy revisions, not only within one revision, so historical and
new plans cannot jointly exceed the host ceiling.

## 6. Transaction and concurrency boundary

The Catalog scheduler locks one candidate batch header before checking its in-flight count and
claiming one range. The batch lock serializes concurrent scheduler instances. The range claim and
event append commit together; worker submission occurs outside that transaction through the
existing idempotent single-analysis service.

The old unique partial index allowing only one active range per batch is replaced by an ordinary
`(batch_id, state)` index. The aggregate bound is enforced while holding the batch-row lock. Legacy
rows have `scheduling_mode=SERIAL` and `max_in_flight=1`, preserving their exact behavior. Only
request 1.3 may set `BOUNDED_PARALLEL/2`.

Worker lease admission uses one stable transaction-scoped host advisory lock before counting held
leases. Locking only an immutable capacity-policy Revision is insufficient because V1 and V2 plans
can coexist during rollout. The shared host lock makes global Codex, Knowledge Analysis, and GPU
limits linearizable across policy revisions; the existing unique held-slot constraint remains the
last race-safe guard for one slot.

Each range still permits exactly one submission attempt. A lost create response may replay only the
same deterministic idempotency key. Parallel scheduling never authorizes an automatic retry.

## 7. Failure and completion behavior

The new request retains `CONTINUE_AND_COLLECT`: one terminal range failure is recorded and does not
prevent another pending range from being claimed when capacity is available. `SUCCEEDED` still
requires every ordinal accepted. After no active or pending range remains, any collected failure
terminalizes the batch as `BLOCKED` with the existing collected-failure code.

A final full-corpus acceptance must prove exactly 495 ordered ranges and 1,702 pages, with no gap,
overlap, duplicate range, duplicate analysis-run pointer, or missing accepted Artifact pointer.
Parallel completion alone never constitutes full-corpus acceptance.

## 8. Dependency direction and adapter ownership

- JSON Schema and frozen Pydantic contracts define worker inventory V2, capacity policy V2, and
  batch request 1.3 before service behavior.
- Catalog owns batch scheduling and transactional range claims.
- Orchestrator owns capacity resolution, lease acquisition, systemd unit selection, and worker
  lifecycle.
- systemd, polkit, Linux users/groups, runtime paths, and Codex CLI remain infrastructure adapters.
- GUI/API may display and authorize typed commands but do not implement scheduling or capacity
  rules.

## 9. Simpler alternatives rejected

Borrowing slots 1--4 for analysis was smaller in source code but would violate their reviewed
authoring, review, image, and item-management responsibility and could starve the single-item
pipeline. Running multiple Codex processes under slot 5 would defeat per-slot lease exclusivity and
mix one authentication/workspace identity across concurrent jobs. Enlarging page ranges would risk
visual omissions and change analysis quality rather than solve capacity. Lowering `xhigh` or
skipping PNG inspection conflicts with the accepted quality requirement. Adding two new support
slots was unnecessary because the host-wide analysis ceiling is intentionally two.

## 10. Rollout and rollback

Source, migrations, runtime identities, and fixed units are deployed only at a boundary with no
active or reconciling worker lease. Slot 5 is never killed for deployment. Slot 6 begins disabled or
AUTH_REQUIRED until its own device login and capability observation pass; root Codex credentials
are never copied.

Rollback stops new V13 submissions, leaves historical V13 plans and results readable, points future
starts back to V12/capacity V1, disables slot 6, and restores serial batch creation. It does not
delete a slot-6 workspace, lease, result, batch, or Artifact revision and never rewrites a submitted
range.

## 11. Required verification

- old worker inventory/capacity/batch schema bytes and hashes remain pinned;
- worker inventory V2 rejects duplicate IDs/users, wrong role, unsafe path, and slot/user mismatch;
- slot 6 systemd, polkit, workspace, user/group, sandbox, and auth isolation match slots 1--5;
- two support leases can coexist on slots 5 and 6, while a third analysis lease is denied;
- one additional non-analysis Codex lease can coexist, while a fourth global lease is denied;
- held leases under different capacity-policy revisions share the same host-wide ceiling;
- concurrent batch claimers never exceed two in-flight ranges and never claim one ordinal twice;
- legacy batches remain exactly serial;
- completion order may differ but final ordinal projection is deterministic;
- failures are collected, no automatic retry occurs, and full coverage is separately proven;
- migration upgrade, downgrade, and re-upgrade preserve historical rows and indexes;
- no large binary payload enters PostgreSQL; and
- no live Codex invocation occurs in default tests.

## 12. Single-runner capacity refill amendment

Observed V14 execution evidence showed a valid `BOUNDED_PARALLEL/2` correction batch using only
slot 5: four jobs ran sequentially even though slot 6 was eligible. The cause was scheduler
starvation, not worker or authentication failure. The single Catalog runner always reserved a due
submitted-range poll before attempting a pending-range claim. A long-running range became due again
before every subsequent loop and kept the second capacity position empty.

The runner now performs at most two bounded actions in that case: it commits one reserved poll, then
attempts one ordinary capacity refill. The existing batch-row lock, active-range count, partial
indexes, `max_in_flight=2`, per-range state machine, and deterministic range idempotency key remain
the authoritative concurrency and duplicate-submission controls. Serial batches cannot refill
because their one active range already equals `max_in_flight=1`. A failed stop-on-first range cannot
refill because its batch is terminal; continue-and-collect may refill as designed.

The simpler alternative of globally prioritizing claims over polls was rejected because a steady
stream of new batches could starve result reconciliation. The post-poll refill preserves poll
priority while ensuring an already selected bounded-parallel batch uses its reviewed second slot.
