# Installed numerical runtime proof — protocol proposal

2026-10-12 UTC. SOURCE_IMPLEMENTED / NOT_INSTALLED / NOT_ACTIVE / NOT_EVALUATED.
This is the next source-only boundary after the native bundle/backend checkpoint. The
main agent reviewed this note and the draft schema before adapter/model implementation.
No prefix, archive, proof, device capture or permission described here is installed by it.

## Eleven-item boundary note

1. **Responsibility/system boundary.** A narrow Catalog infrastructure observer implements
   `InstalledEmbeddingRuntimeObserver`. It independently resolves a configured immutable
   installation proof, verifies retained numerical wheels and actual installed member/RECORD
   closure, and reads bounded fixed OS identity sources. It grants no workflow/operator/GPU
   authority and never launches, installs, downloads, imports ML or publishes artifacts.
2. **Canonical source.** One root-protected raw archive per wheel SHA is retained after the
   prefetch → root-quarantine validation/install boundary. Installed package files are the
   explicit installation materialization of those archives, not a second model payload.
   The root-reviewed immutable proof binds the exact archive SHA, installed RECORD raw SHA,
   closed installer additions and captured physical identity. Installed RECORD/version alone
   cannot establish a wheel identity. No signatures, PKI, secrets or new registry are added.
3. **Logical entity/revisions.** Proof ID, immutable proof revision, semantic proof SHA and
   canonical raw SHA are separate. Profile selects an owner-defined fixed location, not an
   identity. Archive raw SHA identifies immutable archive bytes; original wheel basename is
   validated metadata. Numerical descriptor SHA remains separate from proof/transport audit,
   GPU UUID/PCI/boot identity, full environment audit and unrelated source/GUI/platform release.
4. **Pointers/checks.** Root configuration supplies the exact proof pointer and profile; no
   worker request may supply a path, role, archive, expected descriptor or alternate prefix.
   Verify JSON Schema 2020-12, frozen Pydantic closure, canonical bytes/raw/semantic SHA,
   profile, exact numerical library set, metadata identity, archive ZIP/RECORD closure,
   distinct canonical zero-byte real ZIP directories that are ancestors of regular files,
   bounded compressed WHEEL/filename tag expansion with exact expanded-set equality,
   installed RECORD/member bytes, no editable source, protected ownership/modes/links,
   named/FD ancestor identity and actual Python/prefix/OS/hardware/driver/build read-back.
   A proof's configured raw pin is admission input, not a self-authenticating JSON claim.
5. **Dominant access patterns.** One immutable proof lookup; archive/distribution/member
   key lookup; streaming byte verification; sorted metadata; then immutable epoch checks.
   Fresh process admission verifies once; repeated backend observations do not reread every
   wheel/member or reparse RECORD. Fixed small OS observations remain live rather than cached.
6. **Data structures/indexes.** Frozen proof/pointer/library values, dictionaries keyed by
   archive/installed member and sets for uniqueness/closure; ordered tuples for reproducible
   results. Directory coverage uses one pending-directory set and regular-file ancestor
   membership, not a retained set of every possible path prefix or repeated directory/file scans;
   retain file/directory epochs. No DB index, runtime Git lookup, shared mutable
   cache, plugin framework or additional scheduler/queue is introduced.
7. **Scale/complexity.** Proof raw bytes ≤128 KiB, installed/wheel RECORD ≤8 MiB, metadata
   ≤128 KiB, ≤20,000 entries per wheel, archive/member ≤2 GiB and expanded wheel ≤4 GiB;
   actual declared sizes further bound all reads. Exact CPU set has five distributions and
   CUDA twenty. Initial verification is O(archive + installed bytes + members), streaming
   with ≤1 MiB chunks; later validation is O(member count) stat/FD checks and bounded OS
   reads. ZIP directory allocation must itself be bounded before parsing. Directory checks
   are O(total bounded path components), with O(entry count) retained sets. No binary payload
   is retained in DTOs/DB. Hashing cost is measured later, not optimized by weakening proof.
8. **Transaction/concurrency.** No DB transaction or cross-worker operation. Installer
   acceptance/proof pinning is an owner release boundary after independent closure review.
   Keep ancestors/target identities stable while verifying; retain immutable epochs for
   subsequent observations. CUDA hardware observation happens only after the owner has
   provided the validated physical ownership handle; this observer never acquires/releases it.
