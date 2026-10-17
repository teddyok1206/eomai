# Private Chat QUERY publication boundary

2026-10-17 UTC. Implementation design, not runtime activation or source authority.
Follows [owned-question execution intent](PRIVATE_CHAT_SIMILARITY_QUERY_BASIS.md).

1. Responsibility: extend the existing Orchestrator `EmbeddingArtifactStore` for
   the distinct private QUERY. Only its existing ControlFileSetPublisher commits
   artifacts. No worker, Catalog or API writes to NAS; no second storage framework.
2. Canonical source: the original owned message Artifact remains the only canonical
   question text. Native `input.json` is a temporary workspace input. Do **not**
   publish another copy of its private text. Publish a pointer-only `intent.json`,
   validated result, shard and float32 binary instead.
3. Identity: new closed private launch-association and execution-record contracts
   bind exact Workflow/step/command, original logical native Job, context, private
   basis, runtime, recipe and hashes. Artifact producer Job is a separate identity.
   Earlier execution-intent and approved-reference schema bytes stay unchanged.
4. Pointers: intent carries the original message pointer via the existing basis,
   full immutable execution intent and launch association. Native input can be
   reconstructed only through the owned-message resolver and checked against the
   recorded native request/input hashes. A stored vector is never an ownership grant.
5. Access patterns: exact original native/intent/launch identity, four ordered
   file-set members and indexed idempotent publication. No corpus or history scan.
6. Structures: frozen records and the existing Artifact manifest/Job machinery.
   No new DB table/index/queue/cache or public source binding. Private result type
   is distinct and cannot enter the existing approved-reference/index read path.
7. Complexity: bounded metadata/question validation and one 1-row float32 vector;
   O(metadata bytes + dimension). Question text is read only at the local input
   validation boundary and is not placed into PostgreSQL or the new file set.
8. Concurrency: reuse the existing publisher's original-key lock, commit/replay,
   preselected identities and immutable timestamp. Keep local no-follow FDs and
   file epochs across commit. Uncertain/late failures preserve committed evidence;
   they do not authorize a second model execution or new key.
9. Dependencies: pure workflow values own closure; Orchestrator owns workspace
   validation/publication. Reuse its existing file and publisher receipt checks.
   No infrastructure import enters workflow/contracts and no new dependency is added.
10. Failure: changed question/basis/control/native/result/binary/hash, foreign
    producer identity, symlink/hardlink/unsafe permissions, duplicate JSON and
    malformed publisher receipt fail explicitly. Known content errors use stable
    codes without serializing private text. A validated launch record is supplied
    provenance only, not actual execution/current-session admission.
11. Alternative: copying native input into NAS duplicates the owned question and
    adds an unnecessary private copy. Reusing a reference result misstates its
    source. A small private execution record preserves reconstruction/lineage
    using the existing owner without either problem.

Tests must cover local input/result/binary closure, exact replay/key stability,
publication identity/timestamp and malformed returns, source/path substitution,
absence of question text in the committed members and predecessor rejection.
Actual DB publication/concurrency tests require the existing guarded disposable
PostgreSQL route; unit fake publishers are not persistence/authority evidence.

This does not admit a new Runner result, alter its CHECK/migration, launch a unit,
authorize a private source, publish a public index binding or expose a Chat tool.
Current user/session/owned-message authorization is still required immediately
before execution/publication and again before result delivery by the eventual
private owner. Missing admission must remain unavailable, not bypassed by this store.

Private publication requires a preallocated producer identity and an observed
result hash. This is a concrete native-launch/producer separation, not a rule that
every two logical identity concepts must always contain different identifier bytes.
The predecessor reference path with publisher-allocated identity keeps its existing
behavior. Both paths share commit/receipt validation, not source or execution grants.

## Source and execution checkpoint

Implemented the distinct launch/execution-record resource (raw
`0e1282a4f912a4aaa25cb7cb4062179742a5d8165a875c3b17d101547eaacf0a`)
and `EmbeddingArtifactStore.publish_private_chat_query`. The supplied native input
is checked locally but absent from the committed four-member file set. Both QUERY
families share the existing publisher/receipt checks; their result schemas, keys,
Artifact types and source/admission meanings stay distinct.

Related source regression895 PASS/59.31s across22 suites; strict mypy4 production
modules, Ruff/format7 paths and shell/diff checks PASS. The first broad run had
894 PASS/1 failure in the store's explicit import inventory. The final store uses
existing protocol identifier validators, not a new dependency on the DB-owning
control service. Only three named pure private contract modules were added to
the unchanged no-DB/network/process/Git import/call guard.

First guarded disposable PostgreSQL run47 PASS, including four new private
publication/replay/concurrency/late-commit cases, and cleanup PASS. The subsequent
dependency correction is covered by the final source regression above; a separate
47-case disposable revalidation of those exact final bytes is running and is not
inferred from the earlier run. No model, operating DB/service, source authority,
private query admission, Chat tool or runtime/default activation was used.

First proof: `/opt/eom/embedding-benchmark-os-evidence/private-query-Yh9bNn4J`.
The original marked DB and its dedicated roles were removed; source/log evidence
is retained. The current final gate uses20 exact source pins, a fresh marked
database and the existing `embedding-tests` purpose, not a new test/queue framework.

### Final source-candidate verification

Candidate `b8c1f4aad445aaf7fb9dfe2832cd70a07b8ceb8c` is committed/pushed.
The separate final20-pin disposable run also completed **47 PASS / cleanup PASS**,
including all four new private cases. The exact final production source was
unchanged through preparation, migration/reconciliation, tests, inspection and
cleanup. Final protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-query-final-iFAgy711`;
operator raw `f1800492abb5e68388233377a6f885bcbb6b74f00139bc283d0fc52571ad04a7`;
test stdout raw `cb2f15d7f325e9e95e57ea70b5407544025835b400787177346d32e8958f49f7`.
The first47 result is retained separately, not added to this test count. Both
disposable databases/roles were removed; no operating DB or original history changed.

Standard three-wheel build/RECORD passed. Dist:
`/tmp/eom-api-build/b8c1f4aad445aaf7fb9dfe2832cd70a07b8ceb8c.FijGgA/dist`.
Raw platform `a3b2ce099c5b73f8f60afa590d08f4672c1a4ecd2a54f975a7d6087d7a6c07a2`;
contracts `538d23031cdb04e3e589bf920def34ddd6686fa888fb0e1c56d3dc28f3f2d885`;
API `8cf707550f9ff6e78d4550e0d09366de1dd27397d79757408fae298836fb85b6`.

Separate unprivileged Conda `-I -S -B` archive proof imported163 EOM modules
exclusively from the exact platform/contracts wheels, with source/test/optional-ML
imports0. It exercised text-free private publication and the unchanged shared
reference closure using a clearly synthetic publisher; actual DB/NAS/model/
activation calls0. Synthetic input was staged separately, raw
`f064b020f063c70a2ed9adeae81c4700880de134d1ab9b01dce592b10885f205`.
Proof programs/materialization remain under `/tmp/eom-private-query-publication.Yh9bNn4J`.
The real transaction/concurrency evidence is the guarded47 suite, not this fake publisher.

Status: **SOURCE_PASS / DISPOSABLE_DB_PASS / NOT_INSTALLED / NOT_ACTIVE /
C4_NOT_ACCEPTED**. Actual private numerical admission, current owned-work/authority
composition, result delivery and Chat tool activation remain required. The full
goal also still requires remaining consumer/live gates and actual CPU/CUDA
comparison/default selection. No original HTTP request/process/key, protected
runtime, active service, source policy or device default was replaced for this work.
