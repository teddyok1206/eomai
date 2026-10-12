# Disposable limited operator-fence test profile — proposal

2026-10-12 UTC. **DESIGN_ONLY / NOT_PREPARED / DB_TESTS_NOT_RUN**.
This note reads existing source only. No database connection, DDL, grant, secret read, Identity
change, migration, Git or production operation was performed. Frozen Identity seven files,
their six prepared integration cases and the native-launcher proposal remain unchanged.

## Eleven-item boundary

1. **Responsibility/boundary.** Add one explicit disposable-test preparation/run leaf for the
   existing six operator-fence integration cases. It narrows the unique API test runtime's IAM
   privileges and installs the exact admitted Identity-owned routine **only in that disposable
   database**. It grants no production/source/native/background authority and is not a new DB
   profile registry, migration, bootstrap framework or permanent runtime-role policy.
2. **Canonical source.** Reuse `scripts/api/testdb_guard.py`'s exact four-field manifest, generated
   database/owner/runtime names and `EOM_API_DISPOSABLE_TEST_DB:<test_id>` marker. Reuse existing
   disposable owner/runtime environment files, migrations and public Identity fixed SQL constants.
   Do not copy credentials into a new environment, invent a production-role substitute, rewrite
   the role matrix, or seed fake permissions to make a race test pass.
3. **Identity/revision.** Database name, owner/runtime role names and OIDs, test ID, marker, current
   migration revision, fixed routine signature/body SHA and preparation profile are distinct.
   One fixed acknowledgement, `OPERATOR_FENCE_LIMITED_TEMP/1.0:<exact_test_id>`, identifies this
   intended mutation; it is not operator authentication or a reusable grant. No mutable latest
   profile, production role selector or test-ID substring match is accepted.
4. **Pointers/checks.** Before connection and every write, recheck the current acknowledged
   manifest bytes/held FD/named epochs and exact private state. Before every DB mutation, check
   actual connected database/current user, database/schema owner+marker, both role markers/OIDs,
   expected migration and unchanged role attributes/membership. Bound URLs to loopback5432 and
   exact manifest identities; no query/options/socket/alternate host or secret-file fallback.
5. **Access patterns.** Exact manifest/profile lookup, one bounded metadata preflight, one ordered
   small ACL/routine transaction, read-only verification and six independent-process tests.
   Existing Job/event/Orchestrator grants are preserved rather than recomputed by another grant
   manager. No corpus, Item, NAS, artifact binary, model, GPU or production data is read.
6. **Structures/indexes.** Fixed tuples for the nine IAM tables and five permitted reads; sets/maps
   for exact columns/ACL targets, role identities and bounded metadata uniqueness. Reuse the guard
   model and PostgreSQL catalogs. One private per-state operation lock and one small no-clobber
   receipt suffice; no schema/table/index/queue or global mutable profile collection.
7. **Scale/cost.** Manifest/environment reads bounded to4KiB each, receipt≤2KiB; metadata queries
   are bounded and set-based. IAM changes are O(total columns in nine fixed tables); preserving
   other grants is O(bounded app/public object ACL metadata), not one SQL request per column.
   No data-table scans or large JSON/secret-bearing logs. Unsupported metadata scale fails closed.
8. **Transaction/concurrency.** Require a fresh READ COMMITTED owner transaction and exclusive
   per-state setup/run phase, no active other test runner. All IAM/schema/function/TEMP mutations
   use that one disposable owner connection/transaction, with bounded trusted waits. Role/global
   attributes are already prepared by the existing API bootstrap and only validated, not repaired.
   Recheck file/DB guard immediately before each write and commit; no inference occurs.
9. **Dependency/ownership.** The purpose-specific script uses explicit `eom-api` Python, existing
   psycopg/SQLAlchemy and public guard/Identity constants. No new dependency or private cross-service
   import. The new phase can run as `eom` with the **disposable owner URL**, since that role owns
   the database/app and has the required public-schema ownership privilege; it needs neither root
   nor administrator secrets. If that precondition fails, reject; do not escalate/grant it.
