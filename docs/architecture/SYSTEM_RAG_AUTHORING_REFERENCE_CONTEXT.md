# Authoring/review use of the common approved-reference context

2026-10-16 UTC. Design before behavior; SOURCE scope, not activation.
This advances C3 of the original incremental-RAG goal, without declaring the
private-intent/private-draft query work or any consumer deployment complete.
The main implementer has read the complete common-context implementation note
(3721 lines at this checkpoint), including its historical preservation rules.

## Boundary and required decisions

1. Responsibility: the existing Catalog common composer and selected-reference
   preparer may serve ITEM_AUTHORING/ITEM_REVIEW as well as PAST_EXAM_VARIATION.
   Native execution, publication, item-start and workspace delivery retain their
   existing owners. This step creates no second search/provider or worker route.
2. Canonical source: one exact approved past-exam reference, its accepted report,
   official source resolution, pinned Graph/policy and immutable numeric members.
   These observations describe that reference, **not the private brief or draft**.
3. Identity: purpose already belongs to the closed request1.0 schema and canonical
   request hash. A changed purpose is a different request; existing QUERY/control/
   Artifact/plan identities and all predecessor schema bytes remain unchanged.
4. Pointers: retain exact reference/profile/report/index/space/recipe closure and
   current actual caller authorization. Never relabel a completed variation QUERY
   as authoring/review or substitute a later index to reuse an earlier request.
5. Access patterns: one selected-source preparation, bounded per-view PK/namespace
   reads, existing batched full-population ranking/materials, late reauthorization.
   Purpose selection adds O(1) work; it creates no extra source scan or model call.
6. Structures: one immutable Catalog-owned tuple of actually supported reference
   purposes, used by preparation and composition; a defaulted frozen owner-local
   preparation field preserves existing variation callers. No DB/index/queue/cache.
7. Scale: existing1024-source/3-view/top64 and materials8-reference bounds remain.
   No claim of constant-time source authorization or improved model throughput.
8. Transactions: caller-owned root, current Identity/source fences and original
   native START/claim/lease/receipt/rollback rules remain. Source authorization is
   not cached or derived from purpose/audit fields. Old-purpose replay conflicts
   before recapture, persistence or native execution.
9. Dependency: the existing Catalog integration values own this support policy.
   Pure composer calls public ports only; contracts/domain gain no SQL/ML/IO
   dependencies. No package, generic mode registry or new authority is introduced.
10. Failure: unoffered GENERAL_CHAT_READ/MOCK_EXAM_OBSERVATION and invalid purposes
    still fail explicitly before source reads. Missing current authority, wrong
    native request/result, stale or revoked source remain failures, not optional
    absence. Actual action permissions remain with their action owner; read support
    grants neither WORKFLOW_START nor publication/approval rights.
11. Alternative: copying the composer for authoring/review would duplicate source,
    vector and late-check rules. Changing a source type to pretend it is a private
    draft would falsify provenance. Reuse the schema's explicit approved-reference
    basis, while adding real private-query successors separately when their durable
    origin, current authority and native admission are implemented.

## Protocol, tests and activation limit

The existing JSON Schema2020-12 common request/context/materials already carry the
three purpose literals and approved-reference basis. Their wire meaning needs no
widening or predecessor edit for this **reference-only** boundary.
The new preparation field is an owner-local value, not an exposed HTTP/body field
or permission. Freeze existing schema hashes and default variation bytes in tests.

Test positive authoring/review composition through the same independent-view/
Graph-observation union, current selected material resolution and late denial.
Test changed-purpose request hashes, rejection of an old-purpose native QUERY,
same-key replay conflict without recapture/submit, strict preparation values,
missing accepted reports and unoffered consumers. Existing pointer/resource/layer,
variation/materials/QUERY/source and maximum-three-review regressions remain.

At the input1.1 foundation checkpoint4f302b99, plan23 and the item publisher were
variation-only. Do not reinterpret that checkpoint as ordinary workspace delivery.
The separate plan24 successor below extends the item owner without relaxing plan23;
private brief/result query bases remain open in the requirement ledger. No runtime
selection, source-policy change, model execution or human evaluation is part of
this source step. The continuous INDEX service stays on its pinned release.

## Executable request closure discovery and additive successor

The shared-composer characterization reproduced6 denials and now passes10 tests.
The first two real control-Artifact/native-input tests then correctly failed at
the existing native request schema: its extra allOf permits PAST_EXAM_VARIATION
only. This is a real input/output compatibility gap, not a reason to weaken that
schema or call the source foundation a completed native integration.

Add the closed **reference-query-workflow-request/1.1 input only**, before behavior.
It reuses the old request's field schemas, canonical fields/limits, actual human
capture, definition1.0.0 and fixed REFERENCE_QUERY execution. Its context permits
the three explicit approved-reference purposes. Existing request1.0/parser bytes
and semantics remain strict and variation-only; old callers still construct1.0.
Policy, native numerical input/result, launch/receipt/checkpoint and worker protocol
meanings remain unchanged: they pin exact request/context hashes and do not grant
authority from the consumer label. No DB schema, queue, model or policy expansion.

Share request fields/hash/member checks between the two frozen models, retain the
strict old parser, and add an explicit two-literal supported parser/type used by
the existing owner/Runner/Artifact readers. The ordinary query preparer selects
1.1 only for a new authoring/review reference request; it never upgrades stored
history. Unknown versions, mixed purposes, bool/extra/forged model copies, same-key
purpose drift and original missing-launch recovery denial must remain rejected.
Exact queue routing must recognize1.1 as QUERY, never ROLE/INDEX fallback.

This is a versioned extension of the same native operation, not private brief/
draft search or an authorization grant. Inspect actual source/lease/persistence
behavior in focused source and guarded disposable DB regressions before release.

## Source and guarded execution evidence

The same common composer/current selected-material owner now serves the three
explicit reference purposes. Unsupported chat/exam purposes still deny before
source reads. Purpose changes the canonical request/context hashes; an old
variation QUERY cannot be relabeled as authoring/review. Late source revocation
still removes the entire result, including counts and candidates.

