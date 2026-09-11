# Local GPU image-model prompt policy V1

Status: implemented

Last reviewed: 2026-09-11 UTC

## Responsibility and boundary

Catalog deterministically turns the image worker's per-slot drawing description into the positive
and negative prompts sent to the fixed local SSD-1B provider. The worker still decides what must be
drawn. Catalog owns the common renderer style and does not ask another worker or an external model
to rewrite the request.

The two reviewed source files remain byte-unchanged:

1. `config/control-plane/standard-item-v5/references/guidance/content-team-integrated-science-authoring-v05.md`
   at `sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435`;
2. `content/image-specs/kice-integrated-science-illustration-v1.md` at
   `sha256:9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed`.

The first source owns the current item/visual-slot structure and the mandatory team-lead prefix.
That conversational prefix is removed at the provider boundary, while the worker subject's content
and internal whitespace are kept immediately after the model's mandatory style lead. Only the
current IMAGE slot is sent; 25-item batch
layout and unrelated examples are not model input. The second source supplies the common visual
rules. Its request-specific scientific modules remain the worker description or deterministic SVG
overlay; only always-applicable raster rules are compacted into the model policy.

## Canonical identity and pointers

`local-gpu-image-prompt-policy/1.0` is a code-owned derivation pinned to the two source hashes above.
The existing `local-image-generation-request/1.0` remains the cross-service contract. It records
the complete positive and negative prompts, their separate SHA-256 hashes, the immutable model
revision, sampler, seed, request ID, and request self-hash. Request identity also includes the
derived policy revision and both prompt hashes, so a policy change cannot reuse an old workspace.
No new untyped prompt payload is added. A workspace request is temporary materialization; its typed
request and pinned revisions are the reproducible identity.

## Ordered prompt construction

The positive prompt is an ordered immutable tuple rendered as:

```text
Monochrome KICE exam line art on blank pure white canvas, isolated subjects, crisp black outlines,
flat gray or hatching inside objects only, single composition. Subject: <exact worker subject>.
Exact count, position, direction, scale, ratio, geometry, scientific relation. Necessary objects,
wide blank margins.
```

The historical background-only route additionally says that the raster is non-authoritative. The
negative prompt first rejects color and colored/gray/filled backgrounds, borders/frames, gradients,
shadows, gloss, texture, photography, 3D, perspective, scenery, decoration, extra/duplicate objects,
collage, crop, generated text/labels/numbers/symbols/equations/graphs/scales, and watermarks, then
appends the worker's item-specific exclusions. Authoritative labels and exact geometry remain in the
sanitized SVG overlay.

Chromatic directives in worker generation text fail closed rather than competing with the required
monochrome presentation. Black, white, gray, and hatching remain valid. Missing subjects, unsafe
human/photo styles, overlong tokenizer input, or conflicting routes also fail explicitly.

## Access patterns and complexity

Prompt clauses are ordered tuples because order is stable and the provider consumes them once.
Forbidden-style checks use bounded regular-expression/string scans. Assembly and validation are
O(prompt bytes + tokenizer tokens) time and O(prompt bytes) space. Per item there is at most one
typed local-provider request, so a registry or persistent prompt table would add no useful lookup.

## Token, transaction, and retry behavior

SSD-1B has two CLIP encoders, each with a 77-token maximum. Worker content is first and the common
clauses are compact so a normal item-specific description remains untruncated. The provider checks
both real tokenizers before CUDA and rejects any overflow; it never silently truncates a scientific
constraint.

Inference remains outside the Catalog artifact transaction. Request identity, prompt hashes,
provider binding, drawing revision, and fixed seed make retry byte-exact. A conflicting replay fails
instead of overwriting the workspace. Only Catalog validates and commits the resulting artifact to
NAS.

## Simpler alternative and why it is insufficient

Passing the full two documents to CLIP would truncate the subject and most rules. Passing only the
worker sentence reproduced the earlier colored sample because monochrome print rules were absent.
Letting a second LLM summarize the files would be nondeterministic and would violate the local-only
boundary. The pinned ordered derivation is the smallest deterministic form that preserves both the
worker's requested scene and the two sources' always-on visual policy.
