# Native benchmark execution composition

Status: source implementation in progress; not six-launch acceptance or a device-default change.

This closes the execution composition described in
`INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md`, without changing the released
`embedding-device-benchmark/1.0` schema or its numerical/performance thresholds.

## Boundary and data flow

The application owner must authorize the actual operator, resolve pinned Graph/policy/source
revisions, materialize the accepted input Artifact, and create a genuine structured Job. The
Catalog infrastructure handoff adapter only prepares a local execution directory. A valid
`operator_audit_id`, request hash or handoff is **not** authentication or launch admission.

Canonical source remains the registered input Artifact and its validated source pointers.
`benchmark_id`, immutable benchmark revision, Job ID, execution ID, input-set semantic hash,
invocation semantic hash and raw serialized-file hash remain distinct. The returned handoff
receipt contains small metadata, not copied source documents or a published output Artifact.

The existing request/invocation/input validators run before filesystem effects. Raw bytes are
canonical and bounded; no stale pointer is replaced by latest. Resolution of permissions,
source media/schema/lifecycle and Artifact bytes belongs to the supported application owner,
not to a root filesystem preparer or numerical worker.

## Local materialization

The fixed root is `/run/eom-incremental-embeddings/benchmark`. Installation must prepare this
protected root separately. The adapter must not create arbitrary ancestors. Execute-only
root-owned global parents prevent native users listing other executions. Ancestor traversal
uses directory `O_PATH` descriptors; only the execution-specific directory is readable under
its closed native-user/owner-group ACL. Every component is no-follow and non-writable by
other principals.

One atomic execution-directory creation is the concurrent-claim boundary. Existing or
partially prepared executions are explicit failures, not overwrite/replay permission. The
worker cannot create, replace or remove members: root owns the directories and immutable
input, and precreates the exact empty output files owned by the fixed native account.
Invocation FD ownership stays with the caller; the worker owns only its captured duplicate.
Preparation failures preserve the partial directory for explicit inspection, never broad
recursive cleanup or a second identity that disguises the failed attempt.

Primary operations are keyed execution lookup, bounded ordered output iteration and exact
set membership. A fixed tuple (4 or 16 output members), descriptor-relative file operations
and atomic `mkdir` suffice. Time is O(input bytes + path depth + member count), space is
O(input bytes + path depth); no DB/index/cache/migration or new dependency is needed.
Shared deterministic ACL/member-layout functions keep preparation and capture consistent.
This is a local infrastructure boundary, not a new cross-service JSON message.

## Remaining execution responsibilities

1. Application source authorization, real Job admission and immutable owner-request capture.
2. Six fresh fixed CPU/CUDA units in the released interleaved order, mandatory installation
   admission, exact configuration pins, Unix peer fencing and checkpoint/resource exchange.
3. Actual GPU physical lease/cgroup/cleanup and image/trainer model/cache/BUSY/crash/timeout
   gates before CUDA inference. Retained negative OS gates alone do not satisfy them.
4. Owner validation of sealed output bytes, token witnesses, numerical ranking/performance
   and all nine owner gates. Only the Orchestrator commits validated output Artifacts to NAS.

Each launch retains its own immutable outcome. Timeout is not proof of non-execution;
unknown cleanup blocks the next device launch and publication. Retrying requires supported
state reconciliation and a recorded launch decision, not truncating staged files. No worker
may authorize itself, impersonate an operator, mutate another service's DB or write NAS.

The simpler generic three-file INDEX handoff is insufficient: benchmark launches require
4/16 native-owned members, read-only per-execution ACLs and independently pinned invocation
and staged-input bytes. Reuse the existing contract and fixed runtime-profile mapping rather
than introducing a parallel queue, generic runner framework or artificial Job/Artifact.

Source tests use explicitly synthetic ownership fixtures and cannot prove root admission,
actual device timing or installed-runtime acceptance. Those remain separate opt-in gates.

## Source checkpoint — 2026-10-17

The root-only preparer, shared closed ACL/member layout and execute-only ancestor traversal
are implemented. Eight focused source suites: **526 PASS** (39.13 s); strict mypy on four
changed production modules and Ruff/format pass. Cases cover six layouts, schema/hash
closure before mutation, real concurrent mkdir uniqueness, no-clobber, private partial
failure, missing/symlink/writable/default-ACL root, and listing-denied ancestor traversal.
No released schema bytes changed; no dependency, migration or model execution was added.

`tests/integration/test_embedding_benchmark_handoff_privileged.py` is a separate opt-in
root OS test (`EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED=1`). It prepares only private `/run`
fixtures, permanently drops child UID/groups, and tests actual native-account access and
other-account denial. It does not create production Jobs/Artifacts or exercise GPU/models,
and must not be reported as six-launch numerical/performance acceptance.

## Actual private filesystem gate — 2026-10-17 05:44 UTC

Candidate source `aca170cccdbfaddad884fb8c316cf0a606023e71` passed the standard API
build/RECORD gate. A passive owner release was installed with the existing protected
installer; **no active owner selector or numerical prefix was changed**. The same EOM2
sudo authorization was reused, without a new login prompt, TTL change or saved credential.

Wheel raw SHA-256 (not semantic request or Artifact hashes):

- platform: `c10a57c10bc6061c69aeeb1e3124a1a6b029fb2e1efcef908f291db5eedad009`;
- API contracts: `3ef98394dc7d05639270caa861a2ec97727000539af60cd4fbe55d28bced2f8b`.

The fixed root operator ran the six opt-in OS cases against the installed candidate, with
real UID0 preparation and permanently unprivileged CPU/CUDA-account children. Private
`/run` fixture directories were the only overridden location; expected UIDs/GIDs and
permission rules were not replaced. Exact output write/read succeeded; global listing,
path-based invocation reads, input modification, extra member creation/unlink and the other
native account's execution access were rejected. All **6 cases PASS**, separate from the
526 source tests. The test deliberately uses synthetic bytes, not numerical/model evidence.

Protected OS-local evidence (not a product Artifact or a NAS output):
`/opt/eom/embedding-benchmark-os-evidence/aca170cccdbfaddad884fb8c316cf0a606023e71/`
contains the prior intent, installation stdout/stderr, exact source fixtures, test stdout/
stderr and result. Test stdout raw SHA-256:
`5e6cca423a80a1ca132a69af27d5623259df8e2e80cc73885e45395d5be837e2`.
The no-replay local operator receipt is
`/tmp/eom-benchmark-handoff-os.o5HRuMIF/operator-result.json` (`returncode=0`).

Models/GPU executions/production Jobs/Artifacts/new authentication prompts: **0**.
The production handoff root and running INDEX/QUERY work were untouched. Active image
guardian selection remains the previously verified e232/c203 pair. Actual source-admitted
benchmark Jobs, fixed six-launch runtime/channel composition, regression gates and measured
CPU/CUDA comparison remain pending; the full goal is not completed by this OS gate.

## Fixed CPU entry and socket activation — design before implementation

The next concrete executable is a CPU-only benchmark leaf, not another queue or grant.
Its existing1.0 invocation arrives on PID1-opened stdin; its one Unix listener arrives via
systemd socket activation. PID1 creates `control.sock` in the protected execution directory,
owned by the workflow owner with mode0600. The native user can accept on the inherited FD
but cannot create/unlink that member or connect as an owner. The existing channel validates
actual SO_PEERCRED against an exact owner PID/UID/GID, not a model-supplied actor.

The trusted root launch composition must write a root-only per-execution environment file
containing the invocation raw hash, actual owner PID and absolute monotonic deadline.
The owner captures the existing protected CPU installation pins into that exact launch
file; the unit never reads a mutable global environment as an implicit latest. CLI parsing is a small
frozen internal value, not a new worker JSON message; request semantics remain the released
JSON Schema2020-12 invocation/input protocol. A listener or prepared file is never source/
Job authorization. The launcher must admit the actual operator and genuine Job before
starting the socket; the owner must stop the service before removing its socket on cleanup.

The unit explicitly bounds CPU/memory/tasks/time/output, disables network/GPU/DB/NAS/auth
access, and permits writes only to precreated output members. A private tmpfs hides the
shared handoff parent; only this execution is rebound into the worker namespace. Root-owned
directories/inputs and the closed ACLs prevent creation/removal or input writes even though
the precise bind is writable for the existing output inodes. No model or policy is selected
from worker text. It accepts only CPU ordinals1/4/5 and exact installed configuration pins;
CUDA remains a separate mandatory physical-ownership composition, never a CPU fallback.

Both the existing INDEX/QUERY leaf and this benchmark leaf use one public CPU backend
composition, retaining mandatory installed admission and late optional ML imports. No
numerical encoding/codec/hash rule changes. Main reads the bounded invocation envelope for
channel construction; the existing worker capture independently rechecks the same stdin
identity/raw pin before reading documents or entering the backend. That is a separate
validation boundary, not repeated corpus/model materialization.

