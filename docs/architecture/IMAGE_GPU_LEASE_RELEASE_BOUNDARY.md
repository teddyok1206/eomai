# Image release closure for the standalone GPU lease wheel

2026-10-12 UTC. Source-only implementation plan; **NOT_INSTALLED / NOT_ACTIVE**.
This leaf closes package admission, not shared-lock/group/device migration or embedding activation.
No build/deploy/privileged/Git/model/GPU operation is executed by the source tests.

## Narrow design note before changes

1. **Responsibility/boundary:** extend the existing provider/trainer build and deploy scripts with
   the one canonical `eom-gpu-lease` wheel. A cohesive read-only dependency verifier serves four real
   callers; it does not own scheduling, activation, users, model loading or a new installer framework.
2. **Canonical source:** exact reviewed source snapshot and one
   `eom_gpu_lease-0.1.0-py3-none-any.whl`. Do not bundle its files into platform/provider/trainer wheels.
   Package bytes, source commit and wheel SHA are distinct; no latest/glob-selected successor.
3. **Identity/revision:** legacy provider7/trainer11 argument positions retain their meanings.
   The reviewed successor adds trailing `--gpu-lease-wheel PATH --gpu-lease-sha256 HEX` options.
   A candidate whose METADATA declares this dependency requires those exact options; an actually
   dependency-free legacy cohort may retain the old invocation. Neither case selects a GPU device.
4. **Resolution:** validate closed filenames/distribution versions, raw SHA, regular/single-link
   file identity and FD epochs, bounded ZIP32 EOCD/central bytes and actual header count before
   `ZipFile` allocation, ZIP paths/types/bounds, complete RECORD hashes/sizes, metadata/tags,
   source namespace/member closure and dependency pins. Existing installed RECORD ownership must
   exclude platform/other-distribution claims, unowned files and any lease bytecode before import.
5. **Access patterns:** exact wheel/distribution/member lookups, uniqueness, bounded streaming hash,
   ordered source comparison, immutable quarantine and append-only sanitized phase receipts.
6. **Structures/indexes:** maps/sets for names, RECORD and dependencies; sorted tuples for summaries.
   No new DB/table, package registry, generic dependency dispatcher or arbitrary command callback.
7. **Scale/complexity:** fixed provider/trainer cohorts, bounded wheel/member/metadata/RECORD sizes.
   O(bytes + members + requirements), with one hash per admitted immutable copy; no repeated list
   scans or ML imports are needed. Central bytes/count are bounded before ZIP object allocation;
   fixed-interpreter metadata stdout is bounded while reading, with a deadline and discarded stderr.
   No model weights or long logs enter Git/receipts.
8. **Transaction/concurrency:** first create a private quarantine, copy the helper and inputs with
   O_NOFOLLOW/O_EXCL/FD epochs, and verify exact helper SHA before executing it from protected staged
   source with isolated, bytecode-disabled Python. Admission precedes environment cloning, pip,
   identities, bindings, workspaces or unit mutations. Installed mutation is not atomic: retain
   sanitized preflight and
   mutation/verification receipts plus exact quarantined inputs for explicit recovery on failure.
9. **Dependency direction/ownership:** operator shell → fixed verifier leaf → stdlib/installed
   packaging metadata. Do not widen API verifier whitelists or import private API helpers. The helper
   executes only from protected admitted staging, not a writable worktree or development PYTHONPATH.
10. **Failure/retry/idempotency:** missing/extra/wrong/changed wheel, RECORD/metadata/source/dependency
    drift, ZIP64/comments/multidisk, oversized capture, timeout, bytecode or overlapping ownership
    fails closed. Kill/reap timed-out or oversized probe children and close capture FDs. No online
    install, dependency omission, silent latest or synthetic READY. After a mutation failure,
    preserve evidence and report recovery
    required; rerun only through the same reviewed source/pins and fresh admission.
11. **Simpler alternative:** adding a pip wheel argument alone leaves arbitrary bytes, dependency
    omission and duplicate RECORD ownership unchecked; copying four independent validators makes
    the invariant drift. One narrow verifier plus existing scripts is the smaller authoritative rule.

## Exact proposed sequence

Build archives the standalone source with the existing package cohort and the verifier from the
same reviewed commit, builds the exact wheel offline/no-deps, validates source/RECORD/dependency
metadata before outputting pins, and emits the standalone wheel path/hash explicitly.

Deploy retains the existing legacy argument positions and validates successor options before any
runtime mutation. A root-private staging bootstrap copies the exact pinned helper and wheels using
stable FDs and hashes; no writable-source module is imported. The helper validates the immutable
source closure, required lease metadata, installed ownership and all candidate dependency versions.
It writes a small content-free admission receipt. Existing owner/drain checks remain; they are not
the complete shared-GPU all-entrypoint drain proof.

