# Bounded multiview INDEX release selection

2026-10-15 UTC; terminal audit2026-10-16 00:14 UTC.
**BOUNDED_THREE_VIEW_WINDOW=PASS; CONTINUOUS_INDEXING=NOT_ACTIVE.**
Parent: [multiview owner design](../architecture/LOCAL_INDEXING_MULTIVIEW_OWNER_DESIGN.md).
Reviewed INDEX source: `d4846220f1afbebaa8bb79507297eed42cea9219`.
Do not silently replace it with a later documentation commit or replace API/QUERY.

1. Responsibility/boundary: use existing Identity register/activate and Catalog
   service-policy publication, existing Orchestrator control-Artifact publisher,
   then the existing fixed INDEX unit. No new permission, queue, protocol or DDL.
2. Canonical source: current owner/runtime selections, current Identity head,
   immutable native/data policies and official committed vector/index metadata.
3. Revision: register source-specific service revision12 after exact current11;
   pin new unit/wheel/runtime and three namespace views. Never change revision11.
4. Resolution: verify root file epochs/hash/ownership, actual DB owner, current
   Identity reference/head, no nonterminal service commands, and previous original
   START success. Keep source/Graph/policy/model/space/recipe pins unchanged.
5. Access: exact service/head/START lookup, same-service executable-work predicate,
   bounded three-view selection and existing source/binding reconciliation.
6. Structures/indexes: existing PK/head unique keys, ordered namespace tuple,
   existing FIFO claim/lease and immutable index revisions. No additional index.
7. Scale/cost: three leaf runtimes; start with at most one source per view and
   1800second discovery interval for a bounded window, CPU global ceiling1 and
   existing memory/thread limits. This is not a throughput/default acceptance.
8. Transactions/concurrency: native control publication is a separate owner commit;
   register/activate/data-policy publication share one caller root. Install root
   selections only while the exact unit is inactive and commands are terminal.
   No claim runs until the selected controls/files have been revalidated.
9. Dependency/ownership: only installed owner code and protected interpreter.
   Numerical workers receive staged inputs; no DB/NAS/group access is added.
   Orchestrator alone commits control and vector Artifacts to canonical storage.
10. Failure/replay: preserve first output, original IDs/keys/receipts. Unknown
    mutation outcome requires actual metadata inspection, not a new identity/key.
    Same fixed publication key uses existing idempotency. Stop on drift. Use the
    supported graceful stop Event while current work is active, never force-kill
    or move a nonterminal request under another identity/source release.
11. Simpler alternative: retaining the old source identity would misrepresent the
    installed code, and broadening the old immutable policy would erase provenance.
    A purpose-specific successor with the existing control owners is sufficient.

Preserve exact old runtime/owner/unit files before replacement. After replacement,
verify their raw hashes and systemd selection. The existing conservative whole-
second startup fence requires new files to predate the start second; wait only for
that bounded timestamp precondition, without weakening the fence or changing TTLs.
Do not boot-enable or start another batch as a side effect of file installation.

Rollback before admission: while the unit remains stopped and has no executable
commands, the supported Identity activation may select the exact prior registered
reference with expected current resource version; restore the exact backed-up
files and reload systemd. Preserve the new registered revision/grant/control
Artifacts as history. After admission, finish/recover the original new-authority
commands before any rollback; do not strand them by switching authority.

Success evidence must show per-view original Workflow/START, exact native launch
count, new versus reused encodings, source bindings, immutable index chain and
current partial denominator. Observed timing is not a CPU/GPU comparison. Keep
API2857bf77, QUERY owner8c411041, held HTTP login/key, Pack activations and0055
unchanged. Remaining full-goal consumers/device gates remain separate.

## Current control selection and preserved pre-compute failures

At23:18 UTC, actual current Identity11/resource version22 and no executable
service commands were checked. Persistent rows remained encoding6/binding6/index
revisions3. Prepared stage:
`/var/lib/eom-indexing-multiview-d4846220-ve3gx4tx`.

The actual Orchestrator UID990/GID1000, with supplementary groups and capabilities
cleared, committed the exact native policy (model forwards0):

- Job`job_5f2b95fb06da4ede95a9e908dd33b790`.
- Artifact`artifact_74822065fcd24add83b17d02c4572a1d` /
  `rev_e02d22a91d2c4858a0c29cdbab643be4`, `policy.json`.
- Member raw SHA`8618e958a500a1e0068c94415723f1094a1507d1f233c88e3ebb07f8834831e1`;
  semantic policy SHA`5e8845c4dc31fe3cbe381d4c49e0d0f2ec5c6430e8e0204cc1880915394023ea`.
- File-set manifest SHA`25740c10978ff7c12c6ec5ae541a82e67157c0fc60875978f33052ef3bbbd5ff`.

