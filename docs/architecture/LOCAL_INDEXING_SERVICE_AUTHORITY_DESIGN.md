# Local indexing service authority

2026-10-14 UTC. Required continuation of
[the full incremental design](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md)
and [registry authority boundary](INCREMENTAL_EMBEDDING_REGISTRY_DESIGN.md#8-operator-audit-is-not-background-service-authority).
This is a purpose-specific implementation boundary, not a service grant or activation.

## Decisions before persistence / cross-owner changes

1. **Responsibility.** Identity owns service identity/revisions/current activation and
   revocation. Catalog owns the released indexing data grant and the existing official
   Graph/source/report resolver. Runner/Orchestrator own existing commands, claims,
   numerical execution and Artifact publication. Workers own none of these authorities.
2. **Canonical source.** Small immutable identity metadata is canonical in Identity,
   with one mutable current head and append-only audit. Source/report/Graph/Artifact
   pointers and Catalog policy revisions retain their existing canonical owners.
3. **Identity.** `localindexservice_…` is logical; `localindexservicerev_…` is immutable;
   content SHA is separate. Registration is not activation. Disabled heads may retain
   their old reference for history but cannot authorize an operation.
4. **Resolution.** Validate exact IDs, schema/hash, revision chain, current activation,
   installed trusted owner runtime and actual authenticated DB principal. A service
   ID/audit hash, ambient UID, generic SYSTEM actor, WORKER/ADMIN role or idle slot is
   insufficient. Operator sessions and machine identity remain different concepts.
5. **Access.** Indexed service/revision lookup, append-only successor/event sequence,
   concurrent activation/revocation and per-root exact-source reauthorization.
6. **Structures.** Minimal Identity head, immutable revision and audit-event relations;
   PK/composite FK/unique successor/event sequence and immutable-row guards. No generic
   IAM framework, copied user, token registry, new queue, broker or vector database.
7. **Scale.** A small number of installed local services, O(log R) indexed revision
   lookup, bounded small metadata and O(1) current-head lookup. No binary/prompt/report
   bodies in these relations. Existing corpus/binding indexes own corpus-scale work.
8. **Transaction.** Current service head is shared-locked for an operation root;
   supported activation/disable writers exclusively lock the same head and append
   audit in that transaction. Recheck exact references late. Numerical computation
   remains outside SQL roots. No historical request is rewritten to the latest grant.
9. **Dependencies.** IO-free identity contracts/state rules are below Identity adapters;
   Catalog consumes the public Identity fence and its own released data grant, never
   mutates Identity tables. Runner consumes public owner contracts, not private SQL.
10. **Failure/replay.** Missing/inactive/stale/mismatched identity, runtime or policy
    fails before discovery/reservation/launch/commit. Revoke stops new work/replay
    admission; uncertain original execution retains its identity/evidence. Registration
    repeats must match exact immutable bytes; activation uses expected head version.
11. **Simpler alternatives.** Reusing guiadmin expires and impersonates a user. A
    role-less policy bypass or treating a parser/UID as permission is not authority.
    Existing retrieval-policy rows are immutable RELEASED-only, so they are not a
    revocable service registry and must not be quietly given new lifecycle meanings.

## Protocol first and scope

Start with a closed `local-indexing-service/1.0` identity/reference/status family.
It contains no password, token, requested role or source permission. Validate JSON
Schema2020-12 before Pydantic behavior; preserve future WorkFlow1.1 service audit
field names. Service IDs require50/53 characters, not the old32-character protocol
registry key; do not truncate them or store them in the protocol-version table.

The first protocol work does not advance the deployed migration head. Persistence,
installed runtime provenance and current-principal fencing are subsequent required
owners, not implied by parsed metadata. No new dependency is needed.

The Catalog policy successor must explicitly grant `LOCAL_EMBEDDING_INDEX` to an
exact service revision/hash and bounded corpus/partition/source/population/model/
recipe/resource scope. It permits discovery, accepted-report reads and derived
embedding registration only, not Item/report approval, Graph publication, user
retrieval, arbitrary filesystem access or role impersonation. Role-based1.0 reads
keep their exact meaning. Service reads reuse the official resolver through a
separate checked scope; they do not pass a service ID through operator `_scope()`.

Unattended execution uses an installed trusted service/provider and current DB
principal, not a Studio session or copied auth. Actual role names/runtime provenance
must be inventoried before activation, not guessed from source. Revocation and
supported writers must be tested with real independent DB roots. Installed purpose,
CPU/GPU lease/resource and consumer grants remain independent gates.

`SERVICE_IDENTITY_AUTHORITY=NOT_ACTIVE`, `AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

## Implemented protocol boundary

The JSON Schema family and its identical packaged resource precede the IO-free
`eom_operator_identity.local_indexing_service` models. Identity metadata, exact
reference and current-head projection are separate frozen values. Every field is
required; versions reject booleans/coercion, timestamps require aware UTC, role
names reject whitespace and extra credentials/roles/source grants are forbidden.

The identity semantic hash excludes only `content_sha256` and normalizes UTC times
to six fractional digits using the existing canonical EOM serializer. Logical ID,
revision ID and hash are not interchangeable. Successors require the same logical
service, exact predecessor, incremented number and nondecreasing creation time.
An ACTIVE projection requires its exact current reference; disabled projections
may preserve the old reference without granting access. A head cannot predate the
identity revision it claims is current.

Serialization revalidates copied/constructed models, including nested references,
before any field can be dropped. Wire parsers accept only bounded canonical bytes
and reject duplicate JSON members, extra/missing fields and nonfinite values.
Pure current/successor validation does **not** produce an authenticated capture,
opaque capability, source grant or installed runtime approval. The existing
operator-seed guard continues rejecting service audits until the actual service
owner and Catalog grant are implemented and verified.

No DB migration, new permission, runtime identity, service activation or model
execution is part of this protocol-only change. Identity persistence/fencing,
Catalog's separate source grant and official missing-binding scheduling remain
required before unattended indexing can be enabled. Existing human policy1.0 and
frozen Workflow request1.1 retain their previous bytes and meanings.

### Source verification — 2026-10-14 UTC

- Combined70 source suites: **1,929 PASS** (276.13s), including identity transport,
  INDEX/QUERY admission and existing Artifact/native execution/consumer boundaries.
- Strict mypy30 source modules and Ruff lint/format50 Python files: PASS.
- Exact schema mirror SHA-256:
  `dc7de7cef0239b48096609c79f4f08c976e272640d89b42a33ff8634bb835807`.
- Protocol-only diff: no migration/DB mutation, service/role activation, model/GPU
  inference or change to the existing operator-seed service-audit rejection.
  Prior actual disposable PostgreSQL acceptance is not relabeled as service IAM proof.
- Code candidate `24336eaa64f4c9ce4285db5feb97430c05d3adb4`: all3 release
  wheels built and RECORD verification PASS. An existing immutable operator
  interpreter, isolated from source checkout and without package installation,
  imported the previous25 modules and the new public identity/contract modules
  from those wheels. Packaged schema SHA, all3 canonical wire shapes, inactive
  metadata/copied-model rejection and unchanged unoffered QUERY admission PASS.
  This is package verification, not an installed service/DB/runtime grant.

Protocol-only milestone before the persistence implementation below:

`SERVICE_IDENTITY_PERSISTENCE=NOT_IMPLEMENTED`,
`SERVICE_RUNTIME_AUTHENTICATION=NOT_IMPLEMENTED`,
`CATALOG_SERVICE_SOURCE_GRANT=NOT_IMPLEMENTED`,
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

## Identity-owned persistence implementation

The control-plane registry uses exactly3 relations. `local_indexing_services`
contains the logical ID, latest registered revision, independently selected current
revision, ACTIVE/DISABLED state, resource version and UTC timestamps. Registration
of a successor preserves the current activation. Explicit activation may select an
older exact registered revision for rollback; it never silently selects latest.

`local_indexing_service_revisions` stores the small typed identity fields directly,
not a second JSON document or Artifact payload. Unique `(service_id, revision_number)`
and `(service_id, previous_service_revision_id)` plus composite same-service FKs
protect the immutable chain and both head references. Deferred current/latest FKs
allow the first disabled head and revision to be registered in one transaction.

`local_indexing_service_events` is append-only, keyed by service and resource version,
with a unique bounded operation key, exact command hash, actual database principal,
target/previous/result revision pointers and previous/result states. It contains no
credentials or binary data. Same-key replay returns the original event's historical
result; callers must separately resolve/lock the current head. A conflicting key,
different immutable bytes or stale expected resource version fails, not repairs.

These in-process owner use cases require an explicit active PostgreSQL root and
the actual authenticated table-owner principal (`SESSION_USER = CURRENT_USER`),
not a requested administrator role. They qualify all3 tables in `app`, use an
indexed exclusive head lock for writers and a retained shared head lock for the
owner's metadata read. A savepoint makes one operation atomic without committing
the caller's root. Wait limits are bounded and existing smaller limits preserved.
No service/runtime write grants are installed. There is no new operator permission
or user-facing endpoint. The later least-privilege runtime fence must not use this
control-plane owner privilege as a substitute for machine authentication.

Migration0055 adds only these relations, indexes and history/head guards; no existing
rows or roles are changed. Downgrade refuses any service/head/revision/event history.
Application code owns canonical hash/successor validation and atomic event coupling;
DB constraints/immutable guards reinforce it. Unsupported table-owner SQL is not a
supported control interface. Catalog service-source grants and actual installed
runtime authentication remain separate required work.

### Persistence verification — 2026-10-14 UTC

- Source regression:72 suites, **1,940 PASS** (275.85s). The later lock-error cleanup
  correction passed its focused79-case source gate and the full29-case actual
  registry gate. Strict mypy35 modules, Ruff lint/format59 files, shell syntax and
  diff checks PASS. No new dependency: PostgreSQL transaction-state inspection
  reuses the already declared psycopg driver.
- In the existing marker-guarded disposable DB,0054→0055→0054→0055 migration cycle
  PASS before service history was created. Existing Workflow/Artifact history was
  preserved. After history existed, the actual downgrade refusal was verified;
  rows were not deleted to make a positive empty-history test pass.
- Actual PostgreSQL registry: **29 PASS** (1.20s). Registration stays disabled;
  successor registration preserves the selected current revision; explicit rollback
  works. Same-key replay returns the original historical state without reactivation.
  Global key conflicts and late event failures leave no orphan head/revision even
  when the caller commits its root. Independent roots verify same-key deduplication,
  competing expected-version updates, nonforking successors, retained shared locks,
  supported disable, lock timeout/replay and immutable records. Composite FKs,
  head/version/NULL guards, UTC conversion, smaller caller wait limits and actual
  database-principal audit were checked. The existing disposable runtime role
  gained no privileges on the3 new tables.
- A real PostgreSQL lock timeout reproduced an initial cleanup defect: checking
  only `Session.is_active` issued a second SET in an aborted root and masked55P03
  with25P02. Cleanup now inspects the captured driver's actual transaction status,
  never reconnects a lost connection, and preserves the original cause under
  `LOCAL_INDEXING_SERVICE_BUSY`. Root read failures require rollback; writer
  savepoint failures preserve the outer root. There is no automatic retry/new key.
- Existing native stage/runner/QUERY53 (33.63s), Artifact/registry/application28
  (77.39s), encoding reservation9 (12.29s): **90 PASS** on0055. Together with the
  new29,119 distinct actual DB cases passed; repeat runs are not added to the count.
  The old90 retain their synthetic IAM/numerical seams. The new29 prove actual
  owner metadata/locks, **not** an authenticated background runtime or source grant.
- Final disposable inspection: correct marker/owner, head0055, other connections0,
  read-only server transaction confirmed. Synthetic committed evidence is retained.
  Production migration, service installation/permissions and numerical runtime
  were not changed. API ready and all9 relevant services remained active.

Current boundary:
`SERVICE_IDENTITY_PERSISTENCE=SOURCE_PASS_AND_DISPOSABLE_DB_PASS`,
`CONTROL_METADATA_LOCKING=DISPOSABLE_DB_PASS`,
`SERVICE_RUNTIME_AUTHENTICATION=NOT_IMPLEMENTED`,
`CATALOG_SERVICE_SOURCE_GRANT=NOT_IMPLEMENTED`,
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

Next is the separately admitted least-privilege runtime fence and Catalog indexing
source grant. The owner-only metadata lock must not be called a machine-authentication
capability or be exposed as runtime owner privilege. Source head0055 does not imply
that production has been migrated; installed release alignment remains required.

### Release admission successor

The first7bf24aea package attempt correctly stopped at the existing0054 admission
guard. Add JSON Schema `release-operator-context/1.4` and its admission receipt for
exact0055, using the existing protected operator boundary and immutable source/
archive/wheel/runtime pins. The new fixed VERIFY/UPGRADE0055 callbacks accept
only0055 itself or, for an upgrade, exact0054. They do not skip the production0053
predecessor; a separately pinned0054 release must perform that earlier step.
Old context1.0–1.3 schema bytes, callback targets, owner checks and the historical
0051 migration wrapper retain their meanings. No generic `head` callback or role
override is added. The build's installed-head gate advances only with the tested
new admission family. Failed build evidence is preserved. This source change is
not an installed/admitted root operator, production migration or service data grant.

The new1.4 family and existing1.0–1.3 regressions passed in the final73-suite
**1,958 PASS** gate (276.70s), with strict type36 modules and lint/format65 files.
The actual DB119-case proof above is unchanged. Callback tests use explicitly
synthetic protected-runtime/owner-DB seams; they are not root installation proof.
The exact schema raw SHA is
`af03ddeccb0cab48f60341121c987e05733e18aba1986c06408d835953eacb79`.

Code candidate `284d9a8ce6aabcec4680e1e404ed4a79dd0d3817` passed all3 wheel
builds/RECORD and the installed package simulation with the exact0055 admission
gate. An immutable operator interpreter imported the25 existing named modules
and5 identity/registry modules from wheels only. Pointer widths, deferred same-
service FKs, schema SHA/canonical values and rejection of an implicit owner root
were verified without a DB connection or installation. QUERY remains globally
unoffered. This package proof does not activate the new root context, service
authentication, Catalog grant or automatic reconciliation. The initial failed
7bf24aea build and lock-error reproduction logs were retained separately.

## Actual runtime admission boundary

Use one fixed, root-managed `eom-embedding-index-owner.service` under the existing
infrastructure user `eom-workflow-runner`, with the existing restricted Catalog DB
role. This is not a Codex/numerical worker and consumes no Codex slot. Ordinary
systemd EnvironmentFile loading supplies the existing Catalog credential; it is
not put into a new config, argv, worker input or user-session store. No new IAM,
credential registry, broker, queue or generic daemon framework is introduced.

Before Identity can admit a service operation, verify the **actual current process**
against the root-owned unit: MainPID, user, invocation, cgroup, fixed entrypoint,
isolated interpreter and immutable installed owner release. A root-owned small
runtime config binds the exact service reference, source commit and raw wheel,
interpreter and unit hashes. A separately released Catalog grant pins that config's
raw SHA; parsing or supplying these values alone never authenticates a caller.
The unit does not contain the config SHA, avoiding a config/unit hash cycle.

Owner release files must match the retained root-published platform/API-contract
wheels. Capture and recheck file epochs, namespace closure, actual unit/process
identity and boot lifetime. Files newer than process startup are not accepted as
proof of already-loaded code. No source checkout/Git, arbitrary unit/path/role or
model-supplied observation is admitted. Ambient UID alone is explicitly insufficient.
Code/root-config replacement or restart invalidates the old capture; supported
restart captures the newly installed instance. Current DB head/policy/source checks
and numerical CPU/GPU admission remain separate and are repeated per SQL root.

Identity's later narrow SECURITY DEFINER routine retains the same shared head lock
used by supported control writers and returns only bounded typed metadata. Catalog
receives no Identity table writes. Its actual authenticated DB principal and the
non-transferable current runtime capture must both match the registered identity;
a metadata DTO or generic SYSTEM/ADMIN actor is not a substitute. Runtime config
schema precedes the observation behavior. This remains uninstalled until the
compatible release/privileged acceptance gates pass; no deployment is inferred.

The narrow DB interface is `public.eom_fence_local_indexing_service_v1(text,text,text,text)`.
Only the actual `eom_catalog_manager_runtime` login, without `SET ROLE`, may invoke
it. It takes exact service/revision/identity-hash/source pins, locks the one indexed
head `FOR SHARE`, and returns only the existing closed identity/status metadata.
Disabled, stale or different-principal identities fail; it does not return a data
grant. Both metadata documents are revalidated, including their semantic hash.
The caller must retain its explicit READ COMMITTED root, and may not acquire this
lock first inside a savepoint. Waits are bounded; failure requires root rollback,
not implicit retry. A root-local witness may only be reused by the same Session,
connection, transaction and thread, with a fresh current runtime recheck.

Installing the exact function/ACL is a separately admitted owner operation, not
an import side effect or Catalog self-grant. Before each use inspect exact function
signature, body, definer, fixed search path, ACL, table/schema owners and the
runtime's absence of Identity table privileges. The existing metadata tables do
not change, and no extra registry/table/credential is introduced by this interface.

### Runtime and DB fence implementation checkpoint — 2026-10-14

The closed non-secret `local-indexing-runtime/1.0` schema/resource and strict frozen
model are implemented. They bind an exact service reference/source and raw wheel,
interpreter and unit hashes, not credentials or permissions. Canonical bounded
parsing rejects duplicate keys, nonfinite/extra data and forged copied models.
The mirrored schema raw SHA is
`db53688fbf73d082cab552b696c59788aa0fbc7d404077f3610b91b81ef2756f`.

The Identity infrastructure observer checks the actual current unit/process,
isolated interpreter, immutable root files and retained wheel namespace closure.
Its same-process capture rejects serialization and rechecks unit/boot/file epochs
at use time. Ordinary developer execution is rejected before protected config IO.
The SQL fence binds that capture to the actual authenticated DB principal, exact
active Identity revision and retained root lock; it never returns a Catalog data
grant or substitutes an operator role. First acquisition inside a savepoint,
implicit/autocommit/wrong-role roots and cross-thread/root reuse fail explicitly.

Validation so far:

- New focused source tests:146 PASS. OS/unit/runtime and SQL responses are explicitly
  synthetic seams; actual temporary file/hash/descriptor checks run, but this is
  **not** root/systemd/Catalog authentication acceptance.
- The official guarded disposable PostgreSQL purpose:42 PASS, comprising existing
  Identity metadata29 and new exact SQL semantics13. New routine DDL/ACL exists
  only in rolled-back roots; committed synthetic registry history is retained.
  Exact pin/NULL/stale/SET ROLE/actual-principal mismatch denials and a shared-lock
  timeout/replay with the supported control writer are exercised in PostgreSQL.
- These13 SQL tests use the actual disposable **owner**, with that identity
  registered accordingly. They do not impersonate or prove the production Catalog
  login, least-privilege installed fence, root runtime capture or data scope.
- The initial PostgreSQL run had one test-invocation syntax failure
  (`SET LOCAL ROLE CURRENT_USER`); the fixture now uses the supported bound server
  setting.40 PASS/1 failure remains in its original log;42 PASS is the reviewed run.

No new service/entrypoint/config/routine/data grant is installed by these changes.
Source migration head remains0055 and no production migration/role change occurs.
Required next boundaries remain the executable service composition, actual narrow
DB installation/admission, successor Catalog service data grant/official source
resolution, then genuine bounded seed/delta/replay/QUERY and CPU/GPU comparison.
The full incremental-embedding goal is not complete.

Final source gate for this checkpoint:77 focused suites /2,104 PASS in277.12s;
strict mypy40 modules and Ruff lint/format74 Python files PASS. The SQL body is
frozen with raw SHA
`eba4706dc13f62c8546fd4d1dc7390179057d944da475720eefae2b6cd885c85`.
Shell syntax and `git diff --check` PASS. The guarded read-only postcheck confirms
disposable identity, head0055 and0 other connections. Logs are retained under
`/tmp/eom-identity-provider-install.nAaycoDM/`:

- `local-indexing-service-auth-regression.log`
- `local-indexing-service-auth-{mypy,ruff,format}.log`
- `local-indexing-service-auth-postgres-reviewed.log`
- `local-indexing-service-auth-inspect.log`

Initial runtime-fixture failures remain in
`local-indexing-runtime-focused.log`: its test-owned directories inherited group
write from the developer umask. The fixture now sets nonwritable modes; production
ownership/write-bit checks were not weakened. No actual runtime grant was tested
by that fixture correction.
