# GraphRAG·증분 임베딩 첫 구현 checkpoint

기록: 2026-10-12 UTC. 소스 기준: `165b0214a8c8812fe5e4d24e5a8b266ea345dbb6`.
기준 설계: [전체 goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).
**전체 goal은 진행 중이다.** 아래 source/임시 DB PASS를 운영 인덱스 완료로 확대하지 않는다.

## 구현·실행 완료 범위

- native Workflow definition/request와 encoding input/result를 JSON Schema2020-12 및 frozen
  Pydantic으로 정의했다. 과거 agent Workflow/역할 계약 bytes·의미는 유지한다.
- encoding key는 storage partition + numerical space + 실제 text hash다. source/profile/Graph
  association은 별도로 검증하며, Graph-only 변화와 동일 text는 벡터를 재사용하는 pure delta
  계획을 만든다. 이 계획만으로 background 권한이나 Job admission이 생기지 않는다.
- float32-LE row-major bytes와 integer-only JSON manifest를 분리한다. raw SHA/shape/finite/L2
  norm을 검증하며 저장된 bytes를 재정규화해서 손상을 숨기지 않는다.
- injected backend의 모델/runtime 일치·ordered result closure와 local output을 검증하고,
  기존 `ControlFileSetPublisher`를 통해 `result.json`, `shard.json`, `vectors.f32`를 한 번 게시한다.
  logical encoder Job과 publisher Job/Artifact/Artifact revision/hash는 구분한다.
- formatter/linter PASS, strict mypy 관련 source15개 PASS, focused source 회귀 **598 PASS**.
  숫자는 한 번의 통합 suite 결과이며 개별·과거 suite와 합산하지 않는다.

## 실제 disposable PostgreSQL 증거

official lifecycle의 marker/owner/schema 검증을 통과한 임시 DB만 사용했다.
source migration `20261010_0051`의 upgrade → downgrade1 → upgrade와 head 확인 PASS.
공식 runner의 신규 `embedding-tests` action에서 합성 입력으로 **2 PASS (6.22s)**:

- 실제 owner publication, 세 member/outer manifest·pointer·SHA·binary read 검증;
- 동일 key replay가 기존 inode/mtime/bytes를 유지하고 다른 bytes는 conflict로 거부;
- 서로 다른 spawn 프로세스/engine의 동시 publication이 한 Job/Artifact/revision으로 수렴;
- PostgreSQL approved-row UPDATE/DELETE trigger가 실제로 거부;
- Job/Artifact/revision/event DB row에 원문 text·raw vector bytes/float arrays가 없음.

앞선 동일 두 케이스의 thread 기반 실행도2 PASS였으며 위 실행은 독립 process 검증으로
보강한 결과다. 수치를 합산하지 않는다. pytest 임시 local artifact paths만 사용했고 운영
DB·NAS·원 기출·모델에는 쓰지 않았다. 모델/GPU 실행0회. 검증 후 guarded cleanup으로
정확한 임시 DB/owner role/상태 파일을 제거했다. 삭제된 것은 재생성 가능한 테스트 자료이며
운영·historical evidence를 삭제한 것이 아니다.

## 아직 완료·활성화하지 않은 범위

| 경계 | 상태 |
| --- | --- |
| vector/binding/index 계약·pure encoding/delta·owner Artifact path | SOURCE_PASS |
| 위 owner publication/replay/concurrency | DISPOSABLE_DB_PASS |
| Catalog 영속 encoding/binding/index registry·CAS·missing-binding query | 구현 중, 아직 미배포 |
| exact-key reservation·native Runner admission/executor·자동 reconcile | 미연결 |
| scoped indexing service identity/권한·현재 source 재인가 | 설계 필요 경계 명시, 미활성 |
| CPU/CUDA bundle·보호 runtime·공유 physical GPU lease | 설계, 아직 실제 설치/실험 전 |
| GPU 성능·수치/검색 일관성·기본값 활성화·rollback | NOT_EVALUATED / NOT_ACTIVE |
| 최초 영속 seed·실제 source delta·소비자 연결 | 미실행 |

계약상 index1.0은 view별1024 bindings 상한이다. 미래 corpus를520으로 고정하거나
truncated 결과를 전체 coverage로 표시하지 않는다. 큰 corpus/paging과 empty snapshot은
명시적 successor가 필요하다. 과거 operator ID나 permission hash를 상시 background 권한으로
사용하지 않는다. source/model/policy latest를 조용히 대체하지 않는다.

