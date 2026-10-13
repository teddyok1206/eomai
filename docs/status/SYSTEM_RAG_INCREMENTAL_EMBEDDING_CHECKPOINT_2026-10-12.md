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

## Current-source·report·Artifact registry verifier — 2026-10-12 UTC

기존 official source capture/admission/projection에 caller의 Catalog root Session용 additive
operation과 bounded Artifact read context를 연결했다. index/shard/result/vector의 exact
canonical bytes와 same-file-set/hash/row closure를 검증하고 등록·조회·재전송 때 현재 실제
사용자 및 pin된 원문·report·Graph·policy를 다시 확인한다. 같은 numerical vector가 있다는
사실은 source 사용 권한이 아니다. 원래 independent read-only capture/reuse 동작은 보존했다.

1,024 members를 처리하는 synthetic operation-count 검증에서 metadata query3회와 manifest
hash1회이며 member당 SQL/full-manifest hash를 반복하지 않는다. Session/root transaction/thread,
revision/member/aggregate byte ceiling을 확인하고 초과는 file IO 전 거부한다. 해석된 bytes는
request-local일 뿐 권한 cache·DB binary·새 Artifact 정본이 아니다.

root 독립11-suite gate **177 PASS (16.64s)**, strict mypy10·Ruff/format10 PASS다.
첫 tests-included strict run의6개 fixture typing 오류는 typed simulation boundary와
`monkeypatch.setattr`로 수정했고 production override·blanket ignore를 추가하지 않았다.
actual immutable temporary files와 simulated source/IAM ports를 사용한 source 검증이다.
실제 revoke-vs-register concurrency와 production 권한을 통과했다는 뜻이 아니다.

Identity owner의 required fence interface만 있으며 concrete security helper/grant/default
composition은 없다. 누락 시 검증·member read/write 전에 명시적으로 unavailable이다.
Catalog에 IAM UPDATE 권한을 주거나 기존 advisory lock만으로 password reset까지 보호된다고
주장하지 않는다. 별도 reviewed official IAM seam과 실제 disposable revoke tests가 다음 gate다.

## CUDA prefetch의 선할당 상한 수정·실제 재검증 — 2026-10-12 UTC

기존 offline inspector의 같은 held FD에서 ZIP32 EOCD/central bytes·actual header count를
검증한 뒤에만 `ZipFile` 객체를 만든다. count/byte/ZIP64/comment/multidisk/malformed 입력과
실패 FD cleanup은 source **73 PASS (0.17s)**, strict mypy2·Ruff/format2 PASS다.
별도 새 private receipt로 실제25개 raw hash/총3,848,835,734 bytes, bounded structure/metadata/
dependency와 named/FD epochs를 확인했다. 이전 receipt/source hash를 새 코드 PASS로
덮지 않았다. exact receipt/hash는 CUDA package-lock 문서 §10에 기록한다.
이 결과는 실제 설치·전체 RECORD·GPU 권한·추론/default activation의 증거가 아니다.

## Numerical compressed-tag 호환성·dependency 준비 — 2026-10-12 UTC

실제 safetensors archive의 compressed WHEEL tag와 filename은 같은 두 tag의 표현이다.
이전 observer의 raw-line 비교를 bounded Cartesian expansion 후 exact-set 비교로 수정했다.
subset/architecture 변환이나 PEP600 alias 추측은 하지 않는다. count·길이·component·aggregate
상한은 product 할당 전에 검증한다. 원 archive·schema·dependency·설치 이력은 변경하지 않았다.

root 동일 observer/resolver/backend/codec/historical suite **488 PASS (7.42s)**,
strict mypy2·Ruff/format2 PASS다. agent의 broader520/source117 gate와 합산하지 않는다.
실제 numerical5 archive 진단의 원 receipt는 pre-tag-fix evidence로 그대로 보존하며,
설치 proof나 GPU/CPU 모델 실행 PASS로 재분류하지 않는다.

reviewed shared lock의 나머지41 dependency archive **48,245,185 bytes**도 private mutable
prefetch에서 exact inventory/raw SHA/leaf epoch를 독립 확인했다. 기존 CUDA/common9 파일을
중복 다운로드·정본 복사하지 않았다. 이 결과는 root quarantine, 전체 RECORD closure,
protected interpreter 또는 설치 admission이 아니다. 이후 owner가 독립 재검증해야 한다.
운영 migration/설치·model/GPU 실행0, default activation은 여전히 NOT_ACTIVE다.

## Native admission protocol 정본·독립 root 검증 — 2026-10-12 UTC

request1.1/source-plan1.0/encoding-job1.0/execution-policy1.0의 additive JSON Schema2020-12와
byte-identical packaged mirrors, frozen Pydantic 및 public validation/owner-port를 검토했다.
released request1.0·role/definition/execution protocol bytes는 보존한다. wire에 source/vector
bytes나 worker authority/lease secret을 넣지 않고, computational encoding key와 original
Workflow/plan·owned subset·shared committed row pointer를 구분한다. 서비스 audit는 읽을 수
있지만 실제 background grant는 여전히 명시적으로 unavailable이다.

root 독립 native/legacy8-suite **475 PASS (15.94s)**, no-install package-resource **5 PASS
(4 deselected,4.40s)**, strict mypy8·Ruff/format8 PASS다. metadata-only zero-demand coverage는
fake empty native Job/Artifact를 만들지 않는다. copied/constructed bool-integer bypass,
exact coverage/pins, overlap computational key와 raw/semantic hash 경계를 검증했다.
이는 DB 동시성·Runner claim/launch·현재 사용자 인증·IAM fence·GPU 실행 증거가 아니다.
해당 behavior와 compatible release/GPU 비교는 다음 단계이며 전체 goal은 ACTIVE다.

## Fixed CPU/CUDA bootstrap source와 base assembly — 2026-10-12 UTC

새 두 prefix 전용 snapshot bootstrap은 root-private byte-tree/hash/link/mode 확인 뒤에만
exact `bin/python3.12 -I -S -B`를 실행한다. 기존 experiment helper 함수/상수 AST와 shell bytes는
그대로다. public dependency graph54/CPU55/CUDA70과 별도 private source/wheel pin을 검증하며,
원 모델 bytes·권한·units·factory·DB는 변경하지 않는다. root 독립4-suite **275 PASS (4.27s)**,
strict mypy2·Ruff/format2·bash syntax PASS다. agent broader299와 합산하지 않는다.

새 branch의 private ZIP32 실제 header/count/central 상한은 `ZipFile` 할당 및 기존 wheel
검증 전에 적용한다. 모든 private EOM namespace의 registered/unregistered/unchecked `.pyc`와
scan을 우회하는 내부 symlink를 거부한다. bootstrap의 끝은 INSTALLED_NOT_ADMITTED/NOT_PROBED이고
numerical proof·full-prefix/ABI·worker 권한·launcher는 독립 후속 gate다.

