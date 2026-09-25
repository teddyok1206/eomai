# Local image LoRA pilot status — 2026-09-25 UTC

## Outcome

`STOPPED_BEFORE_DATASET`: the approved internal past-exam source population does not contain the
minimum 100 unique, policy-eligible non-authoritative raster crops required by ADR 0113.

No GPU training was started. No LoRA adapter, training receipt, holdout result, provider binding, or
activation was created. The installed SSD-1B base model and production provider policy were not
modified.

## Immutable inputs

- source target set: 520 occurrence-backed accepted past-exam analyses;
- target-set SHA-256: `sha256:f9d3c3332bf763e70935f7568285c027c2bbf75d63d44be682471d3b676b014b`;
- Graph Revision: `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9`;
- Graph snapshot SHA-256: `sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`;
- training authorization Artifact Revision: `rev_7a39e24f6d1c4079857956b67d181766`;
- authorization member SHA-256: `sha256:cfa7b1ce6c77f5b339284adac27479c3bc995ff0a7075cac5ed501ba6ce7b920`;
- holdout plan semantic SHA-256: `sha256:2be3ff035caa653815c5b7c1134937e776c31d7b15d4ef2942184e3a815b7283e24`.

## Locator and review evidence

- source commit: `ab2d2a563ef0a2c7aef3ce79bc1bd3a8af835db1`;
- locator run: `imgcroplocator_a30b7b2ba2b9f38ca00ea0b000a72ad9`;
- command SHA-256: `sha256:3d53f07628863f0f887ff1b334d2fd224bf86fe0e809650a9e61573464cf929f`;
- unique staged pages: 73;
- locator CPU time / peak memory / swap: 8m 22.388s / 1.8 GiB / 0 bytes;
- proposal anchors / proposals / omissions: 139 / 683 / 68;
- proposal Artifact Revision: `rev_24608be00d5145c8bb3ff6745a2a1ed3`;
- proposal member SHA-256: `sha256:47a296855b2f299ba7f385060efc26e91a8a01524b56ceb469add5e5dea203fb`;
- DRAFT review ID: `imgcropreview_38da90750436aabe525ae0b5ae6fa7b6`;
- DRAFT review Artifact Revision: `rev_a41ea79532d2401195512e6d3e4f6a34`;
- DRAFT review member SHA-256: `sha256:cc9622ff272877e118895b10fd075724060c5ac1058e72f6db5949a51eede1d9`;
- contact-sheet materialization SHA-256: `sha256:b2304424ae960e08c2cab01f2057ec58514a89cdab934be9a12838f928a2d1ac`;
- grouped review boards inspected: 18;
- strict preliminary survivors before duplicate removal: at most 18.

The all-pending DRAFT is preserved as the canonical review boundary. It is intentionally not
rewritten as FINAL. Temporary contact sheets and grouped boards are review materializations, not
canonical sources and not Git content.

## Gate decision

The minimum dataset size is 100 and duplicate removal cannot increase a population. Proceeding
would require weakening a safety rule, fabricating or augmenting samples, or admitting excluded
answer-bearing/authoritative diagrams. All are forbidden by the accepted design.

The next eligible action is a new authorization and source snapshot containing enough separately
approved non-authoritative visual material, followed by a fresh immutable proposal population. The
current run is not retried and its history is not reinterpreted.
