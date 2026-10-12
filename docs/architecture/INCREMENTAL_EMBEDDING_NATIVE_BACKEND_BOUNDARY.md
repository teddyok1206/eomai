# Native bundle resolution and numerical backend boundary

2026-10-12 UTC. Source-only successor; NOT_INSTALLED / NOT_ACTIVE / NOT_EVALUATED.
This note is written before the resolver/backend implementation. It implements only the
next adapter seam from `INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md` §§3, 5, 9–10.

1. **Responsibility/boundary.** An owner-configured bundle resolver verifies one protected
   bundle and the existing payload; an optional offline backend implements the native
   encoding port. It neither admits a workflow nor launches, publishes, or activates it.
2. **Canonical source.** Existing legacy `manifest.json` and its registered immutable
   member files remain the only canonical model payload. The successor stores only
   small `bundle.json` metadata. Neither copies nor hardlinks model bytes are created.
3. **Identity/revisions.** Payload model/revision, execution model/revision, bundle/revision,
   manifest semantic/raw hashes, file-set hash and numerical runtime hash remain distinct.
   The flat execution spec is exposed only after exact bundle/payload closure checks.
4. **Pointers/resolution.** Owner configuration supplies protected storage roots and the
   exact bundle pointer, separately from a worker request. Resolve derived immutable
   locations, schema/media/identity/raw/semantic hashes, canonical bytes, exact legacy
   file set, member SHA/size, ownership/modes/link safety and before/after file identities.
   Release lifecycle and operator authorization remain the owner's admission boundary;
   filesystem verification is not an independent permission grant.
   This shared legacy seam retains named-path/leaf-FD checks and ancestor symlink rejection;
   it does not establish the future launch verifier's full root-owned held-ancestor-FD proof.
5. **Access patterns.** Exact immutable revision lookup, streaming member verification,
   small descriptor equality, and bounded ordered batches dominate. No latest lookup,
   database access, global model cache or cross-worker exchange is introduced.
6. **Structures/indexes.** Frozen snapshot values, ordered tuples, and the authoritative
   legacy resolver's file set protect identity/order. No persistence schema/index changes.
7. **Scale/complexity.** Bundle metadata is at most 64 KiB. Weights are streamed O(bytes)
   once per resolved payload; later observations are O(member count) stat checks. Encoding
   preserves bounded O(rows × dimension) host output and bounded batch working memory.
   Relevant imported implementation files are bounded to 128 KiB each, opened no-follow
   and hashed once; subsequent read-back checks retained file/directory identity epochs.
8. **Concurrency/transaction.** No DB transaction surrounds inference. A trusted ownership
   handle is required before CUDA import/initialization/load and revalidated before/after
   work. The owner retains its physical lease through synchronized teardown/unit exit.
   This seam does not acquire, release, or claim production GPU migration is installed.
9. **Dependency/ownership.** Catalog adapters depend on contracts/ports. Core imports never
   import PyTorch/Transformers. The legacy resolver gains a supported snapshot seam used
   by both paths; legacy CPU behavior and released manifest/spec bytes remain unchanged.
10. **Failure/retry/idempotency.** Missing/stale/hash/changed payload or bundle, missing
    trusted runtime observer/CUDA ownership, runtime/device/recipe drift, overflow,
    non-FP32/mixed-device tensors and inference failure produce stable explicit errors.
    No fallback, truncation, batch/dtype shrink, warn-only determinism or latest substitute.
    Before/after actual observations must match the exact configured descriptor.
11. **Simpler alternative.** Passing a CUDA flat spec to the CPU resolver either breaks its
    exact legacy manifest invariant or requires duplicate weights. `.to("cuda")` alone
    cannot establish runtime proof or physical ownership. A small successor resolver and
    a lazy backend, with narrow observation/ownership ports, preserve those boundaries.

## Trusted runtime observation seam

The backend reads actual Python/package/module versions, its relevant imported implementation
file hashes, torch CUDA build, device placement, eager/eval/FP32 state, numerical flags and
thread settings. It constructs the recipe from read-back, not request claims. A separate
required owner-supplied observer supplies verified distribution archive hashes and physical
hardware/driver identity. The observer takes no worker request or expected descriptor.
Wheel SHA cannot be inferred from a version or reconstructed from imported code; a concrete
protected installer-receipt plus RECORD/driver/device observer is still an installation gate.
Absence of that observer denies execution. Synthetic observer/lease PASS is source evidence
only, not proof of an installed runtime, released policy or GPU activation.

The unreleased native backend port also exposes the exact configured batch size and actual
thread read-back. The focused encoding adapter compares those values with the canonical
request before and after encoding, alongside model/device/runtime equality. A matching
runtime hash alone cannot authorize a different request batch/thread recipe. No wire schema
or historical CPU interface changes are needed. Interop threads are fixed to one by the
versioned offline encoder implementation and checked directly.

No dependencies are added: lazy imports use the already designed isolated native runtime.
The backend never imports image services, invokes model downloads, spawns a process, accesses
NAS/DB, or consumes an external LLM API.
