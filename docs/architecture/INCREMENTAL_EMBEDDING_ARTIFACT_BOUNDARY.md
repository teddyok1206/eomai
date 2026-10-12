# Incremental embedding Artifact boundary

This implementation composes the existing Orchestrator `ControlFileSetPublisher`;
it does not activate a Workflow, grant source access, run an encoder, add a DB
table, or write directly to NAS. Contract definitions are schema-first in
`item-inference-transfer-embedding-v1.schema.json`.

1. **Responsibility and boundary.** `EmbeddingArtifactStore` validates one native
   encoding result and publishes exactly `result.json`, `shard.json`, and
   `vectors.f32` through the existing owner. Its caller must first resolve the
   pinned input Artifact and reauthorize current source/report/Graph/policy access
   using the supported owner boundary. DTO possession is not authorization.
2. **Canonical source.** The registered source, accepted report, and profile stay
   canonical and are not copied here. One binary member contains the numerical
   rows. `result.json` is the primary immutable execution record; `shard.json` is
   the independently referenceable reusable component. Repeating bounded shard
   metadata in the execution record is an explicit validation/publication
   materialization boundary, not a second vector copy. No source text, report,
   PNG, PDF, or model weights are published.
3. **Identity and revisions.** The logical encoder Job in the native input/result
   is separate from the publication owner's Job, Artifact ID, Artifact revision,
   and content hashes. The owner assigns publication identities; reuse retains
   exact member pointers rather than resolving latest revisions.
4. **Pointers and resolution.** The Workflow input pointer must hash the exact
   canonical native input; Workflow space/input-set and result Job/request/space/
   ordered rows must match. Source files are bounded regular own-UID, single-link
   mode-0600 members of a protected mode-0700 local directory, read through
   no-follow FDs with ancestor and file identity checks. Canonical JSON has no
   trailing newline. Raw vector SHA, byte count, dimension, row count, finite
   values, and stored unit norms are verified without repair or renormalization.
   Nested official JSON schema URIs have no fragments; the binary schema label
   identifies a float32-LE codec, not JSON Schema validation of binary bytes.
5. **Access patterns.** This boundary performs fixed-name lookups, one ordered
   scan of the bounded vector rows, and immutable same-key publication replay.
6. **Structures and indexes.** A fixed three-member tuple and small frozen receipt
   suffice. Existing publisher Job/idempotency and Artifact records own all
   persistence and indexing; no embedding registry, vector DB column, or new
   mutable cache is introduced.
7. **Complexity and scale.** Work is O(metadata bytes + rows × dimension), with
   at most 1024 rows, dimension 4096, and 16 MiB of float32 bytes. Temporary
   materialization is bounded; the returned value contains only three pointers,
   the two Job identities, and the outer manifest SHA.
8. **Transaction and concurrency.** Exclusive member creation preserves an
   existing shard rather than overwriting it. The existing publisher's same-key
   lock, immutable request comparison, stage-hash checks, NAS commit, and DB
   completion transaction own concurrent replay and interrupted-commit recovery.
   Local FD identity is checked again across publication; a changed workspace or
   file is an explicit failure, never proof that nothing was committed.
9. **Dependency direction and ownership.** Orchestrator infrastructure depends on
   public workflow/catalog/protocol contracts and the shared IO-free binary
   codec, not Catalog service implementation. Only `ControlFileSetPublisher`
   commits NAS content. No worker receives NAS or database access.
10. **Failures, retry, and idempotency.** The publication key pins the logical
    encoder Job and full native Workflow request hash. Missing, symlinked, changed,
    noncanonical, hash-mismatched, or invalid-norm members fail before publication.
    A conflicting existing shard or owner receipt fails explicitly. Publisher
    failures are not auto-retried here; an explicit same-key replay uses existing
    publisher semantics and does not run the model again. The caller retains the
    original UTC publication timestamp and installed source commit on replay;
    changing either is a publisher request conflict, not a new acceptance.
11. **Simpler alternative.** A result-only JSON Artifact cannot expose one canonical
    reusable binary component without putting floats/binary in JSON or duplicating
    vectors. A second publication/registry would add identity and recovery work.
    One existing three-member file-set is the smallest boundary preserving both
    execution provenance and reusable component identity.

Pure tests use local temporary files and an injected fake publisher. They are
not evidence of production activation, actual CPU/CUDA inference, source
authorization, or a successful NAS/DB commit.
