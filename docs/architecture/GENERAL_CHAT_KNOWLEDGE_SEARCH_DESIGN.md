# Chat knowledge search — first implementation boundary

Status: first search slice live, 2026-10-08 UTC. The user approved proceeding
with the integration plan and runtime activation. This note records C01/C02/C03,
not C04/C05 acceptance. Earlier candidate checkpoints remain historical evidence.

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

### Build checkpoint

Implementation commit: `617e132eff71612abe0d99dfde50b5f56b2d95c0`.
Both package builds passed from this exact commit; subsequent documentation
commits do not change the source identity embedded in those wheels.

| Component | Build evidence | State |
| --- | --- | --- |
| API and shared contracts/platform | `scripts/api/deploy_release.sh --build-only`; wheel RECORD verification PASS; directory `/tmp/eom-api-build/617e132eff71612abe0d99dfde50b5f56b2d95c0.e87puf/dist` | Built, not installed |
| Web | `scripts/web_gui/build_release.sh`; non-editable runtime simulation PASS, 39 verified files; wheel `/tmp/eom-web-gui-build/617e132eff71612abe0d99dfde50b5f56b2d95c0.3PLFOA/dist/eom_web_gui-0.1.0-py3-none-any.whl` | Built, not installed |

Web wheel SHA-256:
`6b9296c5b5798285ed8a600963b9b4cb8a86e2953cef51454c7a6b4191aac310`.
Temporary build paths are staging locations, not durable Artifact identities.
The source tests and package inspection pass; live activation and manual review
of the new search UI remain pending. This checkpoint used zero model calls,
no DB migration or grants, and made no changes to the six production slots.
The next slice is C04/C05: trusted Catalog access, bounded source input, cited
answer contracts, and protected history/revocation before coordinated activation.

## Runtime privilege correction

The first authenticated HTTPS search failed with an API runtime privilege denial
on `item_origin_profiles`. The disposable query-plan tests used owner-created
temporary tables and did not prove the limited production role's access. The new
search UI was withdrawn to the prior verified Web release while plain chat and
the additive API release remained available. This supersedes the initial
assumption that the existing DB grants covered every discovery dependency.

The canonical origin profile and lexical index remain Catalog-owned. The API
read adapter needs only `item_id`, `item_revision_id`, `item_manifest_sha256`,
and `source_domain` from `item_origin_profiles`, and `graph_snapshot_revision_id`,
`node_id`, and `term` from `knowledge_node_terms`. Origin projection must select
those columns explicitly, not materialize the complete ORM entity. No rights
records, provenance author fields, full-table SELECT or writes are authorized on
either table. Application permissions remain GENERAL_CHAT_READ intersected with
ITEM_READ; owner/worker grants and all six slots remain unchanged.

The existing API privilege matrix is the authority for these additive column
grants. Extend its supported bootstrap and startup readiness checks, sharing the
existing column-profile mechanism with narrowly scoped UPDATE grants rather than
adding another reconciler. Bootstrap revokes column-level drift before granting
the exact matrix; readiness checks missing/extra columns and rejects table-wide
grants. Catalog metadata and Item/Graph revisions are unchanged: no new logical
entity, pointer, schema, migration, cache or queue is needed.

Access remains batched indexed lookup and one read-only repeatable-read search
transaction. Privilege checks are one bounded matrix query over the scoped tables
and their columns. Reconciliation is an operator deployment boundary, not a
worker or per-search side effect. Failure blocks readiness; retries use the same
supported bootstrap and retained credential, never direct row changes. The
simpler full-table grant is insufficient because it exposes unused metadata and
does not enforce least privilege. Validate actual queries and denial of excluded
columns/writes with the guarded disposable API runtime role before redeployment.

Correction validation: API/Web regressions 935 PASS / 18 environment-specific
SKIP, and guarded discovery SQL/plan plus actual limited-role tests 23 PASS.
The role suite also caught an origin-filter `EXISTS (SELECT *)`: PostgreSQL
requires access to its unneeded columns, so the filter now explicitly selects the
permitted revision key. The temporary-table metadata suite alone could not catch
that boundary. Exact readiness rejects missing grants, an extra author-column
grant, and full-table SELECT; excluded metadata and writes are denied by the real
limited role. Bootstrap replay/drift reconciliation passed in the disposable DB.