Dominant operations are exact FD/path/peer identity checks and one deadline-bounded accept;
fixed tuples and one selector suffice (O(path depth + envelope bytes), bounded memory).
No DB/index/migration/cache/dependency is added. A failed connection, changed socket,
expired deadline or wrong peer closes owned descriptors and fails before model entry;
it never restarts a unit or chooses another owner. Installed-prefix updates and current
source-admitted six-launch acceptance remain separate, explicit requirements. Socket and
service templates are source candidates only until their reviewed release is activated.
Benchmark admission must hold the existing owner CPU-capacity lock, not a new lock inode.
The existing stale-execution monitor must recognize this fixed benchmark unit too, so an
owner crash releasing flock cannot let INDEX/QUERY overlap its surviving worker. Extending
that deny/observation inventory is not a new dispatch or source-authority grant.

### CPU executable source checkpoint — 2026-10-17

Implemented the stdlib-first fixed CPU executable, exact nine owner arguments, bounded
stdin envelope adaptation, inherited nonblocking listener capture, real SO_PEERCRED plus
socket-epoch fencing, deadline/owned-FD cleanup and late admitted backend composition.
The old CPU INDEX/QUERY entry uses the same public backend composition with its original
arguments and receipt checks. No encoding/codec rule or released JSON Schema bytes changed.
The shared capacity monitor recognizes a surviving benchmark worker, but the old INDEX/
QUERY dispatcher still explicitly rejects a benchmark purpose.

Twelve related suites: **689 PASS41.02s**; strict mypy5 production modules, Ruff/format9,
both candidate unit syntax checks and diff checks pass. Source cases include wrong owner/
mode/deadline/socket mutation, real local Unix connections, missing/extra/invalid pins,
stdin identity/hash/CPU-only checks, lazy backend and close-on-failure paths, plus active/
orphan benchmark capacity refusal. The first Unix fixtures exceeded sockaddr_un's pathname
bound; short private paths fixed that. Their intermediate parent also inherited the shell's
group-writable umask; explicit private parent creation fixed the fixture, not production
permissions. Initial failures are not counted as PASS or kernel/root admission.

The opt-in root test adds a real native-UID acceptor and a separate workflow-owner UID/PID
client. It exercises only protected files/Unix peer capture, not PID1 activation or a model.
No benchmark template is installed, no numerical prefix is upgraded and no Job is submitted
at this source checkpoint. **Still required:** supported source/real-Job owner composition,
root per-launch environment preparation, admitted prefix successor, actual PID1/runtime
activation, CUDA ownership/entry, six measurements, original regression gates and C1–C5.

### Actual native/workflow-owner peer capture — 2026-10-17 06:18 UTC

Source candidate `5ef60fc36d67299277286f48d4efc77cf8f029e0` passed the standard API
three-wheel/RECORD build and was installed as a **passive owner** only. Numerical prefixes,
active CPU jobs, root GPU guardian selection, service templates and activation were not
changed. Existing EOM2 sudo authentication was reused; no fresh prompt or credential save.

Platform raw wheel SHA:
`f38dd3bbc348f40809fbf7db93ade4f5b1985622fa3c2569263929e33a16dcbf`;
API-contract raw wheel SHA:
`0ff7ec39617cc24ded79c0ddf45d59704f7e4ccf9a7b0e4e6fe059cd759d81f9`.
Build directory:
`/tmp/eom-api-build/5ef60fc36d67299277286f48d4efc77cf8f029e0.bMGoVP/dist`.

The exact source fixtures ran against that installed owner with no optional ML import:
**7 privileged cases PASS**, distinct from the689 source tests. Six reproduce actual
root/native-account DAC. The seventh permanently drops a real native CPU child and a
separate real workflow-owner client to their actual UIDs/GIDs, and verifies the kernel's
exact owner PID/UID/GID through the production Unix channel capture. The owner has only
the client connection, not the inherited listener; the native child cannot list the global
parent, owns only accepted/captured descriptors, leaves the borrowed listener intact and
closes its endpoint. No source/Job/Artifact authority or model is synthesized by this test.

