# Explicit six-launch benchmark owner composition

2026-10-18 UTC. Design before behavior; existing benchmark schema/recipe and
thresholds remain unchanged. No model run or operating activation is implied.
Continues the [existing execution composition](EMBEDDING_BENCHMARK_EXECUTION_COMPOSITION.md)
and [frozen device-comparison design](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md).

1. Responsibility: assemble the existing Catalog fresh administrator/source/policy
   admission, fixed CPU/CUDA execution and Orchestrator series/Artifact owners.
   This is one operation-local application factory, not a new service or queue.
2. Canonical input is the closed BenchmarkOwnerRequest1.0 and selected immutable
   policy Artifact. Current authentication comes only from an actual supported
   Identity capture, never the request's audit ID, a stored row or root privileges.
3. Preserve benchmark/Job/execution/Artifact/revision/hash distinctions. The
   existing original Job key and six fixed ordinal reservations own replay.
4. Validate request/configuration/policy raw-versus-semantic hashes, actual capture
   provenance/operator and both typed native backend selections before composition.
   Actual current permission/ADMIN/Graph/source/provenance checks stay in admission.
5. Factory construction reads only OS account/process identity, not DB or Artifact
   bytes, and has no authentication, unit, model or publication side effect.
   Run uses existing indexed original-key and bounded six-launch
   history; constant-size composition, O(1) extra storage, no new index.
6. The actual fixed native owner UID/GID and no supplementary groups are required.
   No worker sudo, API credentials, root auth or model-supplied callable is added.
7. This supported composition uses the current native QUERY composition's
   900-second fresh-auth cap; the generic Identity fence contract is unchanged.
   A provided fence may be stricter, never looser. Do not renew authenticated_at or accept a fake
   capture to keep a long run alive. An expired gate remains explicit.
8. Publisher settings supply the installed owner source commit; root-controller
   release must match it. Reuse that publisher's exact engine/session factory and
   canonical artifact root. No ambient settings or shadow storage is introduced.
9. Catalog infrastructure composes existing public Identity/Orchestrator adapters;
   domain/schema code remains infrastructure-free. No dependency added.
10. Factory failure is content-free and before execution. Existing owner handles
    admission denial, capacity, original uncertain reservation and exact replay;
    no model retry/new identity or success reinterpretation is added.
11. Manually assembling disconnected adapters in an operator script was the simpler
    alternative but omitted the actual factory and made source/audit/runtime mixing
    easy. This function owns only composition, not another authorization rule.

The reviewed original-execution root controller must still serve its exact protected
stage before actual numerical work. This factory does not start privileged helpers,
install/select policies or provide that controller. The supported actual source
selection, live administrator capture, protected controller coordination, six real
measurements, comparison/default decision and actual rollback remain separate
operating gates. During the user's no-login interval, prepare/test these boundaries
without prompting or pretending an old session is fresh.

## Source verification — 2026-10-18 UTC

The explicit factory now connects the existing admission, fixed execution and
Artifact publisher using the original publisher's engine/session factory and
installed source commit. It introduces no schema, migration, dependency or queue.
The selected request is closed by the existing raw-value/schema/semantic codec;
policy member bytes and policy semantic identity remain distinct checks.

Related45 source suites: **1244 PASS /232.84s**, including17 new composition cases;
the earlier14 focused cases overlap and are not summed. Strict mypy1 production
module, Ruff/format2 and diff checks PASS. Local SQLite/actual adapter construction
is real; OS identity and issued Identity capture are synthetic test fixtures.
The real admission rejects that SQLite root before installed probes or Job writes.
An independent actual unprivileged process was rejected with the stable content-free
code before any model import or DB operation; this is negative process evidence,
not positive fixed-owner/live administrator acceptance.

Actual fresh-auth/source/policy admission, protected root-controller coordination,
six model runs and resource/cleanup assessment, paired QUERY/DOCUMENT device routing
and actual rollback remain OPEN. No operating DB, service, policy, protected owner,
numerical prefix, model, selector or default was changed. CPU remains selected.
Construction success is neither authentication nor runtime readiness. The user
requested no interactive login for24 hours from2026-10-18 00:13 UTC; stale capture
is not substituted for that missing live gate, and no additional login was requested.
