# ADR 0163: Wire contract identity and dual validation

## Status

Accepted for implementation on 2026-10-01.

## Context

EOM has three contract gaps that share one cause: a wire discriminator is sometimes reused for a
projection with a different shape, and a few file/process boundaries rely on a Pydantic model
without a canonical JSON Schema 2020-12 contract.

The affected boundaries are:

- Catalog curriculum outline -> Application API -> Studio projection;
- execution preset draft request -> control-plane revision;
- Catalog mock-exam assembly policy -> Application API view;
- operator-authored mock-exam rating-set JSON -> production CLI;
- HWPX Manager -> isolated HWPX Builder request and template-binding files; and
- the isolated Kordoc Node bridge -> HWPX Builder report.

Released schemas and historical artifacts are immutable. Existing clients may still send the
legacy execution-preset request during a bounded compatibility period.

## Decision

### Responsibility and boundary

Contract packages own wire identity and validation. Application services normalize successor and
legacy API requests into the existing domain use case. Infrastructure adapters validate their
file/process inputs before constructing domain-facing typed values.

### Canonical source and revision model

Each distinct wire shape receives one distinct `schema_version`:

- `curriculum-editorial-outline-view/1.0` for the Studio projection;
- `execution-preset-draft-request/1.0` for a preset creation request, with an explicit pinned
  `target_revision_schema_version`;
- `mock-exam-assembly-policy-view/1.0` for the public assembly-policy projection;
- `mock-exam-explicit-rating-set/1.0` for the operator rating document;
- `hwpx-render-request/1.0` and `hwpx-template-binding-manifest/1.0` for the legacy single-item
  Manager/Builder handoff; and
- `hwpx-kordoc-bridge-report/1.0` for the Node bridge report.

The corresponding logical entities and immutable revisions remain unchanged. A projection is not a
new revision of its source entity; it is a separately identified value object derived from one
pinned revision.

### Pointers and resolution checks

Existing identifiers, revision identifiers, media types, member paths, and SHA-256 values remain
separate. Successor schemas retain all current pattern, cardinality, ordering, and hash constraints.
No resolver may substitute a current/latest revision for a pinned one.

### Access patterns and data structures

Runtime schema lookup remains an immutable map from a short logical contract key to one packaged
schema resource, giving expected O(1) lookup and O(S) startup inventory validation for S schemas.
Schema-version uniqueness auditing uses maps keyed by discriminator and sets of canonical object
shapes, giving O(S + F) time and space for S schemas and F model fields. No repeated list scan or new
persistent index is required at the current scale (under two thousand tracked schema files).

### Transaction and concurrency boundary

No database schema or transaction boundary changes. API idempotency remains keyed over the exact
successor request body. HWPX jobs continue to commit through the existing Manager transaction and
Artifact boundary; validation happens before Builder work or output commit.

### Dependency direction

Interfaces consume API/HWPX contract models. Application services normalize requests and own use
case orchestration. Infrastructure adapters load packaged schemas through contract-package public
validation functions. Contract and domain packages do not import service implementations.

### Failure, retry, and compatibility

Malformed or mismatched wire data fails with the existing stable boundary error before side
effects. The execution-preset endpoint accepts the released legacy request and the successor during
the compatibility period, but Studio emits only the successor. The released mock-exam `/policy`
read endpoint retains its legacy response while Studio selects the additive `/policy-view`
successor. Historical schema bytes and artifacts are not rewritten. Replaying the same idempotency
key with a different legacy/successor body remains a conflict.

### Automated enforcement

A repository contract audit must reject:

- unresolved external `$ref` values;
- one structured `schema_version` mapped to multiple closed object shapes unless explicitly
  allowlisted as a discriminated union family;
- the enumerated operator/file/process boundary models in this decision without their required
  canonical schema identities; and
- canonical/package schema byte drift unless a released immutable exception is recorded.

Boundary tests must also prove JSON Schema rejection occurs before Pydantic parsing for the new
operator and HWPX file/process contracts.

## Alternatives considered

Keeping the existing discriminators and documenting their context is simpler locally, but leaves
version-only routing ambiguous and makes future consumer mistakes likely. Replacing all current
models or introducing a generic contract framework would be larger than the demonstrated need.
Successor value contracts plus one small audit module preserve compatibility with less machinery.

## Consequences

There is no migration and no large payload duplication. A few additive schemas, DTOs, validator
entries, and compatibility branches are required. The old HWPX V1 canonical/package formatting
difference remains immutable history until its release status is resolved; new enforcement records
that exact exception and requires byte parity for all other mirrors.