10. **Failure/retry/idempotency.** Wrong ACK, marker/owner/OID/schema/migration/file drift, unsafe URL,
    unexpected routine/body/ACL/overload, inherited privileges or other runner stops before mutation.
    Failure before commit rolls back this transaction. After commit/receipt failure preserve phase
    evidence; inspect exact profile for same-key recovery, not broad repair or API reconciliation.
    Existing exact prepared receipt may replay read-only; conflicting/partial state is explicit.
11. **Simpler alternative.** Running the six cases against default API privileges is deliberately
    invalid: that profile writes IAM and cannot demonstrate Catalog's SELECT-only fence. A fake
    adapter/administrator runtime would evade the boundary. Narrow one unique disposable role
    after normal bootstrap; preserve all non-IAM grants and use existing full-database cleanup.

## Actual source facts and the test-only TEMP distinction

`testdb_prepare.sh` creates unique database/owner identities and exact comments, migration owner
search path `app, public`; `testdb_run.sh migrate` verifies migration head and up/down/up before
`testdb_prepare.sh --reconcile` creates/reconciles the unique runtime. Existing bootstrap makes
that runtime LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOINHERIT/NOREPLICATION/NOBYPASSRLS,
removes role memberships, sets `app, pg_catalog`, grants CONNECT and exact API table/column grants,
and revokes TEMP from PUBLIC. Its IAM write/read grants are correct for API, not this fence profile.

The frozen fence inspector requires exactly five readable IAM metadata tables and no table or
column writes; no reads of credentials/sessions/tokens/events. Its routine must be owned by the
manifest's actual app/operator-table owner; raw `prosrc`, signature, options, ACL and schema/runtime
privileges are exact. The existing production execute-role literal stays `eom_catalog_manager_runtime`.
Only the prepared tests substitute the manifest's unique runtime literal in their test processes.

One of the six cases creates `TEMP TABLE operators` as that unique runtime, then verifies the
adapter rejects `pg_my_temp_schema()!=0` without reading/deleting shadow content. Default bootstrap
denies TEMP, so preparation must grant **TEMPORARY only to the exact unique disposable runtime**.
This is an explicit synthetic negative-test prerequisite, not a requirement/grant for production
Catalog or native workers. Do not grant PUBLIC TEMP, schema CREATE or a temp-shadow bypass.
Root approved including this test-only TEMP distinction; it changes none of the frozen test bytes.

## Exact proposed preparation sequence

1. Use a **fresh** already migrated/reconciled ordinary disposable state from the existing guarded
   scripts. Before profile mutation, prove its actual IAM write privileges and reject fence
   admission. If the routine is also absent, do not attribute the generic rejection solely to
   IAM privileges; exact IAM verification remains separately decisive. Record the negative
   outcome, not an installation PASS. Existing API
   test runs and this profile must not share a concurrent/reconciled runtime phase.
2. Add an early closed `testdb_run.sh` branch for `operator-fence-prepare` with required fixed
   profile ACK and exact test ID. Delegate to one purpose-specific Python leaf **before** the old
   shell sources owner.env. The leaf opens the state, manifest, owner.env and runtime.env no-follow,
   held/named FD epochs, eom:eom0700/0600, regular/nlink1, bounded ASCII and exact key sets. Parse
   environment values as data, never shell source/eval; keep URLs/keys/passwords out of output.
   Canonical manifest bytes must equal `manifest.to_json()`; preserve the existing manifest format.
3. Require eom UID and explicit isolated interpreter; validate owner/runtime URLs' driver, user,
   loopback host/port/database/password presence and absence of URL query/options. Acquire one
   private held per-state operation lock; do not unlink/overwrite another or stale receipt. No
   default credential lookup and no read of `/etc/eom/secrets/postgres.env` is permitted.
