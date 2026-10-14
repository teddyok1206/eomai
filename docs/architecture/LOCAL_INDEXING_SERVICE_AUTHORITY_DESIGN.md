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
