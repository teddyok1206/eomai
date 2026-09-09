# PDF Learning Completion V1

Status: implementation contract. Production execution remains an explicit operator action and is
authorized only from an installed build whose commit, tree, archive hash, schemas, migration, and
application code were admitted together.

## Invariant

`COMPLETE` means an exact sorted bijection, not matching counters:

```text
50 pinned PDF inventory entries
  -> 108 original work units
  -> 520 unique (bundle revision, item number) keys
  -> 105 accepted original work units + exactly 3 authorized successor work units
  -> 520 accepting decisions from each key's own effective request/result/acceptance
  -> 520 unique promoted Item Revisions
  -> exactly one terminal ACCEPTED analysis leaf per Item Revision
  -> 520 unique placements in one pinned current Graph snapshot
```

All missing, conflicting, duplicate, extra, active, terminal-failure, pending, or slot-05/06 held
lease counts are zero. The three failed original extraction work units and any superseded analysis
attempts remain immutable history; they are not effective terminal leaves and must be explicitly
accounted for by lineage.

## Required design procedure

1. **Responsibility and boundary.** `LegacyItemCorpusCompletionService` is a Catalog application
   use case. It resolves already registered protocol artifacts and terminal batch rows, derives the
   exact coverage document at the cardinality defined by those pinned generic inputs, asks the
   orchestrator-owned Artifact publication boundary to commit
   one canonical Artifact, then invokes the existing `LegacyAssessmentRegistry`. A separate
   `PdfLearningCompletionService` reads Catalog state and commits a pointer-only end-to-end receipt.
   Workers never participate in either operation and never write to NAS.

2. **Canonical source.** The pinned original 108-work-unit batch manifest is the only authority for
   expected scope. Its pinned inventory and its PDF corpus bindings define the exact 50 PDFs. The
   recovery authorization defines the only replaceable original work units, and its pinned
   successor manifest defines the only permitted replacements. Database counters and a prior
   coverage row are observations, not scope authority.

3. **Logical entity and revision model.** Inventory ID/hash, batch ID/manifest hash, recovery
   hash, bundle logical ID/revision ID/manifest hash, acceptance ID/hash, Item ID/revision ID,
   analysis run ID, Graph ID/snapshot revision ID/hash, Artifact ID/revision ID/member hash, and
   installed-build admission commit/tree/archive hashes remain distinct immutable identities. A newly derived
   coverage has a content-derived logical ID and self-hash; replay does not create a new identity.

4. **Pointers and resolution checks.** Before use, resolve every member by exact Artifact ID,
   Artifact Revision ID, member path, schema ref/version, media type, member SHA-256, approved
   lifecycle, and access permission. Validate JSON Schema 2020-12, reject duplicate JSON keys,
   validate the Pydantic model and self-hash, then compare embedded identity/hash with the pointer.
   Never follow a mutable latest pointer. For every effective work unit, require the stored
   request/result/receipt/acceptance chain to equal its manifest request. For each item, require the
   acceptance decision to belong to that exact acceptance and expected item number. Dangling,
   stale, mixed-batch, or hash-drifted pointers fail explicitly.

5. **Primary access patterns.** The construction path performs indexed lookup by batch ID,
   Artifact Revision ID, acceptance ID, and bundle revision ID; ordered iteration by original
   ordinal and `(bundle revision ID, item number)`; membership/deduplication of expected keys; and
   immutable snapshot comparison. The end-to-end verifier resolves promotions by
   `(acceptance ID, proposal ID)`, analysis history by Item Revision, terminal leaves by predecessor
   adjacency, and current-Graph placement by `(snapshot revision, occurrence revision, item number)`.