실제 fixed Conda base31 **56,222,902 bytes**의 raw SHA와 leaf epochs를 확인했다. 승인된 기존
sudo 인증을 재사용해 reviewed shell hash의 root-private copy로 새 두 빈0700 developer prefix만
준비했다. CPU base는 non-root explicit/offline/copy assembly exit0, Python3.12.13 read-back이다.
CUDA base도 같은 exact local archive manifest로 non-root assembly exit0과 Python3.12.13을 확인했다. private platform/
numeric wheels·protected publication·model/worker/GPU 실행은 이 단계에 없으며 기존 prefix와
모델을 덮거나 복사하지 않았다. base assembly는 protected runtime 설치/입장 PASS가 아니다.

## Public archive prerequisite와 첫 실제 실행 보존 — 2026-10-12 UTC

후속 non-root wheel assembly의 `direct_url.json`이 처음부터 canonical retained archive URI를
가리키도록 기존 snapshot helper에 fixed public-retention entry를 추가했다. 실행은 이미
보호된 기존 CPU experiment Python3.12.13의 isolated/no-site/no-bytecode stdlib만 사용하며,
mutable API Python이나 새 developer prefix interpreter를 root로 실행하지 않는다.
공유 bounded filename map에서 exact CPU55/CUDA70만 선택하고 solver/network/model은 없다.

첫 실제 CPU retention은 임시 source child directory가 group-writable775여서 안전 검사에서
거부됐다. CUDA 단계는 실행하지 않았고 archive payload를 게시하지 않았다. 실패한 root-private
helper와 로그, 최초 empty SHA reservation은 보존한다. 원 archive bytes/hash는 그대로 유지한
채 해당 eom-owned input child만0700으로 제한했다. 별도로 root umask077에서 신규 cache root가
0700으로 생성되는 버그를 재현/수정했다: 신규 root만 명시적0755로 게시하고 기존 wrong-mode
root/incomplete reservation은 자동 복구하지 않는다. 재실행 전 exact empty reservation의
복구 가능한 이동과 cache mode 검증을 별도 기록한다.

root focused bootstrap/legacy/CUDA preallocation source gate **303 PASS (2.35s)**,
strict mypy2·Ruff/format2 PASS다. 이전 gate와 중복되어 합산하지 않는다. 실제 public retention,
numeric/private wheel installation, protected snapshot/proof, 모델·GPU 실행과 default activation은
이 기록 시점에는 아직 PASS가 아니다.

## Public archive recovery와 non-root numerical assembly — 2026-10-12 UTC

검증된 exact empty reservation을 원 root-private failed snapshot 아래
`failed-empty-reservation`으로 복구 가능하게 이동했다. 최초 실패 helper/log와 빈 폴더는
삭제하지 않았고 cache root만 검증 후0755로 제한했다. 수정된 raw-pinned root-private helper의
bounded retry1에서 CPU55/CUDA70 exact public archives의 retention이 모두 PASS다. common archive는
SHA별 한 canonical 파일이며 CPU/CUDA별 중복 정본을 만들지 않았다.

정확한 retained `file:///opt/eom/embedding-runtime-archives/...` URI와 raw SHA를 명시한 임시
lock으로 새 CPU/CUDA prefix의 public wheel assembly가 각각 non-root/offline/no-deps/
require-hashes/no-compile/no-cache exit0이다. 모델 import·추론·GPU 실행은 없다. public install
성공은 private current-source wheel, protected publication, numerical proof, full-prefix/ABI,
worker sandbox/identity/lease admission 또는 default 활성화 PASS가 아니다.

## Identity-owned current operator fence와 Catalog savepoint composition — 2026-10-12 UTC

Identity의 고정 definer routine text·읽기 전용 installed owner/ACL/privilege inspection과
PostgreSQL adapter를 source로 검토했다. 실제 ACTIVE operator를 같은 READ COMMITTED root
transaction에서 row-fence/refresh하고, private weak root witness만 실제 nested 재확인에 쓴다.
이 witness는 권한·session 인증·saved operator ID grant가 아니다. 만료/로그아웃/폐기 session은
공식 owner transport의 별도 필수 인증 경계로 남는다. SAVEPOINT 전에 Catalog authorize_scope를
배치하여 rollback이 최초 row fence를 풀지 않도록 수정했고 Identity 오류는 artifact 오류로
오인하지 않는다. frozen 역사적 protocol/schema/원 operator 데이터는 수정하지 않았다.

root 독립9-suite **471 PASS (15.96s)**, strict mypy10·Ruff/format10 PASS다. subset184 및 기존367
결과와 겹치므로 합산하지 않는다. prepared limited-role integration6은 source/collection만
준비되었으며 실제 DB 실행·routine 설치·권한 grant·migration·운영 활성화는 아직 없다.

## 후속 guarded DB baseline — 2026-10-12 21:21 UTC

새 disposable DB `/tmp/eom-api-testdb-20261012212033_1dde6544`에서 기존0052
up/down/up·control-plane gate와 ordinary unique runtime reconciliation이 PASS다.
같은 isolated DB의 기존 model-free Artifact/index/registry/application suite는
**16 PASS (23.01s)**다. 이전16 PASS와 중복되므로 합산하지 않는다. 운영 DB/migration에는
변경이 없으며, native encoding 독립-process 경쟁과 limited Identity fence6은 아직 실행 전이다.
이 state는 후속 테스트에만 사용하며 cleanup은 **PENDING**이다. cleanup 전 결과를 전체
cleanup PASS 또는 운영 IAM 설치 PASS로 확대하지 않는다.

## CPU/CUDA 비교 protocol과 encoding reservation source — 2026-10-12 UTC

독립 root 검토에서 benchmark schema/mirror, frozen models, canonical serializers 및
원본 resource freeze를 확인했다. root regression **681 PASS (13.10s)**,
strict mypy6·Ruff/format6 PASS다. 실제 같은 입력의 CPU/CUDA cold/warm/genuine QUERY
측정과 승인된 numerical/performance 조건을 표현하는 계약이지, 측정 결과가 아니다.

encoding 별 기존 Job unique-key reservation, immutable whole-owned-set launch/completion,
fresh scoped replay/read와 선형 batch 검증도 root **237 PASS (19.86s)**,
strict mypy8·Ruff/format8 PASS다. 실제 source/authority/binary verification adapter는
필수 주입 경계이며 자동 service grant를 만들지 않는다. guarded DB 경쟁8은 아직 실행 전이다.
두 suite는 기존 suite와 겹치므로 합산하지 않는다. 모델·GPU 실행0, CUDA default NOT_ACTIVE,
전체 목표 ACTIVE를 유지한다.

