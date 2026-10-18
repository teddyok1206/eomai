# Claim-scoped Chat similarity consumer

Status: implementation candidate; not operating activation or full goal acceptance.

## Boundary and canonical identity

The existing Orchestrator V4 broker owns the optional TOPIC enrichment. RECENT,
EXAM, READ and textbook retrieval keep their existing paths. The actual live Chat
claim supplies the actor and original request; workers cannot supply authority,
model paths, Graph manifests or a new QUERY identity. Catalog resolves the pinned
semantic Graph scope into its exact manifest pointer and applies the existing
shared Item discovery filters to at most 64 native candidates.

Canonical inputs remain registered request/dispatch members, the immutable native
Workflow/context and Catalog Item revisions. Small observations reference those
identities; no question, vector, Item/report body or binary payload is copied.
Semantic Graph hashes are not raw manifest hashes. Candidate component hashes are
not Item manifest hashes. Normal offered→read→materialize→reauthorize remains the
only citation path; an observation is auxiliary metadata, never source Evidence.

## Ordered bounded access and ownership

One per-turn consumer uses the existing native owner client, Catalog client and
Artifact commit owner. Native ordering is preserved, Graph cards follow, and a
revision-keyed map deduplicates at most 70 references in O(n) time/space. A shared
revision with conflicting Item/hash fails explicitly. There is no new DB table,
queue, search engine, scheduler, cache service or dependency. Cached original
acknowledgements are identity, not authority: the live claim and native source
authorization are checked again before metadata delivery/publication.

The normal Graph search runs first. Its permission/pointer failures are not hidden
by enrichment. Ordinary availability failure may retain valid Graph cards, but
native PENDING/unavailable/unknown without Graph cards is FAILED/unavailable, not
EMPTY. Permission, malformed reply or hash/pin failures never yield partial cards.
The existing READY-only provenance/1.0 and all worker V4/tool/2.0 bytes stay frozen.
A new closed observation/1.0 sibling records both ready and non-ready attempts in
the same atomic file-set as the normal tool record. Genuine legacy single-member
records remain distinguishable. The primary pointer remains unchanged for workers.

## Concurrency, retry and budgets

The existing claim/lease/idempotent native Workflow owns concurrency. One turn
submits one exact original request; explicit continuation is allowed only after
validated PENDING. Unknown transport latches for this turn: later TOPIC calls do
not physically resubmit. READ acknowledgements retain their actual action/hash;
they are never relabelled PREPARE. The initial PREPARE acknowledgement is retained
in memory solely for supported exact-original reads.

The existing 180-second/12-round wait is bounded further by one per-turn deadline;
each exchange reserves the fixed RPC timeout and shutdown interrupts waits. No
detached work or new identity is created after a timeout. A pending native Workflow
remains historical executable/recoverable work under its original owner; an ended
Chat claim cannot grant subsequent admission or source use.

## Composition, failure and rollback

Activation requires an explicit protected owner configuration selection, V4 RAG
policy and the already-supported private source endpoint. Invalid structural
configuration or missing fixed OS identities fail startup. Temporary endpoint
unavailability is recorded per query and may preserve authorized Graph cards;
a flag does not prove installation or live admission. Default is off.
Rollback deselects this optional consumer with a compatible installed release; it
does not rewrite historical tool records or native Workflow results. Old valid
search behavior remains independently usable when the consumer is not selected.

The simpler alternative (merge native cards without durable observations) loses
pending/unknown provenance and can present unavailable work as an empty search.
Changing frozen READY-only provenance to admit those states would reinterpret
history. A bounded owner-only sibling avoids both problems without changing the
worker protocol.

## Required evidence

Closed-schema/raw construction, actual broker routing, ready/non-ready and unknown
latching, original READ correlation, current actor/source rechecks, filtered native
ordering and duplicate conflict, unchanged READ/RAG/RECENT/EXAM, atomic publication,
legacy replay and missing/tampered companion tests. Source/package tests are not
production activation, GPU performance or current full-corpus coverage evidence.
