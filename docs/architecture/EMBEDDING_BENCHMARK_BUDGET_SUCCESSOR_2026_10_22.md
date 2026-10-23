# Embedding benchmark execution-budget successor — 2026-10-22 UTC

Status: source implementation candidate. No deployment, inference, authentication extension,
automatic retry or GPU-default activation follows from this document or schema validation.
600 seconds is a bounded experimental budget, not a guarantee that the full first run will finish.

1. Responsibility and boundary: the existing Orchestrator benchmark owner authorizes and records
   work; Catalog's installed adapters stage and observe it; fixed PID1 units execute local numerical
   workers. The successor changes the benchmark's effective execution budget only.
2. Canonical source: immutable request and execution-policy Artifacts, installed service/socket
   bytes and their pinned SHA-256 values, and actual runtime/host admission receipts. The native
   configuration's 180-second resource recipe is installation metadata, not the effective benchmark
   sandbox policy or a compute grant. Normal INDEX/QUERY numerical recipes and identity/policy
   meanings remain unchanged; their installation-linked verifier/control pins need a coordinated
   refresh if the shared fixed CPU prefix is replaced.
3. Identity and revisions: released benchmark 1.0 remains exactly 180 seconds. Explicit policy,
   request and invocation 1.1 select exactly 600 seconds. Existing logical IDs, immutable revisions,
   failed histories, original model/input identities and numerical meaning are not rewritten.
4. Pointers and resolution: preserve exact Graph/source/access-policy/input/model/runtime and
   Artifact revision/hash checks. Root and numerical worker independently compare the invocation's
   released policy with the selected fixed unit family and absolute monotonic deadline before model
   construction or device access. A caller-provided duration never grants a larger budget.
5. Access patterns: constant-time policy/version and device/unit-family lookup; ordered six-launch
   execution; append-only launch history; exclusive native/GPU capacity ownership.
6. Structures and indexes: small immutable closed lookup tables select 180/600-second budgets and
   the corresponding service/socket families. Existing indexed Job/launch tables, unique claims,
   immutable manifests and physical GPU lease mechanism are reused; no new DB/index/queue.
7. Complexity and scale: O(1) budget/family selection and O(number of bounded input/output members)
   staging/validation. Six ordered launches and fixed checkpoint/sample counts remain unchanged.
8. Transaction and concurrency: existing owner admissions, native capacity lock, atomic launch
   reservation, physical GPU lease and Artifact commit boundaries remain authoritative. The new
   budget does not authorize concurrent launches or replacement executions after uncertain work.
9. Dependency direction: contracts own pure version/budget selection; application owns current
   authorization and state; Catalog adapters own filesystem/socket/unit effects. No domain or
   contract code imports infrastructure. Numerical workers have no DB/NAS/operator credential access.
10. Failure, retry and idempotency: monotonic compute deadlines remain fixed once staged; cleanup
    receives only its bounded existing grace. Expiry is not successful completion or permission to
    retry. Existing failed or uncertain launches are preserved and resolved by supported application
    paths. Real session freshness remains 900 seconds, separate from compute/cleanup/listener limits.
    A successor root listener may wait up to 3600 seconds, but this is not an authorization grant;
    genuine reauthentication occurs only between terminal, durably recorded launches when needed.
11. Simpler alternative: changing only TimeoutStartSec or accepting arbitrary durations would
    contradict immutable 1.0 policy and other deadline guards. A separate explicit 600-second unit
    family plus the same pure policy selector is the smallest compatible extension. New numerical
    implementation/model identity or a generic resource framework is not needed for this budget.

Deployment must preserve old service/socket bytes and true numerical implementation-v3 bytes.
The installed admission freezes the entire numerical prefix, not merely numerical-v3 modules.
Therefore changed worker/channel/contracts and new budget600 entries require ordinary explicit
CPU/CUDA successor-prefix installation with new whole-prefix inventory and fresh admission receipts.
Preserve the three true numerical implementation bytes, original model weights and encoding recipe;
do not introduce a cross-prefix bootstrap or patch an admitted prefix under its old receipt.
Actual installation, admission and successful comparison remain separate pending gates.

