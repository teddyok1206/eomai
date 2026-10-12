# Shared physical GPU lease — source-only boundary

2026-10-12 UTC. Status: source implementation candidate, **NOT_INSTALLED / NOT_ACTIVE**.
This additive branch does not migrate a user/group/unit, start a GPU process, or prove CUDA cleanup.

## Design note before implementation

1. **Responsibility/boundary:** a stdlib-only infrastructure adapter claims one Linux local flock.
   Orchestrator admission, authorized work, scheduling, runtime/device policy and cleanup remain
   outside it. Image provider, trainer and native embedding are three real consumers; none imports
   another service's private implementation.
2. **Canonical source:** one root-provisioned existing `/run/eom-gpu-lease/gpu0.lock` inode, parent
   `root:eom-gpu-lease 0750`, file `root:eom-gpu-lease 0640`, tmpfs only. The adapter never creates,
   changes permissions/ownership, writes, renames or removes it. Existing image legacy lock defaults
   remain unchanged.
3. **Identity/revision:** this lock is a transient physical-resource mutex, not an Artifact/model
   logical identity or revision. GPU UUID/PCI mapping, installed release and admission policy are
   pinned by the owner separately. A different filesystem path is not a substitute resource.
4. **Resolution:** only the exact reviewed shared path selects the new production branch. Resolve
   the dedicated GID from the trusted host group database; walk/retain ancestor FDs using NOFOLLOW,
   root-owned non-writable directories, exact parent/file modes and GID, regular/nlink1 file,
   O_RDONLY existing-only, FD/named inode and metadata epochs, and kernel mountinfo tmpfs identity.
   A private synthetic policy seam is test-only and not exposed as caller-supplied runtime authority.
5. **Access patterns:** one fixed key, nonblocking exclusive claim, bounded ordered directory walk,
   immutable metadata comparison, release. No worker-to-worker message or source/actor lookup.
6. **Structures/indexes:** a small lease resource handle retains the file/ancestor FDs and immutable
   stat epochs. No database/index, mutable global registry, framework, provider manager or plugin.
7. **Scale/complexity:** one resource, O(path depth) metadata work plus a bounded mountinfo read;
   O(path depth) retained FDs. Kernel flock provides exclusion, not FIFO, fairness, quota or authority.
8. **Concurrency/lifetime:** LOCK_EX|LOCK_NB on the read-only FD. Close verifies epochs and releases
   all FDs even on failure. Fork/dup retain the open-file description; leased/ancestor CLOEXEC FDs
   close on successful exec.
   A lease context alone neither owns a cgroup nor proves orphan GPU processes/kernels are gone.
9. **Dependency direction:** standalone `eom-gpu-lease` supports Python3.11/3.12 and imports only
   stdlib. Provider/trainer adapt stable INVALID/BUSY labels to their existing errors. Platform native
   runtime can use the same public package without importing image ML/code. Each packaging change
   records this explicit shared infrastructure dependency reason.
10. **Failure/retry/idempotency:** wrong/missing/replaced inode, owner/GID/mode/link/mount/metadata
    or unavailable group is INVALID; contention is BUSY. Neither causes mkdir/create/chmod or implicit
    legacy fallback at the fixed shared path. A failed release does not establish safe GPU reuse;
    the owner must fence uncertain execution. Claims do not replay source work.
11. **Simpler alternative:** sharing the image-private 0700/0600 path fails the second UID or widens
    private storage access. A root supervisor-only lock can release on supervisor death while a child
    survives. A tiny fixed shared branch preserves legacy behavior and is smaller than a daemon or
    queue; activation still needs drained all-entrypoint migration and explicit per-unit group review.