## Operational acceptance

The corrected API/platform/contracts release is
`dafe7db999353dac6b57bebe1a183d42d3aa1610`, tree
`9dad14b87c60cc94eb835fd40bf7be068ecec5a3`, built at 2026-10-08 11:16:57 UTC.
The dedicated owner/worker pin advanced through the supported stopped-runtime
installer to the same release. Web is `40876a61dc82996262cfd4e70335c5704d4cc720`;
its 39-file installed integrity check passed. Web and chat runtime/protocol/unit
bytes are unchanged between those commits, so this is a verified compatible
release set, not an unexplained mixed deployment.

API wheel RECORD, runtime isolation, installed metadata and authenticated
login/refresh/logout smoke passed. The actual HTTPS Studio session verified secure
cookies, authentication/CSRF rejection, forbidden authority fields, search UI
assets, recent results (3), exact pinned lookup (1), official exam results (3),
topic results (3), empty search (0), wrong hash rejection, and the exact selected
revision's Preview. Chat slot and history remained readable and READY. These are
HTTP/session/asset checks, not a new manual visual review or model-answer test.

Production origin inventory is 520 EXTERNAL_INSTITUTION profiles and 106 current
eligible Items without an origin profile; there are no current INTERNAL_EOM
profiles. Consequently the GENERATED filter correctly returns zero. Its positive
SQL/metadata path passed in isolated fixtures, but positive live GENERATED
coverage is NOT_AVAILABLE_IN_CURRENT_DATA. Those 106 Items remain accessible in
RECENT/EXACT reads and are not silently reclassified. Origin-profile completion
is a separate inventory/backfill decision, not a deployment row update.

All 13 pre-existing terminal chat receipts retain the same pointer/state digest
`c58208f939a5aa080194bbdd38e011b0e51fb9a10668f903f50f030bcaa5d1bb`.
Migration remains `20261008_0049`; six slot configurations are unchanged. No chat
turn, question production, GPU call, HWPX build or model retry was submitted.
The two old non-terminal job rows have no held leases, no active transient
execution or executing Workflow command, and remain unmodified historical state.
Source regression gates: 935 PASS/18 environment SKIP, guarded PostgreSQL 23 PASS,
post-fix focused 65 PASS; Ruff/format/mypy/shell/diff checks PASS. Test counts
overlap and must not be summed as unique coverage.

API rollback record:
`/var/lib/eom-api/deployments/dafe7db999353dac6b57bebe1a183d42d3aa1610.json`.
API staging wheels:
`/tmp/eom-api-build/dafe7db999353dac6b57bebe1a183d42d3aa1610.ILfnac/dist`.
Their SHA-256 values are:

- Application API: `10cc364daa7cca73c38825c1ef34cb3db58ea5729e125a09605d2ac7da34bc61`.
- API contracts: `dcc24ca6af00c6aa76df2313f321c85f1128a31c5e5a28cbba59f0b366ee658f`.
- Platform: `2a57fa4399eaebb8f406e7391531bf3d51a3b4abdd7e00c2c4f07ffced756e36`.

Web staging wheel SHA-256:
`6a2fd4d4c9391944f67dab23374da5e926d5274d088dfe8a00ca94944a98b552`.
The initial failed live request remains failed evidence. The prior Web package
was actually restored during diagnosis; compatible API/chat services stayed
available, and search was activated again only after the limited-role correction.
Prior API/Web wheels were verified and retained, not deleted. No claim of a full
API rollback drill follows from the successful Web withdrawal.

`FIRST_SLICE_SEARCH_LIVE=PASS`. C04 grounded input/cited answers, C05 protected
grounded history/revocation and subsequent integration milestones remain pending.

# Grounded answer successor — implementation boundary, 2026-10-08

