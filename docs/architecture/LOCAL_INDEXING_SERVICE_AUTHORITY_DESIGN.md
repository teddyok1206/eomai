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

`SERVICE_IDENTITY_PERSISTENCE=NOT_IMPLEMENTED`,
`SERVICE_RUNTIME_AUTHENTICATION=NOT_IMPLEMENTED`,
`CATALOG_SERVICE_SOURCE_GRANT=NOT_IMPLEMENTED`,
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.
