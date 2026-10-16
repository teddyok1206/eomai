# Automatic indexing: OS loader-cache drift

2026-10-16 UTC. Chronological incident and recovery record, not a lost corpus or failed Item.
Full incremental-RAG goal stays ACTIVE and incomplete. No blind automatic restart/retry.
Latest recovery checkpoint: QUERY READY10:25 UTC; INDEX identity14 started10:59 UTC
and first missing-binding request QUEUED11:00 UTC. Earlier stopped/pending observations
below are historical, not the current service selection. New terminal encoding and
full coverage were not yet observed at that checkpoint. Authenticated HTTP continuation
stopped at login11:09 UTC; a subsequent input-validated observer is waiting in EOM1.

## Observed state and preserved work

- Last scheduled healthy observation06:18:39:19 successful STARTs, one processing
  and one pending. This was a command-state observation, not vector coverage.
- Original INDEX invocation`d6b391c6fa864cf099fc92580f471a18`, source2a4843c3,
  exited06:29:00/status1, Restart=no/NRestarts0. At06:28:59 it emitted
  `WorkflowRuntimeNotReady / LOCAL_INDEXING_SERVICE_UNAVAILABLE`.
- Independent READ ONLY database inspection06:53:14:20 SUCCEEDED/COMPLETED,
  one PENDING/REQUESTED, no failed command or mismatched controls. Successful
  commands retain attempt/generation1; pending has0/0 and no error code.
- Original pending target: Workflow`workflow_d9dfdd0ba988482892ce84d4b4d48e7c`,
  command`wfcmd_dbf2b31a80eb4e55ab2dc23991a3efa2`, METADATA_ONLY. It has not been
  re-keyed, marked successful, directly updated, retried or replaced.
- Prepared unit templates, both environment hashes and runtime roots PASS.
  Actual UID990 numerical installation verifier FAILS before model import.
  Existing API/Catalog/QUERY PIDs remain1045380/1078492/1496865 respectively.
  INDEX is currently FAILED, not active or still processing.

## Exact cause

The actual no-forward verifier was rerun once under UID990/GID1000, empty
supplementary groups and NoNewPrivs, using its unchanged protected script pin.
Closed exception-context inspection identified the precise fixed public OS file:

```text
NATIVE_INSTALLATION_CAPTURE_INVALID
  -> INSTALLED_RUNTIME_FILE_HASH_MISMATCH
  -> /etc/ld.so.cache
```

Only closed codes and owned-module/line metadata were emitted, not exception
messages, arbitrary locals, credentials, source contents or full traces.

| Cache observation | Raw SHA-256 |
| --- | --- |
| Independently accepted fixed host seed | `bc2b95fdb167f457249c288055aa78a2fe3e67364b66d73a8f6d8dc745bcf3f3` |
| Current cache,45467bytes | `a36a656bcbec4f29f8200d6c89e1432b38c1bb6b9959e8039cf71c1cc3b1866e` |

dpkg records show bind9/dnsutils updates and a libc-bin trigger at06:25:21;
the cache mtime is06:25:21.947406 UTC. Actual libc and loader hashes still match
their accepted pins. This identifies the observed cache-byte drift; it does not
prove the entire new host dependency closure or semantic equivalence of caches.
Whether the OS update was automatic or manually initiated was not established.

The CUDA directory probe ran06:45, after this06:29 failure; it did not cause or
restart INDEX. No OOM or new-source/policy failure is inferred from memory peak.

## Separate original HTTP verification

The original same-key continuation process1499680 received
`AUTH_INVALID_CREDENTIALS / HTTP401` at06:41:52 and exited. No auth capture,
new QUERY, saved token/password, replacement key or model run occurred.
Its local state file still says LOGIN, but the actual process is missing and its
terminal log is authoritative. It is **not currently waiting for input**.

Do not ask for another login until native runtime readiness is repaired. A fresh
human login would not repair this independent installation failure. Preserve the
original key`goal-http-reference-query-20261015-01` and its original request.

## Recovery boundary

Do not rewrite/revert the OS cache, mutate accepted receipt bytes, change old pins,
remove hash checks, disable OS updates, claim old success as fresh acceptance, or
restart into an unchanged failed verifier. No DB row/state repair is permitted.

