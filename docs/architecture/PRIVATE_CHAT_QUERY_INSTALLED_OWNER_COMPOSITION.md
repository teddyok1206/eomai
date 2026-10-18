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

## Bounded host connection — design before behavior

Extend the existing reference QUERY host with one optional private listener, not
a parallel service/pool/queue. Each endpoint has its own root-provisioned SGID
parent: API and Chat can use their own group without adding a worker/controller
to another group. Both sockets retain the same non-root owner UID. API and Chat
peer UIDs must be distinct and the endpoints/parents cannot alias.

The existing four-handler semaphore/pool is shared across both listeners.
Two known descriptors use bounded select/accept (O(1), no pending task backlog).
The API listener retains its unchanged current human-capture exchange. The
private listener checks only its fixed kernel Chat peer before parsing the closed
existing EOF-framed request; then its trusted operation-local factory authorizes
that exact origin and returns the existing dispatch. No request/worker chooses
an endpoint profile, declared role, capture or arbitrary callable.

Current installed provider observation is rechecked before private dispatch as
part of compatible owner service composition; it never mints a human capture.
The factory independently rechecks native runtime/live origin/current sources.
An exception after application entry is still unknown original work, not a retry
grant. Invalid peer/frame must not call the factory. One request invokes factory
and application at most once and gets at most one final reply.

Startup failure must close/remove only already-owned socket identities; a foreign
or replaced socket is preserved. Stop closes both listeners, drains the shared
finite pool and leaves the actual native driver/runtime lifecycle to its existing
owner. Saturation closes excess connections before any application call. No
schema, migration, model/native launch or actual service activation occurs here.
Installed configuration selection and acknowledged BUSY-original liveness remain
separate required steps, not implied by having a listener implementation.

### Host source checkpoint — 2026-10-18 04:00 UTC

The optional private listener and operation-local factory dispatch are implemented
in the existing host; both listeners share four handlers and bounded select/accept.
Kernel peer rejection precedes provider reads/private factory construction. The
existing human-capture handler is unchanged. Private request/reply1.0 schema
bytes are unchanged; only the owner-local Python factory port is added.

Related36 suites **1001 PASS /312.58s, no skips**; focused59 overlap that total.
Strict typing3 production modules, Ruff/format4 Python files and diff checks PASS.
Cases use real local Unix sockets/current test UID, explicit synthetic installed
provider/source/handler behavior, and no model. They cover separate endpoint
profiles, wrong peers/frames/provider, one factory call/final failure, global four
handler saturation, invalid profiles, partial bind cleanup and replacement-socket
preservation. They are NOT an actual protected API/Chat dual-UID/DAC deployment
or live source authorization. No actual host/configuration was activated.

This change touches only the host/socket factory adapter; no SQL, state machine,
claim, native executor or persistence rule changed. The preceding f0ff5875
121-case disposable SQL evidence remains its historical data-layer proof rather
than being relabeled as this host's OS acceptance. No unnecessary DB/model run
was added to test a socket-only boundary.

### Actual read-only installation inventory — 2026-10-18 03:55 UTC

A fixed root read-only probe, through the same existing noninteractive operator
pane, found both private prepare/CPU unit templates, its owner env file, runtime
and owner workspace directories, and the private launcher module in the running
0fab624c owner release **MISSING**. No env content/credential was emitted, and no
file/service/workflow/model was changed. Original QUERY service ExecStart still
points to owner0fab624c0cf0feee08431793861a9c2b9c8462f3.
Probe `/tmp/eom-private-runtime-inventory.QwK9S4EN/observe_root.py`, raw
f8922e6b080b2acbd361031c83d6f2a161424a15ab94620df333f9519eabdc1a;
root readback raw6dbc21f4e72f45a3650d1d196fe66d09e6457ba3c8631fc2e2679be01ff4974a.

Read-only source inspection of the fixed CPU target referenced by the proposed
private unit also found only INDEX/QUERY argument dispatch. Checked member:
`/opt/eom/conda/envs/eom-embedding-index-cpu/lib/python3.12/site-packages/eom_catalog_service/embedding_native_cpu.py`,
rawdf379cd5a5de58865571f061a50c710f422f6a52e5cffd1b602d2bbc13594720.
This is file/CLI-branch evidence, not a model invocation or proof of which modules
an already-running INDEX process has loaded. It establishes that copying the new
private unit/turning on a flag is insufficient for that fixed interpreter target.

Next deployment must verify/stage a compatible private-capable numerical release,
private units/env/directories/policy/owner configuration and Chat source endpoint.
Keep current INDEX and frozen comparison CPU intact; do not invoke the existing
in-place prefix-replacement path while INDEX work is live. First inspect/reuse the
supported runtime producer and plan exact successor/rollback/claim-drain boundaries.
This is an expected uninstalled feature gap, not an incident in existing services.
Actual source/consumer/CPU-CUDA/default/rollback gates remain OPEN.

## Published package candidate — NOT_INSTALLED

Code `f0ff587591b5662e51a7b4f0e927164535032132` is pushed. Standard build-only
three-wheel/RECORD/installed-simulation checks PASS. The two new production
modules and unchanged Identity provider export module match source bytes inside
the platform wheel. Separate-process factory import loads no torch/transformers/
sentence-transformers/numpy. Existing runtime services were not reinstalled.
Build directory:
`/tmp/eom-api-build/f0ff587591b5662e51a7b4f0e927164535032132.VAAubA/dist`.
Platform rawdfcf6b845009a38e0932fed5f39fce289693045c8ba7822a05d8852656ce0e8e;
API contracts rawebde89fbe4d6b4feb6cf5a5df9e6bcd0de2adac625ad610d8d1bd05d8de5ed7f;
API raw500dc248eab5a5dc239e6642f6a35c616a82f241faaba560eb228e3c90120994.

### Bounded host package — 2026-10-18 04:08 UTC, NOT_INSTALLED

Code `20a1b6c15f53e1cdeb127579a44397c49655e7a3` is pushed. Standard build-only
three-wheel/RECORD/installed-simulation checks PASS. Four exact platform-wheel
members match source: the host, preparation transport, operation-local factory
and unchanged packaged private request/reply1.0 schema. A separate-process host
and transport import loads no torch/transformers/sentence-transformers/numpy.
This does not establish installed admission or actual Chat source authorization.

Build directory:
`/tmp/eom-api-build/20a1b6c15f53e1cdeb127579a44397c49655e7a3.vIMZ4d/dist`.
Platform rawd24eae667d6d493ae683391c9535b668fef20e4e0823e4f660dda5ae27cf9bbb;
API contracts raw395e65c54a9bb53a753b6170699143d1d10aeac4e7a001af55ccd16e76b670d2;
API rawffae07032b9cf8edca8c9deff69220ea5344d6d9eebe3a4912735ab47c38beaa.

At04:08 UTC both existing INDEX and reference QUERY owner services remained
active/running. Neither was reinstalled or restarted for these package checks.
Private static admission remains FALSE, operating CPU default is unchanged,
and current consumer/coverage/six-real-CPU-CUDA/default/rollback gates stay OPEN.
Package completion is not full-goal completion. No new human login, model/GPU
benchmark or HTTP replay was performed; background INDEX work was left running.