Schema1.1 and its packaged mirror have raw SHA
`4b52a34d7970189de9d6447a5ebdd2b073b1999059f5e2a9c9263b0f9e890ae3`.
The old six-frame schema retains raw SHA
`68e741506fec708956096aa5af6199e7c03821219385775cf9623aea88246c9b`.
Shared frozen fields/checks have two strict literal subclasses/parsers. The public
supported type is intentionally a runtime UnionType, because existing fixed
dispatch uses isinstance; PEP695 TypeAliasType would not be a valid runtime check.
Existing native owners/queue/claim/checkpoint/Artifact readers select the two
literal parsers. Ordinary variation producers retain1.0; new reference purposes
select1.1. Definition, policy, native input/result, receipt and worker frames stay
unchanged. Real SQL routing quarantines even a malformed1.1-only marker from ROLE
and INDEX queues; correct1.1 uses the original QUERY path only.

Executed gates in explicit API Conda, without production pytest/model/GPU runs:

- Broad source regression:1971 PASS/438.97s across78 files, one pre-existing
  Starlette/httpx deprecation warning. This run precedes the last raw-input error
  translation below; it is not advertised as a single final-byte whole-repo run.
- Final affected input/owner/submission/composer boundary regression:234 PASS/
  81.49s. Two additional raw-input cases reproduce generic ValueError for copied
  extras/cycles; only that pre-schema normalization maps ValueError/TypeError to
  the existing content-free contract code. Schema-unavailable errors retain their
  separate meaning. Original red logs are preserved, not turned into success.
- Fixed handoff/systemd regression:47 PASS/15.24s, including1.0/1.1 variation/
  authoring/review staging and exact result-byte replay. Actual temporary files
  and f32 codec are used; ownership/model/installed admission remain synthetic.
- Final independently guarded PostgreSQL stage suite:132 PASS/111.46s, including
  real1.1 first-create/exact replay and concurrent same-key starts for both new
  purposes. Query-only routing, existing rollback/lease/checkpoint/immutability and
  native/index regressions pass. IAM/source/physical execution seams are explicitly
  synthetic; real control Artifact bytes and PG transactions are not live corpus.
  Before/after independent disposable identity/head0055 and zero-other-connections
  inspections PASS. No DDL/role or production data change.
- Strict mypy26 production modules; Ruff/format all changed Python paths PASS.
  These overlapping test inventories are not added into one acceptance count.
- Independent pure fixture comparison to Git baseline aba066a2 verifies identical
  canonical bytes for all eight legacy bundle/policy/request/launch/native-input/
  result/receipt/output members. This is unchanged legacy serialization evidence,
  not actual source permission or a model run.

Evidence prefix:`/tmp/eom-identity-provider-install.nAaycoDM/authoring-reference-`.
The early missing test filename executed no tests; the corrected exact inventory
passed and both invocation logs remain. No validator, timeout or history was
weakened to repair a fixture or get a green gate.

**Input1.1 foundation4f302b99: SOURCE_AND_DISPOSABLE_PASS / NOT_INSTALLED / NOT_ACTIVE.**
At this checkpoint ordinary plan delivery and private intent/result search remained
open. The later ordinary delivery work is recorded below; plan23 is still
variation-only and no old plan/Pack/request is upgraded.
API/QUERY/Web flags, source policy, numerical runtime/device and active INDEX
release were not changed by this source work.

## Immutable build and package composition

Source commit `4f302b99284a7039845d6d6dee375f1f14a524b4` passed the standard
`scripts/api/deploy_release.sh --build-only` gate. This is a build, not an install
or activation. Retained build directory:
`/tmp/eom-api-build/4f302b99284a7039845d6d6dee375f1f14a524b4.9NqFyM`.

| Immutable build member | Raw SHA-256 |
| --- | --- |
| `source.tar` | `2d68b780f1289ca1ae2ef42d21c53e8d8ed6c0f782a785fce90e9a10ad9e8936` |
| `eom_platform-0.1.0-py3-none-any.whl` | `b17a0dd2511fc07a9c813db7ae1fbe8de0c296cae71b59942bb905b968c12e57` |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `ec1ae2a1fdeb79f724781c4938a4eb0628b3b224b4b377f0e9d4f35b0e1af238` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `a4d0df9e5679a878ef7cc551af799dcdfb1dbf0b8b6a49d73019d20dd095cb71` |

An additional unprivileged `-I -B` API-Conda process verified the platform and
contract archive hashes and restricted all142 imported EOM modules to those two
selected wheels. Three purpose cases passed request/launch/receipt closure, and
the strict predecessor parser refused both1.1 cases. The input constructors came
explicitly from checkout test fixtures; this is **archive-only EOM runtime import
composition**, not a claim that the entire test process had no checkout access.
No DB, current-Identity/source lookup, model, GPU, service mutation or activation
occurred. No ML package was imported. Evidence:
`authoring-reference-release-build.log` and
`authoring-reference-owner-archive-proof.log` under the evidence prefix above.

The candidate is pushed to GitHub. The running INDEX remains source2a4843c3;
API/QUERY/Web and ordinary consumer delivery are not selected by this build.

## Ordinary authoring/review delivery successor — design before schema/behavior

1. Responsibility: extend the existing grounded execution-plan/resolver and
   Catalog role-materialization path, not the released variation-only plan23 or
   a parallel worker/search/approval framework. Source scope only until tested
   and selected in a compatible release.
2. Canonical input: a fresh ordinary educational-retrieval1.0 request, its official
   Evidence5 manifest/context and one current-authorized approved-reference
   similarity context. This context describes a reference, not a private brief
   or the generated draft. Private-query bases remain a separate open requirement.
3. Identity: new closed resolved-execution-plan24.0 pins an existing delivery and
   its small typed reference anchor. Plan19/23 documents and canonical hashes are
   never upgraded in place. Ordinary requests retain their retrieval1.0 meaning.
4. Resolution: context request must be ITEM_AUTHORING, with the exact pinned anchor,
   Graph and policy. Its selected PAST_EXAM source must occur exactly once in the
   same official Evidence manifest and retain matching immutable Item/member/hash
   identity. Current source, Identity and late-byte checks stay mandatory.
5. Access patterns: exact plan/Workflow/QUERY lookup, bounded Evidence source
   membership and two local payload materializations for authoring/review only.
6. Structures: reuse immutable plan/delivery/anchor models, explicit supported-plan
   literal dispatch, existing Artifact/plan PK/unique constraints and one bounded
   source-membership pass. No DB table/index/queue/cache or numerical artifact copy.
