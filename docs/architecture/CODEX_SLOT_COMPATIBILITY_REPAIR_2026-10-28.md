# Fixed-slot compatibility repair during unrelated embedding work

Status: implementation design, 2026-10-28 UTC. This does not approve a model call or change a production policy by itself.

## Observed failure

The installed Platform adapter expects `eom-worker-exec` SHA-256 `b2c96d46…`, while the protected executable and reviewed capability policy still pinned `ea022ab5…`. All six bindings consequently report `CAPABILITY_OBSERVATION_FAILED`; stale usage percentages do not establish quota exhaustion. The executable was copied from the exact admitted API source snapshot under a stopped-worker/no-lease fence, with the predecessor retained for recovery. Runtime identity now passes, but the old policy cannot authorize the new executable without fresh compatibility evidence.

The existing global compatibility maintenance preflight rejects *all* nonterminal Platform jobs. That correctly protects its original all-producer maintenance mode, but an unrelated GPU embedding job (and older unresolved embedding rows) makes it impossible to revalidate fixed Codex slots while indexing continues. Do not rewrite those rows or stop GPU INDEX to make the gate pass.

## Scoped diagnostic boundary

1. **Responsibility/boundary:** add an explicitly named fixed-slot compatibility mode to the existing Orchestrator compatibility use case and CLI. Keep the original global maintenance mode unchanged. This is diagnostic execution, not ordinary Workflow execution or an account-login shortcut.
2. **Canonical source:** current binding/assignment records, the protected installed CLI and worker executable, released capability policy, and the immutable compatibility report Artifact. No spreadsheet, frontend value, or local report JSON grants capability.
3. **Identity/revisions:** reuse `codex-compatibility-request/1.0`, exact binding ID, assignment revision, resource version, source commit, run ID, case ID, and existing checkpoint/report/Artifact identities. No new DB table or wire schema.
4. **Pointer checks:** the existing request validator, protected executable hash/epoch guard, exact binding comparison, Artifact publication, and policy install must all pass. Stale or changed bindings fail closed; no `latest` substitution.
5. **Access pattern:** six ordered cases, indexed binding and lease lookups, physical fixed-worker unit check before each launch, append-only per-case checkpoint. Existing immutable tuple and DB indexes suffice.
6. **Scale/complexity:** at most 64 bounded cases by the existing contract; this repair requests six. Checks are O(cases + indexed active claims), without scanning or materializing corpus data.
7. **Concurrency:** acquire the existing global host-capacity advisory lock before inference. In scoped mode require zero active/reconciling fixed-worker leases, zero processing control commands, and no active fixed-worker/helper unit; permit unrelated GPU Platform jobs and already-running general-chat work. The lock prevents new claims while held; if another owner has it, fail before a model call. Existing work is never cancelled or restarted. This may delay *new* GPU claims during the bounded probe window and must be observed.
8. **Dependency/ownership:** CLI is presentation, Orchestrator application owns validation/checkpoints/fence, infrastructure inspects DB and systemd. Worker has no direct DB/NAS access; Orchestrator alone publishes the report.
9. **Failure/replay:** fixed request/epoch/checkpoints remain the only replay identity. A failed or uncertain case is not retried under a new identity automatically, and neither FAILED history nor approved policy is reinterpreted. A policy update still requires the official committed report pointer and exact predecessor hash.
10. **Simpler alternative:** retaining the old policy after only a file-hash change would falsely treat untested executable bytes as admitted. Stopping GPU or editing old Platform rows would disturb unrelated work. The scoped fence reuses the already-tested enrollment pattern and compatibility publisher without a new queue/framework.

Exit checks: each admitted pair PASS under the new helper SHA; official policy installation pins that report; supported OBSERVE shows only admitted bindings available. If a quota/model failure occurs, record it as such and leave unsupported pairs blocked. Creative solution-report execution remains out of scope for this repair.

## Quota-limited role admission (2026-10-28)

The six fixed slots are independent account assignments, but authoring slot 01 and
review slot 02 require a common tested model/effort pair before either is admitted.
If slot 01 reaches its provider usage limit, a fresh report may still admit an
actually passing image, item-management, or support slot without carrying forward
old scoped claims. The report remains the canonical immutable evidence; the
current runtime, assignment, permission, and hash checks remain unchanged.
An all-failed or authoring-only report admits nothing. This changes only policy
projection, with no DB, wire schema, queue, or worker protocol change. Access is
bounded keyed lookup over six slots and linear aggregation over at most 64 cases.
The simpler all-or-nothing projection is insufficient because one account's quota
otherwise disables independently verified roles. A quota-limited account remains
unable to execute; no failed report is rewritten or treated as a PASS.