The worktree helper is untrusted input bytes, not runtime authority: its input mode need not be
read-only, but a fixed reviewed SHA and both FD/named metadata epochs must match before it is
copied to the root-owned `0600` quarantine. Only that protected copy executes, with isolated
`/srv/eom/conda/envs/eom-api/bin/python -I -B`; development PYTHONPATH is not used. Local package
payloads and project metadata are compared against the separately protected exact commit archive.
The helper's existing `packaging` dependency is used for wheel names/tags, requirement markers and
version ranges; this introduces no ML dependency or new core/API distribution dependency.
Only root-protected non-lease installed distribution metadata may retain Conda cache hardlinks
with stable FD/named epochs and protected owner/modes/ancestors. Wheel/source/quarantine inputs,
canonical lease payloads and its METADATA/RECORD remain single-link admission targets; editable,
unowned, foreign-component and duplicate lease ownership is rejected. This narrow exception avoids
misclassifying legitimate Conda metadata as mutable source authority; it does not trust the cache
location or relax installed-package permissions. Source tests use temporary owners and a synthetic
UID substitution for the foreign-owner negative, never an actual ownership/privilege change.
The bounded archive reader admits selected roots and their directory ancestors only, never links.
External PEFT/bitsandbytes wheels may own only their own package namespace and distribution metadata;
`.data` relocations or other package namespaces are rejected before pip.
Before Python's ZIP reader constructs member objects, the same held wheel FD is used to validate
the final comment-free ZIP32 EOCD, bounded central-directory size and the actual number of central
headers. ZIP64, multidisk, member comments and malformed/trailing central bytes are unsupported.
The only metadata subprocess uses the fixed protected profile interpreter and fixed metadata-only
code, isolated and bytecode-disabled. Its stdout is capped before accumulation, stderr goes to
`DEVNULL`, and a deadline covers reads and child completion; cleanup kills/reaps and closes the pipe.

Only after admission does the existing offline installation sequence consume protected wheel copies.
The successor standalone distribution is installed once with `--no-compile`; cloning an inference
prefix must not introduce a second owner. Before and after mutation, inspect metadata/RECORD
without importing Torch/Diffusers, and finish installed ownership verification before the first
image-package import probe.
A lease `.pyc`/`.pyo`, including a registered unchecked-hash, an unregistered cache file or a
sourceless top-level sibling, is denied before import rather than skipped or deleted. All isolated
release/probe Python invocations disable bytecode
with `-B`; pre-existing bytecode requires explicit owner recovery, never automatic cache deletion.
A separate isolated, bytecode-disabled import probe loads only the stdlib lease package and checks
its protected origin; it does not claim an actual GPU lease, group privilege or device availability.

Keep quarantine and phase receipts on error for explicit recovery; no automatic broad cleanup,
uninstall, environment overwrite or rollback is added. Package-prepared output remains separate
from `GPU_SHARED_LEASE_MIGRATION_REQUIRED` and actual shared mode/device activation. Full migration
requires all physical entrypoints drained and pinned to one inode, reviewed per-unit group/device
policy, cgroup/driver cleanup and image regression. Passing source fixtures closes none of those gates.

Receipts use the closed private `image-lease-release-receipt/1.0` shape with source commit, fixed
role/filename/raw-SHA pins, UTC creation time and nonactivation booleans. No item/model contents,
authority DTOs or deployment secrets are recorded. Duplicate keys, unexpected fields, paths,
context drift or activation claims fail resolution. Admission is revalidated immediately before
the mutation receipt; recovery retains exact inputs rather than claiming an atomic package update.

## Source verification

The synthetic suite uses temporary code/wheels/prefixes only. It does not invoke Git archive,
build/deploy scripts, Conda/pip installation or root operations. Actual argument-parser snippets
are exercised without the rest of the deployment script. The installed-import simulation manually
materializes a reviewed stdlib lease wheel in a temporary fake prefix, then imports only that package
with isolated Python; it asserts no ML modules were loaded.
The 81-case suite adds ZIP preallocation/count/byte bounds and held-FD cleanup, bounded stdout plus
discarded large stderr, read/completion deadlines with kill/reap/pipe cleanup, fixed-prefix escape
denial, and registered unchecked-hash/unregistered/sourceless bytecode denial without deletion.
All four scripts pin helper SHA-256
`231089d320a70a41272c006ccca38e1c68014fccfba2ff61feb1515ca5699300`.
These are source-fixture gates, not actual archive admission, installation or shared GPU activation.

```sh
/srv/eom/conda/envs/eom-api/bin/ruff format --check scripts/image_provider/verify_release_dependency.py tests/unit/test_image_gpu_lease_release.py
/srv/eom/conda/envs/eom-api/bin/ruff check scripts/image_provider/verify_release_dependency.py tests/unit/test_image_gpu_lease_release.py
/srv/eom/conda/envs/eom-core/bin/mypy --strict --explicit-package-bases --follow-imports=silent scripts/image_provider/verify_release_dependency.py tests/unit/test_image_gpu_lease_release.py
/srv/eom/conda/envs/eom-api/bin/python -m pytest -q tests/unit/test_image_gpu_lease_release.py
bash -n scripts/image_provider/build_release.sh scripts/image_provider/deploy_runtime.sh scripts/image_trainer/build_release.sh scripts/image_trainer/deploy_runtime.sh
```
