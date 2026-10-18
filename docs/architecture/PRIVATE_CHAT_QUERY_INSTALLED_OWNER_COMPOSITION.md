# Private Chat QUERY installed-owner composition

Design before implementation, 2026-10-18 UTC. Continues
[the bounded prepare/read exchange](PRIVATE_CHAT_QUERY_PREPARE_APPLICATION.md).

## Identity boundary discovered during concrete composition

The running QUERY controller uses the pinned `eom_app` database owner. Existing
`PostgresOperatorAuthorizationFence` deliberately supports only
`eom_catalog_manager_runtime` through its existing security-definer routine.
It must not be made role-configurable or granted another execution role just
to connect private Chat. `AuthenticatedSessionFence` is also not a substitute:
private live Chat origin is not a human session capture, and no capture may be
fabricated to bypass an HTTP fresh-auth denial.

1. Responsibility: Identity implements its existing `OperatorAuthorizationFence`
   interface for a trusted, pinned database owner already able to lock its own
   `app.operators` rows. Chat ownership and Catalog permissions remain separate.
2. Canonical state is the current Identity operator row. Actual live original
   Chat origin comes from the existing authenticated fixed-peer source RPC; the
   new fence itself is not authentication, a Chat grant or a session refresh.
3. Reuse `OperatorAuthorizationFenceOwnerPin` (role/name and actual OID) and bind
   one selected operator ID per operation. Preserve full origin/request/Graph/
   policy identities in their existing owners; do not persist a second registry.
4. Before locking, verify actual CURRENT_USER=SESSION_USER and pinned role/OID,
   non-superuser/non-BYPASSRLS, actual ownership of the operator table and app
   namespace, READ COMMITTED root and exact app/pg_catalog namespace. Refresh the
   bound row and reject inactive/deleted/password-change-required state.
5. Access is an indexed one-operator lookup with FOR SHARE. Existing supported
   Identity writers take that operator's exclusive row lock before role/status
   changes, so the fence survives through caller commit/rollback.
6. One frozen operation-local value; no retained Session, mutable witness cache,
   capability minting, queue, DB/schema/migration or new dependency. Reacquire/
   recheck on every call. No nested root is supported by this private-owner seam,
   matching the existing private source owner's clean-root requirement.
7. O(log operators) indexed target read plus bounded fixed catalog inspection,
   O(1) memory. Repeated checks deliberately refresh current status; immutable
   files and large payloads are neither copied nor hashed by this adapter.
8. The caller owns the clean transaction. Reject pending writes before autoflush,
   cap existing lock/statement waits without increasing a stricter prior setting,
   restore those settings on success; failure requires normal caller rollback.
9. Identity infrastructure owns SQL and the adapter. No Catalog/Chat/Workflow
   dependency is imported into Identity. QUERY infrastructure composes it with
   the actual live Chat client and existing public Catalog source owner.
10. Fail with existing content-free Identity error codes. No retry, login, role
    switch, credential storage, session TTL change or fallback to session capture.
11. Reusing the Catalog-only routine by widening its role contract is invalid.
    Copying the full session adapter would retain unnecessary credentials and
    three-row session/token locks. A small owner-only bound-target adapter with
    no authority cache is the simpler correct implementation.

The future QUERY factory must verify live origin, bind that exact actor, use
the same existing finite driver and create separate private-purpose native
owner/executor/launcher objects. Never borrow reference purpose or API capture.
Its protected configuration/role/launcher verification and private admission
remain required. This document/new adapter does not activate private execution.

The operation-local factory takes existing Engine/publisher/Catalog settings,
private configuration/spaces, the actual private launcher and the caller's shared
`NativeQueryPrepareDriver`. It revalidates that composition/runtime, authorizes
the original through the concrete Chat source client, binds the original actor to
the new Identity fence, then composes the existing private owner/executor/Runner/
prepare-read dispatch. Native-only family, zero worker roles and no role executor
are explicit. Repeated calls retain only immutable configuration and the same
finite driver; no capture/session or second scheduler is retained. This is a local
factory, not a new transport/schema/authorization service. Public Identity module
import is explicit so its optional adapter does not change existing provider
exports or eagerly load into every API/Catalog process.