7. Scale/complexity: existing plan1MiB, context512KiB, materials and Evidence bounds;
   one O(n) source-membership pass and O(1) selected lookup, with n already bounded
   by the Evidence contract. No extra embedding or corpus scan per review round.
8. Transactions: bind the successor before first plan persistence under the same
   workflow root. Exact replay returns the original plan; changed delivery conflicts
   without republishing. Artifact/source authority remains with existing owners.
9. Dependency: workflow owns pure schema/value associations; Orchestrator owns
   publication/staging; Catalog owns actual source/Identity/QUERY authorization.
   Runner invokes these ports. Workers gain no DB/NAS/tool/other-worker authority.
10. Failure/retry: missing/duplicate/foreign anchor, changed purpose, stale/revoked
    source or missing current reader fail explicitly before auxiliary disclosure.
    No-context legacy/general-knowledge paths retain their behavior. All primary/
    escalated/rework review attempts use the same immutable reference context;
    maximum-three-review and independent Evidence receipts remain unchanged.
11. Simpler alternative: widening plan23 would rewrite variation semantics;
    relabeling an old QUERY would falsify its purpose/hash. A small additive plan
    can share the real materializer without either shortcut. A future private-
    draft result must have its own actual origin/query, not this anchor's score.

The ordinary successor does not expose a new user toggle, auto-select a reference,
publish a new Pack, activate HTTP/Web, resume a held canary or run a model. Existing
Pack1.20.17 auxiliary-reference availability is reused only where its exact stored
plan declaration is checked. No-context/source-policy/default device changes.

### Implemented ordinary-reference boundary and current evidence

The new schema24.0 and exact packaged mirror have raw SHA
`21c49d6a0a7e2a46ef0eca5cb02e1d4ac5f4685d692f1b27b577a13c334f699b`.
Thirty existing plan fields reuse the predecessor's exact field schemas; only the
version, resolver and ordinary retrieval1.0 are selected explicitly, plus two small
delivery/reference pins. The predecessor schemas are byte-identical. No DDL, new
queue, WorkerRequest, role/result, Evidence receipt or numerical contract change.

The existing trusted item-preparation owner and API acceptance now handle the two
explicit modes: retrieval2.0 with PAST_EXAM_VARIATION/plan23, or retrieval1.0 with
ITEM_AUTHORING/plan24. ITEM_REVIEW is not silently relabeled as a fresh authoring
request. Each review attempt consumes the original ITEM_AUTHORING reference; a
future real private-draft query needs its own origin and result. Cross-purpose
input conflicts before publication or workspace disclosure.

The existing pointer-only publication RPC already selects an exact completed QUERY;
it contains no purpose/input text or authority supplied by a model. It reuses the
same operation/schema1.0 for a version1.1 QUERY, with independent current caller/
start-permission/source/producer/Artifact checks. The owner-local preparation and
plan consumer are extended; the old RPC bytes and strict QUERY1.0 stay unchanged.
Current role reads continue over the existing runner-only Catalog Unix operation.
The public HTTP reference-preparation route has not been activated for ordinary
authoring, and no automatic reference selection or Web feature activation occurs.

The actual local materializer stages official Evidence and two separate auxiliary
payloads, never fake variation intent/source files for an ordinary request. The
new ordinary staged instruction explicitly distinguishes this reference from the
new draft. Image/registration do not gain auxiliary access; Evidence-only allowlists
remain separate. Existing role escalation and maximum-three-review topology stay.

Current executed gates (overlapping inventories are not added):

- Guarded disposable PostgreSQL stage suite139 PASS/114.49s: includes seven new
  ordinary-purpose versions of original first-plan/START, exact replay, concurrent
  same-key/competing preparations, transaction rollback and DB immutability/FK
  tests. Real transactions/control Artifact bytes; source/IAM/worker seams remain
  explicitly synthetic. Independent before/after disposable identity/head0055 and
  zero-other-connection inspections PASS.
- Current affected contracts/materialization/role/owner/socket tests134 PASS/
  75.64s; final transport/owner subset99 PASS/69.36s. Final full relevant source
  regression1632 PASS/430.49s across80 files, including ordinary and variation
  role/socket consumers, first binding/replay, Evidence-only receipt boundaries,
  curriculum normalization, immutable schema packaging and bounded review rework.
  One existing Starlette/httpx deprecation warning remains. Real local Artifact
  reads/Unix sockets and these source tests are not installed-IAM/model acceptance.
- Strict mypy15 changed production modules PASS. Ruff/format checks pass at the
  final source checkpoint; all30 changed Python paths pass final Ruff/format.
- Pure comparison with Git baseline18942f0f: legacy plan23 canonical bytes and
  staged variation instructions identical. SHA values respectively
  `0bcaa5416a8c463c8cdb50a6972e541e3a4d6ac8eb9bee52873ea52f63d315b8`
  and `c315115b22f7212db8e9573b28a06f4a5995ac05762ffad7522b2c81b6caa23c`.
  This is development/test data comparison, not a runtime dependency on Git.

The first new tests exposed incomplete synthetic ordinary inputs (curriculum scope
and external clients incorrectly sending an internal graph root), missing offline
transitive schema resources, and assertions matching an error's message instead of
its stable code. The schema registry includes the exact required offline resources;
fixtures now obey the real curriculum/API normalization. No permission, schema,
error check or published historical row was weakened to accommodate a fixture.
Original failed invocation logs are retained under
`/tmp/eom-identity-provider-install.nAaycoDM/authoring-delivery-*`.

The broad source run also found a pre-existing stale resource-total assertion112:
the preceding committed registry already had116 resources; this successor adds
only plan24, giving117. The test now requires one-to-one equality with the actual
canonical schema-file inventory, plus every packaged mirror/hash and explicit
required-family names. Unregistered, missing or duplicated resources still fail;
the obsolete constant is not a functional admission rule. The earlier failed run
is retained, and the full relevant inventory is rerun after this correction.

**SOURCE_AND_DISPOSABLE_PASS / NOT_INSTALLED / NOT_ACTIVE.** Remaining gates must not be inferred
from the focused tests above. This advances ordinary reference delivery; private
brief/draft query semantics, actual HTTP/start/worker activation, chat/exam consumers
and physical CPU/CUDA comparison remain open in the original goal ledger.

