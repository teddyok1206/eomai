# Map: published Graph exploration

2026-11-05 UTC. User request: move `교육 지식 맵` to Data as `Map`,
and provide read-only, Obsidian-like exploration. The previous screen shows
analysis coverage, not published Graph nodes; retain it as a learning diagnostic.

## Boundary and invariants

1. **Responsibility:** Catalog owns bounded reads of its existing published node,
   edge and provenance tables. Application API authenticates the actual operator;
   Web only presents that read model. No worker, retrieval job, model, GPU, graph
   publication, write, editing or approval is triggered by Map.
2. **Canonical source:** existing published KnowledgeGraphSnapshot and its
   approved manifest, not a second graph or vectors. Labels are index metadata,
   not quotations or a claim that original PDF pixels were inspected.
3. **Identity:** initial open resolves the active corpus once; expansion/search
   retains that immutable graph revision and snapshot SHA. A refresh explicitly
   starts a new view. Missing, unpublished or mismatched pins fail explicitly.
4. **Pointers:** use Catalog's existing public snapshot resolver. Provenance
   includes exact accepted analysis, source revision, artifact revision, source
   and excerpt hashes. Detail resolution checks matching snapshot analysis,
   approved artifact identity and lifecycle; unavailable sources are marked, not
   replaced. `available` means this metadata association remains available, not
   that Map has read/rehash-verified the file bytes. Actual Item content/media
   reads still perform their existing complete schema/media/hash/permission
   resolution; metadata does not authorize raw Artifact or NAS reads.
5. **Access:** preserve the old administrator-only exposure, require actual
   `knowledge_graph:read`, `knowledge_analysis:read`, `item:read` and
   `content_intake:read`. This is an administrator index viewer, **not** the
   released worker RAG query policy, and grants no worker retrieval authority.
6. **Access patterns:** snapshot PK lookup; node type/lexical term lookup;
   indexed incoming/outgoing adjacency; bounded provenance join. Reuse existing
   indexes, map/set deduplication, stable ID order; no persistent derived cache.
7. **Scale:** at most 120 nodes, 240 edges and 20 source references per response;
   one-hop expansion. Return explicit truncation. Frontend bounds its visible
   subgraph too. Work/memory is proportional to the bounded neighborhood, not
   total corpus size; no all-graph download or N+1 provenance queries.
8. **Concurrency:** one read-only repeatable-read transaction; no DB schema,
   migrations, claims, queues or data mutation. Existing creative registration
   and GPU INDEX/QUERY processes and their pinned installations remain running.
9. **Dependencies:** Web → API → Catalog read application → existing tables and
   snapshot resolver. The lower Catalog layer does not import API/Web. Vanilla
   SVG is sufficient; no new dependency or generic visualization framework.
10. **Failure/replay:** all reads are side-effect-free. Stale response/selection
    is discarded on navigation, refresh or account change. A failed expansion
    keeps the previous valid view. Old analysis-quality contracts stay intact.
11. **Simpler alternative:** relabeling the coverage screen would falsely imply
    Graph browsing; an all-graph JSON dump would be unbounded. Use bounded
    neighborhoods and the existing DB detail/assembly/similarity functionality.

## Presentation

- Data navigation: DB, Map, Learning, Operations data.
- Search concepts, select a node, inspect its type and sources in the right pane,
  expand its one-hop neighborhood; select an edge for relation/provenance.
- Textbook / past exam / creative / AI are source layers. A shared concept can
  have multiple layers; do not clone it into disconnected layer-specific nodes.
  `INTERNAL_EOM` origin means AI; imported external Items mean creative, not
  "approved". Historical Items without origin profiles use their exact existing
  `external-item-learning` / `generic-item-development` registration families;
  unknown families remain UNKNOWN. Curriculum/guide nodes remain distinguishable.
- Drag/pan/zoom are display state only. Layout distance is not similarity.
- Item opening is a **new authorized DB read**, keeping the exact Item revision
  and manifest. The DB resolves its current graph context explicitly for assembly;
  it never substitutes a newer Item revision or mutates the Map's frozen view.
- Show source revision/anchor/hash in technical details. Do not invent page
  locators, a PDF URL or an original-file viewer where no supported read contract
  exists. Item preview uses the existing authorized preview path.

## Acceptance

Schema/Pydantic parity; pin and permission negatives; missing/revoked source;
bounded indexed adjacency and deterministic results; no mutation/model calls;
rapid selection/account changes; browser node/edge inspection and DB handoff.
Deploy API/Web as a compatible set, keeping background process IDs and pins.

