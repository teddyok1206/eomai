# Ordinary reference Item start with asynchronous similarity preparation

2026-10-15 UTC. Implementation scope, not installation or live acceptance.
Parent: [system-RAG goal](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).

1. Responsibility: add one application-owned reference-item start operation. Reuse
   `WorkflowStartRequest`, CommandAdapter's existing Evidence/control preflight,
   native preparation owner and Catalog publication/current-read. Keep the old
   `/workflows` contract and bulk production entrypoint unchanged.
2. Canonical source: existing API idempotency row binds the whole user request;
   existing Evidence result pins Graph/policy; original QUERY/START/Job owns native
   progress; the final Workflow transaction owns immutable plan23. No new tracker.
3. Identity: namespace the domain key by the actual operator/API operation. Derive
   one stable native preparation key/operation ID from that domain key. Never
   accept a client-selected completed QUERY, actor, permission, path or index.
4. Pins: repeated Evidence resolution uses the same key. Changed Graph/policy
   conflicts explicitly. Compatible Pack/preset are selected/validated before
   preparation and rechecked against the first authoring transaction. If controls
   change while waiting, they are validated afresh; no authoring plan exists yet.
   The final plan, not a transient pending response, pins the accepted controls.
5. Access: indexed operator/endpoint/key-hash lookup, existing unique claim, fixed
   preflight reads, one native QUERY, bounded context publication/current-read.
   There is no candidate list scan, new index, source cache or stored bearer.
6. Structure: retain API `PROCESSING` while auxiliary work is pending, but yield
   its request-processing lease. Invalidate the old lease owner and set expiry to
   current UTC; exact same-key/hash claims may resume. Do not store a PENDING
   response as COMPLETED or label normal waiting FAILED_FINAL. No DB migration.
7. Cost: constant indexed metadata work per explicit observation plus existing
   bounded source work. No API transaction spans model execution. No in-process
   pending-user registry, polling daemon or new queue/framework is introduced.
8. Concurrency: one existing API claim owns each short request. Yield fences stale
   complete/fail callbacks. Existing native key/claim/lease and final Workflow
   uniqueness protect replay after crash/takeover. Final receipt replay precedes
   mutable control/source preparation and returns no source bytes or new authority.
9. Dependency: router validates HTTP and calls application; application composes
   typed operation-local preparation; CommandAdapter owns existing creation;
   Catalog/Identity/native adapters retain their current authority and IO. Neither
   API nor Web reads NAS, launches an encoder or supplies a manufactured capture.
10. Failure: PENDING is a distinct closed reply, never an accepted Item. Unknown
    transport outcomes retain the original key; no automatic new-key retry or
    latest substitution. READY context is published/revalidated before the first
    plan. No plan19 creation followed by mutation to23. Forced-password, freshness,
    source revocation and actual role authorization remain mandatory.
11. Simpler alternatives: blocking HTTP through encoding is timeout-prone; caching
    PENDING prevents progress; a new durable preparation aggregate duplicates the
    existing QUERY and API claim. A narrow lease-yield operation and typed pending
    result reuse those owners without weakening their invariants.

Protocol first: add `workflow-reference-start-reply/1.0` JSON Schema2020-12 and its
packaged mirror before the response model/behavior. Input retains the existing
closed Workflow start shape, with application admission limited to supported
reference-variation requests and no production-occurrence fields. The new route is
default-disabled until installed compatibility, actual HTTP preparation/read and
bounded Item/role canaries pass. Browser/BFF retains the original draft/key while
showing a plain-language waiting state; no PENDING result enters its replay cache.

Required tests: pending→ready→exact replay; changed body/operator/key; concurrent
claims; stale finalization after yield; crash after domain commit; unavailable or
revoked native/Catalog owner; no first plan/START while pending; exact first plan23;
legacy and bulk unchanged; schema/mirror/OpenAPI, real socket and disposable PG.

## Source implementation and installation order

The API route is `POST /api/v1/workflows/reference-starts`, with current-request
Identity capture, fresh WORKFLOW_START and unchanged independent Catalog source
permissions. The existing `/workflows` and production coordinator are unchanged.
Default-off API/Web configuration flags are separate. Web normal/non-reference
requests retain the old operation. PENDING is never cached as an accepted draft;
the browser retains one saved snapshot/key, stops continuation on editor/session
changes, and bounds its observation window without calling waiting a failure.
The Web adapter validates the closed reply without importing API runtime code.

`CommandAdapter` retains the sole Evidence/control/creation rules. Its typed local
preparation strategy runs outside the final creation transaction. An existing
domain receipt skips mutable preparation after a crash between domain commit and
HTTP receipt completion. A shared pure resolution mapper and compatible-input
validator are reused at preflight and final checks, not duplicated in Web.