The [Linux flock API](https://man7.org/linux/man-pages/man2/flock.2.html) permits exclusive locks on
read-only local descriptors and describes fork/dup/last-close semantics. Kernel mountinfo's major:minor
field is the stat device identity used for the closed tmpfs check.
[Linux mountinfo API](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html).

## Lifecycle inspection and activation limitations

Provider `acquire_gpu_lease()` scopes return after the GPU operation; paired/native/extraction paths
have their own scopes. Trainer `_lock_gpu()` retains its legacy descriptor return or returns the new
shared handle at the fixed path, both closed after the CLI operation. A small SIGTERM scope now enters
release-finally immediately after acquisition; handler lookup/install/restore failure cannot suppress
release. Neither adapter inspects residual children/cgroups or driver cleanup. Source inspection found
trainer subprocesses for CPU Poppler/Tesseract rendering/OCR/version checks, not a GPU-child lifecycle
implementation. This observation is not proof that every installed backend is child-free.
The shared branch must not relabel these scopes as whole-unit/orphan-safe lifetime proof.

Existing fixed image systemd templates use `KillMode` defaults and GPU access independently of this
mutex. No unit/installed policy changes occur here. Production rollout remains blocked until the
owner inventories every image/provider/trainer/direct entrypoint, drains active/uncertain work,
pins a single shared inode and installed branch, verifies group/device privileges and descendants,
and proves cleanup/lease fencing and image regressions. Mixed legacy/shared active runtimes are
not coordinated by this source-only change. CPU-only embedding remains the safe admitted option
when this boundary cannot be established.

## Packaging / release blocker

`eom-gpu-lease` is the one canonical standalone wheel. It is deliberately **not** included in
`eom-platform` package discovery: installing both ownership records for the same module in a prefix
would be invalid. Root pytest/mypy source paths include its source tree; the platform declares it only
under the optional `gpu-runtime` extra. Provider/trainer declare their real direct dependency and
native runtime installation must supply the same protected standalone wheel. No API/core default
dependency or GPU infrastructure import is added.

Provider/trainer import this optional module lazily only when the exact reviewed shared lock path is
selected. Legacy imports/0700/0600 claims still work without that distribution; missing shared-package
imports fail with existing UNAVAILABLE/INVALID labels before opening any shared path. A subprocess
test blocks the optional distribution and exercises these real import/legacy/negative branches.
Core source references found during review are trainer CPU crop helpers and a PDF-render subprocess;
trainer package `__init__` itself imports no CLI/provider. This is source evidence, not a complete
installed dependency or runtime-import acceptance.

The existing image build scripts currently archive/build only image contracts/provider/trainer;
the deployment scripts use `--no-deps`. They have not been updated or run in this source-only leaf.
Consequently these new provider/trainer wheels are **NOT_RELEASE_READY** until a compatible release
includes and validates the pinned standalone lease wheel/dependency closure before any installed
package mutation. Do not deploy a candidate with the unchanged scripts, install dependencies from
an arbitrary online index, or treat source tests as proof of installed wheel ownership. The next
release gate must verify that only the standalone distribution owns `eom_gpu_lease` files in each
prefix, plus the drained physical-lease migration and unit/group/device policy described above.

## Verification scope

Synthetic temporary-path tests exercise modes/owners/GID, symlink/hardlink/races, missing files,
read-only descriptors/no create/chmod/write, mount rejection and real independent-process flock
contention. No test provisions the production group/path or opens a GPU. Tests with synthetic UID/GID
expectations are not a real root-ownership acceptance; installed privilege/device gates remain pending.

The new shared-adapter/import-absence cases47 and existing provider/trainer cases96 passed together
in the explicit Python3.12 `eom-image-test` environment. Root reran these with the26 pure performance
decision cases: **169 PASS (32.28s)**. Ruff/format6 source files and strict mypy6 files passed in that
environment with explicit source paths. An initial root mypy invocation omitted the optional trainer
source path and failed imports; the corrected invocation passed without code or dependency changes.
The core-only checker lacks the pre-existing PIL typing dependency for provider; this is not masked
with blanket ignores or represented as a full core-environment image-checker PASS.

Provider/trainer imports remain usable without the standalone shared package when using legacy
0700/0600 locks. Only selecting the exact shared path imports it; absence rejects that branch with
existing stable labels, not a fallback. The canonical standalone wheel remains required for a
released shared-GPU profile regardless of this lazy-import compatibility.

Public `SharedGpuLease.assert_valid()` rechecks retained FD/named epochs and mount without release.
It rejects a closed/changed handle and lets the native owner check a trusted acquired lease before/
after work without reaching into private functions. It does not prove residual cgroup/driver cleanup
or prevent a trusted `fileno()` borrower from unlocking the descriptor. Such borrowers must retain
the acquired description unchanged; resource admission/lifetime fencing remains the owner boundary.

After that revalidation method and its two cases, the same complete source gate is
**171 PASS (32.27s)**; strict mypy6 files and Ruff PASS. The earlier169 execution is preserved above.
