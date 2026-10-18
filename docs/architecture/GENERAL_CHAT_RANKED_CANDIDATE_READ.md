# Catalog-ranked Chat candidate metadata

Design before protocol/behavior, 2026-10-18 UTC. C4 prerequisite, not activation.

1. Responsibility: extend the existing Catalog Chat read boundary to filter up
   to64 ordered native candidate keys through the same Registry/Graph metadata
   owner as ordinary discovery. No new search engine, worker tool or authority.
2. Canonical state: current Item/revision/approval, exact component association,
   published Graph and released access-policy revision. Native ranking is only
   an offered candidate order, not permission, evidence, approval or correctness.
3. Input keys carry Item identity, source class and exact analyzed component's
   Artifact/revision/SHA relation. These are metadata join keys, **not file-read
   pointers**: no path, staged file, arbitrary schema or bytes are dereferenced.
   Output carries the distinct canonical Item manifest SHA from the Registry.
4. Closed schema2020-12/Pydantic and request hash bind actual actor, exact semantic
   Graph/policy scope, TOPIC/source selectors and ordered unique keys. Reuse RAG
   actor/policy/snapshot checks in the same repeatable-read/read-only transaction.
   Check exact active Item/component/Graph relations before title projection;
   only current approved revisions may become discovery cards.
   Native/query/report/Artifact byte authority and later materialization remain
   their existing owners' responsibility, not a grant made by this metadata read.
5. Dominant access: at most64 indexed revision/component/Graph joins; map/set
   membership and stable native order; existing indexed term/source filtering.
6. Reuse existing discovery SQL and card projection. Extend it with a typed
   optional ordered pool, never rerank just the legacy six cards. No migration,
   index, queue, cache, generic callback framework or dependency additions.
7. O(K indexed lookups + matched rows), K<=64, fixed query count, O(K) metadata;
   no per-candidate query loop, corpus scan, original text/report or vector I/O.
   Existing B-tree indexes cover revision, component revision, Graph source and
   Graph term lookups. Test compiled SQL and guarded query plans where available.
8. One existing Catalog read transaction owns role/policy, current relations,
   term/source selection and presentation. No Job, claim, NAS write or model run.
9. Contract stays in Catalog contracts. Existing RAG owner composes the existing
   discovery adapter's public in-session read; Unix handler/client remain adapters.
   Extract shared projection functions instead of reaching into private modules
   or copying discovery business rules. Keep ordinary search behavior unchanged.
10. Missing/revoked/wrong Item-component/hash/Graph relation fails without partial
    titles/counts; do not silently choose latest or repair. A valid candidate not
    matching the requested TOPIC/source is filtered normally before LIMIT. Retry
    is caller-controlled; no automatic transport replay, role override or login.
11. Eleven batches of existing six-card reads would create N+1 work and apply
    different snapshots/limits. Copying the discovery query would drift. One
    bounded pool through the same owner/query/presenter is the simpler boundary.

RECENT/EXAM are not admitted by this operation. Returned native cards must be
approved and Graph-indexed; pending legacy discovery cards remain a separate
ordinary channel. Stable order is native rank, with at most one card per Item
revision (choose the first deterministic placement); output max6. Current/source/
term filters occur before top-K. All64 inputs must retain valid exact metadata
relations. A valid immutable historical approved/superseded revision is not a
dangling pointer merely because current advanced: filter it out of TOPIC results
without substituting its successor. Retired/revoked/missing/wrong-hash relations
fail explicitly, even outside the selected topic. Do not turn those into EMPTY.

This is filtering the native **global top64**, not computing exact filtered
top-K. Preserve the companion's explicit limitation. Native QUERY still searches
the full authorized bounded population, independently of a Graph/lexical top64.
The future broker derives the real actor/origin from its live ticket, reauthorizes
native public/report/source pins through their supported owner, merges the
authorized native and ordinary channels, and commits the existing provenance.
This contract alone neither does that nor proves end-to-end Chat delivery.
