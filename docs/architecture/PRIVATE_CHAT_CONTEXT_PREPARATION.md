# Initial private Chat context selection

Design before behavior,2026-10-18 UTC. This fills the missing initial selection
between an actually owned Chat question and the existing private Workflow request.

1. Catalog owns official Graph/policy/index resolution, not Chat ownership or
   numerical execution. Existing Chat/source owners must still validate the origin.
2. Canonical inputs are the original question basis and owner-selected immutable
   Graph/access-policy/numerical namespace. No question text or fake Item anchor.
3. Preserve original request/basis identity, exact source/index revisions, raw
   Artifact hashes and semantic hashes separately. Current index is selected only
   for the first request; replay compares the stored exact request instead.
4. Use existing closed PrivateChatSimilarityRequest1.0. The small frozen preparation
   value is owner-local, not a new wire schema or authority grant. No worker change.
5. Dominant access is unique-namespace lookup then immutable revision/member lookup,
   O(log I) per indexed lookup plus bounded manifest parsing at existing limits.
6. Reuse existing repository/B-tree and root-local Artifact reader. Factor initial
   view selection once for the real reference and private use cases, not a second
   search service, registry, cache, queue or DB table.
7. The caller holds one clean Catalog root on the correct engine. Current actual
   operator/Graph/policy authority is checked before and after index bytes, then
   producer provenance is checked. No commit, writes, claim or model operation.
8. Only CONTENT_ONLY private comparisons are supported. Missing index remains
   an explicit absent pin; private native submission must not invent a fallback.
9. Catalog infrastructure owns current selection; pure contracts/domain remain
   infrastructure-free. Runner later constructs the original execution request.
10. Corrupt/stale index, revoked policy/Graph, other actor and malformed preparation
    are explicit errors. Replay never selects latest or creates another identity.
11. Reusing reference preparation with an invented approved Item would be shorter
    but scientifically false. Copying its index loop would duplicate rules, so the
    existing initial-selection operation is shared instead. No dependency added.

Runner's selection entrypoint reads the original actor/turn Workflow before calling
Catalog's first-capture operation. Replay reuses its exact private context/audit/
controls and compares the owner-local selection intent; it never recaptures a
current head. Both selection-based and already-pinned entrypoints share one root,
original lookup, request builder and atomic Workflow+START path. Missing initial
index is explicit INDEX_NOT_PREPARED with no Workflow, command or model operation.

## Implementation and exact verification

Initial view selection now has one Catalog implementation shared by approved
reference and private-question preparation. A small owner-local value and pure
intent validator preserve CONTENT_ONLY/basis/configuration closure without an
invented Item or public enrollment of private text. The Runner reads its original
actor/turn key first and routes both entrypoints through the same request builder
and atomic start. Replay never captures a newer head or rebuilds the audit.

Detached preparation passed45 focused and246/8-suite (overlapping) source cases,
strict3/Ruff/format4. That code was transferred only after the separate135-pin
98/257 gate completed and its original reader candidate16adadda was pushed.
Final combined main1014 PASS/43 suites/252.64s, strict11/Ruff/format8/diff PASS.
Focused68 predates two extra redaction cases and overlaps the combined result;
these figures are not summed. No private static admission or worker tool changed.

Exact138-pin finite PostgreSQL100 PASS/no skips/cleanup PASS, read back2026-10-18
00:47 UTC. New two cases cover actual first Catalog namespace/index selection
without an approved Item anchor and initial selection→original Workflow+START→
replay without recapture. Existing candidate composition, revocation, canonical
private read and atomic persistence cases remain in that same cohort. Identity,
Chat ownership, declared Workflow fixtures and numerical backend are synthetic;
SQL/index registration/committed files and ranking are real. No genuine encoder,
operating DB change, login, service deployment or tool activation occurs.

Evidence `/opt/eom/embedding-benchmark-os-evidence/private-context-ZXyFHg9h`;
helper raw `d3778bfaed725d6748ae278e316d58f060839862f2639ad3e4ccc2ad83b0e578`;
test stdout raw `84a6f56935fd0795a7440daf8f317eee8563efc1f8ab9d3455d2dfc7e2ade2d1`.
Original root1367215/wrapper1367208 terminated normally; source/test/migration pins
stayed unchanged through cleanup. No schema/storage/queue/migration change in
this slice; the earlier257-case0057 stage proof stays historical, not a rerun for
this source. Operating migration remains last verified0055, source head0057.

Actual protected runtime composition/private policy, current-source/native
admission, installed Chat delivery and full C1–C5/seed–delta/six real device
comparisons/default/rollback remain OPEN. Earlier actual-user HTTP403 freshness
gate is deferred, not fixed by source tests; no login prompt before the user's
24-hour no-login deadline.

## Next Chat delivery boundary

Prefer integration behind the existing `search_eom_items`/`read_eom_items` owner
interfaces over introducing a parallel chatbot or silently changing V4 schema
bytes. Private context is auxiliary discovery, never scientific source evidence;
actual materialization/citations still use the official current Catalog reader.
Exact exam placement, RECENT order, explicit filters and permissions must remain
unchanged. Any semantic-discovery successor must define how it preserves TOPIC
intent and pins before implementation; merely reordering six legacy cards does
not prove full private candidate retrieval. Keep PENDING/known absence distinct
from revoked authority, corrupt pointers and failed original execution, and never
retry numerical work through a new identity to meet a tool timeout. Preserve the
canonical private context/receipt provenance even when workers receive ordinary
discovery cards. New internal owner messages require schema-first contracts;
changing worker prompt/tool/result meaning requires an explicit successor, not
unversioned fields or pretending legacy bytes already permit them.

The next owner application joins this existing first-capture/atomic-start boundary
to one shared finite native drive and the existing canonical completed read:
[private QUERY prepare application](PRIVATE_CHAT_QUERY_PREPARE_APPLICATION.md).
That source seam is not private-policy admission, a new Chat tool or activation.
