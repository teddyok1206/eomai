# Cooperative CPU admission for interactive reference queries

2026-10-16 UTC. Design before queue-read behavior. **NOT_ACTIVE**.
This closes the original incremental RAG plan's interactive/background scheduling
boundary; it does not replace the five consumers or the CPU/CUDA gates.

## Observation and protected meaning

The original authenticated HTTP request remained PENDING for its first600-second
observation. Read-only metadata at12:55 showed the same Workflow/attempt1 and one
original native allocation, not a failed or newly generated query. At13:00 the
kernel identified the INDEX owner as holder of the shared CPU lock; the query's
launch-prepared marker existed but its dispatch-attempted marker did not. Its exact
unit had no invocation. This demonstrates one real capacity wait, not proof of
permanent starvation or permission to relaunch an uncertain execution. The active
operator's900-second fresh-auth gate subsequently rejected observation; do not
extend it or reinterpret the earlier successful login as a bad password.

## Small design / required procedure

1. **Responsibility/boundary:** the existing background INDEX application yields
   before another queue claim/discovery while an interactive reference QUERY
   actually owns a current command lease. Do not preempt in-flight native work.
2. **Canonical source:** existing Workflow and command rows. Scheduling metadata
   is not source/Graph/session/native authority; actual owners still reauthorize.
3. **Identity/revisions:** preserve original Workflow, command, attempt, request,
   native allocation and released definition identities. No new aggregate/revision.
4. **Pointers/checks:** join commands to their exact Workflow; require the released
   reference-query definition key, RUNNING/LOCAL_EMBEDDING, human owner match,
   START/ADVANCE command, LEASED/PROCESSING, populated lease identity/generation,
   and unexpired lease. Do not inspect private text, source pointers or credentials.
5. **Access:** one EXISTS per background loop, not a source/target scan. Return
   a boolean only; no query IDs/counts are delivered to the service's workers.
6. **Structures/indexes:** reuse command state/claimable B-tree and Workflow PK.
   Bound work by current leased commands; no new queue/table/index/cache/lock file.
7. **Complexity/scale:** O(log commands + active-lease candidates) indexed filtering
   and PK joins; one scalar and constant application space. Verify the actual SQL
   plan on synthetic disposable data; no production load test.
8. **Transaction/concurrency:** a short fresh READ ONLY transaction ends before
   waiting/claiming/inference. This is a cooperative hint, not an atomic resource
   reservation: the existing shared physical CPU mutex and native fencing remain
   authoritative if the query arrives after observation.
9. **Dependency direction:** the Runner's scheduling-read adapter owns SQL; runtime
   application exposes the decision; the entry loop schedules existing use cases.
   No domain/contract DB import, cross-component table mutation or model calls.
10. **Failure/retry:** metadata unavailable defers new background work with a safe
    bounded transition log, never guesses idle. The loop waits interruptibly using
    its existing5-second cadence. It changes no Job/command state or attempt.
    Expired, terminal and merely pending history cannot block INDEX indefinitely.
11. **Simpler alternative:** a nonblocking shared mutex alone protects capacity but
    does not coordinate prospective background claims with a currently leased
    interactive request. Increasing concurrency, adding random retries/waiters,
    disabling auth or inventing a second scheduler is unnecessary.

This is not strict global priority/FIFO or a deadline guarantee. Only already
leased current reference-query work is observed; an unobserved browser request or
a future private-query family needs its own actual admission. A pending row alone
does not prove a live authorized requester. No priority rule grants permission to
execute another caller's command or widen a source policy.

## Verification / activation

Test active/unexpired versus terminal/expired/missing lease, actor/family/state
mismatch, exact single-query SQL, no content/row lock/DML, fail-closed read errors,
no INDEX claim or discovery while deferred, interruptible stop and resumption with
unchanged round-robin order. Guard PostgreSQL fixtures and query-plan checks with
the existing disposable test database mechanism. Preserve all old native history.
Source tests do not prove installed behavior: install a compatible INDEX owner
successor without changing numerical space/payload, verify current QUERY admission
and same original execution, then perform the existing authenticated HTTP check.
Do not ask the user to authenticate again before these runtime prerequisites close.

### Source and disposable PostgreSQL evidence —13:33 UTC

Focused source tests32 PASS, expanded regression171 PASS, strict type checking of
the two production modules PASS, and Ruff/format PASS. These overlapping runs are
not additive coverage. The guarded `embedding-stage-tests` run completed208 PASS
in203.10seconds, including18 scheduling tests and a real query-plan assertion with
10,000 synthetic historical commands using `ix_workflow_commands_claimable`.
An uncommitted writer did not block the read; the next snapshot observed its commit.

The first guarded run was207 PASS/1 FAIL because a new test tried to rewrite an
immutable Workflow definition. The existing DB trigger correctly refused it. The
fixture now creates a genuine other-family Workflow through the supported INDEX
submission instead; no production constraint was relaxed. Both disposable DBs
were removed by the existing official cleanup command. Failure evidence remains.

Logs are in the temporary operator directory
`/tmp/eom-cuda-protected-candidate-34ayfVS1`, including
`cpu-priority-postgres.log`, `cpu-priority-postgres-v2.log` and both cleanup logs.
This is **SOURCE_PASS / POSTGRES_PASS / NOT_ACTIVE**. Existing operating INDEX
identity14 and original QUERY allocation remain unchanged by these tests. A source
PASS is not proof of physical CPU fairness or completed authenticated delivery.

### Bounded installation/drain plan —13:38 UTC

Candidate`c69833324f4ba16d7b51a04c633c1ef61a36c263` was built with the existing
three-wheel/RECORD gate. Stage only its platform/API-contract pair through the
existing protected owner installer; keep the CPU numerical environment and
operating QUERY release unchanged. Staging does not activate a service identity.

For the operating INDEX, match PID1953488, invocation
`36f20dd36c444cc780b52fe8eed41fbe`, Restart=no and all three selected file hashes
before requesting its existing SIGTERM stop Event on the main process only. Do not
issue a systemd stop job with its four-minute kill deadline: the current command
may legitimately take longer. No native child signal, forced termination, DB state
repair, new execution identity or automatic retry is part of this drain request.
The current pinned command must finish naturally before checking terminal states.

Only after actual main-process exit and no unfinished old-identity commands may
the existing Identity/Catalog control publication select a compatible successor.
If a queued command remains, keep the old identity/pins and resolve it through
supported original execution or unstarted cancellation, not a rewritten request.
Retain current files/releases as rollback evidence. Drain failure means no file
selection or identity change; it does not authorize timeout escalation.
