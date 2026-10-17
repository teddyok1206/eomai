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
- Guarded disposable PostgreSQL: IN_PROGRESS; not substituted by synthetic tests.
- Compatible build/installation: NOT_YET_VERIFIED for this change.
- Original HTTP delivery: NOT_YET_VERIFIED after this change.

JUnit/evidence staging: `/tmp/eom-scoped-model-benchmark.qm1UD6ca`.
Initial test failures and earlier evidence are preserved; only final gate runs
establish this checkpoint. No operating DB, model, Workflow or HWPX was mutated.

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