6. **Data structures and indexes.** In memory, use dicts for ID resolution, sets for exact-set and
   uniqueness checks, tuples for canonical output, and adjacency counts for analysis leaves. This is
   O(n log n) time because of canonical sorting and O(n) space at n=520. Existing primary/unique
   keys and B-tree indexes cover batch/work-unit, Artifact Revision, acceptance decision,
   promotion registration, analysis source history/predecessor, Graph snapshot membership, and
   occurrence placement access. Two composite B-tree indexes bound the broad analysis-history
   alias lookup by source Artifact and accepted-result Artifact identity. A pointer-only
   observation table has one primary-key lookup by semantic completion hash; it stores the stable
   first-observation timestamp and fingerprint, never PDF, item, or result payloads.

7. **Scale and stability.** The durable Catalog service derives cardinalities from its pinned
   manifests and authorization and does not hardcode one release. Expected cardinalities are fixed
   only in the release-specific end-to-end receipt: 50 PDFs, 108 effective work units, and 520 item
   keys. Canonical order is bytewise identifier order, then
   numeric item number. Hash each immutable document once after canonical serialization. Do not
   persist large item, PDF, or Graph payloads in database rows or in the small publication receipt.

8. **Transaction and concurrency boundary.** Perform all database observations for an end-to-end
   receipt in one PostgreSQL read-only repeatable-read snapshot. Coverage preflight must complete
   before its Artifact side
   effect, and registry registration repeats pointer checks in its transaction. Artifact commit and
   registry insertion cannot be one database transaction, so deterministic idempotency makes an
   orphaned but valid Artifact recoverable by replay. After receipt commit, re-resolve the complete
   mutable fingerprint: all 50 PDF files, effective extraction and failed-lineage rows, promotion
   and analysis state, logical current pointers, Graph projections/current pointer, runtime mode,
   active work, and slot leases. Any change invalidates the attempt; regenerate from a fresh
   snapshot.

9. **Dependency direction and ownership.** JSON schemas and frozen Pydantic value objects live in
   `catalog_contracts`; domain contracts import no infrastructure. Catalog application services own
   orchestration, exact-set rules, transaction boundaries, idempotency, and stable errors. SQLAlchemy,
   PostgreSQL, filesystem materialization, NAS, and Artifact adapters remain in `catalog_service` or
   orchestrator infrastructure. A CLI may only validate a typed command, call the service, and
   render its receipt.

10. **Failure, retry, and idempotency.** Reject incomplete or nonterminal batches, unauthorized
    replacements, overlap, missing/extra/conflicting keys, wrong-origin acceptances, duplicate
    proposals/promotions/leaves/placements, stale current Graph, active/pending work, held slot-05/06
    leases, and all pointer/hash/schema drift with stable content-free codes. Derive the coverage
   ID and Artifact idempotency key from pinned immutable inputs. Persist the truthful first database
   snapshot observation timestamp under the semantic completion identity and reload it on replay.
   An identical replay returns the same Artifact Revision and registry row;
    the same logical/idempotency identity with different content is a conflict.

11. **Simpler alternative and why insufficient.** Reusing a prior `LegacyItemCorpusCoverage` or
    checking `expected_item_count == accepted_item_count == 520` is insufficient: V1 permits a
    smaller subset to call itself `COMPLETE`, does not require canonical ordering, and the registry
    currently checks that an acceptance/item-number pair exists without proving it originated from
    that bundle request. A standalone `/tmp` script is useful only as an offline verifier; making it
    authoritative would bypass the Catalog application and orchestrator commit boundaries. The
    smallest safe source change is therefore one deterministic coverage use case plus a separate
    end-to-end receipt verifier.

## Publication protocol

`legacy-item-corpus-completion-command/1.0` pins the original batch manifest, successor manifest,
recovery authorization, and inventory, and contains the authorized actor plus a command self-hash.
It does not accept caller-supplied counts, an arbitrary idempotency key, or coverage content.

