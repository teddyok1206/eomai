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

Package candidate `40e130d362898731a09c233bac482f08a1ee2ba8` also passes the normal
three-wheel build/RECORD and installed simulation gate. Its fixed dist is
`/tmp/eom-api-build/40e130d362898731a09c233bac482f08a1ee2ba8.0t5hh9/dist`.
An independent immutable operator interpreter `-I -B` imports34 named modules from
those wheels, resolves the packaged local-only schema references, verifies the SQL
body/schema hashes and refuses ambient-process runtime admission. No repository
module, DB/session, service installation or model/GPU execution is used by that
probe. QUERY global admission remains UNOFFERED. Logs:
`local-indexing-service-auth-wheel-build.log` and
`local-indexing-service-auth-wheel-import.log` in the same evidence directory.
Production API readiness was read-only READY at2026-10-14 05:10:43 UTC; this is a
service health observation, not acceptance or activation of the new boundary.

## Catalog service data scope

The next additive policy is `education-retrieval-access-policy/1.1`, a **service-only
closed shape**, not a change to the role-based1.0 shape or a new human role. Keep
the existing immutable Catalog policy-revision table; no new registry or migration.
The purpose-specific owner resolves1.1 explicitly, while existing role-based1.0
readers continue to reject unsupported shapes. No latest-policy substitution occurs.

Pin one exact service reference and runtime-config raw SHA, one corpus/logical
Graph, sorted approved source classes, one DOCUMENT encoder space/view recipe and
at most3 exact namespaces. Namespaces may differ only by view. Pin the execution
policy/resource semantic hashes as independent compute restrictions, and bound the
source population to at most1024. Occurrence scope allows only PAST_EXAM. Accepted
V10 solution projection is the only answer-bearing use; this grants no human query,
Item/report approval, Graph publication or arbitrary file access. The service head
is the revocation point; policy history remains immutable RELEASED evidence.

Dominant access is exact policy PK/hash plus indexed service/corpus/Graph checks and
bounded published-source iteration. Use the existing source resolver and a shared
internal candidate-pool algorithm after two separate checked authority front doors.
Do not construct operator `_scope()`, fake requester roles or synthetic permission
lists for service reads. The resulting pool is ephemeral per-root data, not a grant.
The service head, corpus and mutable source rows remain locked/rechecked under the
same explicit Catalog root. Computation and Artifact publication remain outside it.
Failure/timeout requires rollback; same-key reconciliation preserves prior output.
The simpler UID/parser/ADMIN reuse is insufficient, while a parallel source engine
or generic permission framework would duplicate existing authoritative rules.

Keep the **source policy** and **service data grant** distinct. The1.1 service grant
pins the existing1.0 source-policy revision/hash; it is not stored in place of that
source policy in bindings/indexes. Both are resolved at service reads. This preserves
later real-operator retrieval under the same source-policy pins, without treating
the service as a human role or asking human readers to interpret a service policy.
Source classes/ITEM_PREPARATION and answer-bearing capability remain constrained by
the pinned source policy, while the explicit service grant supplies the distinct
background purpose authority. No permission list is fabricated from these limits.

### Implemented service policy/read boundary — 2026-10-14

The mirrored1.1 service-policy schema and strict bounded canonical model are now
implemented; raw schema SHA is
`2ba2fc1fd906fef5a17acb3a7ba7d7e3351aa9a2e863a4386f0913b4bf7f7152`.
The1.0 policy schema bytes and role semantics remain unchanged. The new policy has
no roles/permissions/operator ID, and rejects credentials, copied-model extras,
mixed model/recipe/partition/population namespaces, occurrence/non-past-exam mixing
and stale semantic hashes. An exact runtime-config hash is mandatory independently
of the service reference. Execution-policy/resource hashes do not themselves launch
or admit numerical work.

`CatalogLocalIndexingSourceAuthority` requires the concrete Identity DB/runtime
fence, explicitly resolves both service1.1 and source1.0 policies, and retains
current corpus/publication/policy locks. It checks the exact namespace, model,
recipe, source classes, source-count ceiling and compute-control hashes. The old
role-based `_scope()` is never called for a service. The source policy must permit
ITEM_PREPARATION, the requested source classes and answer-bearing Item capability.

`KnowledgeRetrievalApplicationService` now has two authority front doors and one
shared bounded candidate-pool algorithm. The snapshot adapter likewise has
separate operator/service envelopes and one shared mutable-source lock, Artifact
prefetch, physical-member verification, accepted-report and projection body. This
avoids a second search engine or copied scientific eligibility rules. Service
capture rechecks authority late; scope-only admission does no source/member IO.
Missing reports and unavailable views retain the existing partial coverage meaning.

Source gates before final regression: new policy/authority77 PASS, existing
retrieval/snapshot/registry adapter141 PASS, strict mypy46 modules and Ruff lint/
format83 files PASS. The new IAM/unit and metadata tests use explicitly synthetic
seams; they are not root/Catalog runtime admission or an actual corpus run.

