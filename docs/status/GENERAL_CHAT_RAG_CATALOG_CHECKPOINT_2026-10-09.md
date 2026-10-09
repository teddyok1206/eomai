# CHAT-RAG-2 Catalog read-path checkpoint

As of 2026-10-09 05:04 UTC. This is source implementation plus a read-only
diagnostic against actual stored materials, **not deployed conversational
acceptance**. Parent source: `eaa287beca103339a44b66e5790e0a209ced53e6`.

## Implemented boundary

- `chat_rag_resolution.py`: prepare pinned Graph/policy scope, retrieve bounded
  approved analysis and reauthorize exact prior evidence.
- `KnowledgeRetrievalApplicationService`: public read-only selection uses the
  existing authoring authorization, bounded multihop ranking and source resolver.
  Indexed Korean terms resolve to real stable topic keys; no dummy query seed.
- `KnowledgeGraphPublicationService.resolve_accepted_analyses`: bounded public
  read method reuses the accepted result/proposal/receipt/member validator. Four
  run/Artifact/job preload queries retain their ORM identities; source cache is
  shared. Three Graph reference projections use two queries, not per-source SQL.
- Private Catalog `CHAT_RAG` handler is restricted to the existing trusted API/
  dedicated-chat owner socket peers; it is not a worker mutation capability.
- Original source logical/revision/member/hash, accepted result and normalized
  Markdown remain distinct. Intake batch/staging details are not projected.
- Actual operator status, password-change requirement, role and effective read/
  retrieval permissions are checked before metadata discovery. No new grant.
- Source text is labeled approved analysis rather than a verbatim original quote.
  Text budget is UTF-8 safe and respects a smaller released policy token limit.
  Original PDF and PNG pixels are not shown to the model by this read path.

The chat Graph hash is `snapshot_sha256`. Manifest Artifact file hash is a
separate concept. A source review caught this distinction before integration;
five regressions now check snapshot/hash/Graph/revision binding. The initial
preliminary materialization probe is not the final compatibility evidence.

## Source verification

- Broad chat/protocol/native/API/Web/Catalog/Graph/analysis/dependency suite:
  **800 PASS** (includes the first 43 new Catalog RAG cases).
- Two additional accepted-analysis batch/pointer cases are checked by the final
  focused **45-case** suite; these counts must not be summed as independent
  coverage of all behavior.
- Ruff, formatter and mypy for all five changed production modules: PASS.
- Existing released chat schema/prompt bytes were not modified.
- No new dependency, queue, migration, canonical data or privilege was added.

Initial new test invocations exposed a fixture import path and an absent mock
reader attribute; these fixture errors were corrected and the affected suites
rerun. They were not live failures and did not trigger operational changes.

## Actual stored-material diagnostic

Source-side only: the new source was imported in an administrative diagnostic,
not installed into a long-running service. Catalog queries used read-only
transactions. No credentials, item/document content or worker output was printed.

```text
PREPARE=SUCCEEDED
RETRIEVE=SUCCEEDED
SOURCE_CLASSES=TEXTBOOK,TEXTBOOK,TEXTBOOK
SOURCE_COUNT=3
MATERIALIZED_TEXT_BYTES=4303
AUTHORIZE_EXACT_PRIOR=SUCCEEDED
EXACT_CONTEXT_EQUAL=true
PREPARE_SECONDS=4.103
RETRIEVE_SECONDS=3.128
AUTHORIZE_SECONDS=2.569
MODEL_CALLS=0
GPU_CALLS=0
HWPX_BUILDS=0
DB_MUTATIONS=0
ARTIFACT_PUBLICATIONS=0
SERVICE_RESTARTS=0
```

Graph revision: `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9`.
Snapshot SHA: `sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`.
Released policy: `accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9`,
`sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0`.
Context SHA: `sha256:16c68bea45fbd6269acfd7698fb1ef6a124a0788656acb137a2c7d2f111774f7`.

Read-only PostgreSQL EXPLAIN used `ix_knowledge_node_term_lookup`,
`ix_knowledge_node_source_class` and `ix_knowledge_node_type`, with index/index-only
scans and bounded top-K. This is an observed plan for one representative query,
not a workload benchmark, installed-role permission test or latency SLO.
Sanitized private diagnostic: `/tmp/eom-chat-rag.bwgaz7ou/catalog-read-smoke-v2.json`.
It is small metadata, not canonical conversational evidence.

## Remaining gates

```text
CONTRACT_FOUNDATION=PASS
CATALOG_SOURCE_READ_PATH=PASS
ACTUAL_MATERIAL_READ_ONLY_DIAGNOSTIC=PASS
NATIVE_V4_TOOL_CONNECTION=PENDING
OWNER_DUPLEX_HISTORY_AND_REPLAY=PENDING
RAG_SOURCE_CARD_UI=PENDING
DISPOSABLE_PERSISTENCE_AND_INSTALLED_ROLE_GATES=PENDING
COMPATIBLE_RUNTIME_DEPLOYMENT=PENDING
AUTHENTICATED_TEXTBOOK_ANSWER_AND_EXACT_FOLLOWUP=PENDING
GOAL=ACTIVE
```

Next: connect the already defined V4/read-tool V2 contracts to the existing native
tool broker/owner/worker/history flow, preserving old Item navigation and receipts.
Do not infer completion from this source checkpoint or from AGENTS.md guidance.
