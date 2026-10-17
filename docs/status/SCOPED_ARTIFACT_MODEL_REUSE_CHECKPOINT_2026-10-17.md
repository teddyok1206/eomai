# Scoped immutable model reuse — source checkpoint

2026-10-17 UTC. Full goal remains ACTIVE/NOT_COMPLETE. This changes one read cost
boundary within the original common-context delivery, not its source population,
Graph/policy/report pins, current authority, output or completed QUERY identity.
Design: [root-local decoding](../architecture/SCOPED_TYPED_ARTIFACT_DECODING.md).

## Authoritative observation and correction

The [original actual HTTP read](REFERENCE_QUERY_HTTP_READ_TIMEOUT_2026-10-17.md)
returned503 at30018.781ms. Installed e132c1aa and current read/snapshot modules
matched. Repeated JSON/schema/model decoding was identified and measured, but
neither the small profile nor this synthetic benchmark decomposes the live30s
request. No successful live latency/delivery result is claimed.

Existing root-scoped raw-member reuse already avoids rereading immutable bytes;
it does **not** stat/hash a retained member on each call. Early negative test
assumptions incorrectly expected that. Source semantics were inspected and
preserved: every typed call still performs the existing pointer/provenance and
exact-size checks; fresh-root materialization still rejects physical corruption
or a missing file. Source/IAM/report/Graph reauthorization remains fresh. This
change adds no filesystem or permission cache across requests.

## Source gates

- Final focused suite:217 PASS, including32 new scoped-model cases, exact Item/
  report consumers, retained four-capture authority tests and dependency rules.
  JUnit raw SHA `8f9e8b65a0a624451c8ccf0f792be45498fb362175c314d34655066a0f2f370f`.
- Strict typing:4 production modules PASS. Ruff/format/diff checks PASS.
- Guarded disposable PostgreSQL:47 embedding-storage/registry tests PASS, followed
  by213 execution/prepare/concurrency tests PASS; no skips. The original47-test
  process exited0, but its operator wrapper failed while interpreting the summary
  because of an over-escaped regex. That failed wrapper/evidence was preserved.
  A separate continuation verified its exact stdout hash and empty guarded DB,
  ran only the not-yet-run213 suite, inspected and removed the same disposable DB.
  This was not a product failure, model retry or reinterpretation of failed history.
- Compatible3-wheel build/RECORD: PASS for main f5994de2. Archive-only182-module
  import and optional-port/two-consumer smoke PASS, with synthetic Session/bytes
  and no checkout/test/ML imports or actual DB/NAS/socket/model/install calls.
- Operating installation: NOT_YET_PERFORMED for this change.
- Original HTTP delivery: NOT_YET_VERIFIED after this change.

JUnit/evidence staging: `/tmp/eom-scoped-model-benchmark.qm1UD6ca`.
Initial test failures and earlier evidence are preserved; only final gate runs
establish this checkpoint. No operating DB, model, Workflow or HWPX was mutated.

Disposable DB continuation evidence:
`/opt/eom/embedding-benchmark-os-evidence/scoped-model-decoding-continuation-8re3M4kj`.
213-test stdout raw SHA
`c23b810cb857e38a0a0a181536b1ca7c74b0bb305ff65c802ad84454a28113ec`;
prior47-test stdout raw SHA
`967aff33025db0e7d2ed0c7f856ba237ac3b0bf9103fbfa1b509e00318eb80c8`.
The original failed operator's evidence is under the sibling
`scoped-model-decoding-GJafimza`. Exact guarded test state
`/tmp/eom-api-testdb-20261017150629_106a9b6a` was removed by supported cleanup;
operating data and protected evidence were not deleted.

## Package and release preparation

Source candidate `f5994de26407f2f6e8a17e1c56740d6868e4f57f`, tree
`759c0c9b0c4ee39bf5612b9ceaf62e98f25f1bfc`, pushed to main.
Archive raw SHA `60b74d6667f87e15e8e1a6845db7dd22764ca44290beb70cec27528dfb790079`.
Build directory:
`/tmp/eom-api-build/f5994de26407f2f6e8a17e1c56740d6868e4f57f.ytM5gc/dist`.

| Wheel | Raw SHA-256 |
| --- | --- |
| platform | `62bc1b030bb28ac5d375f6697c0b6aa16fc82cd9169870531f8303a10006b74a` |
| API contracts | `a900be1274a033f47dbb74a4c21b8cd1be5e0f5677104c87012a0eb4ab467ba4` |
| API | `bec43906b44a98baff8b20e5efdb29c2c0d626a136f88fc64c78921177674c1e` |