GPU가 정확성·성능·격리·image/trainer resource gate에서 우수하면 기본 CUDA 활성화까지가
이번 goal이다. CPU와 GPU numerical space는 분리하고 기존 CPU 환경·payload·이력·rollback은
보존한다. 실제 benchmark/activation 증거 없이 GPU가 더 빠르거나 기본값이 됐다고 보고하지 않는다.

다음: schema-first registry/registration → supported native work/source admission → 실제
seed/delta/replay → 공통 후보 소비자 연결·GPU 비교/선택 → compatible release/live 검증.
교과서 chunk/PDF matching/ANN/대화 삭제 부록은 별도 후속 범위다.

## 후속 source checkpoint — 2026-10-12 17:20 UTC

등록 command/result와 exact receipt closure, pointer-only Catalog 관계4개, source migration
`20261012_0052`, payload를 복제하지 않는 runtime-bundle/numerical descriptor 계약을 추가했다.
이는 registration application/native Runner/현재 source authority/CUDA backend를 활성화하지 않는다.
이 후속 source 전체 gate는 **720 PASS (18.15s)**, 새 파일8개 strict mypy PASS,
Ruff format/lint 및 diff check PASS다. 기존598 PASS와 합산하지 않는다.

새 별도 marker-guarded DB에서0052 up/down/up 및 combined Artifact/registry **7 PASS (7.10s)**.
registry5개는 encoding/source binding/index head/revision의 happy relation, unique·composite FK,
append-only guards·fenced head CAS와 nonempty downgrade 거부를 실제 PostgreSQL에서 검증했다.
DRAFT Item/REQUESTED analysis를 사용하는 합성 FK fixture는 DB 관계 존재가 승인/eligibility를
보장하지 않는 것을 명시한다. source/member authorization과 registry use case의 동시 생성·
query-plan/limited-role gate를 완료했다고 보고하지 않는다. 해당 임시 DB와 상태도 guarded
cleanup으로 제거했다. 운영 DB migration은 실행하지 않았다.

첫 실행은3 PASS/4 FAIL: protocol fixture가 Job보다 먼저 flush되지 않은 FK 오류였다.
test fixture의 저장 순서만 수정한 뒤 위7 PASS를 얻었다. 기존 immutable history를 고치거나
production state machine을 수정하지 않았다. 통합 source 첫 실행의719 PASS/1 FAIL도
새 additive schema2개가 frozen predecessor inventory에 포함된 test 분류 문제였다.
기존295/296 resource count/hash/bytes 기대값은 그대로 보존하고 새 successor만 분리했다.

GPU 준비: [공식 metadata·고정 download lock](../architecture/INCREMENTAL_EMBEDDING_CUDA_PACKAGE_LOCK.md)의
25개 exact wheel을 별도 private local wheelhouse에 `pip download --no-index --no-deps
--only-binary=:all: --require-hashes`로 준비했다. advertised byte budget은3,848,835,734이고
다운로드 exit0로 요구한 raw wheel hashes가 확인됐다. CPU 환경·모델 payload는 변경하지 않았다.
이것은 full model/protocol runtime 설치·RECORD 검증·CUDA import/추론/benchmark/lease/default
activation의 증거가 아니다. 독립 archive/FD 검사와 별도 보호 staging·offline 설치가 다음 gate다.

기존 operator deployment callback은0051에 명시 고정되어 있다.0052 운영 배포 전에는
historical0051 의미를 보존하는 compatible successor/release gate가 필요하며, 현재 후보가
기존 배포 callback으로 자동 설치된다고 주장하지 않는다. consumer·service authority·paging
미구현 상태와 전체 goal 진행 상태는 위 표와 동일하다.

## CUDA prefetch·closed release successor — 2026-10-12 17:48 UTC

