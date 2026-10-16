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

At13:43:29 UTC the original process was still naturally draining its PROCESSING
command (attempt/generation1). Exactly one further START was PENDING with
attempt/generation0, absent lease and zero steps: Workflow
`workflow_da99e553b6484ef4a84db9c99ae156b1`, command
`wfcmd_50bf70fafc694d45a288d4d13dba7736`, request SHA
`2900c81e329764033a18ff3f8859bbdb566d697137c13d15f390909a392c1689`.
Prepare its exact existing `local-indexing-unstarted-cancellation/1.0` command
only after normal service exit, using the installed supported deployment-owner
application. Execution, if its guards still pass, records truthful CANCELLED
history, not success, with no claim/step/Job/model. Only subsequent normal
missing-binding reconciliation can discover successor work. This is the
previously specified unstarted branch, not permission to cancel active work.

Only after actual main-process exit and no unfinished old-identity commands may
the existing Identity/Catalog control publication select a compatible successor.
If a queued command remains, keep the old identity/pins and resolve it through
supported original execution or unstarted cancellation, not a rewritten request.
Retain current files/releases as rollback evidence. Drain failure means no file
selection or identity change; it does not authorize timeout escalation.

### Operating selection evidence

As of2026-10-16 13:54 UTC.

The original INDEX invocation exited naturally at13:43:51 UTC, status0/success.
At13:45:29.963866 UTC, the installed public cancellation application under actual
DB-owner principal`eom_app` cancelled only the pinned never-started command above.
Original request/key/service14, attempts/generation0 and zero steps were retained.
Receipt semantic:`f7a514677ae2342b9cd16be0bf21cb9ef08f76e21fac4a80978fd01f225ebef0`;
raw:`3ed46c30191bda4702b0cbeaab1ed2f4f510152bfb4205dedb80e4c960e5fe9a`.
No Job, Artifact or model call was created by cancellation.

The existing protected installer staged the exact c6983332 owner pair INACTIVE.
Its installed import proof loaded213 EOM modules solely from that release; queue
presence was synthetic SQL, with zero actual DB/model calls. The numerical CPU
prefix, its B41 host seal and the operating QUERY owner did not change.

Only actual Orchestrator UID990/GID1000/empty supplementary groups committed the
new native control policy, with zero permitted/effective/ambient capabilities and
NoNewPrivs1 before EOM imports. Job:`job_82d4251748f34a86a65b41e6e6b72ee0`;
Artifact:`artifact_2e48c03cd60e43dc890c926d70014674`;
revision:`rev_366d10ad73d64bbf9867acd54e9db94c`;
policy raw:`4c8db635a9bbe23d40778eeebc86b62a0e6568b3f4859720d5f994f2fb305add`;
semantic:`9fc767ff4853dfcf2070bc5bd89efe7fd5264a8346216eb8defc580f93e5b4ca`;
manifest:`f0d5cdfca33bbcd72d50e38854349bfd78ed6d1ffe6bb81fe94ace740a1b49fb`.
The first three finite operator launches failed before publisher imports/Job
creation: missing effective UID-switch capability, a root-only diagnostic check
inside a lower-UID0700 directory, then the same capability boundary. Actual own-
process diagnostics showed bounding capability was not an effective grant. Reuse
the existing QUERY supervisor's explicit bounded ambient UID-switch pattern;
the finite proof verified zero capabilities after dropping IDs. No production
rule, auth fence or service account membership was weakened. Failed units/logs
remain; the fourth launch made the single actual policy publication.

Public Catalog independently checked its producer, manifest, bytes and hashes.
Public Identity operations registered/activated service revision15/resource30:
`localindexservicerev_932e10f72a064234b6617c44333dc9ca`, semantic
`9c2ffb5106d0517f8c01f353b9601adf36b4dbb82927ce4b3232ac3296e1d7c0`.
The new grant is`accessrev_8b50aba2d58848e7b2f17cef105a03a5`, semantic
`7926486d341ef55f5f025db3c0cb41544fd20a31289d26238b0c80d3347b7b95`.
Namespaces, source classes, encoder space/profile, max4/poll60 and numerical
environment/verifier are unchanged. Exactly four owner control-pointer fields
changed; the unit differs only by its selected source commit.

Stopped-owner file selection/readback PASS:
runtime raw`cd1569f5f2aad33ffb9bd2671e71ce83e303c704d9162d9b1a7244304cfa34f2`,
owner raw`c426bb831188b7167ddd935b61ff935f008c5e48ed3dcbe78e958bf9f584fb3e`,
unit raw`6c3b5a5815789cdb23f068d29417aeb521fd1b7267b74546f9e49b63958015bc`.
Root evidence/old files remain in`/var/lib/eom-indexing-priority-c6983332`.
**SELECTED_NOT_STARTED**: keep INDEX paused for the original authenticated QUERY
window, then observe its actual deferred/resumed behavior before claiming live
priority acceptance. Source/PG/install/control selection is not that acceptance.

At13:54:58 UTC read-only operator metadata still showed the exact original QUERY
Workflow/step attempt1, original Job allocation1.1 only and no numerical completion.
Its selected native policy/bundle still match. No request/key was regenerated.
This metadata is not fresh user authorization or authenticated C1 acceptance.

### Bounded end of the operator pause

Do not starve automatic indexing while the operator is away. Schedule one standard
systemd deployment action for2026-10-16 14:15 UTC (not a new production scheduler).
The root-owned stdlib-only helper accepts no arguments, credentials or source
input; it matches the three exact selected file hashes and requires inactive/
success before starting only the existing INDEX unit once. Already active means
no additional start. Failed/mismatched or execution after14:20 means refusal,
not retry, reconfiguration or failed-history reset. No boot enable is changed.
The action uses no DB/Artifact/model API; the normal installed owner still owns
every source/identity/claim/native check. If the human QUERY is then leased, its
new preclaim gate must defer; otherwise normal bounded missing-binding work can
resume. Scheduling/start requests alone are not READY or live-priority evidence.

### Actual restart and initial discovery —14:17 UTC

The fixed one-use timer invoked its checked helper at14:15:00.239952 UTC and
exited successfully after exactly one start request. It made no DB/auth mutation,
direct native/model launch, forced stop or boot-enable change. No permanent sudo
grant, credential cache or authentication lifetime change was introduced.

The actual c6983332 INDEX owner passed its installed/runtime composition and
emitted SERVICE_STARTED at14:15:21.858162 UTC, PID2291322/invocation
`e30682cfae184d7391936b3356ecb224`, active/success/NRestarts0. Its normal
reconciliation queued original max4-target CONTENT_ONLY and CONCRETE_FACETS work
at14:16:17 and14:17:12, using the same Graph and source scope. This proves actual
startup and initial normal discovery, not completed new vectors or whole coverage.

**STARTED / LIVE_DEFERRAL_UNVERIFIED / C1_UNFINISHED**. The new gate has not yet
been observed while a real active human QUERY lease exists. The original HTTP
observer awaits fresh Studio authentication in EOM1; old successful login and
later freshness rejection remain distinct evidence. Routine INDEX observation
next no earlier than14:47:30 UTC; a bounded real-request/deployment check is a
separate opt-in boundary, not permission for frequent corpus polling.
