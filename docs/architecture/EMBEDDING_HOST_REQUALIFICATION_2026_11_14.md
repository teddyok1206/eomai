# 2026-11-14 embedding host requalification

This is the existing [host requalification](EMBEDDING_HOST_REQUALIFICATION_2026_10_21.md)
path, not a new embedding model, queue, search engine or dependency-update service.
Source verification, installation admission and actual vector storage are separate gates.

## Observed cause

At 06:06:17 UTC, the installed package log records libc6 changing from Ubuntu
`2.39-0ubuntu8.9` to `2.39-0ubuntu8.12`. `dpkg -V libc6` reports no package-file
integrity difference. A bounded read-only probe in the existing QUERY namespace
checked all 23 selected host files: exactly eight glibc member hashes differ;
their lengths and the other 15 members, including the selected loader cache, match.
The actual verifier correctly denies `INSTALLED_RUNTIME_FILE_HASH_MISMATCH`.
Evidence: `staging/native-query-host-files-diagnostic-20261114.json`.

## Scoped design

1. **Responsibility.** The existing fixed host closure owns the reviewed table;
   existing snapshot, native installation/admission and INDEX/QUERY selection owners
   publish and select successors. Material/Codex processing stays independent.
2. **Canonical source.** Current protected OS package files and existing immutable
   model/tokenizer/numerical archives remain canonical. Do not downgrade the OS or
   invent an old-glibc per-unit bind to make the previous receipt appear current.
3. **Identity.** Add one named, content-addressed November glibc baseline over the
   reviewed October 23 baseline. Preserve every predecessor table, seed and receipt.
   New host/config/inventory/probe/receipt revisions are installation identities,
   not a replacement embedding space or a reason to re-encode existing documents.
4. **Pointers.** Resolve the exact compiled baseline and existing snapshot/config
   pins with normal bounds, permissions, raw/semantic hashes, mount/FD/ELF/alias/
   closure checks. Never accept an arbitrary current file allowlist or latest.
5. **Access.** One O(1) baseline lookup and bounded ordered 23-member capture; no
   corpus traversal or database query belongs in host approval.
6. **Structures.** Reuse immutable file tuples and the existing closed mapping.
   No new schema, DB table/index, registry, environment flag or library dependency.
7. **Cost.** O(23) metadata derivation and streamed bounded file verification.
   Existing held epochs prevent repeated full-prefix hashing per document/query.
8. **Concurrency.** Use the existing CPU/CUDA publication locks and exact affected
   unit quiescence. Preserve retained INDEX parent/claim/allocation/execution before
   selecting a supported completion, retirement or unstarted-cancellation path.
9. **Dependencies.** The stdlib host adapter remains shared with protected bootstrap;
   contracts remain pure. Metadata SDK and numerical runtime source pins are separate.
10. **Failure/replay.** The predecessor still rejects new glibc. Only explicit new
    snapshot selection may use the new table; fresh real native admission precedes
    activation. Never replace pins in an existing INDEX plan, relabel a failed run,
    discard completed vectors, or use readiness as evidence of new vector storage.
11. **Simpler alternative.** A hash bypass or in-place receipt update destroys the
    invariant; copying old system libraries creates a new unsupported runtime.
    One reviewed table plus the existing requalification path is the smallest fix.

Keep encoder/codec/L2 implementation, weights, tokenizer, recipe, dimensions and
numerical fingerprint independently verified. Host evidence alone does not prove
bitwise numerical equality. Preserve compatible existing vectors and verify a real
new common-format vector commit after supported INDEX recovery.

## Source delta and execution order

The only new fixed-host entries are `ld-linux-x86-64.so.2`, `libc.so.6`,
`libpthread.so.0`, `libdl.so.2`, `libutil.so.1`, `libm.so.6`, `librt.so.1` and
`libresolv.so.2`. Their exact expected bytes are compiled in the named baseline;
source tests require exactly this delta, immutable predecessors, unknown-seed denial,
and both CPU/CUDA dispatch to the existing capture guard.

After source validation: install a protected inactive candidate; publish/audit matching
CPU/CUDA host/configuration successors through existing owners; obtain actual no-forward
admission; inspect and recover original pending INDEX work through supported ownership;
select compatible INDEX/QUERY controls; verify real new embedding storage and retrieval.
This document does not claim those operational steps have already completed.