9. **Dependency/adapter ownership.** The new Catalog adapter depends on contracts/stdlib
   filesystem/ZIP/CSV/AST/metadata facilities, not image services or private source scripts.
   Reuse the supported bounded protected metadata seam where applicable, but retain a narrow
   streaming/ancestor-FD adapter for multi-GiB installed files. The image wheel verifier's
   role/source rules, packaging dependency and 256 MiB limit are not compatible runtime APIs.
   Full-prefix/interpreter/systemd/device-DAC/network/auth audit remains the launch verifier's
   independent responsibility; successful numerical closure does not replace that audit.
10. **Failure/retry/idempotency.** Missing/stale/changed/schema/raw/semantic hash, wrong
    profile/prefix/distribution, duplicate/missing member, ZIP limit/path/link/RECORD failure,
    unauthorized generated file/pyc/editable source, CPU heterogeneity, absent/wrong driver or
    captured GPU UUID/PCI/boot mismatch fail with static codes. No latest, version-derived
    wheel SHA, automatic archive download, implicit fallback or mutable repair. Re-observation
    reuses the exact snapshot; a new proof revision requires fresh owner admission.
11. **Simpler alternative.** Reading package versions and returning the configured descriptor
    merely echoes claims; RECORD alone can be rewritten with installed bytes. Retaining raw
    reviewed archives gives reproducible independent byte closure without inventing signed
    entry manifests. A narrowly closed proof plus initial verification/epoch reuse is smaller
    than a generic install-proof framework or a second release system.

## Owner-fixed locations — proposed, not installed

Profiles approved for the proposal:

- `CPU_INDEX_FP32`: `/opt/eom/conda/envs/eom-embedding-index-cpu`
- `CUDA_INDEX_FP32`: `/opt/eom/conda/envs/eom-embedding-cuda`

The historical `/opt/eom/conda/envs/eom-embedding-experiment` is never modified or admitted
under these profiles. Exact CPython 3.12.13/Linux x86_64 is required. Proposed proof root is
`/opt/eom/embedding-runtime-proofs/<proof_id>/<proof_revision_id>/proof.json`; archive root is
`/opt/eom/embedding-runtime-archives/<raw_sha_hex>/<original_wheel_basename>`. Owner installation
configuration derives these paths; proof JSON contains no absolute location or authority.
CPU/CUDA common wheels reference the same archive rather than retaining profile duplicates.
Root retains accepted archives for inspection/rollback; obsolete mutable prefetch is removed
only after root acceptance. Neither action is part of this source implementation.

## Exact numerical closure, separate from complete environment audit

CPU contains exactly `numpy==2.4.6`, `safetensors==0.6.2`, `tokenizers==0.22.2`,
`torch==2.7.1+cpu`, `transformers==4.56.2`. CUDA replaces Torch with `2.7.1+cu128` and adds
the fourteen exact `nvidia-*` distributions plus `triton==3.3.1` from the reviewed CUDA lock.
The draft schema fixes all twenty name/version pairs. This intentionally conservative CUDA
closure includes bundled numerical/runtime libraries even when eager inference does not call
every component. It does not permit compile/distributed/storage capabilities.

All other runtime/protocol dependencies and interpreter/shared-system libraries still need the
independent complete installation audit. Its source/transport/prefix hash is not substituted for
this numerical fingerprint, and unrelated GUI/Slack/platform code does not invalidate vectors.
An environment audit does not allow the observer to omit NumPy/NVIDIA/Triton numeric pins.

## Archive ↔ installed mapping and closed installer additions