앞 단계 registry/runtime-bundle source는 `7928df34`에서 게시했다. 이후 read-only offline
inspector가25개 wheel의 raw SHA·정확한 filename/byte count·metadata/tag·dependency closure와
bounded ZIP 구조/held FD epoch를 독립 검증했다. 실제 receipt·source SHA 및 mutable prefetch
한계는 [package-lock 증거](../architecture/INCREMENTAL_EMBEDDING_CUDA_PACKAGE_LOCK.md#8-later-authorized-prefetch-exact-raw-hashes-and-offline-structure-pass)에
기록한다. weights/runtime 설치나 GPU 실행은 하지 않았다.

historical0051 context/schema/callback을 변경하지 않는 별도 release-operator1.1 context와
`MIGRATION_VERIFY_0052` / `MIGRATION_UPGRADE_0052` literal callback을 추가했다.
target은0052, 허용 upgrade predecessor는0051에만 고정하며 `head`나 arbitrary command는 없다.
source/context/receipt/head mismatch는 DB construction 전에 거부한다.
[0052 successor note](../architecture/RELEASE_OPERATOR_MIGRATION_0052_SUCCESSOR.md)를 참조한다.
이것은 보호 operator context admission·운영 migration·role/bootstrap·배포의 실행 증거가 아니다.

새 inspector55개와 exact release successor/legacy boundary 회귀를 함께 실행하여
**167 PASS (2.16s)**, 관련5개 strict mypy 및 Ruff/format/bash parsing PASS다.
기존720개 suite와 겹치므로 합산하지 않는다. 잘못 지정한 nonexistent test path와 초기 mypy
module-name invocation 오류는 source 수정 없이 올바른 경로/explicit package bases로 재실행했다.
whole goal과 GPU 기본값은 여전히 IN_PROGRESS / NOT_ACTIVE다.

## 공유 physical-GPU adapter·성능 판정 — 2026-10-12 17:54 UTC

small stdlib `eom-gpu-lease` adapter와 provider/trainer exactshared branch를 구현했다.
root-provisioned tmpfs readonly inode만 claim하며 create/write/chmod나 기존 private directory의
권한 확대가 없다. independent-process contention, last-dup-close, process death, inode/mode
drift, 잘못된 group/mount 및 모든 FD cleanup을 합성 경로에서 검증했다. 기존 legacy lock와
optional module 부재 시 import는 유지하며 shared 선택은 fail-closed다.
source 검증은 실제 group/unit provisioning, cgroup/driver cleanup 또는 whole-unit ownership
증거가 아니다. 이미지 배포의 standalone wheel closure·전체 entrypoint drain/migration은 후속이다.

pure 성능 판정은 사전 고정한 cold3/warm5/query2×5 integer microseconds를 별도로 비교한다.
정수 cross multiplication으로 boundary rounding을 피하고 두 질문의 회귀를 평균으로 숨기지 않는다.
성능 PASS를 correctness/권한/자원/활성화 PASS로 바꾸지 않는다. 미래 benchmark wire schema와
실제 protected-runtime 측정은 아직 pending이다.

기존 provider/trainer와 새 lease/performance gate를 함께 실행해 **169 PASS (32.28s)**.
strict image-test mypy6파일/Ruff/format/diff PASS다. source-path 없는 초기 mypy invocation은
정확한 경로로 수정·재실행했으며 production/source workaround를 추가하지 않았다.
read-only `nvidia-smi`는 RTX5080/driver580.126.09/VRAM16303MiB/사용2MiB/util0%를 보고했다.
이는 관측 시점 상태이며 CUDA 실행·capacity admission/성능증거가 아니다. 현재 모델/GPU
추론은0회, 운영 기본값·legacy CPU 환경·model payload는 그대로다.

그 뒤 native owner가 private 구현에 접근하지 않고 실행 전후 lease metadata를 확인하도록
public nondestructive `assert_valid()`를 추가했다. close도 같은 규칙을 재사용하며 lease/권한을
새로 취득하는 함수가 아니다. closed/drift 및 경합 유지 두 케이스를 포함한 동일 gate는
**171 PASS (32.27s)**, strict mypy6/Ruff PASS다. 앞선169 결과와 합산하지 않는다.

## standalone lease wheel의 local build/import — 2026-10-12 17:57 UTC

게시된 `cdb8cb8362809d86a8a855498d717d9e30375876`의 정확한 package archive에서만
`eom_gpu_lease-0.1.0-py3-none-any.whl`를 offline/no-deps/no-build-isolation으로 만들었다.
소스 worktree와 운영 prefix에는 build/install하지 않았다. wheel의6개 member, dependency0,
Python3.11/3.12 bound, raw SHA와 모든 RECORD digest/count를 검사하고 별도 임시 site에
offline/no-deps/no-compile 설치한 뒤 isolated import를 확인했다. Torch/Transformers/image
service import와 production lock claim은 없었다.

build 위치: `/tmp/eom-gpu-lease-wheel.jvzfDpXy`.
wheel raw SHA: `5d7ee6850447871dec556c21e1a16f3822e0748fa4ab6052a19cbd3184fbef89`.
이는 developer-owned private temporary 설치 simulation이며 immutable root quarantine·실제
runtime 설치/권한·shared physical migration을 통과했다는 뜻이 아니다. source build/archive와
생성된 wheel을 구분하고, 운영 시 exact wheel/source closure를 다시 검증해야 한다.

## native bundle resolver·CPU/CUDA encoder source — 2026-10-12 18:16 UTC

owner가 구성한 exact bundle과 canonical legacy payload를 재사용하는 작은 resolver, lazy
CPU/CUDA FP32/eager encoder를 추가했다. 기존 CPU resolver·released manifest와 payload bytes는
변경하지 않았다. module-level ML import·다운로드·DB/NAS 접근이 없으며 같은 weights를 새
model revision directory에 복제하지 않는다. protected implementation 파일은 bounded nofollow
read로 한 번 hash하고 이후 immutable epoch만 확인한다.

actual Python/import version·device/precision/determinism/thread/model/tensor와 tokenizer
IDs/masks/padding/overflow, host-L2/f32 및 동기화 경계를 검사한다. request의 batch/thread도
actual backend와 실행 전후 비교하여 runtime SHA만 맞춘 다른 recipe를 거부한다.
trusted installed-distribution observer와 CUDA ownership이 없으면 입장하지 않는다.
현재 그것들의 실제 설치 구현·stdio/launcher/권한/admission은 pending이므로 fake observer
PASS를 설치·GPU 실행·활성화 PASS로 보고하지 않는다.

새 resolver/backend·기존 CPU·계약·codec·injected encoder 회귀 **371 PASS (5.77s)**,
strict core mypy9파일 및 Ruff/format9파일 PASS다. 첫 schema exception은 stable error wrapping으로
수정했고, root strict tests에서 발견한6개 fixture typing 오류는 checked non-None path와 typed
local로 수정했다. blanket ignore나 runtime workaround는 추가하지 않았다. 전체 설정의 optional
image dependency/기존 SDXL type 오류를 이 범위의 PASS로 확대하거나 임의 수정하지 않았다.

Catalog application 동시성 테스트용 새 marker-guarded DB의0052 up/down/up와 prerequisite
검사는 PASS다. 아직 application test 완료 증거가 아니며 해당 임시 DB는 검증 후 guarded
cleanup해야 한다. 운영 DB/schema/payload/default에는 변경이 없다.

## Catalog application·native descriptor gate — 2026-10-12 18:46 UTC

source registration/replay/CAS application과 bounded missing-binding anti-join을 추가했다.
동일 operation의 immutable 결과를 재사용하며 현재 head는 잠금 뒤 새로 읽는다. CAS 실패는
savepoint 전체를 되돌려 부분 metadata가 남지 않는다. Graph-only association은 재검증하되
같은 numerical space/text는 기존 encoding을 재사용한다. 검증 port가 없으면 DB 존재나
FK를 승인 근거로 쓰지 않고 거부한다. 현재 port의 production source/Artifact owner 구현과
background 목적 권한은 아직 연결되지 않았다.

batch contract validator는 기존 scalar 의미/schema bytes를 보존한다.1,024 bindings가 한
shard를 공유하는 operation-count 검증에서 binding/entry 각1,024회, shard parse1회,
full-shard hash2회다. 기존 scalar 반복의 O(B*R) 경로를 O(B+E+R)로 정리했으며 caller의
"already validated" 주장이나 영속 eligibility cache는 없다.

native descriptor leaf는 root-created regular input/result/vector FD를 별도로 검증한다.
입력 검증 전에는 backend를 만들지 않고, binary fsync 후 canonical completion JSON을
기록한다. alias/mode/owner/flags/offset/epoch/hash/result drift와 partial write·context exit
실패는 성공이나 재인코딩으로 처리하지 않는다. 결과의`shard.json`은 기존 Artifact owner가
한 번 물리화한다. 이 source leaf에는 실제 fixed launcher/worker identity/runtime composition이
없으며, 합성48케이스는 설치·GPU/CPU 모델 실행이나 cgroup 정리 증거가 아니다.

root 통합 source gate는 **296 PASS (14.41s)**, 관련10파일 strict mypy 및11파일 Ruff/format,
testdb runner bash parsing PASS다. earlier suite와 합산하지 않는다. 최초 source invocation의
누락 PYTHONPATH는 invocation만 수정했고, 새 proof schema로 달라진 inventory는 historical
296개 bytes/count/hash를 보존한 채 새 schema만 분리했다.

같은 guarded disposable DB에서0052 up/down/up/prerequisite와 combined gate
**13 PASS (17.60s)**: Artifact2+registry5+application6. 실제 독립 process들의 same-key first
creation은 한 revision, competing successor는 한 CAS advance로 수렴했다. stale Session
identity-map 재전송·savepoint rollback·3-statement bounded lookup도 검증했다.

앞선 full run 두 번은12 PASS/1 FAIL(17.75s/17.67s), diagnostic 한 번은1 FAIL/12 deselected
(3.16s)였다. 모두 composite index 이름을 추측한 테스트 오류다. 실제 DB는 tiny fixture에서
`ix_embedding_binding_encoding`의 indexed equality와 나머지9 equality filters를 선택했다.
chosen installed B-tree/table/key 및 exact10 predicates와 composite unique index availability를
분리해 검증하도록 수정했으며 production planner 선호/성능을 주장하지 않는다.

검증 후 같은 operator sudo pane의 guarded cleanup으로 정확한 임시 DB/owner/state를 제거했다.
제거 대상은 재생성 가능한 테스트 자료뿐이며 원 corpus·운영 DB·NAS·모델·historical acceptance는
보존했다. 운영 migration/배포·GPU inference는0이며 기존 기본 device도 그대로다.

다음은 official current-operator source/Artifact verifier 연결, installed numerical observer와
image standalone dependency closure → scoped native admission/launcher → CPU/CUDA 실제 비교·
기본값 결정·seed/delta/공통 소비자 연결이다. 전체 goal은 계속 ACTIVE다.

## Index Artifact 게시·복구 및 실제 CUDA layout 확인 — 2026-10-12 UTC

기존 `EmbeddingArtifactStore`와 `ControlFileSetPublisher`에 단일 `index.json` 게시를 연결했다.
logical index/revision과 Artifact/revision/raw hash는 분리하며, 같은 index/revision key의
body 변경은 충돌이다. exact Graph/policy/shard/predecessor와 순서·space·row 참조를 검사한다.
vector/source/report를 복제하지 않으며 approved control Artifact를 원문·Item 승인으로
해석하지 않는다. 현재 사용자/source 재인가와 최종 Catalog 검증은 별도 필수 경계다.

root 독립 source 검증 **230 PASS (6.09s)**, 관련 strict mypy4·Ruff5·format5·bash parsing
PASS다. marker-guarded 새 disposable DB의0052 up/down/up와 prerequisite PASS 후 combined
**16 PASS (21.68s)**: 기존 Artifact2 + 새 index3 + registry5 + application6. 서로 다른
process의 동일 key 생성은 한 canonical Artifact로 수렴했고, file commit 후 중단된
COMMITTING job은 supported replay로 기존 inode/Artifact를 유지하며 복구했다.

같은 operator sudo pane의 guarded cleanup으로 재생성 가능한 해당 테스트 DB/owner/state를
제거했다. cleanup exit0이며 원 corpus·운영 DB·NAS·모델·historical acceptance는 보존했다.
구체적 테스트 경로·실행 결과는 기존 API disposable database 문서와 index publication note에
기록한다. 이전296/13 gate와 새230/16 gate를 합산하지 않는다.

별도 numerical observer/resolver/encoder/codec/historical contract root source gate는
**442 PASS (6.95s)**다. 이는 합성 fixture 검증이며 actual installed proof가 아니다.
실제 다운로드 archive25개는 lock raw SHA와 일치하지만 numerical16개 점검에서 Torch의
492개, Triton의33개 zero-byte directory member가 RECORD에 생략되는 정상 layout을 발견했다.
regular file hash/size closure는 일치하며 현재 observer는 directory member를 거부한다.
미출시 검사기의 이 좁은 호환성만 보정한다. 누락된 CPU/base wheel은 설치 완료로 간주하지
않는다. Torch의 upstream `torchfrtrace` entrypoint target은 archive에 없으며 임베딩에서는
사용하지 않고 동작을 주장하지 않는다. 운영 설치·migration·추론·기본값 변경은 아직0이다.

native Runner의 source-plan과 실제 owned-subset launch 입력을 분리하는 protocol-first
후속안을 검토했다. 기존 queue/claim/Job을 재사용하고 Codex 슬롯·role·인증을 흉내 내지
않는다. operator seed와 향후 background service 권한은 분리하며 실제 service policy가
없으면 자동 실행을 활성화하지 않는다. GPU 비교와 우수할 경우 기본값 전환은 전체 목표의
필수 작업으로 유지한다.

## Image standalone lease dependency release closure — 2026-10-12 UTC

기존 provider/trainer build/deploy의 legacy7/11 인자는 보존하며 exact standalone lease
wheel와 raw SHA를 successor 옵션으로 받는다. fixed helper SHA의 root-private copy만
실행하고 admission 전에는 pip·계정·unit을 변경하지 않는다. wheel namespace/RECORD와
installed lease의 단일 owner를 검증하며, root prefix의 Conda metadata hardlink 예외와
canonical lease single-link 규칙은 구분한다. shared physical lock/group/device migration은
이 leaf가 수행하거나 PASS로 선언하지 않는다.

root 재검토에서 확인한 archive preallocation·subprocess stdout·unchecked bytecode 문제는
held-FD bounded ZIP32 central-directory 선검사, metadata stdout/deadline/kill/reap/FD cleanup,
registered/unregistered/sourceless lease bytecode 거부로 수정했다. bytecode를 자동 삭제하거나
hash 검증을 건너뛰지 않는다. installed ownership 검증이 최초 image import probe보다 앞선다.

root 독립 release fixture **81 PASS (0.95s)**, explicit image-test 환경의 lease/adapter를
포함한 **130 PASS (2.23s)**, strict mypy2·Ruff/format2·bash4 PASS다. 두 gate는 중복되므로
합산하지 않는다. helper의 source raw SHA는
`231089d320a70a41272c006ccca38e1c68014fccfba2ff61feb1515ca5699300`다.
실제 이미지 runtime 설치/권한·lease 전환·GPU 실행/default activation은 여전히 pending이다.

## Numerical installed-proof observer의 source 완료 — 2026-10-12 UTC

JSON Schema2020-12·동일 packaged mirror·frozen proof를 먼저 정의한 뒤 exact retained raw
wheel/RECORD/installed byte closure, nofollow 파일 snapshot, fixed Linux interpreter/device
관측을 분리했다. configured proof pointer는 owner 입력이며 worker의 descriptor 주장을 그대로
돌려주는 observer가 아니다. numerical hash에는 무관한 GUI/Git 전체 release를 넣지 않는다.
단일 immutable 초기 검증 뒤에는 file/namespace epochs를 재검사하며 권한을 cache하지 않는다.

실제 Torch/Triton archive에서 확인한 zero-byte canonical directory 호환성을 좁게 추가했다.
directory는 실제 regular payload의 ancestor여야 하며 duplicate/link/nonzero/unrelated,
file-directory 충돌과 RECORD file/hash/size 누락은 거부한다. proof1.0 schema 및 historical
296 Catalog schema bytes/count/hash는 그대로다. directory를 skip하며 파일 closure를 약화하거나
upstream wheel을 다시 만드는 방식은 사용하지 않는다.

root 동일 observer/resolver/backend/codec/historical suite 재검증 **461 PASS (7.10s)**,
strict mypy11·Ruff/format11 PASS다. 앞선442에 directory 케이스를 추가한 재실행이며 합산하지
않는다. 실제 protected prefix/proof 생성, 전체 환경 ABI/RECORD와 device/cgroup/sandbox,
shared physical migration, native launcher와 CPU/GPU 추론은 별도의 pending gate다.

기존 numerical 버전4개의 공식 small METADATA를 재조회해 protected CPU METADATA와 같은지
확인하고 exact URL/SHA를 common download lock에 기록했다. 별도 임시 폴더의 downloaded4
raw hash·inventory·총32,014,410 bytes가 독립 검사로 일치했다. primary baseline CPU Torch도
기존 exact URL/SHA의175,833,687-byte archive를 별도 임시 폴더에 준비해 raw SHA를 확인했다.
HEAD403은 그대로 기록하고 공식 index의 동일 URL/hash·bounded Range GET206으로 availability를
확인한 뒤 pip의 hashed cache body로 준비했다. URL/version/flavor 변경이나 설치·모델 실행은
없었다. archive regular-file/RECORD layout 검사는 후속 receipt에서 별도로 보고한다.