## 실제 guarded encoding/Identity DB gate와 cleanup — 2026-10-12 UTC

source helper/harness를 root 독립 **222 PASS (1.06s)**, strict mypy2·Ruff/format3·bash
syntax PASS로 확인했다. 최초 root pytest는 잘못된 fixture filename으로0개 실행됐고,
올바른 고정 목록으로 다시 실행한 위222개만 PASS로 기록한다.

앞서 준비한 exact disposable DB에서 ordinary encoding reservation suite는
**8 PASS (12.00s)**다. 두 독립 프로세스의 동일 key/겹치는 batch 경쟁, 원 Artifact allocation
보존, immutable association/completion/replay, 늦은 fence rollback과 bounded query를 확인했다.
실제 SQL evidence이며, synthetic source/Artifact metadata admission은 실제 NAS/vector proof가 아니다.

같은 DB의 별도 acknowledged `OPERATOR_FENCE_LIMITED_TEMP/1.0` profile preparation,
frozen Identity suite **6 PASS (12.15s)**, exact read-only profile replay가 모두 PASS다.
routine/ACL/TEMP는 해당 unique disposable owner/runtime에만 적용했다. 실제 권한 변경 writer,
savepoint root fence, password/retired session, ACL drift와 TEMP shadow 거부를 검증했고
production routine·role·operator·schema에는 변경이 없다.

실행 로그와 secret-free receipt는 외부 임시 evidence 디렉터리에 보존했다. receipt raw SHA는
`a11723479708a2dcf236275a5e122f9c49b6cd802e9676917d39d978d612e05f`다.
기존 guarded cleanup이 exact marked DB와 전용 두 role/state만 제거하여 **cleanup PASS**다.
앞의21:21 기록의 cleanup PENDING은 이 후속 evidence로 닫힌다. 이전16/8/6/source suite는
역할을 구분하며 중복 source PASS와 합산하지 않는다. 모델·GPU 실행0, protected runtime/
native launcher/default activation PENDING, 전체 목표 ACTIVE다.

## 실제 비교에 사용할 bounded row-ranking source — 2026-10-12 UTC

기존 scalar cosine/`math.fsum`/clamp를 같은 public 함수로 공유하고, actual profile/view/text
ref를 유지하는 별도 ≤18-row ranking seam을 검토했다. query의 모든 view를 제외하고
exact6→5 profile coverage, stable unrounded order와 CPU complete-span≤4e-5 cluster를 검증한다.
transitive close-score chain으로 큰 순위 차이를 허용하지 않는다. raw vector/hash/space,
실제 CPU receipt의 pre-CUDA sealing과 전체 numerical 비교는 후속 owner 경계다.

root source/legacy6-suite **408 PASS (8.36s)**, strict mypy3·Ruff/format3 PASS,
독립 peer read-only review도 완료했다. 첫 test collection의 잘못된 `profile_key` import와
fixture implicit re-export strict 오류를 수정한 뒤 이 최종 source gate를 실행했다.
이는 추가 모델·GPU·Artifact 실행이나 default 활성화가 아니며 기존 installed HOST_L2
bytes/proof를 변경하지 않는다. 새 runtime의 관련 source SHA는 실제 설치 후 별도 관측한다.

## 고정 native runtime config source — 2026-10-12 UTC

CPU/CUDA 고정 profile의 작은 installation config schema/mirror와 frozen metadata를 root
검토했다. config logical/revision, bundle/proof raw·semantic pointers, numerical SHA와 정확한
자원 값/hash를 분리한다. 실행 파일/path/role/권한/default flag는 없으며 config는 admission
증거나 factory가 아니다. raw config pin은 외부의 보호된 owner 설정에서 공급한다.

root는 direct raw validator의 immutable bytes 확인과 negative3을 추가했다. 최종13-suite
**815 PASS (14.34s)**, strict mypy6·Ruff/format6 PASS다. 기존812/227/681/source 결과와
겹치므로 합산하지 않는다. schema/mirror raw SHA는
`f48da8820d2452fe62cfaa8b3401f42abac2f43b94eaf1a18968e5f8492bef5e`다.
실제 model/GPU 실행·새 runtime admission/default activation은 아직0/미완료다.

## 실제 pip wrapper 호환 source와 전체 설치 admission 경계 — 2026-10-12 UTC

실제 pip26.1.2가 생성한 `removesuffix('.exe')` wrapper를 확인하고 기존 두 exact byte
recipe에 세 번째 recipe만 추가했다. shebang·archive entry module/callable·추가 코드 금지와
기존 오류/API를 유지하며, 설치된 wrapper/RECORD를 수정하거나 실행하지 않았다.

root 독립 proof/observer/distribution suite **185 PASS (4.17s)** 및 관련 ten-suite
**456 PASS (6.83s)**, strict mypy3·Ruff/format3 PASS다. 이 회귀 수에는 병행 개발 중인
observer/resolver의 추가 source fixture가 포함되어 있으며, 각 미완료 기능의 운영 PASS를
뜻하지 않는다. 원 wrapper 변경의 독립62-case coverage와 구분하고 겹치는 수를 합산하지 않는다.

전체 설치 admission 설계는 exact31 Conda 원본·재배치·canonical Python cache·host ELF와
고정 도구를 별도로 검증하도록 기록했다. 기존 new-profile publisher의 새 interpreter
첫 호출 전에 **기존 보호된 interpreter의 필수 검증**을 넣는 후속 범위를 명시했다.
actual31 archive와 현재 prefix의 읽기 전용 진단은 설치 admission이 아니며,
정상 canonical bytecode를 blanket 삭제하거나 기존 실험 환경을 변경하지 않는다.
이 전체 admission·실제 CPU/CUDA 측정·CUDA 기본 활성화는 아직 PENDING이다.

## CPU/CUDA 비교의 bounded checkpoint/ACK channel — 2026-10-12 UTC

기존 benchmark1.0의 고정1/21-phase 계약을 변경하지 않고, canonical JSON·4-byte 길이·
64KiB 상한과 단일 absolute deadline을 적용하는 Unix socket adapter를 구현했다.
실제 peer PID/UID/GID와 socket inode를 관측하고 호출자가 제공하는 필수 peer/unit fence와
fresh source/authority/vector continuation fence를 ACK 전에 실행한다. 이 callback의 실제
운영 composition은 별도 필수 gate이며 synthetic fixture의 성공은 권한 증거가 아니다.

독립 peer 검토에서 positive Python socket timeout이 `MSG_DONTWAIT`에도 내부 pre-select를
실행하여40ms 제한을253.7ms로 넘길 수 있음을 재현했다. timeout `None` 또는 `0.0`만 허용하고
callback/IO 전후 다시 검사하도록 수정했다. descriptor 교체·권한 취소·oversize header·
partial frame·EOF·잘못된 hash/order와 실제 독립 unprivileged process 연결도 source로 검증했다.

