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
