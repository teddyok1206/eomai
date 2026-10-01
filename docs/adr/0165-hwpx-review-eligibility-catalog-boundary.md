# ADR 0165: Catalog-owned HWPX review eligibility resolution

## Status

Accepted for implementation on 2026-10-01.

## Context

The post-registration review lifecycle permits one current `generic-item-development@1.16.0`
Item Revision in `IN_REVIEW` to produce a validated HWPX before human approval.  Catalog owns the
eligibility rule because proving it requires dereferencing the immutable V2 Item manifest and its
component Artifact Revisions on NAS.

The Application API runtime is intentionally denied NAS access.  Its HWPX composition currently
injects a local `RegistryService`, so the review exception reaches Catalog persistence code inside
the API sandbox.  The safe manifest read fails and is collapsed into
`HWPX_APPLICATION_REVISION_INELIGIBLE`, even though the registered Revision is otherwise eligible.
Granting NAS access to the API or reducing the decision to a state/version check would violate the
runtime boundary and weaken the review contract.

## Decision

### Responsibility and dependency direction

Catalog remains the sole owner of the HWPX review-eligibility decision and NAS dereference.  A new
read-only private Catalog application operation accepts one exact Item Revision ID and returns a
typed immutable eligibility proof.  The API composition supplies an adapter implementing the HWPX
Manager's existing Item Revision resolver port: ordinary Item/Revision metadata still comes from
the indexed Registry read model, while review eligibility is resolved through the private Catalog
socket.  The HWPX domain/application service does not import an API or socket implementation.

The proof is not an approval and is not persisted as another source of truth.  It binds the logical
Item, immutable Item Revision and number, `IN_REVIEW` state, source Workflow/version, exact manifest
Artifact/Revision/hash, and a canonical self-hash.  HWPX compares every returned identity with the
already selected Revision before accepting the exception.

### Canonical source and pointers

Canonical state remains:

```text
Item.current_revision_id -> immutable Item Revision
                         -> V2 manifest Artifact Revision/hash
                         -> ordered component Artifact Revisions/hashes
```

Catalog resolves and validates that chain using the existing V2 manifest validator.  Missing,
stale, non-current, non-`IN_REVIEW`, wrong Workflow, schema/media, lifecycle, component, or hash
inputs fail explicitly.  No implicit latest Revision is substituted and no large bytes cross the
socket.

### Access patterns and data structures

The dominant operation is a key lookup by `item_revision_id`, followed by primary/foreign-key
lookups for the current Item, Workflow, Pack, metadata, manifest, and its bounded component set.
Existing primary keys and uniqueness constraints match those accesses.  The manifest component
comparison uses keyed positions already validated as sorted and unique; corpus-size scans, new
indexes, caches, tables, and migrations are unnecessary.  Runtime cost is `O(c)` time for `c`
components in the one Revision and `O(c)` transient validation space; `c` is contract-bounded and
independent of corpus size.

### Transaction, concurrency, retry, and idempotency

The operation is read-only and runs within one Catalog session snapshot.  It changes no DB row,
Artifact, lifecycle, or lease, so byte-identical retries are naturally idempotent.  HWPX still
records its build request through the existing unique operator/idempotency-key boundary.  A
concurrent current-Revision change or approval makes a later eligibility resolution fail or makes
the returned proof disagree with the selected Revision; neither condition is repaired silently.

Socket unavailability is reported as Catalog unavailability.  A valid negative eligibility result
uses the existing Registry stable error family.  The HWPX public boundary continues to expose the
stable `HWPX_APPLICATION_REVISION_INELIGIBLE` product error without leaking NAS or database detail.

### Simpler alternatives rejected

1. **Allow API NAS reads.** This expands a deliberately isolated runtime and duplicates Catalog
   storage authority.
2. **Trust only `IN_REVIEW` plus Workflow version.** This omits the exact manifest, Pack, metadata,
   and component pointer checks required by ADR 0164.
3. **Return a boolean.** A boolean cannot bind the decision to the selected immutable Revision and
   manifest, so a stale or mismatched response cannot be detected.
4. **Copy the manifest into PostgreSQL or the socket response.** This duplicates a canonical
   Artifact and moves unnecessary payload across boundaries; the smallest typed proof is enough.

## Required verification

- JSON Schema 2020-12 is defined before behavior and is byte-identical in canonical/package
  resources; Pydantic enforces the same shape and proof self-hash.
- Catalog accepts only the exact current `1.16.0` `IN_REVIEW` V2 Revision and performs the existing
  safe manifest/component validation.
- HWPX rejects wrong Item, Revision number/state, Workflow, manifest pointer/hash, and proof hash.
- Application API composition reaches Catalog through the private socket and does not call the
  NAS-reading local Registry method.
- Existing approved-Revision HWPX, runner composition, approval, historical schema bytes, and
  idempotent build behavior remain unchanged.