Actual guarded disposable PostgreSQL:51 PASS, comprising prior registry29, exact
SQL function semantics13 and new policy reads9. The9 new cases run under the
actual disposable owner and keep all synthetic1.0/1.1 policy rows in rolled-back
roots. Exact PK/hash/family, malformed/extra documents, real RowShareLock and
rejection of1.1 by human1.0 readers are checked. No service/IAM/worker grant or
runtime role change is made. Postcheck confirms the disposable marker/owner,
head0055,0 other connections and an actual read-only inspect transaction.

The first policy DB run was50 PASS/1 failure and remains in
`local-indexing-source-policy-postgres.log`. It exposed an existing parser-boundary
defect: `_policy()` caught Pydantic validation errors but not JSON Schema validation
errors, so an unsupported document leaked the internal schema exception. The same
deserialization owner now maps both to its stable POLICY_INVALID error; no special
service-version bypass was added. The reviewed51 PASS is recorded separately.
The initial synthetic namespace-negative fixture accidentally selected its existing
view; it now selects a genuinely different view, without weakening the scope rule.

Required next work remains supported service-policy publication, Registry/Runner
service-purpose composition, immutable successor execution/request controls, actual
installed admission and bounded seed/delta/replay/QUERY. No new service, policy or
numerical purpose has been installed/activated by this source/read checkpoint.
`CATALOG_SERVICE_DATA_POLICY=SOURCE_AND_DISPOSABLE_READ_PASS`,
`CATALOG_SERVICE_POLICY_PUBLICATION=NOT_IMPLEMENTED`,
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

Final checkpoint regression:83 suites /2,275 PASS in283.77s, strict mypy46
modules and Ruff lint/format83 files PASS. All source/schema/resource/dependency
and existing operator/INDEX/QUERY boundaries remain in that gate. No skipped case
is relabeled as an executed live permission or model test. Evidence under the same
`/tmp/eom-identity-provider-install.nAaycoDM/` directory:

- `local-indexing-source-policy-regression.log`
- `local-indexing-source-policy-{mypy,ruff,format}.log`
- `local-indexing-source-authority-final.log`
- `local-indexing-source-policy-postgres-reviewed.log`
- `local-indexing-source-policy-inspect.log`

This is source/package-read preparation plus actual disposable owner policy reads,
not the completed incremental-index goal or production service activation.

Package candidate `ac7df7db935d636218c053c01de54c6440f77b48` passes the3-wheel
build/RECORD and installed simulation. Fixed dist:
`/tmp/eom-api-build/ac7df7db935d636218c053c01de54c6440f77b48.UeXkNf/dist`.
The immutable operator interpreter `-I -B` imports40 named modules from wheels
only, resolves the new schema's packaged local reference closure, round-trips the
synthetic service policy and preserves separate service/source policy references.
It rejects human-policy reinterpretation, a missing actual service fence and
ambient-process runtime admission. No DB connection, service/policy publication,
installation, model/GPU run or source-checkout dependency is used. QUERY global
admission remains UNOFFERED. Evidence:
`local-indexing-source-policy-wheel-{build,import}.log` in the same directory.

## Supported service-policy publication

Catalog owns one small control publication use case, not a runtime self-grant.
It requires an explicit clean writable READ COMMITTED root and the actual policy
table owner (`SESSION_USER = CURRENT_USER`), then the supported Identity owner
metadata lock for the exact ACTIVE service revision. Source policy1.0 and ACTIVE
corpus/logical Graph are resolved/locked through their existing owners. The shared
pure source-policy compatibility rule is used both here and by runtime reads.

The canonical source is the existing immutable Catalog policy-revision row. Its
revision PK plus semantic SHA supplies idempotency; no new command queue, outbox,
registry, operation-key table or schema migration is needed. Concurrent exact
publication inserts once; the losing root reads and revalidates the same row.
Different content under the same revision fails, never updates or repairs it.
Use bounded waits, one savepoint for the insertion, and retained pre-savepoint
Identity/source/corpus locks. Caller commits/rolls back the root; uncertain timeouts
require same-revision replay after rollback. Only small policy metadata is stored.

Expected scale is a small number of releases. Exact PK/unique-hash lookup and
indexed corpus/service references are O(log R); metadata parsing is bounded64KiB.
The returned result contains revision/hash, actual publication audit and created/
replayed observation, not service authentication or a data capability. Runtime has
no policy-table INSERT/UPDATE/DELETE grant. Actual runtime/config/compute admission
remains a separate later gate. Direct ad-hoc DB rows and copied operator credentials
are not a supported substitute. A generic publication framework is unnecessary for
this single control operation; existing typed policies/relations are reused.

Implementation and actual disposable owner evidence are in the
[publication checkpoint](../status/LOCAL_INDEXING_POLICY_PUBLICATION_CHECKPOINT_2026-10-14.md).
The supported control API is implemented; service/runtime activation is not.

## Registry service-purpose composition — implementation plan

1. Catalog's existing Registry application remains the one owner of exact encoding/
   binding lookup, registration/CAS/replay and Artifact validation. A narrow trusted
   source adapter adds service-purpose admission, not a second Registry/search engine.
2. Canonical source stays the existing Graph/source/accepted-report resolver and
   committed Artifact. Service identity and policy stay at their existing owners.
