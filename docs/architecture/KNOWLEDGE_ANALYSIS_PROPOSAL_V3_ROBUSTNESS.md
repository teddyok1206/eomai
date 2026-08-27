# Knowledge Analysis Proposal V3 robustness design

Status: implementation target
Date: 2026-08-26 (UTC)
Owner boundary: Workflow Contracts, Catalog Contracts, Orchestrator, Catalog application service

## 1. Responsibility and boundary

The knowledge-analysis worker analyzes one immutable, bounded educational-document range and
returns a proposed normalized document plus source-grounded graph records. The worker does not
publish graph state or write canonical storage. The Orchestrator validates the role result, splits
the proposal into a deterministic Artifact file set, and commits the validated Artifact. The
Catalog application service owns request creation, risk review, acceptance, batch lifecycle, and
publication eligibility.

This change closes a schema-to-typed-contract gap exposed by the historical V6 batch. The V6 JSON
Schema admitted multiple ambiguity observations with the same `code`, while the Pydantic model
treated that category code as a unique record identity. Two legitimate observations of one
ambiguity category therefore passed worker-side structured-output validation and failed only at the
Orchestrator typed boundary.

The change is additive. These deployed identities remain byte-for-byte immutable and readable:

- `knowledge-analysis-worker-proposal/1.0` and `/2.0`;
- `knowledge-analysis-request/2.0`, `/3.0`, and `/4.0`;
- proposal receipts `/1.0`, `/2.0`, and `/3.0`;
- accepted results `/2.0`, `/3.0`, and `/4.0`;
- role protocols `workflow-role/1.4.0`, `/1.5.0`, and `/1.6.0`;
- workflow definitions `knowledge-analysis@1.0.0`, `@2.0.0`, and `@3.0.0`;
- execution presets V4, V5, and V6 and all their batch/run evidence.

V3 proposal processing uses new immutable identities:

- worker proposal `knowledge-analysis-worker-proposal/3.0`;
- request `knowledge-analysis-request/5.0`;
- proposal receipt `knowledge-analysis-proposal-receipt/4.0`;
- accepted result `knowledge-analysis-result/5.0`;
- role result `knowledge-analysis-proposal-result@4.0`;
- role protocol `workflow-role/1.7.0`;
- workflow definition `knowledge-analysis@4.0.0`;
- execution preset bootstrap V7.

## 2. Canonical source and identity model

The pinned Educational Document Revision and its approved analysis-bundle Artifact Revision remain
the canonical source. A source path is only a materialization location; it is never identity.
Every request pins the document revision, Artifact Revision, member path, SHA-256, selected physical
page interval, execution-preset revision, risk-policy revision, and request hash.

Proposal records use these identity/value rules:

- anchors, nodes, edges, claims, and component observations have explicit local IDs unique within
  one proposal;
- node `stable_key` values are also unique within one proposal;
- references are local typed pointers and must resolve exactly within the same proposal;
- ambiguity entries are small immutable observations with no independent lifecycle and no inbound
  references;
- `category_code` classifies an ambiguity but is not its identity, so separate observations may
  share a category;
- exact duplicate ambiguity value objects are rejected;
- proposal order is retained as immutable output order but is not used as durable identity.

This avoids inventing an `ambiguity_id` that no consumer resolves or persists. It also avoids using
a category as an accidental surrogate key.

## 3. Pointer and resolution checks

Before Artifact staging, the new typed proposal boundary must establish all of the following in one
linear integrity pass:

1. every explicit local ID and node stable key is unique;
2. every per-record anchor pointer list is duplicate-free;
3. every node, edge, claim, component observation, and ambiguity anchor resolves;
4. every edge endpoint resolves, is not a self-edge, and matches the endpoint types declared by its
   relationship contract;
5. every endpoint-type triple is allowed by the closed Education Graph ontology;
6. any claim marked as influenced by general knowledge requires proposal-level general-knowledge
   provenance;
7. exact duplicate ambiguity value objects are absent;
8. the request identity and every source anchor's Artifact Revision/member path equal the pinned
   request;
9. educational-document anchor locators remain within the selected physical-page interval.

JSON Schema 2020-12 remains the first validation boundary. Pydantic then enforces the cross-record
rules that JSON Schema cannot express. The worker instruction explicitly lists the same integrity
pass so the model is not asked to discover hidden post-generation constraints.

## 4. Dominant access patterns and data structures

The dominant operations are local-ID uniqueness, membership, key lookup, and sparse-reference
resolution. The validator therefore builds dictionaries keyed by anchor ID, node ID, and node stable
key, plus sets for the remaining explicit IDs and exact ambiguity-value hashes. It performs ordered
iteration only to preserve deterministic diagnostics and serialization.

