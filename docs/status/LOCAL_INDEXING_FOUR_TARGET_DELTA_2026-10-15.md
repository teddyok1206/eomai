# Four-target incremental INDEX and controller observation cost

2026-10-15 UTC. Parent: [original goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).
This is a bounded live checkpoint, **not full-corpus, all-view, consumer or GPU acceptance**.

## Actual operating result

At22:52:54 UTC, the existing installed INDEX owner had completed one four-target
batch and drained successfully. Persistent CONTENT_ONLY coverage advanced **2→6/520**;
encoding and source-binding rows each advanced2→6, index revisions2→3, logical
indexes remained1. All original two encodings/bindings (including their hashes,
Artifact revisions, row positions and timestamps) and previous index revisions
were unchanged. No old experiment was relabeled as persistent-vector coverage.

| Identity | Pinned result |
| --- | --- |
| Installed owner | `ae8f8bf669be4224d87f97fd67e2de5b79a94840` |
| Service identity revision | `localindexservicerev_2e56cbf71dc24741a5ec19014a2d8e77`, revision11 |
| Workflow / original START | `workflow_83cc2a155e484590a9f9194ce7941038` / `wfcmd_433ed146482e4ffea609c72e16ae1da8` |
| Logical index | `embeddingindex_e8a00544f6304ded82e1a5bb8f8e4131` |
| New index revision | `embeddingindexrev_c811ae5543dc48928d400ee21ed69878` |
| Previous index revision | `embeddingindexrev_ec428fa3e4bd4ecd878b68cee5d932b1` |
| Semantic index SHA | `sha256:cfe404cc4be122e1df81ea741831458b5daf9cec3a02786dce99bf93972c72e9` |
| Index Artifact / revision | `artifact_24e517a000a74debafddd0fa75d0458e` / `rev_1aaae4c2def14826b70b415d965c2c72` |
| Manifest member raw SHA | `sha256:1abae8b61d9242105f34060b40988fb6337211481798dc3603a6c02a2f665728` |
| Receipt Artifact / revision | `artifact_a34a14f423944792b58db2a53c183294` / `rev_9e212615e3b44edcbb0943255af7c78c` |
| Receipt semantic SHA | `sha256:d0da27fa6cee5b2d08211040d67db1702235fd690ccbb35b74fd4280c5f64afb` |

There was **one native model launch, four newly encoded texts**, command
attempts1 and lease generation1. The exact native unit
`eom-embedding-native-cpu-index@1d6726a1a88f499c8308bd0f8785d39c.service`
ran22:39:51→22:41:01 UTC, exited0, and recorded memory peak4,615,049,216bytes
and CPU74,530,157,000ns. Native calculation time is not the whole Workflow time:
the index committed22:43:30 and Workflow/START became terminal22:50:03 UTC.
The controller had no OOM/oom_kill; hitting a memory-high event is not an OOM.

Only the mutable root-owned owner deployment selection changed:
`maximum_targets: 1→4`; `poll_interval_seconds: 1800` stayed unchanged. Its raw
SHA changed from`836cef3b4102751e6aed5c5d88c69ff016b526a258ee0affdaf3a5387af671f2`
to`a398249fde8ba012c296d67d799dd7fa3ac36b1dc57fbbf56a65490dc14bfb54`.
The runtime/service-identity/model/space/policy/authority pins and CPU admission
ceiling did not change. Configuration backups and address-only profiling evidence
are under the protected deployment window
`/var/lib/eom-indexing-four-target-window-t3zlzlz2`.

The existing SIGTERM handler was used as a graceful drain event, without putting
systemd into deactivating while a current claim still needed its active-unit
fence. No forced kill, direct row repair, failed-history rewrite or extra target
was used. The unit is now **inactive/dead, Result=success, boot-disabled**. The
four-target selection remains installed; **continuous automatic indexing has not
been re-enabled**, and1800seconds is this bounded window's poll selection, not a
claimed production throughput default.