최종 root benchmark/channel/ranking/기존 native3FD **304 PASS (9.50s)**,
strict mypy4·Ruff/format4 PASS다. 독립 peer channel **53 PASS (6.69s)**는 그 subset이므로
합산하지 않는다. 최초 추가 gate는 잘못된 test filename으로0개 실행됐고 올바른 고정 목록의
위304개를 다시 실행했다. 모델/GPU 실행0, 실제 benchmark/기본 활성화 PENDING을 유지한다.

## native Workflow 완료 receipt protocol — 2026-10-12 UTC

새 step-output과 Workflow receipt의 두 closed2020-12 schema를 먼저 추가한 뒤 frozen
models/parser를 구현했다. step은8KiB pointer carrier만 보관하고,64KiB registration receipt는
별도 owner Artifact를 참조한다. Workflow/step/owner Job·source-plan·등록 command/result·
raw/semantic hash를 구분하며, 과거 receipt의 as-of 관측을 현재 권한/인덱스 상태로 취급하지 않는다.
Codex 역할 결과 union이나 기존 네 admission schema의 bytes/hash는 변경하지 않았다.

root는 직접 schema 검증에도 기존 depth/object/collection guard를 직렬화 전에 적용하도록
보강했다. 최종 독립 eight-suite **390 PASS (46.84s)**, strict mypy5·Ruff/format5 PASS다.
이전382/95와 겹치므로 합산하지 않는다. 이는 protocol source gate이며 Runner dispatcher,
실제 receipt 게시·session continuation·migration0053·model/GPU 실행은 아직 후속 범위다.

## 고정 native factory와 모델 파일 재사용 source — 2026-10-12 UTC

필수 installed-admission과 exact config raw pin을 받는 no-argument scope를 기존 numerical
observer/bundle resolver/backend에 연결했다. 실제 admission 구현·root-installed capture는
아직 없으며, boolean/설정 파일만으로 실행을 허용하지 않는다. CUDA는 관측 전에 실제
ownership handle을 요구하고 factory가 owner lease를 닫지 않는다. stdout/stderr는 null로
전환하고 기존 root-owned3FD index leaf만 재사용한다.

큰 payload는 한 번만 검증하고 동일 원본 snapshot을 재사용한다. root 검토에서 stronger
ancestor epoch가 payload 읽기 **이후**에만 관측되던 순서 차이를 확인해, resolver의 작은
metadata observer seam으로 읽기 전 관측과 읽기 후 재검증을 추가했다. 같은 bytes의 manifest/
ancestor 교체와 구성된 가짜 snapshot은 ML import 전에 거부한다. 예전 constructor는 유지한다.

root 독립 seventeen-suite **961 PASS (16.77s)**와 native11-file strict mypy·Ruff/format PASS다.
shared mechanical adapter도 포함한 겹치는 gate이므로 이전198/515/304 등과 합산하지 않는다.
병행 extraction 중 중간76개 실패는 wrapper filename regex의 잘못된 escaping으로 분류되어
수정 후 위 고정 목록을 다시 실행했다. live 장애·installed acceptance로 재해석하지 않는다.
실제 unit/DAC/source session/whole-prefix admission·모델/GPU 측정·기본값 전환은 PENDING이다.

## 보호된 초기 검증에 재사용할 stdlib wheel closure — 2026-10-12 UTC

기존 typed numerical adapter의 wheel/RECORD/member/wrapper 검증을 하나의 purpose-named
stdlib core로 분리했다. numerical API·오류·결과는 같은 adapter가 유지하며 두 검증기를
복제하지 않는다. 작은 frozen pin은 직접 호출에서도 type/hash/name/bounds/order를 다시
검증한다. 새 core는 기존 file adapter 외에 Pydantic/schema/ML 패키지를 import하지 않는다.

위 root17-suite **961 PASS (16.77s)**에 새 direct-core56개와 실제 `-I -S -B` child import가
포함되어 있다. 해당 source3-file strict mypy·Ruff/format도 독립 PASS다. 기존 initializer/
test fixture를 대체한 stub import가 아니라 실제 file adapter를 사용했다. 이는 새 prefix
전체의 Conda/ELF/host/first-instruction admission 또는 실제 임베딩 실험 PASS가 아니다.
실제 owner admission leaf를 이 같은 검증기로 연결하는 다음 단계는 아직 PENDING이다.

## native 단계 DB guard와 exact0053 release source — 2026-10-12 UTC

기존 Workflow에 native stage와 nullable-safe step CHECK만 추가하는0053 source를 준비했다.
새 테이블/queue/role은 만들지 않는다. native definition·완료된 Workflow·원 요청/receipt 흔적이
남으면 downgrade는 DDL 전에 거부하고 기록을 지우지 않는다. current actor/session/source를
검증할 필수 owner/executor interface는 기본 구현/boolean grant 없이 분리했다. 실제 dispatcher와
현재 인증 continuation은 아직 구현 후속이며 static admission/metadata만으로 실행하지 않는다.

root는 schema1.2를 먼저 작성하고 exact0053 verify/upgrade callback, shell 허용값, source head와
배포 검증을 함께 추가했다. 기존 context1.0/1.1 bytes와0051/0052 callback target은 그대로다.
최종 root native/legacy/release seventeen-suite **579 PASS (46.03s)**,
source11+release6-file strict mypy·Ruff/format 및 shell syntax PASS다. 중간 release141 PASS/1 FAIL은
새 두 literal을 current closed-enum 테스트에 아직 추가하지 않은 원인으로 수정 후 재검증했다.

guarded stage harness/profile source **92 PASS (0.86s)**도 별도로 확인했다. 새18 migration DB
cases는 준비/collection만 완료했으며 **실제 DB 실행은 아직 NOT_EXECUTED**다. source head0053은
production DB migration·설치 release alignment·native 실행·GPU 기본값 활성화를 뜻하지 않는다.
기존0052 disposable8/6/16과 cleanup PASS 증거를 새로운0053 PASS로 확대하지 않는다.

## 실제0053 disposable DB gate와 cleanup — 2026-10-12 23:08 UTC

기존 supported `testdb_prepare.sh`로 만든 exact marked disposable DB에서
`testdb_run.sh migrate`의0053 upgrade→0052 downgrade→0053 upgrade와 현재 head0053,
control-plane routine/trigger 검증이 PASS다. 같은 owner/manifest preflight를 사용하는
`embedding-stage-tests`는 **18 PASS (0.35s)**, skip0이다. nullable-safe native/legacy CHECK,
native history가 남으면 DDL 전에 downgrade 거부, legacy/unrelated history의 보존을
실제 PostgreSQL에서 검증했다. 모든 사례는 outer rollback이며 worker/model/GPU/NAS 작업은 없다.