Catalog's public pinned member reader revalidated schema/media/hash/file-set and
that successful producer Job before the actual control mutation. Supported
Identity register/activate and Catalog policy publication committed in one root
at23:22:31 UTC. Revision12 is
`localindexservicerev_ee62d4cc09d446cf8195b82316941d71`, identity semantic SHA
`ff9f90ebc7d44557aedaf3164841d35fa0046a7f90314b7d071e41482080fd9f`, resource version24.
Grant`accessrev_b59fd2981537475ea7017faa42e4538c`, semantic SHA
`c015742e94fc6c7712efc0bd8758f0760b2bdd86a17b6f4347bbe3106ba3deff`, retains the exact
original source policy/model/space/recipe and adds only the three released views.

Selected root files (raw SHA; exact predecessor copies retained in the stage):

| File | Raw SHA-256 |
| --- | --- |
| Runtime | `6be37e0c90b5e3a6822c4722df8e432d708d5dd17997b13fb4fc75dcf9f38b78` |
| Owner configuration2.0 | `015aba8fdc401f7ed718866318c444cd90c4a9c2dfa459d9742a92fac34e0225` |
| INDEX unit | `7b49b0554731e62e701ac2a4b2f733f5c29a5e2b1750f5964de4bdc376a455f7` |

The first operator helper replaced these exact files while stopped, reloaded
systemd, then refused its own post-read check because it compared complete
`stat_result`, including access time. A disposable text-file probe reproduces:
read changes atime, whole-stat equality fails, but dev/inode/mode/owner/link/size/
mtime/ctime identity is unchanged. Actual read-only metadata at23:29:02 confirmed
zero revision12 Workflows and no new native Jobs, with6/6/3 persistent rows. The
same selected files were retained; they were not reinstalled with new identities.
The corrected start-only observer uses the same meaningful epoch as production
runtime; no production authentication/freshness/hash fence was weakened.

The first actual invocation at23:29:33 (PID1195909,
`42c2e6e7ead0465cb489204483a21d0e`) then refused its existing no-forward numerical
installation verifier, before queue discovery/claim. It remains failed in the
journal. Redacted actual UID990 numerical diagnostics reproduce
`INSTALLED_RUNTIME_FILE_UNPROTECTED` for the host libc file, not source or vector
content. No request/command/failed history was changed to success.

## Profiling cache side effect and exact recovery

The earlier22:44 controller `perf record` used its default build-id cache. This
created one hardlink from
`/root/.debug/usr/lib/x86_64-linux-gnu/libc.so.6/a4a7992a8e66555c8141ab2a08a8465ff6e0ea65/elf`
to`/usr/lib/x86_64-linux-gnu/libc.so.6`. Exact device64512/inode3698665, ctime and
the six task-created cache files establish the link; only that cache ELF had
link count2. Actual libc bytes still matched the independently accepted host SHA
`3a15d66867d83762c7f2f1e37359cb8f6c5743edb369c65285cb0b1c4f7498bf`.
The original nlink1 verifier correctly refused the additional alias.

At23:38:31, after confirming no active INDEX native Jobs or revision12 Workflows,
the exact cache member was atomically replaced by an independent same-byte copy.
The system library path/inode/bytes/mode/owner/mtime were not replaced or changed;
its link count returned2→1 and ctime necessarily changed. Cache bytes are preserved
as an independent root-owned file (inode14454824, nlink1), not discarded. Before/
after manifests are in the protected stage. No runtime/receipt/host allowlist or
security rule was relaxed, no model ran, and no OS library bytes were patched.

**Future profiling must use `perf record -N` / `--no-buildid-cache`** and inspect
protected file/link metadata before and after. Local `perf record -h` confirms
this flag prevents updating the build-id cache. Address-only sampling does not
mean filesystem-read-only: the original profile remains valid address sampling,
but its cache side effect must not be omitted from the operational evidence.

The original actual no-forward verifier passed at23:40 UTC after detachment.
One supported start of the **same** source12/configuration from its known failed
invocation then began at23:41:35, PID1201778,
invocation`3cb026dbd8024ae5991d3f60637c4b76`. No publication/configuration was rerun,
failed history was not reset and no new authority/operation key was substituted.
`LOCAL_INDEXING_SERVICE_STARTED` followed at23:41:56. The bounded observer initially remained
alive (PID1201734), watching only its exact revision12 original STARTs and sending
the existing graceful stop Event when the third one is active after two successes.

| View | Workflow | Original START |
| --- | --- | --- |
| CONTENT_ONLY | `workflow_c7b091ec86ec49febd5703d9cc928fb4` | `wfcmd_6b3e5d11ad1647bba2e303651b33dc8a` |
| CONCRETE_FACETS | `workflow_bf3a79d64b4f4f468f4b68f8b7c1ed70` | `wfcmd_2e6bcc7df2474582bf1066381b2e2eb6` |
| METADATA_ONLY | `workflow_c8ce6c87312642639c2bfc5dc6555c64` | `wfcmd_06fa3ea4f3f34c6090a4e02bb39083bf` |

