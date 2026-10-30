# Shared Graph term collisions during creative registration

## Boundary and canonical source

The Catalog Graph projection owns derived node identity. Accepted analyses, source Item
Revisions, original proposals, public solution reports and their hashes remain canonical and
unchanged. A worker can describe the same named scientific term as a CONCEPT in one source
and a PROCESS in another. This is not permission to overwrite either type or merge unlike
types. Publisher `1.10.0` correctly rejects that ambiguity but stops a whole creative cohort.

Publisher `1.11.0` adds an explicit projection policy; old publisher replay is unchanged.
There is no wire schema, DB migration, queue, worker protocol or new dependency. Existing
publication commands/manifests already pin publisher version, accepted analyses, structure,
source pointers and expected prior Graph revision. Publication idempotency includes the new
publisher version, avoiding reuse of a failed older projection.

## Identity and resolution

- Preserve the existing Item-Revision scope for Item-local elements.
- Collect node types for each remaining projected key. One type retains the shared key.
- TEXTBOOK and PAST_EXAM keys/types are protected. Their conflicting types still fail closed.
  If they supply one type, preserve its original key/ID; a conflicting creative type receives
  `shared-type:<type>:<SHA-256(original key)>` in the new Graph revision.
- When only creative sources disagree, qualify every competing type deterministically,
  rather than select a winning meaning by input/run order. Same-key, same-type nodes still
  merge across Items. No equivalence relationship is invented between unlike types.
- Conflicting types for the same original key within one immutable Item Revision still fail.
- Keep source pointers, labels, edge endpoint validation, Item bindings, curriculum alignment
  and answer-bearing rules. Every edge uses its proposal-local endpoint mapping. Accepted
  proposal text and embedding input are not rewritten by this projection.

Historical Graph revisions remain immutable. Only a new successor projection can change
creative-only derived IDs. Protected textbook/past-exam node IDs and edges must be preserved.
Unknown targets, hashes, access or lifecycle continue to fail at existing owner boundaries.

## Access patterns, concurrency and recovery

The prepass uses dictionaries of key→type sets plus (Item Revision, original key)→type.
It is O(N) time/space for N proposed nodes, followed by existing deterministic serialization;
there is no pairwise source comparison. Publication remains in the existing transaction/CAS
and artifact commit owner. One cohort process serializes publication even when multiple
official Workflow jobs solve different sources concurrently. Existing indexed idempotency,
claim and lease rules remain authoritative; a local cursor/status file is only a cache.

Restart reuses the exact accepted analysis and original report. It does not regenerate the
question/report or rewrite failed history. Rollback selects the prior installed owner and
leaves accepted artifacts and published Graph history intact; old code cannot reinterpret a
new Graph under old projection semantics.

## Simpler alternatives and checks

Blindly overwriting type, ignoring a node, retrying the same old projection, or rewriting an
accepted proposal loses identity/provenance or deterministically fails again. Scoping every
scientific concept to an Item would avoid collisions but destroy useful shared Graph links.
Only actual cross-type collisions receive the bounded typed identity.

Required tests: old publisher rejection/replay; historical textbook/past-exam node and edge
preservation; creative cross-type separation; same-type sharing; within-Item rejection;
deterministic order; endpoint/curriculum/Item-binding closure; report byte/hash preservation.
Before operating activation, validate the installed wheel and an actual accepted collision
through the supported Graph owner. Service active alone is not success.

Source checks on 2026-10-30: related projection/curriculum/Item publication suites 154 PASS;
new endpoint test plus typed identity/cohort/status suites 27 PASS (overlapping suites, not
summed). Existing guarded disposable PostgreSQL Graph/analysis identity, concurrent create,
acceptance, publication/replay and index checks 6 PASS. These are not operating acceptance
and do not prove three actual worker slots are active.

During operating restart, a second local scheduling defect was confirmed: the runner slept
10 seconds even after each already-verified source. Reconstructing 95 source identities thus
added 950 seconds of pure idle time, in addition to real pointer/read validation. Completed
VERIFIED ticks now continue immediately; actual EXTRACTING/ANALYZING work keeps the existing
10-second poll and graceful-stop boundary. No status-file cursor is trusted and no validation
is skipped. This is a control-loop delay fix, not a faster model or an execution-policy bypass.