기존 guarded cleanup이 exact marked DB와 전용 owner/state를 제거했다. optional runtime role은
생성하지 않았고 production DB/role/권한/Artifact는 변경하지 않았다. **cleanup PASS**이며
prepare/cleanup의 비밀값 없는 기록은 외부 임시 evidence 디렉터리에 보존했다. migration/test
결과는 해당 실행의 도구 출력과 이 checkpoint에 기록한다; 별도의 전체 실행 로그를 만들었다고
주장하지 않는다. 앞 절의18-case NOT_EXECUTED는 이 후속 실제 evidence로 닫힌다.

이 결과는0053의 disposable DB acceptance이지 production migration·native dispatcher·전체
설치 admission·실제 CPU/CUDA 속도 측정·GPU 기본값 활성화 PASS가 아니다. 새 모델/GPU 실행0,
기본값 NOT_ACTIVE, 전체 목표 ACTIVE다. 이전 source579/961과 DB16/8/6은 서로 다른 gate로
보존하고 겹치는 테스트 수를 합산하지 않는다.

## 실측용 actual token·resource source seam — 2026-10-12 23:21 UTC

기존 encoder의 tokenizer/padding/forward/host-L2 경로를 공유하는 명시적 observed API를 추가했다.
bounded actual batch/used IDs·mask·types와 input/token hash를 반환하지만, 일반 index encode에는
관측 tuple 생성·hash 비용을 추가하지 않는다. EMPTY는 tokenizer 전 거부하여 token 증거를
꾸며내지 않으며, 고정2048 ceiling의 OVERFLOW만 actual≤4096 count/hash 요약을 제공한다.
CUDA의 누적 allocator peak는 실제 device 읽기와 runtime/lease fence 전후 검사이며,
constructor 이후 peak를 초기화하거나 whole-process/device 관측이라고 주장하지 않는다.

기존 resources1.0 메시지로 완료된1/21 checkpoint 뒤 단 한 번의 owner finalization을 처리한다.
peer/FD/absolute deadline과 immutable canonical local baseline을 유지하고, owner가 worker의
RSS/allocator/OOM/capacity/input/token 수치를 바꿀 수 없도록 검증한다. terminal exchange가
실패해도 완료된 checkpoint는 역사적 증거로만 남으며 resource/admission 성공이 아니다.
actual monitor와 source/session/command continuation 구현은 이 seam의 필수 후속 adapter다.

root independent nine-suite **825 PASS (22.22s)**, strict mypy8·Ruff/format8 PASS다. raw nested
bool 재검증·false overflow·CUDA absent allocator를 root review 후 보강했다. 최초 root test
invocation의 잘못된 legacy filename으로0개 실행됐고, 실제 파일 목록을 확인한 뒤 위 고정
nine-suite만 PASS로 기록한다. agent의 중간812 PASS/1 FAIL은 ordinal3 CUDA fixture가 preliminary
resource를 finalized로 반환한 오류로 분류하여 fixture만 수정했다. source gate를 live 장애나
model 실행으로 재해석하지 않는다.

기존 wire schema·수치 recipe·성능 threshold는 그대로다. 관련 encoder module bytes가 바뀌었으므로
실제 release 이후 implementation/runtime pin을 새로 관측해야 하며 old proof를 재사용 승인하지
않는다. worker leaf/files·실제 설치 admission·CPU/CUDA 모델 실측·GPU 기본값 활성화는 아직
PENDING, 새 모델/GPU 실행0이다. 이전 source 결과와 겹치는 수를 합산하지 않는다.

## native 요청 저장과 atomic submission source — 2026-10-12 23:57 UTC

기존 Runner repository에 exact request1.1 저장·재조회와 actor-bound fingerprint를 추가했다.
기존 role union과 fingerprint·request1.0 history·nullable pins는 보존한다. 실제 주입된 owner와
executor가 없으면 definition/replay 조회 전에 거부하고, 현재 root Session에서 source/권한을
검증한다. zero-demand coverage는 같은 control 검증 후 Workflow/command/Job 없이 반환한다.
신규 Workflow와 원래 START는 기존 savepoint 안에서 원자적으로 생성하며 replay는 원 START를
재사용한다. 저장된 actor/audit는 권한 부여가 아니고 inference/모델 실행은 호출하지 않는다.

root는 최종7-file raw hash를 확인하고 전체 변경을 검토한 뒤 고정17-suite를 독립 실행했다.
**584 PASS (39.50s)**, source/tests6-file strict mypy·Ruff/format PASS다. agent584 PASS는
같은 범위의 별도 실행이므로 합산하지 않는다. legacy Workflow·기출변형 request/dispatch와
native controls/storage/replay를 함께 회귀 검증했다. 실제 DB/claim/dispatcher/runtime activation
검증이 아니며 DB0053의18 PASS와 구분한다. 새 모델/GPU 실행0, 기본값 NOT_ACTIVE,
전체 목표 ACTIVE다. 다음 Runner 작업은 exact claim과 고정 native step dispatch 연결이다.

## Conda31 파일 closure 독립 source gate — 2026-10-13 UTC

고정31 원본 archive에서 source/installed 변환 ledger를 유도하고 기존 wheel 검증기를 재사용하는
read-only adapter를 검토했다. original payload SHA, prefix relocation, canonical CPython cache,
실제 target-owner가 별도로 있는 link와21 licensing member를 구분한다. 파일 관측은 bounded
metadata를 한 번만 읽고 FD/named/ancestor epoch를 재검증하며 expected read에 같은 bytes를
재사용한다. 원본을 추출하거나 cache를 삭제/재생성하거나 설치 metadata로 스스로 승인하지 않는다.

root는 frozen5-file raw hash와 core1457/test1214/CLI58줄 및 runtime-files diff·설계의 전체를
검토했다. 독립 고정15-suite **902 PASS (20.21s)**, strict mypy4·Ruff/format4 PASS다.
agent892 PASS와의10-case 차이는 별도로 개발 중인 CUDA OOM source fixture이며 해당5개 기존
native 파일의 일시적 testable freeze 동안 실행했다. 서로 겹치는 결과를 합산하지 않으며,
미완료 native worker 또는 operational admission의 PASS로 해석하지 않는다.

실제 `-I -S -B` API interpreter child가 current stdlib audit/files/wheel module을 import했다.
그 외 child는 bounded synthetic pipe emitter이며 actual zstd/새 prefix/ML/GPU 실행이 아니다.
standalone CLI는 actual owner/tool admission이 없으므로 module/input 읽기와 spawn 전에 거부한다.
설치 전체의 host/loader/source closure와 기존 보호된 interpreter의 pre-successor instruction
gate, 실제 source/session/launcher 연결, CPU/CUDA 실측과 기본값 활성화는 여전히 PENDING이다.
production DB/NAS/운영 권한 변경0, 새 model/GPU 실행0, 전체 목표 ACTIVE다.

