# Incremental embedding index Artifact publication owner

2026-10-12 UTC. Main-agent-approved source-only publication leaf; NOT_INSTALLED / NOT_ACTIVE.
This closes the missing Orchestrator publication leaf; it does not authorize a source,
advance Catalog's index head, launch an encoder or activate an installed runtime.

1. **Responsibility/boundary:** extend the existing
   `services/orchestrator/eom_orchestrator/embedding_artifact_store.py` with one
   `EmbeddingArtifactStore.publish_index()` operation. It uses the existing
   `ControlFileSetPublisher`, not a second publisher, queue, scheduler or registry.
   The owner fixes sole member/primary `index.json`, artifact type
   `control_embedding_index`, manifest version `control-file-set/1.0` and the
   existing `embedding-index-manifest/1.0` schema/media contract. Export those fixed
   constants so the later official reader does not guess new owner semantics.
2. **Canonical source:** the owner-built, fully validated index manifest is the
   bounded metadata source. Its exact committed shard and predecessor pointers
   retain their own canonical components. Publish no vectors, model weights,
   source/report/profile bytes or duplicate shard manifests. The one local
   canonical `index.json` is materialized only at this protected commit boundary.
3. **Identity/revision:** preserve logical index ID, immutable index revision ID,
   semantic `index_sha256`, raw canonical member SHA, publication Artifact/revision
   IDs and the outer manifest SHA separately. The publisher's owner Job is neither
   an encoder Job nor the logical index ID. Return a frozen pointer-only
   `PublishedEmbeddingIndexArtifacts` containing owner Job, index ID/revision,
   exact index member pointer, semantic index SHA and outer manifest SHA.
4. **Pointers/resolution:** reparse the existing schema and use
   `validate_embedding_index_references()` for exact unique shard pointer/hash,
   ordered row/encoding/space/partition closure and exact predecessor namespace.
   A small frozen in-process `EmbeddingIndexPublicationScope` pins expected Graph
   snapshot and access-policy revision/hash; every binding must match it. It is
   metadata context, not permission or an "already validated" switch. Actual
   source/report/profile/evidence resolution and
   `validate_embedding_source_bindings()` stay with the official Catalog caller;
   do not move full staged source material through this leaf or duplicate that
   semantic rule. Current permission/lifecycle is reauthorized before publication
   and independently checked again by the official registration verifier before
   the metadata transaction. DTO possession, FK presence and an approved control
   Artifact never establish approved Item/source authority.
5. **Access patterns:** one fixed local name lookup/create, bounded canonical
   serialization/read/hash, map/set pointer uniqueness, ordered immutable binding
   closure and same-identity publication replay. No implicit current/latest lookup
   occurs here. At most the existing 1,024 bindings/shards and 64 MiB metadata limit
   apply; the published file set has exactly one member.
6. **Structures/indexes:** use the existing frozen contracts and tuples; retain
   bounded pointer maps/sets in the public pure validator. Existing publication
   Job idempotency records own persistence. No new DB table/index, mutable cache,
   authority DTO or generic callback framework is needed.
7. **Complexity/scale:** O(index metadata bytes + bindings + total referenced shard
   rows), plus existing deterministic ordering/schema-validation cost. O(bounded
   metadata) temporary memory; numerical vector bytes are never read or copied by
   this index-only operation. The independent committed-artifact reader validates
   each canonical vector component when registration requires that proof.
8. **Transaction/concurrency:** reuse protected mode-0700 own-UID local directory,
   held no-follow ancestor/member FDs and mode-0600 regular single-link files.
   Create `index.json` with O_EXCL once, fsync and read it back through the held-FD
   boundary; an existing member must equal exact canonical bytes. Retain/revalidate
   FD/named metadata epochs across the publisher call. The existing publisher
   owns same-key lock, staged raw hashes, immutable request comparison, interrupted
   commit recovery and completion transaction. Artifact publication and Catalog
   registration remain separate transactions, never a claimed atomic cross-service
   operation.
9. **Dependency direction/ownership:** Orchestrator infrastructure depends only on
   public catalog/protocol contracts and the existing Orchestrator publisher. The
   caller supplies exact resolved metadata; no Catalog implementation/private
   repository import or source-reader service bypass is introduced. Workers still
   emit only local native result/binary and cannot choose NAS, index identity,
   publication paths or publication authority. Installed source commit is an
   explicit constructor pin, not a runtime Git query. No new dependency is needed.
