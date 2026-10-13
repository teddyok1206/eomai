# Native embedding owner/session boundary — proposal for review

2026-10-13 UTC. DESIGN_ONLY / NO_BEHAVIOR / NOT_INSTALLED / NOT_ACTIVE.
This note specifies the smallest missing authenticated continuation for the merged native
submission/dispatch. It does not admit a SQL role, HMAC key, source, launcher or service identity.
No code, schema, DB, credential, API, model/GPU, deployment or default changes accompany it.
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

## Proposed smallest official Identity API

The names below are proposed public Python seams, not wire messages or an installed grant:

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

## Exact next source/test plan — root approval required before behavior

First implement/review only the official Identity capture/fence foundation:

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