## Preserved startup refusal

The first invocation refused admission with`LOCAL_INDEXING_RUNTIME_CHANGED`
before a Workflow/Job/model launch: the root configuration replacement occurred
in the same second as process start, while the existing textual systemd start
timestamp observation has whole-second precision. Read-only before/after metadata
proved no new command, encoding or binding. Once the unchanged selected file was
older than the next start second, one supported start succeeded. The failed
invocation remains in the journal. No state-machine, timestamp fence, permission
or runtime-authentication rule was relaxed.

## Source correction: distinct ancestors within each observation

The controller's end-to-end duration motivated inspecting actual work rather than
raising timeouts or removing fences. The already-installed`perf` sampled the exact
controller PID for10seconds:302 user CPU samples, lost0,0.118MB, with12.91% in
`__lxstat64` and34.44% in Python evaluation. Only instruction/frame addresses were
recorded, not raw stack/local variables. This does **not** attribute all elapsed
time or establish a whole-Workflow speedup.

`identity_service.local_indexing_runtime._ProtectedFiles` now gathers distinct
ancestor **path names** in an insertion-ordered dict within one observation.
It rechecks every distinct ancestor's existing owner/mode/type/symlink predicates
and every captured file epoch. Loaded module aliases are validated individually
but their identical physical origin is observed once. No authority, file metadata
or freshness result is cached across observations; FD identity, bounded byte/hash
checks, closed module origins and current unit/identity/lease checks remain.

Dominant operation: repeated shared-parent lookup, not a new source cache or
registry. WithN files, depthD andP distinct parent paths, filesystem observation
calls change from`N*(2D+1)` to`N+2P`; collecting names takesO(ND) andO(P) space.
An actual synthetic shadow traversal with2,048 files and5 shared ancestors measures
**22,528→2,058 lstat calls per fence**, retaining both the directory and symlink
observations. This is an operation-count improvement, not a measured wall-time
claim. Every subsequent fence rechecks shared ancestors and file epochs.

Ownership stays in the existing infrastructure adapter. There is no new wire
contract, queue, schema, dependency, DB index, identity or grant. A cross-fence
metadata cache would be simpler to make fast but would violate current-change
detection, so it is not used. The active immutable owner release is not patched
in place; this source correction needs a separately selected compatible install
and actual protected runtime check before any live performance claim.

## Verification and remaining scope

- Source runtime/admission/verification/contracts/source-authority regression:
  185 PASS/5.77s. The final added reference-loop check then passed with the154-case
  runtime subset,5.11s; these suites overlap and must not be summed.
- Separate owner-config/reconciliation/registry/SQL/dependency/release boundaries:
  134 PASS/17.25s. Strict type check of the changed production module, Ruff,
  formatter and whitespace checks PASS.
- A prior invocation accidentally used installed older modules after losing its
  source-path variable; it failed before live effects. The corrected invocation
  asserts the exact checkout module origin and new method before running tests.
  No production guard was changed to accommodate that invocation error.
- Official API health smoke PASS. The original genuine HTTP preparation canary
  remains the same process/key/pane; no successful login has been recorded at
  this checkpoint. It is not restarted or treated as an accepted HTTP test.

Private content-free execution logs are in the existing development window
`/tmp/eom-identity-provider-install.nAaycoDM/`, notably
`indexing-four-target-{baseline,after-admission-failure,terminal-observation}.log`,
`indexing-four-target-controller-profile{,-report}.log` and
`indexing-runtime-observation-cost-{source-final,reviewed-final,boundaries,source-mypy}.log`.
They are not runtime authorization or committed generated artifacts.

The original goal remains active: all-view automation, lifecycle/new approved
Item handling, ordinary reference/author/review/chat/exam consumer activation,
same-request live INDEX replay, and actual CPU/CUDA comparison/conditional GPU
default still require their own evidence. CPU remains selected. Neither6/520 nor
the installed inactive83bad async-start candidate completes these requirements.