### Ordinary delivery immutable candidate build

Source`15ffdef5697fd1ec0512c3c3dde9499caa49c46b` is committed/pushed.
Standard `scripts/api/deploy_release.sh --build-only` and three-wheel/RECORD
inspection PASS. Retained build:
`/tmp/eom-api-build/15ffdef5697fd1ec0512c3c3dde9499caa49c46b.J3TY7E`.

| Immutable build member | Raw SHA-256 |
| --- | --- |
| `source.tar` | `9618b67052a7115f0280be89e507cb042a816a6b6ec00f4a933fc8344a23c98c` |
| `eom_platform-0.1.0-py3-none-any.whl` | `63ad4147716e9d8f2970a4036f4c9c309e46e48565d060f90183f412af165050` |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `ba30b67ff904ac16ad64ed4dc6a58911d0bca9ae4c11279f393df9578640179d` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `bd8c7a9a2583a20a3ed8f85727538dc6597771dd3722dc06dedfacad9d222252` |

A separate unprivileged API-Conda `-I -B` process admitted only these platform/
contract archives, independently rechecked their hashes, imported all207 EOM
modules exclusively from those two wheels, loaded117 pinned packaged control
schemas and verified both strict plan families, exact reference/Evidence closure
and review escalation dispatch. Legacy plan/instruction bytes still match the
recorded hashes. No checkout/test module, ML import, DB/current-IAM/source lookup,
model or runtime activation was used in this process. Its only input was bounded
synthetic JSON produced separately from test constructors, raw SHA
`1e44fe234fc1946205b223402f823f6997d84560ce1d7fb48092ef18d2bcede4`.
This is source-free archive composition, not installed identity/permissions proof.

The first package probe correctly refused a checkout **test fixture's** transitive
API import; its failed log is preserved. Rather than allowing source/ambient/API
imports into the owner proof, fixture construction was separated into synthetic
JSON staging and the archive process validates those bytes/schema itself. No
production import/dependency/privilege was changed for that probe.
Evidence:`authoring-delivery-release-build.log`,
`authoring-delivery-owner-isolated-proof.log` and the retained original
`authoring-delivery-owner-archive-proof.log` failure, same evidence directory.

Final documentation/guidance/resource checks39 PASS/8.17s. No operating selection
was changed: INDEX2a4843c3/Identity13 continues, API2857bf77/QUERY8c411041 and
Web/Pack flags stay selected as before. Actual public ordinary preparation/start,
private-query bases and remaining original-goal gates are not inferred complete.

## Native preparation purpose successor — design before schema/behavior

1. Boundary: the existing authenticated HTTP→API client→fixed native owner still
   defaults every preparation to variation. Extend this exact path; do not create
   another owner, session cache, worker tool or queue.
2. Canonical source: an exact approved-reference revision and pinned Graph/policy;
   actual source/profile/index selection and current authority remain Catalog-owned.
   No private brief/draft/chat text is accepted or compared by this operation.
3. Identity: add closed input-only system-rag-reference-query-prepare-request1.1
   carrying explicit ITEM_AUTHORING or ITEM_REVIEW. Keep implicit-variation input1.0
   and its strict parser/bytes. Reply1.0 and native execution protocol remain valid:
   the exact request hash already binds the extra purpose/version.
4. Pointers: retain operation/source revision/Graph/policy/hash fields and limits.
   A purpose is intent, not caller identity, source access, execution authority or
   a replacement for the operator-session capture challenge.
5. Access: exact original-key lookup, one captured current caller, current source
   and immutable-index checks, canonical START/replay and bounded result inspection.
6. Structures: explicit two-version schema/model/parser family and discriminated
   HTTP input; existing native admission/claim/checkpoint/driver. No new DB schema,
   registry, queue, cache or numerical member.
7. Complexity: unchanged8192-byte request/4096-byte reply budgets, three views,
   top8/maximum1024 sources. Purpose dispatch is O(1); no extra corpus/model scan.
8. Concurrency: retain existing actual-operator/original-key identity unchanged.
   Do not add purpose/version to that key: a changed purpose must conflict against
   original work, not spawn a second job. Preserve root/claim/lease/replay behavior.
9. Ownership: Catalog contracts own closed messages; API handles presentation;
   native owner uses genuine current Identity capture and official Catalog ports.
   Workers never receive a session, authority override, DB/NAS or caller path.
10. Failure: unknown versions/purposes, same-key purpose drift, malformed raw values,
    expired capture, denied/revoked source and foreign reply hashes fail explicitly.
    Known missing report/index is UNAVAILABLE, not denial or an automatic retry.
    PENDING retains the original durable job/key; timeout never creates a new key.
11. Alternative: changing the default for old1.0 reinterprets history; inferring a
    purpose from a client name/key is ambiguous. An input-only successor lets the
    already implemented native request1.1/plan24 path receive its actual intent.

No runtime/flag/Pack selection or model execution belongs to this source step.
Official-Evidence automatic reference selection and ordinary Item-start routing
remain the next consumer step; this does not pretend that the public route alone
selects a reference or implements a private-query origin.

### Preparation-purpose source and disposable evidence

At2026-10-16 04:34 UTC, the affected source regression across84 files passed
1729 tests/444.49s (one existing Starlette/httpx deprecation warning). After the
last annotation-only simplification of the supported-request type alias, the
final exact HTTP/native/contracts/Unix subset passed110/19.98s, strict mypy9
production modules passed, and the final guarded disposable PostgreSQL stage
suite passed152/138.65s. The independent adjacent API/start/release inventory
passed41/8.50s. These inventories overlap and are not added together.

The PG cases use actual transactions, unique native START identity and unchanged
immutable initial requests; identity/source/executor seams remain synthetic.
They cover three offered purposes, first/replay/concurrent preparation and changed
source/Graph/policy/purpose under the same key. Purpose drift fails explicitly,
without recapturing authority, relabeling history or creating replacement work.
Before/after disposable inspection passed exact database identity, migration
head20261014_0055 and zero other connections. No operating database was tested.

New canonical/packaged input1.1 raw SHA-256 is
`d6a9e8f99ecd8173497d6283f8a8f58e9124a1890cee00fed795b2fc86d8cb0f`.
Original input1.0 remains byte-identical at
`ebc804f035eae57c9b4a649316cd63471203218ecb04603454eb08f2bfa15720`.
Ruff/format pass on all15 changed Python paths. No new dependency, DB migration,
runtime activation, model execution or current-IAM acceptance is implied.

