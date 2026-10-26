# Original unbound controller failure

2026-10-25 UTC. This closes an original planning failure, not a numerical
retirement, CPU fallback, retry grant or new queue.

- Owner/boundary: Catalog's root-only read adapter observes the exact original
  control unit, protected allocation/launch/empty work files and current native
  unit. Orchestrator's existing `EmbeddingBatchPlanStore.record_failure` alone
  appends FAILED. The operator retains the actual schema-owner transaction gate.
- Canonical source: original immutable parent/allocation plus protected files and
  actual kernel/systemd observations. A DTO, EOF, expiry or DB row alone is not
  proof. The failed root outcome is preserved. No numerical invocation or
  retirement is fabricated.
- Identity/revision/pointers: pin parent Job/request, allocation attempt/control
  request, root invocation/PID, boot and file hashes. Commit one validated small
  evidence Artifact with an immutable member/hash pointer via the existing
  Orchestrator publisher; no binary or source text goes into PostgreSQL.
- Access/structures: one indexed parent lookup, a constant set of bounded files
  and two fixed unit observations, frozen evidence. O(1) metadata/space and O(bytes)
  for small file hashes; no corpus scan, cache, queue, table or index is added.
- Transaction/concurrency: existing original parent lock serializes failure and
  replay. Refuse route, BOUND, Workflow or publication evidence. Recheck actual
  stopped unit/file fences before transaction exit so a late change rolls back.
- Dependency direction: the evidence value/schema has no I/O; Catalog implements
  the root read adapter; the maintenance operator uses public Catalog and
  Orchestrator application interfaces. Workers gain no permission or persistence.
- Failure/retry: require original failed root, no active process/retained FD,
  expired original allocation, zero original work files and absent input grant.
  Call this NOT_GRANTED, not BUSY or proof that CUDA was never initialized.
  Unknown/changed/granted work is refused; terminal history is never changed to
  success. Exact replay uses the same evidence and existing failure record.
- Simpler alternative: the existing retired-numerical proof cannot express an
  absent native invocation. Supplying a dummy invocation/retirement would corrupt
  provenance. A small new evidence contract is narrower than changing execution
  protocols or creating an INDEX Identity merely to bypass the original parent.

Tests must cover schema strictness, changed/granted/nonempty files, real-root
admission, unit identity/process/FD changes, and late fences. Existing disposable
PostgreSQL failure concurrency/replay/rollback suites exercise the same planning
store. No pytest may use production DB. Live closure retains original FAILED root
and records the original parent FAILED through the supported operation only.

## Source verification, 2026-10-26 UTC

- Closed schema/immutable evidence, original root/no-grant reader and existing
  GPU controller/retirement/channel/planning regressions:198 PASS,42.80s
  (`/tmp/eom-unbound-control-regression-20261025-r3.log`). These overlap the
  earlier127-case subset and are not added together.
- Guarded disposable PostgreSQL r73:63 PASS,27.58s; database removed. This includes
  the real official application's owner transaction, concurrent exact replay,
  Artifact/late-physical/publication refusal, and all three existing planning
  families' atomic route-versus-unbound-failure race. OS/Artifact/source leaves
  are explicitly synthetic here, not actual root/GPU acceptance.
- The r72 attempt retained62 PASS/one fixture failure: its synthetic INDEX
  selection used two view children, unlike this actual single-child parent.
  Correct the fixture to one CONTENT child; do not weaken that original context
  rule. The failed log and successful disposable cleanup remain evidence.
- Strict mypy5 production modules and scoped Ruff/format PASS. No dependency,
  migration, live state transition or new model invocation is implied by these
  source results. Actual installed read/official closure remains separately gated.
- Existing dependency-boundary and source/control-admission suites:25 PASS,
  16.04s (`/tmp/eom-unbound-control-dependency-admission-20261026-r1.log`).

The first installed SDK `a5122dc0` passed wheel/RECORD staging, but its read-only
PREPARE refused a plain hexadecimal root-template constant where the protected
file API requires `sha256:`. The actual two service-template hashes matched their
pins; this was a representation bug, not drift or permission failure. It happened
before local proof publication, Artifact creation or any DB state mutation.
An explicit red regression reproduces this mismatch. Normalize that one boundary
without changing either template/hash or weakening the file check, then stage a
new immutable SDK rather than editing the installed prefix. Preserve the original
failed read log; do not mistake staging for live failure closure.
