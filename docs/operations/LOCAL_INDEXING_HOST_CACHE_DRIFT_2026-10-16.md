# Automatic indexing: OS loader-cache drift

2026-10-16 UTC. Current operating incident, not a lost corpus or failed Item.
Full incremental-RAG goal stays ACTIVE and incomplete. No automatic restart/retry.

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