Original contract RED and all subsequent evidence remain under
`/tmp/eom-identity-provider-install.nAaycoDM/purpose-preparation-*`, including
`source-regression.log`, `focused-final.log`, `mypy-final.log`, `stage-final.log`
and `db-after-final.log`. **SOURCE_AND_DISPOSABLE_PASS / NOT_INSTALLED / NOT_ACTIVE.**

The first immutable build of source`a8238d7a` correctly refused the stale committed
OpenAPI snapshot after the new discriminated input. That failed build log is
preserved as `purpose-preparation-release-build.log`; no install/activation ran.
The existing official OpenAPI exporter regenerated the deterministic snapshot and
its SHA file. An explicit two-version request-body/discriminator test was added;
OpenAPI, HTTP preparation, release inventory and deployment-boundary tests passed
112/21.47s. This corrects release metadata, not runtime authority or protocol
semantics. A corrected immutable candidate must pass the standard build again.

### Purpose-preparation immutable candidate

Corrected source`8f7da6abd44064801991d0e27cd8dc761b86914c` is committed/pushed.
Standard build, all three wheel RECORDs and installed-wheel/current OpenAPI
equality PASS. Retained build:
`/tmp/eom-api-build/8f7da6abd44064801991d0e27cd8dc761b86914c.dtpdrn`.

| Immutable build member | Raw SHA-256 |
| --- | --- |
| `source.tar` | `2902e7e08ecbf0fa0c0c488a1a4830f22e768e618fdff3372554d0f28b8ad16a` |
| `eom_platform-0.1.0-py3-none-any.whl` | `c1a7c0687c29608c4ac43d2ca387920b3bbffde42b463ef5aebc8c27dc009395` |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `fceb1214dfc4769ed668a769b5719e6387aa0702d19b458f7efb248d28debd37` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `43990e96e567b7ef079cc52b48b4e3f80bb30bdb2ee32fbbb8e9293a32a70224` |

Separate unprivileged Conda `-I -B` baseline/candidate processes admitted only
their exact platform/contracts archives and imported297 EOM modules exclusively
from those wheels; checkout imports0. The candidate validated implicit PAV1.0,
explicit authoring/review1.1 and all bound reply states. Original canonical frame
SHA`674238c6aa2efbebd2d873d72b8fac595d4e82836be80d570b2b6dc914799b85`
and actual-operator/original-key-derived identity match baseline15ffdef5 exactly.
No test/checkout/ML imports, current IAM/DB/source lookup, model or activation calls
were made. Bounded staged synthetic input and its original1e44fe23… hash remain
unchanged. This is package composition, not installed operator/source permission.

Evidence: `purpose-preparation-baseline-wheel.log`,
`purpose-preparation-candidate-wheel.log`,
`purpose-preparation-release-build-corrected.log`, same evidence directory.
An initial command supplied an incorrectly truncated expected synthetic-input
hash and failed before any EOM import; the refusal is retained separately and the
expected full input hash was corrected, not a validation rule or input byte.
No selected API/QUERY/INDEX/Pack/Web configuration changed.

## Official Evidence reference selection — design before implementation

1. Responsibility: ordinary authoring chooses an optional approved reference from
   its own already-published official Evidence5. Never run a parallel lexical/vector
   search or label an unrelated Item as a member of that Evidence.
2. Canonical source: the pinned publication, original retrieval request, immutable
   Evidence manifest/context and current official Catalog source/profile reader.
   Neither a browser's Item ID nor a model's proposed authority selects the anchor.
3. Revision model: retain Evidence logical/revision, original retrieval and Graph/
   policy/result hashes. Add only a closed pointer-only SELECT_ITEM_AUTHORING_REFERENCE
   read operation on the existing API-only Catalog socket, with no publication,
   queue, registry, DB schema, Workflow definition or native execution change.
4. Pointer closure: verify the original publication against its canonical DB rows,
   requester, Artifact lifecycle/schema/media/raw hashes and exact manifest fields.
   Return evidence ID, source Item revision/content hash and accepted report pointer
   hash, not Item/report bytes. QUERY still resolves the same source independently.
5. Access: current actual API actor and current Catalog Identity/permissions first;
   the released pinned policy and original Graph are reauthorized, not broadened.
   API-only peer remains required. Chat/worker/runner peers cannot select for Item start.
6. Selection: only non-answer-bearing PAST_EXAM/ITEM_REVISION/REFERENCE_PATTERN
   entries with accepted solution evidence are eligible. Use original manifest
   relevance order, choose the first eligible immutable source revision, then validate
   its source/report equality through one existing selected-source read. No random/latest
   source or private-brief/draft vector comparison is invented.
7. Access patterns: bounded primary-key metadata reads, one bounded manifest/context
   materialization, at most128 manifest entries and only one source ID; dict/set
   joins and stable original order, O(n) manifest traversal, O(1) source materialization,
   existing PK/FK/unique indexes. No unused Item bytes or N+1 source read.
8. Transactions: use one Catalog-owned current root, read/shared locks as existing
   authority requires; the root closes normally, with no domain/Artifact write or
   commit, new idempotency record or future permission cache.
   Immutable selection is reproducible. Native preparation keeps the original
   actual-operator/key and rejects changed purpose/source, so replay cannot re-key.
9. Ownership: contracts own messages; Catalog owns resolution/selection; the API
   gets pointers through its existing peer adapter and invokes preparation1.1.
   The current API/QUERY/INDEX release selection remains unchanged in source work.
10. Failures: missing/corrupt/stale/foreign requester/denied/revoked is FAILED with
    no partial selection or retry. Legitimately no eligible reference is explicit
    UNAVAILABLE/REFERENCE_NOT_OFFERED after authorization, not a fabricated result
    or evidence receipt. Ordinary GraphRAG may continue only through a separately
    explicit optional-reference branch; denial is never converted to absence.
11. Simpler alternative: passing the first browser Item or doing another search is
    fewer lines but loses original Evidence provenance. Repeating full corpus
    retrieval copies work and can select different material. This one existing-
    socket read keeps source ownership and leaves native numerical work unchanged.

This is an implementation boundary, not activation approval or proof that ordinary
Item-start routing, private-query semantics or remaining goal consumers are complete.

