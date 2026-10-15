# Official Identity operator-row fence proposal

2026-10-12 UTC. Narrow Identity adapter/static SQL inspection approved for source-only implementation;
migration, grants and runtime composition still require main-agent review. The 17 native protocol
paths remain frozen. No migration number is reserved and no
`CURRENT_MIGRATION` change is proposed here. Read with the native Runner admission proposal and
incremental embedding registry design. Background service admission remains explicitly unavailable.

## Owner-install operation follow-up — 2026-10-15 UTC

The actual Catalog-role preflight found the fixed routine absent (zero overloads),
while file/schema/hash and actual role checks passed. Runtime composition remains
disabled; this is not a reason to weaken the read adapter or add IAM table writes.
Add `install_operator_authorization_fence(session, owner)` within Identity, using
the frozen SQL/signature/body and existing exact installation inspector below.
No cross-service message or persistent schema changes: a small frozen internal
result reports CREATED/REPLAYED, the pinned owner and body hash, not a grant.

Responsibility/canonical source/pins/indexed access/dependency/concurrency remain
the eleven points below. Installation additionally requires a clean explicit root,
actual SESSION_USER=CURRENT_USER=pinned schema/operator-table owner and OID, no
SET ROLE, read-committed writable PostgreSQL/psycopg and bounded waits no weaker
than caller limits. A fixed nonblocking transaction advisory lock serializes this
one routine name; one savepoint contains CREATE, default PUBLIC EXECUTE revoke,
fixed Catalog EXECUTE grant and exact final inspection. Caller owns root commit.
Existing exact installation replays with no DDL; overload/owner/body/ACL drift
aborts without OR REPLACE or repairs. Installation failure rolls back new DDL/ACL.
No automatic schema-USAGE repair, cluster role change, IAM grants, arbitrary SQL
input, worker access, source reads, model execution or new dependency is permitted.
The actual installed/runtime proof is separate from source and disposable tests.
Reusing raw constants in an ad hoc release script would omit owner/replay/atomic
validation; extending Identity's existing supported control boundary is sufficient.

## Eleven-point boundary

1. **Responsibility:** implement the existing public
   `OperatorAuthorizationFence.fence_current_operator(session, operator_id) -> None` seam in official
   Identity infrastructure. It holds one operator row against supported permission/status/password
   denial writers during a short Catalog root transaction. It does not authenticate an operator,
   return authority, validate a session, authorize source reads or register an index by itself.
2. **Canonical source:** current `app.operators`, actual active role assignments and current permission
   joins are authoritative. Old request operator IDs, permission digests, `ActorContext` permissions,
   cached ORM state and service-audit metadata are not current grants. Catalog still independently
   applies its pinned released source policy and exact Graph/source/report/Artifact checks.
3. **Identity/revision:** the only function argument is the exact owner-captured `operator_` logical ID.
   Do not accept a username, worker role, requested SQL identifier, principal replacement or policy
   hash as authority. Existing operator/credential/role versions and UTC audit history are unchanged;
   this fence is not a new identity revision, service principal or token issuance system.
4. **Resolution:** require a live PostgreSQL `READ COMMITTED` root Session transaction, the exact fixed
   function/signature/owner/security options and least-privilege EXECUTE profile. Hold the row lock,
   then refresh current operator state and query current roles/permissions before source admission.
   Missing function, wrong isolation, missing/deleted/disabled/password-change-required operator,
   schema/owner/ACL drift or lock failure is unavailable/denied, never an advisory-lock fallback.
5. **Access patterns:** one indexed operator-ID lookup/row lock, followed by existing indexed active
   role/permission joins and bounded official source closure. Concurrent readers may share the row;
   supported target denial writers already use `FOR UPDATE` and must wait until root commit/rollback.
6. **Structures/indexes:** reuse the `operators` primary-key B-tree, existing active-role lookup/index
   and role-permission keys. A private per-adapter weak Session-keyed root-lock witness supports the
   existing outer preflight/inner savepoint calls; it caches no authority or source/session state.
   No new table/index, global IAM lock or general lock registry is introduced.