For `A` anchors, `N` nodes, `E` edges, and `R` other references, validation is `O(A + N + E + R)`
time and `O(A + N + E + R)` bounded auxiliary space. Contract maxima remain small and explicit
(1024 anchors, 512 nodes, 1024 edges, and bounded supporting records). No repeated list scan or
quadratic deduplication is required.

The persistent graph continues to use indexed immutable snapshot projections. This proposal change
does not add a DB table, column, migration, cache, or binary payload.

## 5. Transaction and concurrency boundary

Worker output is local and untrusted until schema and typed validation both pass. Artifact staging
uses a fresh workspace; the Orchestrator commits only the complete validated file set. Catalog
acceptance stores immutable pointers and hashes in its existing transaction boundary. A failed
proposal creates no accepted result and no graph publication.

Each analysis run and each batch range retains its existing idempotency key and at-most-one active
lease rules. V7 is a new preset revision, so V6 accepted ranges cannot be silently reinterpreted or
reused under the new protocol. A V7 full batch executes all 495 ranges and preserves V4/V5/V6 as
historical evidence.

## 6. Dependency direction and adapter ownership

- Catalog Contracts own proposal value types and cross-record domain validation.
- Workflow Contracts own versioned role input/result envelopes and schema dispatch.
- Orchestrator owns result validation, local materialization, and Artifact commit.
- Catalog application services select the compatible immutable version and own run/batch state.
- worker instructions describe the contract but do not redefine domain rules;
- filesystem, PostgreSQL, Codex CLI, and NAS operations stay in their existing adapters.

Domain/contract packages do not import infrastructure. Workers do not communicate with one another,
write NAS, or acquire persistence responsibilities.

## 7. Failure, retry, and idempotency behavior

Cross-record failures remain fail-closed as `WORKER_RESULT_INVALID` with safe stable diagnostics.
No validator repairs, renames, drops, merges, or silently deduplicates worker records. The only
semantic correction is that repeated ambiguity categories are valid when the observations differ.
Exact duplicate ambiguity observations are still rejected.

Automatic retry remains disabled. A terminal failed batch is never resumed by mutating its rows.
After source gates and deployment, a newly authorized V7 batch uses a new batch ID, run IDs, jobs,
idempotency key, markers, and evidence directory.

## 8. Alternatives considered

### Remove the V2 uniqueness check in place

Rejected because it would reinterpret deployed V6 result bytes and violate protocol immutability.
It would also leave the misleading `code` name and hidden worker contract unchanged.

### Add a synthetic ambiguity ID

Rejected because ambiguity observations have no independent lifecycle, are not pointer targets, and
are consumed only as ordered evidence and aggregate counts. An ID would add accidental identity and
maintenance cost without a real lookup use case.

### Silently merge or suffix duplicate category codes

Rejected because the Orchestrator must not change untrusted semantic output to make it acceptable.
Merging can lose distinct evidence; suffixing turns a category into an opaque invented identifier.

### Replace every proposal array with a dynamically keyed JSON object

Rejected because Codex strict structured-output schemas require closed object properties and cannot
safely express arbitrary runtime keys. Arrays plus explicit local IDs and a linear indexed validator
are simpler and preserve deterministic order.

### Retry on typed-validation failure

Rejected because it spends usage without correcting the hidden contract and makes batch behavior
nondeterministic. The contract must be fixed first; automatic retry stays disabled.

## 9. Verification strategy

Required tests cover:

- JSON Schema 2020-12 and Pydantic acceptance of two distinct ambiguity observations sharing one
  category;
- rejection of exact duplicate ambiguity values;
- duplicate IDs and node stable keys for every identity-bearing collection;
- duplicate local anchor pointers;
- dangling anchors and edge endpoints;
- self-edges, endpoint-type mismatch, and closed-ontology mismatch;
- general-knowledge provenance mismatch;
- request/source pointer and physical-page-range mismatch;
- deterministic Artifact members, receipt counts/hashes, and accepted-result pointers;
- protocol coexistence and exact historical schema/bundle hashes;
- schema-first worker validation, clean-process imports, batch idempotency, and failure isolation;
- replay of the sanitized structural signatures from all available historical worker results;
- no large binary DB values and no graph publication from a failed proposal.

Release gates include focused unit/integration tests, the complete non-live knowledge/control-plane
suite, disposable-DB integration, Ruff, formatter, strict mypy, shell syntax, repository boundary
and secret scan, deterministic schema/package inventory, and reviewed release artifacts.