### Official reference selector source checkpoint

The closed selector schema, typed request/reply, current Catalog selection, exact
original Evidence read, existing API-only socket dispatch and API peer client are
implemented. The Catalog server composes this read-only operation only when its
existing compatible similarity read owner is present. No additional runtime owner,
queue, DB schema, model, generic search framework or public authority field exists.
The ordinary Item-start caller/optional-reference branch is not connected yet.

Canonical/packaged selector raw SHA-256:
`fc2bee449016d3fb3de84be22b6a22f1cee55aa88aa2f79f085b661d2a4e9215`.
At04:50 UTC, final focused/source/actual-Unix/adjacent Catalog/resource tests151
PASS/22.94s, strict mypy6 production modules PASS, Ruff/format9 paths PASS. Original
Evidence metadata/source/IAM/current report observations in these cases are
synthetic, not PostgreSQL/current-user/NAS/model acceptance. The actual socket peer,
frame limits, raw closed models and no-retry behavior are exercised. Positive,
empty-offer and late-denial owner tests preserve one root and one batch read;
even empty results reauthorize after IO. Malformed/hidden fields, foreign actor/
request/Graph/context, duplicate or mismatched source/report, answer-bearing or
nonreference entry, denied peer and source error cannot yield a partial selection.

Initial fixture failures used noncanonical `+00:00` timestamps, inconsistent changed
profile/content metadata and a plain Mock as a context manager. Fixtures now obey
canonical `Z`, exact source/report closure and the context-manager protocol; no
production validator was relaxed. Original logs are retained under
`/tmp/eom-identity-provider-install.nAaycoDM/authoring-reference-selection-*`.

No install/activation or operating data mutation is part of this checkpoint.

Final review narrowed source materialization to the single highest-ranked eligible
original reference before calling the existing source owner. Up to128 manifest
entries still undergo bounded identity/schema validation, but unused Item/report
bytes are never loaded. This is an obvious O(n)-to-O(1) source-materialization
improvement, not a measured latency claim. A denied/stale selected reference still
fails; the selector does not quietly fall through to another source. The final
selector/real-socket46 tests and strict mypy6 PASS after this change. The earlier
e7b6bef4 standard three-wheel/RECORD/OpenAPI build passed; it remains a retained
intermediate candidate, not the corrected single-source candidate or activation.

### Next caller integration, not implemented by the selector checkpoint

The existing opt-in reference-start operation can add an ordinary retrieval1.0
branch without reinterpreting accepted variation2.0 requests. It must keep actual
actor capture, fresh WORKFLOW_START, full-request idempotency claim and domain replay
first. The ordinary adapter should call this exact official-Evidence selector,
then preparation1.1/ITEM_AUTHORING with the same original domain key, and hand a
READY result to the existing checked plan24 preparation. Pending must still create
no authoring Workflow/plan/START. Denial/failure never becomes optional absence.

A legitimate no-reference result requires an explicit typed NOT_OFFERED outcome,
an append-only audit targeting the original Evidence revision, and the existing
ordinary Evidence-only plan path. It must not invent a QUERY/context/receipt or
block a valid ordinary request merely because no optional pattern was offered.
The existing variation branch must remain mandatory/exact and byte-identical.
This caller branch, UI routing, current-auth HTTP/worker acceptance and activation
are still required; the selector or an unprivileged package proof cannot close them.

### Single-source selector immutable candidate evidence

Source`3fa9b958eefb8dd65516480b58881bc86dc9732a` is committed/pushed. Final affected
source/Unix/Catalog/resource/guidance checks179 PASS/23.40s and strict mypy6 PASS;
Ruff/format9 production/test paths PASS. Standard three-wheel build/RECORD and
installed OpenAPI equality PASS. Retained build:
`/tmp/eom-api-build/3fa9b958eefb8dd65516480b58881bc86dc9732a.OM3pZZ`.

| Immutable build member | Raw SHA-256 |
| --- | --- |
| `source.tar` | `1738a1dbf5302ba2bda3b845460a63524930274cc5c025c42b8a664e7bfeeb64` |
| `eom_platform-0.1.0-py3-none-any.whl` | `0d262f3cca08efc67ef1dc292ea3d7d49ec536e41e3b230a1bf51e6bda0dadbf` |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `c2ec2e7f34a538c96431cee5c577d393f3c14a34105ce458d9b5666fc727497d` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `5c0384b3d980405fa94694391b3740722c154cb215d8aaf49ddfebfbc1397339` |

Separate unprivileged Conda `-I -B` proof admits exactly the platform/contracts
archives above, verifies their raw hashes, loads301 EOM modules only from those
archives and validates Evidence5/selector request/selected-unavailable-failed reply
composition. A missing owner fails closed. Predecessor preparation1.0 wire/native
key and1.1 authoring/review behavior are preserved. No checkout/test module, ML,
database/current-IAM/source read, queue submission or activation occurs. The same
bounded synthetic1e44fe23… staged input is independently hash-checked; its synthetic
publication pointers are never materialized or presented as real accepted sources.
Log:`authoring-reference-selection-wheel-proof.log`, same evidence directory.

The broad87-file regression was started before the last single-source refinement;
its result is separate from the exact final179 tests. Neither is operating/current
source authorization or a fresh disposable-PG acceptance of the new Evidence read.
Those and the remaining caller/activation gates stay explicit rather than inheriting
the preceding preparation-only PG152 result.

The broad87-file run subsequently finished1782 PASS/446.84s, with one existing
Starlette/httpx deprecation warning. It imported the pre-refinement selector and
fixtures before the single-source change; the separate final179 tests/type6/
package301-module proof cover the exact3fa9b958 candidate. Inventories overlap and
are not added. Final documentation checks28 PASS/3.85s. The original full goal is
still ACTIVE; no selected service, human session, native key, Pack or model default
was changed by these source/package checks.

## Ordinary reference-start caller — design before implementation

1. Boundary: reuse the existing opt-in reference-start application/HTTP endpoint,
   domain command adapter and Web gateway. Admit the already-schema-defined ordinary
   retrieval1.0 input for generic-item-development1.16; preserve exact variation2.0.
   No released JSON Schema bytes, reply1.0 shape, worker protocol or queue changes.