7. **Scale/cost:** operator lookup is O(log O) for O operators; hold one row, not a corpus-wide scan.
   Scope cost remains bounded by the existing source operation. Lock/statement waits must be bounded
   by trusted owner settings. No SQL transaction/fence is held through model load, GPU execution,
   queue waiting or a long-running benchmark. A later phase reacquires and reauthorizes exact pins.
8. **Transaction/concurrency:** first acquire the operator fence before current permission/source
   checks in a nonnested root transaction and retain it through root commit/rollback. A later call
   inside the existing savepoint is permitted only with this adapter's exact retained-root witness;
   it acquires no target-row lock there and still refreshes/rechecks actual current state. No first
   acquisition inside a savepoint or separate/autocommit connection. Denial committed first is seen;
   metadata commit first is ordered before that denial.
9. **Dependency/ownership:** Identity owns the concrete adapter and cooperating target writers;
   Catalog imports only its existing explicit public fence interface, not a private IAM repository.
   Migration/release owners install the SQL routine and reconcile exact function privileges. Catalog
   retains SELECT-only IAM tables; it receives no table UPDATE, credentials/session/token access,
   role membership, DDL, superuser or OS privilege. No new dependency is needed.
10. **Failure/retry:** return `None`, not a grant/projection/permission boolean. Stable content-free
    adapter errors map into existing Catalog unavailable/forbidden labels. Database lock timeout,
    deadlock or transaction failure aborts the root operation; a supported retry starts a new root
    transaction and repeats fresh transport, row, permission and source checks. Never reuse a prior
    successful fence as a lease or bypass denied source/index closure on idempotent replay.
11. **Simpler alternative:** SELECT-only Catalog cannot take a row lock requiring UPDATE privilege;
    adding broad IAM UPDATE is excessive. Existing Identity advisory locking does not cover
    `AuthService.change_password()` and is not a substitute for the target row lock. A fixed definer
    routine supplies only that lock. A general IAM framework or broad token-rotation rewrite is
    unnecessary for this operator-row boundary; session freshness remains a separate owner gate.

## Actual writer inventory and exact scope

Paths below are existing source observations, not evidence of installed/live readiness. All Identity
paths are under `services/identity_service/eom_identity_service/`.

| Existing owner path | Actual locking / effect | Relationship to proposed operator-row fence |
| --- | --- | --- |
| `repository.py:require_operator(..., for_update=True)` / `operator_by_username(..., for_update=True)` | Target operator `SELECT FOR UPDATE` | Conflicts with the shared target-row lock |
| `service.py:assign_role/revoke_role` | Target row lock before assignment mutation; update role/lock versions | Already cooperates; role revoke also takes the existing invariant advisory lock |
| `service.py:disable/delete/enable` | Target row lock before status/soft-delete changes; disable/delete revoke sessions; delete also retires roles/credential | Already cooperates; no hard-delete or row repair is added |
| `service.py:revoke_sessions` | Target row lock before bulk session revoke | Orders the writer, but row-fence success still cannot prove a particular session is active |
| `auth_service.py:change_password` | Operator `FOR UPDATE`, then credential lock, password update and token/session retirement | Already cooperates despite not taking the global invariant advisory lock |
| `auth_service.py:update_credentials` | Same operator/credential row locks; invariant advisory lock only for username changes | Already cooperates for password/username/token retirement |
| `local_admin_recovery.py:reset_admin_password` and `approved_login_id_recovery.py:reset_approved_pair` | Existing invariant lock, target operator lock, then credential mutation/required-password flag/session revoke; approved pair locks sorted IDs | Already cooperates; preserve their narrow local authorization and one-use recovery semantics |
| `auth_service.py:login` | Operator and credential row locks; failed-login lockout / successful session issuance | Also conflicts, but login lockout currently denies login, not every already-issued access session; do not broaden its meaning |
| `auth_service.py:logout` / `logout_all` | Session-row lock only / bulk session UPDATE, no target operator lock | Not covered by this row fence; separate session-freshness scope, not a reason for an automatic rewrite |
| `tokens.py:authenticate_access/rotate_refresh/_revoke/rotate_current_session` | Session/token locking and expiry/reuse/revocation/rotation; operator lookup is not `FOR UPDATE` | Session/token denial and natural expiry are not established by an operator-ID fence |
| `repository.py:revoke_operator_sessions` | Bulk API-session UPDATE helper | It does not acquire an operator lock itself; listed target-locking callers cooperate, `logout_all` does not |
| `repository.py:seed_builtin_rbac`, `service.py:bootstrap_admin`, `scripts/api/reconcile_structured_item_permission.py`, RBAC migrations | Role/permission matrix bootstrap/reconciliation or migration writes, not target operator locking | Explicit release/bootstrap maintenance exception below |

