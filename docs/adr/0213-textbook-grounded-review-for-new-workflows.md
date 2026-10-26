# ADR 0213: Mandatory textbook evidence for new review workflows

Status: implementation in progress, 2026-10-26 UTC. The shared
`review-textbook-evidence/1.0` contract and a Catalog-only one/two-document
publication boundary exist in source. The single-document `workflow-role/1.31.0`
input/result schemas and typed models now bind textbook usage to science and
curriculum conclusions. The pure validator can reopen the exact Catalog
manifest and reject foreign sources, anchors, request identities and blank
conclusions. No review Workflow selects that successor yet; the orchestrator
has not connected the validator to its commit boundary. This decision does
**not** activate a new review path or reinterpret historical reviews.
The Orchestrator explicitly refuses a V5 result before artifact commit until
that trusted receipt is installed; schema registration alone is not activation.

## Decision and boundary

Every **new** scientific review invocation—generated Item review, single-file
material review, and paired question/solution material review—must attempt an
authorized, topic-relevant `TEXTBOOK` Graph retrieval before a worker may issue
a scientific verdict. Past-exam and approved-Item references may supplement it;
they cannot substitute for it. A prompt sentence or a policy that merely allows
`TEXTBOOK` does not satisfy this requirement. The orchestrator must stage a
validated textbook source and bind its immutable Graph, policy, analysis, member,
anchor and content hashes to the particular review request and result. If no
authorized relevant textbook source can be resolved, that invocation cannot
claim a completed, textbook-checked review. It returns an explicit unavailable
or insufficient-evidence outcome; it never fabricates textbook support or falls
back to model memory.

The currently released single-document `workflow-role/1.28.0` has **no Graph
evidence**. The paired `1.27.0` can receive a mixed Evidence Bundle, but its
policy permits `TEXTBOOK` without proving that a textbook source was selected.
The standard Item review's `graph_grounded` path requires accepted solution
evidence, while `general_model_knowledge` can review without Graph context.
All three therefore need successor contracts; changing only role prose would
leave the guarantee false. Preserve every released request, prompt, result,
receipt, execution pin and historical status unchanged.

## Required design procedure

1. **Responsibility:** Catalog resolves source relevance, permission and
   immutable bytes through its existing retrieval application. Orchestrator
   selects the released successor, materializes only checked evidence, validates
   the worker result and commits the receipt. Workers neither query Catalog nor
   choose their own authority.
2. **Canonical source:** the active published Education Graph, released access
   policy, accepted textbook analysis and original source anchor. A worker's
   summary or an unverified PDF quote is not canonical textbook evidence.
3. **Entity/revision model:** one review request pins its input Item Revision or
   document revision(s), one or more Evidence Bundle revisions, Graph revision,
   policy revision and result Artifact revision. Old and successor families remain
   separately readable.
4. **Pointers/resolution:** validate logical/revision identity, source class
   `TEXTBOOK`, lifecycle, role permission, schema/media, accepted-analysis status,
   source/page anchor and SHA-256 at planning, staging, result admission and
   replay. Never silently retarget to the current Graph after a request starts.
5. **Access patterns:** keyed Item/document revision lookup; bounded document
   term→topic lookup for material review; indexed curriculum/topic lookup for
   Item review; bounded Graph traversal; immutable evidence/member resolution.
6. **Structures/indexes:** reuse existing keyed Catalog lookups, term and Graph
   indexes, unique idempotency keys and typed manifests. Use sets for distinct
   source/citation IDs and maps for exact result-pointer resolution. Do not add a
   second vector search or duplicate textbook content in DB.
7. **Scale:** bound terms, topics, source count and context by the released
   policy. Planning is indexed plus bounded ranking; citation validation is
   linear in the bounded result. Avoid a whole-book prompt dump or per-finding
   full-corpus scan.
8. **Concurrency/transaction:** Catalog publication uses its existing
   idempotent Evidence Bundle transaction; Workflow creation follows successful
   evidence planning. Orchestrator owns one result commit and receipt. A timeout
   is reconciled with the same key, not a second review request.
