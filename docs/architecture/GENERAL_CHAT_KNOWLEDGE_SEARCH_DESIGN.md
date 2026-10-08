# Chat knowledge search — first implementation boundary

Status: implementation in progress, 2026-10-08 UTC. The user approved proceeding
with the integration plan. This note records C01/C02/C03, not C04/C05 acceptance.

## Inventory

Read-only repeatable-read inventory, as of 2026-10-08 05:33:27 UTC, using the
installed API identity (no production mutation): migration `20261008_0049`;
626 current ACTIVE/APPROVED Items. The integrated-science graph is
`graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9`, SHA
`sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`.
Its occurrence projection contains 520 distinct past-exam revisions. Current
graph membership covers 545 current Items; source classes include 520 PAST_EXAM
and 25 APPROVED_ITEM sources. Snapshot analysis count 1040 is not an Item count
(additive report analyses are separate). TEXTBOOK pointers exist, but their
presence does not establish chat access/rights; documents are excluded here.
Installed API pin is `aead8a5840c2b5aa61a1a0bd281c0ff32746429e` and Web pin is
`d5c113ed32e6ab0dc3227d860e7de117b7a850fe`; both were read from installed build
metadata, not inferred from Git HEAD. General chat owner/worker services are active.

## Responsibility and canonical source

This first slice is a model-free read use case: explicit recent/exam/topic/exact
query -> bounded cards -> existing pinned Item Preview. It neither starts chat
turns nor claims an Evidence Bundle, source-byte validation or grounded answer.
Item Registry is canonical. Graph is a pinned metadata discovery projection.
Each card keeps Item ID, revision, manifest SHA and official approval separately.
Exact requests verify the manifest SHA and never resolve implicit latest.
Graph source hashes belong to the analyzed content component member, **not** to
the Item manifest. The new resolver compares the analysis's Item revision,
Artifact ID/revision and content hash with that revision's component pointers.
The live metadata audit found zero mismatches across these component pointers.

## Pointers and scope

Only ACTIVE Items with IN_REVIEW/APPROVED revisions are discoverable. Ordinary
queries use current revisions; explicit pinned lookup can read an eligible
non-current revision without substituting another revision. Existing ITEM_READ
scope is reused, intersected with GENERAL_CHAT_READ; no new permissions/grants.
The API already owns this official read adapter boundary (including Item Bank).
Cards contain metadata only, not raw Graph nodes/snippets, documents, reports,
answer-bearing excerpts or arbitrary Artifact paths. Preview rechecks its own
permission and resolves actual bytes. Registry-only cards remain discoverable.

## Structures, scale and concurrency

Dominant patterns: revision PK lookup, immutable snapshot lookup, ordered recent
iteration, exact exam B-tree lookup, snapshot/term lookup, batched membership.
Existing indexes suffice initially. Candidate limit <=20; query terms <=8;
exact references <=6. Maps/sets deduplicate revision/event/membership lookups.
Results are a bounded ordered tuple; no total-count query or unbounded offset.
The response explicitly reports truncation rather than pretending to enumerate
the corpus. Topic queries return indexed item metadata only, not unrestricted
Graph evidence. There is no new cache/table/queue/migration/dependency.
Lookup is O(log N + K) for exact/indexed keys; term join work depends on matched
postings and is bounded by the existing corpus, with output bounded by K. Do not
claim a LIMIT alone bounds DB work; measure the PostgreSQL plan before release.

Each query uses one repeatable-read, read-only transaction and pins one published
snapshot belonging to the integrated-science corpus. A supplied pin must match
ID/hash/corpus; missing, retired or hash-mismatched pins fail explicitly. Registry
reads remain usable when no graph is published; exam/topic require a graph.

## Dependency and failure boundary

Public JSON Schema precedes frozen API/Web DTOs. Router authenticates and calls
the application service, which depends on a read port; SQL is in the adapter.
The existing QueryAdapter exposes one batch revision projection so approval
receipt rules are reused, not copied into this new adapter. Web BFF forwards
only the typed request and validates the typed response. UI generates navigation
from Item/revision IDs, not model URLs; stale search responses and logout clear
the cards. Source deletion/revocation is rechecked on subsequent search/Preview.

Search is read-only and needs no idempotency key/model retry. A replay with a
snapshot pin uses the same graph but does not claim immutable registry selection;
C04's turn-owned selection Artifact will provide that stronger guarantee.
Errors are stable missing/stale/hash/projection/unavailable codes. No fallback
to a model, latest snapshot or unrelated corpus. Plain chat remains independent.

## Simpler alternative and staged follow-up

Calling existing latest Item Bank endpoints alone omits non-indexed Items and
does not pin a graph. Dumping Registry/Graph into a prompt is unsafe/unbounded.
The minimal correct first slice is this official bounded read projection.
It does not yet need Chat Owner -> Catalog socket admission; C04 must add the
operation-specific trusted peer, independently verified actor, bounded source
materialization and additive worker/citation contracts before grounded turns.
C05 history/revocation/replay and C06 actual multimodal input remain pending.
No ordinary V1 user message is silently changed into a grounded input.

## Verification and release state

First slice: API/Web regressions 933 PASS / 18 environment-specific SKIP;
guarded disposable PostgreSQL metadata/plan suite 14 PASS. The latter uses
connection-local temporary tables, 10,000 synthetic Items and 20,001 lexical
postings. It verifies read-only repeatable-read, index selection without forcing
the planner, fixed query count for 1 vs 20 Items, ambiguous exam placements,
missing/stale/hash pointers, pending approval, deletion and no-Graph behavior.
It is not a claim of production throughput or persistence constraint acceptance.
Browser-module fixtures verify stale responses, owner changes, safe text and exact
navigation. They are not a manual browser visual acceptance.

The broad regression run also caught a pre-existing obsolete deployment test:
it expected a literal 59-schema list after the release builder had switched to a
canonical-directory inventory. The test now follows the real staging boundary,
verifies mirrored bytes, and retains runtime/RECORD/OpenAPI/PDF checks. A pure
read-only POST search is explicitly marked in OpenAPI, not given an unnecessary
DB idempotency record. Mutating endpoints retain their idempotency requirements.

This is a **source candidate**, not live activation. C04/C05 and their full
RAG/report/policy inventory remain pending. Keep the existing live chat release
unchanged until the compatible release-set decision: the supported API installer
also replaces a shared platform wheel consumed by pinned owner/worker runtimes.
Do not bypass that ownership or use an ad-hoc pip install to publish this UI.