The next implementation boundary is a reviewed immutable loader-configuration
snapshot mounted by the existing fixed native/runtime-verifier units, together
with fresh compatible installation evidence. Relevant executable/library hashes,
aliases, dependencies, namespace, permissions and current-source checks remain
mandatory. See the [design before behavior](../architecture/EMBEDDING_HOST_CONFIGURATION_SNAPSHOT_DESIGN.md).

Before actual recovery, inspect remaining native Jobs/allocations/physical units,
review whether the original pre-claim request remains compatible, and use existing
supported recovery/retirement only if applicable. Never fabricate a new identity
to evade an unknown launch or reinterpret historical failure.

## Evidence

Temporary bounded operator files under`/tmp/eom-identity-provider-install.nAaycoDM/`:

- `index-runtime-stopped-read-only-diagnosis.log`: actual command/control/verifier
  observation; root helper raw`e689d7858e9c4745d0ac73b5369a28a73488acdfd2385c9d7eeb960d85410ecb`.
- `index-runtime-actual-host-cause.log`: actual UID990 exception cause;
  root helper raw`bc6e86720ba40da0ed2d3d4c1b02189de9f5f7c7031b5271b5e41204fabb0981`.
- Original HTTP continuation terminal log remains in the original canary directory.
- Slack BLOCKED gate report`devreport_49a78000b9b646c0aaee0f6922b91e82` delivered.
  Its first incorrect installed-reporter invocation failed before delivery; the
  development tool's explicit source invocation delivered once. Reporting did not
  change or block any application/runtime work.

This incident changes the next required action; it does not waive C1–C5, automatic
source lifecycle, genuine CPU/CUDA comparison or conditional GPU-default gates.

## Compatible CPU publication window —prepared09:25 UTC

Candidate source remains`3346ae080bd4ec9b4d0d56b27aa5f56df39fb8f1`; later document
commits do not change this explicit selection. The existing protected owner copy
is inactive. A separate1.2GiB developer materialization was assembled with OLD
Python only: no candidate interpreter, model or numerical operation was executed.
The seven unchanged console entrypoints retain their existing fixed native wrappers;
their generated RECORD entries were mechanically relocated after OLD pip--prefix.
The normal complete source/wheel/wrapper audit, not this assembly, admits bytes.

Read-only09:21:46 preflight found no native unit, prefix user or nonterminal native
Job. The original pending INDEX remains attempts/generation0 with no error. The
old expired, never-allocated QUERY history remains unchanged. The unfiltered
service command projection contained23 successful commands and1 pending; it is not
the earlier START-only denominator or a vector-coverage measurement.

Prepared input1.1 raw`2c85529c017abae2e54b6546ced6741b090d41920a82634ec3642e1e735dfa94`
is16392bytes and passed Schema2020-12 plus the installed bootstrap parser. A fresh
finite OLD no-site host-only preflight with this exact input and the actual snapshot
mount PASS; this still does not admit the candidate prefix. Original/candidate
tree fingerprints are respectively`5168f397b0515656580ec541a9f33d3c685e2ff20b8f4edcbd71b827aa6fbd2f`
and`74e58fcca4fa6fa8a0ff6935f68f5c298c076a213a8d1117869019b32e7ebb14`.
The independently implemented bounded read-only fingerprint matches the existing
installer's original-tree result exactly. The three numerical implementation files
also match the original bytes; complete new admission remains required.

Execution boundary: gracefully stop only the exact original QUERY owner to prevent
new numerical admissions, repeat read-only work/proc checks, and verify the snapshot
host again before any prefix move. Hold the existing fixed publication lock while
preserving the old CPU directory at the exact new sibling
`/opt/eom/conda/envs/.embedding-cpu-preserved-3346ae08-x6wGos7H` and placing the
developer input at the fixed CPU location. Then the unchanged supported publisher
owns its own reservation, quarantine, host preflight, full OLD byte/ELF audit and
only afterward NEW helper execution. Do not overwrite an existing destination.

Old unit/config/receipt bytes and all original request identities are preserved.
No automatic rollback to the known-invalid old host configuration, row repair,
model run, source permission change, new key or owner activation is permitted.
The QUERY owner stays stopped until coherent native admission/configuration/unit
selection is verified. API/Catalog and unrelated services are not restarted.
Publication success means INSTALLED_NOT_ADMITTED, not runtime recovery.

