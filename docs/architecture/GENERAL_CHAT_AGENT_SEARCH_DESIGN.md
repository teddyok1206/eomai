# Conversational internal search (C06)

The previous C04/C05 release answers from explicitly attached sources. It does
not implement model-initiated search. C06 closes that gap; it does not enable
production, review, approval, deployment, account mutation, external APIs, shell,
filesystem, or direct worker DB/Catalog access.

## Boundary and design decisions

1. Responsibility: the isolated Codex adapter requests two allowlisted native
   dynamic tools. The existing Orchestrator worker client executes those reads
   through the Catalog application boundary under the conversation owner.
2. Canonical source: Registry revisions, published Graph snapshots and accepted
   solution reports. Search cards are discovery metadata, not content evidence.
3. Identity: V3 turn input/result and dispatch/worker envelopes are additive.
   V1/V2 schema bytes, prompt semantics, completed turns and artifacts remain.
4. Pointers: reads pin Item ID/revision/manifest hash, exact Graph snapshot/hash
   and Artifact member pointers. Existing Catalog resolution validates existence,
   permission, lifecycle, schema, media, source lineage and hashes.
5. Access: indexed topic/exam/recent discovery, keyed revision lookup, ordered
   bounded tool exchange, immutable append-only evidence. No corpus scan by model.
6. Structures: shared Catalog discovery implementation; maps/sets for offered
   revisions and duplicate calls; ordered tuple of tool evidence pointers. Reuse
   current indexes, queue, atomic claim, worker ticket and publication idempotency.
7. Scale: at most four searches and one read per turn, six discovery cards per
   search, three distinct Items/nine content sources, existing 96 KB context cap.
   Lookup costs follow existing indexed queries; exchange memory is bounded.
8. Concurrency: one admitted generation owns the existing FIFO chat claim.
   Tool traffic is multiplexed on that same owner-initiated, peer-credential-
   authenticated worker connection. No reverse worker connection/new socket,
   identity, DB table, migration, privilege grant, queue or framework.
9. Direction: shared contracts -> Catalog read implementation; API and
   Orchestrator adapters use contracts. Workers have neither Catalog socket nor
   DB credentials. Only Orchestrator publishes validated tool evidence to NAS.
10. Failure/retry: deny unknown tools, cross-turn IDs, request/hash mismatches,
    extra calls and out-of-offer reads. Persist sanitized success/empty/error
    tool records before returning them. No inference retry on uncertain transport.
    Final admission resolves canonical tool records and verifies the answer's
    citation context. Historical reads reauthorize all tool-resolved selections.
11. Simpler alternative: extracting keywords in the API or asking users to attach
    cards is insufficient: neither lets Codex refine the user's actual request.
    Separate planner generations/new worker sockets add unnecessary boundaries.

## Native integration

OpenAI Docs documents experimental `dynamicTools` and `item/tool/call` request/
response events: <https://learn.chatgpt.com/docs/app-server>. The adapter is pinned
to the installed CLI protocol. Exactly `search_eom_items` and `read_eom_items`
are allowed. All other native capabilities remain disabled. Tool arguments and
source text are untrusted. No private reasoning is exposed or logged.

The installed model metadata defaults to `code_mode_only`, independently of the
CLI feature switches. Pin `code_mode.direct_only_tool_namespaces=["functions"]`
so the two flat tools remain visible directly. Do not enable the Code Mode host,
shell, an MCP provider or another interpreter to route these reads. This uses the
pinned CLI's supported exposure override, not model-catalog/auth modification.
The initial live candidate completed without calling tools and is preserved as
non-acceptance evidence. Native mock events cannot prove actual model visibility.
See [pinned native tool routing](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/tools/spec_plan.rs).

Search uses topic terms, recent Items or exact exam placement. A read selects
only exact pointers offered in this turn, then materializes canonical content
and available solution reports through the existing resolver. One read per turn
avoids ambiguous citation keys; current tool-read sources replace initial
prepared sources explicitly. Follow-ups can search again without manual attach.

## Acceptance

- Schema/Pydantic, native event sequence and actual pinned CLI shape.
- Unknown tool/identity, malformed arguments, call limits, duplicate and forged
  pointers, stale revision/hash, authorization revocation and empty/error cases.
- Same-socket bounded duplex framing, disconnect, concurrent probe, no replay.
- Disposable persistence: exact claim/actor, canonical tool receipts, duplicate
  acceptance prevention, historical V1/V2 and actor-isolated history.
- Indexed shared search, API compatibility, dependency direction and wheel.
- Installed compatible runtime plus HTTPS conversation asking for internal Items
  **without manually attached sources**, source citations and a follow-up.

Source implementation PASS, installed runtime PASS and actual conversation PASS
are reported separately. Read-only search is not authority to perform mutations.
