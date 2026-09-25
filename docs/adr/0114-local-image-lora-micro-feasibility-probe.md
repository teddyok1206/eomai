# ADR 0114: Local image LoRA micro feasibility probe

- Status: Accepted for one evaluation-only run
- Date: 2026-09-25 UTC
- Scope: local SSD-1B training feasibility; production activation is forbidden

## Decision

The failed 100-sample crop gate from ADR 0113 remains immutable and correct.  EOM will run one
smaller, separately versioned feasibility probe using 12-18 unique reviewed crop proposals and
exactly 200 optimizer steps.  Its only question is whether a small adapter produces enough visible
movement toward Korean science-assessment illustration style to justify collecting a production
dataset.  It is not a production training dataset, an approval of the pending V1 crop review, or a
replacement for the 100-sample acceptance gate.

The resulting adapter is permanently typed `EVALUATION_ONLY`; neither the current provider binding
nor any production activation contract accepts that state.  A useful result authorizes only a later
dataset-expansion decision.  It does not authorize provider activation.

## Responsibility and system boundary

The Orchestrator-side staging adapter resolves the approved training authorization, immutable crop
proposal set, selected proposal IDs, exact source-page Artifact Revisions, holdout pins, and the
base-model revision.  It writes a bounded workspace and a typed command.  The isolated image
trainer reads only that workspace and the read-only local model store, applies the proposal's exact
crop and OCR redaction boxes, materializes temporary 768x512 samples, trains the UNet LoRA, and
returns a typed local result.  It does not read PostgreSQL or NAS and cannot access the production
provider workspace.

Only the Orchestrator validates and commits the evaluation-only adapter, manifest, and receipt to
NAS.  Temporary crop PNGs and optimizer state are not canonical derivatives and are destroyed after
the evaluation evidence has been committed.  The source authorization permits `LORA_ADAPTER_ONLY`;
therefore the micro probe never publishes a reusable crop dataset.

## Canonical source and revision model

```text
approved training authorization revision
  + immutable crop-proposal-set revision
  + immutable holdout plan revision
  + exact base-model revision
  + immutable micro-probe plan (12-18 selections and captions)
  -> isolated command/run attempt
  -> temporary redacted crop realization (hashes only retained)
  -> evaluation-only adapter revision + worker receipt
  -> fixed base-versus-adapter evaluation
```

The micro plan pins proposal IDs and source anchors; the staged proposal set supplies the immutable
page pointer, crop box, redaction boxes, rights policy, and visual provenance.  The worker result
retains the realized crop hashes and perceptual hashes, but no crop bytes.  Logical IDs, revision
IDs, Artifact IDs, Artifact Revision IDs, and SHA-256 hashes remain separate.

## Access patterns and data structures

The dominant operations are exact proposal lookup, source-page lookup, membership, and duplicate
detection.  Proposal and page lookups use maps; holdout and uniqueness checks use sets.  Exact crop
deduplication is O(n) by SHA-256.  Perceptual deduplication uses the existing four-band Hamming index
and is O(n) expected time at this bounded scale.  Stable output uses tuples ordered by proposal ID.
No database schema or index is added.

## Training and evaluation invariants

- 12-18 selected proposal IDs, at most one per source anchor;
- exact approved authorization and source snapshot from ADR 0113;
- all selected pages, rights policies, proposal hashes, and holdout exclusions revalidated;
- OCR redaction boxes filled before grayscale resize and letterboxing;
- exact and near-duplicate realized crops removed; fewer than 12 remaining crops fails the run;
- UNet LoRA rank 8/alpha 8, batch 1, accumulation 4, frozen text encoders and VAE;
- fp16, AdamW 8-bit, learning rate 1e-4, no horizontal flip, fixed seed;
- exactly 200 optimizer steps and no resumable mid-run checkpoint publication;
- adapter manifest state `EVALUATION_ONLY`, activation policy `FORBIDDEN`;
- identical prompts, seeds, sampler, dimensions, and negative prompt for base/adapter comparison;
- record subject fidelity, exam-style preference, person/text leakage, and nearest-training-image
  similarity before deciding whether to collect more data.

## Transaction, concurrency, failure, and retry

The existing GPU file lock makes training mutually exclusive with image inference.  The plan and
command hashes define one run identity.  The worker writes one exclusive terminal result; a failed
run stays failed and retry requires a new attempt.  Pointer, schema, media, hash, rights, holdout,
redaction, duplicate, runtime, CUDA, loss, or adapter-file drift fails closed.  The production model
and provider binding remain untouched, so rollback is simply removal of the temporary worker unit
and refusal to activate the evaluation-only Artifact.

## Simpler alternative rejected

Lowering the V1 dataset minimum from 100 to 12 would silently change a released production-candidate
contract and could make a micro experiment loadable by the provider.  Duplicating or augmenting the
same few crops to reach 100 would misrepresent dataset diversity.  A separate micro-probe protocol
is slightly more code but keeps the original gate truthful and makes accidental activation
structurally impossible.
