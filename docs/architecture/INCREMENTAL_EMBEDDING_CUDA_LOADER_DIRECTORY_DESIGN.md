# CUDA loader working-directory boundary

2026-10-16 UTC. Design before implementation. This is a byte-audit and native
working-directory prerequisite, not installation, GPU admission or a benchmark PASS.

The retained CUDA cuSPARSELt library has an empty component in `$ORIGIN:`.
The loader searches the current directory for that component. Ignoring it, removing
it from the wheel, or allowing an arbitrary working directory would invalidate the
existing independent runtime proof. The CPU profile keeps rejecting this spelling.

1. **Responsibility/boundary:** extend existing protected runtime file snapshots,
   prefix ELF closure and native runtime composition. Do not add another installer,
   registry, device scheduler or loader implementation.
2. **Canonical source:** retained exact CUDA wheel bytes remain unchanged. A fixed
   root-provisioned directory `/opt/eom/embedding-cuda-loader-empty`, root-owned
   mode0555 with no ACL or entries, supplies an independently observed empty search
   route. Its existence is not presumed and this source change does not create it.
3. **Identity/revisions:** retain directory device/inode/owner/mode/time epochs and
   protected ancestor identities separately from numerical model/space hashes.
   Existing CPU closure hashes, historical proofs and payload bytes are unchanged.
4. **Resolution:** no-follow ancestor/leaf FDs, exact named/FD identity, protected
   ancestors, empty contents, exact0555/root ownership and absent access/default
   ACLs. Recheck epochs after resolution and throughout native backend lifetime.
   Native CUDA composition additionally requires the actual current directory to
   be that fixed inode; installation byte inspection alone does not require or
   change the installer's working directory.
5. **Access pattern:** constant-depth directory capture, O(1) emptiness detection,
   subsequent epoch checks; existing bounded ELF dependency traversal is unchanged.
6. **Structures:** existing immutable `RuntimeFileEpoch`, per-request snapshot map
   and fixed profile mapping. No DB/schema/index/cache or cross-service message.
7. **Complexity/scale:** one directory per admitted CUDA process, not one per model,
   text or ELF. Capture once, reuse its epoch, never repeatedly scan/hash the prefix.
8. **Transaction/concurrency:** no DB transaction or mutation. Directory creation
   and fixed systemd `WorkingDirectory` selection belong to a later independently
   reviewed, drained installation. Namespace/DAC/mount verification remains an
   actual launch prerequisite. Root maintenance may not mutate an admitted runtime.
   Epoch checks detect observable drift; they are not protection against privileged
   root rewriting/restoring state or an undetectable within-clock-tick mutation.
   Root-only ownership, read-only namespace and drained maintenance are mandatory.
9. **Dependency ownership:** stdlib-only filesystem inspection stays in Catalog
   infrastructure. Prefix inspection and native factory reuse that public snapshot
   behavior; contract/domain layers do not import filesystem or ML infrastructure.
10. **Failure/retry:** missing/nonempty/writable/linked/replaced directory, ACL,
    incorrect cwd or changed epoch fails explicitly. No chdir, repair, wheel patch,
    latest lookup, alternate path, retry or inference is performed. CUDA missing
    this prerequisite stays unadmitted; current CPU operation remains untouched.
11. **Simpler alternative:** retaining a blanket rejection is safe but leaves the
    already requested CUDA comparison unimplementable with the unchanged official
    wheel. An observed empty immutable directory plus actual cwd verification
    accounts for the real loader behavior without broadening library search.

Only an **empty component** is covered. Explicit relative paths, `.`, `$LIB`,
`$PLATFORM`, prefix escapes and unknown absolute routes remain rejected. The CUDA
ELF byte-closure digest records the captured empty-directory epoch when used;
the CPU digest and strict no-empty-route behavior remain byte-compatible.

Required source tests: positive CUDA empty route with unchanged normal dependency
resolution, missing/unprotected/nonempty/ACL/link/ancestor/FD/name/epoch/cwd
negatives, independent CPU rejection and unchanged CPU digest. Tests are synthetic
filesystem/ELF fixtures, not actual CUDA, sandbox, lease or speed acceptance.

Next actual steps remain protected CUDA publication/proof, fixed-unit namespace and
device-denial verification, migration of every image/trainer physical lease entry,
the six original measured launches and conditional default activation. None is
replaced by this source checkpoint.

## Source checkpoint

The current unadmitted CUDA library was re-inspected read-only: its actual RUNPATH
is still `$ORIGIN:`. No library was loaded, imported, modified or run.

- Focused directory/factory/prefix suites:187 PASS/16.04s.
- Expanded directory/factory/prefix/host/Conda/observer/native/benchmark-entry
  regression:640 PASS/66.89s.
- Inventory-export/installer/distribution/wheel/proof/config/legacy-CPU-install
  regression:779 PASS/19.37s.
- Strict mypy on the three production modules, Ruff and formatting PASS.
- Final strict mypy includes all six changed production/test modules PASS.
  The test previously reached a constant through an implicit re-export; it now
  imports the constant from its existing host-closure owner, without re-exporting
  another API or changing its shared bound.
- The focused187 cases overlap the expanded640 inventory; no sum is claimed.
  Synthetic fixed-directory and factory ports do not establish actual unit isolation.

The first test invocation mistakenly used installed modules and failed collection;
it made no runtime change. Explicit source paths corrected the invocation. The
first source run had186 PASS/one timing-dependent synthetic epoch assertion; that
fixture now makes its observable timestamp drift deterministic, without relaxing
production checks. Both failed logs are retained. Directory/root-only immutability
is enforced by ownership/namespace/maintenance rules, not an unrealistic claim of
detecting every privileged within-clock-tick mutation.

Evidence logs are temporarily retained under
`/tmp/eom-identity-provider-install.nAaycoDM/cuda-empty-loader-*`.
No production service, database, role, source policy, CPU environment, model,
GPU lease or default device was changed by these source checks.

## Actual fixed-directory prerequisite —06:45 UTC

An independent fixed root operation prepared the empty directory root:root0555,
then ran a finite probe under existing UID978/GID975 with NoNewPrivs, no retained
capabilities, private network/devices and read-only filesystem. Exact cwd/FD/epoch,
denied file creation, rejected wrong cwd and restored original empty inode PASS;
no Torch/Transformers/NumPy/SQLAlchemy import, GPU/model or other service restart.
This is deliberately not the absent CUDA identity or a CUDA-runtime/device gate.

- Helper raw`c072dd4c2f9915df085a7ffab7434228d50853c52f861535058dd85f23ae3476`.
- Selected runtime-file module raw`5d24c672e2a59365ef72f6a5f48696e014c881d0a7eaf708ca4d7134c3b4bda3`.
- Unit`eom-cuda-empty-loader-prerequisite-8fcdd241.service`, exit0/success/no restart.
- Root-private receipt at the existing deployment stage:
  `cuda-empty-loader-8fcdd241.json`; public code copy is an explicit prerequisite
  installation materialization, not a change behind an immutable CPU prefix.

Separately, the old INDEX invocation stopped06:29 after OS loader-cache drift and
the HTTP login continuation exited06:41:52 after authentication rejection. Those
pre-date this06:45 probe; no process is now waiting for that login. The independent
[host-cache incident](../operations/LOCAL_INDEXING_HOST_CACHE_DRIFT_2026-10-16.md)
must be repaired before original native work or genuine HTTP acceptance resumes.