Repository-wide source searches found the routine denial writers in these Identity owners and
role-matrix mutation in bootstrap/reconciliation/migrations, not a second runtime role-management
owner. This is a source inventory, not a claim that unreviewed administrator SQL cannot bypass it.
All supported future permission/status/password target writers must preserve target-row locking.

`seed_builtin_rbac()` adds missing built-in roles/permissions/pairs and rejects unexpected existing
built-in pairs; it is not a normal per-operator permission-revocation API. Initial bootstrap is meant
for the empty operator database, while the reviewed reconciliation script can add matrix pairs after
operators exist. RBAC migration downgrades can delete permission pairs. Such matrix operations do
not cooperate with an operator-only fence: require a reviewed drained maintenance/release boundary,
exact intended matrix delta and no concurrent admitted source operations. Do not silently bless
online matrix mutation, invent a broad global IAM fence, alter role grants, or repair rows as part of
native admission. If runtime matrix revocation is later required, it needs its own owner-reviewed
cooperation design and tests before activation.

## Fixed SQL routine and limited-role admission

Proposed exact raw signature: `public.eom_fence_operator_authorization_v1(text) RETURNS void`.
No other overload, default argument, variadic argument, alternate schema or arbitrary function name
is supported. The concrete adapter invokes the qualified fixed name with a bound operator argument
explicitly cast to `pg_catalog.text`; never interpolate an identifier or inspect worker SQL.

The routine is a static PL/pgSQL, `VOLATILE`, `PARALLEL UNSAFE`, `SECURITY DEFINER` function, with
`search_path=pg_catalog,pg_temp`. `public` and `app` are not searched; its one table reference is
explicit `app.operators`. It validates non-null exact ASCII `operator_[0-9a-f]{32}` input, then locks
that ID with `FOR SHARE` (not `FOR KEY SHARE`, `SKIP LOCKED` or a weaker advisory substitute). Lock
by identity, not a pre-lock ACTIVE filter. A missing row raises a fixed content-free failure. It
returns no state, permission, credential, token, approval or row payload. Use explicit null rejection:
`STRICT` alone would silently skip the function on null input. No dynamic SQL, DML, durable writes,
exception-to-success handler, role switching or helper callbacks are permitted.

Function owner is the existing trusted application-schema migration owner, whose exact role/OID is
independently admitted by the protected release gate (`current_user == app` namespace owner in
`scripts/api/release_operator_runtime.py`), not an invented hardcoded `postgres` identity, Catalog
runtime or worker. The owner must already be able to lock `app.operators`; do not create a new IAM
owner role or grant blanket UPDATE to the caller. Record/check the admitted owner and exact reviewed
routine body/options, including explicit `app` table binding, as release metadata. Caller-supplied
owner text or a source-worktree hash alone does not establish that installed function.
The exact authorized EXECUTE principals are that trusted function owner and the dedicated Catalog
runtime, not PUBLIC or arbitrary owner-selected service roles.

Creation/owner/options/ACL installation is one privileged migration transaction: revoke default
PUBLIC EXECUTE before committing and grant EXECUTE only on this raw signature to
`eom_catalog_manager_runtime`. Grant that role only necessary `USAGE` on `public` for this qualified
call, never `CREATE`; preserve the existing exact table grants and no inherited role memberships.
The Catalog bootstrap currently revokes its explicit `public` schema privileges and grants `app`
USAGE; function admission must be an explicit additive reconciliation, not an accidental reliance on
PUBLIC defaults. Validate effective schema permissions and inherited/default privileges as well as
explicit ACLs. If `public` is writable by an untrusted effective principal, report a separate schema
security prerequisite; do not silently perform a broad global privilege migration.

