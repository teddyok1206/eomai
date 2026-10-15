# Anchor-bounded QUERY provenance backport

2026-10-15 UTC. This minimal owner release is based on047611bb, not an API/Web
upgrade. Main design: SYSTEM_RAG_SIMILARITY_CONTEXT_IMPLEMENTATION_BOUNDARY.md §37.

1. Catalog owns exact-anchor preparation; full context ranking keeps full capture.
2. Canonical sources remain approved Item/profile/report, Graph/policy and registered
   immutable index/Artifact bytes. No cache or new canonical store.
3. Original request, Workflow/command and launch IDs/keys/revisions remain unchanged.
4. Same authority, pinned schema/media/hash/lifecycle, registered index/binding/row
   and numeric validation. Exact selected source precedes materialization.
5. QUERY uses exact-key lookup; ranking uses the existing ordered full population.
6. Existing selected-source predicate/index and root-local immutable read-window
   scope are reused. No DB index/migration, wire schema, queue or dependency changes.
7. Native source materialization becomes bounded to1 rather than up to1024 sources;
   selected index/member verification costs remain. Operation counts are not latency.
8. Caller-root start/end current fences, unique claim, lease and idempotency remain.
9. Catalog owns IO/admission; native runner calls the supported anchor entry.
10. Denied/stale/missing anchors/indexes fail; completed QUERY compares relevant
    exact anchor/text/request pins. Full consumer coverage has independent late
    reauthorization. No expiry bypass or automatic duplicate submission.
11. Increasing auth TTL or dropping validation would hide the source of delay;
    shared existing verifier methods are simpler than a new authority/cache layer.

The original canary stopped at16:21:04 after fresh-auth expiry. Read-only metadata
at16:23:49 shows original Workflow RUNNING, START PROCESSING attempt1, application
step RUNNING without output, no native launch Job. Preserve and inspect the exact
original lease before supported continuation. No live success is claimed here.

Source counterpart: main a689415e. The owner-only regression passes183 /95.25s;
the final anchor suite passes12 /5.81s (11 overlap; one additional exact-native-
input test,184 distinct total). Strict mypy3 production modules and Ruff/format
pass. An initial regression had one fixture failure: its synthetic anchor seam
omitted pure pre-index preparation validation. The fixture now mirrors the actual
Catalog entry; production validation was not weakened. Both logs are preserved.

Existing recovery intentionally refuses an expired command with a RUNNING step
but no original native launch Job. This backport does not change that guard,
repair operating rows, submit another key or claim live model acceptance. It is
an inactive compatible candidate only, not automatic recovery authorization.
