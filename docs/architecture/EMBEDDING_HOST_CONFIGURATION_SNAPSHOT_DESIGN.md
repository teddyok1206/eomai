# Immutable embedding host-configuration snapshot

2026-10-16 UTC. FIRST_SOURCE_SLICE_IMPLEMENTED / NOT_INSTALLED / NOT_ACTIVE.
This is a scoped continuation of the original incremental-RAG runtime goal, prompted
by the [observed OS cache drift](../operations/LOCAL_INDEXING_HOST_CACHE_DRIFT_2026-10-16.md).
It authorizes no new role, source access, model run or operating-system update policy.

1. **Responsibility/boundary:** existing runtime installation/admission and fixed
   unit owners materialize and select one immutable loader-configuration snapshot.
   Keep Catalog source authority, INDEX/QUERY execution and Artifact ownership
   unchanged. Do not build a second installer, queue or search service.
2. **Canonical source:** independently inspected protected OS configuration bytes,
   preserved with exact hash/size and small installation evidence. A deployed
   root-owned snapshot is an explicit installation materialization, not a second
   model payload, mutable cache or replacement for current executable/library checks.
3. **Identity/revision:** a minimal versioned snapshot manifest pins its logical and
   immutable revision identity, selected file roles and raw hashes. Keep this apart
   from model/encoder numerical fingerprints. Do not recalculate vectors because
   unrelated ldconfig entries or installation metadata changed.
4. **Pointers/checks:** JSON Schema2020-12 and frozen models before behavior. Use
   fixed owner-derived installation locations, no caller-supplied paths or authority.
   Verify raw/semantic manifest hash, bounded no-follow files, owner/mode/nlink/ACL,
   FD/named identity, expected roles, loader-cache structure and relevant lookup
   closure, all existing executable/library/alias/dependency/version checks. A
   changed raw cache is not automatically accepted because libc alone is unchanged.
5. **Access patterns:** one initial bounded configuration read, exact role lookup
   and immutable epoch validation; reuse existing runtime file snapshots. No source
   population traversal, numeric encoding or database query belongs in this reader.
6. **Structures/indexes:** small frozen manifest and role-keyed file map/set; existing
   installation evidence/pointer owner. No DB table/index, mutable latest registry,
   globally writable cache, dynamic library allowlist or deployment framework.
7. **Scale/complexity:** loader cache remains bounded128KiB; fixed file-role set.
   Initial bytes O(B), later fixed-count epoch checks O(1). Relevant host library
   verification retains its existing bounds; never hash a full ML prefix per text.
8. **Transaction/concurrency:** drain affected native admission and prove no unknown
   running/allocated work before installation selection. Bind the exact read-only
   snapshot at its required OS location **before process exec**, not after Python
   imports. Real mount/FD/loader/proc observations must verify the selected namespace.
   New unrelated global cache generation must not retarget an admitted process.
9. **Dependency ownership:** stdlib manifest/filesystem code remains infrastructure;
   systemd/mount configuration belongs to existing fixed launcher/installer adapters.
   Domain/contracts import no filesystem, subprocess, SQL or ML. Existing scope and
   frozen historical profile readers retain their exact predecessor semantics.
10. **Failure/retry:** old host seed/receipt/proof bytes are immutable. Use explicit
    compatible successors and exact component selection, never a false-equality
    wrapper, latest fallback, skipped hash or replaced OS cache. Relevant OS library
    changes still stop admission and require fresh review. Retain the original
    pending command until its exact launch/allocation and supported compatibility
    path are known; supported preallocation retirement may be needed, never direct
    row repair or a new key to hide an uncertain execution.
11. **Simpler alternative:** updating one hard-coded global cache hash after each
    unrelated package update repeats this failure and invalidates installations.
    Removing cache checks loses loader closure. A small immutable configuration
    materialization plus existing fixed-unit namespace/evidence is the smallest
    way to preserve reproducibility without disabling OS security updates.

## Concrete implementation order

1. Inspect the complete current host closure and snapshot format, not only raw-cache
   inequality. Define minimal closed schema and predecessor/successor semantics.
2. Extend existing file/admission adapters. Add missing/stale/hash/permission/ACL,
   duplicate-role, live-cache-versus-snapshot, namespace and historical-byte tests.
3. Prepare compatible protected CPU environment/entry/verifier/units through the
   existing installer, preserving original prefixes/receipts. Keep the same numeric
   weights/tokenizer/encoder recipe; independently prove numerical identity before
   reusing its space. Do not assume installation/source changes are numeric changes.
4. Verify real first-instruction namespace and denial behavior under actual UID and
   limits. Select compatible owner configuration/policies with existing release
   operations; no worker sudo/groups/DB/NAS permission expansion.
5. Recover the original INDEX work through supported ownership/claim rules, verify
   one terminal/follow-on then restore the30-minute routine observation cadence.
6. Only after native readiness, resume the original genuine HTTP key with one human
   login. Then continue C2–C5 and the real six-launch CPU/CUDA/default-device gates.

Rollback selects a compatible earlier runtime set only if its actual host assumptions
still hold. Do not roll the OS cache backwards, delete new artifacts, amend old
acceptance or label a still-invalid installation healthy.

## First source slice and shared capture boundary

The first source slice defines the closed manifest/pointer, fixed-path file resolver
and actual own-FD/read-only-mount witness. It is not an installation receipt or an
activation. Its manifest pins both the unchanged baseline host seed and the target
seed calculated by substituting **only** the cache size/hash in that baseline.
The resolver checks this relation, not merely the manifest's self-hash.

Keep the original fixed-host capture entry point and seed bytes unchanged. A separate
snapshot capture entry point requires an already observed exact read-only mount and
an independently supplied expected target seed. Both paths use one private capture
implementation for all executable, library, alias, absence, dependency and symbol
version checks. The snapshot path rechecks its namespace/mount witness alongside the
same held host descriptors. It does not generalize the host allowlist or admit a
native installation. This small extraction serves two concrete capture paths, not a
new loader/installer framework.

The existing native configuration/receipt/factory/unit consumers are deliberately
not redirected by this source slice. Their compatible configuration selection and
pre-exec binding remain a separate required integration before any service restart.

The filesystem adapter owns the snapshot entry point and calls the same package's
private host-capture primitive. The fixed host module only receives a bound local
mount recheck, stays stdlib-only under `-I -S -B`, and never imports the filesystem
adapter, Pydantic, contracts or ML. There is no lazy/circular import workaround.

### Source verification (not runtime recovery)

- Final focused contracts/files/mount/shared-host and frozen-predecessor suite:
  298 PASS. Closed schema/mirror/raw pin, 316 prior resource bytes and the original
  296-resource acceptance remain frozen, without changing historical digests.
- Expanded host/prefix/Conda/wheel/native-receipt/CUDA-directory suite:955 PASS;
  it imported the source before the final malformed-JSON/missing-member additions.
  The final focused suite covers those additions. Counts overlap; do not sum them.
- Installed-release/factory/entry/probe/fixed INDEX/QUERY template regression:
  279 PASS. No runtime unit or prefix was selected by these tests.
- Strict type checks:6 files PASS; Ruff format/lint and diff whitespace PASS.
- Synthetic filesystem/namespace tests are not a real root-held snapshot, pre-exec
  mount or fresh native admission. No model, GPU, DB mutation or service restart.

Source ownership: schema and frozen values in `eom_catalog_contracts`; fixed-path
materialization/mount witness in `embedding_host_configuration_files.py`; fixed host
closure in `embedding_runtime_host_closure.py`. No new dependency, database object,
queue, model payload, worker access or deployment selection is introduced.