Readiness must check exact function namespace/name/one-text-argument/void result, admitted owner,
definer flag, volatility/parallel setting, safe `search_path`, reviewed body, no unsafe overload, no
PUBLIC EXECUTE and the exact supported EXECUTE principals. PUBLIC/unrelated-role EXECUTE, wrong
owner/body/options, absent function/USAGE, or Catalog IAM UPDATE/credential/session/token access
is a failed admission gate. No new API/Runner function grant is inferred; if another real consumer
later needs this seam, review its own exact profile first. The function does not override read-only
transactions or make autocommit invocation a retained fence.

## Freshness, root transaction and transport are different checks

The concrete Identity adapter requires an already-active root transaction on the caller's exact
PostgreSQL Session; it neither commits nor creates a separate connection/transaction. Reject
AUTOCOMMIT, read-only transactions, first acquisition in a nested/savepoint transaction and
non-`READ COMMITTED` isolation. Bound waits using trusted owner transaction settings;
timeout/error aborts the root operation. Do not replace expired/failed fences with unlocked SELECT.

The concrete source adapter uses a 5,000 ms row-lock cap and 10,000 ms statement cap for its own
checks/lock/refresh. It reads the actual numeric millisecond settings and chooses the lesser of each
positive owner setting and that cap (zero/unlimited uses the cap). A trusted 1 s setting is never
weakened to 5 s. Successful return restores the prior owner setting strings exactly; failure retains
bounded settings until required rollback. These are transaction-local settings, not role/engine/
global changes. Installed routine/schema/ACL inspection remains read-only and installs nothing.

Because existing ORM mapping is schema-neutral, the refreshed operator SELECT explicitly uses
`schema_translate_map={None: 'app'}` for that one query. The new native fence also requires current
effective schemas exactly `['app', 'pg_catalog']` and `pg_my_temp_schema()==0` before each acquisition
or witness reuse. This prevents temp/schema-shadow state from passing the new boundary while
Catalog's existing role joins remain unqualified; it neither changes the global search path nor
rewrites unrelated legacy temp-capable features. No worker-selected temp name/content is read.

### Retained-root witness refinement for the actual savepoint composition

Source review found that `register_embedding_index()` currently performs its original verification
inside `session.begin_nested()`. Locks first acquired after that savepoint could be released by
savepoint rollback; unconditional nested acceptance is therefore unsafe. The proposed smaller
refinement keeps first acquisition nonnested and requires an official `authorize_scope` preflight
on the same configured adapter and root Session before registration enters its savepoint. Root
owns that later Catalog placement change; these Identity files do not alter frozen Catalog behavior.

The adapter owns `WeakKeyDictionary[Session, _RootOperatorFenceWitness]`, not a mutable global cache.
Its private frozen witness stores weak references to the exact `SessionTransaction` and `Connection`,
the one exact operator ID, acquisition thread, backend PID and database transaction ID. A strong SessionTransaction
reference would retain its Session and defeat weak-key GC, so both references must be weak. Lookup
is O(1) expected; memory is O(active witnessed Sessions), no persistence or revision lifecycle.
A small per-instance lock protects only dictionary membership, never SQL or permissions.

Record a witness only after the actual fixed routine acquired the row lock in a nonnested root
and the fresh operator checks succeeded. A later call may be nested only if this exact adapter's
witness matches the live Session/root/Connection/operator/acquisition-thread/backend/DB transaction identity; skip the
fixed row-lock call in that branch. Always recheck context/installed function and refresh the actual
row before current permission/source queries; a witness is lock lifetime evidence, never a grant.
Changing operator in the same witnessed root is unsupported. Missing witness, a different adapter,
root replacement/rollback, connection invalidation or DB transaction change is unavailable; discard
stale evidence. Concurrent use of a Session/wrong-thread witness is rejected. Session GC automatically
evicts the weak key. Never reacquire inside a savepoint to
repair missing evidence, transfer a witness DTO, or cache operator/permission/session approval.

