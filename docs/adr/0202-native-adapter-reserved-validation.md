# ADR 0202: Native-adapter reserved validation without a parallel evaluator

## Status

Consumer source-verified, 2026-10-05 UTC; **lab installation and live reserved
comparison pending**. Canonical metadata preflight and own inspection of thirteen
eligible sources are complete. The earlier schema-only checkpoint below is historical.
This decision does not authorize activation or reinterpret historical acceptance.

## Verified need

The native44 pilot and reference1.2 comparison succeeded, but three TRAIN examples
did not establish LoRA superiority. Existing reserved comparison1.0 accepts only
reference1.0 and loads its historical reviewed-micro adapter. Merely replacing an
input filename could therefore test the wrong adapter while reporting success.

Fresh readmission of native44's complete37-member training-source closure and the
old fourteen-case reserved command proves thirteen retained cases disjoint from
the actual44 training targets: selection, document, original-PDF SHA and exam-group
intersections all zero. Thirteen cases span six original PDFs/six exam groups.
The historical wheat-seedling remnant hold remains excluded; old reviews/results
are not rewritten. All thirteen source PNGs were inspected in three contact sheets.

Some sources are only48x99 or57x75 at144DPI. The matched comparison can diagnose
relative behavior on these inputs, not certify high-resolution print quality.
Four-family coverage is still missing (the predecessor has three families), and
these are previously used VALIDATION sources, not untouched HOLDOUT examples.

## Required design procedure

1. Responsibility: extend the existing reserved comparison contract/admission,
   staging, paired worker and publication owner. No second queue, worker or renderer.
2. Canonical source: approved original-page review/crop revisions and frozen split,
   reference1.2 configuration, native1.1 training/result/manifest and full source
   metadata closure. Paths remain locations, not identities; no implicit latest.
3. Identity: proposed reserved command/result1.1 pins reference1.2 exclusively.
   Existing1.0 schema bytes and behavior remain unchanged. A changed command creates
   a new logical run and immutable result/adapter pointers, never a rewritten receipt.
4. Resolution: validate permission/lifecycle/existence, exact member/media/schema,
   canonical bytes/SHA and complete native source closure before any PNG/weight/model
   read. New result must bind the exact native evaluation and adapter-manifest semantic
   hashes; reject crossed legacy/native families even after rehashing.
5. Access: bounded metadata traversal, indexed pointer resolution, ordered case
   iteration, membership/deduplication and immutable output manifests. No whole-item
   blobs, binary DB values, repeated source hashing or repeated list membership.
6. Structures/scale: reuse native metadata admission and immutable source DTOs;
   a small typed training-authority value derived from canonical regions supplies
   sample/document/PDF/group sets and authorization/basis pins. Maps/sets give
   O(metadata bytes + TRAIN targets + VALIDATION cases), bounded12–16 cases/32 outputs.
   Existing DB/index/queue/storage layout and dependencies need no change.
7. Transaction/concurrency: existing Orchestrator staging and artifact owner,
   physical GPU lease and command/result idempotency. One shared selected-adapter
   rule supplies both staging hashes and worker material; do not duplicate adapter
   selection into unrelated adapters. Record staging before submitting one unit.
8. Dependencies: contracts own version/provenance/leakage rules; Orchestrator owns
   canonical reads and commit; provider owns staged filesystem and paired inference.
   Workers have no NAS/DB/repository access and never communicate directly.
9. Failure: missing/corrupt/denied native metadata, mismatched authorization/basis,
   TRAIN/HOLDOUT cases or collision with native-only training documents/PDFs/groups
   fail before binaries or GPU. Preserve failed prefixes; never substitute old weights.
10. Retry: same immutable command replays success or failure without models,
    transforms/GPU acquisition/writes. Unknown submission is queried by its same
    unit identity, not retried under another identity. Old exhausted budgets stay closed.
11. Simpler alternative: use reserved1.0 unchanged or relabel a TRAIN reference run
    as VALIDATION. Insufficient: the first reads the wrong adapter; the second lacks
    reserved source authority. A closed successor through current owners is smaller
    than a new general experiment framework.

## Compatibility and chronology

Use one closed command/result codec for legacy1.0 and successor1.1, not scattered
version-string tests. Legacy interpretation and predecessor hash fixtures remain
unchanged. Native configuration parsing uses the existing reference family parser,
including native1.1/result1.0/manifest1.0/evaluation1.4 validation. Staged native source
metadata keeps the existing hash-addressed paths and bounded total-size admission;
the numerical worker independently checks the same closure before reading pixels.

The old configuration's micro adapter is provenance, not the selected new adapter.
Leakage tests must include a document/PDF/group present only in the new native cohort;
checking the legacy micro cohort alone is insufficient. Keep authorization and common
original/supplemental basis comparisons explicit.

Already approved reserved sources may predate the new native configuration. Successor
chronology requires source review/crop completion before the new comparison and
native training completion before its pinned reference configuration, not a new crop
review after every model change. Preserve legacy1.0's chronology behavior. Do not
re-render or create replacement source revisions merely to satisfy a timestamp.

## Frozen initial comparison and evaluation meaning

Initial proposal: retain thirteen previously screened cases and exactly their
caption/negative prompt/source/seed104729 from the old reserved experiment; the
held wheat case is not restored. Existing 832x512 source initializer, final800x500,
strength0.35, Canny/controller/control policy, SDXL/VAE,30-step Euler grid, CFG7 and
LoRA strength1 stay fixed. Compare BASE versus native44 in one26-output dispatch,
within the existing32-output/ten-minute/16GiB bounds. Pre-register before execution;
no automatic prompt/seed/strength sweep or training retry.