Temporary explicit materialization/evidence boundary:
`/tmp/eom-cpu-host-recovery-x6wGos7H`. The first archive-retention invocation
rejected the non-private build-parent path before copying a member. Its exact empty
root reservation was verified and moved, not deleted or chmod-published, to
`/opt/eom/embedding-runtime-archives/.incomplete-19fb4269-x6wGos7H`; the retained
wheel/source were then prepared through the existing helper from a private input
directory. Original runtime and production data were unchanged by preparation.

### Actual stop/publication outcome —09:35 UTC

At09:29:36 the requested stop of original QUERY invocation
`de6e8fabd34c44a982bae93b569735a0` reached MainPID0/empty cgroup but recorded
exit1: the root supervisor's`os.kill(child, signum)` at entry line319 raised
PermissionError/EPERM after the child had dropped to UID990. The selected root
unit bounds SETUID/SETGID/DAC_READ_SEARCH but omits KILL. Do not suppress this
exception or reset the failed unit to manufacture a graceful success. The first
operator helper's NOT_CHANGED label was set before its post-stop state assertion;
it correctly preceded any prefix move but did **not** mean the QUERY stop had not
occurred. Its original log is preserved; this is the explicit audit clarification.

Revalidated absence of native Jobs/processes/physical units and the untouched
original pending request allowed the publication window to continue. At09:33:19
the original CPU directory was preserved at the exact planned sibling. The existing
publisher then used the actual snapshot namespace and stopped at
`BEFORE_OLD_PREFIX_BYTES_AUDIT / INSTALLED_RUNTIME_PREFIX_SOURCE_PROJECT_INVALID`.
Its original unit`eom-cpu-runtime-publish-3346ae08` terminated09:35:00/exit1,
invocation`7c3fb6870c9b463b8126e91155210063`. No NEW interpreter/helper, model,
DB mutation or owner activation occurred. The staged3346ae08 directory and failed
private input/inventory remain preserved, not accepted or automatically retried.

The cause is reproducible in the source-project reader: only JSON package-data
patterns are accepted, while the actual wheel newly includes the two owner
`resources/*.service.in` templates. The matching next source fix declares those
two exact literal files in pyproject and permits only those namespace/filename
pairs in the existing source-byte closure; no arbitrary extension/glob, omitted
wheel member or hash bypass. Add whole-prefix source/wheel/installed-member tests
for both files, missing/changed/extra files and wrong namespaces before rebuilding.
The original1.0/1.1 schema bytes remain unchanged; each bootstrap source member is
still independently hash-pinned by the installation input.

Separately, the root QUERY supervisor needs KILL only to signal its own unreaped
fork child. Add that bounded parent capability, never an ambient child capability;
retain the child's all-zero permitted/effective/ambient checks and no saved root
identity. Source tests and finite real-UID negative/positive signal probes precede
new owner selection. This is a lifecycle correction, not a user/worker permission
grant or a reason to alter original Job/Workflow history. API/Catalog remain on
their original active processes. Native recovery and the full goal remain open.

### Corrective source and finite kernel evidence

Whole-prefix regression first reproduced the actual SOURCE_PROJECT_INVALID rejection.
The fixed package-data declaration lists exactly the two owner templates; the
reader's existing literal-source/wheel/installed-byte checks now include those
namespace/filename pairs only. General service globs remain rejected. Focused
whole-prefix156 PASS covers both resources and missing/changed/extra/wrong-role
negatives. The first green run's duplicate TOML-key test fixture was corrected
without changing the production rule, then156/156 passed. Expanded source/install/
host/closure/owner suite938 PASS, native receipt/admission suite300 PASS and
dependency/QUERY/history/documentation suite46 PASS; counts overlap and are not
added. Strict2 core files and formatter/linter PASS. No schema, DB migration,
queue, dependency, model payload, numerical implementation or original request
changes are part of these two corrections.

Actual finite systemd probes with the same root bounds/ambient SETUID and actual
UID990/GID1000 child independently reproduce the signal-permission boundary:

- without bounded KILL: SIGTERM returns PermissionError as expected; child self-
  terminates via its bounded timer, parent reaps it, terminal exit0;
- with bounded KILL: the parent delivers SIGTERM to its owned fork child, which
  exits0 and is reaped normally;
- in both cases the existing installed `_require_dropped_identity` checks actual
  saved IDs, empty supplementary groups, NoNewPrivs and all-zero permitted,
  effective and ambient capabilities **inside the child** before its ready signal.