3. No new logical entity/revision/table is needed. An owner-local service caller holds
   only the exact public service reference. It is audit/selection, never authority.
4. The installed authority must match that reference and freshly fence actual runtime/
   DB identity plus service grant for every capture. Source bindings keep parent1.0
   policy pins, not the service1.1 grant. Missing/stale/hash/revoked references fail.
5. Access remains indexed encoding/binding lookup, immutable Artifact iteration and
   current-source capture. Service discovery/publication cannot become user QUERY.
6. Use a closed operator-or-service caller value, one dedicated indexing source
   adapter and the existing map/set/indexed repositories. No new queue or IAM layer.
7. Preserve current bounded1024-source scale and O(S+V) materialization. Scope-only
   admission reads no file; exact-byte/numeric validation is still shared.
8. Current authority locks are obtained before Registry's savepoint and rechecked
   under the same caller root. Numerical work and Artifact publication retain their
   current separate owner/transaction boundaries.
9. Composition is Catalog infrastructure/application over public Identity contracts.
   Human authorization and read APIs retain actual-operator semantics; no fake role.
10. Same-key replay still reauthorizes and never rewinds history. Revocation fails
    before Registry writes; failures preserve original rows/results. No automatic
    retry, latest substitution or failed-history reinterpretation is introduced.
11. Passing a service ID as an operator, skipping publish permission globally, or
    copying registration/materialization code is simpler only superficially and
    violates authority/maintenance boundaries. The separate typed entry reuses the
    existing validator and source materializer instead.

This is an in-process owner composition change. There is no new wire message;
existing frozen JSON Schemas retain their bytes/meaning. Runner service execution
still requires explicit successor request/execution controls and actual installation.

### Next execution-control decision (not activated)

Use a service-only request1.2 and execution-policy1.1, leaving request1.1's future
service-audit rejection and `OPERATOR_SEED_ONLY` policy1.0 unchanged. Policy1.1 pins
the exact service reference, not the service grant hash: Catalog's grant pins the
native policy, so the reverse reference would create a hash cycle. Its profiles,
numerical input/output, CPU/GPU resource limits and explicit current-owner checks
reuse the existing owners. An audit hash is never runtime/source authorization.

The fixed `local-embedding-index@1.0.0` DAG has no actor rule: it declares the same
encode/complete operations and one-attempt limits. Reuse its unchanged bytes/hash;
new actor admission belongs in the successor control contracts, not a second DAG,
new queue or resealed numerical environment. Existing completion/launch contracts
already pin the exact Workflow request SHA and need no actor-only format change.

The existing Workflow actor columns admit the50-character logical service ID and
a purpose-specific actor type within their bounds. Do not pass it as an operator or
generic SYSTEM. Extend the existing owner/claim/lease/recovery/executor path with
explicit typed dispatch and fresh service fencing; do not create a target-scanning
parallel runner. Old request hashes/business fingerprints remain exact. Any claimed
runtime compatibility or activation still needs its own installed/actual evidence.

### Runner successor implementation boundary

1. Runner owns admission/commands/claim/lease/recovery; Orchestrator retains numerical
   execution, encoding reservations and Artifact commit. No worker acquires DB/NAS.
2. Canonical authority remains current Identity plus Catalog grant/source/report;
   canonical execution controls remain existing committed policy/plan Artifacts.
3. Reuse logical service/revision/hash and existing Workflow/command/Job identities.
   New schema versions identify new messages, not new mutable entity registries.
4. Request1.2 pins service audit, source policy, Graph, plan, native policy1.1, runtime
   bundle, namespace/space and resources. Resolve exact versions/hashes; never latest.
5. Dominant access is exact key lookup, indexed command claim, immutable event order
   and bounded source iteration. No per-runner independent target scan.
6. Reuse indexed queues, unique encoding keys, CAS heads and append-only checkpoints.
   Add only a closed request/policy union and a purpose-specific authority strategy.
7. Metadata stays64KiB, sources/demands bounded1024; no new corpus-scale copy, vector
   DB value or query. Existing numerical/file materialization remains the sole path.
8. Acquire actual source/actor fences before submission/claim savepoints; retain and
   recheck in each root, and validate live lease late. Never compute under SQL locks.
9. IO-free workflow contracts stay below application/adapter composition. Human and
   machine authentication are separate strategies; execution/recovery logic is shared.
10. Preserve old business/request hashes and old audit-only rejection. Use actor type
    `local_indexing_service` with its exact logical ID, not human/SYSTEM. Deny revoked
    service, mismatched controls and stale command before effects; uncertain execution
    rejoins its original launch, never creates a new identity or rewrites failure.
11. Extending operator policy1.0, copying the executor, granting a saved audit, or
    creating a second queue is insufficient. Successor controls and a narrow actual
    actor authority reuse the same numerical path and keep old semantics testable.

No migration or dependency is planned for this actor/control change. Schema2020-12
and packaged mirrors precede models/behavior. Source tests and disposable SQL prove
only their explicit seams; real service installation and bounded processing remain
separate required acceptance.