## 2026-11-06: source layers across the pinned Graph

The old dropdown only hides already loaded nodes. Selecting a layer that is not
in the current bounded neighborhood can incorrectly look like an empty DB.
Keep the existing published Graph and Map V2 response; add one optional `layer`
query parameter using the existing closed `MapLayerV2` enum in API/BFF OpenAPI
(JSON Schema 2020-12). No new response version, worker protocol or DB migration.

- **Owner/canonical identity:** the same Catalog read use case and exact published
  snapshot/hash remain authoritative. Registry-only files not yet in this Graph
  are not invented as nodes. Source kind and approval remain separate.
- **Pointers/checks:** preserve snapshot resolution, permission checks, source
  availability, node/edge identity and exact Item handoff. Changing a layer or
  lexical search retains the current pin; only explicit refresh resolves current.
- **Access/structures:** use snapshot/source-class/node indexes and the existing
  origin/Workflow PK joins to select matching node IDs before the seed limit.
  Use one ordered immutable classification rule table for Python presentation and
  SQL predicate generation, so imported, material and AI categories cannot drift.
- **Bounds/scale:** filtered lexical terms intersect layer membership in SQL;
  unfiltered opening samples at most two seeds per primary source layer plus ten
  curriculum seeds. There are at most twenty seeds,120 nodes,240 edges,20 source
  pointers; adjacency and client maps/sets retain their existing bounds. Work is
  indexed snapshot-local membership/term selection, not an all-Graph JSON load.
  Check the actual plan/timing before introducing any index or persistent cache.
  DB membership work scales with matching snapshot-local provenance rows (and
  distinct/sort work); a small response is not a promise of constant query cost.
  Visible adjacency/layout stays O(V+E) with the fixed node/edge bounds.
- **Transaction/concurrency:** the same read-only repeatable-read transaction and
  finite statement timeout; no claim, publication, write or model/GPU invocation.
  Existing creative recovery/registration and frozen INDEX keep their own owners.
- **Dependency/failure:** Web → authenticated API → existing Catalog application.
  Missing/stale pins and invalid layers remain explicit. A failed layer load keeps
  the last valid drawing; account changes and late responses cannot replace it.
- **UI:** the five real source categories remain visible, with clickable color
  labels synchronized to the selector. Multi-layer concepts have multiple color
  markers, not cloned independent nodes. Sources/DB opening keep exact references.
- **Simpler alternative:** client-only filtering does not search the Graph; adding
  another Graph, full download, new cache or vector lookup is unnecessary. Reuse
  the existing DTO and one additive query instead.

Acceptance: API/BFF enum and pin propagation; SQL/Python classification parity;
layer match before LIMIT; absent/unknown layers; bounded mixed seeds; real
disposable-DB reads/query plans; browser switching/late replies/account reset;
installed API/Web/provider alignment. No future textbook layout or educational
quality guarantee is implied by a metadata map.

## Local cleanup

The user clarified **no NAS relocation**. Remove only recoverable obsolete
build/temporary copies, with a frozen plan and per-target active-reference and
identity checks. Never delete DB fields, Item metadata, running environments,
models, canonical vectors, uploads or protected rollback inputs.

2026-11-05 first pass: 68 disposable source/Web copies, 4,469,813,248 bytes freed;
source archives/wheels retained; no restart. Four creative slot leases resumed
without intervention after the local-storage reserve became available.

Second pass: 621 old `source.tar` build inputs (26,271,836,160 bytes). For each,
the retained API wheel identifies the exact commit, tree and archive hash;
`git archive --format=tar <commit>` reproduced the exact SHA-256. Revalidated
file identity/hash and all live process references before unlinking only those
files. Active/recent commits, every wheel and all installed prefixes remain.
Recovery commands/hashes are in the cleanup manifest. No NAS relocation or DB
change. Combined recovery: 30,741,649,408 bytes (about 28.6 GiB).

Final reachability reconciliation restored 14 reflog-only source archives
(311,429,120 bytes); net removal is 30,430,220,288 bytes (about 28.3 GiB).
The remaining removed archives' commits are reachable from retained Git refs.

Deployment discovery: API/Web-only restart is not independently supported by the
existing API-provider identity pins and systemd QUERY dependency. Use the existing
compatible release-set rollout, allow creative workers to finish naturally, then
resume the producer. Do not detach dependencies/weaken source verification to
make the additive Map endpoint deploy independently. Frozen INDEX/GPU pins and
processes are preserved; no new runtime framework or migration is introduced.