2. Canonical source: the original CREATE_ITEM_PRODUCTION_EVIDENCE result5 and the
   Catalog selector; no client Item ID, second search, private brief vector query,
   mutable latest or role supplied by a model.
3. Identity/pointers: preserve the actual API caller/capture, original full-request
   idempotency key and pinned controls/Evidence. The ordinary native preparation1.1
   declares ITEM_AUTHORING. Same key/purpose/source conflicts cannot create new work.
4. Exact closure: before accepting READY, compare the checked plan's source revision,
   original content SHA and solution-pointer SHA with the Catalog-selected pins.
   A race changing the report/source between selector and QUERY is an explicit error,
   not permission to accept unrelated or newer evidence.
5. Optional absence: only selector REFERENCE_NOT_OFFERED and native initial
   UNAVAILABLE/INDEX_NOT_PREPARED may use an explicit small frozen no-offer value.
   ANCHOR_REPORT_MISSING contradicts the just-selected accepted report and must fail;
   permission/source/hash/failure/timeout/PENDING never become absence.
   Ordinary requests that do not request PAST_EXAM also take the explicit no-offer
   branch after shared control/Evidence validation, without widening source classes
   or contacting an irrelevant selector. Ready reference preparation remains strict
   about the PAST_EXAM class; the shared control validator serves both real paths.
6. History: the no-offer value binds exact Workflow-request and Evidence-result hashes.
   The existing application audit records reason and original Evidence revision;
   then the existing Evidence-only plan path runs, with no fabricated QUERY/context/
   vector/receipt. Domain replay precedes selection and does not upgrade old work
   after an index becomes available.
7. Access patterns/scale: O(1) request/key/hash lookups and at most one selector and
   one preparation exchange per current API attempt; existing bounded Catalog reads.
   No DB/index/cache schema or generic framework. Long source bytes remain owner-local.
8. Transactions/concurrency: keep existing API claim/defer/complete and atomic Item/
   first-plan/START root. PENDING creates no Item work. A late pin mismatch can occur
   after independent context Artifact publication; preserve that output, never claim
   no side effect or auto-retry with a new identity.
9. Dependencies: API application ports own the optional selector/read adapter and
   no-offer value; Catalog client implements the port. Shared checked-start code owns
   no-offer scope validation. Production composition supplies existing audit; no DB/
   NAS/native owner is constructed by the API or browser.
10. Presentation/activation: the existing disabled Web flag may route ordinary
    generic1.16 retrieval1.0 to this same endpoint; older/default flows stay unchanged.
    Missing compatible backend is not an automatic fallback. No flag/Pack/runtime
    activation occurs in source work. Maximum-three-pass and Evidence-only receipts
    remain unchanged; every review still reuses the original reference.
11. Alternative: silently returning None loses the reason/pins and can hide denial;
    rejecting all missing optional vectors breaks normal GraphRAG; a second start
    implementation duplicates transaction/idempotency. The typed branch reuses the
    existing owner and explicitly distinguishes absence, pending and failure.

### Ordinary caller source/disposable checkpoint

At2026-10-16 05:18 UTC, final focused HTTP/caller/Unix/publisher/first-plan/absence/
legacy/Web checks112 PASS/33.27s; strict mypy8 production modules and Ruff/format13
paths PASS. Web pending/browser/default-resolution42 PASS/5.31s is overlapping
evidence, not an additional aggregate total. Full related91-file regression is
running separately. No wire-schema bytes, worker prompt, model, DB schema or selected
runtime/Pack/feature flag has changed.

Final supported disposable `embedding-stage-tests`162 PASS/141.04s, with independent
before/after database marker/identity/head20261014_0055/zero-other-connection guards.
Ten new PG cases cover exact ordinary-only absence, wrong request/Evidence/reason,
unchanged mandatory variation, first normal plan19, same-key concurrency/one plan/
one START, normal-plan replay without reselecting/upgrading and source-class subset.
Earlier161-case run predates the final shared-controls/non-PAST branch and is retained
separately. Identity/source/Evidence/native completion seams are synthetic; actual
transactions/constraints/temporary Artifact writes are real, with no operating DB,
NAS, model or worker execution. This is not PG acceptance of the selector's current
original-Evidence read, nor a genuine current-user source/worker activation gate.

An actual source HTTP→real Catalog sockets→existing context publisher→atomic Item
start case verified PENDING creates no Item, READY stores the first plan24, and the
same accepted request replays without selector/QUERY calls. A first403 was a fixture
problem: the transport-only synthetic account had only WORKFLOW_START, not GraphRAG
access. The synthetic case now explicitly grants EDITOR retrieval/read capabilities
before its capture; production authorization, role policy, fresh-auth and TTL were
not weakened. Original failed log is retained. All evidence stages are under
`/tmp/eom-identity-provider-install.nAaycoDM/ordinary-reference-start-*`.

**SOURCE_AND_DISPOSABLE_PASS / NOT_INSTALLED / NOT_ACTIVE.** Private brief/draft
query bases, actual compatible activation/worker acceptance and the rest of the
original full-goal ledger remain open. Every review still receives the original
ITEM_AUTHORING reference, not a claim that its latest draft has been vector-compared.

### Ordinary caller immutable candidate and final regression

Candidate`f37ae7be9910e5acfd64e9cb0d3bc65e13c0c8ee` is committed/pushed. Exact final
related regression1856 PASS/464.77s across91 files (one existing Starlette/httpx
deprecation warning), focused112/PG162/type8/Ruff13 and documentation28/3.89s PASS.
These are overlapping inventories, not a combined execution count. Standard API
build/three wheel RECORDs/installed OpenAPI and independent Web build/target Web
Conda import/installed48-file simulation PASS; no operating installation ran.

Retained API build:
`/tmp/eom-api-build/f37ae7be9910e5acfd64e9cb0d3bc65e13c0c8ee.pMaLJ2`.
Retained Web build:
`/tmp/eom-web-gui-build/f37ae7be9910e5acfd64e9cb0d3bc65e13c0c8ee.uqZ4Ka`.

