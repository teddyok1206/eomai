# Mixed indexing service policy 1.2

2026-10-19 UTC. Source-only successor to the released service policy 1.1.

1. **Boundary:** extend the existing Catalog service-policy reader, publisher and source gate;
   parsing a policy still grants no runtime identity or source permission.
2. **Canonical source:** an immutable released policy revision in the existing policy owner;
   the separately pinned source access policy remains authoritative and unchanged.
3. **Revision:** 1.2 is additive. Policy 1.1 schemas, hashes, namespace semantics and parsers remain
   exact; no existing revision or runtime identity is rewritten.
4. **Pointers:** retain exact service, runtime hash, source-policy revision/hash, corpus, Graph,
   space, recipe and native/resource-policy pins. Only mixed namespace2 and the closed combined
   projection use are admitted by 1.2.
5. **Access:** exact revision lookup, at most three namespace membership checks and at most two
   source-class membership checks; never resolve implicit latest during saved operations.
6. **Structures:** frozen contracts, bounded tuples and sets, and the existing indexed policy PK.
   Explicit schema dispatch selects only released 1.1 or 1.2; no registry or cache is introduced.
7. **Scale:** 64 KiB per policy, 1–3 ordered unique views, 1–2 source classes, maximum 1,024
   sources. Parsing is O(bytes); scope checks are bounded O(namespaces + classes).
8. **Transactions:** retain the current service fence, original source-policy/corpus locks,
   immutable publication savepoint and exact revision/hash/byte replay check.
9. **Dependencies:** schema precedes contract; pure shared namespace and source-policy checks
   stay in contracts. Existing Catalog adapters retain all PostgreSQL/IAM ownership.
10. **Failure:** unsupported versions, copied extras, mismatched pins, revoked authority and
    incompatible parent source policy fail closed with existing stable errors. No automatic
    activation, retry, policy widening or default-device change occurs.
11. **Alternative:** widening 1.1 would change released meaning; a second publisher would duplicate
    authority and transaction rules. A separate 1.2 model with closed dispatch is the smaller
    compatible extension. No new dependency is required.
