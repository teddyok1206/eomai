# Local GPU image-model prompt policy V1

Status: implemented

Last reviewed: 2026-09-12 UTC

## Responsibility and boundary

Catalog deterministically turns the image worker's per-slot drawing description into the positive
and negative prompts sent to the fixed local SSD-1B provider. The worker still decides what must be
drawn. Catalog owns the common renderer style and does not ask another worker or an external model
to rewrite the request.

The three reviewed source files remain byte-unchanged:

1. `config/control-plane/standard-item-v5/references/guidance/content-team-integrated-science-authoring-v05.md`
   at `sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435`;
2. `config/control-plane/standard-item-v6/references/guidance/content-team-hwp-question-editor-handoff-v1.md`
   at `sha256:6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5`;
3. `content/image-specs/kice-integrated-science-illustration-v1.md` at
   `sha256:9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed`.

The first source owns the item and visual-slot intent. The second owns the HwpQuestionEditor
responsibility split: zero/one/two IMAGE placement, editable panel labels, and separation from
scientific labels. The third supplies the common illustration rules. All three are materialized for
the image worker by the successor control policy. Only one current IMAGE slot's bounded semantic
subject is sent to the GPU; unrelated examples, HWPX panel labels, and other slots are not model
input. Request-specific scientific geometry and labels remain in the deterministic SVG overlay.

## Canonical identity and pointers

`local-gpu-image-prompt-policy/1.4` is a code-owned derivation pinned to the three source hashes above.
The existing `local-image-generation-request/1.0` remains the cross-service contract. It records
the complete positive and negative prompts, their separate SHA-256 hashes, the immutable model
revision, sampler, seed, request ID, and request self-hash. Request identity also includes the
derived policy revision and both prompt hashes, so a policy change cannot reuse an old workspace.
No new untyped prompt payload is added. A workspace request is temporary materialization; its typed
request and pinned revisions are the reproducible identity.

## Ordered prompt construction

For the V6 hybrid route, the positive prompt is deliberately bounded to:

```text
monochrome: <worker-authored alt_text, at most 50 Unicode characters>
```

The ordered fixed negative prompt rejects color, gray background, borders, frames, gradients,
shadows, photography, 3D, perspective, scenery, decoration, extra/duplicate objects, collage,
cropping, generated text, labels, numbers, symbols, and equations. Authoritative scientific labels
and exact geometry remain in the sanitized SVG overlay. `(가)` and `(나)` panel labels remain
editable HWPX text and are neither GPU nor SVG input.

Chromatic directives in worker generation text fail closed rather than competing with the required
monochrome presentation. Black, white, gray, and hatching remain valid. Missing subjects, unsafe
human/photo styles, overlong tokenizer input, or conflicting routes also fail explicitly.

## Access patterns and complexity

Prompt clauses are ordered tuples because order is stable and the provider consumes them once.
Forbidden-style checks use bounded regular-expression/string scans. Assembly and validation are
O(prompt bytes + tokenizer tokens) time and O(prompt bytes) space. Per item there is at most one
typed local-provider request, so a registry or persistent prompt table would add no useful lookup.

## Token, transaction, and retry behavior

SSD-1B has two CLIP encoders, each with a 77-token maximum. The worker's bounded `alt_text` and the
compact common clauses fit without truncating the semantic subject. Full team-lead sources,
`illustration_prompt`, scene constraints, required labels, and SVG remain in typed workflow and
Artifact provenance instead of being truncated into CLIP input. The provider checks both real
tokenizers before CUDA and rejects overflow.

Inference remains outside the Catalog artifact transaction. Request identity, prompt hashes,
provider binding, drawing revision, and fixed seed make retry byte-exact. A conflicting replay fails
instead of overwriting the workspace. Only Catalog validates and commits the resulting artifact to
NAS.

## Simpler alternative and why it is insufficient

Passing the full three documents to CLIP would truncate the subject and most rules. Passing only the
worker sentence reproduced the earlier colored sample because monochrome print rules were absent.
Letting a second LLM summarize the files would be nondeterministic and would violate the local-only
boundary. The pinned ordered derivation is the smallest deterministic form that preserves both the
worker's requested scene and the two sources' always-on visual policy.