Isolated package checker raw SHA
`b1cc1668fca5489b27532d4f228166eb4ccc7ab53265cf89ff094c6bf6a6afe8`.
Its fake member resolver is explicitly **not** provenance/real-session acceptance;
those are separate source/PG gates above. Optional frozen-model reuse and both
actual consumer imports load entirely from the two pinned wheels with `-I -S -B`.

The existing materializer AST is unchanged except reviewed SPECS/EVIDENCE
constants. Protected helper raw SHA
`347bae1a19ca11d3449a92dc113fbe3aaa841d02571bff53b699a86e8f4470c0`.
It staged the pinned archive/wheels at
`/var/lib/eom-release-operator-stage.f5994de2-p0dqwbwj`; context1.4 raw SHA
`dbcf30a10a72dc7e372f9d9eb92e82990cee568377a0abccdfff5cd7b5926699`.
Materialization PASS was followed by the existing protected runtime/launcher's
`ADMIT_PASS callback=ADMIT`. Admission stdout raw SHA
`472b19a1a7bcd6a8fa177e0367393ad1249b61c29db54eb653641fad92abc93c`.
It verified the exact prefix/context/source/wheel preparation; no EXECUTE callback,
installation, service change, DB mutation or model execution was performed.
The admitted identity is f5994de2, not a subsequent documentation-only HEAD.
Standard installation must use an exactly matching clean source/admitted release;
do not reuse this receipt to authorize different source archive bytes.

A separate minimal candidate `7eea7b83` backports only the identical four runtime
changes to installed e132c1aa.80 focused installed-base source tests and strict4
PASS. It is retained in `/tmp/eom-scoped-read-release.cLXdKzkl/source`, not built,
selected or installed. The verified main candidate above remains distinct; no
unfinished private Chat/exam feature is activated by staging either candidate.

## Synthetic benchmark, not live latency

520 synthetic canonical Item members plus520 synthetic solution-report members,
four phases, actual parsers and temporary files. Only source fixture content was
used: no production DB/NAS/operator authority. The schema registry was warmed
separately (cold initialization1.973s). Both modes retained the same raw bytes.

| Measure | Raw bytes only | Scoped frozen models |
| --- | ---: | ---: |
| Item decodes |2080|520|
| Report decodes |2080|520|
| Immutable metadata prefetch queries |3|3|
| Retained raw bytes |1749280|1749280|
| Decoded raw-byte charge |0|1749280|
| Retained model count |0|1040|
| Tracemalloc current Python allocation bytes |2603068|13769474|
| Tracemalloc peak Python allocation bytes |25155924|25103338|
| First phase seconds, tracemalloc enabled |4.906|4.924|
| Subsequent phase seconds, tracemalloc enabled |4.361/4.422/4.370|0.038/0.037/0.039|

All eight phase outputs have the same canonical-serialized raw SHA
`sha256:56bb6701828172d4bf4e7336266326369215ecf1dbdafd5254a177582e2521c7`.
The raw-byte charge is **not** a Python RSS bound: retained decoded allocation is
larger, disclosed above. Tracemalloc adds overhead; these are not uninstrumented
production timings. No wall-clock CI threshold is asserted. A committed128-member
count regression independently requires512→128 decodes and1024 total provenance
resolution calls across both modes, preserving every per-phase resolution.

Benchmark script raw SHA
`92abde55392b9782f23fc8ffa5322a6c8f90311ef7612d5815daaa2168382443`;
result JSON raw SHA
`de69e349fbbf33eeaa5958f8859bc1a3283c078d8dba37ea990a3f5e7379fc55`.
They are outside Git, under the staging directory above, not canonical corpus.

## Background indexing observation —15:04:40 UTC

One due read-only observation, not a new indexing launch:625 encoding rows/625
source-binding rows,163 immutable index revisions,6 logical indexes. Latest
three-view binding counts197/209/219, each with545 eligible sources. These are
relations/views, **not625 distinct Items**, full coverage or a vector audit.
Latest five work rows:2 REQUESTED,1 RUNNING,2 COMPLETED, failure codes null. This
bounded recent window is not proof of global absence of failures. Previous14:20
counts were613/613/160. No observation-triggered retry/claim/restart occurred.

## Remaining original-goal work

Validate the compatible package/release and exact original HTTP read/replay with
a valid supported operator session, without changing its key or regenerating
its numerical result. Then close actual C1–C5 consumer admission/delivery and the
frozen CPU/CUDA comparison/default-device gates. Those are still incomplete;
this performance checkpoint, partial index progress and optional Chat scaffolding
are not substitutes for full goal completion.