Prepared tests must prove first nested acquisition fails; genuine outer-root acquisition permits
inner reauthorization; nested rollback does not release the outer row lock; stale/replaced root,
changed actor/connection/DB transaction, different adapter and GC cannot reuse it. This is smaller
than refactoring registration's existing replay/unique-race savepoint and its transaction ownership.

After the function returns, reread the actual operator row with `populate_existing=True` (or an
equivalent explicit refresh) before `_scope()` can call `session.get(OperatorRecord, ...)`. Validate
current ACTIVE/not-deleted/not-required-password-change fields, then perform new SQL joins for
active roles/current permissions and the exact released policy. The existing factory uses
`expire_on_commit=False`: neither `session.get()` nor a prior ORM object guarantees fresh state.
READ COMMITTED gives new statements fresh committed snapshots; after waiting for a denial writer,
the subsequent refresh/permission statements must see its committed effect. REPEATABLE READ/SERIALIZABLE
must not be described as that freshness guarantee or silently accepted; support would need a
separately reviewed retry/snapshot rule. Hold the row fence until the root's actual commit/rollback.

Current Catalog capture calls the fence before `_scope()` and official source authorization in
`inference_transfer_snapshot_catalog_adapter.py:capture_in_session`; registry verification calls
that existing capture seam. Preserve that order, required fence injection and existing current
`knowledge_graph:publish` registration guard. No fence/default means unavailable before writes.

The API's `get_authentication()` calls `AuthService.authenticate_access()`, which completes its own
authentication transaction before returning `AccessAuthentication`. This operator-row function
cannot prove that its session/token is still current later, especially after logout, expiry,
refresh reuse or a password change that retired tokens but left the operator ACTIVE and its password
flag clear. A saved operator ID/permission hash, old ActorContext or queued request is never a fresh
transport grant. Required live authentication/session/fresh-auth checks remain official owner
transport obligations; current operator permissions are additionally rechecked under this fence.
Absent an admitted fresh owner continuation, native commands remain unavailable before claim/commit.

Do not expand this first seam into a broad AuthService/token rewrite just to claim in-flight logout
cancellation. If a concrete owner operation requires current-session denial to linearize with its
metadata commit, it must separately own the exact authenticated session context (not a request DTO)
and review an official same-root freshness/cooperation boundary. Such a proposal must address
operator/session/token lock order—existing refresh locks a token before a session—before adding
operator locks after either. This ID-only function supplies neither that context nor that guarantee.
Natural expiry is also a UTC-time check, not an operator-row write blocked by a lock. No source
policy or background service principal is activated by successful invocation.

## Proposed migration and verification gates

Only after review, include this fixed routine/ACL lifecycle in the shared **post-0052 migration batch**
alongside the reviewed native stage/NULL-role step guard scope. This is a batch boundary, not a
reserved “0053” revision. Keep existing queue/command/Job schemas and released protocol bytes;
do not alter `CURRENT_MIGRATION`, create a speculative migration file or execute DDL in this task.
Existing protected release callbacks and exact privilege readiness are the owners of installation;
no source-only test or interface import is a production READY claim.

Prepared, opt-in independent-process tests must use the existing disposable testdb guard, explicit
Conda environments, manifest-pinned owner/runtime roles/database/schema and synthetic operators only:

- Limited Catalog role can execute the exact function and current supported permission queries,
  but cannot direct `SELECT FOR SHARE`, UPDATE/DELETE operators, read credentials/tokens/sessions,
  create/replace functions, grant roles or execute an unsafe overload. An ungranted role is denied.
- Owner/readiness fixtures assert exact signature/body/owner/options/ACLs. Missing/extra EXECUTE,
  PUBLIC grant, unsafe search path, writable schema, wrong owner or overload fails admission.
- Process A holds the fence through root commit/rollback; process B runs the real revoke-role,
  disable/delete, change-password, credential-update or synthetic-authorized recovery writer.
  Synchronize with bounded pipes/events/DB lock observations, not sleep-only timing. Writer cannot
  commit while A holds the shared row. Rollback releases it and leaves no metadata side effects.
- Reverse order: B takes the actual target `FOR UPDATE`, commits denial, then A's waited refresh
  sees revoked permission/disabled/deleted/required-password state and rejects before metadata
  mutation. Preload a stale OperatorRecord in A's identity map to prove refresh is effective.