Both10-second-bounded probes PASS, no current session/query/source capture, DB,
model, GPU or worker permission change. Protected probe helper raw
`addb2c19aafd09c7ac3a32d687d75748852b687d388168a968e7389677408738`.
Evidence: `query-signal-old-proof.log`, `query-signal-successor-proof.log`,
`unit-resource-regression-red.log`, `unit-resource-regression-final.log`,
`native-recovery-successor-regression.log`,
`native-recovery-successor-admission-regression.log`,
`native-recovery-successor-boundaries.log` and `successor-final-strict.log`
under the same temporary recovery directory.

Failed publisher private directory`/opt/eom/.embedding-index-install-4NZqt8Wd`
has a zero-byte inventory candidate and ends at BEFORE_OLD_PREFIX_BYTES_AUDIT;
it never reached PREFIX_BYTES_AUDITED_NOT_ADMITTED/NEW. Preserve it and both CPU
directory materializations. Build an explicit successor from the reviewed source,
verify its **actual** archive→wheel payload including both literal templates before
another supported publication, then perform fresh native configuration/probe/seal.
Neither these source tests nor the finite signal probes are native recovery PASS.

### Actual successor publication PASS —09:57:01 UTC

Reviewed source`b41b3cb47f4d0dcfb25c08f46bc8ffd56388a595`, tree
`af7297a6839792c15c5126d0ffb27ad4f4258a04`, standard three-wheel/RECORD inspection
PASS. Build`/tmp/eom-api-build/b41b3cb47f4d0dcfb25c08f46bc8ffd56388a595.K49ny4`;
platform raw`776df86a3635fd763696b0c892930c518748fb9d1ec9af1dd81b5aac39a781c9`,
source archive raw`ab44f0bb8f7d78edba8ba818a11920cc4d9e055a7ff93c82fb63b26c827a471d`.
Before publication, actual source archives and corresponding wheels were compared
byte-for-byte by the corrected reader: original accepted c2f8eef8's1466 payload
members and successor's1605 members PASS, including exactly two inert templates.
All three numerical implementation pins match across those actual wheel files.
This actual package proof did not execute NEW or replace native admission.

The independent root input1.1 raw is
`aca8c6dea404a234cff815ae2296d0c39b7a21683cd6ee85cf193b013c16bf52`/16392bytes.
Only the reviewed prefix-reader bootstrap pin changes to
`98d94b9be5db27f52fd2c4004b63e0a30803a846ce7be7d14558560431fadd30`;
the other six bootstrap members, helper58e61d5e, snapshot/host seed, public archive
closure and all existing historical input/config/schema bytes remain unchanged.
Schema/parser validation and OLD-only candidate assembly PASS. Candidate tree
`d0298a4d2e69938521a98f05739901a6d86ee6ecf449daed194cb862725136b5` was independently
checked before any rename, while all actual native Jobs/units/prefix users were absent.

The exact failed3346ae08 prefix was moved, not deleted or accepted, to
`/opt/eom/conda/envs/.embedding-cpu-rejected-3346ae08-4NZqt8Wd`; the original c2f8eef8
directory remains separately preserved at its earlier planned path. The supported
publisher then ran once under the exact pre-exec snapshot binding, actual PID1835088/
invocation`fa2c80adcc2349acb355ce661a522669`. Its terminal exit0 and protected phase
receipt prove this sequence:

```text
HOST_BYTES_PREFLIGHT_PASS_NOT_ADMITTED
STAGED_NOT_ADMITTED
BEFORE_OLD_PREFIX_BYTES_AUDIT
PREFIX_BYTES_AUDITED_NOT_ADMITTED
INSTALLED_NOT_ADMITTED
```

Only after the full OLD byte/ELF audit did the existing NEW installation helper run.
No model, tokenizer, numerical forward, DB mutation, worker Job, source capture,
new HTTP key, owner activation or ordinary service restart occurred. Protected
installation evidence is`/opt/eom/.embedding-index-install-RJO7Vx2Q`; inventory
raw`57d720c59d108d895e7e9df77ce6a2d93063869f80cd1c79db289f41edd50bb5`,
host-only receipt raw`93b079bb8de462ebc9b1fa60608ea4f3073d02a97adeaad0273fda10c81be0e5`,
full-prefix receipt raw`f06b1af664e7e081b5fdd677d829625425765baa106d8b2891f8bb436ed2b2ee`.
The retained developer input is
`/opt/eom/conda/envs/.embedding-index-prepublication-CPU_INDEX_FP32-.embedding-index-install-RJO7Vx2Q`.
Local bounded window:`/tmp/eom-cpu-host-successor-Z1YMaK2I`.

