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

## Scoped update preservation (2026-11-10)

The previous projection replaced every scoped entry even when a report tested only
slot 06. This removed slots 01–05 from the allowlist despite unchanged runtime and
account assignments. The existing Orchestrator policy projection now owns a bounded
**slot-scoped replacement**, not a second registry or a new worker protocol.

- Canonical inputs remain the protected installed predecessor policy, committed report
  pointer/hash, exact runtime hashes and current binding/assignment/slot/role records.
  Logical bindings, immutable assignments and policy hashes remain distinct.
- Preserve only V3 scopes on **untested slots**, with the same runtime and exact current
  binding/assignment/slot/role. Tested slots replace all their previous scoped models;
  failed cases do not retain an old PASS. V2 scoped entries require fresh validation.
  Global compatibility behavior is unchanged. Authoring/review still require a common
  admitted pair; losing one current assignment also removes the orphaned peer pair.
- Use maps/sets over six slots and at most 64 cases/32 entries. Lookup/aggregation is
  linear, canonical grouping/sorting O(entries log entries), with no DB/index/schema change.
- The existing installer resolves committed evidence, rechecks runtime/current bindings,
  uses an exact predecessor hash and filesystem lock, and atomically writes a new policy
  with a recoverable predecessor. Identical replay must produce identical bytes. No
  direct binding-state UPDATE, failed-history rewrite, model retry or auth-file change.
- The protected installer remains the filesystem adapter; policy decisions stay in
  `codex_compatibility_policy`. Existing control OBSERVE refreshes auth/capability state.
- Repairing the already-dropped scopes requires the exact protected predecessor backup
  plus the current committed slot-06 report, not an arbitrary old policy or a guessed
  model. Revalidate all pointers/runtime/current assignments and preserve the current
  06 scope before installation. If any pin changed, do not revive that scope.

Replacing all scopes is simpler but loses unrelated admitted work. Unconditionally
unioning policies is also incorrect: it could restore failed tests, changed accounts
or old executable versions. This narrow projection preserves only unaffected evidence.
Historical policy bytes and report schemas keep their original meaning.
