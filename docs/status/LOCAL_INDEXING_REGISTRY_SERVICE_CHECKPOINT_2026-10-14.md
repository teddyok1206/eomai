# Local indexing Registry service composition checkpoint

2026-10-14 UTC. A source/owner-composition checkpoint of the
[original incremental RAG goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md),
not full-goal completion or installed activation. Predecessor:
[policy publication](LOCAL_INDEXING_POLICY_PUBLICATION_CHECKPOINT_2026-10-14.md).
Durable ownership and the next control decision are in the
[service authority design](../architecture/LOCAL_INDEXING_SERVICE_AUTHORITY_DESIGN.md#registry-service-purpose-composition--implementation-plan).

## Implemented boundary

`CatalogEmbeddingRegistryVerifier.for_indexing_service` composes an exact trusted
`CatalogIndexingRegistrySourceAuthority`. Its small owner-local caller contains
only a pinned public service reference, never an operator ID, role or permission.
Caller validation is not authentication. Each capture still goes through Catalog's
actual runtime/DB/service-grant/source-policy gate under the same root Session.

- One Registry application/repository and one canonical source/report/numerical
  materializer. Scope admission, registration/prepared validation, exact lookup and
  retained-row/index assembly use the same new service front door. The repeated
  registration capture blocks now share the same owner dispatch as lookup.
- The service grant stays separate from parent source policy1.0. Index bindings and
  consumer selection keep the existing source-policy pins. No fake ADMIN/WORKER or
  service ID passed as an operator, and no automatic fallback between caller modes.
- Scope-only admission reads no population or file. The installed source owner
  reauthorizes actual service identity/grant before and after full materialization;
  same-root locks and the existing pre-savepoint authority checks remain in place.
- Existing registration/CAS/replay/encoding uniqueness, Artifact producer approval,
  finite/L2/hash/row validation and historical observations are reused, not copied.
  Same-key replay still requires current authority and never rewinds history.
- Service-derived publication does **not** authorize consumer QUERY. Human similarity
  and pinned-index reads reject the service actor; actual user admission is unchanged.
- No new wire schema, DB relation/migration, dependency, worker permission or model
  runtime. Source/test migration head remains0055; no production mutation occurred.

## Executed evidence

Final source regression: **85 suites /2,304 PASS** in295.20s. Focused Registry/service/
source tests:149 PASS, including21 new cases. Strict mypy48 modules and Ruff lint/
format89 files PASS. Existing operator source/consumer/native boundaries are included.

Marker-guarded disposable PostgreSQL: **30 PASS** in78.38s (existing28 +2 service-actor
application cases). The new two verify actual Registry registration/replay/missing
lookup and rejection before any Registry SQL when the trusted verifier denies replay.
Their IAM/source verifier is explicitly synthetic. They do not prove an authenticated
machine service or actual source/numerical execution. Committed synthetic histories
are retained. Postcheck: correct marker/owner, head0055,0 other connections, read-only
inspection confirmed.

Evidence directory: `/tmp/eom-identity-provider-install.nAaycoDM/`.

- `local-indexing-registry-unit-reviewed.log`
- `local-indexing-registry-regression.log`
- `local-indexing-registry-mypy.log`
- `local-indexing-registry-final-{ruff,format}.log`
- `local-indexing-registry-postgres.log`
- `local-indexing-registry-inspect.log`

The earlier `local-indexing-registry-unit.log` is preserved:147 PASS /2 fixture
failures. One supposed foreign-view fixture selected its unchanged current view;
one old human-only synthetic verifier accessed `operator_id` on the service actor.
The tests now choose a genuinely different view and an explicitly synthetic service
verification seam. Production guards were not relaxed to repair either fixture.

## Remaining work, not claimed complete

Service-purpose Runner request/execution control, installed service unit/provider,
least-privilege DB admission and actual official missing-binding reconciliation are
not activated by this code. Old request1.1 service audits remain non-executable and
policy1.0 remains operator-seed-only. The next implementation uses explicit successor
controls and the existing command/lease/recovery/executor path, not a second queue.

Genuine bounded persistent seed, source-add delta, same-key replay and QUERY remain
required, followed by consumers in the original order and actual CPU/GPU comparison.
There is no measured reason yet to change the default device. Source gates, synthetic
DB tests, parsed service metadata and historical520 experiments do not close these.