Current status is **CPU_INSTALLED_NOT_ADMITTED**, not native/runtime/goal PASS.
Fresh1.1 native configuration and exact snapshot selection, real UID978 installation
probe, independent root receipt/seal and coherent owner/control selection are next.
Only then recover the preserved original INDEX work through supported compatibility/
preallocation maintenance and resume the original human-authenticated HTTP request.
QUERY and INDEX remain their original FAILED/PID0 histories, not reset; API/Catalog
keep original PIDs1045380/1078492 and invocations. C1–C5, full coverage and actual
CPU/CUDA benchmark/default-device gates remain required by the unchanged goal.

### Actual snapshot-bound native probe and independent seal PASS —10:12:30 UTC

The installed b41b3cb4 CPU interpreter now has fresh installation acceptance,
not merely source tests. Protected preparation used the supported numerical observer
to compare the actual installed libraries, CPU identity and three implementation
pins with the original bundle/proof. All matched. The original bundle, numerical
runtime and vector space are reused; no re-encoding or replacement Artifact was
invented for a host-configuration change.

The new explicit configuration remains under logical ID
`embeddingnativeconfig_b839a737216d4324869c7f9b62e98d8a`, with immutable revision
`embeddingnativeconfigrev_927557e47c11457aa8f6a85bb9c044ec`:

- family:`embedding-native-runtime-config/1.1`;
- raw:`9160e25cba729b86b5dcc0bb7bf0342d23c816fb3839cb63e898aeb9dceea0a0`;
- semantic:`a43792039f6415b6955bde3cb14d721ddf1ff3660302767735dc892c08848bac`;
- runtime unchanged:`f02cfc2b977c262b2b20cf7a3cc07553ad41f718ca39334953fb11d7a6ab10fb`.

The protected original configuration and receipt are not edited. Preparation's
first finite invocation rejected opening the lock read-write in its read-only
namespace before metadata writes. Its successor uses a read-only descriptor for
the same exclusive flock. A second pre-write rejection identified an old operator
assumption of ancestor `--x` ACLs; actual retained UID978 ACLs are `r-x` on those
directories. They were inspected, recorded and preserved, not widened or changed.
The third preparation completed with zero model calls/ML imports/DB writes.

With real native Jobs/units/prefix users absent, the deployment owner selected the
exact immutable cache member through the documented root-owned `selected-cache`
installation selector and installed the reviewed mandatory-binding probe template
raw`dcfa3596b92297ada1330c4393fb6a305c9703b3a1678476125f6f7eb96ae34f`.
The old unit is preserved in
`/opt/eom/.embedding-native-host-successor-b41b3cb4/prior-probe.service`.
The first selection invocation found its template staging file absent and stopped
before any selector/unit change; after that exact file was staged, selection
completed. No ordinary service was restarted and no workflow was submitted.

One actual fixed probe execution completed, without retry:

- execution:`86b996ba62ac45afa1a10f3ae6edd981`;
- UID/GID:`978/975`, no supplementary groups;
- PID:`1930388`, invocation:`4b6205c5dfde4907a3ae72a54d8a5e9a`;
- input raw:`e75b6aac9b9ad710de7450c67e09b1fe7f44efc024e84ea2d07b7b336f4087b5`;
- result raw:`3eba912d84ed9c2e8edc82d9cbed8a21222722c93c7d4dc05f2b7a32340c4a31`;
- owner observation raw:
  `32d19bf98166fbbef50f60033dfb4b0ca7306a0841da341e4453aed461195fb2`;
- effective policy, including actual mandatory read-only binding:
  `bc29e56d0cf2b8de12585337988884ab10d2ce8b22948770dcffea18fe9c01ef`.

The owner observed the actual live process/cgroup/start identity and executable
mappings, checked the numerical descriptor and access denials, acknowledged that
same invocation, then observed successful termination and an empty cgroup. Eight
model payload members were checked; model/tokenizer constructors and forward
calls were zero. Root optional ML imports were zero. Original failed and pending
work was not reinterpreted or resubmitted.

An independent root sealing pass reused that protected actual probe evidence,
without re-executing it. Current `ProtectedNativeEmbeddingInstallationAdmission`
then accepted the new exact configuration/inventory/host mount/receipt together:

- status:`CPU_INSTALLATION_SEALED_AND_READER_PASS`;
- sealed:`2026-10-16T10:12:30.096365Z`;
- receipt raw:`2ce9852cc4904aa33a62b9dbbbb738efab661444e8c35e833787e6b526f7d2f1`;
- receipt semantic:`49e80308fd5f4d4f0d100c6046767722ffdc6fc7b8a61585691ebe7758d889b9`;
- inventory semantic:
  `b2d1542719a59a52d64192234d98638a6cbff0de88345a1f9ba6553c9770f7f1`.

Receipt/inventory live under the new configuration ID/revision in
`/opt/eom/embedding-runtime-admission`; protected operator observations remain in
`/opt/eom/.embedding-native-host-successor-b41b3cb4`. The existing shared schema
files were equality-checked and left unchanged, not republished. Same-boundary
snapshot admission/probe/unit tests:52 PASS in5.17s; this overlaps prior suites
and is not added to their totals.

**Native CPU installation acceptance is PASS; service recovery is not yet PASS.**
Coherent owner release, verifier/native environment/units and service-identity
selection remain before supported original-work recovery. The original human HTTP
continuation is already terminal401; no login prompt/token is being retained and
no new login is requested before native service readiness. Common HTTP/consumer
activation, full coverage and the real CPU/CUDA comparison remain unfinished.

The compatible owner pair from the same reviewed b41b3cb4 build was subsequently
installed through the existing protected `install_owner_release.sh`, with its
pre-exec snapshot binding and an allowed owner-release temporary directory.
Actual wheel/RECORD verification and both package installations PASS; target:
`/opt/eom/embedding-owner-releases/b41b3cb47f4d0dcfb25c08f46bc8ffd56388a595`.
Platform raw is the776df86a pin above; API-contracts raw is
`1b5856199176ad44be0deb88522441b388d1ab49e52548ab52913c7e23deed74`.
An isolated installed import check loaded345 EOM modules, all from that exact
release, with zero optional ML imports. The release remains **INACTIVE**.
The initial systemd invocation rejected executing a non-executable protected
shell script before any install mutation; explicitly invoking the existing script
with Bash corrected that invocation without chmod, history reset or a new installer.

Final observed API/Catalog PIDs/invocations remain unchanged and active; INDEX and
QUERY remain their original failed/PID0 invocations. No new login, worker Job,
DB mutation, command identity or model forward was introduced by this window.
README/documentation checks3 PASS in1.78s. Same temporary evidence directory also
contains `owner-installation-b41b3cb4-v2.log` and `installed-owner-import.log`.

### Coherent native selection and QUERY service READY —10:25:41 UTC

Without changing the INDEX identity, original pending request or source policy,
the deployment owner prepared/selected a compatible native/QUERY set. It updates
the four source-fixed INDEX/QUERY templates, three non-secret native environment
files and the QUERY owner configuration/unit together, while both old owners were
stopped and actual native Jobs/units/prefix users were absent. Existing files are
retained under the root-only stage:
`/var/lib/eom-release-operator-stage.2857bf77-6g9mpdap/native-host-query-b41b3cb4`.
Manifest raw:`9fb15552fde9290594ffbefde0ba65516767720f3a166758beaa1b3eec20935c`.
No schema, queue, DB row, source permission or numerical bundle changes occurred.

The b41b3cb4 release's protected no-forward verifier pins the new1.1 configuration
and receipt; raw`588355859a967ac3bc50ce70079766c4e9ddbca399bf0c67b090cf4bef96cf49`.
The existing stdlib INDEX/QUERY preparation bootstrap was materialized unchanged
under that same protected release. Staged unit analysis PASS. Actual UID990
verification in the mandatory snapshot namespace completed successfully with no
capabilities/model calls, invocation`b09629b382aa45f4ade400ca04813336`/exit0.
Its `RemainAfterExit` observer remained live after the process exited; only after
recording PID0/success/empty cgroup was that wait interrupted and the completed
probe unit stopped. The accidentally typed subsequent command had not run
(no unit/log/selection receipt); selection then ran once through its original
prepared manifest. No native model execution was repeated.

Selected non-secret file raw pins:

- CPU environment:`52b283d1bb9a4bb04101ea5f3d60cba826e5588fe15311f743e7fcdd697d9e29`;
- INDEX preparation environment:
  `b80b97cce7b1d7f237dec36f85fa5624777aceeaefe46c8254d82d2bf533ccdc`;
