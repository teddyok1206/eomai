# ADR 0197: Native LoRA admission to the existing matched-input diagnostic

Date: 2026-10-05 UTC

Status: source implementation verified; installed native inference and quality pending.

1. Responsibility: extend the existing isolated LoRA evaluation owner with the
   explicit command/result successor `local-image-sdxl-lora-evaluation/1.2`.
   It consumes native-training 1.0 metadata, not a micro-manifest alias. Existing
   evaluation 1.0/1.1 schemas, inference, GPU lease and systemd template remain.
2. Canonical sources: pinned baseline command, native training command, successful
   result and its exact adapter manifest. Orchestrator re-admits both source
   lineages against the same frozen crop-set basis before reading PNG/weights.
3. Identity: command-derived run ID, logical/revision adapter IDs, Artifact
   revision pointers, member byte hashes and semantic hashes remain separate.
   The result and adapter manifest must belong to the same committed revision.
4. Resolution: validate bounded canonical JSON, schemas, hashes, successful
   training/result/manifest relation, base model and permission/chronology first.
   Native TRAIN target admission remains owned by its existing resolver. Every
   baseline reference must be TRAIN. Missing/stale/unknown family fails closed.
5. Access patterns: fixed metadata lookup, set membership, ordered case/seed
   iteration, sorted handoff, idempotent terminal receipt verification.
6. Structures: frozen typed commands/results, closed schema dispatch, dictionaries
   for metadata and crop membership. No new DB, queue, registry, cache or index.
7. Scale: baseline at most six cases/twelve images; native metadata at most the
   existing 200 targets. O(metadata + selected bytes), no training PNG copies.
8. Concurrency: existing exclusive workspace and GPU lock. Only Orchestrator
   publishes; worker reads staged inputs and writes bounded local result members.
9. Dependencies: contracts own pure decoding/provenance; Orchestrator owns source
   permission and full frozen lineage; provider owns staged bytes and numerical
   execution. Share exact adapter material validation, not training source unions
   with unrelated legacy reserved-comparison consumers. No new dependency.
10. Retry/failure: exact same identity replays verified terminal evidence without
    loading the base model or generating. Partial/unreceipted output is not retried
    with a fresh seed. Preserve failed evidence and old exhausted run budgets.
11. Alternative: an operator-only path bypass would hide incompatible training
    schemas; a second numerical runner would duplicate lifecycle and budget code.
    The explicit successor and existing execution owner are the smaller change.

The closed case relation is `LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT`.
Baseline prompts, seeds, conditioning, output geometry and numerical settings are
unchanged, so this first diagnostic isolates the trained adapter. Native-resolution
training does not imply native-resolution inference. The old 832x512 baseline is
reported truthfully; it does not establish reserved-source, four-arm, independent
blind, publication or product quality. Freeze a new bounded experiment before GPU
dispatch; do not spend an already exhausted historical diagnostic budget again.

Required tests: predecessor byte preservation/rejection of the new family;
missing/stale/hash/manifest/model/chronology mismatches; canonical TRAIN lineage
and same frozen basis before media; exact staged set; unchanged prompt/seed output
coverage; success/failure replay without generation; corrupt output rejection;
schema packaging and source-free installed import. Production activation remains
FORBIDDEN until the original goal's quality and Item/HWPX gates are satisfied.

## Source verification

New native consumer fixtures cover 24 cases, including failed terminal replay.
The broad non-live SDXL/control-publication/environment/dependency run returned
1009 PASS and two failures. The image-test environment manifest had 20 older
missing entries plus this new test; all 21 were added and its two tests now PASS.
The remaining failure is the previously documented Orchestrator import of Catalog
planning modules in `source_page_crop_expansion_inputs.py`; it was not suppressed.
Thus 1010 of those 1011 distinct checks are now passing, not a whole-repository
unqualified PASS. Nine changed source modules pass strict focused mypy; ten files
pass Ruff/format, release scripts pass syntax, and diff whitespace is clean.

The existing baseline owner already enforces TRAIN membership before returning
its typed resolution. The duplicate adapter-side partition loop was removed;
native comparison additionally requires exact equality of the frozen basis pin.
The closed evaluation codec centralizes the three supported command/result
families across publication, staging and worker loading. Unrelated legacy spatial
and reserved-comparison training unions were not widened.
