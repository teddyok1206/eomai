# Original six-launch timing assessment

Design before behavior,2026-10-18 UTC. Continues the existing
[execution composition](EMBEDDING_BENCHMARK_EXECUTION_COMPOSITION.md), not a new
benchmark recipe or permission to execute models.

1. Responsibility: assemble the existing device timing evidence from six original
   completed launches, then call the existing fixed performance comparator. No
   numerical correctness, authorization, cleanup or default-activation verdict.
2. Canonical source: the original Job journal and committed per-launch Artifact
   members, read by the existing current-administrator/source/policy admission.
   Pure aggregation alone cannot prove their provenance.
3. Preserve request/Job/execution/Artifact/revision/raw-versus-semantic hashes.
   Reject another Job, repeated execution, missing/reordered launch or another
   request rather than substitute a later/fastest run.
4. Resolve only the receipt's exact same Artifact Revision. Fixed native timing,
   owner cold timing and query timing members require manifest/schema/media/hash
   checks; authorization is rechecked before and after reading.
5. Access pattern: ordered immutable six records, then keyed query identity lookup.
   O(6 + 20) time/space; no global scan, cache, queue, new index or DB schema.
6. Keep CPU→CUDA→CUDA→CPU→CPU→CUDA. Every cold span counts; warm/query samples
   come only from the prescribed first CPU/CUDA launch, not extra cold launches.
7. Cross-check native encode clocks with actual owner query clocks and cold spans.
   Preserve raw nanoseconds. CPU floors and CUDA ceilings microseconds exactly as
   the released TimingEvidence1.0 contract prescribes; thresholds do not change.
8. One caller-owned Catalog root holds current source/policy authorization and
   original journal reads. Pure value construction neither commits nor launches.
9. Catalog's existing Artifact adapter owns bytes; pure aggregation imports only
   contracts/value/comparison code. No domain-to-infrastructure dependency added.
10. Missing/corrupt/foreign/incomplete timing data fails explicitly, with no retry,
    new identity, state repair or conversion of failed history to success.
11. Comparing manually entered medians is simpler but loses owner/native clock
    closure and permits cherry-picking. Reuse the frozen comparator instead of
    implementing another threshold policy.

Actual six runs, source/runtime/lease/numerical/regression gates, paired QUERY and
DOCUMENT routing, conditional GPU default and actual rollback remain required.
Synthetic timing tests are not observed CPU/CUDA performance.

## Implementation boundary

`BenchmarkLaunchJournal.require_completed_launches` now returns the same six
validated original invocation/receipt/result values. Existing receipt-only reads
delegate to it; each worker result is materialized/parsed once in that operation.
No journal event, SQL schema, state transition or persisted payload changes.

The existing Catalog admission reads only fixed cold/query timing names from the
receipt's exact Artifact Revision. Its normal resolver validates producing Job,
manifest, schema/media and raw bytes. JSON Schema2020-12 and frozen Pydantic
fragment models validate clocks, with canonical-byte equality rejecting duplicate
fields/noncanonical input. Current source/policy/administrator fences surround
the read and producer provenance is checked again before return.

The read application requires the original series in VALIDATING_RESULT, closes
six original records under one source root and checks history again on exit.
The pure assembler checks request/input/runtime closure, a single Job, six unique
executions, fixed order, native-versus-owner cold/query clocks and conservative
nanosecond conversion before calling the existing threshold comparator.
It does not publish an OwnerResult, change Job state or assert any of the other
nine gate families passed. Full measured numerical/rank/resource assessment and
protected live execution coordination remain OPEN.

## Exact disposable PostgreSQL proof — 2026-10-18 01:14 UTC

The finite source-pinned gate ran the existing supported `embedding-encoding-tests`
purpose: **23 PASS /no skips /inspect PASS /cleanup PASS**. Actual PostgreSQL,
official temporary Identity login/capture/logout and registered immutable Artifact
reads are exercised; Graph/source, capacity and native clocks remain synthetic.
The new case connects the actual original Job/journal through six registered
Artifacts into two identical read-only assessments, then denies a logged-out
capture. Job counts and dispatch counts remain unchanged by both reads. No user
login, real model, operating DB or live runtime activation occurs.

Protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/benchmark-timing-kuRqpv6j`.
Helper raw SHA256:
`ed95d6a52444e2c6b0b5009464a31aa1109658bc2ee5d1f18675c40890fcbc9f`.
Test stdout raw SHA256:
`d98379ba228fb9edfc3943441474eb16a794ffc0bff52b280ac6720bf67ffdb8`.
The original root1387715/wrapper1387708 terminated normally. All171 source/test/
migration pins remained unchanged through cleanup and protected readback01:15 UTC.
The exact temporary state directory is removed by the existing guarded cleanup;
the evidence and all historical failures are retained. Same EOM2 noninteractive
sudo session, no prompt/credential persistence/TTL change or automatic replay.

Initial focused timing fixtures incorrectly assigned a separate Job per launch;
three positive tests failed until fixtures pinned one original Job and re-sealed
dependent hashes. Production one-Job closure was not relaxed. Adding a new journal
read-count check left an old cumulative-count assertion in the wrong position;
that test alone failed in the first broad run (1294 PASS/1 FAIL). The original11
reads are now asserted before the new operation, which reads exactly six results,
and the compatibility wrapper is separately checked. Focused correction PASS;
the final full source rerun completed with **1295 PASS /48 suites /246.19s** at
01:19 UTC. Strict mypy4 production modules, Ruff/format8 and diff checks PASS.
Focused15 timing/10 canonical-read cases and previous1244 overlap and are not
summed. No source/schema/runtime proof is inferred from an earlier source snapshot.

The next due read-only INDEX observation01:18:47 UTC reported785 encoding/binding
rows,203 revisions and6 logical indexes; latest per-index265/545,275/545,245/545
remain PARTIAL, not785 Items or a fresh full Artifact audit. Latest five operations
are3 COMPLETED/2 REQUESTED, each failure_code null; this is not a global lease or
failure inventory. The actual INDEX service is independently active/running,
MainPID1149648. Original HTTP observer837676 remains live and was not replayed.
Next routine INDEX check no earlier01:48:47 UTC. Sanitized local evidence:
`/tmp/eom-benchmark-timing-observation.GxTtO3fX/index-observation.json`.

CPU remains the operating default; all actual consumer/device/default acceptance
requirements from the original full goal remain intact. No interactive login
before2026-10-19 00:13 UTC, no stored credentials or fresh-auth substitution.
