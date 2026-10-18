# 증분 임베딩의 CPU/GPU 비교·격리 runtime·기본 device 전환

작성일: 2026-10-12 UTC. 조사 기준 source: `165b0214a8c8812fe5e4d24e5a8b266ea345dbb6`.
상태: **구현 설계 / NOT_INSTALLED / NOT_ACTIVE / NOT_EVALUATED**.
이 문서는 모델·wheel 설치, 실제 인코딩, 운영 권한·DB 변경이나 GPU 활성화의 증거가 아니다.
[상위 설계 §8.1](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md#81-cpugpu-비교와-기본-device-결정--사용자-추가-요청)과
[native 실행 경계](INCREMENTAL_EMBEDDING_EXECUTION_BOUNDARY.md)를 구체화한다.
GPU가 동일 입력 비교에서 우수하고 모든 gate를 통과하면 **기본 활성화까지가 목표**다.
비교만 완료한 상태를 요청 전체 완료로 보고하지 않는다.

### Actual coordinated image installation —2026-10-17

The opening status describes the original design snapshot, not today's whole goal.
The image migration subset is now **INSTALLED_RELEASED / MODEL_LIFECYCLE_NOT_ACCEPTED**.
At this checkpoint both fixed image Python3.11 prefixes contain the reviewed1a5c6b86
EOM wheels; all19GPU templates, the fixed bootstrap and root guardian entry/template
are installed. The protected guardian owner remains1031a232. The native e5owner,
c499numerical prefix, embedding CPU default, model binding and historical failures
were not changed by this operation. No model/tokenizer/forward ran in this step.

The operation retained the original26templates and EOM namespace/metadata/console
snapshots before entry fencing. All26prefix consumers were fenced, actual units
drained and the existing legacy/shared physical locks held while permissions,
EOM-only packages and the19unit set were changed. Scoped permission preparation
completed376members/349protections/12private metadata entries; original shared
Conda metadata inodes remain in the protected recovery workspace. No external
library was reinstalled and no account gained permanent GPU group membership.
Current image fences are removed; successful source/wheel/installed checks are
separate from actual image lifecycle acceptance, which remains pending.

Exact operation locations, not product Artifact identities:

- root release:`/opt/eom/image-joint-runtime-releases/imagejoint-a610b0c7`;
  `prepared.json`, `physical-drained.json`, `dependency-preflight.json`,
  provider/trainer package intent/result pairs, `installed-fenced.json`,
  `apply-result.json`, `worker-access-result.json`;
- scoped permissions:`/opt/eom/image-runtime-preparations/imageprep_a610b0c7f2e1c2db62242cd5f17674e4/permissions`;
- operator receipts:`/tmp/eom-image-joint-release.FLrlFoWI`;
- installed configuration raw SHA:
  `a53cf55fde2e92de7f565eadcfa6f507fe13617b5b3d72e318ad7e60c263ed53`;
  bootstrap raw SHA remains`7edb475db14b0e23d6a820781fee3813c7714cbe250ebd314b2abceec53b4cd7`.

Three failed preparation/dependency outcomes are preserved, not relabeled: private
wheel staging0400instead of required0600(before live mutation); a33-character
recovery-folder spelling instead of32(before permission mutation); and the existing
Conda`python3.1 -> python3.11`alias causing lexical double-counting(after complete
permission preparation but before pip). Read-only state/byte/epoch observations
established each exact resume boundary. Permission preparation and package installs
were not blindly replayed. The alias finding yielded common verifier398f2c71,
85focused tests/strict typing/Ruff/shell gates PASS and four successor helper pins.
It resolves only to the fixed protected Python3.11site; distinct/escaping sites
remain denied and the actual Conda aliases are retained.

Post-install actual UID984/GID980/ephemeral group974 checks in both prefixes passed
bootstrap read, protected lease import and expected BUSY against the root-held same
shared lease; no Torch/Transformers/Diffusers/image modules were imported. This
probe caught the new root entry directory's creation umask077masking intended0755;
only that exact newly created directory was corrected to0755with preserved intent
and inode checks. Future installation must explicitly set/check directory modes,
then test actual worker UID traversal, not infer it from root-only reads.
These are file-access/mutex checks, **not** provider/trainer model success,
crash/timeout/retained-store cleanup acceptance or six frozen CPU/CUDA comparisons.
Those gates and actual C1–C5 consumers remain required before whole-goal completion.

### Actual lifecycle follow-up — root namespace and console entry

The first dedicated OS-only invalid-input case failed acceptance. The root guardian
exited226/NAMESPACE because the optional`/srv/eom/models/image-style`child does not
exist. Separately, the main provider exited0without parsing the deliberately invalid
input: its console module exposes`main()`but has no`if __name__ == '__main__'`guard.
The bootstrap's`runpy.run_module`therefore imported definitions without executing
the worker. No Job/Artifact or product success was registered by this OS probe.
The earlier UID/lock check did not cover CLI dispatch and is not reinterpreted as
runtime success. Original failed test and guardian histories are retained.

The correction keeps the existing closed three-role mapping and pre-import signal
mask, imports the selected CLI and calls its console`main()`exactly once. Console
errors propagate. Root guardian denies the existing`/srv/eom/models`parent instead
of enumerating a possibly absent child; future children are also inaccessible,
without suppressing a missing-path error globally. No schema, model, owner package,
numerical prefix, third-party wheel or authority change is required. Synthetic
tests now assert actual MAIN execution for all three roles and console failure
propagation; related254tests and strict2entry scripts PASS.

Current repair boundary: all26prefix entry fences are installed while the corrected
bootstrap, guardian-template and exact installation hashes are prepared. The first
no-op OS probe's true process outcome remains SUCCEEDED, but its acceptance is FAIL;
it must not be relabeled an expected invalid-input failure. The failed guardian is
not restarted. A fresh changed-source negative case is required after installation.
The original full-release snapshots and known failed smoke remain recoverable.

The source-corrected no-model invalid-input case then passed actual root namespace,
CLI failure, no-ACK/store0 retirement and preservation of the other root-held GPU
lease. Its journal also established that systemd's implicit per-template slice put
the image PID below`/system.slice/system-eom…slice/<unit>`, whereas the existing
ready/terminal/resource contract requires`/system.slice/<unit>`. Before any retained
case, all19main templates and the root guardian explicitly select`Slice=system.slice`,
matching the already-installed native CUDA probe. This changes only unit placement;
the actual `/proc`/cgroup checks, resource limits, UID and shared inode invariants
are not loosened. The all19source gate now requires this explicit placement.

### Retained handshake and explicit fdstore release — source correction

The first retained, deliberately missing-model OS case failed before root ACK with
`IMAGE_GPU_UNIT_ACK_SIGNAL_NOT_RESERVED`. No real model/Artifact was authorized.
A separate non-root own-child kernel reproduction established that blocking
`sigtimedwait(...,30)`temporarily removes the awaited bit from observable`SigBlk`.
The bootstrap reservation itself was not missing. Weakening root's thread-mask
check would hide this mismatch. The standalone lease now consumes with zero-time
`sigtimedwait`and bounded50ms sleeps until the same30sdeadline; before ACK the mask
remains observable. Sender UID0/PID/signo and pre-existing-pending checks stay strict.
An actual own-child`/proc`test observes the blocked mask and rejects a real non-root
signal; mocks alone are not used as proof of kernel behavior. This adds no thread,
dependency or generic event framework: ≤600short polls/30s, O(1)space, at most50ms
additional ACK observation latency, only before model work.

The failed case retained its PID1 descriptor as intended. Actual stop did not free
it: installed`systemd.service(5)`documents`FileDescriptorStorePreserve=yes`keeping
the store until collection or explicit`systemctl clean --what=fdstore`. After exact
MainPID0/empty cgroup/no GPU clients/no ACK checks, an explicitly recorded recovery
reset/cleaned only this no-model OS case; same physical inode reacquisition passed.
Original FAILED outcome and absent READY remain unchanged; no fabricated observation,
new Job, model retry or automatic retirement PASS is recorded. All26image entry
fences remain for the reviewed successor installation.

The existing lifetime owner now distinguishes a stopped unit from a retired one
with a small frozen internal value, not a new worker message/registry. It requires
no queued Job and empty ControlGroup. After the same outcome-specific stop/reset,
store1is revalidated against the original retained resources/device/invocation and
idle GPU, then only that unit's fdstore is cleaned. Store0needs no cleanup. Final
same-inode acquisition and postchecks still decide retirement; unleased exits must
never inspect/clean another holder. One durable retirement intent precedes both
effects, uncertain stop/clean is not replayed, and read-only recovery never performs
cleanup. Source fixtures now model Preserve=yes retaining store1across stop/reset,
including timeout/nonzero clean failures and actual completion followed by read-only
recovery. Identity, source/template/Artifact pins, existing immutable records and
dependency direction remain unchanged. No DB/schema migration, queue or framework
is added. Implicit stop-release and blocking-signal wait are the simpler alternatives
but contradicted the actual OS evidence.

Related379source tests PASS13.96s and strict4source files PASS. New standalone
lease wheel and root lifetime owner installation/selection plus a fresh actual
retained case are still required. The c499numerical prefix must not be rebuilt for
these image-lifetime changes, and source PASS is not six CPU/CUDA model comparisons.

Candidate checkpoint: standard provider/trainer builds and platform wheel/RECORD
inspection completed at`e2326626aed396b3ccfd4d759a834a6e0d987794`. The canonical
new standalone lease wheel SHA is
`f527cc610b7df2a384e40f450d5758a87ad76ff9684a778201a43b60d4593763`;
both builds produced the same bytes. The new root owner was actually installed at
`/opt/eom/embedding-owner-releases/e2326626aed396b3ccfd4d759a834a6e0d987794/site-packages`
using the existing protected installer. Platform/API-contract raw wheel SHA are
`b9e2baac62db98560b32db9498b7e72f108893ba2ea43d3c95ae5d70f1603406`/
`1a2d3f349100a51dff45960d3a6eaf03e60f7d4b81a83cc1dbd9481863e966ef`.
This is INSTALLED_NOT_SELECTED; image worker lease replacement and exact root
entry/config selection are pending. The source fixed entry now explicitly pins
this reviewed owner, never latest. Old1031owner/nativee5/c499prefix remain intact.
Changing this administrative entry requires no numerical rebuild or model rerun.

### Actual corrected retained negative gate —2026-10-17

The successor is now **INSTALLED_SELECTED_RELEASED** for the image guardian only:
owner`e2326626aed396b3ccfd4d759a834a6e0d987794`, fixed entry source
`c203417746409ed751bcb7135e02e614b476a17b`/raw
`788816a97b50b35f9af4444fa9fa1e5198851195c88afbdea2cf4130c8c7a249`,
both image prefixes' standalone lease wheel`f527cc61…`. Only that standalone package
was replaced; existing provider/trainer/contracts, PEFT/BNB, model binding, main
templates73013dd5and bootstrap34796a43were reverified and preserved. Full installed
source/namespace/RECORD gates in both prefixes passed. The nativee5owner, c499numeric
prefix and CPU default remain unchanged. All26temporary entry fences are removed.
Installed root configuration raw SHA:
`ac6b361fa6a0038de43cf73b1be8af8a9d6f23c9efbdcd17341fb6a1fb7215ad`.

The fresh OS-only negative case
`eom-image-provider@imageleasemissing_9585cb0f1fe543d68109f2058c1cf5f6.service`
passed the actual automatic path: protected root READY observation → real SIGUSR1
ACK → expected`LOCAL_IMAGE_MODEL_UNAVAILABLE`for the deliberately absent model
pointer → original FAILED outcome preserved → automatic root retirement/store0 →
same physical inode reacquired with no GPU clients. Both old failed acceptance
cases remain failed; no model weight, Job, Artifact or generated image was produced.
This verifies a retained failure and its root lifetime, not image model success,
cache replay, trainer success, crash/timeout or six CPU/CUDA benchmark runs.

Exact private OS evidence under the existing release root:

- `invalid-input-v2/`: actual no-lease invalid-input retirement PASS, including
  untouched external/root-held lease and no fabricated ACK;
- `explicit-slice-result.json`: all19main plus guardian placement/pin update;
- `unack-os-fd-clean-{intent,result}.json`: explicit exact predecessor recovery,
  absent READY kept absent and same-inode reacquisition; no automated PASS relabel;
- `wait-and-retirement-successor/`: preparation/import, both prefix backup and
  lease-only install intent/result pairs, old entry/config backups and selection;
- `retained-missing-model-v2/{intent,observations,result}.json`: new actual retained
  failure PASS; local receipt`corrected-retained-result.json`returned0;
- `/opt/eom/image-gpu-lifetimes/<new-unit>/<actual-invocation>/ack`and`retirement`:
  immutable actual root intent/result records, not product Artifact identities.

Source379related tests/strict4and separate entry/guardian/lifetime96tests remain
separate evidence scopes. Whole-goal completion and GPU default change are unproven.

2026-10-16 source 후속: [CUDA loader 작업 폴더 경계](INCREMENTAL_EMBEDDING_CUDA_LOADER_DIRECTORY_DESIGN.md)는
공식 cuSPARSELt의 빈 RUNPATH component를 고정0555 빈 폴더의 관측으로 해석하고,
native CUDA factory에서 실제 cwd를 재검증한다. CPU의 거부 규칙과 digest는 유지한다.
이는 CUDA 설치·namespace·공유 lease·실제6회 성능 비교나 기본 device 활성화의 증거가 아니다.

## 1. 현재 근거와 변경하지 않을 경계

읽기 전용 inventory에서 전달된 장치는 RTX 5080, VRAM 16,303 MiB, driver 580.126.09이며
관측 시점에는 idle이었다. 이 수치는 계획 입력이지 CUDA 호환성·전용 capacity 승인 증거가
아니다. 실제 실행 직전에 UUID/PCI identity, compute capability, driver, 장치 node 및 현재
점유를 다시 확인한다. `nvidia-smi`의 CUDA 표시는 설치된 PyTorch CUDA build를 증명하지 않는다.

| 현재 source 경계 | 확인한 동작 | GPU 구현의 책임 |
|---|---|---|
| `services/catalog_service/eom_catalog_service/local_embedding_adapter.py` | exact runtime versions 확인, CPU FP32/eager/eval/inference mode, 무절단, CPU pooling 및 host L2 | 별도 admitted CUDA 분기; 현재 CPU 의미 보존 |
| `packages/catalog_contracts/eom_catalog_contracts/inference_transfer_embedding.py` | `CPU/CUDA`, `FLOAT32`, TF32 false, execution-runtime hash가 space에 포함됨 | installed runtime과 hash를 실제 owner가 검증; DTO만으로 활성화 금지 |
| `services/orchestrator/eom_orchestrator/inference_transfer_cpu_handoff.py` | root staging, ancestor FD, O_EXCL/O_NOFOLLOW, owner marker, canonical input | indexing/GPU successor의 고정 branch와 별도 staging root |
| `services/orchestrator/eom_orchestrator/inference_transfer_cpu_systemd.py` | exact unit/interpreter, no override/drop-in, invocation/종료 확인, uncertain guard | 동일한 고정 launcher pattern의 새 native CUDA leaf |
| `services/catalog_service/eom_catalog_service/inference_transfer_cpu_verifier.py` 및 `services/orchestrator/eom_orchestrator/inference_transfer_cpu_installation.py` | runtime 보호·RECORD/pip check·UID/capability·파일/소켓/network denial | CUDA unit의 별도 verifier와 실제 device allow/deny probe |
| `services/image_provider/eom_image_provider/provider.py:acquire_gpu_lease()` | same-UID parent 0700/file 0600, nonblocking flock | 아래 공유 physical lease로 명시적 successor |
| `services/image_trainer/eom_image_trainer/cli.py:_lock_gpu()` | 별도의 same-UID image flock 진입점 | provider와 함께 같은 physical inode로 전환 |

2026-10-12의 read-only `getent`와 installed fixed-template instance의 `systemctl show`에서도
provider/trainer의 실제 User/Group은 `eom-image`, SupplementaryGroups/DropInPaths는 empty,
FragmentPath는 각각 `/etc/systemd/system/eom-image-provider@.service`와
`/etc/systemd/system/eom-image-trainer@.service`였다. 이는 두 entry의 identity 관측이며
전체 GPU unit inventory·privilege acceptance 완료는 아니다.

다음은 immutable baseline/history로 보존한다.

- `/opt/eom/conda/envs/eom-embedding-experiment`, 기존 CPU worker 계정·unit·verifier·manifest.
- 기존 E5/BGE weights, tokenizer와 모든 member SHA, upstream revision, CPU 결과와 실패 이력.
- API/core, Python 3.11 image/trainer runtime. 이들을 업그레이드하거나 CUDA embedding을
  실행하기 위해 Catalog/core ML dependency를 추가하지 않는다.
- CPU experiment 1.0은 ranking 실험이며 vector output 계약이 아니다. GPU indexing을
  기존 experiment 입력에 가짜 query/candidate로 포장하지 않는다.

## 2. 패키지 선택: 같은 PyTorch release의 명시적 CUDA build

후보는 **Python 3.12.13 / Linux x86_64 / `torch 2.7.1+cu128`**다. CPU baseline의
`2.7.1+cpu`와 upstream PyTorch release를 맞추고, 모델·tokenizer library version은 그대로
유지한다. 임의 최신 버전이나 image runtime의 Python 3.11 interpreter를 재사용하지 않는다.
PyTorch의 2.7 발표는 Blackwell과 CUDA 12.8 wheel 지원을 명시하고, 공식 이전 버전 안내는
2.7.1의 cu128 build를 제공한다. 이는 후보 선택의 근거이며 이 host의 실행 PASS는 아니다.
[PyTorch 2.7 발표](https://pytorch.org/blog/pytorch-2-7/),
[공식 이전 버전](https://pytorch.org/get-started/previous-versions/).

공식 stable [cu128 wheel index](https://download.pytorch.org/whl/cu128/torch/)에서 확인한 pin:

```text
torch-2.7.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl
https://download-r2.pytorch.org/whl/cu128/torch-2.7.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl
SHA-256 0b64f7d0a6f2a739ed052ba959f7b67c677028c9566ce51997f9f90fe573ddaa
```

small wheel metadata의 SHA는
`e41a1ec38ccc8170c228b57b1432cc7ae03718dd69bb0a72d1fc32707dde1765`다.
[공식 wheel metadata](https://download-r2.pytorch.org/whl/cu128/torch-2.7.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl.metadata)는
CUDA runtime 12.8.57, NVRTC/NVJITLINK 12.8.61, cuBLAS 12.8.3.14, cuDNN 9.7.1.26,
Triton 3.3.1 등 exact transitive 요구를 명시한다. 설치 단계에서는 **모든** 해당 dependency의
exact version·wheel URL·SHA를 별도 lock으로 고정하고 `pip check`/RECORD를 검증한다.
이 문서는 dependency wheel의 hash를 조사·승인했다고 주장하지 않는다.

`transformers==4.56.2`, `safetensors==0.6.2`, `tokenizers==0.22.2`와 기존 CPU lock의
일반 transitive pin을 유지한다. Torch CUDA dependency는 장치 실행의 필수 library라는
이유를 lock에 기록하며, vision/audio/Diffusers/Accelerate/SentenceTransformers나 compile
extras는 추가하지 않는다. wheel이 Triton을 요구하는 것과 `torch.compile` 사용은 별개다.
설치 전 ABI/GLIBC·disk/RAM·driver 및 실제 build arch list를 검증한다. 드라이버 변경,
package flavor 자동 변경이나 toolkit system-wide 설치로 실패를 우회하지 않는다.

## 3. 모델 payload는 하나, runtime bundle과 numerical space는 별개

현재 BGE pin의 authoritative source는 `scripts/embedding/_install_experiment_snapshot.py`의
`reviewed_bge_model_spec()`이다. 이 코드의 upstream revision은
`9a0624b896d81da7492a910ffa53731274b6cf3d`, maximum tokens는 **2048**이다.
초기 후보 문서의 다른 upstream revision이나 모델 광고 상한8192로 바꾸지 않는다.
실행 시 installed manifest를 이 source pin과 공식 resolver로 재검증한다.

`LocalEmbeddingModelSpec/1.0`에는 CPU package flavor가 포함되고, 현 resolver는 모델 revision
directory의 `manifest.json == spec`를 요구한다. 따라서 `2.7.1+cpu` manifest로 cu128 실행을
성공 처리하거나 기존 manifest를 수정해서는 안 된다. 단순 CUDA spec을 새 directory에
복제하는 방법도 canonical weights를 중복시키며 hardlink는 현재 nlink=1 invariant에 어긋난다.

최소 successor는 **작은 runtime bundle manifest가 기존 immutable model payload를 참조**하게
하는 것이다. JSON Schema2020-12를 먼저 정의한 뒤 frozen Pydantic/owner resolver를 추가한다.

- logical model ID, legacy payload revision/manifest SHA, 새 runtime-bundle revision/manifest SHA를
  구분한다. successor는 legacy bundle predecessor와 `model payload pointer`를 pin한다.
- payload pointer에는 source model ID/revision, schema/version, expected manifest/file-set SHA가
  있으며 owner 설정으로 storage location을 해석한다. 모델 입력에 filesystem path를 받지 않는다.
- legacy snapshot의 파일 list·upstream/config/tokenizer/weights SHA를 정확히 검증하고 CUDA
  bundle도 같은 list를 참조한다. bytes를 복사하거나 두 canonical payload를 만들지 않는다.
- library pins는 새 bundle에 cu128로 명시한다. legacy CPU resolver/1.0 contract는 보존하며
  GPU payload-resolution branch는 exact successor로만 입장시킨다.
- 현재 EmbeddingSpace1.0의 CPU/CUDA enum만으로 이 payload-pointer successor가 지원된다고
  주장하지 않는다. bundle/schema closure가 달라지면 이를 참조하는 space/input의 최소
  compatible successor도 먼저 정의하고, released1.0 bytes·CPU 이력을 재해석하지 않는다.

`execution_runtime_sha256`는 canonical typed numerical descriptor의 hash다. descriptor는
encoder 구현/host L2 recipe의 관련 installed file SHA, Python/architecture, torch wheel/build
SHA 및 CUDA/cuDNN·관련 numeric library versions/hashes, Transformers/tokenizers/safetensors/
NumPy pins, device model/compute capability와 driver pin, eager attention·FP32·precision flags,
deterministic/CUBLAS 설정, batch/padding/thread recipe를 포함한다. GPU UUID/PCI identity는
resource admission에 별도로 pin한다. 모델 payload·prefix/pooling/차원/정규화/overflow는
model/space에서 pin한다. **전체 EOM Git commit·전체 platform wheel hash·무관한 GUI/Slack
변경은 numerical fingerprint에 포함하지 않는다.** source/installed release audit는 별도다.
같은 descriptor를 공유하는 unrelated release로 모든 vector를 재인코딩하지 않는다.

## 4. 최소 공유 physical-GPU lease와 image migration

기존 `/var/lib/eom-image/gpu0.lock`을 CUDA embedding 계정에 그대로 전달하면 same-UID
검증과 parent0700에서 실패한다. image private directory를 group-writable하게 만들거나
embedding을 `eom-image` UID로 실행하면 모델/workspace 경계가 무너진다. root supervisor만
legacy flock를 잡는 안도 supervisor crash 시 GPU child가 살아 있는데 lock가 해제될 수 있어
단순 wrapper로 채택하지 않는다.

선택안은 기존 nonblocking flock를 **한 root-provisioned local inode**로 옮기는 작은
physical-lease adapter다. 새 broker/daemon/DB queue/GPU registry는 만들지 않는다.

```text
/run/eom-gpu-lease/            root:eom-gpu-lease 0750, local tmpfs only
/run/eom-gpu-lease/gpu0.lock   root:eom-gpu-lease 0640, regular/nlink=1
```

- root installer가 한 번 생성한다. 실행 중 unlink/replace/recreate하지 않는다. GPU0은
  admitted physical UUID/PCI mapping의 고정 resource이며 caller/model이 lock path를 고르지 않는다.
- GPU unit에만 `SupplementaryGroups=eom-gpu-lease`를 고정한다. 계정의 global group membership,
  sudo/Docker/`eom` group은 추가하지 않는다. CPU historical unit/계정에는 아무 변경도 없다.
  이 좁은 per-unit read/lock 자격도 **설치·privilege-review gate**이며 이 문서의 권한 부여가 아니다.
- adapter는 root-owned non-writable ancestors, exact parent/file UID/GID/mode, regular/nlink=1,
  named/FD inode identity 및 local filesystem을 검증한다. O_RDONLY|O_NOFOLLOW|O_CLOEXEC로
  기존 파일만 열고 `LOCK_EX|LOCK_NB`를 잡는다. worker O_CREAT/fchmod/write 권한은 없다.
  Linux local flock는 read-only FD에도 exclusive lock를 허용한다. NFS/SMB는 제외한다.
  [Linux flock API](https://man7.org/linux/man-pages/man2/flock.2.html).
- 이 공용 OS adapter는 Python3.11/3.12에서 사용 가능한 stdlib-only 작은 infrastructure
  package로 추출한다. image provider의 public `acquire_gpu_lease()`는 exception-label wrapper로
  유지하고 trainer의 `_lock_gpu()`도 같은 adapter를 사용한다. embedding은 image service나
  domain private module을 import하지 않는다. 실제 image/trainer/embedding 세 소비자가 있으므로
  이 추출은 공통 boundary이며 범용 plugin/handler framework가 아니다.
- lease는 CUDA 초기화/model load 전에 취득하고 kernels 동기화·모델/tensor teardown과 unit
  종료까지 유지한다. 긴 GPU batch를 preempt하지 않으며 lease 중 다시 owner queue를 기다리지
  않는다. guard FD는 main unit lifecycle에 묶고 GPU-using descendant가 살아 있는 동안 닫거나
  LOCK_UN 하지 않는다. 비정상 종료/남은 cgroup/driver cleanup은 owner가 uncertain으로 fence하고
  종료·GPU resource 회수를 확인하기 전 image/embedding 재입장을 허용하지 않는다.
- native embedding은 CUDA를 쓰는 subprocess/daemon을 만들지 않는 single-process leaf다.
  CPU tokenizer thread와 CUDA GPU-using descendant를 구분한다. fork/dup는 같은 flock open-file
  description을 공유하지만 O_CLOEXEC FD는 exec 뒤 남지 않으므로, exec child가 GPU를 계속
  쓸 수 있는 구조는 이 profile에 허용하지 않는다. 이미지/trainer의 실제 subprocess 여부도
  조사하고 해당 lifecycle의 FD retention·cgroup cleanup을 검증한 뒤 전환한다.
- flock는 물리적 상호배제일 뿐 권한·FIFO·priority·VRAM hard quota가 아니다. 작업은 여전히
  Orchestrator admission/기존 queue를 거친다. 실제 image production task를 먼저 입장시키고
  embedding은 concurrency1, 작은 batch, bounded 비선점 lease를 사용한다. Codex Worker slot이나
  `CodexCapacityController`의 image-role GPU flag로 native embedding 권한을 가장하지 않는다.

**migration gate:** provider CLI, pair/native-geometry/extraction entry, trainer CLI와 모든 설치된
GPU template/drop-in/direct operator entry를 inventory한다. 입장을 drain하고 active/uncertain
unit 및 legacy lock holder가 없음을 확인한 상태에서 adapter/units/lock policy를 함께 전환한다.
source-only unit 수정이나 서로 다른 두 lock를 혼용한 배포는 불합격이다. legacy0700/0600
branch와 old inode는 이력/rollback용으로 보존하되 active profile은 shared 하나만 허용한다.
trainer/provider/embedding의 상호 경합, 프로세스 crash/timeout/잔존 child, inode 교체·symlink·
metadata mismatch 및 old entry 거부를 회귀한다. 이 gate가 닫히기 전 GPU 기본값은 금지다.

### Image unit lifetime integration —2026-10-17 design before implementation

The actual CUDA installation probe/seal/native reader/retirement passed; this is
not evidence that the19 installed legacy image GPU templates have migrated.
The migration reuses the existing physical inode and PID1 fdstore, not a new
broker, queue, database, model runtime, or competing mutex.

1. Responsibility: the optional stdlib GPU adapter acquires the fixed lease,
   requests its retention, and waits for a root acknowledgement before yielding.
   Image code never observes/changes another worker, clears a store, or retires a unit.
2. Canonical source: installed root-owned unit/code pins and actual PID/invocation,
   cgroup, process/driver state and stored lock FD. Notifications and paths alone
   are not proof of store acceptance. Product input/output schemas remain unchanged.
3. Identity: reuse exact systemd unit/instance/invocation and PID/start ticks;
   do not invent a Job, Artifact or revision for this OS lifecycle.
4. Pointers/checks: existing-only lock dev/inode/epochs, fixed unit/template and
   actual user/groups/capabilities, root-protected notification endpoint, and
   terminal cgroup/driver observations. No caller-supplied lock/authority fallback.
5. Access: one indexed unit lookup, one bounded PID/FD observation, one physical
   flock per invocation, and append-only local lifecycle evidence. No corpus scan.
6. Structures: existing typed OS observations, fixed template-to-role lookup and
   bounded descriptor sets. No DB schema/index or generic runtime registry.
7. Scale/complexity:19 admitted image templates, one active physical GPU holder;
   O(F+T) observation for a bounded number of FDs/threads and constant-size policy.
8. Concurrency: root observes PID1's duplicate of the SAME exclusive description
   before ACK. Worker close only closes its own FD; PID1 retains ownership through
   success, cancellation or crash until supported root terminal verification.
9. Direction: provider/trainer depend on the public optional GPU adapter. Existing
   root installation/Orchestrator infrastructure owns launch/observe/retire; the
   adapter never imports Catalog, ML, NAS, SQL, HTTP or Orchestrator packages.
10. Failure: absent/early/foreign/late ACK or retention errors fail before model
    work; no unlocked legacy fallback, store removal or auto-retry. Busy remains
    busy. Root preserves failed identity/history and fences unknown cleanup.
11. Simpler alternative: changing only --gpu-lock or holding a parent FD releases
    ownership too early on context exit/parent crash. Sending FDSTORE plus a
    barrier alone proves processing, not acceptance; therefore explicit root ACK
    and terminal cleanup remain required.

An explicit stdlib-only unit bootstrap blocks SIGUSR1 before importing either
image CLI so new threads inherit the blocked signal. Do not mutate signal state
when a library is merely imported. The new acquire-for-unit API requires this
already-blocked process-lifetime reservation; it does not install a handler or
restore/unblock SIGUSR1 during model work. Root's
bounded observer must reject an unexpected thread/child frame before ACK.
The legacy same-UID lock branch and independent plain shared-lease API remain
unchanged. Only image's explicitly selected shared branch requests the new unit
handshake. Source changes alone do not activate any installed image template.

Installation must coordinate provider/trainer wheels, all19 templates, per-unit
shared group and root observation/retirement before enabling CUDA models. Do not
add RemainAfterExit to an operating --wait launcher without its exact cleanup
owner: it would hang waiting for a unit that no one retires. Root guard activation,
all-entrypoint draining/migration, real mutual exclusion/crash/terminal checks and
six model comparisons are separate remaining acceptance, not source-test claims.

#### Worker-entry source checkpoint —02:18 UTC

Added the explicit optional-adapter acquire/context pair for unit-retained GPU
ownership. It requires SIGUSR1 already blocked, rejects a pending early ACK,
acquires the unchanged fixed inode, uses the existing FDSTORE/BARRIER request,
then waits30s for the actual signal's root UID/nonzero sender PID. It validates
the held lease again before yielding. Error/cancellation closes only its own FDs;
no LOCK_UN/store removal/legacy fallback. Plain shared and legacy APIs remain.
Provider/trainer shared-path branches use the new public entry; existing stable
error labels, local image result schemas, model data and orchestration stay unchanged.
No new worker JSON message was invented: this reuses the existing OS notification
protocol and POSIX signal metadata, not a worker-claimed JSON `ack=true` field.

`scripts/image_provider/run_gpu_unit.py` is a separate root-installation input,
not a general module launcher or a wheel-installed console command. Its fixed
role/prefix map admits only provider/trainer, actual image UID/GID with the narrow
per-unit lease group, isolated/no-bytecode Linux interpreter and no preloaded ML.
It accepts exactly one shared --gpu-lock (including unambiguous equals form),
rejecting missing/legacy/duplicate/abbreviated choices. Only then does it reserve
the signal and import the fixed existing CLI. Import alone changes no signal mask.
The future root installer must pin this separate bootstrap's exact source bytes;
the existing image wheel build does not imply it installed the bootstrap or guard.

Explicit image-test Conda run: **287 PASS in14.34s**, including39 new entry/negative
cases (the earlier179/275/280 runs overlap and are not added). Real temporary FD
duplicates prove continued contention after worker success/failure/timeout/cancel,
then release only when the synthetic retained owner closes. Root ACK and identities
are explicitly synthetic; these are not actual PID1/image privilege acceptance.
Python3.11 grammar for the shared adapter/bootstrap is checked. Ruff/format/diff
and strict4 changed production files PASS, using the actual image-test interpreter
as the type checker's dependency target. The initial pytest invocation lacked
source image paths and initial API-only type lookup lacked Pillow; both invocation
errors were corrected without installing Pillow/ML into the API or weakening types.

This is **SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVATED**. Actual19-unit guard,
launch/drain/template migration and independent terminal cleanup remain required.
No installed GPU account, unit, image prefix, numerical CUDA/CPU prefix, index,
default, model output or authentication/session was changed at this checkpoint.

#### Installed entry inventory correction and package candidates

Read-only02:19 UTC inventory reconfirmed19 installed NVIDIA-granting image
templates, all still legacy and with no active/activating/deactivating/reloading
image unit in that observation. This is not driver-client/migration acceptance.
The actual executable inventory exposed three bindings, not two: provider CLI in
the image prefix, trainer CLI in the trainer prefix, and **provider CLI in the
trainer prefix** (lineart extraction, learned comparison, LoRA evaluation).
The initial bootstrap candidate668baed3 did not represent the third binding and
was **never installed**. Replace that bootstrap candidate, not the valid wheels.

The corrected immutable lookup includes PROVIDER_IN_TRAINER and stores prefix,
module and console-name together, without a role-name conditional. Current
bootstrap raw `2da0e3d7a8ba729e5a73ef29208bd1cf49e3ae394d35beea5c965095321aed55`.
A fixed expected inventory plus one case per source template prevents empty
selection, an unmapped execution combination or silent GPU-entry expansion.
Latest related regression: **308 PASS in14.18s**, including60 new entry/inventory
cases; strict4/Ruff/format/diff PASS. Earlier overlapping runs are not added.
These identity/root-signal cases remain synthetic, not actual image unit admission.

Standard immutable builds for code `1a5c6b86598c0eec301c23851a85e80d25123d43`
passed both existing source/ZIP/RECORD/dependency gates. Exact candidates:

- Provider stage `/tmp/eom-image-provider-build/1a5c6b86598c0eec301c23851a85e80d25123d43.NL0k0B`.
- Trainer stage `/tmp/eom-image-trainer-build/1a5c6b86598c0eec301c23851a85e80d25123d43.DUhDJi`.
- Common lease wheel raw `c72b90e3b2a7ed2a3abdbcc9ea1eff54376e148ea874622a90389d7dc2a0bdbf`.
- Contracts wheel raw `4eb98940e36d63ab224af79b5bb5dab2be4a913b0dbb5b79cff80230ea43e156`.
- Provider wheel raw `624cb44d0d708da84fb769ac842acad8bcea5906560d25a72a57e9aafe9ca37c`.
- Trainer wheel raw `b2614f1e9d6ec98120d3de8c301e1ed704411ac4e75b02e2d922c1ac1bbbe522`.

Shared wheel bytes match across the two independently verified build boundaries.
Both report GPU_SHARED_LEASE_MIGRATION_VERIFIED=NO. The later correction changes
only the separately installed root bootstrap and tests; these package sources
and wheel hashes remain valid, so no repeat wheel/model/prefix copy is justified.
Do not install the stale bootstrap from that source commit or claim the wheel
verifier packaged a root bootstrap it does not contain. Full root guard, exact
bootstrap deployment, all19 lifecycle migration and actual image acceptance remain
required before the already planned CUDA model comparisons/default decision.

#### Root image unit readback checkpoint

The next existing-owner building block is implemented as **read-only source**,
not a dispatcher, ACK sender, installed guardian or model grant. It consumes no
worker JSON/authority and changes no image input/output schema, DB or queue.
The existing required-design note above still defines its responsibility/source,
pointers, O(F+T) bounded FD/thread access and failure/concurrency boundaries.

- `image_gpu_unit_identity` owns the closed19-template → three-role lookup;
  names/instances cannot be arbitrary paths or implicit new GPU roles. All19
  source executable bindings are independently compared with that lookup.
- `image_gpu_unit_observation.observe_image_gpu_unit_ready` requires root, exact
  caller-pinned installed template/bootstrap hashes, actual account/group, exact
  activating unit/PID/start/invocation, pinned command/executable, effective
  private-network/empty-capability/device/retention policy, sole cgroup process,
  and reserved ACK signal in every bounded thread. Device/boot and empty GPU
  clients are checked using existing readonly observers. It never sends ACK.
- Existing physical-FD readback shares its canonical worker/PID1 flock, tmpfs,
  inode/epoch/readonly/store-name validation with a distinct image resource type.
  Image code does not fabricate a native installation-probe report. Independent
  native/image dataclasses preserve the old probe fields and canonical bytes;
  common private validators and same-inode reacquisition implementation are reused.
- The protected cgroup reader was extracted once for actual CPU/CUDA/image use;
  the native wrapper retains its strict identity and old error labels. Missing
  trees stay explicit, and duplicates, non-root/writable/nested/symlink trees,
  excessive counts and impossible PID ranges are refused. No caller can choose
  an arbitrary cgroup directory or make a missing tree recreate itself.
- `verify_image_gpu_unit_terminal` preserves original success/failure/timeout
  separately, pins the original invocation/start, rechecks file/account/policy,
  ended original process, empty/confirmed-absent cgroup, zero GPU clients and the
  still-retained physical fence. PID reuse is tested by PID+start, not PID alone.
  Unknown results or partial cleanup fail explicitly. It never stop/reset/retries
  a unit, clears a store, changes history or marks an application Job successful.

Found and reproduced an additional pre-installation bootstrap ambiguity: its
non-abbreviating `parse_known_args` could forward a later `--g` that the original
CLI then expands to --gpu-lock, overriding the earlier canonical shared path.
Seven failing regressions reproduced it before correction. The bootstrap now
rejects reserved-flag prefixes among forwarded arguments. Original provider and
trainer abbreviation behavior is independently preserved/tested; no backend shim.
**Current bootstrap raw7edb475db14b0e23d6a820781fee3813c7714cbe250ebd314b2abceec53b4cd7**;
earlier2da0e3d7/668baed3 bootstrap candidates were never installed and must not
be used for the later coordinated migration. Package wheels1a5c6b86 remain valid:
only their separate root-bootstrap input changed, not their package source bytes.

Latest source results in explicit Conda environments: root observation/resource/
retirement/dependency suites **274 PASS20.25s**; image/shared-lease/release suites
**317 PASS14.37s**; strict6 source modules, Ruff/format/diff PASS. Earlier overlapping
runs are not added. Tests explicitly simulate root/systemd/kernel observations;
the private cgroup fixture initially inherited group-writable mode and was correctly
refused, then fixed to its declared protected0755 fixture without weakening code.
No privileged image/GPU acceptance or model execution is claimed by these tests.
No DB mutation changed, so no production/disposable DB test was introduced here.
The three numerical implementations remain exact3487cae0/440d7406/f667e54d bytes.

Still required: compose these reads with the existing root unit owner; capture
all19 installed release pins and drained old invocations before any ACK; persist
original readiness/terminal intent before effects; send only the exact original
main ACK; perform supported outcome-specific terminal retirement and same-inode
post-checks. A cache/busy/pre-lease exit must not clear another unit's store/lease.
Package that owner and bootstrap with all19 source templates/group/lock settings
in one bounded rollout. Do not deploy RemainAfterExit into the existing --wait
launcher without the terminating owner. Actual cross-consumer/crash/timeout
acceptance, six frozen comparisons/default decision and C1–C5 remain open.

Routine readback02:33:42 UTC: original INDEX/QUERY PIDs3633849/3633843 and
invocations7c9ea0c5/ae90dbc1 remain active/running. Subsequent CONTENT a9e2bc90
and CONCRETE fcc0aad5 four-target commands succeeded02:14:11/02:25:49; no new
complete corpus denominator/metadata-command result is inferred. HTTP observer
2895440 is still alive/LOGIN, without a new prompt/key/QUERY or accepted auth.
Next routine readback is not before03:03:44 UTC. Full original goal remains ACTIVE.

#### Root image lifecycle effects — design before implementation

The next adapter composes the existing image readiness/terminal observations with
the fixed systemd main-process signal and outcome-specific retirement already
used by the native probe owner. It is root infrastructure, not a worker tool,
admission receipt, new queue or product Artifact owner. The coordinated installer
must still fence/drain all19 entries before activating a caller of this adapter.

Canonical identities remain the actual closed unit name, invocation, PID/start,
root-installed template/bootstrap pins and retained physical inode. Root-only
records live under `/opt/eom/image-gpu-lifetimes/<unit>/<invocation>/`: separate
exclusive `ack` and `retirement` reservations contain no-clobber, fsynced intent
before the single effect and a result only after confirmed completion. These are
local OS audit metadata, not copied image payloads or NAS product Artifacts.
Records serialize the existing frozen observations with Pydantic TypeAdapter;
no cross-service/worker format or DB schema changes. Directory lookup is bounded
O(1), each observation remains O(F+T), and records are append-only per invocation.

Root reobserves an identical readiness frame before SIGUSR1 to only the fixed
unit main. Retirement preserves success versus failure/timeout and uses `stop`
versus `reset-failed` only after original terminal evidence is durable and freshly
confirmed. Post-checks require inactive/dead/Main0/store0, the original or cleared
invocation, empty cgroup/GPU and actual exclusive reacquisition of the SAME inode
held across checks. Unknown command outcome never auto-replays; an existing intent
blocks another effect, with a separate read-only recovery path. No caller-supplied
command, signal, path, history relabeling or borrowed-FD LOCK_UN is accepted.

The simpler unrecorded signal/stop sequence loses the original failure and cannot
distinguish an uncertain effect from an unsubmitted one. A new broker or general
transaction framework is unnecessary: the existing OS observations and atomic
per-invocation directory reservation provide the required local boundary.
Actual controller dispatch, all19 source installation, pre-lease/cache exits and
privileged lifecycle acceptance remain separate obligations, not source PASS.

**Implemented source checkpoint2026-10-17:** `image_gpu_unit_lifetime` now owns
the explicit root ACK, outcome-specific retirement and read-only post-retirement
recovery APIs. One original-outcome classifier is reused by capture/recovery;
recovery rejects success/failure relabeling. Atomic phase reservation prevents
concurrent/second effects, including when a command or result-record write has
an uncertain outcome. Intent failure submits nothing; result failure preserves
the intent without replay. Root paths use no-follow directory FDs and protected
metadata, records use O_EXCL/fsync, and the existing physical inode is actually
held across post-checks. No borrowed descriptor is unlocked.

Fresh root lifecycle/observation/resource/native-retirement/dependency suite:
**321 PASS23.64s**, including47 new lifecycle cases. Separate existing image/
shared-lease/release regression: **317 PASS14.32s**; strict7 source files,
Ruff/format/diff PASS. These tests use synthetic privileged/kernel ports and real
temporary record I/O; they do not send actual signals, stop operating units,
create an installed lifecycle directory, run a model or claim19-entry acceptance.
Package/numerical inputs are unchanged: the1a5c6b86 image package candidates and
separate7edb475d bootstrap remain; installed numericalc499/admin-ownere5, CPU
default, active services and all19 legacy image templates were not changed.

Routine readback03:04:02 UTC found the same INDEX/QUERY PIDs/invocations active.
METADATA2240521c, CONTENT7ba56f52 and CONCRETEc14b3131 completed at02:37/02:51/
03:02 respectively. Separate queued view snapshots377/387/399 missing bindings
are not one coherent corpus denominator; eligible545/report-missing25 is not a
regression of the original520 backfill. Next routine check≥03:34:02 UTC. Original
HTTP observer2895440 was still LOGIN at03:01, no accepted authentication or new
request. The full goal remains ACTIVE: compose the fixed root guardian and
pre-lease/cache exit handling, then coordinated19 migration/actual acceptance,
six frozen comparisons/default decision and actual C1–C5 consumer verification.

#### Fixed guardian composition — design before implementation

The root guardian observes one already-starting fixed unit; it neither launches
models nor creates a queue. Its input is a frozen internal installation value:
the exact19 template/hash pairs, separate bootstrap hash and physical device
capture. These are caller-pinned protected installation inputs, not worker JSON
or proof that a deployment/drain has happened. The coordinated installer still
owns package/source verification and draining the old legacy entrypoints.

At guardian entry, capture all19 protected template bytes and the bootstrap once,
validate every command against the same closed role/lock rule, and retain file
epochs throughout. A keyed tuple/map gives O(19) initial validation and O(1)
selection. A bounded watcher pins the one actual invocation, waits for the main
process/PID1 retained descriptor, invokes the existing root ACK exactly once,
then the existing terminal verification/retirement. Fixed unit TimeoutStartSec
and TimeoutStopSec bound the observation; missing/drifting/unknown states stop
observation, not the worker, without automatic replay or history repair.

Cache hits, input errors and lease contention can terminate without acquiring a
GPU lease. They require a distinct frozen terminal observation: original success/
failure, exact source/unit/invocation/start, empty cgroup and actual descriptor
store0, all rechecked. Their root intent/retirement uses the same exclusive phase
reservation and fixed stop/reset rule, but never borrows or clears another unit's
physical fence and does not require an unrelated GPU holder to be idle. Reusing a
fake READY observation here would conflate two different ownership states.

The existing root infrastructure owns this adapter; domain/worker formats, DB,
NAS ownership and numerical code remain unchanged. No generic state-machine,
broker or new runtime registry is required: two real ownership states, existing
typed OS observations, one bounded loop and existing root effects suffice.
Installing template hooks/root launcher remains a coordinated deployment step;
source composition alone must not enable CUDA comparisons or change defaults.

**Implemented source checkpoint2026-10-17:** the fixed root guardian adapter now
captures all19 caller-pinned protected templates and the bootstrap once, validates
every command through the public closed role/lock rule, retains file epochs, pins
the actual invocation/start and composes ACK → terminal → retirement. Its timeout
comes from the pinned finite unit limits, not a caller override. Fast0.2s checks
apply only before ACK; running work uses1s checks, avoiding five systemctl launches
per second. No whole-prefix or payload rehash is repeated by this watcher.

Cache/input/busy exits have a distinct no-lease terminal observation with actual
store0 and repeated empty-cgroup/unit/policy/file checks. Their retirement reuses
the existing exclusive intent/result and fixed effect machinery, but never reads,
releases or waits for another GPU holder. If a process dies with a retained store
before READY was observed, the guardian explicitly leaves it fenced for supported
recovery; it does not fabricate a PID/start/READY observation or clear the fence.

The explicit root dispatch adapter checks the protected caller-pinned guardian
template, fixed systemd-escape identity and actual fresh guardian unit before one
nonblocking start. Existing/failed/running guardians are not restarted. Timeout
or nonzero submission is uncertain, not permission to submit again. Actual
unprivileged systemd-escape output was checked for a representative original unit;
this is an identity-only read, not privileged launch/activation evidence.

Fresh ten-suite root/guardian/resource/native/dependency regression **361 PASS
25.45s**, separate image/shared/release **317 PASS14.35s**, strict8/Ruff/format/diff
PASS. Initial launcher-test failures were a missing fixture `Path` import, fixed
without weakening production checks. Root/kernel/dispatch ports remain synthetic;
no actual signal, root guardian start, main stop/reset, model or DB operation.
Source bootstrap7edb475d and package candidates1a5c6b86 remain unchanged; current
installed services, numericalc499, admin-ownere5 and all19 legacy templates remain.

Still next: install a reviewed protected root entry that supplies these exact
installation values; wire its guardian template and all19 pre-entry hooks/bootstrap/
per-unit supplementary group in a drained coordinated rollout with rollback.
Then execute actual cross-consumer/crash/timeout/cleanup acceptance before six
CPU/CUDA numerical comparisons and conditional default. C1–C5 and the original
authenticated HTTP acceptance remain part of the full ACTIVE goal. Next routine
INDEX/auth observation remains≥03:34:02 UTC, not another login prompt or QUERY.

##### Actual guardian owner preparation03:26 UTC

Source `1031a2323d24cf2fcb968e1edd83a5e0cf5047a3` was committed/pushed clean.
Standard build/three-wheel RECORD/source/OpenAPI inspection passed at
`/tmp/eom-api-build/1031a2323d24cf2fcb968e1edd83a5e0cf5047a3.Hq4FL0/dist`.
Owner platform wheel SHA is
`e707b88d9fea4fbae6a4d54d87441d47c01194d96730debebaeb9872a540e76c`;
paired API contracts wheel SHA is
`8877cf604763ba7e1d3f53bebb508cede89f5ee6bbe708cf5c1abf81e9e7089f`.
Separate unprivileged OLD-interpreter installation/import from
`/tmp/eom-image-guardian-import.HAgcR7ln` passed with no optional ML imports/effects.

The first operator attempted to execute the intentionally0444 protected shell
installer directly; sudo refused before execution (`command not found`), target
absent and no mutation. Its original helper/result remain under
`/tmp/eom-image-guardian-owner.JVPNajsd`. After confirming unchanged installer SHA
559ada51 and absent target, the corrected explicit `/bin/bash` invocation used the
same EOM2/pts5 authorization with no password prompt or retry of an uncertain
effect. Supported owner-only install exited0 at03:25:58 UTC. Old releases remain;
new root-owned0755 owner is
`/opt/eom/embedding-owner-releases/1031a2323d24cf2fcb968e1edd83a5e0cf5047a3`.

Independent actual readback found root0444/nlink1 guardian/lifetime modules,
respectively SHA `c6e777430bdf1f19fd1b06a716e0366192d997ff6fc6add1f32b3298a7255c7c`
and `45fef85e578485dd2e61a71d9f107b92330769975db86fdc28fab08addd21622`.
OLD-interpreter imports resolve from that installed owner with optional ML0 and
no privileged effects. This is **OWNER_INSTALLED / NOT_SELECTED / NOT_ACTIVE**,
not an operating guardian or migration/model grant. Native administrativee5,
numericalc499, image packages/bootstrap/templates, application/services and
CPU defaults were not changed. No new numerical-prefix audit/rebuild is needed
for this administrative-only installation. Important Slack milestone delivered
`devreport_58eb654fe94f4238b5bf9584bdc4346f`03:26:50 UTC, Korean summary first.

##### Coordinated template rollout boundary — design before implementation

The19 existing image templates retain their original command arguments, resource
budgets, workspaces and model bindings, but switch the executable to the reviewed
stdlib-first bootstrap, fixed shared lock and per-unit supplementary lease group.
An explicit root ExecStartPre launches the separate fixed guardian before the
unprivileged main starts. Retain the main unit after exit, preserve PID1's single
descriptor, disable automatic restart and admit one invocation per instance.
ReadOnlyPaths exposes the existing shared inode without granting its creation or
mutation; the old lock/path remains as history/rollback, not an active fallback.

The separate root guardian is OS coordination, not a worker/model role. It uses
the existing OLD interpreter and reviewed installed owner, no repository/NAS,
model stores, database or auth inputs. Root proc/FD observation requires bounded
DAC-read/ptrace capabilities; fixed systemctl commands use PID1, not an arbitrary
privileged shell. Read-only driver queries have only the four fixed device nodes,
AF_UNIX/AF_NETLINK and a private network; no ML import or model file access. Only
its root-local lifecycle audit directory is writable. Root entry files are
protected installation code, not paths/commands supplied by a worker or user.

Existing component deployers must reject the new source templates (or installed
guardian entry) before wheel/user/unit mutation. They configure unrelated bindings
and identities and cannot safely perform this19-entry migration piecemeal. Reuse
their existing wheel/source/RECORD verifier in the coordinated operator instead:
pin source and existing wheel bytes, drain and fence entrypoints, preserve exact
old prefix members/templates/configs, verify no active/uncertain legacy holder,
install both reviewed package sets/root entries/all19 units while fenced, reload,
verify the complete source/effective set, then reopen only the supported path.
Migration failure leaves the fence and durable evidence; no blind reinstallation.
Rollback uses preserved exact old inputs as one compatible set, not a latest
package/model substitution. These are source/installation changes, no new worker
protocol, DB/queue or replacement Artifact ownership boundary.

Existing image-prefix preflight also found operator-owned0775 directories and
Python executables. The unchanged release verifier correctly refuses them. The
coordinated preparation must preserve exact prior metadata and normalize only
the fixed two image-prefix ancestor chains, Python3.11 executables, site-packages
directory and distribution METADATA/RECORD ancestors/files needed by that verifier.
The shared `/srv/eom/conda/envs` parent changes ownership/protection only; other
environment contents and current jobs are not rewritten. New environment creation
there becomes an explicit privileged installation operation. This is not a full
image numerical-prefix admission or an audit of every third-party library.

For any regular metadata file with multiple links, never chown/chmod its shared
inode (which can also belong to a Conda cache/another environment). Preserve the
old directory entry/inode in the private rollback workspace and materialize an
identical-byte private file at the exact original path before protection. Record
hash and before/after identity/metadata; bounded no-clobber preparation must stop
on symlinks, unknown owners, changed epochs or partial outcomes. No model/Artifact
payload is copied, no global Conda cache or unrelated environment file is changed,
and the verifier's protection checks are not relaxed. Preparation runs only after
the image-entry drain/fence, with its rollback metadata preserved.

##### Template/root-entry/preparation checkpoint2026-10-17

All19 source templates now select their original operation through the fixed
Python3.11/-I/-B/bootstrap role and shared inode. Original model/workspace/budget
arguments remain. Retention/one-invocation policy, per-unit lease group and root
pre-entry hook are explicit. The separate root guardian template has only proc/FD
read capabilities, fixed device-query access and its root-local metadata write
directory; model/auth/NAS/DB locations are inaccessible. Existing polkit remains
closed and does not grant workers permission to start the root guardian.

`gpu_guard_entry.py` is the source for the two fixed root start/watch entries.
Its2020-12 header schema pins owner1031a232, forbids authority/extra/latest fields
and validates the frozen installation schema/Pydantic invariants before calling
the existing owner. Protected bounded/no-follow reads and config epochs prevent
silent rebinding. Only safe stable diagnostics are emitted, never config inputs.
This small root installation value is not a new worker/RPC/DB contract. Legacy
component deployment now refuses the new source/installed guardian before any
wheel/user/binding/unit mutation; it cannot accidentally deploy only half the set.

`gpu_runtime_permissions` captures only the fixed two image-prefix paths and
required metadata, preserves intent before one application, and refuses drift,
unknown ownership, symlinks, special modes, wrong workspaces or replay. Shared
metadata entries are retained in the private same-filesystem recovery workspace;
identical-byte new entries receive protection without changing the old inode's
owner/mode/content. A local inode→epoch map accounts only for the coordinator's
own rename-ctime changes across known aliases. Parent-directory fsync and before/
after identities are recorded; no model copy, recursive environment rewrite or
unrelated environment-file permission change is performed. Final activation and
full compatible rollback remain the coordinated operator's responsibility.

Actual **root-only disposable filesystem** tests ran from protected hash-checked
copies in `/opt/eom/.image-permission-tests-lyfi_bfr`: **8 PASS0.06s**, with real
chown/chmod/hardlinks, two aliases plus a third cache alias, no fake root identity,
and no production-prefix/model mutation. Default unprivileged invocation correctly
skips these8 instead of claiming privilege acceptance. Protected test operator
SHA777b4a88 and source2b9ee357/testc58975c2 are preserved under
`/tmp/eom-image-permission-test-operator.vrInfUOo` and the root stage.

Then the same tested adapter captured the **actual production plan, read-only**:
376 members,349 needing protection,12 private metadata materializations totaling
163540bytes. Its root-local JSON SHA is
`dffa5024ce569fa9a0b6719d7641454006d40d5940ed27617bef8c3963c2bc78` at
`/opt/eom/.image-permission-tests-lyfi_bfr/production-plan-readonly.json`.
Both actual prefixes and recovery root use filesystem64512. This is a preparation
inventory, not permission application, image deployment or numerical admission.

Source image regression340 PASS14.23s and all20 candidate unit syntax checks
passed. Final eleven-suite root-entry/core/resource/dependency regression is
**378 PASS26.00s**; fresh strict2 script modules, Ruff/format/shell/diff PASS.
The actual root filesystem8 PASS is separate and is not counted as a source-only
privilege simulation. Initial fixture syntax/old console-binding assertions were corrected
for the intentional new bootstrap; no production guard was relaxed. Core package,
native schema/numerical code, installed owner1031, bootstrap7edb475d and image
wheel candidates1a5c6b86 are unchanged, so do not rebuild those environments for
these script/template-only changes.

The actual coordinated operator is still next. It must fence/drain **all users
of both image prefixes**, including the non-GPU extraction/reference units, before
package updates. Do not rely on a /run mask overriding an existing /etc fragment;
use verified existing-style deployment holds at the effective template boundary,
preserve their exact original state and prove admission is refused. Acquire both
existing legacy and shared physical leases; do not create/replace either inode.
Capture old namespace/config/template inputs and retain original failed history,
then prepare permissions, stage/verify both package sets and config/root entries,
install the whole set while fenced, and verify before releasing the hold. Do not
apply the production plan alone or activate partial RemainAfterExit templates.
Actual cross-consumer/crash/timeout acceptance, six comparisons/default and C1–C5
remain mandatory parts of the full ACTIVE goal.

Routine04:05:53 UTC: same INDEX/QUERY processes/invocations remain active;
CONCRETEab37001d and METADATAaf00d06c succeeded03:40/03:51. Separate queued view
counts369/379/391 are not a fresh coherent corpus audit. Original HTTP observer
2895440 remains live/LOGIN; no new auth prompt/key/QUERY. Next routine≥04:35:53 UTC.

### Actual image-model / cache / BUSY checkpoint — 2026-10-17

The current protected SSD-1B model pointer was read without weights/auth disclosure:
`imgmodel_7f1d9f4f4f041adde5dda11dba9491ff` /
`imgmodelrev_17b6fb3832ac469316e3a447be8e7e1d`, manifest SHA
`20dbed28f34c9275538198110ac4962fcf7a312c0846e6819f284ead791fe70c`.
The V6 binding,19 templates, root guardian and numerical runtime were unchanged.
One declared, one-step **non-Item** provider model invocation ran through the actual fixed
provider unit, READY/root ACK, real local CUDA model, original SUCCEEDED preservation,
automatic retirement, zero stored FDs, empty cgroup and same-inode lease reacquisition.

While a different root controller held the physical lease, the installed provider CLI reused
that exact private output: identical receipt, output hashes/inodes/mtimes, no new unit/model
or GPU client. A fresh actual provider unit then correctly failed BUSY before ACK/model,
retired without clearing the parent's lease, and left no output. The parent proved its
lease remained valid and a second claimant remained BUSY; final same-inode return passed.

Protected OS evidence (not product Artifacts):
`/opt/eom/image-joint-runtime-releases/imagejoint-a610b0c7/provider-success-cache-busy/`.
No-replay operator raw SHA `ef6b373d40e406ba707bc6b8610a649841373dd80df444ab88eb8c447155e70f`;
local exit receipt `/tmp/eom-image-joint-release.FLrlFoWI/image-provider-regression-result.json`
reports0. The generated PNGs remain explicit private test-workspace outputs, not registered
Items, published images or NAS artifacts. Model runs1; training steps/production Jobs0.

The separate actual trainer BUSY case preserved original FAILED/no ACK, MainPID0/store0,
empty cgroup and no training result/output. Its harness deliberately remains **FAILED**:
it required a bare stable error line, while the installed CLI emitted
`eom_image_trainer.runner.TrainingRunnerError: IMAGE_TRAINING_GPU_BUSY`. A bounded
read-only inspection of the same invocation `30aef179dae24d0aaa23af7b14ca24dc` confirmed
this classification; no second trainer unit or model was submitted to hide it.
Evidence: `.../trainer-busy/`; local original failure and read-only receipts:
`trainer-busy-regression-result.json` / `trainer-busy-readonly-result.json` in the same
temporary operator directory. Dataset/plan pointers were explicitly absent negative
fixtures, not approved data or real Artifact authority; they were never dereferenced.

Two source tests reproduced the typed pre-lease exception escaping the CLI. A single
presentation boundary now maps `TrainingRunnerError` to its existing stable SystemExit
code, preserving argparse/unknown failures and all locking, cleanup and no-retry behavior.
Related source regression188 PASS21.32s, strict mypy1/Ruff/format PASS. An initial command
named a nonexistent test file and ran no tests; the corrected inventory above is the
reported result. This correction is **source-only until coordinated trainer installation**.
Crash/timeout and successful trainer execution, six actual CPU/CUDA benchmark launches,
conditional default activation and C1–C5 operational acceptance remain open.

#### Trainer-only installed correction — 2026-10-17 05:56 UTC

The preceding source-only status is superseded for this one CLI correction, not for the
remaining regression/benchmark gates. Candidate `bf533010e2524aca151492b44a62ee3277fd57d4`
passed the standard four-wheel trainer build. Diff from installed e232 image sources is
exactly the eight-line CLI boundary; standalone lease, image contracts/provider, models,
dependencies, root owner/entries/templates and numerical prefixes are unchanged.

Before mutation, the existing protected coordinator captured rollback wheel/source backups,
verified current package RECORDs and candidate dependency/source closure, fenced all19
image entry templates, rechecked zero live processes/stored FDs/jobs/cgroups, and held both
legacy and shared physical leases. It reinstalled **only** the trainer wheel, then verified
the complete installed trainer cohort/source and unchanged19 template/config pins before
removing the fence. Old failed execution/history/receipts were never modified or retried.

Trainer wheel raw SHA:
`b39ff7807150165e177e655b13dfa9429589b5e602f83b560dcc8b1ee3fc18cc`.
Standard build directory:
`/tmp/eom-image-trainer-build/bf533010e2524aca151492b44a62ee3277fd57d4.9YjBGb/dist`.
Protected coordinator raw SHA:
`200a4446970d3d77e1619da2a1ab93f7daf33a46737a0dd828368077a2300d78`.
Evidence/rollback:
`/opt/eom/image-joint-runtime-releases/imagejoint-a610b0c7/trainer-cli-boundary-bf533010/`.
Local no-replay exit receipt:
`/tmp/eom-image-joint-release.FLrlFoWI/trainer-cli-boundary-result.json` (`returncode=0`).

A separate installed CLI negative ran under the real UID984 with the original private
negative input and another owner's physical lease held. It returned exactly code1 and
`IMAGE_TRAINING_GPU_BUSY` stderr, with no stdout/traceback, new unit, model, dataset read,
training step or output. A second claimant remained BUSY while the parent's held lease
stayed valid; no GPU clients appeared. This is actual presentation/pre-lease evidence,
**not** a successful training/model run or a rerun that turns the historical unit green.
Post-release unit readback shows no drop-ins, RefuseManualStart=no and no reload pending.
CPU remains default; CUDA benchmark/default, successful trainer/crash/timeout and consumer
operational gates remain incomplete under the original full goal.

## 5. 별도 protected CUDA 실행 leaf

제안 prefix는 `/opt/eom/conda/envs/eom-embedding-cuda`, worker는 `eom-embedding-cuda`,
staging은 `/run/eom-incremental-embeddings`다. 이름은 새 fixed runtime 설계이며 현재 존재나
activation의 주장이 아니다. 기존 CPU prepare/stdio와 같은 root-staged regular FD 입력/출력,
O_EXCL/immutable invocation·uncertain 규칙을 재사용하고 indexing의 exact 계약만 허용한다.

CUDA unit은 `NoNewPrivileges=yes`, capability/ambient empty, private network/tmp,
ProtectSystem=strict/ProtectHome, AF_UNIX only, read-only runtime/model pointer mounts,
DB/NAS/repository/auth/other worker homes/image models/owner staging/systemd/Docker socket denial을
유지한다. CPU의 `PrivateDevices=yes`를 몰래 수정하지 않는다. 새 CUDA unit만
`PrivateDevices=no`, `DevicePolicy=closed`와 `/dev/nvidia0`, `/dev/nvidiactl`,
`/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools`의 exact rw allow를 사용한다. 다른 GPU/render/device를
막고 character node identity와 실제 DAC open을 검사한다. node access에 필요한 권한을 확인하지
않고 video/render/eom group을 추가하지 않는다. GPU-visible environment는 owner의 pinned
UUID→cuda:0 mapping이며 `cuda.is_available()`는 fallback selector가 아니다.

초기 BGE resource profile 제안은 CPUQuota400%, threads4, TasksMax64, RAM6GiB,
VRAM measured cap8GiB, single batch-size4, one invocation180s다. VRAM8GiB는 admission/측정
gate이지 systemd MemoryMax로 강제되는 GPU quota라고 주장하지 않는다. 공개 source의 2048-token
상한까지 별도 long-input capacity probe를 통과해야 이 전체 bound를 활성화할 수 있다.
OOM/driver failure로 batch·dtype·token ceiling을 자동 축소하지 않는다.

CUDA backend는 legacy와 동일한 FP32 parameter/buffer, eager attention, eval/inference mode,
exact tokenizer IDs/mask/padding, pooling을 사용한다. batch tensor만 cuda:0로 옮기고 pooled
FP32 결과를 host로 가져와 기존 host L2 recipe와 f32 codec을 적용한다. autocast/fp16/bf16,
TF32, quantization, Flash/SDPA, torch.compile, token truncation은 없다.
`set_float32_matmul_precision("highest")`, matmul/cuDNN TF32 false, cuDNN benchmark false,
deterministic algorithms true와 `CUBLAS_WORKSPACE_CONFIG=:4096:8`을 고정·read-back한다.
지원되지 않는 deterministic kernel은 실패이며 warn-only로 우회하지 않는다.
[PyTorch precision](https://docs.pytorch.org/docs/2.7/notes/cuda.html#tensorfloat-32-tf32-on-ampere-and-later-devices),
[deterministic 설정](https://docs.pytorch.org/docs/2.7/generated/torch.use_deterministic_algorithms.html).

## 6. 실행 전에 pin하는 작은 benchmark protocol

benchmark JSON Schema2020-12/frozen request·result를 먼저 정의한다. actor 권한은 owner가
설정하며 worker가 role/DB URI/원본 path를 받거나 정본 eligibility를 추정하지 않는다.
성능 gate를 아래 값으로 사전 고정하고 result를 본 뒤 기준/표본/반복을 바꾸지 않는다.
변경이 필요하면 새 benchmark recipe revision과 승인으로 재시작하며 원 실패를 보존한다.

| 구분 | 고정 workload/반복 | 측정과 통과 조건 |
|---|---|---|
| synthetic | public synthetic 8행: 짧은 한국어/수식·단위·부정/동일문장 duplicate/빈·overflow negative; valid batch1/4 | tokenizer IDs·length/mask 동일, overflow reject, ordered finite dimension/norm |
| 실제 bounded input | 공식 Catalog/Orchestrator로 현재 승인·재인가한 정확한 6 profile×available3 view 최대18 document와 exact2 query; token-length 층화 후 안정 ID 순서; 최대20 valid text | source/report/Graph/policy/model/recipe/input-set SHA를 실행 전에 pin; 부족하면 INSUFFICIENT, 무단 대체 없음 |
| cold process | device별 독립 fresh invocation3회, 순서 CPU→CUDA→CUDA→CPU→CPU→CUDA | owner admission→staging→load/hash/tokenize/encode→f32 validate→local result 검증까지; startup/load/encode 구간 분리 |
| warm encode | cold 첫 invocation 내부에서 unmeasured warm-up1회 후 같은 full batch5회; CPU/GPU 같은 반복 | 실제 같은 process/model instance일 때만 warm; production warm cache로 해석 금지 |
| query/ranking | 그 warm instance에서 query2개 각각 batch1 5회; fixed document matrix로 기존 exact rank; self exclusion·duplicate/tie fixture | query encode 및 full retrieval end-to-end 별도; 아래 수치/순위 gate |
| capacity | synthetic bounded long input 최대 token2048, batch1/4 각1회; 위 실측 중 peak 관측 | RSS≤6GiB, peak reserved 및 whole-process GPU usage≤8GiB, OOM0, 다른 GPU consumer와 중첩0 |

실제 입력은 corpus 내용이나 IDs를 외부 검색/Slack/Git에 보내지 않고 staged local manifest만
worker에 전달한다. benchmark output/긴 log/수치 member는 Orchestrator 검증 후 공식 Artifact
commit 경계로 보관하고 Git에는 코드·recipe·작은 aggregate pointer 요약만 둔다.
기존520개/1560 view 전체를 CPU/GPU 각각 재실행하는 benchmark가 아니다.

CPU primary baseline은 immutable historical `2.7.1+cpu` stack의 **동일 encoder recipe**다.
vector benchmark 계약을 historical env에 추가 설치하지 않는다. 필요한 CPU benchmark/indexing
stdio는 별도 protected CPU successor prefix에 동일 CPU wheel/library pins로 설치한다.
cu128 wheel의 CPU mode는 optional controlled diagnostic이며 primary CPU baseline을 대체하지
않는다. 양쪽 weights/tokenizer upstream+모든 file SHA 및 실제 tokenized input은 같아야 한다.

CUDA wall-clock은 구간 전후 `torch.cuda.synchronize()`로 측정하고 CPU transfer/host L2까지
포함한다. CUDA event kernel 시간은 보조값이다. `perf_counter_ns`, integer microseconds,
texts/s의 numerator/denominator, process peak RSS와 max allocated/reserved VRAM, owner의
bounded `nvidia-smi` process/whole-device 관측을 구분한다. cache·driver memory가 allocated
tensor 수치와 다르므로 allocated만으로 capacity PASS하지 않는다.
여기서 cold는 fresh process/model load이며 OS page-cache cold나 machine reboot 상태를 뜻하지
않는다. host cache drop을 수행하지 않고 위 교대 순서와 cache 상태 한계를 기록한다.
[CUDA timing과 memory 의미](https://docs.pytorch.org/docs/2.7/notes/cuda.html).

## 7. 사전 correctness·성능·resource gate

- 출력 rows/order/차원, float finite·비영 norm, binary length/hash와 f32 L2 norm absolute error
  `≤1e-5`는 양쪽 각각 필수다. original exact input/token IDs가 달라지면 비교 자체 불합격이다.
- CPU/GPU 대응 vector의 cosine `≥0.99999`, normalized component 최대 absolute difference
  `≤1e-4`, 모든 측정 query-document cosine absolute difference `≤2e-5`를 요구한다.
  device 간 raw-vector SHA 일치는 요구하지 않는다. numerical space는 항상 별개다.
- CPU score gap `>4e-5`인 모든 candidate pair의 상대 순서는 같아야 한다. 그 이하 gap은
  predeclared near-tie cluster로 처리하며 cluster 간 순서는 같고 exact tie는 기존 stable-ID
  tie-break를 따른다. top5 boundary에서 다른 멤버는 그 동일 near-tie cluster 안에만 허용한다.
  모든 swap과 gap을 기록하며 임의 top-K overlap 비율로 실패를 숨기지 않는다.
- same-device 반복에서도 위 tolerance와 순위 gate를 통과하고 worker input/hash drift가 없어야
  한다. determinism 설정이 CPU/CUDA bit-identical을 보장한다고 주장하지 않는다.
  [PyTorch 재현성의 한계](https://docs.pytorch.org/docs/2.7/notes/randomness.html).
- **GPU superior**는 warm full-batch encode median `≤CPU median×0.80`, fresh cold end-to-end
  median `≤CPU median×0.90`, single-query encode 및 query end-to-end median 각각
  `≤CPU median×1.10`을 모두 만족하는 것이다. cold3회의 max와 warm/query5회의 max도 기록하고
  어느 fresh GPU 실행도 CPU cold max의1.20배를 넘지 않아야 한다. 작은 표본의 p95를
  통계적 SLA로 주장하지 않는다. hash/load/serialization 포함 개선과 kernel-only 개선을 분리한다.
- 모든 sandbox denial, exact physical lease/cgroup termination, capacity 상한 및 image/trainer
  경합 회귀가 PASS여야 한다. staged image synthetic/canary는 gate용 별도 승인된 opt-in
  실행이며 production 이미지 생성이나 모델 학습을 benchmark에 몰래 추가하지 않는다.
- 비교 recipe/token ceiling 또는 batch가 installed capacity와 다르면 자동 확대하지 않는다.
  warm만 빠르고 cold/query가 위 gate를 실패하면 CPU를 유지하고 원인을 기록한다.
  GPU가 올바르고 빠른 것을 교육적 품질·recall·과학적 정확성 PASS로 해석하지 않는다.

## 8. 기본 GPU 전환·fallback·rollback

correctness/performance/resource/isolation/image regression을 모두 통과하면 compatible released
bundle/runtime/schema/launcher/owner admission policy를 설치·검증한다. bounded GPU delta를
공식 Artifact owner로 commit하고 CUDA space만 포함하는 index revision을 검증한 뒤 expected
version CAS로 current를 전환한다. source coverage·권한 재인가·query route를 같은 GPU space로
pin하고 native execution policy의 `default_device=CUDA`를 실제 활성화한다. CPU vectors와 CUDA
vectors를 같은 index에 혼합하거나 CPU query vector를 CUDA document index에 사용하지 않는다.
query/document purpose space의 명시적 compatible family closure도 검증한다.

GPU busy/unavailable은 실행 전 명시적 `WAIT_FOR_GPU`가 기본이다. GPU admission 실패만
사전 released policy가 허용하는 경우 **완전한 별도 CPU space/index**로 fallback하고 선택 device,
reason, policy revision을 기록한다. CPU index가 없으면 partial/unavailable이지 implicit latest가
아니다. hash/permission/schema/finite 오류, OOM 후 uncertain 실행이나 lease expiry를 CPU retry로
성공 처리하지 않는다. owner는 동일 workflow/attempt/input-set operation key를 reconcile한다.
공유 physical lease·전체 image entrypoint migration을 구축할 수 없다면 기본 CPU를 유지하며
CUDA shadow/benchmark도 미입장 처리한다. 좁은 lease-group gate를 우회하거나 보호 CPU 환경을
바꾸지 않는다. 그때 CPU-only native successor를 먼저 검증·활성화할 수 있으나 GPU 비교·기본
전환 요청은 명시적으로 미완료다.

이전 CPU index/current policy와 model/runtime pointer를 보존한다. rollback은 새 admission을
drain하고 active GPU 작업 종료를 확인한 뒤 policy와 current pointer를 compatible CPU cohort로
함께 되돌린다. CUDA Artifact·실패·revision은 삭제하지 않는다. 보고는 `SOURCE_PASS / INSTALLED /
ACTIVE / LIVE_VERIFIED`를 구분하며, 실제 default policy read-back·delta/replay·권한 재인가·
GPU query provenance·CPU rollback 증거가 없으면 완료가 아니다.

## 9. access pattern·transaction·테스트·구현 순서

primary operation은 exact runtime/payload key lookup, immutable descriptor hash, single-resource
nonblocking claim, bounded ordered encode, O(Nd) exact cosine, append-only execution evidence다.
small frozen descriptor/tuple, member map/set, 한 local flock와 기존 indexed queue를 사용한다.
lease claim은 O(1), model hash는 admitted immutable payload당 한 번 streaming O(bytes), batch
output은 O(Nd)이며 각 text마다 weights를 다시 hash하지 않는다. GPU memory는 token length와
batch를 포함해 실측한다. 새 vector DB/large binary column/lease DB table/전역 cache는 없다.

source/permission/Workflow claim transaction과 GPU 실행을 분리한다. DB transaction을 inference
동안 열어두지 않고 source 재인가→Artifact commit→binding/index CAS는 기존 receipt/idempotency
reconcile을 사용한다. 모델/code/runtime drift, stale pointer, 권한 철회, shared lock mismatch는
explicit stable failure다. 결과가 commit됐으나 metadata가 실패하면 같은 Artifact pointer로
재등록하고 재인코딩하지 않는다. uncertain launch는 새 execution ID로 우회하지 않는다.

구현 순서는 (1) bundle/runtime/benchmark JSON Schema와 frozen model 및 closure negative tests,
(2) stdlib physical lease adapter와 provider/trainer regression·drained installed migration,
(3) 별도 CPU/CUDA protected runtime/stdio/verifier와 FP32 backend,
(4) synthetic→bounded 실제 CPU/GPU benchmark,
(5) 우수 시 CUDA index successor·default policy 활성화·delta/query/rollback 검증이다.
각 단계는 formatter/linter/strict type checker와 focused tests를 통과해야 다음 gate로 간다.

필수 테스트: legacy CPU1.0 bytes/behavior 불변, payload 누락·stale/hash/schema/media/lifecycle·
permission mismatch, bundle successor/동일 weights file-set, no model byte duplication,
runtime fingerprint의 관련 numeric 변경 반영/무관 commit 불변, CPU/CUDA space 혼합 거부,
exact token/overflow/pooling/L2, false TF32와 eager/FP32 read-back, CUDA async timing,
lease 양방향 contention·trainer 참여·wrong inode/mode/GID·no worker create/write,
SIGTERM/SIGKILL/timeout/잔존 cgroup·uncertain/replay, device allow/deny·DB/NAS/network/auth denial,
default activation/fallback reason/compatible rollback, no core ML import/ambient Python/runtime Git.
live model/privilege/GPU/image tests는 명시적으로 marked opt-in이며 unit fake PASS를 대체하지 않는다.

단순 `.to("cuda")`나 CPU env의 pip upgrade는 immutable history·runtime proof·physical capacity를
깨고, root wrapper만은 crash fence를 닫지 못한다. 이미 두 native image lock 진입점이 있으므로
작은 공유 OS adapter와 기존 owner queue/fixed unit을 확장하는 것이 새 scheduler나 GPU service보다
작은 변경이다. 승인·호환 release·검증 가능한 같은 인코딩 모델을 유지할 수 없는 gate에서
멈추고 실제 limitation을 기록한다.

## 10. 첫 protocol-only checkpoint — source 계약, runtime 미구현

첫 additive source 계약은 `schemas/knowledge/embedding-runtime-bundle-v1.schema.json`과
동일 packaged mirror, `packages/catalog_contracts/eom_catalog_contracts/embedding_runtime_bundle.py`다.
JSON Schema2020-12를 먼저 작성하고 frozen 값·순서/중복/hash/closure 검증을 구현했다.
이 checkpoint는 filesystem resolver, CUDA backend, runtime 설치·lease migration·benchmark나
default activation을 구현하지 않는다. 기존 released model/spec/EmbeddingSpace/input bytes는
변경하지 않는다.

`EmbeddingRuntimeBundle/1.0`은 기존 `payload_model_spec`와 typed `payload_pointer`를 참조하고,
같은 logical model/upstream/file set/weights/tokenizer/모델 recipe를 갖는 별도의 flat
`execution_model_spec` revision을 담는다. 실행 revision/runtime pins/manifest hash만 달라질
수 있다. 큰 weights bytes나 filesystem path/actor 권한은 포함하지 않는다. 작은 metadata
manifest 두 개는 기존 flat ModelSpec compatibility와 exact closure를 위한 값이며 payload
canonical 파일을 복제한다는 뜻이 아니다.

`EmbeddingNumericalRuntimeDescriptor/1.0`은 encoder/host-L2/f32-codec 구현 pin, numeric library
distribution pins, Python/device architecture·CUDA capability/driver/build, FP32/eager/무절단·
precision/deterministic flags, batch/thread recipe를 고정한다. sorted unique tuples와 작은 frozen
값을 사용하며 hash에는 무관한 Git/platform release/경로/worker authority를 넣을 수 없다.
직렬화에는 floating JSON number를 쓰지 않는다. 실제 installed code·library·device·flag의
일치는 **다음 trusted adapter stage**가 검증한다. 모델이 보낸 descriptor를 신뢰하지 않는다.

flat execution ModelSpec1.0은 구조상 기존 EmbeddingSpace1.0에 넣을 수 있으므로 이를 위해
released space/input schema를 고쳐야 하는 것은 아니다. 하지만 trusted native adapter가
**owner가 구성한 exact bundle**, 기존 payload manifest와 file hashes, actual runtime descriptor,
space model/device/runtime hash 및 batch/thread recipe를 함께 검증한 뒤에만 사용할 수 있다.
현재 legacy directory resolver의 `manifest == spec` 규칙은 그대로다. flat successor를 legacy
directory에 전달해 그 검사를 무시하거나 runtime mismatch override를 추가하지 않는다.

bundle의 `bundle_sha256`은 자기 필드를 제외한 semantic hash이며 `bundle_raw_sha256`는
canonical manifest 전체 bytes의 hash다. committed `manifest_member.sha256`는 바로 그 bytes를
참조하므로 raw hash와 같아야 한다. 두 field의 의미가 다른 것과 같은 bytes에 대한 raw/member
hash가 같다는 사실을 구분한다. model revision, model manifest semantic/raw SHA와 file-set SHA도
별개다. payload의 기존 canonical/newline flavor는 exact raw pin으로만 인정하며 자동 정규화하지
않는다. pure helper는 작은 manifest bytes만 검증하고 존재·permission/lifecycle·설치 상태를
검증한 것으로 보고하지 않는다.

synthetic 회귀는 immutable legacy SHA, bundle/model/hash 분리, 관련 numeric 변경의 fingerprint
변화, source release 필드 거부, 동일 payload successor, missing/duplicate numeric pins,
dtype/TF32/compile/overflow tricks·bool/float integer coercion·stale pointer·raw/hash/schema/media
오류와 frozen instance bypass를 다룬다. 실제 weights/GPU/network/DB/NAS를 실행·해석하지 않는다.

## 11. 내부 성능 판정 값 — activation이나 worker wire contract가 아님

`embedding_device_comparison.py`는 §6–7의 고정 성능 기준만 계산하는 pure application 값이다.
canonical source는 owner가 측정한 cold3/warm5/query2×5 구간이며, 독립 lifecycle/Artifact인 척
하지 않는 frozen 내부 값으로 받는다. ordered tuples와 constant-size median/cross multiplication을
사용하므로 시간/공간 O(1)이다. float ratio 반올림으로 threshold를 통과시키지 않는다.
각 query의 median을 별도로 비교하여 한 질문의 회귀를 다른 질문의 개선으로 숨기지 않는다.

이 함수는 DB/파일/모델/권한/등록/트랜잭션·retry를 다루지 않고 numerical correctness나 resource
PASS를 추정하지 않는다. 입력 tag/count/type mismatch는 실패다. 실패 reason과 실제 median을
반환하며 `CUDA_PERFORMANCE_SUPERIOR`도 device 활성화 명령이나 전체 gate PASS가 아니다.
미래 benchmark worker 메시지는 §6의 JSON Schema를 먼저 정의하고 이 내부 값을 owner가
materialize해야 한다. 현재 primitive는 wire JSON을 수신하거나 benchmark를 실행하지 않는다.
단순히 warm 처리시간 하나만 비교하는 대안은 cold/query 비용과 tail 회귀를 놓치므로 부족하다.

## 12. Native backend·INDEX owner protocol successor — source only

2026-10-18 UTC. 이 단계는 원 설계의 **실측 우수 시 GPU 기본 전환**을 위한 작은 계약
경계다. GPU 승리·설치·실행·기본 활성화 또는 physical lease PASS의 증거가 아니다.

1. **책임:** 기존 INDEX owner의 CPU 전용 선택을 명시적인 CPU/CUDA 값으로 확장한다.
   launcher, Workflow/Job family, source authority와 실행 state machine은 바꾸지 않는다.
2. **canonical source:** protected owner configuration과 별도로 발행된 기존 native policy,
   runtime bundle·설치 receipt가 원본이다. 계약에는 모델·vector bytes를 복사하지 않는다.
3. **identity/revision:** backend selection1.0과 INDEX owner3.0을 additive하게 추가한다.
   owner1.0/2.0 schema bytes와 해석, 현재 CPU 선택 및 immutable 이력을 보존한다.
4. **pointer 검사:** CPU는 기존 verifier source/raw SHA와 CPU environment raw SHA를,
   CUDA는 기존 `RootLocalNativeConfigurationPin`의 logical/revision/raw/semantic SHA,
   receipt raw SHA와 CUDA environment raw SHA를 보유한다. 실제 존재·설치·권한·device/
   lease/ACK/종료 증명은 다음 trusted adapter의 책임이며 DTO가 이를 승인하지 않는다.
5. **access pattern:** 닫힌 purpose/device 선택과 단일 runtime profile key lookup이다.
   INDEX는 INDEX purpose만 허용하며 선택 device와 profile device가 일치해야 한다.
6. **구조:** frozen discriminated union과 최대3개의 ordered namespace tuple을 사용한다.
   기존 verifier 값은 새 backend 계약으로 옮기되 원래 import alias와 의미를 유지하여
   owner↔backend 순환 의존을 만들지 않는다. 새 registry/framework/dependency는 없다.
7. **규모/복잡도:** backend 선택·최대2 policy profile 비교는 O(1), namespace 검사는
   최대3개다. 기존64KiB owner 상한과 작은 backend canonical-byte 상한을 적용한다.
8. **transaction/concurrency:** pure parser는 DB·파일 선택·claim을 실행하지 않는다.
   향후 owner는 현재 policy를 resolve한 후 default/profile/backend 일치를 확인하고,
   기존 drain·Identity/grant·encoding reservation·Registry CAS 경계를 그대로 사용한다.
9. **dependency:** workflow/domain은 기존 Catalog contract와 identifiers만 참조한다.
   infrastructure CUDA backend pin, SQLAlchemy, Torch, subprocess를 import하지 않는다.
10. **실패/idempotency:** schema/hash/purpose/profile/forged-copy 불일치는 닫힌 오류다.
    CPU fallback, latest 치환, 재키잉, launch 또는 activation을 parser에 넣지 않는다.
11. **단순 대안:** policy `default_device`만 바꾸거나 CPU guard를 제거하면 실제 고정
    launcher/device lifetime을 선택하지 못한다. 이번 단계는 그 계약만 정의하며 실제
    CUDA INDEX→public/private QUERY→정확한 CPU historical read/rollback은 별도 구현과
    genuine6회 성능·정확성·공유 lease gate 이후에만 활성화한다.

Source checkpoint: backend1.0/INDEX owner3.0 schema와 packaged mirror, frozen model,
canonical parser/public export 및 resolved policy의 semantic SHA/default/profile 일치 검사가
추가되었다. 기존 `parse_local_indexing_owner_configuration`은1.0/2.0 전용이다.
별도 `parse_supported_local_indexing_owner_configuration`만3.0 pure value를 읽으며,
현재 CPU runtime은3.0을 DB engine/queue claim 전에 거부한다. old verifier import alias와
1.0/2.0 raw schema SHA·canonical bytes는 그대로다. Source focused7suite187PASS,
strict4/Ruff5/format5이며 실제 GPU 실행·default/retained CPU read/rollback 증거가 아니다.
기존 multiview scheduler fixture에는 별도 CPU scheduling-read seam과 mock engine만 보완했고
business rule을 변경하거나 실패 case를 deselect하지 않았다.