Activation sequence: preserve the currently held genuine HTTP canary and its
installed API/native provider; build/inspect the new compatible wheels; coordinate
API/provider-owner selection only after that canary is terminal; enable the
already supported Catalog and ordinary runner materialization before a bounded
new reference Item; verify the first actual plan23 and role inputs/review flow;
only then enable the Web flag. New Pack17 supports existing plan19/20 explicitly
as NOT_OFFERED; no auxiliary file is invented for ordinary legacy work. Existing
accepted plans/prompts/keys never change. A changed API provider requires its
independently selected source/wheel/config/code pins; no old capture is reused.
This source work does not expand vector coverage or prove the other consumers or
GPU default, and does not activate any new flag in the running services.

## Verification checkpoint — 2026-10-15 UTC

| Boundary | Observed evidence |
| --- | --- |
| API/CommandAdapter, legacy starts, BFF/browser state, schema/OpenAPI/alignment | 160 PASS/38.93s; source-only inputs, no live model or operating DB |
| Existing native-stage disposable PostgreSQL gate | 125 PASS/93.34s, including five claim-yield cases and one first-plan23 case; not125 additional cases |
| Final changed PG cases | 6 PASS/4.13s; subset of125, not additional coverage |
| API deployment inventory/build metadata/deployment/dependency boundary | 100 PASS/9.37s |
| Strict production type check | 18 modules PASS |
| Actual Chromium request-draft handlers | 1 PASS/2.20s; synthetic HTTP replies, desktop/mobile, two PENDING observations and one accepted submission with the same key |
| Formatting/static checks | changed Python Ruff/check-format, JavaScript ESM/Node syntax, shell syntax and diff whitespace PASS |
| Disposable DB postcheck | marker/owner/read-only inspection PASS, migration0055, other connections0 |
| Running service health | API LIVE/READY and API/Catalog/native owner active, restart counts0; index owner remains intentionally inactive |

Earlier failed source runs remain in the private temporary execution directory:
the route inventory rejected an unauditable conditional path (fixed by two
literal adapter methods), and a test edit misplaced an assertion (fixed in the
fixture, with the affected case passing in the final160). Incorrect test-file,
JavaScript module-mode and browser-cache invocations were corrected separately;
none executed a model or changed the operating DB. The existing Starlette/httpx
deprecation warning is recorded; no unrelated dependency migration is bundled.

The existing genuine HTTP canary is retained in its original tmux pane with the
same key and process. At this checkpoint it has not emitted a successful login
or admitted a new QUERY. It is not replaced merely because input is pending.
The old completed QUERY acceptance is not reopened. New source flags remain off;
build/installed compatibility, actual HTTP acceptance and actual Item/role
consumption are separate gates. No new migration, dependency, broker, authority,
credential store, Item generation or coverage expansion was introduced here.

### Built compatible candidate, not installed

Source `7fc8e79c5dcac67dd12bf79231792a641f9f569b` was committed/pushed, then built
using the existing API build-only and Web release builders. Both exit0. API
RECORD/source archive/OpenAPI/installed simulation and Web inventory/RECORD/
actual Web-runtime import/48-file installed simulation PASS. Strict isolated
owner-pair closure28 and API trio closure32 PASS; the latter also verifies all12
changed/new Python members plus the new closed reply schema. These closures
overlap, are not test counts, and deny checkout/ambient EOM and numerical imports.

| Candidate wheel | Raw SHA-256 |
| --- | --- |
| Platform | `90b2485404df1c6f1600fe17ef4ad9acdee0e71be7d32523124caf3cebfaf3b0` |
| API contracts | `e97e1a9ba4da1434beff12864e5b00040dca543a9eb2aee41887cc9be5dd21ff` |
| API | `376ba2535d8adf369b1addf15895208d4741c939dd1bd555eaf058eb81d73261` |
| Web | `874dfd9c92f1b364692352b3e20620edbf501cf48ef3705930dd48f69dde3ffa` |

Local build-only directories are
`/tmp/eom-api-build/7fc8e79c5dcac67dd12bf79231792a641f9f569b.m7jp2c/dist`
and `/tmp/eom-web-gui-build/7fc8e79c5dcac67dd12bf79231792a641f9f569b.ZXRmY3/dist`.
No candidate runtime flag or installed API/provider was changed. The authenticated
HTTP preparation/read and ordinary Item/role gates remain pending, and the full
goal, seed/delta expansion, other consumers and CPU/GPU gate remain incomplete.