| Immutable build member | Raw SHA-256 |
| --- | --- |
| `source.tar` | `f27ba0c7ebf4ced45d448cb6597ef7421c7978d07df3f5df4b5850408c89926d` |
| `eom_platform-0.1.0-py3-none-any.whl` | `54df7e43de4c02ae1098952c9cfba6627f9f923bb361b579c0cd1dac8e2cfae4` |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `2e610638abbbed7225b6d62a577df0a7b0c6bf3d8801fd7bd1be1d423e835f74` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `dfdce95964a9813e40ad61e9c556024e6a0585a3ac1d3e9a6604e79329eae3c1` |
| `eom_web_gui-0.1.0-py3-none-any.whl` | `44517a1bcc3c01ee7b1732743fb178796a8c0abe6db83eaa822603382d868b5f` |

The separate unprivileged Conda `-I -B` two-wheel proof loaded301 EOM modules only
from the exact platform/contracts archives above, preserving the old canonical
preparation1.0 frame SHA`674238c6aa2efbebd2d873d72b8fac595d4e82836be80d570b2b6dc914799b85`
and original native identity, plus explicit1.1 and selector/Evidence5 schema and
fail-closed composition. It makes no checkout/test/ML/DB/current-IAM/source/native
or activation call. It proves this shared foundation, not the API caller's runtime
authority; that caller is covered by the stated source HTTP/Unix tests and standard
installed-wheel build, with genuine activation still pending.

Evidence: `ordinary-reference-start-regression.log`, `focused-final.log`,
`stage-final.log`, `db-before-final.log`, `db-after-final.log`, `mypy-final.log`,
`release-build.log`, `web-build.log`, `wheel-proof.log`, `docs-final.log` under the
same stated prefix. No selected API/QUERY/INDEX/Pack/Web flag changed. Original
human canary process1079683 remained alive waiting on its original getpass at
05:26 UTC; no new login/key/process was created or credential stored.

## Original Evidence persistence verification boundary

The additional opt-in `test_authoring_evidence_persistence.py` is included in the
existing guarded `embedding-stage-tests` purpose, before any runtime credential
environment. It introduces no new mode, queue, schema, dependency or production
behavior. The original service actually publishes V5 context/manifest file sets
through its existing Artifact owner and commits its request/bundle/revision/entry
relations in disposable PostgreSQL. Independent reads use real READ ONLY roots
and actual pinned file/hash/provenance resolution, not mocked publication rows.

Scientific source/report admission and ranking remain explicit synthetic seams;
the synthetic Graph fixture is not accepted scientific evidence or current-user
authorization. These checks cannot close the held genuine HTTP gate. They test
publication/replay/creation timestamps, exact identities/permission fingerprints,
foreign-actor rejection, corrupted/missing members, foreign-root reader rejection
and absence of new Jobs/Artifacts/Evidence during read or replay. Source rows and
their accepted report semantics are still reauthorized by the existing Catalog
owner before/after that reader.

The first run stopped at the synthetic policy fixture: changing its allowed role
without its answer-bearing role correctly failed the existing subset invariant.
The fixture now uses its original EDITOR policy without any policy/validator or
production-role change. Original failure evidence is retained. A separate old
test expected a pre-existing shorter CLI mode inventory; comparison with the
unchanged committed runner confirmed both `inspect` and
`local-indexing-service-tests` already existed. The exact expected set now names
them, plus a new assertion that this persistence file remains in the owner-only
guarded stage branch and never sources `runtime.env`.

The corrected fixture then reproduced a real source-candidate defect: the reader
called `read_pinned` before `PinnedArtifactReadContext.prefetch`, which a mocked
reader did not detect. Its original13-case run had174 PASS/1 FAIL. The production
reader now prefetches just the two exact manifest/context Artifact pairs using
the existing batched metadata reader, after matching original owner/publication
metadata and before reading either payload. No source/policy validation, hash or
file check is skipped; no permission, new cache or latest fallback is added.
The corrected guarded suite175 PASS/142.86s includes all13 added cases. This is
actual disposable DB/Artifact proof, not genuine source/IAM or a deployed fix.

## Genuine HTTP gate observation — 2026-10-16 05:37 UTC

The original canary successfully logged in at05:37:55 UTC after the user's input.
Its unchanged key`goal-http-reference-query-20261015-01`, operation
`queryprepare_a2c36b2744284b65971b6025f7356432` and pinned request hash
`sha256:258c0567f807fb1e4c43b4107809acb7dec5a37add2c7c06082c2b26e3e0ae3f`
are preserved under`/tmp/eom-query-http-canary-8oxU2rnJ`. The original preparation
returned FAILED/AUTHORITY_UNAVAILABLE at05:37:59 UTC, workflow_id=null. The script
exited without an automatic login retry, replacement key or model launch; it is
no longer waiting at its former getpass. Credential material was not persisted.
This is a failed genuine gate, not a source fixture failure or accepted QUERY.

Independent root-owned/hash-pinned metadata-only probes of the installed8c411041
owner at05:41:19 and05:43:13 UTC found the configured eom_app OID16385 matched,
READ COMMITTED/app+pg_catalog/no temp schema/no superuser or bypass/autocommit,
and all three IAM locking targets readable/lockable. The guiadmin operator was
ACTIVE, not deleted or required to change password, with an unexpired recent
session and actual workflow:start plus knowledge_graph:retrieve permissions.
The probes minted no capture, read no source content or printed credential bytes,
and performed no DB writes or launches. They validate the native controller
connection, **not the service's inherited credential selection**. The actual
service EnvironmentFile was independently reproduced under UID990 at05:50:54:
it selects eom_catalog_manager_runtime/OID94661, not pinned eom_app/OID16385,
and cannot lock the three IAM targets. This explains the failed Identity context.
No authority was loosened. [Scoped correction and startup guard](REFERENCE_QUERY_OWNER_SERVICE_DESIGN.md#correct-controller-credential-selection--2026-10-16).

The preparation owner now emits a content-free rejection boundary, plus only the
closed five-code Identity reason when that boundary throws its known exception.
Unrecognized reasons become UNCLASSIFIED. No capture, traceback, SQL, arbitrary
exception body, prompt, content or token is logged; public failure/retry meaning
is unchanged. This diagnostic candidate is not yet installed/selected. Genuine
failure remains open pending the reviewed credential-selection correction and
same-request continuation. The separately installed62198a23 owner pair is inactive;
its original template still selects the old environment. Do not activate that
prefix as if it includes the later startup-role/template correction.

Execution evidence prefix:
`/tmp/eom-identity-provider-install.nAaycoDM/authoring-evidence-`.