## 기존 보호 CPU bootstrap의 실제 읽기 전용 재확인 — 2026-10-13 00:08 UTC

기존 supported `install_experiment_runtime.sh fingerprint`를 non-root 읽기 전용으로 실행해
historical accepted byte-tree SHA `d0dcd26e841ef583ead382b19269f559a3263a35ce809d34c6308bfe0399ed73`와
현재 tree가 일치함을 확인했다. 정본 역사적 근거는 `ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md`
보호 CPU 설치 절이다. 기존 authenticated tmux `EOM:2 rag-incremental`의 sudo 세션으로 historical
`/opt/eom/.embedding-install-n6SfouPM` root:root0700 및 phase-receipt root:root0600/83 bytes를
재확인했고, 네 단계 QUARANTINE_COPY/STAGED_NOT_ACTIVATED/MODEL_AND_WHEEL_VERIFIED/
INSTALLED_NOT_PROBED가 보존되어 있다. 새 비밀번호·토큰 저장/TTL 변경은 없었다.

같은 protected 기록의 install.py는17,826 bytes/raw
`cb58df1ecca3c8df981b49ad4956e71ae23567ad976056b19198a5429e3f9b5d`, platform.whl은3,144,752 bytes/raw
`a8af46128b50c0110ec21deed2e62a4fa6b5fcf140165c1f8962cc00347deb16`다. 이 검사에서는 기존/신규
interpreter·모델·GPU를 실행하지 않았고 파일/권한도 변경하지 않았다. 기존 independently accepted
bootstrap의 이력·현재 무변경 확인이지 신규 host/tool/전체 prefix admission의 대체 증거가 아니다.

## 고정 CPU/CUDA 측정 worker와 local file source — 2026-10-13 UTC

기존 benchmark1.0·sample program·native encoder/f32 codec를 쓰는 측정 leaf를 추가했다.
모델 constructor와 encode span에서 owner ACK 대기를 분리하고 실제 token/count/hash/right padding,
EMPTY/OVERFLOW 거부, cumulative Linux RSS·CUDA allocator/OOM·필수 host OOM 관측을 기록한다.
host OOM의 oom_kill subset을 다시 더하지 않으며 CPU는 CUDA 관측을 만들어내지 않는다.
OOM=3 같은 실패 관측도 evidence에 보존하며 COMPLETED를 성능·자원 gate PASS로 바꾸지 않는다.

고정 local outputs는 root가 사전 생성한4/16 member만 쓰고 create/truncate/overwrite/reopen을
하지 않는다. 실제 native/controller UID/GID에서 closed DAC/ACL을 확인하며 native worker에
eom group을 주지 않는다. cold/query는 ACK 전에 seal하고, supplementary range는 마지막 SHA가
있을 때만 pointer가 된다. 실패는 이미 seal된 exact prefix만 보고하고 partial bytes를 보존한다.
teardown과 resource roundtrip이 실패하면 성공을 반환하지 않고 cleanup은 owner lease를 닫지 않는다.

root는 frozen10 raw SHA와 production/test 전체·설계를 검토했다. 독립 고정 eight-suite
**619 PASS (37.63s)**, strict mypy9·Ruff/format9 PASS다. agent619 PASS와 겹치므로 합산하지 않는다.
프로그램6개/1-or21 checkpoint와 실제 local FD/합성 ACL·library·owner fixture의 SOURCE gate이며,
실제 설치/UID·unit/cgroup·host OOM provider·source/session continuation·GPU monitor는 미연결이다.
native encoder module bytes가 바뀌므로 실제 release에서 새 implementation/runtime pin을 관측해야
한다. 실제 CPU/CUDA benchmark6 launches·GPU 기본값·seed/delta·소비자 활성화는 아직 PENDING이다.

## 고정 host/tool FD source와 실제 읽기 전용 capture — 2026-10-13 UTC

고정19 OS member·10 alias·loader/NEEDED/SONAME/version·native cache/config/preload/경합 경로의
실제 bytes/epoch를 확인하는 stdlib host adapter를 추가했다. 검증된 executable FD로만 고정
readelf/zstd argv를 실행하며, 기존 Conda reader는 그 필수 spawn seam을 재사용한다. 임의 command/
tool/path callback이나 named-exec fallback은 없다. 실행 파일 FD가 loader/library 전체의 root
변경까지 막는다는 주장은 하지 않으며 실제 유지보수 drain/현재 epoch 경계는 별도로 필요하다.

root는 frozen5 raw SHA, host760/test748·Conda diff/test 변경·전체337-line 설계를 검토했다.
독립 고정16-suite **982 PASS (20.78s)**, strict mypy4·Ruff/format4 PASS다. agent982와 겹치므로
합산하지 않는다. 다른 gate의 소스/합성 결과를 실제 native runtime·모델 성능으로 확대하지 않는다.

추가로 현재 UID1000에서 기존 보호된 CPython3.12의 `-I -S -B`를 사용해 source adapter의 실제
읽기 전용 host capture/assert/close를 실행했다. 별도 supplied source seed raw pin
`6f3e1a144cf8e4c0dbf45af34f05a838305aa4bf35b6f62cc088841313be1d5b`와 실제 보호 파일/alias/cache/
ELF·현재 FD/epoch closure가 PASS했다. **DIAGNOSTIC_CURRENT_HOST_CAPTURE=PASS**이며 root0,
tool spawn0, 신규 prefix instruction0, model0/GPU0다. worktree source를 사용한 non-root 진단이지
protected installed-owner admission이나 권한 grant가 아니며 capture handle은 즉시 닫았다.

CLI/publisher first-successor 순서·전체 public/private/source/prefix closure·final admission/proof와
실제 native 실행·CPU/CUDA benchmark/default·seed/delta/소비자 연결은 여전히 남아 있다.
기존 protected bootstrap/runtime와 production DB/NAS는 변경하지 않았다. 전체 목표 ACTIVE다.

## native exact claim/dispatch와 실제 임시 DB 검증 — 2026-10-13 00:45 UTC

기존 Runner에 목적별 bounded candidate peek→exact claim과 고정 encode_batch/complete 실행
분기를 연결했다. native 준비가 안 된 경우 기존 Codex 작업을 막지 않고, 저장된 audit를 현재
권한으로 쓰지 않는다. 실행 사이마다 짧은 root transaction에서 lease와 필수 owner를 다시
검증하며 inference 동안 SQL transaction을 열어두지 않는다. 기존 상태·queue·역할을 유지하고
새 생산 composition은 여전히 owner/executor 미연결로 명시 거부한다.

