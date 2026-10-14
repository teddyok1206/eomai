# Local indexing policy publication checkpoint

2026-10-14 UTC. This closes one source/control boundary of the
[full incremental RAG goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md),
not that goal or production activation. Durable decisions remain in the
[service authority design](../architecture/LOCAL_INDEXING_SERVICE_AUTHORITY_DESIGN.md).

## What is implemented

`publish_local_indexing_access_policy` is a supported **in-process Catalog owner
control operation**. It publishes the existing closed service-only policy1.1 into
the existing policy-revision table. It installs nothing and grants no runtime role.

- Actual authenticated DB principal must own both the policy table and `app`
  schema. Root is explicit, writable READ COMMITTED, with the existing native
  connection namespace `app,pg_catalog`, no temp schema, no initial savepoint and
  no pending ORM mutations. Ordinary `app/public` connections are rejected.
- The public Identity owner API locks/resolves the exact ACTIVE service revision.
  Source policy1.0 and ACTIVE corpus/logical Graph are resolved/locked before the
  insertion savepoint. Publication and runtime share one pure source-policy
  compatibility rule; there is no fake user role/permission list.
- Revision PK + semantic SHA supply idempotency. PostgreSQL arbitrates all unique
  conflicts, then the operation revalidates exact revision, schema, hash and bytes.
  Another revision's SHA collision is an explicit conflict, not a successful replay.
- One insert/savepoint, no UPDATE/repair/deletion/new queue. The caller owns the
  root commit. Result reports revision/hash, created/replayed observation and the
  actual publication principal/time; it is not service authentication or a grant.
- Waits are bounded5s/10s and smaller caller limits are preserved. Cleanup checks
  the captured psycopg transaction status and does not mask an aborted root with
  another SET. Timeout requires rollback and same-revision replay.

No new table/migration/dependency/credential or worker permission is introduced.
Only bounded small policy metadata is stored; no Item/report/vector bytes are added.
The source migration head remains0055. No production DB, service or model is changed
by this checkpoint.

## Executed evidence

Focused publication/compatibility/source gates:85 PASS. Final full source regression:
84 suites /2,283 PASS in289.61s. Strict mypy47 modules and Ruff lint/format86 files
PASS. Source/installed-candidate evidence is not substituted for actual activation.

Guarded disposable PostgreSQL: **70 distinct cases PASS** in the final owner review:
prior registry29 + SQL fence13 + policy reads9, and new publication19. The19 cover
actual owner publication/audit/replay, same-revision content conflict,6 independent
two-root publication races with no DB error, disabled service, missing/stale source
policy and corpus, Graph mismatch, parent restrictions, smaller wait limits, unsafe
initial savepoint/default namespace, actual writer-lock timeout/replay and unrelated
PK/hash conflict. Synthetic committed control history is retained; deliberate bad
row fixtures are rolled back. No production Catalog runtime, machine unit, source
file, numerical model or GPU admission is claimed by these owner tests.

Postcheck: correct disposable marker/owner, head0055,0 other connections and an
actual read-only inspection transaction. Evidence directory:
`/tmp/eom-identity-provider-install.nAaycoDM/`.

- `local-indexing-policy-publication-focused.log`
- `local-indexing-policy-publication-postgres-owner-reviewed.log`
- `local-indexing-policy-publication-final-{mypy,ruff,format,inspect}.log`
- `local-indexing-policy-publication-final-regression.log`

Installed-candidate boundary: source `70a53c50ac818d8f2598f9383269fd61e46b7c3e`
build-only produced the three release wheels with RECORD verification PASS. The
immutable operator interpreter imported41 modules directly from those wheels under
`-I -B`, without checkout/PYTHONPATH or environment installation. Packaged schema
hash/local-reference closure, owner publication exports, shared source-policy
compatibility, and no implicit root/autobegin PASS. This ran no database, runtime
grant, unit, model or GPU operation. Evidence:

- `local-indexing-policy-publication-wheel-build.log`
- `local-indexing-policy-publication-wheel-import.log`

Preserved development failures:

- `local-indexing-policy-publication-postgres.log`: prior51 PASS, then10 default
  namespace fixture failures/1 PASS. The fixture now uses the existing supported
  native engine; the production guard was not broadened.
- `local-indexing-policy-publication-postgres-reviewed.log`: one concurrent exact
  publication returned CONFLICT. The following diagnostic run passed12 cases, so
  that single PASS was not accepted as proof of race absence. PK-only conflict
  handling was replaced by all-unique arbitration plus exact-PK/bytes validation;
  6 repeated races and the non-PK conflict negative then pass in the final19.

## Remaining boundaries

Policy control publication is now implemented/tested, **not performed in production**.
Actual service configuration/unit/least-privilege DB admission, Registry/Runner
service-purpose composition and supported missing-binding reconciliation remain.
Original operator1.0 and request1.1 semantics remain unchanged; service audit alone
still cannot start a native workflow. New meaning needs tested successor controls,
not a broadened old operator policy.

The full goal still requires genuine bounded seed/source-add delta/same-key replay/
QUERY, consumer integration in the original order, CPU/GPU measurement and the
conditional superior-device default. Historical520 experiments, source tests and
synthetic owner metadata do not complete these requirements.