The service returns `legacy-item-corpus-completion-receipt/1.0`. The receipt pins the command hash,
all source artifacts, the newly committed coverage Artifact, the expected-key hash,
acceptance-map hash, and counts derived from those sources. The generic Catalog
contract contains no literal 50/108/520 rule. The full
520-key acceptance map remains canonical in the coverage Artifact rather than being copied into the
small receipt.

The separate `eom-pdf-learning-completion/1.0` receipt is generated only after promotion, analysis,
and Graph verification. Nine deterministic, separately published shards contain the 520 pointer
chains; the small receipt pins their exact member hashes and boundaries. These documents contain no
item bodies, PDF bytes, model prompts, or model results.
Its source-release identity is supplied by installed, hash-pinned build metadata through a release
admission interface. Neither verifier imports from a repository checkout nor invokes Git at runtime.

## Construction algorithm

1. Resolve command pointers and validate exact identity, contract, media type, hashes, and approval.
2. Derive both terminal distributions and require that the successor exactly covers all and only
   authorization replacements; the release-specific verifier separately requires 108/105/3 and
   3/3/0.
3. Index original work units by ID/ordinal and recovery replacements by predecessor ID; require the
   exact partition 105 originals plus three authorized successors.
4. Flatten original expected keys into a set and reject overlap. The generic coverage service uses
   the derived cardinality; the release verifier requires exactly 520.
5. Resolve each effective row and its request/result/receipt/acceptance evidence; require exact
   pointer equality to its originating manifest request and an accepting decision for every and
   only expected number.
6. Derive sorted PDF inventory sources from original manifest corpus bindings and require their
   bundle-revision union to equal the expected scope. The release verifier requires exactly 50.
7. Group accepted mappings by bundle revision, sort bundles and item numbers, create the immutable
   coverage, validate schema/model/self-hash, commit once, and register once.
8. In a stable read snapshot, resolve each coverage key through promotion, a unique terminal
   ACCEPTED analysis leaf with pinned request/result policy pointers, and a unique current-Graph
   placement. Compare actual and expected sets in both directions.
9. Validate quiescence and lease-zero conditions, build and validate the completion receipt, commit
   once, recheck the full mutable fingerprint, and only then report exact completion.

## Operator runbook

Run both commands only from the admitted installed package and an explicit Conda environment. The
root configuration is untrusted input and is schema/ownership validated before any PDF is opened.
Neither command accepts caller-supplied source-release hashes; they come only from packaged build
metadata.

```text
eomctl legacy-assessment extraction-batch complete-corpus \
  --command-file /absolute/path/corpus-completion-command.json

eomctl legacy-assessment learning complete-pdf \
  --corpus-completion-receipt-file /absolute/path/corpus-completion-receipt.json \
  --root-config-file /absolute/path/legacy-source-roots.json \
  --graph-snapshot-revision-id graphrev_<32hex> \
  --graph-snapshot-sha256 sha256:<64hex>
```

Success returns the immutable coverage receipt or, for `complete-pdf`, the completion identity,
small completion-receipt Artifact pointer, and typed receipt. Any nonzero residual, source/runtime
change, pointer/hash drift, or publication conflict fails closed. A retry with unchanged evidence
reuses the persisted first observation and the same semantic Artifact identities.

## Required tests

- valid exact 50/108/520 derivation and deterministic replay;
- one missing expected key and one extra key;
- duplicate key within/across work units and duplicate decision/proposal/promotion/leaf/placement;
- unauthorized mixed batch or unlisted recovery successor;
- acceptance from the wrong request/bundle despite a matching item number;
- stale/missing/unapproved Artifact target, schema/media-type mismatch, and every hash/pointer drift;
- incomplete/active/failed effective rows, subset marked `COMPLETE`, and nonzero quiescence/leases;
- Graph-current pointer drift during and after the receipt snapshot;
- canonical ordering and serialization are deterministic under input permutations;
- concurrent/replayed publication returns one logical coverage/artifact/registry identity;
- database persistence contains only pointers/metadata and no PDF, item, or result binary payload.