독립 재검토에서 두 source defect를 재현·수정했다. parent뿐 아니라 related definition/step의
native marker를 같은 공식 SQL predicate로 분기하여 direct reconcile 우회를 막았다. 잘못된
Pending 응답은 안정적인 OUTCOME_INVALID로 처리하고 성공·새 작업·capacity 해제를 만들지 않는다.
root의 독립21-suite **654 PASS (59.87s)**, strict mypy/Ruff/format11-file PASS다. agent의 동일
654 gate와 합산하지 않는다. harness92 PASS(0.87s), shell syntax/diff check PASS도 별도로 기록한다.

실제 marked disposable DB `/tmp/eom-api-testdb-20261013004344_87e464e3`에서0053 up→0052 down→
0053 up 및 head/control-plane PASS 후, 같은 guarded owner invocation으로 stage18+runner10의
**28 PASS (8.23s), skip0**를 확인했다. 독립 두 process의 동일 command claim 경쟁, row lock,
lease generation/late revocation rollback과 기존 경로 회귀가 포함된다. synthetic owner 콜백은
실제 사용자/source/session 권한 검증의 대체물이 아니다.

supported cleanup PASS이며 해당 disposable DB·표시된 test role/state만 제거했다. 재생성 가능한
시험 데이터였고 canonical Artifact/원본/운영 DB는 건드리지 않았다. sanitized prepare/cleanup은
`/tmp/eom-native-runner-db-evidence.Y1PwbVdO`에 보존한다. 실제 installed native owner/launcher,
CPU/CUDA6회 비교·기본값 전환·seed/delta·공통 소비자 활성화는 PENDING이다. 새 model/GPU 실행0,
production migration/IAM/NAS write0, 전체 목표 ACTIVE다.

## 공통 후보 context·별도 QUERY 계약 source — 2026-10-13 UTC

승인된 reference Item 기준의 공통 context와 production reference-query 입력/결과 계약을
JSON Schema2020-12부터 추가했다. 정본 source/profile/report·Graph/policy·index/space/recipe와
실행 pointer를 구분하며, Graph와 view별 vector 순위는 별도 채널이다. cosine 정수는 표시용이며
확률·승인·정답 타당성으로 쓰지 않는다. 누락된 anchor report·부분 coverage·OPTIONAL과 REQUIRED
미가용·FAILED의 정보 비공개를 명시한다. 기존296개 계약 hash/bytes는 보존했다.

root는 frozen12개 파일·raw SHA 전체와 source/tests를 검토한 뒤 독립11-suite **411 PASS
(13.91s), skip0**, explicit strict mypy·Ruff/format7-file PASS를 확인했다. agent377 PASS는
다른 일부 fixture를 포함한 겹치는 gate이며 합산하지 않는다. QUERY/DOCUMENT 분리와 float-free
정본 JSON은 유지한다. actual actor/source/raw-byte/lifecycle 검증은 기존 owner의 책임이다.

이는 **CONTRACT_ONLY / SOURCE_PASS / NOT_ACTIVE**다. 실제 pinned index read·source authority·
QUERY admission/실행·context compose·기출변형/출제/검토/ChatGPT/25문항 전달은 아직 미구현이며
계약의 목적 enum이 기능 활성화나 권한을 만들지 않는다. model/GPU0, 전체 목표 ACTIVE다.

## 별도 private wheel 후보의 실제 offline build — 2026-10-13 00:55 UTC

root는 worktree/WIP가 아닌 명시적 commit `ba630f1ec9ea23e82030bf5390317bb40ae29f47`의 Git tar에서
non-root·API Conda·`pip wheel --no-index --no-deps --no-build-isolation`로 platform/standalone
GPU lease wheel을 빌드했다. 작업 폴더 `/tmp/eom-embedding-private-release.xnV7hWYH`는0700,
tar와 wheel은0600이다. source tar는 full40 commit directory prefix와 원래 Git metadata를 가진다.

| 후보 | 바이트 | raw SHA-256 | 이번 실제 검사 |
| --- | ---: | --- | --- |
| source tar |54272000|`24cf6b63eebf3fdc6a52ec8e43d19d7ca3ebc8a0ace47af4280cae225475160b`|Git explicit commit archive |
| eom-platform0.1.0 wheel |3444413|`c9c29dda4bab9fb2f0d55c12b8df78d97f5997144602886be7152e24e782081b`|기존 public RECORD verifier PASS |
| eom-gpu-lease0.1.0 wheel |4456|`aac5d47020f208ad6ae30ae04cd533a755e661ce160f4cb74310e5d724ca305c`|ZIP CRC PASS만; full installed/source admission은 미실행 |

두 wheel은 **BUILT_NOT_INSTALLED**이며 root archive retention/보호 prefix/UID·unit·runtime proof/
운영 설치를 변경하지 않았다. 모델/GPU 실행도0이다. 향후 whole-prefix closure에서 실제 source/
RECORD/member와 함께 확인할 후보일 뿐이며 CRC·파일 hash만으로 runtime admission을 만들지 않는다.
현재 읽기 전용 hardware 조회는 RTX5080/16303MiB, used2MiB, driver580.126.09로 확인됐으나
실험 직전 lease/경합 상태는 다시 확인해야 한다. GPU 기본값은 아직 NOT_ACTIVE다.

같은 후보를2026-10-13 00:58 UTC에 **non-root 개발 환경 조립**으로만 설치했다. 실제 UID1000의
CPU/CUDA 전용 prefix는 eom:eom0700임을 먼저 확인했고, `-I -B`/`--no-index --no-deps --no-compile`
pip 설치가 각각 성공했다. CPU는 platform1개, CUDA는 platform+standalone lease2개다. 두 환경의
EOM namespace에 `__pycache__`가 발견되지 않았다. 기존 protected CPU/runtime와 정본 모델은
변경하지 않았다. 새 환경은 **NONROOT_ASSEMBLED_NOT_ADMITTED**이며 root promotion/whole-prefix
허가·actual numerical proof·모델 실행·GPU 기본값·서비스 활성화가 아니다.

## 실제 owner/session 연결의 확인된 경계 — 2026-10-13 UTC

별도 독립 read-only 검토에서 existing 보호 inference-transfer CLI의 FD-only bearer/fixed API
peer와 실제 인증 패턴을 확인했다. generic actor-string CLI와 혼동하지 않는다. 그러나 `/me`와
saved audit는 caller root transaction의 current token/session revocation fence가 아니며, API DB
role은 Workflow/START submission만 지원하고 native claim/step 실행 권한은 없다. 실제 current
Identity provider·SQL role·protected controller와 Catalog/native executor를 연결해야 한다.

