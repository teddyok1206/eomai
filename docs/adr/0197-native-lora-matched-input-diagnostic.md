# ADR 0197: Native LoRA admission to the existing matched-input diagnostic

Date: 2026-10-05 UTC

Status: native four-arm diagnostic technically verified; all24 cells own-REJECTED.

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

## Actual installed diagnostic

Source `ef32aa4a27b9b3b4d0576f61b6b32a797f4b4151` was built from an immutable
archive. Lab contracts/provider only were installed after wheel/installed RECORD,
GPU-lock/quiescence and rollback-wheel checks. Actual source-free `eom-image`
identity imports, old/new schemas and pip check passed. Trainer, numeric dependencies,
units, production binding and five production services were unchanged.

One separately frozen six-generation native run completed in34,810ms, peak GPU
8,328,740,352 bytes. The historical six BASE outputs were revalidated and reused;
no BASE rerun or training update. Conditioning byte hashes match exactly. Actual
installed-role replay preserved33 file identities/sizes/mtimes, with zero model
calls/writes and no Torch import. All19 committed output members re-resolved exactly.

Result `artifact_ce8c3af7155042598652e990191d7c48` /
`rev_8fb939881ca145c6b36822c71d77c7a2`, raw result SHA
`4b4b5b095bcc7f42757b91262afb7acb27cfb38d45ab527500382b395a37e281`.
Own review and twelve text evidence members: `artifact_0d3a22f5cbb5409d84569477c6446e82`
/ `rev_02b69cb6929c4fc0b3c064a0a236e6dc`, `reports/own-review.md`, SHA
`4ad2252d903af8f2721d64705cfd8a42c984f878c3609a5ed8c0cd1ae9a953fa`.

All twelve viewing images were individually inspected and hashes checked. Native
outputs retain gray/grid backgrounds, halos and dark fill; several contours soften.
All six are REJECTED for publication. Midtones increase in5/6 paired cases, while
edge fractions decrease in5/6; these are descriptive metrics, not scientific quality
scores. The native training pilot does not improve this inherited conditioning
configuration enough for use. Do not infer a polarity fix contrary to the already
verified upstream model card, or enlarge training solely because numerical loss is low.
Keep previous zero-strength/negative-clause/spatial controls; the next native-compatible
comparison must isolate conditioning and style on clean admitted inputs. This6/6
budget is exhausted. Goal ACTIVE; full corpus/reserved/blind/Item/HWPX gates remain open.

## Bounded four-arm completion after the six-output diagnostic

The existing zero-strength experiment used the old38-target adapter and three
different cases. It cannot supply the absent native-LoRA-only or base-only cells
for this six-case cohort. Complete the factorial diagnostic using existing contracts:

| Arm | T2I scale | Native LoRA | Evidence |
| --- | --- | --- | --- |
| BASE | 0.0 | absent | six new outputs |
| T2I | 0.8 | absent | reuse accepted historical BASE receipt |
| LORA | 0.0 | strength1.0 | six new outputs |
| T2I_LORA | 0.8 | strength1.0 | reuse the new native comparison receipt |

All six case/source/prompt/negative/seed pins, stack, scheduler,30 steps, guidance7
and832x512 geometry stay fixed. Scale0 is already supported/tested by probe1.0;
native evaluation1.2 already consumes the trained adapter. No schema, core code,
dependency, numerical owner, unit, dataset or production modification is needed.
Freeze/publish exact commands before dispatch; ceiling12 new outputs, one execution
per new arm, no training, no retries or strength/seed sweep. Prior exhausted budgets
remain closed. Parent history is referenced, not regenerated or reinterpreted.

The zero-scaled adapter path is an ablation of T2I residuals in the same pipeline,
not a claim that another plain-SDXL implementation is byte-identical. Verify the
actual installed pipeline multiplication and dependency/source parity before use.
No conditioning transforms or gray pixel editing change. Classify each of the24
cells; own review is not independent. This TRAIN diagnostic is deliberately not
the final24–40 reserved-case/four-family/blind gate. Its result will decide whether
the native style adapter merits clean-input native-resolution follow-up or whether
the next effort must change training data/conditioning rather than repeat this run.

### Four-arm terminal result

Both missing arms completed, exactly12 new outputs and12 reused. All24 were
individually inspected and own-REJECTED: zero-residual outputs lose object/count/
composition, while the conditioned outputs retain gray/grid/halo defects. Native
LoRA reduces measured edges but does not establish better scientific line art.
Installed-role replay had0 model calls/writes;38 committed members and24 viewing
hashes verified. No core/schema/dependency/runtime/production changes were needed.
The pre-dispatch installed-library permission-check failure and corrected operator
are preserved, not hidden. Detailed pointers, per-arm resource evidence and the
next clean-contour/source-initialized direction are in the operations plan's
2026-10-05 06:26 entry. This diagnostic budget is exhausted. Overall goal ACTIVE;
reserved/four-family/independent-blind/Item-HWPX acceptance remains open.