All three were QUEUED by23:44:29, with520 eligible sources, missing reports0 and
unavailable views0. The first original START was PROCESSING/RUNNING by23:45:05,
attempts/generation1; the other two remained pending. No terminal/binding/model
success is inferred from those states. The controller's observed memory peak
reached its unchanged1GiB limit, memory.events max432 but oom/oom_kill0; this is
not an OOM report or a reason to silently increase the budget.

At that checkpoint, bounded model/index acceptance and continuous automation remained pending. The
[full requirement ledger](../status/SYSTEM_RAG_GOAL_REQUIREMENT_AUDIT_2026-10-15.md)
keeps the broader consumer, lifecycle and GPU/default work visible and unwaived.

At23:54:16 UTC the original CONTENT_ONLY Workflow/START completed successfully.
By00:04:46 UTC on10/16, CONCRETE_FACETS was also COMPLETED/SUCCEEDED and the
original METADATA_ONLY START was PROCESSING/RUNNING. The bounded observer had
issued the intended graceful stop Event while that third command was active;
the same unit remains active to finish it, not deactivating or restarted. All
observed admitted commands retain attempts/generation1. Final canonical vector/
binding/index and native-launch count inspection still follows terminal drain.

Phase timing identifies remaining controller work, not a claimed overall speedup:
each initial full-population discovery took about51seconds. The first new native
numeric unit was observed running23:46:28→23:47:31, exit0; its exact Job/receipt
lineage is checked after drain. The first original command completed only at
23:54:16. Numerical execution exit is not equivalent to Workflow completion,
and the remaining post-compute source/index verification deserves measurement
before raising resource limits, adding caches or claiming GPU will remove it.

## Terminal window and independent canonical storage audit

At2026-10-16 00:13:56 UTC, the exact original three Workflows were COMPLETED and
their original START commands SUCCEEDED, each attempts1/lease generation1.
The graceful stop Event drained the last command; the same INDEX invocation
exited successfully, MainPID0/inactive. No fourth discovery/start was admitted.

At00:14:23 UTC, an independent **read-only operator storage-integrity audit**
checked the installed d4846220 contract/member readers. It did not authenticate
as the INDEX service, read source question text, or claim fresh user retrieval
authorization. All six original encoding rows and bindings matched the retained
pre-window metadata exactly, including original Artifact/row/hash/time identity.

| View | Current revision | Bindings / eligible sources | Native launch Job |
| --- | --- | ---: | --- |
| CONTENT_ONLY | `embeddingindexrev_ba3ec2a71b17442f9e59426ee83ad29e` (revision4) | 7 / 520 | `job_cf4cac86191c4bedbb496c04bc6abdb9` |
| CONCRETE_FACETS | `embeddingindexrev_24d16277bd114d9eb811590916c52641` (revision1) | 1 / 520 | `job_eff9f354bfdb4fdc8ab78869e0cb25f6` |
| METADATA_ONLY | `embeddingindexrev_446958f3804e434092ad53b34b90d568` (revision1) | 1 / 520 | `job_9dcba27580fd480d96a0e9aee7fdbb54` |

Persistent totals are encoding9/binding9/logical indexes3/index revisions6.
These are view-specific vectors/associations, **not nine distinct source Items**.
Each new receipt resolves its original Workflow/step/request/source-plan and
Graph/policy/namespace pins, successful producer, registration and exact current
index revision. All six referenced immutable shards passed canonical schema/raw
member SHA, result/shard equality, finite float32/L2 shape and index/previous-
manifest reference validation. Registered numeric row pointers match the bindings.

Each original native launch has exactly one owned encoding Job, both successful;
the corresponding fixed CPU unit is terminal, exit0, restart count0. Three new
encodings, three original native units and preserved older rows are the actual
observations; command counts alone were not used as model-execution evidence.
No DB mutation, new model launch, source-policy change or worker permission was
performed by this audit. API health smoke remains PASS.

Evidence files in the existing private development window:
`multiview-bounded-after-cache-window.log` and
`multiview-terminal-storage-audit.log`. The one-off protected audit is
`/usr/local/libexec/eom-release-operator-indexing-4cf6ac9a/audit-multiview-terminal-d484.py`,
raw SHA`cde91082257a7b10d0c7fa64d18c6938f9d5f6d34812637b9aabc7c5b24e5286`.
It is operator tooling, not a new production queue or retrieval authority.

Continuous policy, full coverage, approved-generated-Item/report lifecycle,
INDEX same-request replay, consumer activation and actual CPU/CUDA measurement
remain explicit next gates. Boot enable remains OFF; this success does not
silently authorize a different batch size, source grant or encoder space.