4. Open as manifest.owner_role. Validate actual current database/user, database/role comments,
   app owner/comment, owner search path `app, public`, current migration, nine ordinary IAM tables
   owned by that owner and non-RLS `operators`, exact existing runtime role attributes/OID/no
   memberships/search-path configuration, and effective owner privilege to create the exact public
   function. If public/app has untrusted CREATE, fail; do not broaden/reconcile schemas. Owner
   and runtime must be distinct unique test identities, never a production fixed role.
5. Snapshot bounded non-IAM effective table/column/sequence/function privileges under app/public,
   excluding only the new fixed routine. Preserve those exactly, including necessary Orchestrator
   Job/event/Artifact/command grants. Bind the current manifest raw SHA/owner/runtime OIDs/marker/
   migration/profile ACK to the operation; validate again immediately before each SQL write.
6. In the same owner transaction, revoke **all table privileges and SELECT/INSERT/UPDATE/REFERENCES
   column privileges only** on these nine exact app tables from the unique runtime:
   `operators`, `roles`, `permissions`, `role_permissions`, `operator_role_assignments`,
   `operator_credentials`, `api_sessions`, `api_tokens`, `operator_events`. Restore SELECT only
   on the first five. Effective PUBLIC/inherited privilege leakage must fail final verification;
   do not remove unrelated principals' grants or blanket-revoke every app table/function.
7. Grant only USAGE on `app` and `public` to that runtime, retaining no CREATE. Existing baseline
   CONNECT remains; grant its exact database TEMPORARY for the synthetic shadow case. Do not
   alter LOGIN/password/role memberships/search path or add a new role. If their validated
   baseline drifted, stop rather than running the ordinary broad API bootstrap again.
8. Require the fixed routine name absent on first preparation; reject unexpected existing body,
   overload or owner. Execute public `OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL` **as the disposable
   owner**, followed immediately in this same transaction by its exact REVOKE PUBLIC constant.
   Grant EXECUTE to the manifest runtime using `psycopg.sql.Identifier`, never string replacement
   of the production role literal. No CREATE OR REPLACE, ALTER OWNER, dynamic body or alternate
   signature; creation and grantor must both be the exact owner so the ACL's two grantees/grantor
   match the admitted rule. Do not execute the exported production GRANT literal in a test DB.
9. Before commit, verify exact raw body/signature/options/owner/ACL, USAGE/no CREATE, runtime
   attributes/no membership, IAM5 read-only/IAM4 no-read and no table/column write, runtime-only
   test TEMP and unchanged non-IAM grant fingerprint. Public/table/role leakage fails and rolls
   back. The public existing integration inspector remains the authoritative adapter check in
   each prepared fixture, with its existing test-only role substitution; this leaf introduces
   no production adapter role-selector or private inspector import.
10. Revalidate the current acknowledged file/DB identities and commit. Write one O_EXCL/fsynced
    private sanitized preparation receipt (fixed profile/test ID/manifest raw SHA/migration/body
    SHA/owner+runtime OIDs/phase), no URL/key/password/SQL body. A receipt is evidence, not grant.
    Receipt failure after DB commit leaves PREPARED_WITHOUT_RECEIPT/UNCERTAIN; retain it for guarded
    read-only inspection or full cleanup, never silently overwrite/reapply profile mutations.

No table data, operator status/roles/credentials/session or historical event is repaired by this
profile leaf. The existing six fixtures create bounded synthetic identities and use actual official
Identity services for revoke/disable/password races under the disposable owner, not runtime IAM
write permission. Public SQL constants are immutable source pins; a source/helper receipt does
not admit production DDL or a new native purpose.

## Run, replay, rollback and cleanup

Proposed closed CLI, run as `eom` (examples are not executed here):

