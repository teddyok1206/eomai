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

Plan23 and its item-specific publisher currently require exact variation lineage.
Do not relax those guards or claim ordinary authoring/review workspace activation
from this shared read foundation. Their actual consumer preparation/delivery and
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

**SOURCE_AND_DISPOSABLE_PASS / NOT_INSTALLED / NOT_ACTIVE.** Ordinary authoring/
review plan preparation/delivery and private intent/result search still remain.
Plan23/publication stay variation-only; no old plan/Pack/request is upgraded.
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
