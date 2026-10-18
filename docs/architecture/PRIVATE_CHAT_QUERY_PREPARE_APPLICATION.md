# Private Chat QUERY preparation and finite drive

Design before behavior, 2026-10-18 UTC. Continues
[initial private context selection](PRIVATE_CHAT_CONTEXT_PREPARATION.md).

1. Responsibility: join the existing initial-selection/atomic Workflow+START use
   case, dedicated private Runner and canonical completed-context reader. This is
   the missing owner application before a Chat tool can await/use a private query.
2. Canonical source is the exact live V4 Chat origin, immutable original private
   Workflow request, selected controls/index and existing result/receipt Artifacts.
   A supplied actor ID, old turn or prior success is never authority.
3. Preserve original turn/claim/worker-input hash/basis, request/index/Graph/policy
   and execution identities. Repeat prepare uses the existing unique origin key;
   no tool-sequence key or substitute approved Item is allocated.
4. Inputs and context results already have closed JSON Schema2020-12/Pydantic
   contracts. The application result is a frozen owner-local value, not a new
   worker/API wire contract. No V4/tool2 bytes or prompt meaning change here.
5. Access: one indexed origin lookup, bounded command failure existence lookup,
   exact canonical result read and fixed Workflow drive. No conversation scan.
6. Reuse the existing single finite Thread handle for reference and private QUERY,
   with separate explicit offer methods and concrete family/actor/owner guards.
   One private invocation cannot overlap a reference invocation in that handle.
   Keep the old public reference driver import as a compatibility alias, not a
   second queue/registry/pool or arbitrary runner callback.
7. Complexity: O(log W + log C + C_workflow) workflow/command selection plus existing bounded
   index/context resolution; one active handle and O(1) drive metadata. No new
   DB/index/cache/migration, retained authority or persistent text.
8. Commit the original Workflow+START transaction before any drive offer or
   completed-context read. Never run a model while holding that admission root.
   A busy driver preserves the existing pending Workflow; no new identity/retry.
9. Runner infrastructure composes the Catalog/source interfaces and existing
   domain Workflow. Domain/schema packages remain infrastructure-free. Orchestrator
   still owns Artifact publication; Chat/native workers get no DB/NAS access.
10. PENDING, initial INDEX_NOT_PREPARED, terminal execution failure and invalid/
    revoked canonical reads remain distinct. READY requires the existing actual
    canonical reader plus current private/public reauthorization; a COMPLETED row
    alone is insufficient. Errors are content-free; unknown failure never becomes
    new model work. Stop offers/drain only the actual original handle on close.
11. Copying the reference driver would create independent unsupervised execution
    handles. Reusing its reference-only admission would fabricate authority.
    Sharing only the finite handle and keeping two explicit validated entrypoints
    is the smaller correct boundary.

This does not activate private admission, install migration0057, publish policy,
launch a model, change a Chat worker protocol or silently change TOPIC/RECENT/EXAM
search behavior. Semantic delivery must still retain provenance and distinguish
PENDING from unavailable/failed work. Reordering six legacy cards is not full
private candidate retrieval. Actual fresh-user and C1–C5/device gates remain open.

## Implemented ownership boundary

`NativePrivateChatQueryPreparation` commits the supported initial selection and
original Workflow/START before offering its dedicated Runner or opening canonical
result-read roots. A current `COMPLETED` row is only a reason to invoke the existing
private canonical reader/service; it cannot create READY without validated query
execution and current private/public/producer authorization. A failed or unavailable
canonical read is never repaired with another query. Initial index absence remains
the existing distinct `PrivateChatQueryPreparationUnavailable` exception.

The immutable owner-local result preserves the original request/origin and actual
context, not a second persisted payload. Revalidated context equality is canonical
value equality, not Python object identity. Queue actor selection is not permission:
the actual `OperatorAuthorizationFence` public protocol remains authoritative and
does not need a caller-invented `capture` attribute. The application rechecks its
exact owner/executor/driver composition before every use.

`NativeQueryPrepareDriver` shares the original one-handle lifecycle across two
explicit guarded offers. Cross-family calls cannot coalesce even if supplied the
same Workflow ID. The old reference import is an explicit compatibility alias;
its public offer stays reference-only. Shared composition guards/value types are
separate from both applications, so loading the driver does not load the private
context application or create an import cycle. A child interruption remains
UNAVAILABLE, with no process-wide exception-hook disclosure or automatic retry.

Tests distinguish real Thread handles/SQL roots/local canonical files from mocked
source admission, Identity and native/canonical result ports. The staged PostgreSQL
fixture explicitly admits its declared private definition; production admission
stays FALSE. New application cases must prove cross-connection commit visibility,
one original Workflow/START on replay, late-denial preservation and failed-history
preservation. No source test or this declared fixture proves installed private
worker/tool delivery. No schema bytes, migration or dependency changed.

