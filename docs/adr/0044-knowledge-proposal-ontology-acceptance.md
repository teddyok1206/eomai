# ADR 0044: Validate graph ontology before Knowledge Analysis acceptance

Status: Accepted

Date: 2026-08-25

## Context

Knowledge Analysis worker proposal schema `1.0` proves bounded structure, closed IDs, source-anchor
resolution, and provenance shape. It intentionally does not encode the full cross-row Education
Graph endpoint matrix. An R6 proposal was therefore structurally valid and auto-accepted even
though five edges used valid edge names with incompatible node types. The graph publisher correctly
failed closed, but that was too late in the lifecycle.

The canonical source of proposal content remains its immutable proposal Artifact Revision and
member hashes. The canonical source of edge semantics remains
`KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY`. The dominant access pattern is one pass over proposal
members, one O(n) node-ID map, and one O(e) edge validation pass. Expected proposals are bounded to
512 nodes and 1024 edges, so time and auxiliary space are O(n + e). No database schema, index,
migration, external dependency, or new binary materialization is required.

## Decision

- Resolve the pinned proposal receipt and each hash-checked member into the existing typed worker
  proposal at the Catalog application boundary.
- Validate every edge using one node-ID-to-type map and the existing closed endpoint matrix before
  transitioning a run to `VALIDATING` or accepting it.
- Persist the proposal pointer for forensic lineage, but fail the run with stable code
  `KNOWLEDGE_ANALYSIS_ONTOLOGY_INVALID` and create no accepted-result Artifact when an endpoint is
  incompatible.
- Keep graph projection validation as defense in depth.
- Publish a new immutable Knowledge Analysis control bootstrap revision 3 with explicit endpoint
  guidance. Preserve v1/v2 configuration and the historical worker-proposal schema/model semantics.

## Consequences

Historical R6 remains an immutable accepted analysis record but is not graph-publishable. It is not
rewritten or silently reinterpreted. New invalid proposals fail before acceptance, while valid
proposals continue through the same risk-policy and idempotent acceptance flow. The new preset is a
pinned revision, so previous workflows retain their original instructions and hashes.

The simpler alternative of expanding endpoint compatibility was rejected because it would corrupt
the ontology. Editing the existing proposal schema or Pydantic validator was rejected because it
would reinterpret immutable historical protocol content. Prompt-only correction was rejected
because model instructions are not a security or data-integrity boundary.
