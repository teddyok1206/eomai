# Incremental embedding CUDA Torch package-lock candidates

Reviewed: 2026-10-12 UTC. Target: Python 3.12.13 / CPython `cp312` /
Linux x86_64 / glibc-compatible manylinux / `torch==2.7.1+cu128`.
Status: **PUBLIC_METADATA_VERIFIED / PREFETCH_RAW_SHA_ZIP_VERIFIED / NOT_INSTALLED /
NOT_ACTIVE / CUDA_NOT_VERIFIED**.

Sections 1–6 retain the initial metadata-only review. Section 8 separately records
the later authorized local prefetch inspection; it does not reinterpret the earlier phase.

This is the complete **Torch base-requirement closure**, not a complete EOM runtime lock,
an installation instruction, source authorization, a model result or a GPU capability claim.
It refines [the runtime design](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md#2-패키지-선택-같은-pytorch-release의-명시적-cuda-build).
The protected CPU environment and all other environments remain unchanged.

## 1. Initial metadata-only sources and verification boundary

The [official stable cu128 Torch index](https://download.pytorch.org/whl/cu128/torch/)
advertises the exact wheel URL and SHA-256 in section 4. Its advertised PEP 658
metadata SHA-256 is `e41a1ec38ccc8170c228b57b1432cc7ae03718dd69bb0a72d1fc32707dde1765`,
matching the fetched 29,230-byte
[official Torch wheel metadata](https://download-r2.pytorch.org/whl/cu128/torch-2.7.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl.metadata).

For every other selected wheel, the version-specific official PyPI JSON response in
section 5 provides its filename, URL, advertised SHA-256, byte count, Python constraint
and non-yanked status. Fetching only that exact URL plus `.metadata` verified its
package name, version and base dependencies; section 5 pins each fetched metadata hash.
The 25 selected wheel metadata documents total 115,422 bytes. Only public index/JSON/
metadata requests and a Torch-wheel HEAD request were made in that initial phase; **no wheel body was
downloaded or executed**. Advertised wheel hashes have not yet been checked against
downloaded wheel bytes.

Metadata parsing used the explicit interpreter
`/srv/eom/conda/envs/eom-api/bin/python` and Python standard-library HTTP, email,
JSON and hashing functions. No target package was imported, no pip resolver/install
ran, and no new environment, model, GPU, credential, DB, NAS or Git state was changed.
Installed CPU package metadata was read as untrusted data, not executed code.

The exact download budget is **3,848,835,734 bytes**
(about 3.585 GiB), excluding unrelated model/runtime wheels,
model payloads, unpacked installation size and temporary overhead.
Torch's 1,039,245,529-byte size is from official HEAD `Content-Length`;
the remaining 2,809,590,205 bytes are PyPI file sizes. This is not an installed disk/RAM estimate.

## 2. Preserve the protected CPU common pins

All nine pins below already appear in
[the CPU source lock](../../infra/conda/eom-embedding-experiment.requirements.lock).
Each selected public wheel's fetched metadata is byte-identical to the corresponding
root-owned, non-symlink, non-group/other-writable installed CPU metadata under
`/opt/eom/conda/envs/eom-embedding-experiment/lib/python3.12/site-packages`.
This proves metadata/version agreement, **not installed RECORD or package-file integrity**.

| Package | Preserved version | Protected metadata member |
|---|---|---|
| `filelock` | `3.32.3` | `filelock-3.32.3.dist-info/METADATA` |
| `typing-extensions` | `4.16.0` | `typing_extensions-4.16.0.dist-info/METADATA` |
| `setuptools` | `83.0.0` | `setuptools-83.0.0-py3.12.egg-info/PKG-INFO` |
| `sympy` | `1.14.0` | `sympy-1.14.0.dist-info/METADATA` |
| `networkx` | `3.6.1` | `networkx-3.6.1.dist-info/METADATA` |
| `jinja2` | `3.1.6` | `jinja2-3.1.6.dist-info/METADATA` |
| `fsspec` | `2026.7.0` | `fsspec-2026.7.0.dist-info/METADATA` |
| `mpmath` | `1.3.0` | `mpmath-1.3.0.dist-info/METADATA` |
| `markupsafe` | `3.0.3` | `markupsafe-3.0.3.dist-info/METADATA` |

The CPU Torch `2.7.1+cpu` metadata SHA-256 is
`0464be2f825052a9766185210a6143fbde6762d77cffd1a77d2f8326baf12ae5`.
Its seven base/common requirements match CUDA Torch's seven common requirements.
The CPU's SymPy 1.14.0 satisfies CUDA Torch's `>=1.13.3`; no downgrade to 1.13.3 is needed.
Setuptools is installed as `setuptools-83.0.0-py3.12.egg-info/PKG-INFO`, not
`.dist-info/METADATA`; its bytes still match the official selected wheel metadata.

Keep Transformers 4.56.2, safetensors 0.6.2, tokenizers 0.22.2, NumPy 2.4.6
and the rest of the separately reviewed CPU model/protocol-library closure unchanged.
Their complete wheel URL/hash lock must be merged separately for a full CUDA runtime
release. Do not append this document to the CPU lock as a second Torch requirement.

## 3. Closure, markers and dependency reasons

With `extra=""`, Python 3.12, `platform_system="Linux"` and
`platform_machine="x86_64"`, Torch has seven common direct requirements,
14 exact NVIDIA requirements and exact Triton 3.3.1. Transitive closure adds only
mpmath and MarkupSafe, for **25 distributions including Torch**.

| Additional base edge | Satisfied exact pin |
|---|---|
| SymPy → `mpmath>=1.1.0,<1.4` | `mpmath==1.3.0` |
| Jinja2 → `MarkupSafe>=2.0` | `MarkupSafe==3.0.3` |
| Triton → `setuptools>=40.8.0` | `setuptools==83.0.0` |
| cuDNN → cuBLAS | `nvidia-cublas-cu12==12.8.3.14` |
| cuFFT → NVJITLINK | `nvidia-nvjitlink-cu12==12.8.61` |
| cuSOLVER → cuBLAS, NVJITLINK, cuSPARSE | existing exact pins in section 4 |
| cuSPARSE → NVJITLINK | `nvidia-nvjitlink-cu12==12.8.61` |

No other selected wheel has an active base dependency for this target.
Unrequested Torch `optree`/`opt-einsum`, setuptools/core/test/doc,
NetworkX/default, Triton/build/tests/tutorials, and other extras are excluded.
In particular, do not add SciPy, pandas, cmake, lit, torchvision, torchaudio,
Diffusers, Accelerate or SentenceTransformers through extras.

| Package | Reason for inclusion |
|---|---|
| `torch==2.7.1+cu128` | Same upstream 2.7.1 release as CPU; explicitly selected CUDA 12.8 wheel. |
| `filelock==3.32.3` | Torch base dependency; preserve CPU pin. |
| `typing-extensions==4.16.0` | Torch >=4.10.0 requirement; preserve CPU pin. |
| `setuptools==83.0.0` | Torch requires it on Python >=3.12; Triton also requires >=40.8.0. |
| `sympy==1.14.0` | Torch >=1.13.3 symbolic dependency; preserve CPU pin. |
| `networkx==3.6.1` | Torch base graph dependency, without optional extras. |
| `jinja2==3.1.6` | Torch base template dependency; preserve CPU pin. |
| `fsspec==2026.7.0` | Torch base filesystem abstraction, without optional extras. |
| `mpmath==1.3.0` | SymPy >=1.1.0,<1.4 transitive dependency. |
| `markupsafe==3.0.3` | Jinja2 >=2.0 transitive dependency; CPython 3.12 Linux wheel. |
| `nvidia-cuda-nvrtc-cu12==12.8.61` | Mandatory Torch Linux/x86_64 CUDA runtime-compilation library. |
| `nvidia-cuda-runtime-cu12==12.8.57` | Mandatory Torch Linux/x86_64 CUDA runtime library. |
| `nvidia-cuda-cupti-cu12==12.8.57` | Mandatory Torch Linux/x86_64 CUDA profiling library. |
| `nvidia-cudnn-cu12==9.7.1.26` | Mandatory Torch Linux/x86_64 cuDNN library; also needs cuBLAS. |
| `nvidia-cublas-cu12==12.8.3.14` | Mandatory Torch Linux/x86_64 BLAS library; satisfies cuDNN/cuSOLVER. |
| `nvidia-cufft-cu12==11.3.3.41` | Mandatory Torch Linux/x86_64 FFT library; also needs NVJITLINK. |
| `nvidia-curand-cu12==10.3.9.55` | Mandatory Torch Linux/x86_64 random-number library. |
| `nvidia-cusolver-cu12==11.7.2.55` | Mandatory Torch Linux/x86_64 solver library; needs cuBLAS/NVJITLINK/cuSPARSE. |
| `nvidia-cusparse-cu12==12.5.7.53` | Mandatory Torch Linux/x86_64 sparse library; also needs NVJITLINK. |
| `nvidia-cusparselt-cu12==0.6.3` | Mandatory Torch Linux/x86_64 cuSPARSELt library. |
| `nvidia-nccl-cu12==2.26.2` | Mandatory Torch Linux/x86_64 collective library; not an approval for distributed execution. |
| `nvidia-nvtx-cu12==12.8.55` | Mandatory Torch Linux/x86_64 tracing library. |
| `nvidia-nvjitlink-cu12==12.8.61` | Mandatory Torch Linux/x86_64 JIT-link library; satisfies FFT/solver/sparse requirements. |
| `nvidia-cufile-cu12==1.13.0.11` | Mandatory Torch Linux/x86_64 cuFile library; not permission for NAS/GDS access. |
| `triton==3.3.1` | Mandatory Torch Linux dependency; not permission to use torch.compile or build extras. |

The library wheels are mandatory requirements of the official CUDA Torch build even
when the proposed encoder is eager-only and single-process. Installing them would
not authorize compilation, distribution, direct storage access or wider device access.
They are not system-wide CUDA-toolkit or driver installation instructions.

## 4. Exact wheel URL/SHA candidates

Every URL in the linked lock is from the exact official PyTorch/PyPI release metadata, not an
unbounded latest solver result. These are requirements-file-compatible direct
references with explicit hashes; they cover **Torch only**. Target marker evaluation
has already selected Linux x86_64/cp312 or compatible universal wheels, so this block
must not be used on another architecture/interpreter.

The authoritative 25-entry direct-URL/hash download list is
[cuda-runtime-wheels.lock](../../scripts/embedding/cuda-runtime-wheels.lock).
It is a pure download lock, not installation/activation policy; this document does
not maintain a second URL/hash copy. An authorized owner's later bounded prefetch
can use the explicit interpreter's pip download with `--no-deps`,
`--only-binary=:all:` and `--require-hashes`, validating downloaded bytes before any installation.

## 5. Per-wheel small-metadata evidence and byte budgets

The JSON/index column is the official source of the wheel URL/SHA and size.
For each wheel in section 4, its small metadata URL is the same URL followed by
`.metadata`. Hashes here identify the **metadata document**, not the wheel:
they must never replace section 4's wheel SHA-256.

| Exact package | Official JSON/index | Wheel bytes | Metadata bytes | Metadata SHA-256 |
|---|---|---:|---:|---|
| `torch==2.7.1+cu128` | [source](https://download.pytorch.org/whl/cu128/torch/) | 1039245529 | 29230 | `e41a1ec38ccc8170c228b57b1432cc7ae03718dd69bb0a72d1fc32707dde1765` |
| `filelock==3.32.3` | [source](https://pypi.org/pypi/filelock/3.32.3/json) | 98901 | 2028 | `2d80f43bd905689145c00b3133bc95895d654ced70a96a1802e9237e0d66599f` |
| `typing-extensions==4.16.0` | [source](https://pypi.org/pypi/typing-extensions/4.16.0/json) | 45571 | 3310 | `b05084ca1d50879865178d9fff9fabeab61bdfb1f361bfbde95421ffc8f9be46` |
| `setuptools==83.0.0` | [source](https://pypi.org/pypi/setuptools/83.0.0/json) | 1008090 | 6581 | `26e45e90de763c6938d93d1df2ecd6782a0f1514d41cbd22ebef4e0ab6475771` |
| `sympy==1.14.0` | [source](https://pypi.org/pypi/sympy/1.14.0/json) | 6299353 | 12816 | `b756c2fbfd5be05ac5bdb0ebca61f55618f30f633ed92d88a5687429313a7595` |
| `networkx==3.6.1` | [source](https://pypi.org/pypi/networkx/3.6.1/json) | 2068504 | 6783 | `aca5d94a97d1f70f301d033addb635f6e66be8973a00aba4127637eed2ef316a` |
| `jinja2==3.1.6` | [source](https://pypi.org/pypi/jinja2/3.1.6/json) | 134899 | 2871 | `68c5548fb67c4132a13898d9b31ec50c6bea2abdd915d921f214355c3a6499c8` |
| `fsspec==2026.7.0` | [source](https://pypi.org/pypi/fsspec/2026.7.0/json) | 206583 | 10561 | `88b1657585de14e3bb82aa5278aa9595b30aa4ca74ead073d8950615c808099d` |
| `mpmath==1.3.0` | [source](https://pypi.org/pypi/mpmath/1.3.0/json) | 536198 | 8630 | `44b66ea444b9c0d19ae94815d356bf047ae6b680c19268b5c265687cd6a81406` |
| `markupsafe==3.0.3` | [source](https://pypi.org/pypi/markupsafe/3.0.3/json) | 22947 | 2690 | `12b4cc61a7fa288cf7667ee3f213786d9619db57fb33ff6f934afbcb5c12ec81` |
| `nvidia-cuda-nvrtc-cu12==12.8.61` | [source](https://pypi.org/pypi/nvidia-cuda-nvrtc-cu12/12.8.61/json) | 88024585 | 1684 | `957c238bb9693e02fdd2dd7b9be2d496e9a870398c083bab5aeb04e0df048eef` |
| `nvidia-cuda-runtime-cu12==12.8.57` | [source](https://pypi.org/pypi/nvidia-cuda-runtime-cu12/12.8.57/json) | 954762 | 1684 | `c450a27787fcec867730bc6490c70db58ca4d224915701b46637d5178878e869` |
| `nvidia-cuda-cupti-cu12==12.8.57` | [source](https://pypi.org/pypi/nvidia-cuda-cupti-cu12/12.8.57/json) | 10237547 | 1730 | `38e4e20eb39e418101e0fffca727d3f5756a301b6b4f13f77bf7cfa31460c037` |
| `nvidia-cudnn-cu12==9.7.1.26` | [source](https://pypi.org/pypi/nvidia-cudnn-cu12/9.7.1.26/json) | 726851421 | 1771 | `a9de8685623b400dea03be6c064df033c60639a3f20745dc91e1f4391bd4fe58` |
| `nvidia-cublas-cu12==12.8.3.14` | [source](https://pypi.org/pypi/nvidia-cublas-cu12/12.8.3.14/json) | 609620630 | 1684 | `b77917e0c0c9ba5137fb6ba258270d904645b6338f74f9f3e277ebe32a7a2426` |
| `nvidia-cufft-cu12==11.3.3.41` | [source](https://pypi.org/pypi/nvidia-cufft-cu12/11.3.3.41/json) | 193118795 | 1543 | `51738ef59e7195e47ca3e5ae138511cf771c6cf2fd1643a5c24b9be928e233d8` |
| `nvidia-curand-cu12==10.3.9.55` | [source](https://pypi.org/pypi/nvidia-curand-cu12/10.3.9.55/json) | 63618038 | 1509 | `d077bc8e1f97cd50997a5f537bdfa9e74f4228540274b13e261e577fbbc4295b` |
| `nvidia-cusolver-cu12==11.7.2.55` | [source](https://pypi.org/pypi/nvidia-cusolver-cu12/11.7.2.55/json) | 260373342 | 1628 | `6c29fd45dfde7170242a34761f2b2d4ac1112978e9ea32686f1fe8e1d2c647fb` |
| `nvidia-cusparse-cu12==12.5.7.53` | [source](https://pypi.org/pypi/nvidia-cusparse-cu12/12.5.7.53/json) | 292064180 | 1552 | `9e790d50c456a85161fe267d6aface3fd0700972891b0c1ab3d0f80d4eb53cfc` |
| `nvidia-cusparselt-cu12==0.6.3` | [source](https://pypi.org/pypi/nvidia-cusparselt-cu12/0.6.3/json) | 156785796 | 6768 | `d9ef439af4fab7f6839a03eec5bff1aaed26903ea17a0e75b136c6d3e69c8b11` |
| `nvidia-nccl-cu12==2.26.2` | [source](https://pypi.org/pypi/nvidia-nccl-cu12/2.26.2/json) | 201319755 | 1997 | `b70f61955da2b73ab44dbdf10f5d822baf48ed6665af2f800e27537caf27848b` |
| `nvidia-nvtx-cu12==12.8.55` | [source](https://pypi.org/pypi/nvidia-nvtx-cu12/12.8.55/json) | 89896 | 1645 | `f8b548c1b05e426d5bd9db4dbaab15214ec3a2c809101535ba45156f3d97f3cf` |
| `nvidia-nvjitlink-cu12==12.8.61` | [source](https://pypi.org/pypi/nvidia-nvjitlink-cu12/12.8.61/json) | 39243473 | 1695 | `e492c83bd198e5eeff43a00c98e4e4ae9c5f172c1d8e7969f5c6a8c3bd76ce16` |
| `nvidia-cufile-cu12==1.13.0.11` | [source](https://pypi.org/pypi/nvidia-cufile-cu12/1.13.0.11/json) | 1197801 | 1499 | `f0d564ccf2003f21f1ad93c9c802f892458e02bcdad3bad3da13f508532b2e43` |
| `triton==3.3.1` | [source](https://pypi.org/pypi/triton/3.3.1/json) | 155669138 | 1533 | `34d1dcbf4948d86b691e0dc803a1aa9e9d884af8ea1281394371809b0a8e234d` |

All PyPI selected wheels were non-yanked at review time. PyPI reports compatible
Python constraints (`>=3`, `>=3.7`, `>=3.9`, `>=3.10`,
or `>=3.11,!=3.14.1`), or no constraint, for target Python 3.12.13.
CPython-specific wheels are Torch, Triton and MarkupSafe. The largest required
manylinux baseline is glibc 2.28; actual host ABI and loader acceptance remain
installation gates, not metadata PASS.

## 6. Remaining acceptance gates

An authorized installer may later prefetch only these reviewed URLs into a bounded
protected local wheelhouse, validate exact filenames/byte counts/wheel SHA-256,
inspect archive members and metadata without execution, merge the separate
model/protocol-wheel lock, then perform an explicit offline install without an
arbitrary latest solve. Missing URLs, unexpected size/hash, yanked/replaced files,
new unresolved requirements or platform mismatch must fail explicitly; do not
silently choose another wheel, flavor or version.

Source-only metadata review is **not** installed package/RECORD integrity, `pip check`,
complete runtime-bundle registration, CVE assessment, CUDA import/load, compiled
architecture support, driver/device eligibility, numerical correctness, benchmarking,
resource capacity, sandbox/lease acceptance or default-GPU activation. Those remain
separate opt-in gates in the runtime design. No large wheels/model payloads or
generated installation artifacts belong in Git.

## 7. Offline prefetch inspection boundary

The optional stdlib-only `scripts/embedding/verify_cuda_wheelhouse.py` owns an
offline, read-only download inspection, not installation or runtime admission.
Canonical inputs are the reviewed lock SHA and its exact wheel name/version/SHA
entries; wheelhouse paths are temporary locations, not artifact identity. One
small sanitized report pins that lock and verified wheel hashes, without copying
wheel bytes or metadata descriptions. No DB, network, worker or NAS adapter is used.

Dominant operations are filename membership/key lookup, one ordered pass over
25 wheels, streaming byte hashing and ZIP-member deduplication/lookup. A keyed
lock map and member sets/maps give O(total wheel bytes + ZIP entries) work and
O(lock entries + current ZIP entries) bounded metadata memory. Hold no-follow
ancestor/directory/file descriptors and compare named/FD epochs before reporting;
verification has no transaction or retry/repair mutation. Missing/extra names,
changed files, hash mismatch, unsafe ZIP members or unresolved dependencies fail
explicitly; a retry starts a fresh inspection rather than silently substituting
an artifact. The simpler hash-only check does not protect filesystem races, unsafe
archive names or an incomplete/wrong metadata closure.

Finite packaging gates are at most 25 wheels, 2 GiB raw bytes per wheel, 20,000
ZIP entries per wheel, 2 GiB per declared expanded member, 4 GiB declared expansion
per wheel, 8 GiB aggregate declared expansion, compression ratio at most 100,
128 KiB per root METADATA and 4 KiB per WHEEL member. These are bounded inspection
limits, not the numerical benchmark/capacity thresholds. Only small metadata/WHEEL
members are inflated; this does not claim full ZIP-member CRC/decompression proof.

The download directory must be current-UID-owned mode 0700, with held no-follow
root/current-UID ancestors (root-owned sticky `/tmp` is allowed). Files must be
current-UID regular single-link files, without world-write or setuid/setgid bits,
and retain their named/FD content epoch. Prefetch mode 0664 is reported and accepted
only behind that inaccessible private directory; **it is not protected runtime data**
and does not weaken the encoder/workspace 0600 invariant. An immutable root-owned
quarantine with stricter file modes and fresh hash verification remains mandatory
before any installation/import.

## 8. Later authorized prefetch: exact raw hashes and offline structure PASS

The owner completed a bounded direct-URL pip download with `--no-index --no-deps
--only-binary=:all: --require-hashes` into the fresh private local directory
`/tmp/eom-embedding-cuda-wheels.u9WOCG9U`. That operation used the original raw
download-lock SHA-256
`011c16be625ebb01125c08dfae9f1f927aca9a20903e917df7d512bb94f94e19`.

Removing one accidental final blank line later produced the distinct current source
lock SHA-256
`1c1bf705f0a0af11f30ee669b870a60a786d3faa344b62fe2bc2095d1fd464ba`.
All 25 entries, URLs and wheel hashes are unchanged. SHA-256 of the current lock
bytes plus one LF exactly reproduces the original prefetch pin. The verifier pins
the current source lock and checks that historical equivalence; its receipt preserves
`lock_sha256` and `prefetch_lock_sha256` separately. No earlier pin/receipt was overwritten.

At **2026-10-12T17:32:19.267832Z**, the explicit API Conda interpreter ran the
offline verifier against that exact local directory. Independent streaming raw
SHA-256 verification passed for **all 25 exact filenames**, with the exact total
**3,848,835,734 bytes**. Every wheel's root METADATA hash also matched section 5's
earlier fetched public metadata. Root package name/version, WHEEL tags, base/no-extras
dependency closure, ZIP path/type/duplicate/range checks and declared packaging
bounds passed. Declared aggregate expansion is **6,605,396,372 bytes**; no package
payload was extracted or imported and no full-member inflation/CRC claim is made.

The wheelhouse was UID 1000/mode 0700. All 25 files were UID 1000, regular,
single-link and mode **0664**; that mutable prefetch mode is recorded, not represented
as immutable/root-protected installation data. Held no-follow directory/file FDs,
bounded reads and final named/FD epoch/inventory checks passed. Wheel bytes and modes
were not changed by the inspection.

The sanitized generated report is outside Git at
`/tmp/eom-embedding-cuda-verification.qMqUmXgd/receipt.json`, in a separate
UID-owned 0700 directory with report mode 0600. It contains only expected package
identities, hashes, byte counts, metadata/tags/closure summaries and explicit pending
gate flags, not package code/descriptions, credentials or model inputs.
Report SHA-256 is
`89f5c90bea36aa9859fa7905d69f39307672e935430d94d3a3126e9898f1ff17`;
the inspected verifier source SHA-256 is
`2cab46bc21ad888ca1bf0f27437e0ab0b96fe9e7eb595ed93018e2362e2498d6`.

Source verification of the helper's synthetic-only test suite is **53 PASS**, with
Ruff formatting/lint and strict mypy PASS. Tests cover traversal, duplicate/NUL
names, special/setuid/setgid/encrypted ZIP members, unsupported compression,
decompression/count/metadata bounds, overlapping ranges, wrong metadata/tags,
missing/incompatible dependencies, symlinks/hardlinks/FIFO, unsafe modes, exact
hash/count failures, concurrent growth/replacement and lock/file epochs. The helper
imports only stdlib and performs no network, extraction or package execution.

This closes only this mutable prefetch batch's raw-hash/structure/small-metadata
gate. **Immutable root quarantine, installation, installed RECORD/pip check,
runtime-bundle/model pointer registration, GPU/driver/lease/sandbox acceptance,
encoding/benchmarking and activation remain NOT_VERIFIED/NOT_ACTIVE.**

The subsequent source review adds immediate FD cleanup registration before
directory `fstat`, and attempts every remaining close even if one close fails.
Its synthetic suite is now **55 PASS**, including injected stat/cleanup failures.
The earlier actual inspection receipt/source hash above is preserved as that
execution's evidence; it is not relabeled as execution of the later helper bytes.