The failed-command existence read uses the existing indexed
`WorkflowCommandRecord.workflow_id` column, then checks the small original
Workflow's command set before LIMIT1. Initial origin lookup uses the existing
unique Workflow idempotency key. No new global scan or index is introduced.

## Source checkpoint and preserved failures

Final related23 suites **597 PASS /289.38s, no skips**; strict mypy5 production
modules, Ruff/format9 and diff checks PASS. An actual separate-process import
verified the shared/legacy driver alias without ML or the private context
application being loaded. Positive admission/Chat/Identity/native results in
these source tests remain synthetic; real Thread handles and SQL root behavior
are distinguished from operating model/consumer acceptance.

The first broad run was590 PASS/1 FAIL: a test incorrectly required the same
Python context object after schema revalidation. It now checks the unchanged
canonical value rather than weakening validation. An earlier invalid synthetic
service-ID fixture was corrected to the official local-indexing identifier.
The public Identity protocol has no `capture` field; composition therefore uses
queue selection only, and the actual existing Identity/source fences still decide
authority. No capture object was fabricated. Two child-interruption tests failed
before the finite driver recorded UNAVAILABLE without invoking the exception hook;
both passed after that fix. Earlier29/54/57 focused cases overlap this final597.

The first guarded147-pin PostgreSQL gate, `private-prepare-Tx4CEHDY`, preserved
100 PASS/3 FAIL and successful cleanup. All three new tests had reached their
post-commit independent-connection observer, which mistakenly expected START
instead of the existing official START_WORKFLOW enum value. Independent protected
readback proved that exact assertion failure and removal of disposable state
`/tmp/eom-api-testdb-20261018023314_46c642c1`. Test-only enum correction does not
change production workflow state, admission, commands or immutable history.
Original failed stdout raw3c7c26c1adb0d50c6e7a348f30416d230064992fcaecbd909d5f1d0a65fd7096
and protected evidence remain at
`/opt/eom/embedding-benchmark-os-evidence/private-prepare-Tx4CEHDY`.
The distinct `private-prepare-8gABET14` gate is the explicit developer re-execution
after that fixture correction, not an automatic retry or live query resubmission.

## Final disposable PostgreSQL verification — 2026-10-18 02:46 UTC

The distinct147-pin `private-prepare-8gABET14` gate passed **103/103, no skips**,
including the three new application cases. Independent protected readback matched
the exact test stdout, all current source pins, real read-only inspection at
source migration0057/other connections0, and successful supported cleanup. Exact
disposable state `/tmp/eom-api-testdb-20261018023958_5640889b` no longer exists.
Both finite root1446697/wrapper1446689 are terminal. The prior failed100/3 gate
and its diagnostics remain preserved, not rewritten or counted as103 PASS.

Evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-prepare-8gABET14`;
root helper raw62bafecced1fb2ce515c283d1117dcac7923ec4126c7ff0f7027148758b88619;
test stdout rawe4f502baca5017cd34150ffcbe56b9aba1240170ef632b2dc0c0e7ba579757b4;
independent observer rawcde3fa20ae737072357e1d7226d83cf3e03ed25e7c797d14ec00109e02c01965.
Local bounded preparation/readback is `/tmp/eom-private-prepare-db.8gABET14`.

SQL/registered files/Workflow/START persistence are real in this disposable
database; Chat/Identity/source populations and native numerical execution remain
declared fixtures. Model runs0, production DB/privilege/admission changes0. Operating
migration remains last verified0055, not this test database's0057. No current service,
slot, numerical prefix or CPU default changed, and no login was requested.

Still required: actual private policy/admission and protected owner composition,
an internal prepare/read transport and actual Chat delivery with canonical
auxiliary provenance/async handling. Existing multi-member control file sets and
the Chat resolver may allow an owner-only provenance companion beside the frozen
tool2 record; verify full producer/permission/replay closure before choosing that
design. Do not invent an implicit audit registry, silently repurpose TOPIC or
change frozen worker/Origin bytes just to get a passing fixture. C1–C5, full
coverage and six real CPU/CUDA/default/rollback gates remain OPEN.

## Published candidate and package evidence

Code candidate `16b021b25cc2408521f682e7b12fb1b77ccc3852` is pushed. Standard
build-only three-wheel/RECORD/installed-simulation verification PASS; all five
changed production modules in the platform wheel match the selected source bytes.
Build directory:
`/tmp/eom-api-build/16b021b25cc2408521f682e7b12fb1b77ccc3852.T2wQTy/dist`.
Platform raw25d9fc5b38aed74a9d07ee8aa2c3a2c53d910bc162c7d60d7b490b6a5a87e0c5;
API contracts rawc05103df64a904f6b1b834c8d533e52c757307f66e485efab3e7fde3fa217c7b.
This is a developer package candidate, NOT protected installation/activation.
The earlier actual c6c01fe7 root CUDA capture remains separate historical evidence.
