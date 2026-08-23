# ADR 0038: Separate Item Origin from Assessment Occurrence and Interaction Type

## Status

Accepted

## Context

EOM must distinguish a human-authored new item, an institutional past-examination item, an EOM
human/AI item, and an adaptation. Existing `item_type_key` describes the content/template or
interaction type. Existing Item Provenance records retain source pointers but do not by themselves
provide a normalized institution and examination occurrence identity.

One `item_kind` enum would conflate independent facts and make combinations impossible or
misleading.

## Decision

Item classification uses orthogonal immutable dimensions attached to one exact Item Revision:

- `source_domain`: internal EOM, external institution, external individual, or legacy unknown;
- `creation_method`: human authored, AI assisted, AI generated, imported, adapted, or unknown where
  evidence cannot establish it;
- an optional versioned source Organization Revision;
- zero or more exact Assessment Occurrence Revision observations;
- exact derivation pointers to source Document or Item Revisions;
- a pinned rights/access policy revision;
- existing workflow, Content Intake, and Item Provenance evidence.

`item_type_key` remains unchanged. “Past examination” is established only by an
`OBSERVED_IN_EXAM` edge/pointer to a real Assessment Occurrence Revision backed by immutable source
evidence; it is not a boolean label.

Organization is a logical entity with immutable revisions. An organization revision carries the
reviewed display name, organization class, jurisdiction, normalized aliases, effective dates, and
provenance. Free-text names are intake observations until they resolve to a reviewed revision.

Assessment Occurrence is a separate logical entity with immutable revisions. Its revision pins the
issuing Organization Revision, exam family, administration year/date, session, subject, form/region
where applicable, source evidence, and rights policy. It remains separate from EOM's Product/Form
entities because an external examination event exists independently of an EOM Deliverable. A future
link may state that an EOM Product/Form reproduces or references that occurrence.

The future `ItemOriginProfile` is a small immutable typed value associated one-to-one with an Item
Revision. It composes pointers to existing provenance/workflow evidence; it does not copy source
documents, item payloads, or binaries.

## Resolution and Failure Rules

Resolution validates logical and revision existence, lifecycle, expected schema, rights, source
evidence, and hashes. Institutional or past-examination classifications without a resolvable
organization/occurrence fail closed. Unknown legacy observations remain explicit and cannot satisfy
a retrieval request that requires verified institutional past-exam evidence.

Changing an organization name, occurrence metadata, origin classification, or rights decision
creates a new revision/profile. Historical Item Revisions keep their pinned values.

## Access Patterns and Indexes

Frequent lookups are exact Item Revision origin, filtering by source domain or creation method,
reverse lookup by Organization/Occurrence Revision, and derivation traversal. Use B-tree indexes on
these foreign keys and controlled fields plus unique one-to-one Item Revision ownership. Derivation
is a sparse adjacency relation. Expected lookup is O(log n + k).

## Consequences

An EOM item may be human-authored or AI-assisted without inventing new compound enum values. An EOM
adaptation can retain external source lineage while remaining an internal Item. Graph snapshots can
project origin edges, but Catalog provenance/profile records remain canonical.

The simpler alternatives were rejected: overloading `item_type_key` breaks existing semantics;
free-text institution tags cannot provide stable identity; and a `past_exam` boolean cannot identify
which examination, source, rights, or correction revision supports the claim.
