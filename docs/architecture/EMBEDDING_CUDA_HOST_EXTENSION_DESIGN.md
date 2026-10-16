# CUDA host extension: closed private libraries, not a CPU allowlist expansion

2026-10-16 UTC. Design before protocol/behavior. SOURCE_CANDIDATE / NOT_ACTIVE.
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