10. **Failure/retry/idempotency:** use a fixed publication identity derived from
    `(index_id, index_revision_id)`; bind exact raw member SHA/size/schema, semantic
    index intent (inside those exact canonical bytes), source commit and original
    index UTC timestamp in the publisher's immutable request. A changed raw or
    semantic payload for the same index revision must conflict under the same key,
    not hash itself into a second publication identity. Replay uses the original
    index bytes/pins/time/source commit and returns the same Artifact pointer,
    without re-encoding or resolving latest. Missing/foreign/revoked references,
    partial/conflicting local files, schema/hash/epoch drift and malformed receipts
    are explicit redacted failures. A post-publication failure is not proof that
    nothing committed; preserve partial evidence and reconcile exact pointers.
11. **Simpler alternative:** calling the generic publisher directly would leave
    index closure, immutable identity/key and receipt checks to each caller. A new
    index publisher duplicates the already tested commit/recovery machinery. The
    smallest safe change is one index-only method and typed receipt on the existing
    artifact store, with a small fixed-name materialization extension.

## Approved implementation scope

The implementation extends the existing artifact store and adds
`tests/unit/test_embedding_index_artifact_store.py` and an opt-in disposable
`tests/integration/test_embedding_index_artifact_persistence.py`. Reuse existing
result/shard publication behavior unchanged; generalize only its fixed-name
metadata materialization/read helper enough to admit the sole index member.
The input signature is the exact index, resolved shard metadata tuple, optional
exact predecessor tuple, expected Graph/policy scope and owner local workspace.
No worker-selected path, arbitrary artifact type or new wire schema is accepted.

Source tests cover sole member/schema/type, separate IDs/raw/semantic hashes,
same-key replay, changed intent conflict, predecessor/shard/source-policy mismatch,
bounded/canonical input, symlink/hardlink/mode/owner/inode/metadata drift, preexisting
partial/conflicting file, malformed receipt, FD lifetime and publisher failure
before/after a simulated commit. They assert no model/Git/NAS/DB/source-read or
automatic re-encode call. Prepared integration tests use the existing disposable
database guard and temporary artifact root for actual owner Job/Artifact metadata,
independent-process same-key contention and exact recovery; they are not run in
this source-only task. No existing Catalog application, proof, image release file
or operational runtime is edited or activated by this leaf. The historical native-result test's
closed import whitelist admits only the new public Graph-pointer contract import; all its
behavior assertions remain unchanged.

## Source gate

The index/store/publisher/embedding-contract focused source gate passed 201 tests. Ruff formatting
and lint plus strict mypy passed for the store and three owned test files. Three prepared integration
tests collected successfully, but no DB fixture, SQL connection or artifact publication was executed
in this task. Passing fake-publisher tests is not actual source authorization, a live DB/NAS commit,
installed release readiness or activation.

```sh
PYTHONPATH=packages/protocol:packages/identifiers:packages/catalog_contracts:packages/workflow:services/orchestrator /srv/eom/conda/envs/eom-api/bin/python -m pytest -q tests/unit/test_embedding_artifact_store.py tests/unit/test_embedding_index_artifact_store.py tests/unit/test_control_file_set_publication.py tests/unit/test_inference_transfer_embedding_contracts.py
/srv/eom/conda/envs/eom-api/bin/ruff format --check services/orchestrator/eom_orchestrator/embedding_artifact_store.py tests/unit/test_embedding_artifact_store.py tests/unit/test_embedding_index_artifact_store.py tests/integration/test_embedding_index_artifact_persistence.py
/srv/eom/conda/envs/eom-api/bin/ruff check services/orchestrator/eom_orchestrator/embedding_artifact_store.py tests/unit/test_embedding_artifact_store.py tests/unit/test_embedding_index_artifact_store.py tests/integration/test_embedding_index_artifact_persistence.py
/srv/eom/conda/envs/eom-core/bin/python -m mypy --strict --follow-imports=silent services/orchestrator/eom_orchestrator/embedding_artifact_store.py tests/unit/test_embedding_artifact_store.py tests/unit/test_embedding_index_artifact_store.py tests/integration/test_embedding_index_artifact_persistence.py
PYTHONPATH=packages/protocol:packages/identifiers:packages/catalog_contracts:packages/workflow:services/orchestrator /srv/eom/conda/envs/eom-api/bin/python -m pytest --collect-only -q tests/integration/test_embedding_index_artifact_persistence.py
```