확인된 경계와 최소11-decision 계획은
[owner/session 구현 경계](../architecture/LOCAL_EMBEDDING_OWNER_SESSION_IMPLEMENTATION_BOUNDARY.md)에
기록했다. 이는 **DESIGN_ONLY**이며 key 복사·역할 사칭·새 권한 grant·영구 사용자 세션·자동 refresh를
구현하거나 승인한 것이 아니다. source/runtime 준비와 실제 current owner/source/GPU authority를
구분한다. 상시 증분 갱신의 공식 service identity는 별도 남은 필수 경계이며 operator seed만으로
자동화를 완료했다고 보고하지 않는다.

### 실제 developer assembly provenance와 controller metadata의 추가 확인

2026-10-13 01:09 UTC 검사에서 private pip metadata는 실제 `/tmp/.../dist` 원본 URI를 기록했다.
현재 wheel closure는 canonical `/opt/eom/embedding-runtime-archives/<raw SHA>/<wheel>`만
허용하므로 이 developer assembly를 그대로 protected admission에 통과시킬 수 없다. Root는
두 환경의 원래 direct_url/RECORD6개를 explicit small backup boundary
`/tmp/eom-embedding-private-assembly-evidence.gF1fEaPk`0700/files0600에 복사하고 원본과 같은
raw SHA를 확인했다. metadata/RECORD를 고치거나 기존 검증 조건을 느슨하게 하지 않았다.
다음은 지원된 exact canonical archive retention 후 명시적 developer rematerialization이다.
protected promotion/first instruction은 아직 실행하지 않았다. 실제 base 실행 파일의775 mode도
prepublication의 명시적 보호 mode 조립 단계에서 처리해야 하며 성공 증거를 만들어내지 않는다.

별도 readonly controller metadata probe는 실제 installed `eom-workflow-runner` UID에서
`eom_app` role/session_user, superuser=false, bypassrls=false와 operators/api_sessions/api_tokens의
기존 SELECT+UPDATE 가능을 확인했다. default_transaction_read_only로 metadata만 조회했고
secret/token/session 행 내용은 출력하지 않았다. 기록은 existing sanitized evidence 폴더의
`current-runner-role-metadata.log`다. Role/grant·HMAC·current authenticated capture/fence admission을
의미하지 않으며 production write0, model/GPU0이다. 같은 사용자의 기존 sudo pane을 재사용했다.

### Canonical retention 최초 staging 실패와 제한된 복구 계획 — 2026-10-13 01:26 UTC

기존 보호 bootstrap의 `-I -S -B`와 separately pinned root-private helper로 기존 public
`retain_index_archive`를 호출했다. source/dist 디렉터리가775여서 source ancestor guard가
`EMBEDDING_INDEX_SOURCE_PATH_INVALID`로 거부했다. 원래 로그 `private-canonical-retention.log`는
보존한다. 첫 wheel의 SHA 디렉터리 예약만 생성됐고 wheel/source bytes는 아직 게시되지 않았다.
다음 wheel과 source tar의 retention도 실행되지 않았다. 새 prefix·모델·GPU를 실행하지 않았다.

root의 metadata-only 검사에서 정확한 첫 예약은 root:root0700, device64512/inode18488967,
ctime/mtime1791854244358351563, named/FD 동일, children0이었다. 이는 함수의 intake 거부 직전에
생성한 빈 task-owned 임시 예약이며 canonical Artifact나 실행 결과가 아니다. 다음 조치는
이 정확한 empty inode/epoch와 기존 root-private snapshot을 재확인해 예약을 그 snapshot 아래로
recoverable하게 옮겨 보존하는 것이다. 삭제·기존 bytes overwrite·chmod로 성공 상태 위장은 없다.
그 뒤 task-owned source/dist의 group-write만 제거하고 **별도 기록된 재실행1회**에서 같은 raw
pin·지원된 retainer/read-back·parent fsync를 사용한다. 원래 실패를 성공으로 바꾸지 않는다.
어떤 precondition이 달라졌거나 nonempty면 추가 side effect 없이 멈춘다. 전체 목표는 source
구현을 병행할 수 있으므로 ACTIVE이며 이 준비 실패를 production 장애나 모델 실패로 분류하지 않는다.

### Canonical retention와 developer rematerialization 결과 — 2026-10-13 01:30 UTC

위 exact empty inode/epoch/child0 guard와 destination absence를 확인한 뒤 예약을
`/opt/eom/.embedding-index-private-cache-JnNdhehG/partial-reservation-c9c29dda4bab9fb2f0d55c12b8df78d97f5997144602886be7152e24e782081b`
로 옮겨 같은 inode를 보존하고 두 parent를 fsync했다. 삭제된 것은 없다. 필요하면 해당 private
빈 디렉터리와 원 실패 로그로 이 준비 실패를 재현/추적할 수 있다.

task source/dist를0750으로 조립한 뒤, separately pinned helper raw
`d3cc5cb687b222d6d292439d60f945d37c91cb635fda8183d48008c0ea8b3d18`와 기존 protected bootstrap에서
public retainer를 다시 호출했다. 명시적 재실행은1회이며 old log는 그대로다. platform/lease/source
tar의 같은 raw SHA별 canonical 파일3개를 root:root0644로 보관했고 지원된 same-target replay의
read-back hash 검증 및 SHA directory/archive parent fsync가 PASS했다. 로그:
`private-partial-reservation-disposition.log`, `private-canonical-retention-retry1.log`.

그 다음 same raw wheel을 canonical `/opt/eom/embedding-runtime-archives/<SHA>/<wheel>`에서
non-root·offline/no-deps/no-compile로 명시적 재설치했다. 임시 설치였던 private packages만 동일
bytes로 재조립했고 원래 metadata6개와 원본 wheel/source는 보존했다. 새로운 direct_url/RECORD는
pip가 생성한 것이며 직접 수정하지 않았다. 두 환경의 platform direct_url raw SHA는
`367338596055ee94b86c630eaf9cd43aee353140cbad09c789fd50bf281a5242`, lease는
`92c391deeb67a88dd82f5b40961504b87f1f8cf2c2b7abe551232dab971f52d5`다. CPU platform RECORD는
`09fbfd57f11a52df4ff41993409bd93682d540f00500da73e0750dcfeaa62bd4`, CUDA platform은
`593e594eeb86cb8d981e7a08bee92fb50c70ee42a76ab886b00cf9eae8cc35d7`, lease는
`6ac8167efcd40496dd4bebe2eceb4714fd6da2f1c4c791232ec65bc4111e5ba2`다. EOM pycache 없음도 확인했다.

**CANONICAL_ARCHIVES_RETAINED / NONROOT_ASSEMBLED_NOT_ADMITTED**이며 protected promotion,
first NEW instruction, 실제 numerical proof/UID·launcher·GPU lease·성능 비교·기본값은 아직
PENDING이다. Root cache/archive filesystem만 변경했고 production DB/IAM/NAS write0,
model/GPU0다. 기존 protected CPU·정본 모델·서비스는 변경하지 않았다.
