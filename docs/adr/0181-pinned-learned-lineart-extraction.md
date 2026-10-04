# ADR 0181: Separate original inputs from learned lineart extraction

Status: accepted design; implementation/installation/dispatch are separate evidence gates.
Date: 2026-10-04 UTC.

## Boundary and canonical source

Continue ADR 0180's licensed, converted fine/style-1 extractor. The Orchestrator resolves approved
original TRAIN crop provenance through the existing SDXL source admission; the isolated image
provider reads local staging and one protected model revision. Only the existing Orchestrator
publisher commits output PNGs and a validated receipt to NAS. No new service, queue, DB schema,
external inference API or production binding is introduced.

The original SDXL command and crop Artifact Revisions remain canonical. The additive extraction
command pins that original command, the canonical extractor manifest, the extractor's logical
ID/revision/hash and up to six original case IDs. It does not duplicate prompt text or disguise
derived pixels as approved source crops. A subsequent SDXL comparison must explicitly pin this
new receipt and its conditioning members; old gray-inversion command/result semantics are intact.

## Identities, pointers and access patterns

`imglineartextractrun -> immutable command -> original command/case IDs + extractor revision`
produces a separate result Artifact Revision with raw black-on-white lineart and white-on-black
conditioning PNGs. Original reference SHA is retained per output. Existence, approval/lifecycle,
schema/media/hash, canonical JSON, TRAIN membership and exact original case selection are checked
before staging. Protected model resolution and F32 finite tensor/architecture checks occur before
inference. No implicit latest or replacement model is allowed.

One original command, one extractor, at most six ordered cases and two PNGs/case are the scale.
Case selection uses a dict and ordered immutable tuple; uniqueness uses a set. The existing
control-Artifact resolver gains a bounded batch read for the same Artifact Revision: one indexed
metadata query, one keyed manifest map/revision, then exact member reads. Original SDXL and new
extraction input materialization can both use it. No persistent cache or new index is needed.
Complexity is O(manifest members + selected members + bytes), rather than repeated metadata queries
and manifest scans. Returned bytes exist only at the declared input materialization boundary.

## Transaction, concurrency and dependency direction

Artifact metadata is read in one repeatable-read, read-only transaction; canonical bytes are
hash-checked outside the query without copying binary payloads into PostgreSQL. All pointers and
sizes are admitted before any staged handoff. The existing exclusive filesystem handoff creates
an immutable root-owned input tree and only then gives the image identity access to its workspace.
The same physical GPU lease covers model load and the whole bounded extraction. An additive
oneshot template reuses the existing numerical trainer environment, worker identity, protected
model root and sandbox. There are no worker-to-worker calls or privilege/group additions.

CLI -> extraction application -> pure command/result rules; numerical/filesystem adapters implement
the application boundary. Contracts import no Torch, Pillow, filesystem, SQL or subprocess SDK.
The exact manifest and original command are staged as small immutable metadata, not copied items.
No dependency is added: the numerical adapter reuses the existing pinned Torch, Safetensors,
Pillow and NumPy SDKs in the trainer environment. Torch remains optional outside that adapter.

## Preprocessing and failure behavior

`FIT_RGB_EXTRACT_INVERT_832X512/1.0` contains the RGB original in an 800x500 white centered region
of an 832x512 canvas, preserving aspect ratio and the old diagnostic's fit geometry. The fixed
generator receives [0,1] RGB F32 and returns black-on-white sigmoid lineart. Bounded quantization
produces an 832x512 L PNG; explicit inversion produces the RGB T2I conditioning PNG. No threshold,
denoising or layout change is silently inserted. These are preprocessing outputs, not proof of
scientific correctness or final publication images.

Success requires complete unique ordered coverage, matching original hashes, measured runtime and
declared time/memory budgets. Failure preserves a terminal receipt and an execution-prefix output
set; failure is not relabelled as success. A receipt replay verifies identity/member bytes without
loading weights or invoking inference. Partial unreceipted output is not permission to run again.
Unknown unit state is inspected by its existing identity, never submitted with a new key.

Installation, source/RECORD checks and rollback use the existing bounded trainer release mechanism;
the optional extractor model/template can be left installed but inactive. Operating V6 is untouched.
The simpler alternative is silently feeding a derived PNG into the old original-crop field. That
would misrepresent provenance and alter released semantics. Another generic registry/worker daemon
is unnecessary for these two concrete preprocessing/comparison boundaries.

## Required evidence

Schema2020-12/Pydantic agreement; missing/stale/hash/permission/lifecycle and duplicate-reference
negatives; indexed batch query/linear manifest lookup proof; original TRAIN admission; whole-handoff
exclusivity; success/partial failure/replay/budget tests; exact unit sandbox; non-editable wheel and
protected model installation; one real six-case run and original-resolution own inspection. Own
inspection stays distinct from independent blind review. No automatic operating activation.