CPU recipe preparation need not replace the shared CPU prefix. A native configuration pins
the numerical recipe/model/bundle/proof/host, while its distinct admission receipt pins the
actual whole-prefix inventory and probe. Publish the already planned revision-only CPU
configuration with the existing admitted CPU interpreter and original references first;
this creates no installation receipt, changes no selected control and starts no native probe.
The original file set, observed numerical implementation and model ACL checks stay intact.
Only the explicit root/isolated-interpreter context is accepted. This small ordered metadata
publication reuses the prior finite operator, profile lock and create-once files; it introduces
no new registry/schema/queue or default lookup. Failure preserves partial files for inspection
instead of replaying or overwriting. The simpler alternative—publishing during prefix
maintenance—unnecessarily lengthens the healthy-service interruption and gains no invariant.

The legacy CUDA readiness closure retains the installed staging-file pin `0f93acf5...`.
Policy1.1 explicitly selects the reviewed staging-file implementation `4bc5d315...` and the
unchanged legacy CUDA numerical leaf `d1542cbf...`; these pins must never be interchanged by a
fallback. This is versioned staging behavior, not a change to the three numerical implementations.
Both dedicated budget600 entries first read the actual protected invocation and compare its exact
released policy and own cgroup against the closed unit family before entering the existing leaf.

The outer operator service's finite runtime must cover its login wait, admitted listener lifetime,
last accepted launch and terminal cleanup. A long listener is not permission to extend any compute
deadline, retry an uncertain invocation or treat an expired human session as current authentication.

## Started failure and clean progress boundary

The original CPU launch actually started and produced partial bytes. The existing never-started
reconciliation contract cannot close it. The additive post-start contract records only the exact
CPU ordinal1, original request/Job/invocation, root completion, original retirement, terminal native
and controller identities and bounded output member sizes/hashes. It contains no vectors, source
text, successful worker result or replacement execution. Root attests files inaccessible to the
owner; owner capture rechecks the actual retained proof, current machine and readable original
files. Parsing a caller-supplied observation is not authority. Controller lifetime must enclose the
actual original completion interval, not merely share a source commit.

`BenchmarkPoststartFailureApplication` reauthorizes exact sources and the actual operator, then
appends one failure event and atomically closes the original RUNNING Job as FAILED. Replays return
that original decision; late authorization or file/process drift rolls back the transition. An
explicit successor registration may change only request revision/input-manifest identity and the
reviewed policy1.0/180 -> policy1.1/600 revision. Source/input/model/numerical/Graph/access-policy
meaning and launch order remain equal. No migration, direct row repair, automatic retry or fake
success Artifact is introduced.

`run_next_launch` reuses the same owner/Journal and dispatches at most one new ordinal. It returns
only a fully validated, durably published clean prefix; the sixth complete launch alone advances to
VALIDATING_RESULT. Unresolved work still stops dispatch. Genuine authentication can be refreshed
between these calls, never substituted during an active launch or renewed by a token refresh alone.
Phase diagnostics buffer a bounded sequence of content-free events during the measurement and
flush only after measurement/resource/channel closure; logging cannot change the measured clocks.

The frozen CUDA leaf opens its local files before READY/root ACK. The shared numerical worker
previously attempted a second context entry, which the file capture correctly rejected. The
successor uses an explicit one-time `begin_worker_execution` handoff: unopened capture follows the
original path; an already-open capture is accepted only for CUDA with the same fresh sealed READY,
no numerical input materialization/output/budget use, and a current FD/file check. Ordinary context
re-entry remains forbidden. Existing close is idempotent, so the worker and outer leaf can release
the same retained capture safely. Old numerical leaf bytes and the legacy readiness pin stay fixed.

## Installation and rollback scope

The current checkout's HOST_L2 bytes differ from the admitted CPU/CUDA implementation. A whole
main wheel is therefore not a numerical-preserving native upgrade. Build an explicit coherent
private-source successor from the admitted runtime baseline with only the reviewed benchmark
closure, and check all three numerical module bytes before installation. Metadata SDK and native
prefix source identities remain separate when their contents differ.

CUDA can be requalified first without stopping the healthy CPU owners. The shared fixed CPU
prefix must not be replaced while INDEX/QUERY use it. Drain the scoped claims/native holders,
prepare both forward and recovery inputs, stop the two affected owners, qualify the replacement
and select their linked config/environment/verifier pins together. Existing source policies,
Identity grants and outer owner releases need no semantic change.