- QUERY preparation environment:
  `be4d1374a042496959eb5321be977c86685afcedff5b305ca30d9d36c1683afa`;
- QUERY owner configuration:
  `b3a1de9c1c24351cea7e56518ab3b6f3ec1af685f12293c0dabcdeb33e5450d9`;
- QUERY owner unit:
  `135fe7015470fe3d0a2221f3c205b235f7e576ea7b4812fa8f614c7b5508a0e7`.

The QUERY owner was started once after all readbacks/preflight completed. Actual
PID1937196/invocation`2a0f502082014dbf9a679b57f3bf6115` reported
`REFERENCE_QUERY_OWNER_READY` at`2026-10-16T10:25:41.529558Z`. Its actual child
PID1937251 has all real/effective/saved UIDs990 and GIDs1000, empty supplementary
groups, NoNewPrivs1 and zero permitted/effective/ambient capabilities. Inheritable
and bounding sets are not claimed to be zero. API/Catalog retain their original
active PIDs/invocations. The old QUERY failure/invocation/history remains preserved.

This is **QUERY_OWNER_READY**, not authenticated common HTTP acceptance or full
goal completion. A new in-memory login observer is waiting in the existing EOM1
pane for the same original HTTP key/request/operation. No token is saved and no
new query identity is fabricated; no actual human HTTP result is yet accepted.

The original INDEX request was re-read through a read-only transaction: exactly
one PENDING START with attempts/generation0/no lease, no steps and only the initial
event, pinned to still-current service revision13/resource version26. Thus the
expired PROCESSING/RUNNING retirement1.0 contract does not apply. INDEX remains
stopped with its original failure invocation. The additive, tested
[unstarted cancellation design](../architecture/LOCAL_INDEXING_UNSTARTED_CANCELLATION_DESIGN.md)
provides the truthful owner-maintenance boundary before an INDEX identity successor.
Candidate e6e9b926's owner pair is now installed INACTIVE and an exact command is
prepared, but no operating cancellation/identity activation has occurred. The
shared numerical prefix stays b41b3cb4 and QUERY remains on its recovered b41b3cb4
release. This never changes failed history to success.

### Supported cancellation, identity14 and actual INDEX startup —11:00 UTC

The reviewed optional owner release remains pinned to
`e6e9b926c5c6811478dd56d8d88c682d1312e3f3`; subsequent documentation commits do not
change this selected source. The protected INDEX numerical prefix and QUERY remain
on b41b3cb4. No shared API/Catalog release or numerical bundle/proof/space changed.

Before activation, a READ ONLY canonical count observed101 encodings,101 source
bindings,32 immutable index revisions and6 logical indexes at10:46 UTC. These are
registry rows, not unique Item coverage or a claim that all520 targets are indexed.

The actual Orchestrator UID990 published the exact new native control policy through
its existing Job/Artifact boundary, not a worker NAS write:

- Job:`job_6547bef2e96246c4babf2dcdf91abc90`;
- Artifact:`artifact_9db642f6ebd24457ac376ef1ca3d00ec`;
- revision:`rev_7ed4ece08a30475da57f46841a258dd7`;
- policy raw:`febc5646c1e6481b5def65fe3a61464268661ec13b153769e78925eb4186be00`;
- policy semantic:`e62f6776dedc9fa38671d78433adb10e9e77665a1d42d58667ff48db2bb0c4b9`;
- manifest:`c731da69b7f221d4fff63069541cf49fa45a45df133e239b120f62bc84892f64`.

An initial finite publication invocation rejected `setresuid` before Python, with
no Job or publication output. It is preserved. The corrected invocation dropped
to UID990/GID1000/empty supplementary groups before EOM imports, asserted zero
permitted/effective/ambient capabilities and NoNewPrivs, and reused the original
policy idempotency key. This was control publication, not a model/encoder launch.
The public Catalog read independently checked the actual Artifact producer,
manifest, policy bytes and hashes before any identity activation.

At`2026-10-16T10:55:55.043161Z`, the installed public
`cancel_unstarted_indexing_workflow` application, under the actual database-owner
principal`eom_app`, terminally cancelled only the original never-claimed request:

- Workflow:`workflow_d9dfdd0ba988482892ce84d4b4d48e7c`;
- command:`wfcmd_dbf2b31a80eb4e55ab2dc23991a3efa2`;
- request SHA:`4e4b2ef8c10ccf722d81f13365200a194433594166651507742e7f044cd136f1`;
- receipt raw:`394288af7df9a6fc2a4dd454faf200bf0a69d6d6a2ff5d80bc89130831ca29b7`;
- receipt semantic:`5e2c31f0ab02e69c73e4dc87754ab3ad4eedb945d7f10922686a3a6d15f9037c`.

Workflow, stage and START command are truthfully CANCELLED, not successful.
Request bytes/hash/key/service13 remain immutable; attempts/generation stay0,
all lease fields remain absent and no step/Job/Artifact/model was created by
cancellation. Historical failed work is unchanged. Identity activation independently
checked this exact receipt and the absence of other executable service commands.

Existing public Identity register/activate/grant applications selected service
revision14, resource version28:
`localindexservicerev_63713ee227a04e3388f04ca65d6aa895`, semantic
`0ec80f58b7b14b09cf0b709eae06b2d8c259f511d36de1f9c53e17583ec88b32`.
Grant revision:`accessrev_2cf7c934457e47f79d4e997fbbdcb683`.
Source classes, namespaces, source-access policy, model/bundle/space/recipe,
maximum4 targets and60-second discovery interval are unchanged. This is no new
queue, schema migration, source permission or direct row-repair operation.

After inspecting the stopped owner and exact selected files, the operator started
INDEX once. Actual PID1953488/invocation`36f20dd36c444cc780b52fe8eed41fbe`
reported`LOCAL_INDEXING_SERVICE_STARTED` at`2026-10-16T10:59:33.123850Z`.
First actual reconciliation at`2026-10-16T11:00:27.273584Z` observed:

| Field | Actual observation |
| --- | --- |
| View/state | CONTENT_ONLY / QUEUED |
| Eligible sources |545 |
| Missing accepted reports |25, separately waiting; not fabricated |
| Missing bindings |481 |
| Selected targets |4 |
| Workflow | `workflow_29e2bf3e901f4098b823857d269d1872` |
| Command | `wfcmd_4508178810d944bfac6d063d6bb12a73` |

This proves startup and normal missing-binding admission, **not new terminal
encoding, full coverage or full-goal acceptance**. Subsequent progress observation
is limited to30-minute intervals after the initial11:00:44 UTC startup gate.
No `reset-failed`, old-row success reinterpretation or speculative new HTTP key.

Root selection/evidence:`/var/lib/eom-indexing-host-e6e9b926` and the original
root-only cancellation stage. Selected runtime raw:
`8cdbcc0334a07ac91850e1da5db4e841bf31d35d01f7d3e621368387b81e54e8`;
owner raw:`e0bf66ef3b69d3d3893add2c97999085302a91f3c86581eb93eece019cc7f1eb`;
unit raw:`4a7a8ba8423a28fd376419a2422676513975d300160e9b181ee79a15e98f8154`.
Temporary bounded logs remain under`/tmp/eom-cpu-host-successor-Z1YMaK2I`:
policy publication attempts, original unstarted cancellation preparation/execution,
INDEX control preparation/activation/selection, startup and first observation.

### Original HTTP continuation stopped before login —11:09 UTC

The existing EOM1 observer PID1937790 was still waiting in getpass when the user
reported entering the password. Completing that pending input produced HTTP422
`API_REQUEST_INVALID` at11:09:16 UTC, before an authenticated operator or query
submission. The observer exited; its stale local LOGIN marker is not a live prompt.
No password/token was persisted, new query/key created or model call made. This
does not establish wrong credentials: input/request validation and authentication
failure are different. The original request/key/operation and all previous failed
observations remain preserved. Authentication HTTP C1 is still incomplete.

The finite local observer was then corrected to validate the existing `LoginRequest`
before network entry and refuse empty/oversized input locally. Its new observation
state/log is separate from the preserved failed observation; request bytes, key and
operation are unchanged. Actual PID1961407 is waiting for getpass in the same EOM1
pane; the user has been told the exact Studio password prompt, not a sudo prompt.
No operating authentication policy, TTL, stored credential or source code changed.
The old EXIT/LOGIN marker is not used as current liveness evidence.

README/runtime-documentation and original-design/layer-boundary checks:31 PASS
in5.17s; `git diff --check` PASS. These documentation checks are not runtime or
authenticated HTTP acceptance and do not add to the overlapping core suite totals.
