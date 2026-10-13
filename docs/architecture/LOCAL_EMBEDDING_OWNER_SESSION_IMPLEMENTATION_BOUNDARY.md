# Native embedding owner/session boundary — Identity source foundation

2026-10-13 UTC. SOURCE_FOUNDATION_IMPLEMENTED / NOT_INSTALLED_PROVIDER / NOT_ACTIVE.
This note records the smallest authenticated continuation foundation for the merged native
submission/dispatch. Only the approved Identity capture/fence and source tests below are implemented.
It does not admit a SQL role, HMAC key, source, launcher or service identity. The appended approved
transport phase adds only a schema/value contract; no DB, credential, API route, worker/native-owner
behavior, model/GPU, deployment or default changes accompany it.
The [master §§8–9](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md#8-자동화의-권한인증capacity),
[Runner boundary](LOCAL_EMBEDDING_RUNNER_IMPLEMENTATION_BOUNDARY.md#focused-gates-and-next-actual-integration)
and [native admission proposal](INCREMENTAL_EMBEDDING_RUNNER_ADMISSION_PROPOSAL.md) remain authoritative.

## Eleven decisions

1. **Responsibility/boundary.** One bounded operator-seed owner operation supplies the required
   `LocalEmbeddingOwnerAdmission` and separately admitted `LocalEmbeddingNativeExecutor`. Identity
   owns authentication/current session fencing; Catalog owns eligibility/Graph/report/registration;
   Runner owns Workflow/command/step history; Orchestrator owns reservations/publication. Ordinary
   Runner `serve` has no permanent operator continuation or implicit native grant.
2. **Canonical authority.** Only official access-token verification can create the operation-local
   capture below. Original request actor/permission SHA, `AccessAuthentication`, `/me` projection,
   session ID and receipt history alone cannot create it or authorize a later root transaction.
   Capture verifies the real HMAC-backed access token and binds its actual token/session/operator
   rows; current row state is rechecked independently on every mutation.
3. **Identity/revision.** Keep original request/plan/policy/Graph/source/launch revisions immutable.
   The capture retains only independently observed token/session/operator identity and token/session
   time bindings, internally and without serialization. Token identity is not a new logical Job,
   Artifact or credential record. Reauthorization does not rewrite an old permission audit digest.
4. **Pointers/checks.** Owner configuration pins exact native definition, released execution policy,
   runtime bundle/profile/resources and control member raw/semantic hashes. Resolve committed
   `source-plan.json`/`policy.json` through `PinnedArtifactReadContext`; reuse existing request and
   plan-entry validators. Actual source capture and final registration stay with public Catalog
   operations, never a worker role/approval claim or a parallel source resolver.
5. **Access patterns.** Exact operator/session/access-token PK lookups and current permissions,
   bounded official population capture/missing-key lookup, existing FIFO exact claims and append-only
   history. No credential scan, permission cache, source-plan queue scan or polling registry.
6. **Structures/indexes.** One opaque operation-local capture, existing immutable pointers and
   existing PK/FK/selector indexes suffice. Root fence bookkeeping is private, bounded to the actual
   live Session/root/connection/thread, not an exported permission handle or global registry.
   Repeated calls inside savepoints reuse only a fence acquired in that same root before savepoints.
7. **Scale/cost.** Existing request≤64KiB, plan≤64MiB and≤1,024 demand bounds remain unchanged.
   Session fencing is a constant number of exact identity/permission queries; source work remains
   bounded by the existing Catalog operation. No vector/text copies into DB or new dependency.
   Each seed has one owner-configured finite deadline; access/session/fresh-auth expiry can shorten
   it, never extend it. Capture itself does not admit CPU/GPU capacity.
8. **Transactions/concurrency.** Capture authentication ends its own short Identity transaction
   before Runner mutations. Each mutation uses the caller's active writable READ COMMITTED root.
   Refresh/lock operator→session→access-token identities in that fixed order and retain locks through
   root commit/rollback, including source/reservation/registration savepoints. Cooperate with actual
   revoke/disable/delete/password-change/logout/refresh writers. Recheck actual current permissions,
   session/token revocation and wall-clock expiries late after authority/source work; existing command
   token/owner/generation/expiry remains the final Runner fence. Never hold SQL through inference.
9. **Dependency/admission ownership.** New Identity infrastructure implements the capture/fence;
   existing public Catalog and Runner ports consume it through trusted owner composition. No worker
   receives token, session capture, DB/NAS access or Identity secret. Actual capture-provider HMAC-key
   and caller SQL-role admission are required separately below; source construction is not proof.
10. **Failure/retry/idempotency.** Missing capture/provider/role/fence, copied or forged capture,
    wrong root/principal, token rotation, logout, revocation, expiry or fresh-auth failure denies
    mutation/claim. No automatic login, refresh, grant repair or saved-token replay. Existing exact
    operation/encoding keys preserve retry history and uncertain ownership. Owner exit/restart drops
    the capture; another operation must authenticate again, not resurrect a queued initiator.
11. **Simpler alternative.** The protected inference-transfer CLI already proves real `/me` over
    fixed verified API transport and keeps a bearer only in memory. Reuse that presentation pattern;
    it cannot replace retained root session/token fencing. Generic `eomctl --actor-id`, an old
    `ActorContext`, or executing Runner on the API engine does not close the authority boundary.

## Implemented source-only official Identity API

The names below are public Python source seams, not wire messages or an installed grant:

```python
class AuthenticatedOperatorSession:
    """Opaque Identity-created, operation-local capture; no public DTO constructor/serializer."""

class SessionTokenService:
    def capture_access(
        self, session: Session, raw_token: str
    ) -> AuthenticatedOperatorSession: ...

class AuthService:
    def capture_access(self, raw_token: str) -> AuthenticatedOperatorSession: ...

class AuthenticatedSessionFence:
    def assert_current(
        self,
        session: Session,
        capture: AuthenticatedOperatorSession,
        *,
        required_permission: PermissionKey,
    ) -> None: ...
```

`capture_access` shares the authoritative existing token/session validation path, with unchanged
legacy authentication/refresh behavior. It adds actual verified access-token identity to an internal
capture and retains no raw token/password/refresh token/HMAC key in that capture. Its private creation
provenance is an adapter invariant, not cryptographic or unforgeable Python security. An arbitrary
constructed/copy-mutated object or a DTO echo cannot substitute for the actual capture operation.

The fence returns no grant and does not advance session idle TTL, token activity, authentication
time or refresh generation. It refreshes actual rows, checks captured identity/time bindings,
ACTIVE/nondeleted operator and required-password-change state, unrevoked ACCESS token, exact session
association, session idle/absolute and token expiry, and the independently configured fresh-auth
limit. Required action is owner-derived from the actual command: START/ADVANCE use `WORKFLOW_START`;
CANCEL/RECONCILE retain their actual existing action/admin checks. No worker/request chooses an action.
Catalog still queries current actual source roles/permissions and pinned policy; permission digests
are provenance only. The late check uses current UTC time, not a caller-supplied clock or cached pass.

Every root acquisition binds the actual Session/root/connection/backend transaction and thread.
A heartbeat thread reacquires its own fresh root fence from the same immutable operation capture;
it never carries the prior root's authorization result. Missing/nested-first/autocommit/read-only/
wrong-role contexts deny. A repeated same-root call may recheck under retained locks, not reacquire
permission from a savepoint. Metadata and actual temporal state are both rechecked before commit.

## Actual role/key and owner transport gates — unresolved, not assumptions

- Existing `AuthService` authenticates with the official `TokenCodec` key. A concrete capture provider
  must prove its protected key/configuration belongs to that same admitted Identity runtime. Do not
  give the CLI/Runner a copy of `/etc/eom/secrets/api.env`, invent another HMAC key or pass the key to
  a worker. If the official provider cannot be safely composed, capture is unavailable. Any transport
  of a server-created capture requires root's separate schema-first owner/API protocol review.
- Existing `PostgresOperatorAuthorizationFence` and its routine are specifically admitted for
  `eom_catalog_manager_runtime`, with no session/token/credential table access. Leave that released
  role/routine unchanged. The new fence must independently validate the actual caller role/OID,
  connection/schema/transaction context and exact supported lock/read privileges or an explicitly
  admitted narrow Identity-owned SQL operation. No `SET ROLE`, superuser shortcut, implicit grant
  or claim that installing the existing operator fence supplies session fencing. Exact role/SQL
  installation choice must be approved before implementation; no new routine is specified here.
- The Application API role can submit Workflow/START but cannot assign native command lease fields
  or create/update native step runs. Native execution uses separately admitted controller Sessions,
  not the API engine. Existing API UID/8765 and Catalog API-only fixed-peer transport checks remain;
  none currently exposes this new capture/native-owner operation.
- Reuse `read_control_bearer_fd` and `FixedApiControlPrincipalReader.read()` as the smallest protected
  CLI presentation pattern: bounded inherited FD, verified connected API UID before bearer bytes,
  bounded `/me`, no login/refresh/retry. Existing `require_inference_transfer_control_owner` checks
  the real `eom-workflow-runner` UID before inputs/settings/DB open. Do not import private CLI helpers
  or treat that UID check as native-purpose/runtime/session admission. Its `/me` result cannot mint
  `AuthenticatedOperatorSession`. HTTP authentication/refresh occurs outside retained SQL fences:
  `/me` itself locks/updates the session and could block against the owner's own retained fence.

An admitted one-shot owner then builds separate controller Sessions and pairs actual native owner/
executor injections, calls `start_local_embedding_in_session`, closes submission SQL and performs
only its exact Workflow's bounded claims. It delegates source capture to
`CatalogInferenceTransferSnapshotSourceAdapter.capture_in_session`, missing bindings to
`lookup_missing_embedding_bindings`, registration to `register_embedding_index`, and encoding
ownership/publication to existing Orchestrator leaves. Neither a bare capture nor a parsed policy
establishes the still-missing concrete owner/executor/publisher/current-source composition.

## Exact approved Identity source/test inventory

Only the official Identity capture/fence foundation in these eight paths is implemented:

| Exact path | Narrow responsibility |
| --- | --- |
| `services/identity_service/eom_identity_service/authenticated_session_fence.py` (new) | Opaque capture and one current caller-root fence; trusted fixed role/fresh-auth configuration, no wire/registry/framework |
| `services/identity_service/eom_identity_service/tokens.py` | Shared actual access validation/capture minting; old token/refresh semantics preserved |
| `services/identity_service/eom_identity_service/auth_service.py` | One transactional `capture_access` public wrapper; no permanent continuation |
| `services/identity_service/eom_identity_service/__init__.py` | Supported additive exports only |
| `tests/unit/test_authenticated_session_fence.py` (new) | Exact raw capture provenance, current rows/root/role/order/expiry and no activity/TTL mutation |
| `tests/api/test_token_unit.py`, `tests/api/test_auth_unit.py` | Legacy validation/refresh/logout/password-change regression and new capture wrapper |
| `tests/integration/test_authenticated_session_fence.py` (new) | Opt-in official disposable-owner gate; real independent revocation/refresh blocking, late expiry/rollback, limited role/root rules; no production execution |

Required negatives include forged/copied capture, another operator/session/token, token rotation,
logout/all-session revoke, disable/delete/required-password-change/permission revoke, stale ORM rows,
idle/absolute/access/fresh-auth expiry before and late, nested-first/wrong-root/thread/role/connection,
missing provider/key admission, and failures that leak neither credentials nor source bodies.
Run explicit API/core strict typing, Ruff/format and focused tests before source freeze.

Only after that foundation and actual role/key admission: proposed new
`services/workflow_runner/eom_workflow_runner/local_embedding_owner_admission.py` and
`tests/unit/test_local_embedding_owner_admission.py` compose the existing port/public Catalog seams;
one separately reviewed fixed one-shot owner composition/CLI leaf supplies the native executor and
operation lifetime. Root separately approves API selection schema/models/route/start adapter/lifespan
injection. Do not change schemas/worker/config/runtime/installer or invent transport behavior here.

## Distinct automatic service follow-up

Operator seed/re-authenticated bounded reconciliation is not automatic indexing. Restart-safe
missing-binding reconciliation still requires official immutable/revocable service registration,
released retrieval-policy successor with literal `LOCAL_EMBEDDING_INDEX`, exact corpus/storage/
source/model/recipe/resource/processing scope and current authenticated service transport. Existing
request1.1 service audit parsing and operator permission hashes provide none of these. No permanent
user token/session or initiating operator impersonation substitutes for this required goal follow-up.

## Approved Identity source delta — before behavior

Root approved only the eight Identity/test paths above plus this checkpoint note. Root's actual
metadata-only installed-controller probe observed `current_user=session_user=eom_app`, non-superuser,
non-BYPASSRLS and existing SELECT+UPDATE on operators/api_sessions/api_tokens. This demonstrates no
need for a new role/routine/grant; it is not installation or native admission. Implement one direct
Identity-owned caller-root adapter, with independently configured expected role name/OID and positive
fresh-auth seconds. Recheck the actual connection/role/OID/privileges/READ COMMITTED writable root,
bounded SQL wait settings and current rows before mutation; retain root/connection/thread witnesses.

The compatible target lock order is **Operator FOR SHARE → ApiSession FOR SHARE → captured ACCESS
ApiToken FOR SHARE**, never a REFRESH-token lock. Supported role/disable/delete/password writers lock
Operator before sessions; logout locks/updates sessions; refresh locks its distinct REFRESH token,
then session, then updates ACCESS tokens. Access authentication locks session and later updates the
ACCESS token without acquiring an Operator row lock. Keep that legacy behavior unchanged, and do
not call `/me` or refresh while the owner holds its session fence. No session activity/idle TTL or
token last-used/refresh generation update occurs in the new fence.

Capture shares one authoritative existing HMAC access-validation path; no duplicate token verifier.
Only private creation after real verification produces an opaque, nonserializable capture. The
source capture/fence protects copied/mutated identities and performs current/late UTC expiry and
permission checks; it does not establish that its TokenCodec/provider key is the protected production
Identity key. Actual protected provider/key/transport and native owner/executor remain uncomposed.
Unit tests use synthetic HMAC keys/rows; guarded integration is collected only here, with actual
independent writer/blocking/rollback execution left to root's supported disposable owner.

## Source freeze checkpoint

The explicit API environment passed **246 source tests** in 6.82s: the three Identity capture/token/
auth unit files above plus `test_operator_authorization_fence.py`,
`test_operator_authorization_fence_sql.py`, `test_inference_transfer_control_auth.py` and
`test_inference_transfer_authenticated_experiment_cli.py`. API and core mypy both passed all eight
listed paths with `--strict --explicit-package-bases --follow-imports=silent`; Ruff check and format
check also passed all eight. The new opt-in integration file collected **11 tests** without execution.
These are source gates, not proof of a live SQL fence, protected HMAC provider, owner transport,
native execution or production activation. Root separately owns actual disposable-DB blocking and
rollback validation. No roles, routines or grants were added.

The capture privately binds the verified access-token HMAC digest for exact row identity; it keeps
no raw token or HMAC key and exposes no serialized credential/grant. The concrete protected provider
and native owner/executor composition remain required, unimplemented follow-ups.

## Root actual disposable-DB verification — 2026-10-13 UTC

Root independently matched all nine frozen hashes and reviewed the full implementation/tests.
Its seven-suite source gate passed **246 tests in6.80s**, with strict mypy, Ruff lint and format
**eight files PASS**. This overlaps the agent's246-test inventory and is not added to it.

Using the existing marker-guarded disposable owner, root prepared a new temporary database and
ran head0053/down0052/up0053 with control-plane guards PASS. The first integration run was
**9 FAIL/2 PASS3.20s**: the generic marker fixture supplied `app,public`, not the explicit
`app,pg_catalog` connection required by this narrower owner. Read-only actual context metadata
confirmed the other role/OID/isolation/lockable checks. Production checks were not relaxed.

After the approved fixture-only correction to a separate engine with the same guarded URL/role,
READ COMMITTED, explicit search path, bounded pool and guaranteed disposal, the one recorded
rerun passed **11 tests in5.82s, skip0**. These exercised independent logout/logout-all/refresh/
password/role/disable/delete/access blocking, unchanged activity, late-expiry rollback and
the intended wrong-OID/first-savepoint denials after a valid baseline. No new role/routine/grant.

Both logs and the migration/cleanup evidence remain at
`/tmp/eom-authenticated-session-db-evidence.rdWuNz8F`. The original failed run is not relabeled.
The supported guarded cleanup removed only the marked test DB and its test identities/roles;
the state directory is absent. Production DB, real user sessions, NAS and model/GPU were untouched.

This proves the source foundation with real synthetic test transactions, **not an installed
production provider**. Current HMAC stays in the actual API Identity owner; an opaque capture
does not cross into a controller via `/me`. The fixed Catalog-manager SQL fence cannot be
injected under `eom_app`. The next explicit provider/transport and same-root Identity bridge
must close these actual boundaries without key copying, role impersonation or a saved-audit grant.

## Approved owner-session transport delta — protocol first, before behavior

Only the canonical `schemas/identity/operator-owner-session-capture-v1.schema.json`, its exact
Operator Identity packaged mirror, frozen `owner_session_capture.py` contract, additive exports/
single-resource packaging and focused contract tests are approved in this phase. Parsing this
message **does not mint an opaque capture or establish provider admission**. No endpoint, exporter,
importer, provider, Operator fence bridge or native owner behavior is implemented by this phase.

1. **Boundary.** Official API Identity verifies the bearer with its existing TokenCodec; controller
   later receives only observed capture bindings. API performs no native inference or NAS operation.
2. **Canonical source.** Only genuinely verified Identity rows can supply a future response.
   `/me`, parsed JSON, actor text, audit hashes and this frozen DTO cannot establish that provenance.
3. **Identity.** Request ID and fresh nonce identify one operation-local exchange, not a credential,
   Job or persistent continuation. Existing operator/session/ACCESS-token IDs remain separate.
4. **Checks.** A closed request fixes operator-seed purpose; response binds its exact canonical
   request SHA plus verified IDs, UTC times, refresh generation and verifier digest. No raw token,
   key, roles, permissions, grant, runtime configuration or pathname is a member of either shape.
5. **Access.** One fixed request/response exchange precedes SQL locking. Each later mutation uses
   actual caller-root SQL fencing and unchanged official Catalog source/Graph/policy checks.
6. **Structure.** Flat frozen values and one immutable schema resource suffice. No registration,
   mutable registry, bearer persistence, receipt store or generic capability framework is added.
7. **Cost.** Request <=4KiB and response <=8KiB; only bounded scalar fields exist. Canonical bytes
   and SHA binding are checked, with duplicate-key, extra-field, boolean-integer and UTC negatives.
8. **Concurrency.** Remote authentication happens once before owner SQL locks; no HTTP, `/me` or
   refresh while locks are held. Operator→Session→ACCESS order and late UTC checks remain required.
9. **Dependencies.** Values stay in Operator Identity contracts, with no IO/SQL/CLI/Catalog/Runner
   import. The future Identity transport may use only supported mechanical fixed-peer behavior,
   not CLI/private modules; the exact infrastructure placement still needs separate approval.
10. **Failure/replay.** Invalid shape/canonical bytes/request hash fails explicitly. Future wrong
    peer/provider, timeout or binding failure denies capture; no reconnect, refresh or response cache.
    Reauthentication creates a fresh nonce, while existing Workflow/encoding idempotency is retained.
11. **Alternative.** Current `/me` cannot transfer the deliberate opaque capture; copying HMAC into
    controller or making API execute native/NAS would breach existing boundaries. This tiny protocol
    is the minimum explicit next seam, not an installed transport or a saved-audit authorization.

The proposed later fixed route is `POST /api/v1/auth/owner-session-capture`. A protected provider
must independently verify actual installed Identity/provider admission and fixed connected API UID
before bearer bytes; only its genuine observation may feed a separately approved opaque importer.
The existing public `require_fixed_api_peer_socket` is infrastructure in
`eom_orchestrator.inference_transfer_control_auth`, not in CLI or Catalog. Operator Identity contracts
must not import it. Identity-owned server export belongs in Identity infrastructure; API route and
controller transport remain separate presentation/infrastructure adapters. Their behavior is not
approved here, and any mechanical relocation must preserve the released fixed-peer path/tests.

The eventual same-root Operator fence bridge must call the authenticated session fence under the
independently configured controller role, not inject the Catalog-manager-only Postgres routine
under `eom_app` or use `SET ROLE`. Current Catalog roles, permissions and source checks remain actual
queries. Automatic indexing still requires the distinct official service identity and released
`LOCAL_EMBEDDING_INDEX` policy/processing scope; an operator capture is never their substitute.

### Protocol-only source checkpoint

The canonical/mirror schema raw SHA is
`bb7571ce9decf18cff2d99e4dc13f2d92f1c237c65ab05fe243ce4d27fac4436`. Its two shapes have
four request and thirteen response fields; the request hash covers all four canonical request fields.
The response temporal rule is authenticated≤issued≤observed<min(access expiry,idle expiry), with
both expiries≤absolute expiry; it validates claims, not current wall-clock/provider authenticity.
All messages require immutable bounded exact canonical bytes at the wire parser. Model copies are
checked as raw flat fields before serialization, without a generic recursive walker. The sole public
schema-family loader returns independent values; no mutable global registry or new dependency was
introduced (Pydantic/jsonschema were already platform dependencies).

Initial source gates: **72 focused contract tests PASS**, and the combined eight-suite protocol plus
legacy Identity/CLI/auth/fence regression **318 PASS in6.88s**. API/core strict mypy and Ruff/format
passed the three Python paths. No new integration, provider, endpoint, key access, DB, model/GPU,
root operation or runtime activation was performed. These gates do not add to or relabel the earlier
root disposable evidence.
The final pinned-resource regression rerun passed **318 in6.94s**; API/core strict checks including
the earlier eight Identity paths passed **eleven files**, with final Ruff/format **three files PASS**.

The smallest next behavior candidate remains separately unapproved: Identity-owned verified-capture
export/import seams; one fixed API route calling existing `AppServices.auth.capture_access` exactly
once; and one controller infrastructure provider using the existing supported
`eom_orchestrator.inference_transfer_control_auth.require_fixed_api_peer_socket` and inherited-FD
reader. Place that client in Orchestrator/controller infrastructure, not in Operator Identity values.
Identity's exporter/importer must consume an independently admitted actual transport observation
through an Identity-owned narrow port, not import Orchestrator, CLI or private Catalog helpers.
No peer algorithm copy or generic transport/provider registry is needed; actual observation-to-opaque
import provenance and the concrete provider admission still require root's behavior review.

Proposed later source paths are `services/identity_service/eom_identity_service/owner_session_transport.py`,
`services/orchestrator/eom_orchestrator/identity_owner_session_provider.py`, and
`apps/application_api/eom_api/routers/owner_session_capture.py`, with focused corresponding tests and
only necessary public export/router registration. The authenticated Operator fence bridge and actual
native owner/executor are later separate scopes. These are a file map, not authorization to implement.

Root independently reviewed all seven frozen protocol paths and matched the raw pins. Its eight-suite
gate passed **318 tests in7.07s**, strict mypy **eleven files PASS**, Ruff and format **three files PASS**.
The canonical/schema mirror and single package-data resource remain exact. No response DTO can mint
the opaque capture; endpoint/provider/bridge/actual authentication activation still remain separate.