Archive entries are safe relative POSIX names; reject duplicates, traversal, absolute names,
backslashes, encrypted entries, symlinks/hardlinks, unsupported archive layout and bounded ZIP
bomb/central-directory violations. A unique `.dist-info` root, exact METADATA Name/Version and
WHEEL identity/tags are checked; wheel RECORD's member set, SHA/size and self-row rule are
verified against archive members. Do not extract the archive or import its code.
Canonical distinct zero-byte real directory entries are permitted only when they are ancestors
of actual regular archive files. Directory links, nonzero bytes, duplicate normalized targets,
file/directory collisions and unrelated/empty directories fail closed. RECORD may omit those
directory entries only: its exact regular-file set, self-row and every non-self SHA/size remain
unchanged. Directory entries never become installed payload/hash allowances or extracted files.
WHEEL `Tag` values and the filename use the same
[PEP 425 compressed-tag-set spelling](https://peps.python.org/pep-0425/#compressed-tag-sets).
Expand each valid three-part dot-separated value with the same stdlib Cartesian product, then
require exact expanded-set equality; never accept an arbitrary subset or normalize architecture
or platform aliases. Before expansion, cap 64 fields, 255 characters per field, 16 alternatives
per component, 64 characters per atom and 128 aggregate expanded tags. Empty/malformed/duplicate
atoms, raw fields or overlapping expanded fields fail closed. No wire schema or dependency changes.

Site-packages payload maps by exact wheel relative name. Unsupported `.data` relocation fails
closed rather than inventing a target mapping. Actual accepted numeric archives must demonstrate
this layout before activation. Installed RECORD is independently raw-pinned and parsed once;
all installed targets normalize inside the selected fixed prefix before no-follow FD resolution.
No raw RECORD `../../../` fragment is ever passed to `open`; only verified canonical prefix-
relative targets are dereferenced. Archive members other than RECORD must match installed bytes.

Only the following extra installed files are permitted, with no arbitrary path/hash allowlist:

- `<dist-info>/INSTALLER` with exact `pip\n` bytes;
- optional `<dist-info>/REQUESTED` with exact empty bytes;
- optional `<dist-info>/direct_url.json`, independently raw-pinned and constrained to the exact
  retained archive URI/hash, with no editable/directory/VCS/unknown fields;
- console scripts with fixed safe names derived from the verified wheel's `[console_scripts]`
  metadata, installed only below the fixed prefix's `bin`, raw-pinned, and validated against the
  reviewed deterministic installer wrapper template/shebang/entry point (never executed).

The proof records presence/raw hashes only for that closed set. An installed RECORD row cannot
authorize another file, unregistered bytecode, dynamic import hook or different entry point.
New successors install `--no-compile`; launcher uses isolated/bytecode-disabled execution.
Legacy CPU installation is unchanged. Installer-generated RECORD bytes need not equal wheel
RECORD bytes, which is why both closures are verified instead of comparing the two blindly.

## Concrete read-back without ML/GPU execution

- Actual Python/version/platform come from the running interpreter; exact selected prefix and
  protected interpreter identity are checked. Wheel METADATA and installed metadata must agree
  with independently verified archives, not just `importlib.metadata.version()`.
- Parse the protected installed `torch/version.py` with a bounded AST constant-only reader;
  require the unique reviewed `cuda`/`__version__` constant assignments to match installed
  distribution identity and CPU-null/CUDA-12.8 build. Do not `exec`, `eval` or import Torch.
  The existing backend independently reads the actual imported build again after ownership.
- CPU reads fixed bounded `/proc/cpuinfo`, requiring all visible processor entries to agree on
  vendor/family/model/stepping. Proposed descriptor hardware spelling is the canonical string
  `<vendor> family <n> model <n> stepping <n>`; this fits the existing descriptor contract without
  silently removing punctuation from a marketing name. Heterogeneous/unsupported data fails.
- CUDA reads fixed bounded `/proc/driver/nvidia/version`, the owner-pinned single GPU's proc
  information and fixed boot ID. Actual driver/model/UUID/PCI/minor/boot identity must match the
  immutable root capture in the proof. PCI path is derived only from its validated captured
  identity and owner profile, never a request. Compute capability is pinned by that independent
  owner capture and rechecked by the actual CUDA backend; it is not inferred from model name,
  `nvidia-smi`'s advertised CUDA version or a worker descriptor. Missing owner capture denies
  construction. A reboot/rebinding requires new owner capture/proof admission, not latest lookup.

Root capture itself remains an explicitly approved installation/admission action. This source
protocol neither performs a GPU query nor claims that a capture exists. Relevant installed
encoder/L2/f32 code remains independently hashed by the existing backend; full transport-code
RECORD/prefix proof remains separate from numerical library archive identity.

## Draft contract and focused test recipes

`schemas/knowledge/embedding-installed-runtime-proof-v1.schema.json` proposes one immutable proof
and one owner-configured pointer. After main review, add the packaged mirror/registration and
frozen models before adapter behavior. It includes no executable/source blob, model weights,
arbitrary path, authority or activation field. Stable sorted uniqueness/canonical semantic SHA
checks remain model-level invariants in addition to JSON Schema 2020-12 shape/closure.

Focused synthetic recipes before any live gate:

- schema 2020-12/mirror/hash, frozen bypass, exact CPU5/CUDA20 sets/versions, missing/duplicate
  numeric wheel, wrong profile/Torch flavor, wrong proof revision/raw/semantic SHA;
- actual raw archive mismatch despite matching version/RECORD, modified installed bytes plus
  rewritten installed RECORD, missing/extra/duplicate archive or installed member;
- zip-bomb bounds before allocation, unsafe ZIP/CSV paths, duplicate CSV rows, .data/encryption/
  link/type rejection, permission/owner/ancestor/FD replacement, missing/stale archive;
- zero-byte canonical file-ancestor directories with unchanged exact file RECORD closure;
  duplicate/link/nonzero/noncanonical/unrelated directories and file/directory collisions;
- equivalent compressed versus expanded WHEEL tags, exact-set subset/architecture rejection,
  malformed/duplicate variants and string/component/aggregate bounds before Cartesian allocation;
- legal INSTALLER/REQUESTED/direct-URL/derived wrappers; unknown generated files, arbitrary
  script names/targets/statements, editable source, wrong URL/archive hash and pyc rejection;
- one initial streaming verification then epoch-only re-observation; file/path/code drift;
  Python/prefix/CPU heterogeneity, changed driver/GPU UUID/PCI/boot/captured capability denial;
- no Torch/Transformers/NumPy import, subprocess/network/DB/NAS/Git/install invocation, or
  request descriptor/hash echo. Gate tests use protected synthetic local archives only.

Real raw wheel closure, protected prefix/receipt generation, full environment RECORD/pip check,
device capture/sandbox/lease migration and numerical CPU/CUDA execution remain separate opt-in
owner gates. Synthetic proof PASS alone cannot satisfy installation or default-device activation.

## Source checkpoint and explicit installation limitations

The approved schema has an exact packaged mirror and additive Catalog registry entry; historical
schema bytes/digests/count baselines remain unchanged. Frozen models precede the new numerical
distribution, protected-file, fixed-OS-identity and configured-observer adapters. Only small
synthetic local wheels/proc surrogates were executed as tests; no ML package was imported or model,
GPU, network, database, NAS, installer or service-unit action was taken.

The initial observer verifies complete archive/installed member bytes and closes the covered
numeric namespaces (including unregistered-file/bytecode denial). Re-observation checks retained
file/namespace epochs plus live interpreter/OS identity, without parsing or hashing immutable
distributions again. Relevant encoder/L2/f32 implementation SHA is still independently resolved by
the existing backend. Python executable ownership/identity is checked here; its full byte proof,
all non-numerical packages, ABI/GLIBC, loader/environment policy and whole-prefix protection remain
the launch verifier's separate acceptance boundary.

Two explicit distlib console-wrapper byte recipes are supported with the exact fixed
`bin/python3.12` shebang. A different installer wrapper, unexpected `.data` layout, invalid ZIP
directory/comment/ZIP64, unsupported tag, existing pyc or direct-URL quarantine URI fails closed.
Compatibility with accepted installer additions and the full runtime must still be checked by
the owner before installation; source and archive inspection do not prove an installed prefix.
CUDA capability remains independently root-captured and is re-read by the actual CUDA backend;
fixed proc observations check driver/model/UUID/PCI/minor/boot only and do not themselves prove
kernel capability, device DAC, driver execution, GPU cleanup or complete sandbox isolation.

## Actual CUDA preinstallation archive inspection — not installed proof

The 2026-10-12 UTC read-only diagnostic held bounded no-follow FDs, matched all twenty-five
raw SHA pins in `scripts/embedding/cuda-runtime-wheels.lock` (3,848,835,734 bytes), bounded
central bytes/count before ZIP allocation, and streamed numerical member RECORD hashes/sizes.
Its private temporary receipt is `/tmp/eom-cuda-layout-inspection.km2Qk8U5/layout-report.json`,
raw SHA `8b02291cbfd7c85d2d10be0fccd8db875d30a8d016d7226673923592fd79f944` (16,585 bytes).
This receipt is diagnostic evidence, not root installation authority or an installed runtime proof.

- `torch-2.7.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl`: 492 zero-byte directory entries
  and 11,010 regular files; only directories are absent from wheel RECORD.
- `triton-3.3.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl`: 33 zero-byte
  directory entries and 345 regular files; only directories are absent from wheel RECORD.
- Both sets of directories are actual-file ancestors with no file/directory collision; every
  non-self regular file SHA/size, metadata identity and WHEEL tag matches. NVIDIA14 match the
  checked layout. All sixteen numerical archives have no local/central ZIP64, comments, `.data`,
  bytecode or excessive (>100) compression ratio. CPU/common wheel layout is not yet inspected.
- `nvidia/__init__.py` is shared by thirteen NVIDIA archives with identical SHA/size; the existing
  verified snapshot identity permits identical references and rejects differing bytes. The
  `nvidia-cusparselt-cu12` archive instead owns the separate `cusparselt` namespace.
- Torch declares `torchfrtrace=tools.flight_recorder.fr_trace:main`, but neither
  `tools/flight_recorder/fr_trace.py` nor its package `__init__.py` exists in wheel/RECORD.
  That unused upstream CLI is broken by this archive's own metadata; do not alter wheel bytes,
  execute it, or claim it works. Torchrun and Triton's proton/proton-viewer module files are present.
- `numpy==2.4.6`, `safetensors==0.6.2`, `tokenizers==0.22.2`, `transformers==4.56.2` and
  CPU `torch==2.7.1+cpu` are **MISSING** from that prefetch. Its nine transport-only distributions
  are outside the numerical fingerprint and do not fill those missing pins.

The narrow unreleased source compatibility change preserves proof schema 1.0 and exact file
closure; it permits only the canonical ancestor directories demonstrated above. No archive,
installed prefix, wrapper, protocol authority or device admission is changed by this source work.

## Shared numerical/CPU Torch archive follow-up — pre-tag-fix diagnostic

The read-only actual common4 plus CPU Torch5 diagnostic matches five exact raw archive pins:
207,848,097 bytes (shared numerical archives 32,014,410 and CPU Torch 175,833,687). Its private
mode-0600 receipt `/tmp/eom-embedding-common-layout.zT2tpuxQ/layout-report.json` is 6,703 bytes,
raw SHA `034d2544de1625974e426f207f34d6da0955a2dd944a37bb46044df859a23305`. Preserve it as the
pre-tag-fix diagnostic; it is not relabeled as source/installed/runtime PASS.
Every regular-file RECORD hash/size and METADATA identity matches. NumPy has 118 and CPU Torch
492 zero-byte S_IFDIR/CRC-zero ancestor directories with no collision or unrelated directory;
the approved narrow directory rule covers those shapes. NumPy f2py/numpy-config, both
Transformers CLI and CPU torchrun module targets are present; CPU torchfrtrace has the same
unused absent upstream `tools.flight_recorder.fr_trace` target. Actual CLI/wrapper execution and
installation remain unverified. The five archives have disjoint numerical namespace roots.

`safetensors-0.6.2-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` has one WHEEL line:
`Tag: cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64`. This is a compressed triple, not a
semantic platform-alias mismatch: both spellings expand to exactly
`cp38-abi3-manylinux_2_17_x86_64` and `cp38-abi3-manylinux2014_x86_64`. The unreleased observer
previously compared raw WHEEL lines with expanded filename tags. The narrow source correction
expands both equally under the bounds above, preserving exact target/identity closure. Do not
change the public wheel, infer its raw SHA from a version, or substitute a different archive.

Compressed-tag source gates: **117 focused proof/observer/distribution tests PASS** and
**520 embedding source regression tests PASS**; scoped Ruff lint/format and explicit API/core
strict mypy on the changed module/tests pass. Source tests are synthetic and include the actual
safetensors compressed `cp38-abi3` spelling plus bounded before-product rejection. No new
dependency, schema byte change, installed runtime test or numerical execution is implied.
