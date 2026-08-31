# Integrated Science Graph Capability V1

## Responsibility and boundary

This read-only capability answers one question: can a new item request safely use the currently
published `integrated-science-textbooks` Graph with the pinned Integrated Science editorial outline?
The Application API owns the projection. Scientific Studio consumes it and never infers readiness
from a static outline or from a Graph ID alone.

## Canonical source and revision model

The reviewed editorial outline resource remains the canonical hierarchy. A knowledge corpus is the
logical entity; its current published Graph snapshot is the immutable revision selected for a new
request. The capability returns the pinned snapshot revision and snapshot SHA-256 only when every
required mapping invariant passes. Historical snapshots remain immutable and are not rewritten.

## Pointer and resolution checks

Resolution verifies the active corpus key, its current snapshot pointer, graph identity, published
snapshot state, exact reviewed framework revision, all 43 expected curriculum units, their node
stable keys and parent pointers, and the exact 119-row transitive closure. The corpus current pointer
is read again after projection; a concurrent change fails closed. Missing, stale, partial, or
inconsistent data returns `UNAVAILABLE` without substituting another snapshot.

## Access patterns and structures

The dominant operations are one unique-key corpus lookup, one snapshot primary-key lookup, ordered
iteration over 43 curriculum units, and membership comparison over 119 closure tuples. Existing
unique/B-tree indexes cover the corpus key, snapshot identity, snapshot/framework unit scan, and
closure ancestor/descendant scans. Expected and observed rows are compared as sets for O(n) time and
O(n) space; the fixed reviewed scale is 43 units and 119 closure rows. No new table, cache, or derived
persistent state is introduced.

## Transactions, dependency direction, and adapters

The API read adapter performs the database projection and returns an immutable API contract. The
router only applies authorization and renders the result. The Web gateway consumes the API contract
and projects a presentation-only READY/UNAVAILABLE state; it does not import Catalog persistence.
This preserves `GUI -> API use case -> contracts`, with SQLAlchemy confined to infrastructure.

## Failure, retry, and idempotency

The operation is read-only and has no retry or idempotency key. Every request recomputes readiness
from the current pinned pointers. Any mismatch is an explicit unavailable reason. A READY response
requires exact counts and non-null immutable pointers; an UNAVAILABLE response must not expose a
partially trusted snapshot pointer.

## Simpler alternative considered

Hard-coding `graph_grounding_available=true` after one successful publication is simpler but cannot
detect a retired corpus, a changed current snapshot, missing hierarchy rows, or closure corruption.
Checking only that a snapshot exists is also insufficient because selection keys could fail at
retrieval time. The bounded indexed verification is therefore required.