Implementation checkpoint: additive JSON Schema/frozen contracts and the native
structured-answer adapter are source-only candidates. No grounded public route,
Catalog socket admission, turn persistence, citation-history projection, or UI
activation has been released. C04/C05 remain IN_PROGRESS. The existing V1 worker
envelope rejects V2 turns, so this adapter cannot accidentally activate grounded
answers under a V1 policy. Do not equate pure contract/native-channel tests with
real authorized Catalog materialization, inference, or production acceptance.

The official App Server documentation supports turn-local `outputSchema`:
[Codex App Server](https://learn.chatgpt.com/docs/app-server#turns). The installed
0.160.0 generated `TurnStartParams` schema also exposes that field. The adapter
projects only the answer object shape into the native schema; canonical JSON
Schema 2020-12 plus frozen models and the owner's request/context/citation checks
remain authoritative. It does not repair JSON, invent citations or retry a failed
inference. V1 prompt bytes and old schema files remain unchanged.

Checkpoint verification: 534 focused protocol/native/owner/worker/API/Web tests
PASS, including 55 new grounding/native cases. Ruff, formatter and strict focused
mypy PASS. This run contains no DB concurrency test, live model inference or
grounded browser acceptance. The Starlette test-client dependency emits its
existing deprecation warning; no dependency was added or changed in this slice.

The user now authorizes connecting discovery to actual Codex answers (C04/C05),
not just metadata cards. The first answer slice uses up to three explicitly
selected Item Revisions, with a pinned optional Graph snapshot. It preserves
plain-chat V1 and does not imply automatic corpus-wide search or image inspection.

1. Responsibility: Catalog resolves authorized sources; the existing Chat Owner
   prepares, dispatches, validates and commits a grounded turn; workers only answer.
2. Canonical source: Registry Item/component Artifacts, published Graph pointers,
   and accepted additive solution reports. A search card is not source content.
3. Identity: existing conversation/turn and immutable Item/Artifact revisions;
   no separate source-card registry or new persistent queue.
4. Resolution: independently verify the active operator and current ITEM_READ /
   GENERAL_CHAT permissions, Item lifecycle and official approval, exact manifest,
   component schema/media/member/hash, published Graph and accepted report linkage.
5. Access patterns: bounded indexed Item/Graph lookups, batch pointer resolution,
   source-key membership, append-only history and existing atomic claim/replay.
6. Structures: ordered frozen source tuples and keyed pointer maps; existing
   Registry/Graph/analysis indexes. No embeddings, vector DB or mutable global cache.
7. Scale: at most three Items and bounded associated Graph/report text per turn;
   linear rendering in bounded source bytes; no corpus scan or N+1 history queries.
8. Transactions: no DB transaction across model generation. Recheck authorization
   before materialization, execution and history exposure; pin immutable inputs.
9. Dependency: public contracts -> existing application ports -> Catalog/socket
   adapters. Only the trusted owner peer receives the new Catalog read operation;
   it cannot call Catalog mutations. No worker socket/DB/NAS access is added.
10. Failure/replay: unsupported/missing/stale/hash/denied sources fail explicitly.
    Same intent keeps the same input pins. Unknown model outcomes are never retried
    blindly; existing exact known-result recovery remains authoritative.
11. Alternative: adding source text to a V1 user string would erase its provenance
    and break honest version/recovery semantics. Add successor message/input/result,
    worker/owner envelope and citation contracts; keep released V1 schema bytes.

Answer sections distinguish source-supported explanation, model inference, general
knowledge and insufficient evidence. Keys must belong to the exact prepared
context. The owner issues a result/context-bound citation integrity receipt, not a
scientific correctness approval. UI navigation comes from verified references,
never model-written paths or URLs. Graph absence is reported, not fabricated.

## EOM representative agent operating connection (2026-10-08)

The representative is a read-only conversation role, not a second Orchestrator.
It explains EOM workflows, answers from explicitly selected immutable Items and
accepted solution reports, and distinguishes timestamped authorized observations
from inference. Account changes, approval, production and deployment remain in
their existing application use cases; chat never claims to have performed them.

Normal chat also uses the successor input with nullable knowledge. Catalog owns
the bounded actor-scoped observation and source resolution. The Chat Owner stages
that typed snapshot and retains exact input/output pointers. Existing indexed
conversation history, atomic capacity claim and idempotency are reused. No new
queue, DB schema, external API, worker tools or dependency is introduced.

Released V1 envelopes remain accepted for historical reads and recovery. New worker,
dispatch and owner successors carry V2 turns. Evidence family resolution reads
the registered immutable member descriptor, never guesses its schema from payload
or substitutes a current revision. History and follow-up context recheck current
source access; immutable receipts are preserved if authorization is later revoked.

Canonical citation evidence is the immutable request and result pair: the receipt
is a deterministic validated projection, not a duplicated database JSON blob.
UI source navigation is built from verified Item identities. At most three Items,
nine source members and bounded history are materialized per turn, using indexed
lookup, request-local maps and batch artifact resolution. Errors before inference
release the exact claim through a supported terminal transition; unknown execution
never triggers automatic model replay.

Source candidate verification: 597 focused protocol/API/Web/Catalog tests, 48
guarded disposable PostgreSQL persistence tests and 23 search/query-plan/runtime
permission tests passed. Ruff and mypy (33 changed source files) passed. The
limited chat-role suite needs its own guarded role preparation: an older test
database's API reconciliation rotated that shared disposable role's credential,
so its 12 setup failures are not runtime acceptance or a production incident.
Production connection and native/browser canary acceptance are recorded separately.

Boundaries: selection is explicit (up to three immutable Items attached from
search); no corpus-wide autonomous model tools, live image inspection or chat
mutations are claimed. Actor observations contain authorized counts and own
workflow states, not other users' conversation/operation details. Corpus counts
and grouped own-workflow counts are aggregate queries over the existing tables;
this candidate does not invent a new cache or index without query evidence.

The first installed native canary prepared and committed its immutable V2 input,
but returned terminal CODEX_TURN_FAILED. Its failed receipt remains unchanged;
there was no automatic generation retry. Native outputSchema projection now omits
array uniqueItems (in addition to conditional semantics), while the complete
canonical JSON Schema and Pydantic uniqueness checks remain mandatory at admission.
Native rejection diagnostics expose only closed categories, never upstream error
bodies. A successful source/unit gate is not substituted for the next live canary.

The dedicated, freshly prepared disposable chat-role database passed all 12
limited-role tests; the prior rotated test credential was not repaired by widening
production permissions. The first adapter-corrected native turn completed with a
valid input/result/observation receipt. Grounded browser acceptance remains a
separate gate, not inferred from that ungrounded turn.

Studio startup now records a navigation generation before asynchronous reads.
Late initial-route restoration applies only if no newer navigation occurred;
existing administrator permission checks still apply. A Node test executes the
actual boot function with delayed reads and covers initial restoration, newer
chat navigation, and unauthorized administrator fallback. This guards the shared
presentation boundary without introducing chat-specific routing state.

### Additive solution-report resolution correction

Live metadata showed that the selected Graph pins 520 accepted V9 bases, while
their accepted V10 solution successors are additive reports, not new Graph
members. Requiring both runs in that snapshot excluded valid reports. Match the
existing retrieval semantics instead: Catalog resolves the unique accepted V10
successor of the exact snapshot-local base, validates its source Item/component
and base accepted-result pointer against that association, and pins the resolved
report Artifact member in the immutable chat input. No Graph republish, latest
snapshot fallback or report-history mutation is needed.

The existing solution resolver returns small frozen source/base provenance beside
its validated pointer/report. This avoids another query or duplicate Artifact
read. At most three indexed predecessor lookups, a request-local map, and the
existing unique-successor check remain authoritative. Missing reports remain
explicit limitations; wrong source/base hashes fail closed. Existing source,
Graph and worker schemas, DB/queue and dependency direction are unchanged.