This is **actual filesystem/Unix peer evidence**, not an actual PID1 activation, complete
namespace/sandbox proof, numerical-prefix admission, model timing or full benchmark PASS.
OS-local protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/5ef60fc36d67299277286f48d4efc77cf8f029e0/`.
Test stdout raw SHA:
`5eaec871b7792ef1070a6b95b1b013c3c50bf6997ac63a362685176bd6ed0bdd`.
No-replay root operator raw SHA:
`e4d5d4a4d245d3f5fc3897c09570be879897541cdb9dcd01abfa241ace2d16ea`;
local exit receipt `/tmp/eom-benchmark-cpu-os.3hTrb8kq/operator-result.json` reports0 and
`expected_seven_tests_passed=true`. All remaining execution responsibilities above stay open.

Routine observation06:10:42 UTC separately confirmed the existing INDEX/QUERY handles
remain live; read-only metadata showed later completed workflows and immutable revisions.
Encoding/binding rows465 and eligible-source545 are different denominators, not465/545
completion. The latest per-view revision rows are not a coherent whole-corpus coverage
audit. Original HTTP observer2895440 remains live/LOGIN; no new key, query, authentication
prompt or worker restart was submitted. Next routine observation not before06:40:42 UTC.

## Per-execution CPU environment preparation — design before implementation

The existing root handoff adapter owns this additional local materialization, not a new
registry or authentication mechanism. It accepts the exact prepared receipt/invocation,
the existing typed CPU installation pins, actual workflow-owner PID and bounded monotonic
deadline. It verifies the staged identity/raw hash and empty output namespace, the pinned
protected configuration and receipt metadata closure, and the real owner's UID/GID/start
ticks before creating anything. Reading SEALED metadata is not fresh installation admission;
the numerical entry still requires its existing independent installation reader/factory.

The canonical authorities remain the original Job/source/session and installed records.
The small returned receipt contains execution/Job identity, raw environment hash, owner
process birth/deadline, and `STAGED_NOT_LAUNCHED`, not a persisted grant or copied corpus.
The environment's eight fixed non-secret fields contain only validated IDs, hashes and
decimal integers. No shell, interpolation, worker-selected paths or mutable latest is used.

Exact execution lookup and bounded file/process reads are O(path depth + envelope/config
bytes), with constant field count. Existing descriptor-relative root/file validators and
exclusive creation are reused; no DB/index/cache/dependency is added. Concurrent preparation
has one file winner. Existing, partial or expired environments are explicit failures, never
truncated, rewritten or silently renewed. Configuration/file epochs and owner birth are
checked again after the exclusive write; late failure preserves the private candidate and
cannot authorize a launch. Application admission/claim/replay/cleanup remain outside this
adapter. Merely trusting the prepared dataclass or parsing receipt claims would be shorter
but would accept stale/forged identities; this staged closure is required before PID1 input.

### CPU environment source checkpoint — 2026-10-17

Implemented this preparation in the existing handoff adapter, without a new wire schema,
dependency, registry or dispatch route. Existing handoff receipt construction now has one
authoritative function; schema-validated inputs still determine all pins. The current CPU
configuration1.1 and predecessor1.0 are tested without conversion or implicit latest.

Eleven source suites: **589 PASS14.46s**, strict mypy1, Ruff/format4 and diff checks PASS.
Nine privileged cases are deliberately SKIP in this source invocation, not OS PASS. Tests
cover concurrent exclusive creation, forged prepared metadata, rehashed-but-different
runtime closure, changed config/receipt/schema/staged files, used output, invalid PID or
deadline, CUDA refusal, late process birth change and partial-write preservation. Current
process reads are real but unit installation/process fixtures are synthetic claims only.
Two failed suite invocations named a nonexistent test file; neither ran tests or counts as
PASS. Corrected inventory produced the result above.

The two new opt-in root cases use a real exec'd workflow-owner child and test root-only
environment access and owner exit after writing. They do not launch a benchmark, submit a
Job, admit a source or execute a model. Actual protected OS results are recorded separately
after the candidate wheel is built and installed passively. Source/real-Job admission,
compatible numerical prefix, PID1 activation, CUDA entry, six measurements and C1–C5 remain
open. Existing active services, model defaults, historical outputs and authentication are
unchanged by this source checkpoint.

### Actual root environment gate — 2026-10-17 06:35 UTC

Candidate `409e19879760fb49bf9e690877d91ecfa904d39b` passed the standard three-wheel/
RECORD build and was installed as a **passive owner only**. The same protected OS suite
now passes **9 cases** against the installed wheel, without optional ML imports. Besides
the seven earlier DAC/actual-peer cases, it verifies an exclusive root600 environment for
a real exec'd workflow-owner child, refusal of named reads by both worker accounts, and
owner exit after writing: that candidate remains private and no launch receipt is returned.
Synthetic configuration metadata remains synthetic even in these actual OS cases.

Existing EOM2 sudo authentication was reused without another prompt. No active service,
numerical prefix, template, source/Job permission or CPU/GPU default was changed. No model,
benchmark invocation, DB Job or NAS Artifact was created. This is not full source/Job
admission, actual PID1 activation, numerical-prefix admission or six-launch acceptance.

Build: `/tmp/eom-api-build/409e19879760fb49bf9e690877d91ecfa904d39b.dPwYFv/dist`.
Platform raw wheel SHA:
`01650b822934309af91025a29531e6bc987166d58854ce5eb4ff183613b61615`;
API-contract raw wheel SHA:
`9718ec9af938fcb721963cc63610cd611f1a086558f1df4fb5b928cd8bbcf91f`.
Protected OS evidence:
`/opt/eom/embedding-benchmark-os-evidence/409e19879760fb49bf9e690877d91ecfa904d39b/`.
Test stdout raw SHA:
`f344ebc87c313af7ebeb2e68fd1392e2e1cde3c3568c60f3524729e5e31239bd`.
No-replay operator raw SHA:
`6813fa26f8d5794ac58f104db134b3a3d4e81bea501ec1bf33b942662a442d86`;
local exit receipt `/tmp/eom-benchmark-environment-os.nMcR7mq1/operator-result.json`
reports0 and `expected_nine_tests_passed=true`. Earlier evidence remains unchanged.

## Actual operator/source admission — design before implementation

The Catalog boundary must resolve an already committed benchmark-input member, not trust
worker text or an audit actor string. Trusted composition supplies the existing opaque
Identity session capture and authenticated-session fence. The benchmark audit identity
must equal that real operator, with current WORKFLOW_START and the existing source-read
permissions. A service-indexing identity is not silently promoted to benchmark operator.

The existing snapshot source adapter reconstructs only the exact six selected Item
revisions under the same root transaction and pinned Graph/policy. It retains current
source/report locks and uses its existing batched Artifact resolver and deterministic
accepted-report projection. The new thin adapter compares every profile/source/report/
Graph pin and selected document/query text with that canonical projection, then resolves
the committed input Artifact through the same typed reader. Missing reports, extra/missing
profiles, unavailable views, stale sources or changed bytes are explicit errors, not an
implicit latest or full-corpus search. Token witnesses remain numerical-worker checks;
source admission does not claim a tokenizer/model/runtime admission.

Primary access is one bounded six-revision selection and keyed profile/source lookups.
The maps/sets require O(P + R + input bytes) time and O(P + R) metadata, with P=6 and R≤20;
only the explicit input boundary materializes the staged texts, at most64MiB. No source
content is copied into a Job row. No DB schema, new queue, mutable cache, dependency or
worker authority is introduced. This Catalog adapter depends on public Identity and
existing Catalog application boundaries; workers still have no DB/NAS access. It returns
an owner-local value valid for the caller's current root only. Submission/launch/replay
must reauthorize in their own current roots; parsing or persisting this result grants
nothing. The simpler approach of comparing hashes in the worker cannot establish current
operator permission or canonical accepted-report lineage, so it is insufficient.

### Original benchmark Job registration

The Orchestrator registers one original benchmark Job using existing Jobs/events/protocol
storage, not a new table or worker queue. Its request is the released owner-request1.0
pointer metadata; staged corpus text is never a DB payload. A trusted Catalog admission
context retains current root source/session locks through the mutation and rechecks scope
and expiry before returning, without rereading/hashing immutable input bytes.

The unique idempotency key is the benchmark logical ID plus immutable revision, not a new
random key per retry. A changed request for that identity is a conflict. Under a nonblocking
namespaced PostgreSQL transaction lock, the existing repository registers the exact
protocol SHA and creates the Job once. Existing unique constraints remain the durable
backstop; a busy submit returns an explicit error, never another attempt. Key lookup is
indexed O(log J); initial validation events are constant size. This short submission lock
serializes a bounded administrative operation, not workers or CPU/GPU capacity. No DB
migration, persistent lock/queue/framework or dependency is introduced.

New Jobs stop at VALIDATED until an admitted real launcher takes responsibility. No
CLAIMED/RUNNING/SUCCEEDED, worker slot, output Artifact or launch permission is synthesized.
Replay reauthorizes the current operator and exact sources, validates the complete original
Job closure and returns its actual historical state, including terminal failure. Any error
requires caller root rollback; there is no nested independent commit or retry. Trusted
composition supplies the actual Catalog adapter, not a model-selected callback or boolean
grant. This admission port is the Catalog/Orchestrator adapter boundary, not a plugin API.

### Source/Job implementation and disposable concurrency checkpoint — 2026-10-17

Implemented the actual Catalog source adapter and Orchestrator Job-registration use case.
The adapter uses the existing opaque authenticated-session fence, official GraphRAG
snapshot resolution, accepted-report projection and pinned Artifact reader. Every selected
profile/source/report/Graph and document/query text is compared; input token witnesses are
still a later numerical-worker responsibility. Registration persists only released pointer
metadata, reserves output identity without publishing an Artifact, and stops at VALIDATED.
Replay checks original request/hash/protocol/task plus both initial append-only events,
returns the same Job and preserves historical failure. No launcher/worker admission is
inferred from registration. Late scope/expiry checks stay within the original root.

Seven focused source suites: **346 PASS19.22s**; four PostgreSQL cases deliberately SKIP
in that source invocation. Strict mypy2 and Ruff/format6 pass. The current source and Job
tests themselves cover36 cases. Initial source tests caught a genuine parser-budget bug:
staged inputs were parsed with the default64KiB envelope bound. The adapter now explicitly
selects the released64MiB staged-input bound, without loosening the protocol. Invalid JSON/
schema input is mapped to a stable code instead of exposing a full validation dump. The
SQLite storage fixture initially returned int1 for a boolean SQL function; the SQL expression
is now explicitly typed Boolean and still requires `is True`. It is not PostgreSQL proof.

Actual marker-guarded temporary PostgreSQL: **15 PASS**, including four new Job cases for
one original/replay, simultaneous submission BUSY then original replay, late authorization
failure rollback/lock release, and preservation of FAILED plus payload-conflict refusal.
The other11 existing encoding reservation/privilege tests also pass. Source authority in
these storage cases is deliberately synthetic, not an authenticated live operator/source
or model benchmark. The first invocation was14 PASS/1 FAIL because the one-off driver
omitted the supported post-migration runtime-role reconciliation and `runtime.env` did not
exist. The failure is preserved. Supported reconciliation of the **same temporary DB** and
one corrected invocation produced15 PASS; no production workaround or row repair was used.

The temporary DB and its temporary roles/credential files were then removed by the guarded
cleanup; operational source data and history were untouched. Evidence remains protected at
`/opt/eom/embedding-benchmark-os-evidence/job-storage-xGCk8OqE/` (original failure) and
`/opt/eom/embedding-benchmark-os-evidence/job-storage-xGCk8OqE-reconciled/` (PASS/cleanup).
Final test stdout raw SHA:
`e88f906cc98cb0de178098ed9bb4a698cab184f301017cc0c572ac1565705e12`.
Reconciliation operator raw SHA:
`08b87c8a1f1db76bfa61f10464584c2d530d5c3269457534d7d22353ea6dfa08`.
Local exit receipt `/tmp/eom-benchmark-job-db.xGCk8OqE/reconciliation-result.json` reports0.

No live benchmark Job, model execution, numerical-prefix upgrade or active release/default
change occurred. The source/runtime owner entry, current operator connection, real input
Artifact preparation, admitted six launches and C1–C5 remain open. Existing HTTP observer
remains live with safe state LOGIN: authentication success is not claimed and no new
prompt/key/request is created. Routine06:41:17 metadata separately shows473 encodings and
bindings,125 index revisions and6 logical indexes; recent per-view counts171/145/157 share
eligible545 but do not establish coherent corpus completion or473/545. Existing INDEX/QUERY
processes remain live. Next routine observation is not before07:11:17 UTC.

### Passive installed source/Job adapter — 2026-10-17 06:52 UTC

Source `9500e325fa89edba2362a295463acf1fda4986cb` passed the standard API three-wheel/
RECORD build. The exact platform/API-contract wheels were installed in its passive owner
prefix only. An isolated installed import verifies both new modules' exact source-file SHA,
rejects an actor string in place of a genuine Identity capture, and imports no Torch, NumPy,
Transformers or tokenizers. Static mypy also verifies concrete Catalog/Orchestrator port
compatibility. These checks do **not** establish a live authorized source read or launch.

Build: `/tmp/eom-api-build/9500e325fa89edba2362a295463acf1fda4986cb.JgNfdO/dist`.
Platform raw wheel SHA:
`4b606527db78d948987d289d47e00e2644a3924c2d7ab330af14fb7a68f1318f`;
API-contract raw wheel SHA:
`2a609088d46ddcf33879201342fdb1d0b15813cc37d4a1517298f527518a9667`.
Evidence: `/opt/eom/embedding-benchmark-os-evidence/9500e325fa89edba2362a295463acf1fda4986cb/`.
Import stdout raw SHA:
`976b3235e17a0242ab033188392efb6164e6857089c60ea9459831adcf333b2a`;
operator raw SHA:
`e4295e8cbe72d6bc7d1bc49bddd3b1d9755eb33e18329f913dcf94032745ccc6`.
Local receipt `/tmp/eom-benchmark-job-owner.dRRFygLW/operator-result.json` reports0.
Same EOM2 sudo reused, no extra prompt or credential save. No active selector, numerical
prefix, service, worker, live Job, model, GPU/CPU default or historical product was changed.
The remaining launch/activation/measurement/consumer requirements above are unchanged.

## CUDA model backend composition — design before implementation

The existing native factory already supports CUDA but requires both independent installed
admission and actual physical ownership. The missing CUDA composition must bind the
concrete protected CUDA receipt reader and the already opened device/retained-lease
adapter; a CPU receipt, parsed config, callback returning true, or probe PASS is insufficient.
This is an installed numerical infrastructure adapter, not source/operator/Job admission.

Inputs are the existing frozen root-local configuration pin (logical/revision IDs, semantic
and raw hashes), exact CUDA receipt raw SHA and a borrowed concrete device-access scope.
The fixed CUDA process identity is checked before metadata/optional imports. Ownership is
checked before the protected installation reader, before/after backend construction/use
and on exit. The shared native factory still owns model lifetime, actual bundle/proof/host
resolution and its unchanged float32/QUERY/DOCUMENT semantics. No numerical rule, schema,
device fallback, default, dependency, queue, DB/index or mutable cache is introduced.

This adapter neither acquires nor closes the caller's borrowed GPU/device scope. Caller
must already obtain the existing mandatory root lifetime ACK and retain ownership beyond
backend close, until terminal/driver cleanup is proved. A failure never retries CPU, renews
the lease or interprets probe metadata as model permission. Constructor/body/close errors
propagate and cleanup uncertainty remains a failure. Access is constant-size pin lookup
plus existing bounded installation resolution, with no copied model/payload or new scaling
structure. Trusted native composition supplies these values, not worker JSON. A direct
factory call with only a structural ownership callback would be shorter but would omit the
required concrete reader/device binding. Actual CUDA entry/ACK/activation and six launches
remain subsequent requirements; source tests cannot prove real GPU admission or timing.

### Concrete CUDA backend source checkpoint — 2026-10-17

Implemented `native_cuda_backend_scope` with the existing protected CUDA installation
reader, exact root-local configuration/receipt pins and concrete opened-device ownership.
It uses the unchanged native factory/encoder and checks ownership before installed capture,
before/after model scope and at exit. It never closes the caller's borrowed physical
ownership, switches to CPU, treats a probe as compute authority or skips installed checks.
CPU composition, numerical implementation bytes and released schema bytes are unchanged.

Eight related suites: **295 PASS26.38s**, including21 focused CUDA-composition cases;
strict mypy1 and Ruff/format2 PASS. Fixtures cover constructor/body/backend/admission-close
and ownership-fence failures, invalid/mutated pins, structural ownership callback refusal,
no default ownership/receipt, and preservation of borrowed ownership after every outcome.
A fresh actual API-interpreter process imports the stdlib-first module and rejects its
wrong native identity before importing Pydantic/catalog contracts or optional ML modules.
That is an actual wrong-identity negative, **not** successful CUDA installation/device/
model admission. All positive lifecycle fixtures remain synthetic source evidence.

This is source backend composition, not an activated CUDA executable. The actual CUDA
entry still needs distinct benchmark pre-initialization retention/ready/root-ACK handling;
the installation-probe message/zero-model outcome must not be repurposed as a benchmark
launch or model success. Fixed unit/namespace/retirement integration and compatible prefix
installation must be completed before model execution. Actual operator/source preparation,
six launches, timing/default decision, original remaining image/trainer regressions and
C1–C5 consumers remain open. No live unit, prefix, model, Artifact or default changed.

## CUDA executable and pre-initialization root ACK — implementation plan

The next executable is the fixed CUDA benchmark leaf, not a repurposed installation probe.
Its root/PID1 transport must be implemented before actual private-data inference:

1. Define the small `embedding-benchmark-cuda-ready/1.0` JSON Schema2020-12 before worker
   behavior. Reuse existing configuration-pin, device-capture and FD-descriptor value types,
   but do not serialize a fake probe input/result. Bind real Job/execution identity, exact
   invocation raw hash, configuration/receipt pins, process birth/UID/GID, retained-store
   name, device capture and zero initialization/model/tokenizer/forward counters. The small
   canonical self-hash is identity only, not root acceptance or compute permission.
2. Keep the existing benchmark1.0 invocation/result/channel and numerical rules unchanged.
   The operational readiness member is fixed `cuda-ready.json` in the root-owned execution
   directory, **outside** the canonical4/16-member numerical output namespace. Root precreates
   it once with native ownership and workflow-owner read group, no create/unlink permission.
   Only this member and precreated outputs become writable in the private worker namespace.
3. Fixed CLI values come from the protected per-execution environment and PID1-opened input
   and listener, not worker JSON paths. Share only the actual common CPU/CUDA CLI/input
   adaptation through a small public value/parser, preserving existing CPU behavior. Block
   root-ACK signals before optional imports; check exact native CUDA identity before loading
   metadata, and retain the existing diagnostics suppression and absolute owner deadline.
4. Acquire the **existing** shared physical lease and request PID1 retention before CUDA
   initialization. Existing O_PATH device/lease capture supplies untrusted descriptor hints;
   no constructor or initialization is permitted before root ACK. Read only protected pinned
   config/proof metadata needed for readiness, with current epochs and no implicit latest.
5. Root independently verifies the exact new unit/template policy, MainPID/start ticks,
   credentials/capabilities/cgroup and executable/host closure, real worker lock and PID1
   retained descriptor, actual device mapping and competing clients. Reuse the existing
   physical-FD observation adapter via a typed benchmark-specific entry, not fake probe
   metadata or an enlarged arbitrary-template allowlist. Source/session/Job authority stays
   with the supported Orchestrator owner; root observation itself grants no source access.
6. Native wait accepts only the reserved signal from kernel-observed UID0, bounded by the
   absolute deadline and existing30-second observation ceiling. Missing/wrong/late ACK fails
   without model construction, CPU fallback, reconnect, new identity or lease renewal. Only
   after ACK may the concrete opened-device scope and CUDA backend composition run. It uses
   the existing owner channel/checkpoints/resource finalizer; actual owner resource readback
   remains mandatory for the frozen1.0 result and timing gates.
7. Close model/backend before borrowed device resources; close only the process's original
   lease description. PID1 retention must survive failure/exit. The existing root terminal,
   driver-client, retained-store retirement and exact-inode handoff checks govern physical
   release; unknown cleanup blocks the next launch and never becomes success.

This is bounded keyed execution lookup, fixed-size readiness IO and the existing ordered
checkpoint stream; no DB migration, new queue, model service or general plugin framework.
Root/native transport and actual current source authorization remain separate adapter
owners. No large payload is copied into DB, no readiness path is caller-selected, and no
worker can access DB/NAS/credentials or sibling executions. Readiness fixtures and API-user
identity negatives are not physical CUDA or source-admitted benchmark acceptance.

Finish the concrete CUDA entry/root-observer/unit and CPU privileged-preparation bridge
before a coordinated compatible numerical-prefix successor. Do not repeatedly update an
active prefix for source-only helper increments. Current INDEX/QUERY and prior accepted
policies stay pinned until explicit release/rollback and native admission gates pass.

### CUDA readiness protocol and shared root FD observation source checkpoint

Defined additive `embedding-benchmark-cuda-ready/1.0` schema/frozen model before a CUDA
worker can emit it. It reuses existing small configuration/device/FD **value definitions**,
not a fake probe message. The new message binds Job/execution/invocation raw hash, pinned
configuration/receipt, process identity/birth and pre-initialization zero counters with its
own semantic hash. Canonical bytes, bounds, duplicate keys, coerced counters, extra authority
fields, aliased descriptors and rehashed cross-Job/device pointers are rejected. Parsing
still cannot acknowledge a GPU, establish a genuine Job or authorize model computation.

The existing root physical-FD observer now has a distinct typed benchmark entry. It binds
the exact benchmark execution unit and checks both real worker lock and PID1 retention
using the same private physical checks as the unchanged probe entry. No arbitrary-template
registration, fake probe, source grant, signal or lease acquisition/release is added. The
benchmark model is imported only for that new branch. Existing image/probe entry imports
remain unchanged; a fresh-process test checks no new readiness or optional ML import.

Related9 suites: **425 PASS20.71s**, strict3 production modules PASS. Separate Catalog
resource/new-readiness/frozen-benchmark contract suites: **268 PASS10.89s**; these overlap
and must not be added together. Ruff/format and exact schema mirror/hash checks PASS.
Schema raw SHA: `c902ead02b103dcff6304cf9fbb9c9e47fcd5db1e23f6e158a7c2660d3913a10`.
An initial import named a nonexistent codec module; it was corrected to the existing public
ROOTLOCAL codec, not another parser. One dependency test initially prohibited the old
benchmark contract too, but the predecessor public package already exports it at
`eom_catalog_contracts.__init__`; the test now protects the actual added lazy-readiness
boundary without claiming removal of that pre-existing dependency.

All readiness/FD positive fixtures are synthetic, not actual root/GPU/source admission.
The kernel FD algorithm itself is reused, not weakened. CUDA executable/ready member writer,
root unit/process/host/source admission and ACK, namespace/terminal retirement, compatible
prefix and actual six launches remain required. No native unit or numerical prefix has
been updated for these source changes; model executions remain0 at this checkpoint.

The preceding CUDA backend candidate `7bc16caef857afab7c32a54ed57de8cd1b43eddb` passed its
standard three-wheel/RECORD build. A fresh isolated API interpreter imported its **wheel**
module with exact member SHA and refused wrong native identity before metadata/ML imports:
`/tmp/eom-benchmark-cuda-composition.JvOuEwWM/result.json`. It is BUILD_ONLY, not installed
native admission. Build `/tmp/eom-api-build/7bc16caef857afab7c32a54ed57de8cd1b43eddb.yplcHO/dist`;
platform raw wheel SHA `2d3c2ca82618b0b66da926d59c943556ba47bd03b9c12311574a1ba4a0b9ebbf`,
API-contract raw wheel SHA `809f3c96ae37655a5bda96f0aa340344cad1c4456935897ef9792e497f6bcc0c`.

Routine07:12:24 observation reused the already installed protected read-only observer,
without a new root script installation. Existing INDEX3633849 and QUERY3633843 are live;
metadata shows485 encodings/bindings,128 index revisions and6 logical indexes. The latest
per-view rows175/149/161 with eligible545 do not prove whole-corpus coverage or485/545.
Two newer workflows completed, one is RUNNING and two REQUESTED with no failure code in
that bounded projection. Original HTTP observer2895440 remains live/LOGIN; no authentication
success, new prompt/key/request or restart is claimed. Next routine check≥07:42:24 UTC.

### CUDA executable and fixed unit source checkpoint — 2026-10-17

The fixed CUDA leaf now composes the existing physical GPU lease, PID1 retention request,
typed readiness writer, root-only ACK wait, opened-device scope, exact workflow-owner peer
and existing benchmark worker/backend. The order is retention → sealed readiness → root
ACK → device R/W ownership → exact peer/channel → model scope. Backend/channel/device
resources close before the process's original lease; PID1's retained copy is never unlocked
or removed by the worker. Failure never falls back to CPU, reconnects, creates another Job,
renews a deadline or represents an installation-probe outcome as benchmark success.

Readiness is one precreated native-owned, workflow-readable 0640 member in the execution
root, not a numerical output. The writer validates actual process credentials, invocation/
Job identity, descriptor/name epochs, no symlink/hardlink/ACL and initially empty bytes. It
writes canonical bounded bytes once, fsyncs and reads them back; partial IO/uncertain close
poisons the local scope and preserves the failed bytes. Subsequent mutation is refused.
The frozen numerical output set remains exactly4/16 members, with its original byte budget.

CPU/CUDA now share only the small stdlib launch/config pin values, exact nine-argument
parser and owned activation-FD lifetime. The existing public CPU pin name is a compatibility
alias. CPU input/backend logic, numerical codecs, float32 rules and existing released
request/result/channel schemas are unchanged. The CUDA source templates use the exact
execution's protected launch.env, private handoff-parent mount, one PID1 listener, four
explicit GPU device rules and existing resource bounds. They have not been installed or
activated. No new dependency is added: only the existing optional GPU-runtime lease package
is used in the selected CUDA leaf; API/CPU fresh imports do not load it or optional ML.

ACK waiting keeps SIGUSR1 reserved and observable in /proc by consuming with zero-time
sigtimedwait rather than blocking in that syscall. It rejects a preexisting signal at main
entry and later checks the actual sender's UID0/PID and the earlier of the absolute deadline
and30seconds. A legitimate root ACK already queued after readiness is accepted, rather than
mistakenly rejected as stale. No model code runs on missing/nonroot/late ACK. A real ordinary-
UID child test samples its /proc SigBlk five times during the wait and proves that this
process's nonroot signal is refused. That is an actual OS **negative**, not a root/GPU
positive. Source positive ordering/lifetime cases use explicitly synthetic doubles.

Nineteen focused/regression suites: **885 PASS53.39s**, strict mypy7 production modules,
Ruff/format10, exact diff checks and both CUDA source-unit syntax checks PASS. Coverage
includes constructor/body/close/retention/ACK/device/channel failures, fixed file IO and
replacement, invalid activation/deadline pins and borrowed lease/descriptor lifetime. Fresh
API-interpreter import/bad-CLI/wrong-native-identity negatives import neither Pydantic nor
optional ML/GPU packages before the guard. The initial three handoff layout fixture failures
were the expected newly declared CUDA operational member; the corrected test checks its
exact conditional presence, empty bytes/mode/link count without relaxing numerical members.
One malformed-proof fixture expected ValueError instead of the existing JSON Schema error;
only that expectation was corrected. No parser/authorization guard was weakened.

This checkpoint is **SOURCE_PASS / NOT_ACTIVE**. It does not claim a real source-authorized
Job/model, root signal, PID1 socket activation, CUDA performance measurement or installation
receipt. The remaining mandatory composition is the actual root unit/process/host/source
ACK owner, protected CUDA launch environment and terminal retirement bridge, compatible
numerical-prefix successor and all six fixed launches. Existing INDEX/QUERY, CPU default,
accepted Artifacts and historical failures are preserved. C1–C5 actual consumer gates and
the full goal remain open. User replies saying authentication was entered are not counted
as success while the original observer's published state is still LOGIN; no duplicate
login process/request or credential persistence is introduced.

The `eff3b87155be37126a78618c682dd449c8964134` candidate passed the standard three-wheel
build and RECORD inspection. An isolated API-interpreter child imported the CUDA leaf
directly from that platform wheel, compared all7 changed/new production members and the
packaged readiness schema with the checkout, and rejected the actual wrong native identity
before metadata/ML imports. It intentionally left stdout/stderr discarded; the independent
parent observed exit0 and emitted only verification metadata. An earlier reporting wrapper
incorrectly expected output after that deliberate quiet boundary; it exited0 with empty
output and did not indicate a native/model failure. No leaf diagnostic restoration was added.

Build-only directory:
`/tmp/eom-api-build/eff3b87155be37126a78618c682dd449c8964134.CIRQrC/dist`.
Raw platform wheel SHA `8c79174844af19d0131ba0e75c10b7fb7f2c4867ede780c7b0c9aa4ce8486d70`;
API-contract wheel SHA `7fbce06c599aba2494a134f6663726dcf96e820343b8997c93495b7d3ba70cf7`.
This is not installed prefix/source-authorized Job/GPU positive evidence. Milestone Slack
sent `devreport_1433d08fc62e4f5a976d0871b9cb8b0c` at07:33:58 UTC explicitly retained that
distinction and the outstanding six-launch/consumer/full-goal scope.

### Protected CUDA launch environment — design before implementation

Extend the existing fixed root preparer rather than add a second launch queue or writer.
Both devices need identical eight nonsecret fields, O_EXCL/root0600 materialization, exact
handoff/owner process-birth checks, absolute180-second bound and pre/post file epochs.
Use one device-neutral immutable preparation result and pin value; preserve CPU public
names as compatibility entry points that still refuse CUDA input. Runtime profile comes
only from the validated frozen invocation, never a new caller-selectable flag or default.

CUDA differs only at the protected installation metadata boundary: parse the exact pinned
config and receipt2.0/2.1 plus the exact versioned receipt schema, and bind configuration,
bundle, installed proof, numerical runtime and host-extension pointers. Share receipt
version resolution with the existing native CUDA installation reader through a public
metadata-reading function; do not copy its dispatcher or reinterpret CPU receipt1.0.
This is bounded keyed lookup plus a single exclusive file write, with no DB/schema/queue
change or stored vectors/content. Metadata reading and preparation remain non-admitting:
actual host/prefix/unit/source/Job/lease checks and independent root ACK are still mandatory.
No protected prefix or template changes during source tests. Partial/late failure leaves
the execution and original file intact; no overwrite, renewal, implicit latest or retry.

### Shared protected preparation source checkpoint — 2026-10-17

Implemented `prepare_benchmark_environment` for the validated fixed CPU/CUDA profiles;
the original CPU-only function/result names remain compatible and still reject CUDA.
One exclusive writer retains the same eight fields, owner UID/GID/birth rechecks, protected
root0600 file and failure preservation. A public `read_pinned_cuda_admission_receipt`
metadata function now serves both this preparer and the existing native installation
reader. It resolves only exact receipt2.0/2.1 and versioned schema pins; full host/prefix/
device admission stays in the unchanged native reader stages, not this small helper.

Ten related suites: **366 PASS31.02s**, including25 focused CUDA-preparation cases;
strict2 and Ruff/format5 PASS. Synthetic local-IO cases cover both receipt versions, exact
field/mode/member sets, rehashed cross-configuration/bundle/proof/runtime/host mismatches,
wrong receipt/schema/raw bytes, the CPU-only facade, concurrent O_EXCL preparation and
owner exit before/after materialization. Late failure preserves the original bytes and
prevents renewal. This is not actual root/PID1/installation/model admission.

The broader CUDA regression run first found a historical test that treated the entire
extensible registry minus its own additions as exactly330 predecessors; the additive ready
schema made that331. The test now selects its original330 names explicitly using the
existing frozen323-name fixture plus the exact7 historical successors. Its original
semantic digest `cee7697e19c0d4e2ae0c9f9bebe8495dbf0fb155f2cfa5f07af60479b83a12c7`,
count330 and every old canonical schema SHA remain unchanged. Future additions do not
redefine that historical family; no prior schema bytes or expected hash were updated.

No protected prefix, template, active policy, existing Job/Artifact or service changed.
Root source/unit/process/host ACK and terminal retirement composition, coordinated
compatible prefix successor, six actual measurements and consumer gates remain open.

Candidate `94b901bed02e837af404da94ce6acdd16d37533c` passed standard three-wheel/RECORD
build and isolated API-interpreter imports of the actual wheel's two changed production
modules, with exact checkout byte comparison and no optional ML/GPU package import.
Build `/tmp/eom-api-build/94b901bed02e837af404da94ce6acdd16d37533c.mdvUkN/dist`;
platform raw SHA `d9ec41f3b1641c235ff9d2b53909e3e30e09b88694575b568c28343cb945ed86`,
API-contract raw SHA `b245929dbcf33d80c650c5c3e43d6e3b636c29c1b69d6917e3162d57c8c490b5`.
BUILD_ONLY: neither this import nor metadata preparation is protected runtime activation.

### Benchmark CUDA root readiness observation — design before implementation

Add a benchmark-specific read-only root observation, not a relabelled installation probe
or image unit. Bind exact installed service/socket bytes, protected per-execution invocation/
launch.env and native-owned ready member, actual unit invocation/MainPID/birth, reserved
signal, argv, UID/GID/capabilities, empty loader cwd, cgroup and executable mappings. Reuse
existing host/prefix ledgers, physical worker/PID1 FD observer and GPU-client query. Pin the
root-selected configuration/receipt/device independently of ready claims. Recheck both
sides of every live observation and hold captured file epochs through the caller's final
readback. A typed observation is OS evidence only; it does not validate an original Job or
replace actual operator/source authorization, installation admission or the later ACK owner.

Two existing responsibilities become shared without widening their callers: native CUDA
UID/GID/capability parsing is a pure process-identity function, and image/benchmark effective
GPU unit policy uses one bounded reader with two explicit account/template families. Keep
old image/probe wrappers/error meanings and exact old positive/negative tests. No arbitrary
unit registry, device allowlist, callback-granted authority or new queue/framework.

Dominant access is fixed keyed filesystem/unit lookup and a bounded ordered kernel snapshot;
file epochs and immutable mapping/FD values avoid repeated prefix/ELF hashing or model/text
copying. No DB/migration/worker wire schema changes. Only root can observe these properties;
all external files/kernel output remain untrusted. Missing, changed, late, competing-client,
wrong-peer/source or unknown cleanup blocks ACK; an observation never resets/stops a unit,
signals a process, mutates a Job, releases the lease or fabricates an Artifact. The simpler
fake-probe conversion would conflate installation testing and model computation and is
therefore not used. Effect/retirement composition must retain distinct original outcomes.

Readiness publication must not race a partial write to the precreated member. The native
writer holds a separate exclusive flock on that readiness file until its successful close;
this is not the GPU lease and never replaces/unlocks that physical guard. Root first treats
an empty file as NOT_READY without locking it, then uses a nonblocking shared file lock to
read a nonempty member. A writer-held lock is also NOT_READY, not malformed JSON or permission
to restart. Thus the writer cannot conflict with root reading the initial empty file and
root cannot parse partial bytes. Named/held epochs and canonical/hash validation still apply;
all owned readiness descriptors close on every outcome. Released worker wire bytes and
the numerical output namespace do not change. Unexpected concurrent writers fail closed.

### Root readiness observation source checkpoint — 2026-10-17

Implemented the distinct read-only benchmark observer. It binds installed service/socket
raw hashes, root0600 invocation/environment, configuration/receipt/runtime pointers and
native0640 readiness, actual MainPID/birth/cgroup/argv/cwd, reserved single-thread pre-init
frame, effective policy, executable ledger, worker/PID1 physical locks and no GPU clients.
Checks are repeated before return. It never signals/stops a unit, registers a Job or grants
source/model permission. The guarded launcher still needs actual operator/source/Job
admission and a separate durable ACK/terminal-retirement owner before six model launches.

Pure CUDA credential validation and the two closed GPU policy families are shared with
the existing probe/image observers; their old refusal cases/error meanings are preserved.
The eight-field environment encoding and nine CLI arguments also have one authoritative
serializer. Two reviewed Python entry/publication member hashes are checked against the
existing prefix inventory in addition to executable mappings: Python source does not
appear in /proc executable maps. Old/missing writer code cannot silently opt into the new
readiness-flock protocol. That metadata match is necessary, not proof of a full byte audit.

Final17 related suites: **681 PASS45.74s**, strict8 production modules, Ruff/format13 and
diff PASS. Included42 observer cases,28 shared-policy cases,8 actual unprivileged readiness
file/flock cases and the existing image ACK/retirement, probe and CPU/CUDA regression tests.
Actual local IO proves partial native writes stay exclusively locked, root shared readers
wait without parsing, borrowed writer locks survive failed reads, empty/locked files are
pending, invalid shapes are refused, owned read locks close, and competing writers poison
their scope without overwriting. A fresh actual API-identity child is refused at the root
guard before file/process observation, with no optional ML imports. Positive root/unit/
GPU/resource cases are explicitly synthetic; they are not actual root/GPU acceptance.

The first image-fixture run still mocked the old subprocess boundary after policy extraction,
causing13 failures and possible ordinary-UID read-only systemctl show calls; no start/stop/
signal was issued. Its fixture now mocks the actual shared adapter, preserving all negative
assertions. A fresh-process test's initially missing os import was corrected; final681 is
from one complete subsequent run. No guard, old schema/hash or numeric rule was loosened.

Routine-read diagnosis also found a scratch operator.py shadowing Python's standard operator
module when maintenance scripts were invoked without isolation. Use the explicit interpreter
with **-I -B** for standalone scratch-directory operators. The failed non-TTY sudo attempt
remains `/tmp/eom-image-joint-release.FLrlFoWI/index-observation-0742.json` with auth-required
return1; credentials were not requested or stored. Corrected same-TTY execution reused the
already installed observer and succeeded at08:08:29 UTC without new root helper installation:
`index-observation-0808.json`. Counts501 encodings/bindings,132 index revisions/6 logical
indexes; latest per-view counts169/179/153 with eligible545 are not501 unique Items or a
coherent full-corpus snapshot. Latest bounded workflows show4 completed and1 running without
failure codes, not a global zero-failure assertion. Original queries/Jobs were not restarted.

This checkpoint is SOURCE_PASS, not installed activation or GPU performance/default PASS.
Only ordinary local test/operational evidence was produced; no protected prefix/template,
production Job, model, Artifact, policy or CPU default was changed by this implementation.

Candidate `dd756f6a9b972a111efff730e7afae8005a1e304` passed standard three-wheel/RECORD
build. An isolated API-interpreter process imported the actual wheel's observer, compared
all8 changed/new production members with the checkout, checked the two native entry/writer
code pins against wheel bytes and refused its actual nonroot identity before observation.
No optional ML/GPU import occurred. This is BUILD_ONLY plus an OS identity negative, not
an installed root/GPU positive. Build:
`/tmp/eom-api-build/dd756f6a9b972a111efff730e7afae8005a1e304.UTxgWS/dist`.
Raw platform wheel SHA `47691d6cd9ab961923c06dc9b964c76eedd6a8fb40b3b58467fcc9172600087f`;
API-contract wheel SHA `3c191f2b38433cab6ad55730783bd2b223e923028018e099cc9af6aa14f18d36`.

### Durable ACK and terminal cleanup — design before implementation

Use the existing image lifetime design: reserve an original unit/invocation/phase once,
fsync intent before a single effect, reobserve identity immediately before the effect,
then fsync the result. Extract only its protected phase-directory and exclusive small-file
IO into a shared infrastructure adapter used by image and benchmark owners. Callers retain
typed observation validation, fixed roots, event meaning and serialization; the byte writer
grants no unit/source/Job permission. No broker, queue, mutable registry or new worker wire
protocol is needed. Preserve existing image record bytes and stable error meanings.

The benchmark ACK is a distinct typed root observation/result, never an image/probe value.
It reobserves exact pinned files/live frame before emitting SIGUSR1 only to the original
fixed unit main. Existing operator/source/Job admission stays with the Orchestrator caller.
An uncertain command or record write retains the intent; O_EXCL prevents automatic replay.
Cleanup has separate terminal evidence and preserves actual success/failure/timeout status,
empty cgroup, retained physical descriptor and driver-idle proof before any stop/reset/clean.
After release, independently acquire the same inode and recheck actual stopped state. Never
unlock a borrowed GPU description, rewrite a failure, or infer cleanup from an observation
timeout. A failure after retention but before readiness needs its own evidence; it is not
an unleased exit and must not fabricate readiness to enter the normal cleanup path.

Late terminal checks cannot call the live-ready observer (its process/deadline legitimately
ended). Reuse a shared pinned-file capture and separate live-frame/terminal observations;
immutable source/code/config/receipt hashes still match. Authorization expiration does not
prevent hardware cleanup, but does prevent publication or further model work. Dominant
operations are bounded keyed metadata lookup, one atomic directory reservation, two
append-only records and fixed systemd read/effect calls. Existing current source, original
Job, numerical outputs and all canonical Artifacts remain outside this OS audit adapter.

### Durable ACK and after-ready retirement source checkpoint — 2026-10-17

Implemented the distinct benchmark root ACK and after-ready terminal/retirement owner.
Its fixed unit/main signal, stop/reset and optional retained-FD cleanup all require the
original immutable execution/unit invocation. Atomic phase reservation and durable intent
precede effects; ambiguous commands or partial intent/result writes remain uncertain and
cannot replay. Read-only reconciliation can prove that the original store is already gone,
but cannot silently issue a second cleanup or manufacture the missing result record.

The image and benchmark owners share only protected phase/file IO and bounded terminal/
stopped-unit parsing. Image callers keep their fixed family, old record envelope, outcome
rules and error meanings. Benchmark-specific typed observations remain distinct; sharing
small physical-resource values does not relabel the benchmark as an installation probe.
Late cleanup reuses pinned-file capture without requiring the expired live window or an
already-ended actor; actual original PID/birth, empty cgroup, stopped state, retained
descriptor, no driver clients and independently acquired same-inode lease remain required.
No borrowed lease is unlocked and original timeout/failure is never rewritten as success.

Final20 related suites: **734 PASS67.02s**, strict6 production modules, Ruff/format10 and
diff PASS. New coverage includes ACK no-clobber/concurrency, partial writes, identity drift,
success/failure/timeout cleanup, retained-store cleanup, uncertain before/after-effect
outcomes, read-only recovery, busy/replaced resources and reused PID handling. Existing
image, installation-probe, readiness-file, CPU/CUDA and launch regressions are included,
not added to overlapping earlier totals. Fresh isolated actual nonroot execution also
refused all three root ACK/retirement/reconciliation entries before metadata or effects,
without importing optional ML packages. Positive root/kernel/GPU cases remain synthetic.

The initial new retirement fixture missed the extracted device-observer mock, producing
8 failures before the expected command/result branches. Corrected only the fixture port,
added a device-drift case and asserted each expected failure reason; no production guard
was relaxed. The final734 is from one subsequent complete run. Earlier ACK fixture import/
directory-listing issues were also corrected in fixtures, not by weakening validation.

This is **SOURCE_PASS / NOT_ACTIVE**, not actual root ACK, model execution, throughput or
GPU-default evidence. Failure after PID1 retention but before any ready message still needs
distinct supported evidence/recovery; the current API must not fake readiness or classify
it as an unleased exit. Actual original-Job orchestration, compatible numerical-prefix
activation, that failure branch, six frozen model launches and C1–C5 actual consumer gates
remain open. No protected template/prefix/default, canonical Job or Artifact was changed.

Candidate `75d69a03ecaf89de9395fe489601bf02de1cefc2` passed standard three-wheel/RECORD
build. An actual isolated API-interpreter child imported all6 changed/new production
members from the built platform wheel and matched their exact source bytes, checked the
two native entry/publication implementation pins, and refused its actual nonroot identity
at all three root lifetime entries before metadata/effects, without optional ML imports.
Build `/tmp/eom-api-build/75d69a03ecaf89de9395fe489601bf02de1cefc2.OK7e4d/dist`;
raw platform SHA `98f47a4df95ac50571b02a0e67c80a9d0154c10fd5ac65e92d8e996224084a39`,
API-contract SHA `dd0873d2bd0ac187cfb4061bd47fc5146357d3a541ae9f6f6a8ca5cc337898c9`.
BUILD_ONLY, not installed root/GPU activation.

The next30-minute read at08:38:39 UTC reused the exact installed protected observer in
the existing EOM2 TTY with isolated Python; `index-observation-0838.json` return0 records
509 encodings/bindings,134 revisions/6 logical indexes. Latest view-specific183/157/169
each report545 eligible sources; these are not509 unique Items or a coherent full index.
The bounded latest5 workflows show3 completed,1 running and1 requested with no failure
code, not a global zero-failure assertion. No new request/Job or restart was submitted.
The existing HTTP process was still at LOGIN at08:34; state/log timestamp unchanged.
The user's acknowledgement alone was not recorded as an authenticated PASS; no new login
process or duplicate password prompt was created and no credential/TTY input was read.

### Actual retained-reader family boundary correction — before implementation

Review against the full goal found that the new benchmark terminal/retirement code called
the old installation-probe retained reader, whose closed regex correctly rejects benchmark
units. The higher-level fixtures replaced that reader and therefore did not expose this
wiring error. Keep the probe guard unchanged; add one benchmark-specific retained adapter
with its own exact fixed unit family, sharing only the existing physical FD/inode checks.
Use it at both benchmark callers. Regression must run the actual public family guards and
synthetic kernel FD readbacks, not replace the entire retained reader. No worker wire bytes,
schema, DB, source permission, numerical code, runtime default or installed activation changes.

Implemented the dedicated benchmark retained reader and corrected both terminal/retirement
callers. The probe-only reader is unchanged and still rejects benchmark units. The new
reader checks its exact benchmark family and real resource value type, then uses the same
bounded device/lease/store/PID1-lock observer; a metadata timeout is uncertain, not cleanup
permission. Tests exercise the actual public guards with synthetic kernel ports, including
unheld PID1 lock, missing store, changed descriptor/device, wrong purpose/type and nonroot.
Two higher-level regressions now retain the real family guard while replacing only its
physical kernel adapter, so wiring a probe-only reader back into either caller fails.

Final20 suites **746 PASS65.27s**, strict3 changed production modules, Ruff/format6 and diff
PASS. These include the earlier734 cases; do not add the totals. The initial6 new tests
were red because the benchmark retained API did not exist, then all passed with the API
and caller correction. Positive root/GPU/kernel cases remain synthetic; this corrects an
actual source boundary mismatch, not an installed GPU acceptance. No real signal, unit
cleanup, model, new Job/request, policy/default or protected prefix was changed.

Candidate `2e1523719c460ab34344e0d8506fe21e7695469a` passed standard three-wheel/RECORD
build at `/tmp/eom-api-build/2e1523719c460ab34344e0d8506fe21e7695469a.FJUzjZ/dist`.
An isolated actual API-interpreter child compared all3 changed production members with
wheel bytes, checked both native implementation pins and proved actual nonroot refusal at
the new resource reader plus all3 root lifetime entries, with no optional ML imports.
Raw platform SHA `83c708bc50a6c479549d2f9be4658325048c124091d3a3ab759e46f918b050dc`;
API-contract SHA `6fc906022ef463ae190d21ac08c509da12695de8a67015eb53db74d7eaacd98d`.
BUILD_ONLY / NOT_ACTIVE; no numerical-prefix or active-owner switch was performed.

### Pre-ACK terminal recovery — design before implementation

A failed benchmark can retain its physical GPU file before writing a complete ready
message. Introduce a distinct root-only unacknowledged terminal observation, not a fake
ready/probe or an unleased assertion. Reuse pinned launch/config/receipt capture without
reading readiness as a required schema. Preserve the actual bounded readiness bytes only
as raw hash/size; do not parse a partial message as a grant. Bind the exact terminal unit's
InvocationID/start timestamp/ExecMainPID and descriptor count, repeated empty-cgroup,
current device/prefix/host and driver-idle checks. No live deadline or actor extension.

Require the protected original ACK phase to be absent; any intent, even incomplete, sends
the operation to explicit uncertain/normal recovery instead. An absent phase is not itself
physical proof. With store1, independently read actual unit fdstore and PID1 exclusive lock
against current fixed device/lease epochs and the terminal unit's ExecMainPID. The original
process birth is unavailable after a pre-ready exit: do not invent it or borrow the probe's
birth. A small physical-only value omits birth and is never source/compute admission. Store0
has no retained resource value and never touches another holder's lock.

Share existing pure node/lease-file identity validation and bounded physical readback, not
worker protocols or authority. Fixed-key protected audit lookup and one O_EXCL retirement
reservation retain existing intent-before-effect/no-replay behavior. Stop/reset/clean target
only the exact original unit, never a PID or global GPU. Recheck absent ACK and original
terminal state immediately before effects, preserve FAILED/timeout, and prove stopped/store0
plus same-inode independent reacquisition after a retained release. Unknown cleanup blocks
the next launch. Read-only recovery never repeats effects. Existing successful inputs,
Jobs/Artifacts and numerical bytes remain untouched. No DB/migration/worker schema changes;
ROOTLOCAL internal frozen values and existing phase records are sufficient. The simpler fake
ready would require invented PID birth/hash/initialization facts and is explicitly rejected.

### Pre-ACK terminal recovery source checkpoint — 2026-10-17

Implemented the distinct unacknowledged failed-terminal observer and exact-unit retirement/
read-only recovery. Shared launch metadata capture does not require a valid ready message.
Empty/partial readiness is pinned by raw hash/size, never parsed as a successful grant.
Terminal ExecMainPID/invocation/start/store count and empty cgroup are read repeatedly; an
existing ACK phase (including an incomplete phase/intent or a dangling phase symlink)
refuses the pre-ACK lane. A new late ACK phase before cleanup also prevents store cleaning.

For retained exits, physical-only values omit unknown process birth. Shared pure node/
lease-file validation and the real unit fdstore/PID1 lock readback still require the same
fixed device/lease inode and original terminal ExecMainPID. Successful retirement separately
holds a newly opened same-inode lease across stopped/store0/current-device checks. Unleased
exits do not open/reacquire a competing lease or require another legitimate GPU user to be
idle. Original FAILED/timeout remains recorded; no failure becomes a completed benchmark.
No new worker schema, dependency, DB/migration, queue or generic dispatcher was introduced.
Existing receipt/schema bytes and numerical entry/encoder/codec behavior are unchanged.

Final27 source suites **1042 PASS83.36s**, strict8 production modules, Ruff/format12 and diff
PASS. Included original image/probe/readiness/CPU/CUDA regressions plus empty/partial messages,
absent/present/partial ACK phase, terminal metadata/timeouts, real temporary audit no-clobber,
concurrent retirement, uncertain before/after reset/clean, partial intent/result, independent
release uncertainty and competing-holder isolation. Fresh actual isolated nonroot execution
refuses7 root entries before file/command access and imports no optional ML/GPU packages.
Its file/command hooks would fail the test if a root guard were late. Root/kernel/GPU
positive paths remain synthetic; do not combine overlapping earlier test totals.

This closes the pre-ACK recovery **source** gap, not its actual privileged/GPU acceptance.
Actual original-Job execution composition, compatible owner/numerical-prefix activation,
six frozen CPU/CUDA launches, performance/default selection and actual C1–C5 consumer gates
remain. Current INDEX/QUERY requests and authentication processes were not restarted.
No real signal/reset/clean, model execution, production Job/Artifact/default or protected
runtime was changed by this checkpoint. Full goal remains ACTIVE/NOT_COMPLETE.

Candidate `ea0bb6e459be08af160979b1cf5a27fbdd0b9d6c` passed standard three-wheel/RECORD
build. An isolated actual API-interpreter process imported and byte-matched all8 changed/
new production members from its platform wheel, checked the unchanged two native code pins,
and proved7 actual nonroot entry denials without optional ML imports. Build:
`/tmp/eom-api-build/ea0bb6e459be08af160979b1cf5a27fbdd0b9d6c.5Ja0w6/dist`.
Raw platform SHA `20ab33cf649fc2b0e9f741735d78837447dd6ea2826d5c0257291faea756c961`;
API-contract SHA `9be274e569807149eb3da4263b6ec5ddc3b53281ba88b8ca70a09ab7e483aa6e`.
BUILD_ONLY / NOT_ACTIVE. No privileged helper install, activation or GPU positive occurred.

### Independent GPU resource finalization — design before implementation

The concrete owner channel cannot finalize CUDA resources with worker allocator numbers
alone. Extend the existing fixed root NVIDIA XML reader, sharing bounded XML/device/tool
validation with the old client query. Read framebuffer and per-process MiB counters without
process names, root credentials or ML imports. Preserve old client parsing/commands/errors.
Use a separate small frozen physical snapshot; no new worker message is needed because the
finalizer returns the existing released BenchmarkResourceEvidence1.0 allowed owner fields.
This adapter is not a launcher, Job/source grant, GPU ownership or cleanup receipt.

Bind the actual original unit/PID/birth/current device and retained worker/PID1 locks on
both sides of each sample. Capture initial pinned file epochs once; perform full prefix/host
checks before capture and at finalization rather than rebuilding/hashing the installation
for every sample. One root control owner calls the bounded accumulator; retain count/maxima/
overlap only (O(1) retained space), never a growing raw trace. Parse ≤256KiB/1024 process rows
with a keyed PID map and stable ordered tuple. Missing/N/A/ambiguous counters fail explicitly.
Repeated equal PID counters deduplicate, unequal duplicates fail instead of undercounting.

Vendor integer MiB display is not exact bytes. Before any numerical benchmark, fix the
conservative interpretation: each displayed counter uses (MiB+1)*1048576-1 as an upper bound;
absent own PID means no reported context and zero process bytes. Never round a cap violation
down or describe the utility as exact NVML byte telemetry. The current actual read-only
format check returned framebuffer total16303/reserved464/used2/free15839MiB, driver580.126.09,
one GPU/no process rows; no model/lease/root effect or runtime admission was performed.

An uncertain observation poisons the per-invocation accumulator; do not emit a successful
finalized result or retry a failed sample as if continuous observation held. Finalization
preserves every local field, adds only the permitted independent owner fields and seals the
existing contract. No DB, cache, queue, dependency or new cross-process protocol is added.
Any later transport must preserve root file/peer provenance; parsing these values alone is
not proof of an activated owner. Also extend the existing stale CPU-capacity deny inventory
to CUDA benchmark units: they use the same4 CPU threads and must block overlap after an owner
crash. This adds no launch permission or generic unit family.

The root accumulator establishes its first sample before the controller may ACK compute.
The future concrete guardian must keep that control thread sampling while other control
work runs; maximum accepted sample gap is2s, fixed before measurement. Missing a period
poisons finalization rather than pretending an end-only sample covered the invocation.
Observed maxima remain sampled upper bounds, not a guarantee of unseen sub-period spikes;
local allocator high-water marks and all other resource gates remain independent.

### Independent resource observer source checkpoint — 2026-10-17

Implemented the shared bounded NVIDIA projection and a concrete root benchmark counter
accumulator/finalizer. It checks actual unit/PID/birth, owner birth, credentials/cgroup,
policy, unchanged launch files and worker/PID1 physical locks on both sides of a sample.
Full prefix/host checks stay at capture/finalization, not per-counter inventory rebuilds.
Constructor captures a pre-compute baseline; one control thread owns count/maxima/overlap.
Sampling gaps are bounded conservatively by current query end minus previous query start,
including query latency, not just convenient completion timestamps. Query/scope/gap errors
poison an open observation; a frozen original result cannot be changed by a duplicate call.

Finalization changes only existing1.0 independent-owner fields and seals/validates the
result against the original local evidence. Exceeding8GiB or overlapping consumers remains
visible, never clamped or reinterpreted as admission. Missing/N/A/counter conflicts fail;
old client-query behavior stays unchanged. The existing CPU stale-execution deny inventory
now also recognizes the fixed CUDA benchmark family, including flat/default-slice orphan
cgroups. No additional unit launch permission or generic dispatcher was added.

Final35 related source suites **1290 PASS107.48s**, strict3 production modules,
Ruff/format6 and diff PASS. The total includes prior1042, not an additive count. Included
actual shared parser/command regressions, resource-field immutability, peak/overlap maxima,
upper-bound cap edge, missing/ambiguous counters, model-time scope changes, owner loss,
sample gap/expiry, poison/no-retry, duplicate finalization and orphan CUDA CPU-capacity cases.
A fresh isolated actual nonroot process is refused before command access with no optional
ML imports. Root/kernel/unit positive cases remain synthetic. No numerical workload, Job,
default, runtime selector or protected prefix was changed. Source readiness is not actual
whole-invocation measurement or an activated six-launch owner; those gates remain open.

### Package and actual passive-owner hardware read — 2026-10-17 09:27 UTC

Candidate `12161ebcaebf8a251f3c7890ec4eee987396a732` passed the standard three-wheel/
RECORD gate. An isolated actual API-interpreter child imported and byte-matched all3 changed/
new production members from the wheel, then refused its actual nonroot identity at the
sampler and GPU-memory entry before commands, with no optional ML imports.
Build `/tmp/eom-api-build/12161ebcaebf8a251f3c7890ec4eee987396a732.Wr095S/dist`;
platform raw SHA `8ccb8fde8c84719161ad34896404140486459d8840d390c9c49febc9f960c790`;
API-contract raw SHA `8462ff3e5812ba456a1ceede78c955e3dc8e7e530a74bba22ba0fb41f510985c`.

The existing protected installer (raw SHA559ada516fe9d46f57926aad70699e81deba5f1a18b4e25e3f6e6bcdf1384b71)
staged the exact pair under `/opt/eom/embedding-owner-releases/12161ebcaebf8a251f3c7890ec4eee987396a732`.
This was a passive installation only: no active owner selector or numerical prefix changed.
Same EOM2 TTY/noninteractive sudo was reused, without credentials, new prompts or TTL changes.
The reviewed fixed root operator was copied protected and verified by raw
SHAa4a19657b45111d2f4fdcccaec7c49a0d701131b720d7ae1966d167219480f02 before execution.

Actual UID0 imported the installed members, checked their protected bytes against retained
wheel members, resolved the exact existing CUDA proof ID/revision and raw/semantic hashes
from the configuration record, then called the real fixed NVIDIA memory adapter once.
At09:27:55 UTC it returned total upper bound17095983103 bytes, used upper bound3145727 bytes
and0 process rows. These are conservative MiB-display bounds, not exact NVML bytes or a
whole-invocation peak. No model/tokenizer/forward, CUDA workload, GPU lease acquisition,
Job/Artifact/DB/NAS publication or active policy/default change occurred. No optional ML
framework was imported. This is ACTUAL_ROOT_READONLY_GPU_QUERY_PASS, **not** actual sampler/
unit/cold-warm/capacity/performance/default acceptance.

Protected OS evidence (not a product Artifact):
`/opt/eom/embedding-benchmark-resource-evidence/12161ebcaebf8a251f3c7890ec4eee987396a732/`
contains intent, install stdout/stderr and immutable result. Operator receipt:
`/tmp/eom-benchmark-memory-os.tRNO69Tg/operator-result.json`, return0, stdout raw
SHA55bb038b1c4016c742c4fac1e0bd0b062e76b84b86c4213e69ad7c356b110506.
No automatic retry or existing release overwrite was performed.

The due30-minute observation at09:10:51 used the same protected read-only index adapter:
521 encodings/bindings,137 revisions/6 logical indexes; per-view187/161/173 each report545
eligible sources. These are not521 unique Items or a coherent complete index. Bounded latest
workflows2 completed/1 running/2 requested had no failure code, not a global zero-failure claim.
Original HTTP PID2895440 was actually live at09:05:01 and still LOGIN, state timestamp unchanged;
no new authentication or request was created. Full goal remains ACTIVE/NOT_COMPLETE.
