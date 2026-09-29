# ADR 0151: Prefer clean scientific illustrations for morphology references

## Decision

For each validated English image subject, the orchestrator derives two sorted, bounded Commons
query terms: the existing morphology query and the same query with an `illustration` qualifier.
The acquisition provider deterministically tries the illustration query first and retains the
ordinary morphology query as its bounded fallback. The worker-authored subject remains canonical;
the added query is a derived retrieval value recorded in the existing discovery command, intent,
bundle, and publication receipt.

## Reason and boundary

The production ammonite canary retrieved four license-compatible photographs from one polished
fossil series. All four contained dense shop backgrounds and correctly failed the existing
reference-simplification background gate. The official Commons API returned a public-domain clean
scientific ammonite illustration for the same target with the `illustration` qualifier, and the
unchanged simplifier accepted it. Retrying the local GPU or weakening the background gate cannot
repair a poor source selection.

This change uses the existing discovery-command `query_terms` tuple; no schema, database, queue, or
NAS model changes are required. Discovery still reads official Commons metadata, acquisition still
downloads only pinned candidates, and the orchestrator remains the sole artifact committer. The
ordinary query remains available when Commons has no eligible illustration result.

## Access pattern and complexity

Query-term uniqueness and deterministic ordering use a bounded set and tuple of at most two values.
The provider performs at most the existing bounded exact/fallback searches for each term and stops
at the first eligible candidate set. With both terms, network work remains constant-bounded and
candidate ranking remains `O(C log C)` for `C <= 20`; persistent storage remains unchanged.

## Failure, replay, and alternatives

Every query and chosen candidate is part of existing canonical command/result hashes, so recovery
replays the same identities. Missing eligible illustration results fall through to the ordinary
morphology query. License, single-subject, source, normalization, and simplification checks remain
fail-closed.

Weakening the complex-background threshold would pass unrelated scenery into img2img and obscure
the target. Adding a segmentation model would add an unreviewed dependency and a new model boundary.
Keeping only the ordinary query repeatedly selected unsuitable members. Using the already supported
multi-query contract is the smallest auditable correction.