```text
scripts/api/testdb_run.sh operator-fence-prepare <exact_state> OPERATOR_FENCE_LIMITED_TEMP/1.0:<exact_test_id>
scripts/api/testdb_run.sh operator-fence-tests <exact_state> OPERATOR_FENCE_LIMITED_TEMP/1.0:<exact_test_id>
```

Proposed `operator-fence-tests` action requires the same fixed ACK/test ID, exact current manifest,
private receipt and actual profile. Recheck the connected guard/profile before invoking pytest;
run only `tests/integration/test_operator_authorization_fence.py` with explicit API Python and
source paths, `EOM_RUN_INTEGRATION=1`, `EOM_RUN_API_INTEGRATION=1`,
`EOM_RUN_OPERATOR_FENCE_INTEGRATION=1`, and the exact disposable `EOM_API_TEST_STATE`/owner URL.
Each frozen child already rechecks database/user/schema owner/marker and substitutes only that
manifest runtime; the prepared fixture independently rejects invalid installed security. No
default API test action is repurposed, and no production/static adapter constant is edited.

The six collected cases are limited routine execution/direct IAM denial, root-lock retention across
savepoint rollback versus actual role revoke, writer-first disable, writer-first password change
with separate retired-session rejection, ACL drift despite retained witness, and actual temp shadow
denial. Processes/locks/events have existing bounded waits and final disposal. A failed/uncertain
child must terminate/join through its existing test lifecycle before cleanup, not be hidden by
changing privilege checks or deleting test rows. Actual six-case PASS can only be reported after
the guarded run; collection and source tests are not DB evidence.

Before commit failure: roll back all narrow ACL/function/TEMP changes; preserve failure evidence.
After commit: do **not** automatically restore API IAM writes, DROP/RECREATE routine, rerun
`--reconcile`, loosen schema policy or reuse another profile key. Read-only exact replay is allowed
only when receipt/current identity/profile all match; otherwise explicit failure/full cleanup.
Use a new disposable state for ordinary API tests. Production migration/downgrade rules remain
owned by the separate reviewed post0052 batch, not this preparation operation.

Cleanup remains the existing root-only `scripts/api/testdb_cleanup.sh --confirm <exact_state>`:
it revalidates exact manifest/database/owner/runtime comments, terminates only that marked DB's
connections, drops that unique database and two unique roles, then removes its validated private
state. No new broad cleanup helper, schema-wide rollback, production role/data deletion or password
rotation. Guard failure stops cleanup. The test-only routine/ACL/TEMP/synthetic histories disappear
with the explicitly disposable DB; no production object needs restoration.

## Minimal next owned paths and pre-behavior gates

| Purpose | Proposed path/change |
| --- | --- |
| One guarded preparation/run leaf | New `scripts/api/testdb_operator_fence.py`; fixed profile/ACK, public guard/Identity SQL constants, safe file/URL admission, narrow owner transaction, receipt and read-only replay |
| Existing test execution owner | Add explicit early `operator-fence-prepare`/`operator-fence-tests` branches to `scripts/api/testdb_run.sh`; preserve all old two-argument actions and defaults, no shell source for new purpose |
| Focused synthetic source gates | New `tests/unit/test_operator_fence_testdb_profile.py`; malformed/production/cross-manifest ACK/URL, file/mode/owner/link/epoch drift, missing marker/OID/migration, unsafe role/schema/body/ACL, per-write recheck, rollback/receipt failure/concurrent setup, exact limited statements/no broad grants and preserved non-IAM profile |
| Historical regression | Existing `tests/api/test_runtime_role_reconciliation.py`, `tests/unit/test_general_chat_role_preparation_cli.py`, Identity source suites; old prepare/bootstrap/cleanup/default CLI paths unchanged |
| Real opt-in gate | Existing six frozen `tests/integration/test_operator_authorization_fence.py` cases through the new guarded action, fresh disposable state only; no fixture prerequisite repair |