## Required proof

Source tests cover wrong actor/owner/OID/namespace/isolation/root, pending writes,
current status refresh, wait-setting restoration and redacted failures. Guarded
disposable PostgreSQL tests prove actual FOR SHARE retention against a concurrent
writer, visibility after release, wrong-owner rejection, non-mutating state and
stricter timeout preservation. Real Chat/native/installed owner admission remain
separate acceptance, never inferred from these SQL tests.

## Implemented local composition

`OwnedOperatorAuthorizationFence` lives in an explicit public Identity module;
existing provider exports and Catalog/session adapters remain unchanged. It pins
the actual role/OID and checks that role really owns both the app namespace and
operator table. The protected QUERY configuration must still pin its real owner;
allowing an operator ID as a method argument is not a role/source grant. Each
call refreshes the one bound target under FOR SHARE and the same clean root,
with capped waits and no success cache or nested-root witness.

`PrivateChatQueryOwnerFactory` reuses the concrete Chat source client and private
launcher. It verifies the runtime before and after current original authorization,
then constructs distinct private source/Identity/executor/Runner objects for that
operation, all using the caller's one shared finite driver. Native private family
and zero role execution remain explicit. The factory itself submits no Workflow,
starts no thread/model and reads no question text; the independent source RPC
performs its own authorization reads. The application still fences actual SQL
Identity and Catalog/source/policy state when used, not merely at construction.

Constructor/unit fixtures explicitly replace installed-runtime/Chat observations;
they are not actual provider or source admission. The new actual SQL tests run
only through the existing marker-guarded embedding-tests action in a disposable
database, with no production runtime-role override or new privilege/routine.
No schema bytes, migration, default role family, policy or installed service is
changed by this local composition candidate.

## Verified candidate scope — 2026-10-18 03:41 UTC

Related34 suites **979 PASS /300.11s, no skips**; strict typing2 production
modules, Ruff/format5 Python files, shell syntax and diff checks PASS. Focused103
overlap this total. Source fixtures are explicit about replacing Chat/runtime
observations, not genuine installed admission. Existing Identity provider exports
are byte-unchanged; the new optional public module is not eagerly imported there.

Guarded `private-owner-wFTJo9d6` passed **121/121, no skips**. The11 new SQL
cases exercise real owner-role/catalog inspection, target refresh, retained SHARE
locks against an independent writer, lock timeout, current disable after a prior
root and wrong actor/OID/namespace/isolation/readonly/nested/pending-write denial.
No production role literal is patched to obtain positive results. Existing110
Artifact/registry/private Workflow/receipt cases remain in the same gate.

Independent protected readback matched all160 source/test/script/schema pins,
exact stdout and read-only disposable inspection at migration0057/other
connections0, and confirmed cleanup of exact state
`/tmp/eom-api-testdb-20261018033446_0ea251e3`. Wrapper1481946 is terminal.
Evidence: `/opt/eom/embedding-benchmark-os-evidence/private-owner-wFTJo9d6`;
test stdout rawece8c57b3f3deda372df678ce89be517841dc0e4cfe7bf0c7ab371f087afb7dd;
root helper rawb2fa196b19fdaa928b200568fa7962ce78100a13c995006ac2c609b494818b3f;
independent observer raw7f4370672c0e80b87c7e8ddd08f660e8c03ae32b384f99ca5408c2d3949c2d71.

These are real isolated SQL locks/rows, not actual human authentication, Chat
source authorization, native numerical execution or operating private admission.
Chat/public source populations/native execution remain declared fixtures. New
model/GPU/HTTP replay0; production DB/role/grant/runtime/default changes0. No
interactive login was requested. Operating migration stays last verified0055;
private static admission stays FALSE and existing HTTP fresh-auth denial stays
unchanged. Full C1–C5, current coverage, six real CPU/CUDA/default/rollback gates
remain OPEN.

Next: bounded private host routing to this operation-local factory, supported
same-original BUSY liveness, canonical auxiliary provenance and actual Chat
consumer delivery. The factory alone is not an installed service or activation.
