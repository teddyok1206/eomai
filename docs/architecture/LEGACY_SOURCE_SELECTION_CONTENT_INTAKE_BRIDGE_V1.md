# Legacy Source Selection to Content Intake Bridge V1

Status: Phase 3 implementation design; source and synthetic tests only until reviewed rights
evidence is available.

## 1. Responsibility and boundary

The bridge converts one human-reviewed `legacy-source-selection/2.0` into exactly one existing
Content Intake batch. It validates identity and rights, temporarily materializes only selected
originals, and invokes `IntakeService`. It does not analyze content, publish a graph, allocate a
Curriculum Framework Revision, or let a worker read a legacy root directly.

The selected curriculum PDF remains one whole canonical source. The Integrated Science page scope
and the fixed [EOM editorial outline](EOM_INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_V1.md) belong to the
later analysis/mapping request; they do not create a second source identity.

## 2. Canonical source and revisions

- Canonical pre-intake identity: exact inventory ID/hash, entry key, and content SHA-256.
- Canonical post-intake bytes: the immutable Content Intake source Artifact Revision.
- Reviewed decision: immutable selection document and its selection hash.
- Rights authority: pinned V2 rights-review Artifact member, its exact inventory-entry pointer, and
  its self-hashed revision payload.
- Workspace copies: disposable materializations only; never identities or PostgreSQL payloads.

The bridge records the validated selection as a small Artifact after Content Intake succeeds. That
Artifact result points to the intake batch; the batch purpose also carries the selection identity.
Retries use the same hashes and return the same Content Intake and selection Artifact revisions.

## 3. Required pointers and resolution checks

The bridge fails closed unless:

1. V2 selection and inventory pass their canonical JSON Schemas and Pydantic invariants;
2. selection inventory ID/hash exactly match the supplied inventory;
3. inventory root alias and root-configuration identity match protected configuration;
4. every selected entry exists exactly once, is a regular original candidate, has the reviewed
   family, and matches the selected content hash;
5. every comparison entry exists as derived migration evidence and matches its hash; comparison
   bytes are never staged as source;
6. every V2 rights-review pointer resolves to one approved immutable Artifact member with matching
   schema, media type, hash, inventory ID/hash, entry key, and content hash;
7. rights payload owner, document type, state, internal-processing permission, and self-hash match
   the selection;
8. every legacy source path is opened component-by-component with `O_NOFOLLOW`, is a single-link
   regular file, remains unchanged while read, and rehashes to the inventory value;
9. the disposable output is a new regular file with mode `0600`, exact byte count, and exact hash;
10. Content Intake rediscovery sees the exact expected staged set.

Model exposure and item grounding are not implied by successful intake. Knowledge Analysis must
later require `DATA_ANALYST_WORKER` in the same pinned rights review, and item production must
separately require `allowed_item_grounding=true`.

## 4. Access patterns and data structures

Dominant operations are exact entry lookup, duplicate detection, deterministic iteration, and
idempotent replay. Inventory entries are indexed once in a map by `entry_key` for expected O(1)
lookup. Selected and comparison keys are sets for overlap/uniqueness checks. The already sorted
selection tuple controls deterministic staging order. Source bytes are streamed in bounded chunks,
so auxiliary memory is O(number of selected entries), not O(total source bytes).

Initial scale is one curriculum PDF, one textbook/reference PDF per batch, or at most ten item-source
files. The contract permits more entries, but the existing Content Intake caps remain authoritative:
500 files, 100 MiB per file, and 2 GiB per batch.

All selected sources in one bridge invocation must share one source owner and intended corpus key.
Mixed ownership/corpus selections fail before side effects and must be split into separate reviewed
selections. This keeps one transactional/intake meaning per batch and avoids partial multi-batch
commits.

## 5. Transaction, concurrency, and idempotency

The existing Content Intake fingerprint and unique constraint are the concurrent-claim boundary.
The bridge uses deterministic staged member names derived from inventory entry keys, so exact replay
produces the same fingerprint. When a matching batch exists, its owner, purpose, filenames, roles,
media types, hashes, and descriptions must all match; semantic conflict fails as immutable rather
than silently reusing unrelated metadata.

Artifact and NAS commit remain owned by the Catalog application service. There is no distributed
transaction across filesystem and PostgreSQL, so replay is the recovery mechanism: the source
Artifact commit is already idempotent, and the small selection Artifact commit follows only after
the Content Intake batch reaches `ANALYSIS_PENDING`. No automatic worker execution follows.

## 6. Dependency direction

```text
eomctl (operator interface)
  -> LegacySourceSelectionService (application use case)
      -> rights-review resolver (Catalog Artifact adapter)
      -> fd-relative legacy source adapter
      -> Content Intake application boundary
      -> selection Artifact adapter
```

Contracts do not import Catalog infrastructure. The CLI supplies protected paths and confirmation
hashes, calls the service, and emits bounded identifiers only. The bridge does not implement Content
Intake persistence or NAS commit itself.

## 7. Failure and rollback behavior

Stable legacy knowledge codes distinguish stale inventory/pointers, invalid class/rights/media,
changed files, unsafe paths, capacity, and output failure. Error messages never contain absolute
legacy paths or source content. Validation and fd-safe materialization complete before Content
Intake mutation. If any validation fails, no Content Intake or Artifact call occurs.

A failed Content Intake call leaves its own evidence under its existing lifecycle rules and is not
retried automatically. A selection Artifact failure after successful intake is replayable using the
same selection hash; it does not duplicate source bytes. Disposable staging is removed on both
success and failure.

## 8. Simpler alternative rejected

Copying a filename directly into Content Intake is insufficient. It loses the inventory revision,
reviewed class, rights pointer, owner/corpus semantics, and proof that the bytes did not change
between inventory and commit. Passing the derived JSON beside the PDF is also incorrect because it
would make comparison output appear canonical. The typed selection and exact-hash bridge are the
smallest existing-contract solution that preserves provenance.

## 9. Current execution gate

Implementation and synthetic tests may proceed. A real selection/intake must remain blocked until a
human supplies and approves source owner/licensor evidence, internal-processing and worker-exposure
rights, materialization/grounding permissions, retention/withdrawal policy, and Framework authority.
No live worker or Knowledge Analysis execution is part of this phase.