Do not edit `testdb_guard.py`, production bootstrap/grants, frozen Identity files/tests, CURRENT_MIGRATION,
existing role matrix, launcher/runtime/source snapshot or WIP for this proposal. Source implementation
requires root review of this exact setup/ACK/transaction/run/cleanup sequence first. No new behavior
or source test was executed by this design-only note.

## Approved source-only implementation checkpoint

Root reviewed the 200-line proposal before behavior. The implementation owns only
`scripts/api/testdb_operator_fence.py`, the additive early branches in `testdb_run.sh`,
`tests/unit/test_operator_fence_testdb_profile.py` and this checkpoint. Frozen Identity seven
files, production bootstrap, guard/model/migration/role matrix, native launcher and root WIP remain
unchanged. Root separately owns the single existing API usage-test whitelist addition.

The helper is eom/disposable-owner-only and never reads administrator secrets. It retains actual
state/manifest/environment FDs, their metadata epochs and raw hashes. Fresh per-write guards pin
database/schema/role and all nine IAM table OIDs; source statements use the public exact routine
CREATE/REVOKE and only the manifest runtime EXECUTE/TEMP target. Non-IAM privilege preservation
includes PostgreSQL18 MAINTAIN; the current EOM PostgreSQL18 profile is the target, not a new generic
database portability layer. No existing Artifact/Job data is changed or read by preparation.

Started/receipt files are O_EXCL and sanitized; no URL/key/password/body is recorded. A transaction
failure preserves STARTED, commit uncertainty creates no success receipt, and post-commit receipt
failure is PREPARED_WITHOUT_RECEIPT. Replay verifies actual current security plus exact raw input/
OID/non-IAM receipts and performs no privilege/routine repair. The one per-state mutex remains held
through verification and the fixed test run. A90s owned-connection cancellation bounds the initial
catalog reads as well as later work, with existing stricter positive owner GUC limits preserved.
The180s test runner uses its own private process session and kills only that owned/unreaped group
on timeout/exception; it does not signal a database-reported PID or arbitrary process group.

One full existing shell SOURCE_PATHS construction now precedes both early and legacy branches;
no incomplete source7/old installed-contract substitute is used by the early helper import. An
actual unprivileged invalid-environment CLI fixture verifies this import closure and rejects shell
injection **before DB access**. Root additionally approved the ordinary two-argument
`embedding-encoding-tests <exact_state>` action, using the old guard/owner/source paths and only
`tests/integration/test_embedding_encoding_reservations.py` with explicit integration flags. It is
not a limited-profile preparation action and requires no profile ACK or new grants.

Source gate: **222 PASS**, including89 new synthetic profile/harness cases,101 frozen Identity
cases,29 API role/CLI regressions and3 chat preparation regressions. SQL positives use an inert
fixture; only synthetic private files and independent-process flock contention were exercised.
Ruff lint/format2 PASS, explicit core strict mypy2 PASS and bash syntax PASS. The authoritative
same-gate test list is:

```text
tests/unit/test_operator_fence_testdb_profile.py
tests/unit/test_operator_authorization_fence.py
tests/unit/test_operator_authorization_fence_sql.py
tests/api/test_runtime_role_reconciliation.py
tests/unit/test_general_chat_role_preparation_cli.py
```

Run pytest with explicit `/srv/eom/conda/envs/eom-api/bin/python` and current repository/source
roots; strict checker is `/srv/eom/conda/envs/eom-core/bin/python -m mypy --strict
--follow-imports=silent --explicit-package-bases` on the new helper/test. The last option resolves
the existing scripts namespace once; without it mypy reports the same file under two module names.
No blanket ignores or new stubs/dependencies were introduced.

No agent DB/root/DDL/secret/Git/model/GPU operation was performed. These gates are not the actual
eight encoding-reservation or six operator-fence DB cases; root owns their fresh guarded execution
and full cleanup separately. Source readiness does not imply production routine/privilege/native
purpose, benchmark or default-device activation.
