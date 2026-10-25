# Known terminated CPU INDEX failure recovery

2026-10-25 UTC; required by the approved GPU-preferred goal, not the unopened
post-checkpoint review. **Design/schema candidate; no production recovery yet.**

## Observed defect

Current CPU standby Workflows borrow64 encodings owned by original native Job
`job_ced5f8ad3d7a4bd0a79e2e792f46416d`, Workflow
`workflow_1b68f2babfcb4d90a6344644f41f1d50`. Its fixed prepare unit succeeded
(invocation `63585ccbb10b41dc8c1234719fec4fb2`), but the exact CPU unit timed out
on2026-10-19 21:32:42 UTC (invocation `03b7cafb93474e55bf2718b8e042fc9f`).
Both have process0/storedFD0. The native association exists, all64 producers remain
RUNNING, and the old Workflow has many successful deferred commands plus one
expired PROCESSING command. Current standby requests therefore wait correctly,
but cannot finish. Existing CUDA failure recovery requires an original GPU
parent/retirement and exactly one START command; that proof must not be fabricated
or weakened for a CPU execution with different history.

Evidence: read-only `/tmp/eom-cpu-reservation-owners-20261025-r1.json`, EXIT0;
actual fixed-unit properties, and current phase metadata at16:35. The current
INDEX/GPU invocation remains live. No row has been repaired directly.

## Boundary and modeling decisions

1. Responsibility: add a fixed CPU failure evidence adapter and one explicit
   schema-owner maintenance use case. Reuse native coordinator, encoding-owner
   FAILED/retry histories and Workflow state transitions; no new queue/framework.
2. Canonical sources: exact original Workflow/step/native intent/association and
   producer Job events; actual PID1 fixed-unit invocation, kernel cgroup emptiness,
   templates and original failure. A caller-shaped proof is not authority.
3. Identity: preserve all logical Jobs, revisions, request/association hashes and
   old command outcomes. The original native admission command and the later
   expired deferred command are **different references**, never relabeled.
4. Pointers: successor recovery3 pins original native Job/intent hash, exact latest
   command/generation, current service head reference and original CPU unit/boot/
   invocation/start/exit identities. Resolve hashes, ownership and lifecycle in
   their official owners. No caller-supplied filesystem path or unit template.
5. Access: indexed Workflow/step/native Job lookups; ordered bounded command
   history; keyed producer identities; exact fixed prepare/main unit reads.
6. Structures: tuples/maps/sets, existing append-only events and existing unique
   producer keys. Scale: at most2048 commands/1024 encodings per maintenance call;
   O(commands + encodings) metadata, no corpus scan or binary DB payload.
7. Transactions: schema-owner/root admission, current-head shared lock, original
   Workflow/command/step/native/encoding locks in existing order. Physical proof
   is checked before and after the short atomic mutation. Busy/conflict rolls
   back; no force flag, lease extension, dispatch or replacement identity.
8. Dependencies: contract contains frozen values only; fixed infrastructure reads
   actual unit/kernel identity. Application owns state transitions and the
   existing Orchestrator storage leaves. Workers gain no DB/NAS/root permission.
9. Failure/retry: only a genuinely terminated failed CPU execution with expired
   command, absent completion/publication and retired service reference may fail.
   Preserve prior SUCCEEDED commands and original FAILED unit. No timeout alone,
   current process, different invocation, partial publication or unknown physical
   state establishes recovery. Do not change generic CPU timeout/UNCERTAIN rules.
10. Replay: the exact command has one immutable maintenance receipt. Replaying
    validates terminal Workflow/native/producer/event closure without a new
    side effect; changed intent fails. New encodings use the unchanged bounded
    successor producer mechanism, never FAILED→SUCCEEDED or ad-hoc Job creation.
11. Simpler alternatives: waiting cannot release these known dead reservations;
    resetting units/replacing IDs or assigning old producers to current work
    destroys provenance. GPU recovery proof does not describe CPU execution.
    Add only the distinct CPU evidence and share existing failure/retry rules.

## Release and tests

Released recovery1/2 bytes and meanings remain unchanged. Define JSON Schema
2020-12 for recovery3 before behavior; keep producer retry declarations1 unchanged.
Prepare/install the compatible successor decoder before any recovery3 event can
be encountered by INDEX **or existing Catalog/API completed readers**. Their
shared platform must recognize the new failure family without changing old
completion, private-chat or runtime policy semantics. At a safe completed-GPU
boundary, drain the old metadata
process without killing numerical work; keep historical non-executable waiters
explicit rather than inventing success or blindly resubmitting them.

Use disposable PostgreSQL for concurrent exact recovery/replay, many successful
prior commands, expired later-command identity, all-or-nothing rollback, producer
uniqueness and ordinary successor retry. Include active/foreign/stale unit,
changed template/boot, owner denial, valid lease, completion/publication and late
physical-change negatives. Unit mocks are not actual retired-CPU acceptance.
First validate the exact old units read-only, then apply the supported bounded
maintenance command; preserve every original failed artifact and result.

The separate observed metadata memory pressure (1GiB cap, frequent max events,
OOM0) is not this failure's cause and does not authorize numerical resource or
deadline changes. Measure/handle it separately if it limits catch-up. GPU default,
full paired coverage and overall goal completion remain unproven.

## Candidate verification — 2026-10-25 UTC

Focused shared-owner/CPU evidence/carrier unit tests:203 PASS; strict mypy:8
production modules PASS; scoped Ruff/format PASS. Guarded disposable PostgreSQL
run r70:53 PASS and database cleanup EXIT0. It covers legacy/mixed CPU carriers,
128 prior deferred commands, atomic late-proof rollback, same-command concurrent
recovery, actual runtime-role denial, exact terminal replay without a new unit
action, and concurrent ordinary producer successor/replay. Earlier SUCCEEDED
commands and all original FAILED producers remain unchanged. Existing GPU1/2
recovery and producer retry regression tests ran in the same disposable database.

Run r69's51 PASS/2 fixture errors is retained: the new mixed fixture initially
called the test-local Artifact member helper with the wrong signature. Correcting
that fixture did not relax production schema, source admission or runtime checks.
OS/model/source leaves in these PG tests are explicitly synthetic. Installed-wheel
and exact original CPU unit checks still precede any production maintenance.