- Password change leaving ACTIVE/password flag clear still orders on the row; separately require
  official transport rejection of the retired access session. Do not falsely expect ID-only fencing
  to identify a revoked token. Logout/expiry/refresh-reuse tests explicitly document the separate
  transport gate; no old-ID queued authority is manufactured to make them pass.
- Wrong isolation/autocommit/first-savepoint/read-only context, timeout, deadlock and lost transaction
  fail closed. A genuine private retained-root witness permits only fresh reauthorization inside the
  existing savepoint; concurrent readers can coexist. No long inference/GPU work holds a SQL fence.
- Guarded up/down/up verifies exact routine/ACL restoration and denied privileges; all fixtures are
  synthetic, no production DB/NAS/model/GPU/network operation or destructive role repair.

Downgrade requires the shared native-history downgrade guard and independently drained consumers:
refuse remaining dependent native history or active fence-dependent composition, rather than
rewriting/deleting it. Revoke the exact runtime EXECUTE grant, then drop only the owned exact
signature after checking expected owner/body/options; refuse drift/dependent objects, never use
CASCADE or drop unrelated functions/roles. Remove only migration-owned dedicated ACL changes when
ownership is unambiguous; shared preexisting schema USAGE is not blindly revoked. Preserve operator,
credential, role, session, Artifact and approved source history. A downgrade does not make unlocked
operation safe; the required concrete fence composition becomes unavailable again.

Later separately approved installation/composition edits belong to Catalog privilege readiness/
reconciliation and the reviewed shared migration/release owner. This source stage performs no
test DB execution, privilege/session/token/role-matrix change or runtime activation.

## Source-only implementation status

Identity owns new `postgres_operator_authorization_fence.py` and
`operator_authorization_fence_sql.py` under `services/identity_service/eom_identity_service/`, plus
additive package exports. The existing public Protocol and Identity/session/token/role behavior
remain unchanged. SQL CREATE/revoke/grant strings are immutable review material for the later owner
migration; importing or calling the inspection helper executes none of them. Inspection compares
raw function body server-side and returns at most two fixed-shape boolean rows, not untrusted body
or ACL payloads. It checks exact owner role/OID/schema/table ownership, ordinary/non-RLS operator
table, static argument/result/language/options, exact owner+dedicated Catalog ACL without grant
options/PUBLIC/overloads, supported role attributes/membership/schema CREATE and IAM table/column
privilege closure. Source/body hash pin is tested independently; no installed admission is claimed.

Unit paths are `tests/unit/test_operator_authorization_fence.py` and
`tests/unit/test_operator_authorization_fence_sql.py`. Prepared independent-process cases live in
`tests/integration/test_operator_authorization_fence.py`: real limited-role denials, retained root
lock through nested rollback against actual role revocation, writer-first actual disable/password
change with stale identity refresh and separate retired-session rejection, ACL drift and actual temp
shadow denial. They require the existing marker-guarded disposable DB plus a separately reviewed
prepared exact routine/limited-role profile; they install/grant/repair no prerequisite and never
touch the production fixed runtime role. Only the manifest's unique synthetic runtime role is
substituted in tests; every child rechecks actual DB/user/schema-owner/marker. The default API test
profile's IAM writes intentionally fail admission. Credential-bearing fixture fields are excluded
from repr/log output. Collection/source tests are not DB PASS, migration PASS or runtime READY.

Final source gates: 101 focused Identity unit cases and the nine-file Identity/Catalog/native
contract regression suite (367 tests) PASS. Ruff check/format and strict mypy with
`--follow-imports=silent` on the six owned Python files PASS. Six prepared integration cases collect
successfully but were not executed; installed routine syntax/privileges/real contention are still
pending guarded DB verification and the separately reviewed post-0052 migration/release gate.
All commands used explicit API/core Conda environments and explicit source paths. No Git, live or
disposable DB, migration/DDL, model/GPU, network, role grant, session behavior or runtime operation
was performed. Initial regression collections used incomplete source paths and encountered
the older installed Catalog package; the final gate above uses the complete source closure.
