# ADR 0135: Separate assessment style from visual subject grounding

## Status

Implemented and source-verified on 2026-09-27 UTC. Production activation remains gated because the
current science adapter is evaluation-only and its three-seed review forbids global activation.
This decision does not promote that adapter, permit arbitrary Internet crawling, or reinterpret any
released Content Pack, image-result, provider request, or production binding.

## Responsibility and boundary

EOM separates two different image-generation responsibilities:

- an approved local LoRA adapter may influence the black-and-white Korean assessment illustration
  style; and
- a pinned visual-reference bundle may supply the morphology, proportions, viewpoint, and visible
  structure of the requested real-world subject.

The content-team `illustration_prompt`, its exact worker handoff, and the Catalog-owned assessment
prompt policy remain authoritative and byte-stable. A visual reference is a separate conditioning
input. It cannot rewrite, prefix, suffix, translate, summarize, or replace the prompt, and it cannot
carry authoritative labels, numbers, answers, or geometry. Those elements remain in the validated
SVG overlay and editable HWPX content.

Workers do not download files, write NAS, invoke the local provider, or communicate with each
other. A Codex worker may propose a bounded search intent and candidate identifiers. The
Orchestrator resolves that result through one trusted acquisition adapter, validates and normalizes
the selected source, and alone publishes the immutable bundle. The Catalog may later resolve the
approved bundle pointer and materialize only the selected normalized image into the fixed provider
workspace.

## V1 source policy

V1 uses only Wikimedia Commons through the official MediaWiki API. Arbitrary search-engine result
pages, hotlinks, private addresses, redirects to unapproved hosts, data URLs, and worker-supplied
bytes are rejected. The trusted adapter independently verifies page identity, canonical source page,
original-file URL, media type, pixel bounds, content hash, and structured license metadata.

The first release accepts only public-domain or CC0 sources. Public availability is not sufficient.
CC BY and share-alike sources require a later attribution/export contract and are therefore rejected
by V1. Every external file remains untrusted even after license validation.

The worker may propose between one and five ordered candidates. The bundle records all verified
candidate metadata but selects exactly one `PRIMARY_CONDITIONING` reference. Multiple-image model
conditioning, additional providers, and automatic license expansion require additive successors.

## Canonical source and revision model

```text
image worker drawing intent
  -> immutable visual-reference search intent
  -> verified Wikimedia source metadata + downloaded original hash
  -> normalized reference PNG
  -> immutable visual-reference bundle Artifact Revision
  -> reference-conditioned provider request wrapper
  -> local generation receipt + reference-conditioning receipt
  -> validated final image Artifact Revision
```

The external URL is provenance, not identity. Identity is the bundle logical ID and immutable
revision, its typed member pointer, and exact SHA-256. The original source hash and normalized PNG
hash remain separate. A workspace file is temporary materialization and never the canonical source.

## Access patterns and data structures

Dominant operations are candidate lookup by provider page ID, uniqueness checks for canonical URLs
and content hashes, stable ordered iteration, and exact member resolution. Validators use maps and
sets for `O(C)` time and space, where V1 bounds `C <= 5`. One bundle contains one manifest, one
normalized primary PNG, and small source metadata; no database table or search index is justified.
Artifact publication uses the existing Orchestrator file-set boundary.

The search intent stores a sorted unique tuple of concise English query terms. Candidate preference
is an ordered tuple because the worker's ranking is meaningful. The acquisition adapter keeps a map
by page ID and a set of normalized content hashes to reject aliases and duplicates without repeated
list scans.

## Reference normalization and conditioning

The trusted adapter decodes a bounded raster with Pillow under decompression-bomb protection,
applies EXIF orientation, converts it to RGB, strips metadata, fits it deterministically onto an
800x504 white canvas without upscaling, and writes one canonical PNG. SVG, PDF, animation, active
content, embedded profiles, and files outside declared byte or pixel limits are rejected in V1.

The provider wrapper pins the unchanged V1 text-generation request plus:

- the exact bundle and member pointer;
- the primary reference ID and normalized PNG hash;
- `sdxl-img2img/1.0` conditioning;
- a bounded strength selected by the trusted policy, initially fixed at `0.35`; and
- the wrapper self-hash.

The isolated provider verifies the staged PNG before CUDA transfer and uses the installed
`StableDiffusionXLImg2ImgPipeline`. It retains the same model, prompt, negative prompt, seed,
sampler, output dimensions, GPU lease, compositor, and sandbox. The receipt repeats the reference
identity and conditioning policy so a text-only generation cannot be mistaken for a grounded one.

## Transaction, concurrency, retry, and idempotency

Search is read-only and may be repeated, but a published intent pins the proposed candidates. Bundle
identity includes intent hash, verified provider revision, selected source page and file hashes,
normalization policy, and normalized member hash. Byte-identical replay returns the same publication;
conflicting replay fails closed. The generation wrapper includes the exact bundle revision and member
hash in its request identity, so changing a reference always creates a different provider request.

The Orchestrator publishes the bundle as one file-set transaction after all candidates and the
primary member validate. The Catalog does no Internet access while serving an Item. Provider failure
does not modify the bundle or retry with another candidate. A new candidate selection requires a new
intent and bundle revision. Existing V1 text-only requests remain valid and unchanged.

## Failure and security behavior

The following fail before provider execution or Artifact commit:

- unsupported provider, scheme, host, redirect, license, media type, or image encoding;
- private, loopback, link-local, multicast, or otherwise non-public resolved address;
- missing or conflicting page/file/license metadata;
- stale page identity, canonical URL drift, duplicate candidate, or content-hash alias;
- unsafe dimensions, decompression bomb, animation, malformed image, or byte limit breach;
- missing/stale bundle pointer, wrong schema/media/lifecycle, or hash mismatch;
- prompt drift between the wrapped V1 request and the existing content-team contract; and
- reference member or receipt mismatch.

Downloaded files are treated as data, never instructions. Captions, titles, descriptions, EXIF, and
webpage content cannot alter prompts, schemas, sandbox policy, workflow state, or routing. The
provider stays `PrivateNetwork=true` and receives no URL or source metadata beyond the typed pointer
and staged normalized PNG.

## Dependency direction and adapters

Contracts and immutable value models remain in `eom_image_contracts`. Search and HTTP acquisition
are infrastructure adapters behind an application-owned interface. The Orchestrator owns validation,
publication, and workspace materialization. The Catalog owns the provider invocation boundary. The
isolated image provider owns only verified local PNG conditioning and CUDA execution. No domain
package imports HTTP, filesystem, PostgreSQL, NAS, or Diffusers implementations.

Pillow is already a pinned provider dependency. The acquisition environment may reuse its existing
Pillow dependency; no search SDK is added because the official MediaWiki API is a bounded HTTPS JSON
interface. A future provider is a separate adapter selected by a successor contract, not a generic
plugin framework.

## Simpler alternatives rejected

Appending visual descriptions to the prompt would violate the exact content-team prompt invariant
and still lose subject morphology. Allowing the worker to download and pass arbitrary bytes would
bypass rights, SSRF, hash, lifecycle, and Orchestrator-only NAS controls. Using one mutable URL at
generation time would make historical output unreproducible. Training every possible object into
LoRA would mix style and subject identity, require unbounded data, and still generalize poorly to
unseen subjects. The additive bundle plus request wrapper is the smallest design that preserves the
existing prompt while grounding the local model in an exact visual source.