The installer retains an old prefix but changes its directory metadata. Moving it back and
restoring an old receipt is not sufficient: inode/mode/time closure is exact. Recovery requires
fresh whole-prefix inventory/config/admission for those restored bytes too. Prepare that recovery
path before cutover; do not promise a fixed maintenance duration without measuring it.

The finite maintenance observer reuses the existing scoped INDEX/QUERY claim query, actual
PID1/cgroup/socket/prefix-user checks and accepted root post-start proof. Root maintenance is
a read-only operational role, not an impersonated human benchmark operator. Its indexed reads
of the exact original Job/event8 verify the already committed typed failure decision against
that live proof; they authorize no new computation or source access. SQL is explicitly READ ONLY
with bounded statement/lock timeouts. A live preflight checks the currently selected owner
invocations without stopping them; the stopped phase additionally compares a root-owned
create-once stopped-unit record. No file/DB mutation or global Codex-job drain occurs in either
observation. This avoids reusing the old never-started proof for a different actual failure.

The finite drain pins INDEX's existing non-root identity and QUERY's existing root
supervisor separately; QUERY continues to drop its serving child to UID990. Do not
generalize either identity to make a check pass. Only exact observed owner mains receive
SIGTERM, and native children drain naturally. Preserve an exclusive intent before signals
and a separate actual stopped record afterward. Timeout never means force-kill, restart,
successful retirement or permission to publish. The fixed publication operator then rechecks
the stopped guard and delegates to the existing installer exactly once. Reuse the already
materialized fea7 private wheel/tar by their exact hashes; do not duplicate them into a new
CPU folder. The installer's one bare preparation marker precedes eight key/value lines and
is part of its existing CLI output, not a malformed result or a new runtime contract.

Recovery definitions and both forward/rollback same-live seal functions can be protected
before cutover, while actual backup paths, epochs, inventory and receipts cannot be filled
until the corresponding effects occur. Future exact pins are a required observation between
stages, not a reason to invent them. A staged definition is not an executed restore or an
admission. Keep the healthy owners up until the reviewed forward/recovery execution
compositions are ready. If owners resume after CPU qualification but before the numerical
window, all budget600 templates must still be absent: unchanged outer owner guards do not
cover that family. Record new owner invocations rather than pretending the old ones survived.

## Source and isolated verification checkpoint — 2026-10-22 UTC

- Actual marker-guarded disposable PostgreSQL group:34 PASS, including new post-start closure,
  concurrent same-request successor submission, replay and late-authorization rollback. The first
  run was33 PASS/1 FAIL because the test wrongly expected two immediate winners; the existing
  nonblocking advisory lock correctly returned SUBMISSION_BUSY. Only the test expectation changed;
  same-request replay after rollback resolves the single winner. Production locking was preserved.
- Actual opt-in root/owner/native DAC test:1 PASS under NoNewPrivileges with DAC_READ_SEARCH and
  without DAC_OVERRIDE. Machine/retirement semantics in this test are synthetic and separately
  unit-tested; this does not claim an actual failed-run proof has been minted or admitted.
- Focused source cohorts:484 PASS for the application/protocol/owner closure;139 PASS for the
  effective GPU policy/native capacity/drivers;205 PASS for host OOM/channel/entrypoint;84 PASS for
  local files/worker/sealed CUDA handoff;73 PASS for version-selected actual readiness file pins;
  44 PASS for dependency/design boundaries. The final budget/policy/capacity cohort is191 PASS.
  Cohorts overlap and must not be summed. The wider benchmark run collected during edits completed
  with2021 PASS/2 FAIL; both failures used the earlier in-memory CUDA pin/test state. Exact rerun on
  the final source is2 PASS, without weakening guards. This is not a claim of a fresh whole-suite
  all-green run after every later edit. Ruff/format for63 Python files, mypy for41 changed core
  modules and diff/shell syntax checks pass.
- Native successor installation/admission, original started-failure closure, real600-second
  inference/comparison and GPU-default selection are NOT_PERFORMED at this source checkpoint.