Verify BASE raw/final hashes against the matching thirteen historical BASE outputs
when source/numerical runtime is identical. Record mismatches instead of quietly
accepting a drifting baseline. Pixel difference and training loss are not quality
scores. Score shape/count/pose/assembly preservation separately from unnecessary
detail, gray-block intent, stroke clarity and print usability. Do not erase deliberate
gray fill, source-native partial framing or appropriate human figures by default.

Native44 result quality stays NOT_REVIEWED until actual output inspection. Independent
blind review and the four-family gate cannot be claimed from Codex's own inspection.
Keep source leakage acceptance, numerical success, educational/visual quality,
Item Preview/HWPX canary and production activation as distinct gates.

Higher-resolution VALIDATION derivatives require explicit source-render contract
support later: the current native576DPI crop path is intentionally TRAIN-only. Do
not relax it, mislabel VALIDATION as TRAIN or touch HOLDOUT for an attractive sample.

## Implementation and required verification order

1. Add JSON Schema2020-12 successor command/result and predecessor hash regression.
2. Add frozen Pydantic models/closed codec, selected training authority/adapter and
   complete native metadata/leakage checks through existing contract owners.
3. Extend existing Orchestrator metadata/hash/staging and publisher; no DB migration.
4. Extend current command loader/worker/result publication/replay; unchanged numerics.
5. Test canonical hashing, family rejection, selected native adapter, native-only
   leakage, TRAIN/HOLDOUT, missing/stale/permission/corrupt pointers, budget/prefix,
   ordered outputs, metadata-before-binary, no-side-effect replay and install resources.
6. Formatter/linter/strict type checks/focused historical regression, immutable
   wheels/source-free imports/actual isolated role before bounded live dispatch.
7. Own and independent review evidence; no activation before the full quality gate.

No new dependency, unit, role privilege, migration, framework or production setting
is required. Steps1–5 and the source gates in step6 are implemented and verified;
immutable wheel/role installation, bounded live dispatch and step7 remain pending.

## Protocol-first source checkpoint

Four mirrored JSON Schema2020-12 resources add explicit command/result1.1. The
command accepts only reference1.2; the result requires both native evaluation and
adapter-manifest hashes. Pinned resource registration/hash maps are extended;
existing1.0 schema bytes remain identical. Successor command/resource SHA
`2b39462b79cfee2132f30650c36616dc8a8a0325e9359ed2fb5d092ba56aba35`;
result SHA `1767718eff8c436cfca616d6ae954b83b294785098e0ba5e4f1196b725757669`.

New schema13 tests plus existing reserved contract/worker regression61 tests =74
PASS. Coverage: mirrored dialect/resource hashes and exact predecessor hashes;
native schema family, wrong reference versions, TRAIN/HOLDOUT rejection, case
bounds, mandatory lineage hashes and rejection by the unchanged legacy consumer.
Fixture pointers/hashes are synthetic: this is wire-shape evidence, not native
provenance/adapter selection acceptance. Strict mypy/Python3.11 on the touched
schema registry, Ruff/formatter on registry/test, and diff check PASS.

At this earlier checkpoint no Pydantic successor/worker, actual native validation
GPU run, install/resource release closure or new quality gate was claimed. The old
installed consumer still rejects the successor instead of silently using a micro
adapter until a compatible lab release is verified.

Canonical17-member text evidence is committed under source54b09912:
`artifact_e7406ada2aa94628b59bc4fe78397453` /
`rev_942b6e5c6a0541809fbfea32bdf04cb1`, primary `reports/own-review.md`, SHA
`6d9737f73be836dbaa6b861087f069613c6faeecb4773e60c04a76105365d0f5`;
all members re-resolved with typed hash checks. Source PNGs/PDFs/weights are not
duplicated. Slack milestone SENT200, `devreport_44f6689c5a4d4fa28bf6098ea01201c7`.

## Consumer source checkpoint

Closed command/result codecs now map1.0 to reference1.0 and1.1 to reference1.2.
One immutable selected-adapter value controls both Orchestrator staging and the
paired worker. Reference admission retains its already validated native metadata
closure, avoiding a second canonical-source traversal. Reserved staging adds only
the hash-addressed native metadata: no TRAIN target PNGs, PDFs or copied weights
outside the existing materialization boundary. The staged worker independently
admits that bounded closure before any reserved pixels or model read.

Native-only selection/document/PDF/group exclusion and shared authorization/basis
are checked; existing reviewed sources may precede the native configuration but
must precede their new comparison. Native result lineage hashes, exact family,
ordered output prefix and historical numerical/resource policies are preserved.
Command publication, result Artifact manifest and wheel resource checks follow
the same codec rather than rewriting predecessor meanings. No DB migration,
dependency, queue, service, privilege or production binding changes are introduced.

Focused regression:169 PASS in79.64 seconds across the new24 native consumer tests,
legacy reserved contract/worker, schema successor, native reference successor,
complete native source admission and test-environment boundary. The new tests use
a complete synthetic multi-batch native closure, not schema-only fake pointers.
They cover the selected native manifest/revision, metadata-first failure, native-only
leakage, staged tampering, lineage/family rejection, old-source chronology, paired
success/failure replay without transforms/models/GPU/writes, canonical-admission
reuse, publication CPU transform checks and absence of source/adapter duplication.
Canonical missing/stale/permission failures are injected at the existing resolver;
this does not replace its real RBAC/infrastructure acceptance.

Ruff, formatter and diff checks are required on the touched files. Strict mypy
passes seven changed core files with the explicit Python3.12 test interpreter and
the three contract/provider files under Python3.11. Initial fixture timestamp/hash
serialization and tuple-union typing failures were corrected before the final
focused run. No new native reserved GPU dispatch or quality acceptance is claimed.
Production activation, independent blind review, four-family coverage and the final
Item Preview/HWPX canary remain separate pending gates.
