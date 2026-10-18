# Chat similarity provenance and delivery boundary

Design before protocol/behavior, 2026-10-18 UTC. This implements part of C4 in
[the original goal](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md),
not a reduction of that goal or an operating activation.

## Decisions and required design note

1. Responsibility: the Orchestrator Chat evidence owner publishes the unchanged
   V2 tool record and a pointer-only similarity companion in one existing atomic
   file-set commit. No worker publication, new evidence authority or search engine.
2. Canonical state: existing Item/Graph/policy/report/index/QUERY Artifacts remain
   canonical. The companion records the exact native prepare request/reply; it
   neither copies the question/vector bytes nor replaces Graph Evidence receipts.
3. One logical tool Artifact has an immutable revision with two members. Keep
   logical/revision/raw member/semantic context identities separate. The companion
   names its sibling by member/schema/media/raw SHA, avoiding a circular pointer
   to its own not-yet-committed Artifact identity.
4. Validate closed schema2020-12/Pydantic, semantic companion hash, prepare/reply
   request correlation, exact original owner/ticket/basis, semantic Graph revision
   and policy scope, raw native manifest pin, sibling record SHA and delivered
   native source identities. Different Graph content/file hashes stay distinct.
5. Dominant operations: bounded immutable serialization, exact keyed membership
   and one idempotent publication; no corpus scan or metadata/title permission
   inferred from a score. Use maps/sets for offered/delivered candidates.
6. Reuse ControlFileSetPublisher, its existing advisory lock/resumable commit and
   unique idempotency key. No DB schema/index/cache/queue/dependency additions.
7. O(record bytes + companion bytes + at most64 candidates); record max256000B,
   companion max640KiB, each materialized only at this validation/commit boundary.
   No binary values or new question copies in PostgreSQL.
8. Validate before staging; commit both members or neither. The existing Chat
   publication lock and independent publication pool remain the owner boundary.
   Same key/different bytes fails; crash recovery uses the existing persisted Job.
   This is one file-set/approved-pointer publication, not a distributed atomic
   database/NAS transaction: COMMITTING intermediates retain supported recovery.
9. Catalog contracts define the auxiliary metadata; Orchestrator infrastructure
   owns local staging and calls the established file-set publisher. Domain/protocol
   never imports database/filesystem adapters. V4/tool2/origin1 bytes are frozen.
10. Missing/stale/hash-invalid references fail explicitly. A companion is not a
    grant to reauthorize an ended private claim. Follow-ups continue reauthorizing
    exact public citations through the existing V2 tool-record path, not by
    reexecuting or treating this companion as source Evidence.
11. Separate non-atomic publication can leave an apparently complete tool record
    without its computation provenance; embedding the full observation in V2
    would change released worker bytes/semantics. One existing file set is simpler.

## Candidate semantics the eventual producer must preserve

Only TOPIC discovery can add related candidates; RECENT/EXAM retain their current
ordering and filters. Native QUERY scores the whole authorized bounded population,
not just the legacy six cards or a Graph top64 shortlist. Subsequent TOPIC/source/
current-registry filtering of the global native top64 is **not exact top-K over
the filtered population**. Preserve this limitation explicitly. Reuse the official
Catalog metadata owner for that filtering, then combine native and Graph channels
by exact identity without mixing their scores or granting materialization rights.

The initial companion supports only a validated READY native reply (whose context
may be READY/PARTIAL/EMPTY). It does not manufacture a result for timeout/PENDING/
FAILED/unavailable. Those states need their own truthful owner outcome before a
consumer can activate; never use this contract to call them empty or complete.

The companion stores only the actually delivered native subset, in native order;
native source component hashes are not Item manifest hashes. Match the native
Item identity, but obtain/reauthorize the distinct manifest pin from Catalog.
Ordinary lexical cards may also appear in the unchanged tool record. Neither a
native candidate nor the companion is a citation until the existing offered/read/
materialization/reauthorization path validates the exact public Item revision.

Scope of this checkpoint: contract, atomic producer and sibling validation.
Actual metadata filtering, broker composition, current permission reauthorization,
protected deployment and end-to-end delivery remain required next steps. Passing
publication tests alone is not C4 completion or proof that the model used a source.

## Source and disposable publication checkpoint — 2026-10-18 UTC

The new, previously unreleased closed schema is
`general-chat-similarity-provenance/1.0`, raw source/resource SHA
`5832a534f919bdb55e75978c46b888295486da31ed026d1c725008e7e76bcd62`.
GeneralChatArtifactStore reuses its existing publication lock/independent pool and
ControlFileSetPublisher, with canonical `chat/evidence.json` plus the auxiliary
`chat/similarity-provenance.json`. Same-key replay returns the same Artifact;
different content and attempts to upgrade an existing legacy key fail explicitly.
No DB schema/index, released worker schema/prompt, permission or source policy changed.

The native prepare1.0 reply does not expose a final-context Artifact-member pin.
Do not invent that pin. The companion therefore preserves the bounded typed
pointer/observation manifest actually returned by that owner: no question text,
vectors, original Item content or report bodies. This is an explicit validation/
audit materialization boundary, not another canonical corpus or authority cache.
If a future supported protocol exposes that canonical context member, reference
its exact revision/hash instead of introducing a parallel source or implicit path.

Final combined source verification: **399 PASS / 14 suites / 55.26s / no skips**:

- new provenance suite (42): contract closure/hash/bounds/native ticket and scope,
  native order/prefix, approved/indexed/source-kind claims, PENDING rejection,
  two-member publication/replay, legacy compatibility, different-content/legacy
  key conflict, missing/corrupt/duplicate/unapproved members, cleanup and frozen
  V4 transcript/committed tool-record replay;
- Chat scope bridge, RAG owner/contract/native, agent search and owner composition;
- private prepare exchange and acknowledged original continuation;
- Catalog schema/wheel/RECORD/installed resources and dependency boundaries;
- generic control-file-set publication and batch Artifact resolution;
- historical318-schema freeze, with this post-baseline resource excluded while
  retaining the exact original entries and aggregate hash.

Strict mypy2 production modules, Ruff/format5 files, diff and fresh-process no-ML
imports PASS. No new dependency. These results are not summed with earlier397/398 or
individual suite runs.

Publication tests use a real **temporary SQLite database and local filesystem**.
The existing production read resolver requires PostgreSQL typed JSON and a
repeatable-read/read-only snapshot. Tests explicitly adapt real SQLite rows to
that metadata snapshot and run the unchanged production member/hash resolver;
**PostgreSQL isolation, native/source/Identity authority and runtime activation
are not proven by these fixtures**. No operating database was a pytest target.

Earlier failed test evidence is preserved in this account: initial missing fixture
alias;20 PASS/1 FAIL from SQLite rejecting PostgreSQL SET;20 PASS/1 FAIL from a
test incorrectly calling the execution-envelope-only schema-family resolver on
a tool record;40 PASS/1 FAIL from claiming SYSTEM_OBSERVATION without prepared
agent state. Fixes were fixture/expectation corrections. Production SQL, the
closed schema families, permission checks and citation/state rules were **not
relaxed**. The final test uses INSUFFICIENT_EVIDENCE and proves discovered cards
remain offers, not materialized/cited source Evidence.

Status: **SOURCE_AND_DISPOSABLE_SQLITE_PASS / NOT_INSTALLED / NOT_ACTIVE**.
Next required C4 work remains official metadata filtering, optional broker
composition, actual caller/current source reauthorization, protected release and
end-to-end delivery. Full C1–C5 activation, seed/delta/current canonical coverage,
genuine CPU/CUDA comparison and conditional coherent default/rollback remain open.
