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
