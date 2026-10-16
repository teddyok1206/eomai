# CUDA host extension: closed private libraries, not a CPU allowlist expansion

2026-10-16 UTC. Design before protocol/behavior. Source and protected host-only
publication/capture PASS; full CUDA candidate/runtime/device admission NOT_ACTIVE.
This is required by the original incremental-RAG CPU/CUDA experiment, not a new
platform or a substitute for real C1–C5/device acceptance.

## Evidence and chosen boundary

The full static candidate scan examined287 ELF objects/78 dependency names without
executing the candidate interpreter or model. After accounting for Tcl/Tk prefix
basenames, additional standard-host candidates are libcuda, ibverbs and mlx5;
rdmacm is absent at the checked standard paths. Actual installed libcuda is
`libcuda.so.580.126.09`,96,284,520bytes, matching the observed580.126.09 kernel
driver release. It alone exceeds the CPU host capturer's intentional8MiB bound.
ibverbs needs libnl-route and libnl-core; mlx5 needs ibverbs; all other observed
direct dependencies belong to the unchanged CPU base closure.

The missing library has an official Ubuntu package:
[librdmacm1t64 50.0-2ubuntu0.2](https://packages.ubuntu.com/noble-updates/librdmacm1t64).
The local APT index independently gives amd64 archive70,698bytes/raw
`7b7cc2fa16564bf301751b43d05d16f0846288b080d9a25a92a691d0df33fc68`.
Acquisition/extraction is data-only; **no apt installation, maintainer scripts,
driver upgrade or global loader-cache mutation** is selected. Its reason is the
official cuFile RDMA dependency in the fully audited CUDA wheel set, not a new
Python/model dependency. Keep its archive/source evidence outside Git.

Use a private, immutable CUDA extension alongside the accepted CPU host snapshot:
six explicit library roles (CUDA driver, rdmacm, ibverbs, mlx5, netlink core/route)
and one CUDA-local loader cache. Reuse existing bounded FD/readelf/hash/namespace
owners. Do not increase the CPU file-size bound or fixed SONAME table. A private
cache/library set avoids changing global OS directories while an admitted CPU
operation is live. File presence alone grants no loading or device permission.

## Required design procedure

1. **Responsibility/system boundary:** the existing installed-runtime owner captures
   one protected CUDA-only extension; schema/value objects merely describe bytes.
   This is not source retrieval, actor authentication, GPU admission or a worker tool.
2. **Canonical source:** accepted CPU snapshot plus independently reviewed installed
   OS library bytes and the hash-pinned official rdmacm archive. Root publication
   uses fresh protected inodes, never chown of developer-held inodes. Only a sealed
   accepted root-local revision can later be selected. Acquisition data is not admission.
3. **Identity/revisions:** separate extension logical configuration ID, immutable
   revision, manifest raw hash, semantic hash and host-seed hash. Runtime/config/
   receipt/encoder spaces select explicit successors; no historical CPU reinterpretation.
4. **Pointers/resolution:** new extension pointer pins logical/revision identity,
   schema, manifest count/raw hash and semantic hash; the base CPU snapshot pointer
   remains exact1.0. Resolve only fixed root-local paths and six exact member names.
   Check root ownership, modes, single links, size/hash, aliases/closed namespace,
   actual cache mount and FD epochs before/after use. Missing/changed means explicit failure.
5. **Access patterns:** six keyed members, exact role-set membership, deterministic
   ordered serialization and a sparse dependency graph. No search engine, queue or DB table.
6. **Structures/indexes:** frozen tuple of unique role records, role→record map during
   validation and existing ELF adjacency/maps/sets. No database/index change.
7. **Scale/complexity:** k=6 plus the existing base host; O(k) metadata and O(B) first
   byte admission, O(k) epoch checks thereafter. Driver alone has a CUDA-specific
   128MiB maximum; the other extension libraries remain individually bounded8MiB.
   Do not retain unnecessary96MiB raw copies after FD/hash/ELF inspection.
8. **Transaction/concurrency:** existing root publication lock, exclusive fresh
   staging and atomic selected-revision replacement. No SQL root spans file copying,
   kernel/device access or model work. Existing CPU/GPU physical leases remain authoritative.
9. **Dependency/ownership:** contracts stay pure; the Catalog infrastructure owns
   capture/cache/ELF behavior. Existing protected OLD bootstrap reads metadata and
   bytes before any candidate Python. Reuse the base captured host for tools/loader
   and compose CUDA extensions rather than subclassing or duplicating its whole verifier.
10. **Failure/retry/idempotency:** preserve rejected stages, raw archive, original
    CPU configuration and prior failed publication. Same selected files reuse the
    same accepted revision; changed bytes require a successor. No automatic
    publication replay, unknown-outcome relaunch, ignored ELF or CPU fallback for
    integrity failure. A changed kernel/device/lease rejects CUDA independently.
11. **Simpler alternative:** adding names/96MiB to the global CPU allowlist would
    change a released CPU seed and still leave rdmacm/cache/driver provenance open.
    Installing OS packages would mutate live global namespaces. Ignoring an optional
    transport or using NoExecPaths alone does not close readable/rematerializable
    executable bytes. A small explicit private extension is the required boundary.

## Protocol first and integration order

**Cache composition invariant:** the base snapshot pointer is immutable provenance,
not a claim that its CPU cache is mounted in a CUDA process. Its source manifest/
cache must still resolve and match their own unchanged seed. CUDA instead witnesses
its declared private cache at the actual read-only`/etc/ld.so.cache` binding. Later
host capture reuses the fixed CPU file/tool/alias checks with the explicitly declared
CUDA cache, then adds the six checked library descriptors. Never feed the combined
CUDA seed to the CPU-only snapshot capturer or accept the base cache mount as a CUDA
mount witness. The private cache must resolve all unchanged CPU names to their
existing fixed routes and the six CUDA names to this exact extension revision;
unknown, duplicated, hardware-specific or alternative ABI entries are rejected.
Publication/cache generation and actual ELF/mapped/device proof remain separate
from resolving this metadata/file set. No global cache update is needed.

1. Define `embedding-cuda-host-extension/1.0`: exact six named library members,
   driver release, unchanged base snapshot pointer/seed, CUDA-local cache metadata,
   deterministic extension/host hashes and typed pointer. Metadata is never a grant.
2. Test schema/Pydantic/raw canonical agreement, duplicate/missing roles, per-role
   sizes, CPU-base/pointer/hash mismatch, order stability and strict predecessor bytes.
3. Implement protected stdlib capture and the existing host-interface composition;
   verify real library/archive source and every transitive needed symbol/version,
   cache-selected route, FD epoch and mapping. Unknown/dlopen driver libraries are
   not implicitly allowed; an actual probe must fail closed if the declared set is
   insufficient and a reviewed successor is then required.
4. Add explicit native config/prefix-audit/bootstrap successors. The current
   root-local SEALED receipt/reader is CPU-only; do not relabel its evidence CUDA.
   Add a separately observed CUDA probe/receipt with real kernel, unit, namespace,
   mapped files, device and shared-lease closure before backend admission.
5. Publish/independently admit through supported owners, then run the original
   frozen six CPU/CUDA comparisons. No library contract/source test substitutes for
   the real probe, benchmark or conditional GPU-default activation.

No new package, host profile, CUDA account/device or model execution is activated
by this document. CPU seed/snapshot, active INDEX15 and all original QUERY outputs
remain unchanged. See [actual staging/inventory evidence](../operations/EMBEDDING_CUDA_PREFIX_PREPARATION_2026-10-16.md)
and the [full requirement ledger](../status/SYSTEM_RAG_GOAL_REQUIREMENT_AUDIT_2026-10-15.md).

## Implemented protocol slice —2026-10-16,15:49 UTC

Source only, **NOT_INSTALLED / NOT_ACTIVE / CUDA_NOT_ADMITTED**. JSON Schema2020-12
was added first, with an exact packaged mirror and raw resource hash. The pure
`embedding_cuda_host_extension` module validates frozen metadata and exact base/
extension pointers. Its ordered tuple contains exactly six roles; JSON Schema
rejects missing, repeated, reordered and extra members before model behavior.
All members have fixed basenames and role-specific bounds. There are no caller
filesystem paths, bytes, database values, unit grants or loader exceptions here.

The runtime seed binds base host seed, driver release, ordered library hashes/
sizes and the private-cache metadata. Logical/revision identity and capture time
affect the separate manifest semantic hash, not runtime identity. Final base
snapshot/pointer/hash/seed validation is mandatory. Metadata validity does not
claim source existence, root ownership, actual namespace, cache resolution, ABI,
mapped-file, kernel, device, GPU lease or probe acceptance.

Focused metadata/base-config/prefix-input/resource/dependency tests:174 PASS in
13.46seconds; strict type check1 module PASS; Ruff/format PASS. These overlap the
earlier145-test run and must not be summed. All322 predecessor resource records,
raw schema bytes and package mirrors are retained, with exact registry metadata
digest`99eb601c6b5fbd7e21bb57c7c6b52cf43b7c6839905333836a277dc580449953`.
Three older predecessor tests initially also counted later private-chat schemas;
they now exclude those explicitly additive successors while keeping each original
316/317/318-record count and digest unchanged. The initial test import invocation
error and subsequent four assertion failures remain in execution history; final
PASS was obtained by rerunning the affected cases, not hiding failures.

Official archive acquisition completed unprivileged at the existing temporary
package stage. Actual70,698bytes and SHA-256 match the pinned APT-index metadata.
Data-only `dpkg-deb --extract` inspected the122,144-byte`librdmacm.so.1.3.50.0`
without executing it, package maintainer scripts or candidate Python. Its exact
direct NEEDED names are ibverbs, libnl-core, libc and the system loader; version
needs include IBVERBS1.0/1.1/1.5/1.9/1.10 and GLIBC up to2.38. This is static
source evidence, **not yet independently admitted symbol-version resolution**.
No package installation, OS cache/driver change, model/GPU run, DB mutation,
service restart or additional login observer occurred in this source slice.

Next: implement the existing protected capture composition and explicit native
configuration/prefix/bootstrap integration, then independently admit the CUDA-only
probe/receipt and perform the six real comparisons. Do not deploy metadata alone
or bypass a dependency gate to call the GPU path complete. The original C1–C5
consumer and GPU-default requirements remain unchanged.

## Implemented file capture —2026-10-16,16:02 UTC

**SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE**. The stdlib-only
`embedding_cuda_host_capture` owner now resolves the exact six-field extension
pointer at its fixed protected root and the existing base CPU snapshot through its
unchanged supported resolver. The normal schema boundary in
`embedding_cuda_host_files` reuses that exact owner, rather than implementing a
second filesystem verifier. The new capture module imports no contracts, Pydantic,
JSON Schema, model, tensor or database package; an actual`-I -S -B` import test
checks that boundary. This is not yet a selected protected bootstrap release.

The owner checks canonical/raw/semantic/seed/identity closure, UTC and exact role
order, root-owned0444 single-link files with no named ACL/capability, protected
ancestor FDs, streaming member SHA/size and an exactly eight-member namespace
(manifest, cache, six libraries; no extra files/directories). Member permissions/
identity are compared before/after byte verification. The96MiB driver is not
retained as a Python bytes value; its own128MiB bound is independent of the unchanged
CPU and other-library8MiB bounds. Rechecks retain epochs, not repeated parsing,
hashes or copies. No filesystem path from model output selects a different root.

The existing cache parser now has one shared immutable entry representation.
The released CPU validator retains its existing interpretation, including ignoring
unrelated cache names, and its fixed seed/SONAME tables remain unchanged. CUDA
validates a separate closed cache with exactly the unchanged15 CPU routes and six
private-revision routes: no duplicate/unknown name, wrong ABI, OS/hardware variant
or other revision. Initial cache parsing is O(m), bounded at4,096 entries/128KiB;
the closed CUDA set is21 entries. This is not a new search/queue/cache service.
The generic existing own-FD/read-only kernel mount witness can observe this
capture's declared CUDA cache; a synthetic test distinguishes it from the base
CPU cache and rejects a writable mount. Synthetic ports are **not** actual root,
kernel or device acceptance.

Final combined capture/contract/base-host/prefix/wheel/installation/resource/
dependency suite:781 PASS in36.14seconds. Final narrow regression213 PASS,
strict3 production modules PASS, Ruff/format/diff checks PASS. These overlap the
earlier780/205/174 inventories and are not added. The initial21 test failures
identified group-writable implicit test ancestors and JSON-Schema exception
expectations; fixtures were corrected without relaxing production checks. Tests
also cover corrupt bytes/recomputed cache hashes, changed base/pointers, extra/
missing/linked members, ACL/capability, mutated constructed pins, bounded hostile
JSON, metadata-parser parity, no byte rehash on recheck and retained epoch changes.

No root extension was published, cache generated/mounted, prefix reinstalled,
service restarted, DB mutated, candidate interpreter/model/GPU executed or request
re-keyed. The existing original HTTP observer remains alive on EOM1, at LOGIN;
its pane has input enabled, is not in copy mode and owns the matching terminal.
No additional authentication window/question was created. Full C1–C5 remains open.

Next concrete boundary: explicit CUDA-native configuration and prefix/bootstrap
successors selecting this exact pointer and **actual CUDA cache**. Only then may
the protected owner compose existing CPU tool/file/alias checks with the six
actually captured ELF descriptors and independently admit versions, mappings,
driver/kernel/devices and shared GPU lease. The CUDA-specific native sealed
receipt/probe must not reuse or relabel the CPU-only receipt. Six real comparisons
and conditional GPU-default activation remain required, not replaced by file tests.

### Explicit installation integration decision

Add closed native-config1.2 and prefix-audit-input1.2 successors, CUDA-only. Each
selects one`cuda_host_extension` pointer; its base CPU pointer remains inside the
exact extension manifest rather than duplicated as an independently chosen value.
Native config preserves the existing bundle/proof/numerical/resource hash rules;
prefix input preserves source/archive/member/bootstrap byte closure. Neither is
a root receipt or device grant. Old1.0/1.1 schemas, strict readers and six/seven
bootstrap-module sets retain their meanings. The explicit1.2 prefix input pins
nine modules: the existing seven plus CUDA capture and CUDA host closure; only
that branch imports those two additional modules after their raw bytes are checked.

Compose an owner-held CUDA host with the existing CPU tool/file/alias verifier,
the actual CUDA cache witness, and six held byte-verified library FDs. Centralize
the existing bounded readelf metadata parser in the already trusted host module
so prefix and CUDA callers use the same ELF/version rules without a bootstrap
module dependency cycle or a new parsing framework. Keep prefix parser errors
and edge/digest output stable. CUDA additionally requires shared-object/no-extra-
loader/no-rpath/runpath metadata and every needed/version to resolve in the exact
six-member or unchanged CPU host graph. No96MiB Python bytes copy or mmap of an
externally mutable file is necessary. All process execution remains the already
captured fixed host readelf, never a candidate interpreter/library load.

Exact-type gates accept the composite only on CUDA paths. Composition delegates
tools/loader/absent-route checks and retains file/mount/FD epochs; it adds only
declared version providers and exact mapped inode checks. Runtime admission still
requires a separately observed CUDA sealed receipt/probe/device/lease and rejects
CPU-only acceptance for1.2. No database/schema migration or operational activation
is implied by adding these source interfaces.

## Implemented CUDA installation composition —2026-10-16,16:31 UTC

**SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE / CUDA_NOT_ADMITTED.** Native config1.2
and prefix audit input1.2 now have separately registered exact schemas/package
mirrors. Native config is CUDA-only, selects the extension pointer and reuses the
same bundle/proof/resource/numerical/hash rules. The explicit installed reader
handles1.2; strict1.0/1.1 readers still reject it. All323 predecessor resource
records and bytes are preserved, including metadata digest
`c56c4771df2bfd000a945c4820060afd1de5383ac7b9657f3e187851bd0d30df`.

The existing prefix inventory1.0 already supports both CPU/CUDA profiles and
continues to describe unadmitted candidate bytes; no new inventory version is
needed. In contrast, the sealed native receipt1.0 is intentionally CPU-only. Its
schema/domain rejection of the CUDA1.2 proof/config frame is explicitly tested;
adding a configuration version does not broaden that receipt.

Prefix input1.2 requires canonical JSON, one extension pointer and nine exact
ordered module pins. The OLD owner checks all nine raw modules before importing
CUDA capture/closure. Existing1.0/1.1 six/seven selected bootstrap sets remain;
ordinary installer staging still copies the prior seven modules and adds the
fixed two CUDA files only for the new canonical1.2 marker. That marker chooses
fixed copy names, **not authority**; full raw/version/shape/module checks remain in
the protected OLD owner. The synthetic shell test covers CPU, legacy CUDA and
CUDA1.2 separately; its inert interpreter is not an actual native acceptance.

The existing bounded readelf metadata parser now lives once in the already
trusted host module. Prefix callers retain their stable errors and output edges/
digests. CUDA composes the original fixed CPU tools/files/aliases with its actual
private-cache mount witness and six held byte-verified library FDs. It requires
shared-object/no-interpreter/no-extra-search-route metadata and resolves every
needed/version against the six-member or unchanged CPU host graph. Exact-type
gates reject that composite on CPU audit paths. FD/name/device/inode and all
underlying mount/file epochs remain live; cleanup closes library and base FDs.
No new abstraction framework, database, queue or binary dependency was introduced.

Final combined regression1327 PASS in99.78seconds; final expanded CUDA
closure/config tests35 PASS in3.98seconds (includes three later actual-source-
inspired cases; overlapping runs are not summed). Strict7 production/owner modules,
Ruff/format15 files, shell syntax/diff checks PASS. Tests cover legacy rejection,
exact module order/canonical bytes, safe old/new shell selection, CUDA-to-CUDA
versions, empty/unversioned versus missing providers, unknown routes, FD
substitution, cleanup, wrong CPU cache mount and CPU-only receipt rejection.

The first shared-parser trial exposed quadratic whitespace matching for optional
ELF Type on a2MiB blank-line fixture. Its own synthetic pytest process was
explicitly interrupted after185.57seconds/91 passes; it was not a runtime job or
observation timeout. Horizontal-only matching fixes the cause; the same maximum
input now passes a no-site subprocess deadline test. Subsequent trial failures
were stale fixture copy-set/exception expectations, one missing test import and a
legacy-only serializer in the new negative receipt fixture. Failures remain in
execution history. A full fresh rerun produced the1327 PASS above; no assertion,
receipt/profile gate, CPU bound or schema was loosened to declare success.

### Actual six-library static source diagnostic —16:26 UTC

A separate unprivileged no-site developer diagnostic used actual OS driver/RDMA/
netlink files and the hash-checked archive's rdmacm ELF. It opened exact resolved
regular-file FDs, streamed hashes, compared before/after identity and passed fixed
readelf metadata through the new shared parser. All six actually report DYN,
no interpreter and no RPATH/RUNPATH. No candidate interpreter, dlopen, tensor,
model/GPU execution, DB mutation, OS/driver installation or service restart occurred.
This diagnostic did **not** attest a protected namespace, complete provider/version
resolution, selected loader cache, mappings, kernel/device/GPU lease or admission.
**Six real static files are not the six CPU/CUDA benchmark launches.**

| Role | Actual bytes | SHA-256 |
| --- | ---: | --- |
| CUDA_DRIVER | 96284520 | `e8e541166449da5a1278f40b27a28d072174b31f2941b101a9609b6d1d3aed32` |
| RDMACM | 122144 | `18609553ba84c9206739d0a6d62ae5371d4713058ed4b68c665e627d967df648` |
| IBVERBS | 138032 | `249242c3ba29d72b7a9be560b768bf43fc5924c8a166f4e3bbb224bd81ade3ab` |
| MLX5 | 545464 | `61afce27090a889326a3a7eb5df44e003712503dbf31eb876fd3666578d2cfe6` |
| NL_CORE | 133944 | `afcb69e2ef0b46c2ce7b7483848332fa9462776d33163f64209acf01f86eddd7` |
| NL_ROUTE | 575344 | `088b0021d638306f5541e7baab06a0182b07db0a280e19b3b40c746f729b3773` |

The actual unversioned driver/netlink metadata motivated explicit empty-provider
regression; rdmacm/ibverbs/mlx5 version counts are inspected, not used as a substitute
for the still-required protected transitive provider check. These small dependency
pins are documentation, not Git-stored library binaries or runtime receipts.

Latest normal INDEX observation16:16:42 found the same PID2387580/invocation active;
next normal check no earlier than16:46:42 UTC. This is not a new vector coverage
or Artifact/hash audit. Existing HTTP observer2391005 remained at LOGIN in that
same check; no additional observer/question/key was created. No operating release,
worker, numerical space, Graph/policy/source, current index or historical result
was selected or altered by these source changes.

Next: privately generate/publish the declared CUDA cache/extension through the
supported protected owner, independently verify the actual1.2 OLD host/prefix
preflight, and implement/observe a **separate CUDA** sealed receipt/probe/device/
lease admission before any candidate/model execution. The CPU-only receipt remains
insufficient. Continue original C1–C5 and the six real frozen comparisons/conditional
GPU default; source/native file composition alone does not finish the goal.

## Private cache publication boundary

Use the installed static`/usr/sbin/ldconfig.real`, not the387-byte dpkg-trigger
wrapper and not a second hand-written cache serializer/sort implementation. Its
local official man page and installed help confirm`-r` private root,`-C` private
cache,`-f` private configuration,`-X` no symlink changes and`-i` ignored auxiliary
cache. Reviewed tool1051280bytes/raw
`d879c9a8a41240aeb7fd0f3221116fc4cf41cc6c64c24e10541d1bafbe537ab1`.
Never invoke it without explicit private-root/cache arguments.

The existing installation owner will publish the extension, not a worker or a new
application registry. Use the existing CUDA prefix-publication lock. Copy each of
the six approved, hash-pinned sources once into fresh root-owned stage inodes;
never chown user-held inputs, hardlink shared CPU files, change global loader
files or install OS packages. Source locations are not identity. The immutable
role/size/hash recipe is independent of source paths, and the optional rdmacm
input remains untrusted until its approved122144-byte content hash matches.

Generate the cache in one finite administrative unit with private mounts/network/
devices and only CAP_SYS_CHROOT, not a model worker. Its private chroot-shaped tree
contains read-only bind views of15 existing CPU library routes and the six staged
CUDA libraries at their final declared revision paths. This keeps the real cache
generator's format/order without copying the CPU payloads or changing the host
cache. Cache/config/auxiliary writes are confined to the private build root.
The selected static utility itself is copied from a held verified FD to a fresh
protected executable inode before use; do not execute a mutable path after hashing.

After terminal unit success, validate the exact21 routes, create canonical1.0
manifest/host/semantic hashes and atomically publish the exactly eight-member
root-local revision. Retain operation stage/unit/failure evidence outside that
canonical namespace. Missing/hash/source/permission failures never publish; an
unknown unit outcome never starts a replacement. Same valid revision may be
read/reused; a conflicting or incomplete revision is an explicit error, not an
overwrite. Existing root/file/FD/mount owners and schema remain authoritative;
no new wire schema, queue, database or model/device grant is needed for this local
administrative materialization. Separate native CUDA probe/lease admission still
precedes any candidate/model execution.

### Publication source checkpoint —2026-10-16 17:25 UTC

The stdlib-only `embedding_cuda_host_publication` administrative adapter now
implements this boundary. Its protected installed entry requires root, the OLD
Python3.12.13 with isolated/no-site/no-bytecode flags, and an immutable installed
owner-release path. The existing reviewed wheel installer remains code authority;
a source path or self-reported hash does not grant privilege. The publication
command is an internal frozen value, not a new cross-service wire protocol.

Fresh focused filesystem/contract/dependency tests169 PASS in14.83seconds; strict
type checking of the two changed production modules, Ruff and format PASS. Tests
include busy locks, source/size/hash substitution, incomplete/conflicting revision
rejection, valid reuse without another unit, exact21 readonly binds in one systemd
property, unit-state ambiguity, terminal failure/timeout evidence, bounded cache
output and stdlib-only import. They use temporary synthetic ownership and mocked
systemd execution; they do not prove an actual root publication or CUDA admission.

Trials exposed implicit group-writable parent modes under the caller's umask and
cross-parent rename of an already0555 directory. Production now creates every
private parent explicitly0700 and moves the complete private0700 revision before
sealing0555. A crash leaving an unsealed final revision is rejected, never silently
sealed/reused. Other trial failures were fixture ownership/argument-count issues;
the production owner guards were not loosened. Earlier truncated test output was
not counted: the fresh169-case run above supplies the recorded outcome.

The preceding4b51b533 standard three-wheel build/RECORD/OpenAPI gate also passed
at `/tmp/eom-api-build/4b51b533b45963d50551c1f0215abbbeba9534e8.dQ2SXg/dist`.
It predates this publisher and cannot be used to install it. A fresh reviewed
commit/build and existing protected owner-wheel installation must precede actual
publication. No root publication, OS/driver/cache change, model/GPU execution,
database mutation, API/Web release or service selection occurred in this slice.
Full C1–C5, original authenticated context verification and the six real fixed
CPU/CUDA comparisons remain open; CPU remains the operating default.

### Actual protected owner install and publication trial —17:26 UTC

Publisher source99a1c101 was pushed and built through the standard three-wheel/
RECORD gate. Platform wheel raw
`1d30208f1a3357aba42c95c0029c6facdf99d3321bb4cb9cd330e5dcb5b6413d`.
Existing root installer raw
`559ada516fe9d46f57926aad70699e81deba5f1a18b4e25e3f6e6bcdf1384b71`
verified and installed that exact wheel into its immutable owner-release directory,
using the admitted OLD interpreter and a pre-exec readonly accepted CPU cache.
No numerical prefix or shared API installation/activation occurred.

The first finite installer unit exited2 because ProtectSystem=strict left pip no
writable temporary directory. It published no final release. After confirming
terminal failure and final-path absence, the second unit supplied TMPDIR within
the already permitted root owner-release namespace and installed successfully;
original stage/log/journal evidence remain. No global /tmp write exception or
installer-source change was required.

Actual publisher unit then exited1 with DIRECTORY_MODE_INVALID before any library
copy/cache unit/model operation. Root0755 extension root exists; the new logical
directory is root0700 because the administrative0077 umask narrowed mkdir0755.
Failed logical ID`embeddingcudahost_8c38c43d910c4f6a869ea283d1c8eb3c` remains
unmodified; no revision/workspace was published. A reproducing regression failed
before the source correction. The creation helper now fchmods only its freshly
opened no-follow owned inode to the declared mode; existing incomplete directories
still fail and are never repaired. Fresh focused170 PASS/strict1/Ruff follow the
fix, with one additional existing-directory regression checked separately.

This is a source defect discovered by a real protected trial, not a CUDA model
failure, permission bypass or reason to disable the guards. Build/install the
reviewed successor before a new explicitly identified publication. Preserve both
terminal attempts. Original HTTP authentication observer is unchanged; no extra
login prompt/key/model request or shared-service restart was introduced.

Successor6f202b7c standard build and protected owner installation passed; fresh
expanded focused171 PASS. Its first actual publication copied the exact96,284,520
driver bytes, then explicitly failed FILE_UNAVAILABLE on the next source. Bounded
read-only stage metadata confirms only that driver file exists; no cache unit or
canonical revision was created. The declared rdmacm input is inside an eom0700
temporary parent, while the administrative unit intentionally has no capabilities.
Root without DAC capabilities cannot traverse that caller-private directory.

For the next known-terminal operation, retain the empty capability set and input
privacy. Have the existing systemd mount owner expose **only that one declared
untrusted file**, read-only, inside a fresh private temporary input mount. The
publisher still requires its eom UID, fixed basename, byte count and independent
hash before copying into a fresh root inode. Do not chmod/chown the caller tree,
grant broad DAC authority or copy the archive to another canonical location.
This is a narrow administrative staging view, not worker source/NAS permission
or native admission. Preserve both failed logical/workspace identities; do not
retry either same revision or silently mark the existing driver copy complete.

### Actual publication and protected static closure PASS —17:30 UTC

The successor finite unit with that single readonly input view completed and
published the exact eight-member root-local revision. Every file is root0444,
regular/single-link and the final revision directory is0555. The cache generator
terminated successfully in its private chroot; installed capture independently
validated all21 exact base/CUDA routes and canonical manifest/file hashes before
returning CREATED. No OS package, system cache or original input tree was changed.

| Identity | Actual value |
| --- | --- |
| Installed owner source | `6f202b7c3e5e85338a19693aa8fb73084c36c1a0` |
| Platform wheel SHA-256 | `f300f96ae2d8b6ac986f4db6ac660520d059ca3a774e61533076437446e9339f` |
| Logical extension | `embeddingcudahost_99ec37f55bbb42de8edb1e889c9d3a25` |
| Immutable revision | `embeddingcudahostrev_3a79d32835b94a5e95532828fe324322` |
| Manifest bytes/raw SHA-256 | 2166 / `b3ef4a05805fe60b8cd22f3fadc5a9836b34265a817ff9d33bf8da94f390036f` |
| Semantic snapshot SHA-256 | `8cecc412c25268f58c1476d3aef742c42d03f596935799dd5ccfe8b6f78e7f7d` |
| CUDA host seed SHA-256 | `1690844d36f4e8fcd59888896aaf2e248a1a3170c24f445559692fb1cfa48591` |
| Cache bytes/raw SHA-256 | 2135 / `222b7ae7827ba996777b2f83fbc9f6757ebe1e013090e14868454711f18b7d8c` |

Canonical fixed root is`/opt/eom/embedding-cuda-host-extensions`; identity remains
logical ID plus revision, not that storage path. The accepted CPU snapshot/seed
are unchanged and remain explicitly referenced provenance, not relabeled CUDA.

A separate finite readonly installed-owner diagnostic then ran the accepted OLD
interpreter with this exact CUDA cache bound **before exec**, UID1000, no
capabilities, private devices/network, readonly system, fixed empty CUDA cwd and
inaccessible source/NAS/secrets. The supported capture resolved the snapshot,
checked real kernel cache mount/file epochs and fixed CPU tools/DSOs, held six
library FDs and inspected all declared SONAME/needed/version edges with fixed
readelf. Entry/exit epoch checks passed; terminal unit exit0 reported
STATIC_PROTECTED_HOST_PASS_NOT_NATIVE_ADMITTED. This is the actual host-only
namespace/byte/version composition, not the full candidate-prefix audit, nine
bootstrap1.2 input, candidate/kernel mapping receipt, GPU device/lease proof or
six numerical comparisons. Output zero-model/device fields describe the limited
program scope, not an independently instrumented syscall audit.

Operating evidence lives in the existing temporary operation directory:
`cuda-host-publication-6f20-v2.log` and`cuda-host-closure-6f20.log`; failed99a1 and
6f20 logs/workspaces remain separately retained. Source regression is now fresh
171 PASS in14.81seconds; earlier170/169 overlapping runs are not summed. Standard
successor build/installed-owner RECORD gate passed. No shared API/Web/INDEX/QUERY
release or model execution occurred; CPU remains selected. Next use the declared
snapshot in the protected1.2 OLD full-prefix owner boundary, preserving the original
root-staged candidate and failed inventory. Do not recopy a large unchanged prefix
or run its interpreter merely to bypass the existing developer-only publish path.

## Readonly staged-prefix re-audit owner boundary

1. Responsibility: extend the existing protected `install_index_runtime.sh` owner
   with a distinct `audit-staged` command. It audits an already root-staged fixed
   prefix; it neither republishes nor installs/adopts a numerical runtime.
2. Canonical inputs remain immutable archive/source/lock/bootstrap pins and the
   explicit1.2 CUDA host snapshot. A failed stage or directory fingerprint alone
   is not authority to execute a candidate.
3. The numerical prefix identity/profile and pinned source revisions remain the
   same; each new audit gets a fresh existing-format private operation directory.
   Original failure receipts/inventory are never overwritten.
4. Reuse the existing typed prefix-audit input and protected OLD leaf. Validate
   exact bytes/hash, profile, helper, nine bootstrap modules, host mount and every
   archive/source/member/needed/version edge before emitting a new inventory.
5. Access patterns are one lock claim, ordered bounded input copies, a full
   streaming tree fingerprint, then the existing indexed archive/ELF audit.
6. Reuse the existing fixed profile publication lock, source pin maps, frozen
   archive plan and deterministic inventory manifest. No new queue/table/cache.
7. Cost remains O(bytes + entries log entries) for the existing tree fingerprint
   and archive/prefix verification, with bounded audit metadata. The upfront tree
   check associates the expected previously staged input, while the full audit
   independently proves archive/source closure. Avoid the multi-GB prefix copy.
8. Hold the same profile lock throughout; require root-protected prefix ownership,
   modes and contained links. The actual administrative unit must expose that
   prefix read-only. A fresh stage holds only small input/receipt/inventory data.
9. Shell remains the administrative filesystem adapter; the existing OLD Python
   leaf owns protocol/hash/closure validation. Candidate Python is never called.
10. Explicit terminal errors retain their new audit stage. No automatic rerun,
    phase repair, failed-history promotion or activation. Successful output is
    AUDITED_NOT_ADMITTED; native sealed proof/device/shared lease remain separate.
11. The simpler developer-only publish path requires recopying or chowning an
    already protected large prefix and then executes its installer. That is both
    unnecessary and the wrong side effect for a readonly recovery audit. Add one
    supported command to the existing owner, not an ad-hoc root recovery script
    or parallel admission framework. CPU legacy publish behavior stays covered.

### Staged-audit source verification —17:38 UTC

The existing shell owner now implements `audit-staged` with that exact boundary.
It shares the existing argument closure, lock, input copies, host preflight and
full OLD prefix-audit leaf, but never creates a prefix quarantine, copies/chowns
the candidate, replaces its directory or enters candidate Python. Fresh audit
receipts/inventory are separate from every failed stage. Recursive root-owner
checks reinforce the previous publication chown invariant for an existing prefix.

Combined installation/CUDA-input/publication regression163 PASS in8.59seconds;
includes old CPU/CUDA publish behavior, readonly staged success for both profiles,
prefix inode/mtime/content preservation, OLD-only order, tree/mode/owner/busy-lock
denials and host/audit/inventory failures without replacement/execution. These
shell tests use inert interpreter surrogates and explicit synthetic UID/path
substitutions; they are not actual prefix closure/native/GPU proof. Ruff/format,
shell syntax and diff checks pass. No new dependency, schema, database or runtime
selection is introduced. The original full goal and separate device/lease gate
remain open; actual protected staged audit is next, not inferred from these tests.

Actual reviewed97cddd56 standard build/RECORD gate passed and its byte-pinned
root-installed shell started the distinct readonly staged audit. Unit
`eom-cuda-staged-audit-97cddd56.service`, invocation
`73d85dcfbb974531a9cb06c7e66b57d0`, PID2545730 was confirmed live17:40:48 UTC.
Input1.2 is20,012 canonical bytes/raw
`f98bfe51b047b574e7f4d7520a21a0fd410d85d3eb13ddceddc4b25f48272071`;
it preserves the31 Conda/70 public/B41 private/lease source pins, created-at/history/
helper bytes, and selects the exact published CUDA snapshot plus nine current
bootstrap module pins. It does not modify a numerical space or existing config.
Fixed prefix/OLD/archive/source are readonly; only the CUDA profile lock and a
fresh small audit directory are writable. CAP_DAC_READ_SEARCH permits reading
declared caller-private inputs, not writing them; private devices/network and
inaccessible NAS/secrets remain. The original failed stage/backup stay untouched.
This paragraph records launch/liveness, not terminal PASS.

Review tightened successor audit stdout to expose only actually checked input/tree
hashes plus audit paths, not an unassociated caller CLI source-commit label. The
running immutable97cddd56 owner is unchanged; its actual known B41 source is
verified through the pinned input/inventory, not that descriptive stdout label.
No redo of the expensive audit is needed solely for this presentation correction.

### Actual full staged-prefix audit PASS —17:45:35 UTC

The same confirmed unit terminated inactive/dead, MainPID0, Result=success and
ExecMainStatus0. Its stdout explicitly reports AUDITED_NOT_ADMITTED/NOT_PROBED.
Both protected host and full prefix byte receipts pass. New operation directory
is`/opt/eom/.embedding-index-install-YC7k6rKQ`; original failedP301NWlp inventory
remains root0600/single-link/**0 bytes**, independently re-observed unchanged.
The new root0600/single-link candidate inventory is8,914,997bytes, raw
`2f4a9c6d25d6be3e3d83b74f7f9d5d15013d9f91e050b1381af9589cd3b64c1b`.
It is still CANDIDATE_NOT_ADMITTED, not a sealed native receipt.

| Audited fact | Actual value |
| --- | --- |
| Entries / regular / links / ELF |31556 /27983 /1380 /287|
| Regular payload bytes |7084538375|
| Source closure SHA-256 |`e0bf9834c7c36c582f90d4fbfdc8d9d340ac2595f65c4e102652ad2efc75bca5`|
| Member inventory SHA-256 |`fd2123c02eacf5bfaab24da2c86b5cb53efa78a54fe493984099d948ef241b62`|
| Full byte closure SHA-256 |`08da7a22977a9fd25a2712839fae9d326f9708fd2b2da189b52c3a1b9accb1ff`|
| ELF closure SHA-256 |`7b62805e3a02ac8bd2cab56484b0558fbd102c63dec064b53562f9f9533afac3`|
| Semantic inventory SHA-256 |`a9a5007622396f2a566d41909afc0216987b5b72a481e435b73a4215de43601e`|

The new input raw matches its pre-run20,012-byte pin and exact published CUDA
host seed. Stage metadata/receipt inspection is bounded and readonly; a JSON
summary alone is not additional native authority. The unit journal reports
3min19.998s CPU and4.0G cgroup memory peak under its4GiB cap; that administrative
measurement includes filesystem work/page cache, not model RSS or GPU capacity.
No previous stage, numerical prefix, CPU/current index/source policy, worker,
system package/cache or shared service was replaced. No candidate Python/helper,
tensor, model, CUDA-device probe or benchmark was invoked. Status is now
**ROOT_STAGED / BYTE_AUDITED / NOT_ADMITTED**, with the original byte-audit failure
preserved as historical evidence. Next separate CUDA sealed receipt/probe/kernel/
device/shared-lease acceptance must precede candidate/model use, followed by the
original six frozen CPU/CUDA comparisons and conditional default/C1–C5 work.

Final source presentation/metadata-preservation regression163 PASS in8.56seconds
overlaps the earlier163 run; independent prefix/host/CUDA capture suites327 PASS
in19.93seconds. Do not add these overlapping counts. Ruff/format/shell/strict
unchanged OLD leaf checks pass; actual97cddd56 standard build/RECORD gate passed.

Separate readonly accepted-OLD/installed-owner metadata validation subsequently
read that exact8,914,997-byte raw-pinned inventory through held protected FDs and
the existing pinned JSON Schema2020-12/Pydantic candidate parser. Its semantic
inventory hash, profile, original owner-input hash, entry/ELF counts and final
file epochs all pass: CONTRACT_PASS_NOT_NATIVE_ADMITTED. This does not relabel
the CPU-only1.0 admission receipt or supply a missing CUDA kernel/device lease.
Routine INDEX observation17:48:46 (over30minutes after the preceding17:18:21)
found unchanged PID2387580/invocation active; not a new canonical vector coverage
audit. Existing original HTTP observer2391005 is live at LOGIN with empty output;
no new process/question/key was created. Next routine INDEX check≥18:18:46 UTC.
