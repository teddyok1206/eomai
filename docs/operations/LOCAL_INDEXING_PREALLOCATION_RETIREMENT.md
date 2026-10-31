# Corrected-release handoff before any native allocation

This is explicit deployment-owner maintenance, not a worker/runtime retry feature.
Design: `../architecture/LOCAL_INDEXING_SELECTION_AND_INITIALIZATION.md`.
No schema migration, new queue, external API, worker privilege or force flag.

1. Observe the exact unit/process/invocation, original Workflow and command.
   An observation timeout is not proof of terminal execution. Preserve logs and
   inspect actual native launch/encoding Job state. Do not submit another key.
2. Diagnose the missing encoding-protocol deployment prerequisite. Prepare its
   exact released hash through the Orchestrator's explicit owner operation, never
   by a runtime read/self-grant or by changing a different existing hash.
3. Build/validate/immutably install the corrected owner release WITHOUT activation.
   Fix source/test invocation issues in development. Do not patch installed files.
4. Freeze a `local-indexing-preallocation-retirement/1.0` COMMAND with the exact
   old service reference, Workflow/request SHA, START command/generation, closed
   cause and intended successor source commit. Store exact canonical bytes for
   replay. A command is the actual deployment owner's explicit classification,
   not autonomous proof inferred merely from an expired lease.
5. As the real PostgreSQL table-owner login, in one clean read-committed root call
   `eom_workflow_runner.local_indexing_preallocation_retirement.
   retire_unallocated_indexing_workflow(session, command)`. The supported use case
   owns all checks/transitions/audit; do not UPDATE rows or insert events by hand.
   It must refuse live leases, allocated/uncertain work, output, extra commands or
   steps, foreign/stale service/pointers and nonowners. NOWAIT conflicts require
   root rollback then exact observation/replay, not force or broad cancellation.
6. Read back the same receipt/state. Original Workflow, stage, command and step
   are FAILED, with the diagnosed code; initial request/hash/keys/lease audit and
   all historical events remain. Job/Artifact/vector/index counts must not change.
   Same command replay returns the original receipt without another event. A
   changed successor commit conflicts rather than relabeling the old retirement.
7. Only after original terminal proof, use ordinary supported Identity register /
   activate, Orchestrator policy publication and Catalog released grant operations
   for the corrected release. Preserve its immutable controls/hashes/rollback.
   Reconcile through the existing authorized missing-binding application, not a
   handmade target list or a DB-created Workflow. Verify actual source/plan pins
   and link the new Workflow to this retirement in the operational evidence.
8. Report first seed/native result/Artifact commit/binding/index separately from
   source tests, failed-original retirement and service startup. Full corpus and
   delta/query/consumer/GPU acceptance still require their own actual evidence.

The retained DB receipt is authoritative retirement history. A local receipt file
is temporary operational materialization, not a second canonical execution. The
function grants no source access and starts no successor. A runtime rollback does
not undo the historical failure or revive its command; future work must use its
own explicit compatible authorization and normal idempotency/claim boundaries.

## Public source metadata3/4 compatibility

The command/receipt1.0/1.1 bytes pin an exact Workflow request SHA, not a request
family name. Apply the same supported service-reference resolver to stored
requests1–4; do not recast public requests as legacy requests or change their hashes.
The canonical state remains the original Workflow/command/step and append-only
retirement receipt. All ID lookups, bounded row locks, real table-owner checks,
expired lease, absent launch Job/output and successor-release checks remain intact.
There is no new queue, table, protocol version or runtime self-repair permission.
The operation still refuses human requests and allocated/uncertain native work.

For a routed GPU request, the deployment owner must additionally verify the exact
physical controller is terminal and its retained handles are closed before
calling this operation: an allocated parent is not proof of a numerical launch,
and absence of a completion is not proof of a dead controller. A cold parent with
no numerical completion must not silently dispatch its original allocation again.
Retain that failure and let the corrected release's existing missing-binding
application create its own authorized successor. A direct row update or an
unfenced second allocation is not an alternative.
