# Legacy automatic-learning preset pins

## Decision

Automatic legacy Item learning must receive an exact typed knowledge-analysis preset and capacity
pin. It must not resolve the mutable current preset at the point of promotion.

1. **Responsibility and boundary.** The Catalog application runner validates environment syntax;
   the learning coordinator validates persistent identities and owns the promotion/analysis
   transaction boundary. Manual `eomctl` learning remains an explicitly named current-preset path.
2. **Canonical source.** PostgreSQL logical preset/capacity records and their immutable released
   revision rows are canonical. Environment values are expected pointers, not canonical content.
3. **Revision model.** The pin separates preset logical ID, preset revision ID and content hash;
   pinned capacity revision/hash; and the shared capacity logical current revision/hash.
4. **Resolution.** Resolution checks logical key/ID/state/current pointer, revision owner/state/hash,
   canonical schema content, the preset-to-capacity edge, and the capacity logical current pointer.
5. **Access patterns.** Every operation performs five indexed primary/unique-key lookups. Terminal
   leaf detection uses the existing indexed batch joins and predecessor relation.
6. **Structures and indexes.** A frozen Pydantic value object carries the small immutable pointer
   set. Existing primary, unique, foreign-key, and batch indexes are reused; no list scan is added.
7. **Scale.** Validation is constant-space and O(1) indexed work per automatic step. This cost is
   intentional because a mutable-pointer race could create an Item with unintended analysis policy.
8. **Concurrency.** Shared row locks cover one complete automatic step and block logical-pointer
   publication until Graph/retry/promotion work returns. Promotion and analysis retain their own
   idempotent transactions.
9. **Dependencies.** The runner constructs the typed pin, the automation service holds the guard,
   and the coordinator resolves persistence. Domain contracts do not import infrastructure.
10. **Failure and replay.** Missing or drifted pins fail before an automatic side effect. Any
    unallowlisted terminal leaf fails before another reconciliation, Graph publication, retry, or
    promotion. An exact ordered allowlisted terminal leaf instead creates its one idempotent
    successor before other work. Existing promotion and analysis keys remain replay-stable.
11. **Rejected simpler alternative.** Merely observing the current preset from an operations loop
    leaves a check/use race and lets the coordinator resolve a later revision. Passing and locking
    exact pins closes that gap without a new framework or schema migration.