9. **Dependency direction:** successor JSON Schema 2020-12 → frozen typed
   contracts → Catalog/Workflow application use cases → existing adapters.
   UI receives only the projected source class, location and honest limitation.
10. **Failure/retry:** no textbook match, revoked source, stale policy, hash or
    permission mismatch, scanned PDF with no extractable topic, and uncertain
    transport are distinct fail-closed outcomes. Do not translate them into
    `VERIFIED`, use a past exam as a stand-in, or mark an old failure successful.
11. **Simpler alternative:** merely adding `TEXTBOOK` to `source_classes` or
    appending a prompt instruction is insufficient: ranked retrieval may return
    zero textbooks, and old result schemas cannot prove which textbook the
    reviewer actually saw or cited.

## Successor shape and rollout

Define schemas before worker behavior. Use a shared small, immutable
`RequiredTextbookEvidence` value in successor Item and material-review plans:
the exact input revision(s), one Catalog-produced retrieval publication,
the nonempty validated `TEXTBOOK` source/analysis/anchor set, and a self-hash.
For paired material review, keep optional past-exam/approved-Item evidence as a
separate pinned supplement. Do not retain the predecessor's mandatory
past-exam solution-report requirement when no past-exam source was requested;
without it, originality or source-comparison axes may be `INSUFFICIENT`, not
silently `VERIFIED`.

Use the existing document-to-Graph lexical scope planner from ADR 0111 for one
or two PDF-projected input documents. Generalize its successor contract to a
bounded ordered document tuple instead of forging a second `SOLUTION` document
for single-file review. Use the Item's selected curriculum/topic identity for
Item review. Unlike uploaded documents, the Item under review is produced
**inside** the Workflow. Its textbook lookup therefore belongs after the
authoring Artifact Revision is admitted and before the review step is claimed;
the API cannot honestly pre-pin evidence for an Item that does not exist yet.
An orchestrator-owned checkpoint must record this new evidence decision under
the same Workflow identity and idempotency key. Both paths request `TEXTBOOK`
explicitly, then validate that the
published manifest actually contains at least one relevant authorized textbook
source. A mixed-source request alone is not evidence of this condition.

New worker-result successors must record textbook evidence usage against exact
scalar conclusion paths and expose `INSUFFICIENT` when the supplied textbook
does not support a claim. A citation on an `INSUFFICIENT` conclusion means the
textbook entry was examined, **not** that it supports the rejected claim. The
trusted receipt reopens the pinned manifest and
checks cited source IDs, page/Graph anchors, result paths and source class before
commit. It proves evidence linkage, not scientific truth. A reviewer remains
responsible for correctness and educational value.

The shared usage value is a small, self-hashed list of textbook evidence IDs,
source anchors and scalar conclusion JSON Pointers, bound to the exact
`ReviewTextbookEvidence.binding_sha256`. Its contract can reject unknown IDs,
non-grounding entries and anchors not present in the reopened manifest. The
result-specific receipt must additionally resolve every JSON Pointer against
the actual successor output and require a nonempty scientific/curriculum
conclusion; the generic value alone is not a claim that every axis was checked.

The released paired result V3 cannot be reused for textbook-only review: its
`SUPPORTED` item contract requires concept **and accepted-solution and
originality** citation applications. A textbook concept citation is not an
accepted past-exam solution report or an originality comparison. The successor
must make those purposes independent, require a textbook citation for supported
scientific/curriculum judgments, and leave unsupported solution/originality
judgments `INSUFFICIENT` without silently promoting the whole review to
`COMPLETE`. The released single result V4 has no Graph usage field at all.

Roll out in this order: schema/model parity and predecessor byte tests;
Catalog one/two-document and Item textbook planning; Workflow materialization
and receipt; distinct new prompts/result contracts; disposable-DB concurrency
and replay tests; source/browser tests; bounded live single, paired and Item
canaries; compatible activation with rollback. If the active textbook corpus or
policy cannot supply relevant authorized evidence for a use case, keep its old
path readable but do not label a new old-path result as textbook-grounded.

The GraphRAG chat tool and its access policy are reference implementations of
bounded authorized textbook reads, not a permission grant to review workers.
No external LLM API, worker NAS write, new DB table or generated Artifact in Git
is authorized by this decision.
