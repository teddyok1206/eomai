# 문항 핵심 착상 전이: 실제 운영 검증 기록

상태 시각: 2026-10-10 16:12 UTC. 이 문서는 실제 설치·실행 증거와 남은 gate를
구분한다. 소스 테스트 통과를 운영 활성화나 사람의 전이 품질 승인으로 확대하지 않는다.

## 보존하는 설계와 범위

- [승인된 설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)의 SHA-256:
  `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`.
- 정본은 기존 승인 문항·기출 분석·풀이보고서 및 pin된 Graph/policy다. 새 비교 표현,
  벡터와 쌍 비교는 보조 파생물이다. 기존 검색·출제·검토·승인 의미를 대체하지 않는다.
- 실제 `guiadmin` 사용 승인을 받았다. 승인은 인증 토큰이나 자격 증명 그 자체가 아니다.
  실제 session과 현재 권한을 검증하기 전에는 corpus를 읽거나 worker를 제출하지 않는다.
- 원래 occurrence-backed 기출 목표 520개를 사용한다. 별도 trusted-RAG canary는 의도적으로
  제외한다. 기존 풀이보고서 520개를 다시 생성하지 않는다.

## Component 상태

| Component | 실제 상태 | 한계 |
|---|---|---|
| 공유 API/platform | 설치 source `ad3ed8caf43f3a4ece5abce25b9b59801451803e`, tree `a974e0754aaa8125cf8d481eda7d3c5cdc29b794`; 16:07:55 UTC 배포 완료 | 비교 owner 경계 설치와 실제 `guiadmin` 인증·자료 조회·비교 실행은 별도 증거 |
| 운영 PostgreSQL | `20261010_0051` migration 및 exact-head 검증 PASS | 새 비교 Workflow stage CHECK 적용이지 비교 control 발행이나 worker 실행이 아님 |
| 별도 CPU Conda | `/opt/eom/conda/envs/eom-embedding-experiment` 보호 snapshot 발행·승인된 격리 probe PASS | 실제 corpus 실험은 별도 gate |
| CPU platform | `06134fcd91413a957ac3133db062dbcdd525ee15` wheel에서 비편집 설치 | d291 candidate와 1,361개 payload member가 일치함; source 표기는 원래 설치값 유지 |
| 최초 API build-only 후보 | `d2917ba448f21b86e7731d8477e802c658c2e106` | 역사적 후보로 보존; 후속 공유 배포는 위 `ad3ed8ca` release |

Component들이 같은 commit이어야 한다고 가정하지 않는다. 실제 파일·wheel·contract
호환성과 설치 provenance를 따로 기록한다. build-only 결과를 live release로 부르지 않는다.

## 보호 CPU 설치의 실제 증거

2026-10-10 15:08 UTC경 보호 snapshot·model·고정 unit·polkit 설치가 완료됐다.

- 고정 runtime의 독립 byte-tree SHA-256:
  `d0dcd26e841ef583ead382b19269f559a3263a35ce809d34c6308bfe0399ed73`.
- 전용 CPU identity: UID 979 / GID 976, private group만 사용, nologin.
- 모델: `intfloat/multilingual-e5-small`, upstream commit
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- local model/revision:
  `embeddingmodel_f30c692a99476867e96f3567ae266036` /
  `embeddingmodelrev_82eace0bd4ceeacb31ced2e8e40bc293`.
- semantic manifest SHA-256:
  `f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb`.
- root-private phase receipt:
  `/opt/eom/.embedding-install-n6SfouPM/phase-receipt`.
- 원래 developer tree는
  `/opt/eom/conda/envs/.embedding-prepublication-.embedding-install-n6SfouPM`에 보존했다.
  이 원래 tree는 보호 실행 환경이 아니며 root로 실행하지 않는다.

새 inode에 복사한 뒤 hash/type/mode/link와 wheel payload를 검증하고 고정 prefix로
발행했다. mutable interpreter·pip를 root로 실행하는 방식이나 광범위한 기존 runtime
소유권 변경은 사용하지 않았다. 설치 자체는 모델 load/forward를 실행하지 않는다.

## No-forward preflight에서 발견한 실제 차이

1. 처음의 unprivileged `pkcheck --detail` 호출은 trusted caller 조건 때문에 거절됐다.
   정책을 확대하지 않고 root caller가 실제 별도 kernel-validated subject의
   `PID,starttime,UID`를 확인하는 adapter로 수정했다. 실제 여섯 allow/deny case는 PASS다.
2. installed unit/polkit bytes와 runtime 경로 검증은 PASS다. 그러나 `systemctl show`가
   빈 structured `ExecStartPre`/`ExecStartPost`를 출력하지 않는 실제 serialization 차이로
   strict parser가 실행 전에 거절했다. `--all`도 이 host에서는 빈 배열을 출력하지 않았다.
   나머지 필수 property·exact FragmentPath·drop-in·reload 검증은 유지하면서 이 차이를
   재현 테스트로 보완했다. unit·권한·sandbox 정책을 바꾸는 해결이 아니다.
   수정 driver SHA-256은
   `6333f2aa7b3456c4d5433ca91afa83688018257f8a44f1de4e8fb90a378be477`이며
   root-private `/var/lib/eom-embedding-verifier.XeVJgr8B/verify.py`에서 실행했다.

위 두 preflight 거절 시점의 probe는 `MainPID=0`, `InvocationID` 없음,
inactive/dead였고 실행하지 않았다.

### 최초 실제 no-forward probe와 권한 수정

수정 preflight 뒤 최초 실제 probe가 15:20:29–15:20:31 UTC에 실행됐지만 exit 1로
종료했다. InvocationID는 `5c4878814d5f42a3b28fc91049a7fe36`이다. 모델 load/forward를
호출하지 않는 고정 검증 프로그램이므로 이것을 임베딩 실험이나 worker 비교로 세지 않는다.

root와 실제 전용 CPU UID로 지원된 runtime/model 검증을 따로 조회해 원인을 분류했다.
runtime/RECORD는 양쪽 PASS였지만 model snapshot은 root PASS / CPU `PermissionError`였다.
metadata에서 고정 모델 논리 ID 부모만 root:976:0700임을 확인했다. installer의
`mkdir(mode=0750)`에 umask 077이 적용되고 explicit chmod가 없어 private group traversal이
누락된 것이다. revision은 0750, manifest는 0440으로 의도한 값이었다.

독립 model manifest/member hash 검증 뒤 해당 부모의 retained FD와 정확 UID/GID/inode를
검사하고 **그 부모만 0700 → 0750**으로 복원했다. 소유자·group·모델 bytes·기존 runtime·다른
서비스 권한은 바꾸지 않았다. source installer에 실제 umask 회귀 테스트를 보강했다.
수정 뒤 실제 CPU UID로 동일 model snapshot/hash read를 다시 확인해 PASS였다.
이는 outside-sandbox read 검증이며 전체 격리 probe PASS의 대체 증거는 아니다.

사용자가 기록 보존 후 no-forward 검증 **1회** 재실행을 명시적으로 승인했다. 원래 실패
observation·확인된 원인·수정·승인 한도를 root-owned 0400 receipt로 먼저 보존했다.

- receipt: `/var/lib/eom-embedding-probe-recovery.vNOQNB0B/first-failed-observation.json`.
- receipt SHA-256: `2397e9df2e0bb279bc7a249313e4621b806ac02ef141447dc3becfdcb469c5ab`.

정확한 기존 failed InvocationID·terminal 상태·PID 0·고정 unit/polkit/runtime/model pins와
실제 권한 범위를 재확인한 뒤, 승인된 fixed no-forward probe만 reset-failed했다. 정상
garbage collection 뒤 fresh 상태를 확인하고 동일 reviewed driver의 기존 첫 실행 guard를
그대로 사용해 **한 번** 실행했다. generic retry, 새 identity, main experiment 재실행이나
과거 실패의 성공 재해석은 사용하지 않았다.

실제 재검증은 **PASS**다. 새 InvocationID는 `1f3c503f4ed2400b9b62fa58a422259e`,
상태는 active/exited, MainPID 0, Result success, ExecMainStatus 0다. 동일 policy의 전후
일치와 설치/RECORD/model hash, 실제 identity/network/file/socket negative 검증이 통과했다.
model load/forward 0이다. 첫 실패 journal과 위 receipt를 보존하며 자동 재실행은 없다.

실제 journal에서도 `IDENTITY=PASS`, `RUNTIME_RECORD=PASS`, `NETWORK=PASS`,
`MODEL_SNAPSHOT=PASS`, `nas=DENIED`, `repository=DENIED`,
`postgres=ABSENT_IN_SANDBOX`, `docker=DENIED`, `MODEL_FORWARD_COUNT=0`을 확인했다.

### 보호 CPU와 후속 후보의 byte 호환성

`16798a34d9ab2b38844724a645645377f2e9f1f4`의 build-only wheel을 실제 설치 CPU와
읽기 전용으로 비교했다. 수치 계산·정적 EOM import closure와 Catalog schema resources
345/345, handoff/launch closure 118/118, owner execution/invocation/staging/artifacts
4/4 member가 일치했다. 수치 group의 sorted member/hash/equality canonical JSON hash는
`0d240e8bfaf7dc6933348212c51bcf417f456450f2a16f2913bc6700cca2c65b`, handoff group은
`72f70fe6cc4e29ddce09ebf22c9474fbf3b6ee969a0ca1b0cb103b323784bd61`이다.

후속 owner HTTP 비교 제출/조회, verifier의 추가 진단, installation preflight 세 모듈은
다르다. 전체 CPU platform이 최신이라고 주장하지 않는다. 실제 HTTP/control/비교 owner는
새 호환 공유 runtime을 사용하고 CPU는 동일한 수치/handoff 경계만 사용한다. 이 검사는
모델·service·probe를 실행하지 않았다.

최종 `ad3ed8ca` 후보도 원래 보호 CPU `06134fcd` 설치와 data-only로 다시 대조했다.
정적 AST EOM import와 Catalog JSON resource를 포함한 수치 경계는 345/345,
launch/handoff 경계는 118/118 member 일치이며 missing/diff는 모두 0이다.
새 explicit recipe는 member 순으로 정렬한
`{member,candidate_sha256,installed_sha256,equal}` rows를 JSON `sort_keys=True`,
separators `(',', ':')`, UTF-8로 hash한다. 수치 경계 manifest SHA는
`0c4fd662de7c651ae1413c5411d3d6850969b146e1bdc1e463fe7899adf280a1`,
launch 경계는 `7c086848862e8ca638f95eb8cb0916e12e12ad3605e9ba3ca98b18b7889f71e8`이다.
이 recipe의 hash를 위 이전 관측 recipe의 hash와 동일시하지 않는다.
CPU 전체 package의 최신화·실제 추론·실제 권한 인가를 증명하는 검사는 아니다.

## 현재 source 회귀 검증

최종 동결 source에 대해 94개 test 파일 **2,609 PASS / 90.30초**, Ruff check/format
기존 46개 및 후속 변경 파일 PASS, strict mypy production 26개 파일 PASS,
Bash syntax/diff 검사 PASS다.
최초 통합 실행은 동시 source/test guard 정렬 중 이전 assertions 두 개가 실패했다
(2,578 PASS / 2 FAIL). 전체 동결 뒤 다시 실행한 결과를 위 최종 gate로 기록한다.
이후 닫힌 API 격리 callback을 추가하는 과정의 이전 six-callback 기대값 하나는
2,586 PASS / 1 FAIL로 확인해 갱신하고, 같은 94개 파일을 전부 다시 실행해 2,587 PASS였다.
native 0755와 protocol 초기 등록 후속 회귀에서는 이전 all-0644 source assertion 하나가
2,608 PASS / 1 FAIL이었다. metadata predicate/실제 mode·alias behavior 회귀를 정렬한 뒤
같은 94개 파일을 다시 실행한 최종 결과가 위 2,609 PASS다.
앞선 2,582 PASS 및 overlapping focused suite 수를 합산해 고유 테스트 수로 과장하지 않는다.

## 운영 변경 경계

공유 API 설치 전에는 지원된 owner projection으로 실제 command/job/lease/GPU claim의
quiescence를 다시 확인한다. historical failed/terminal row와 실제 실행 가능한 일을
구별하며, DB row 직접 수정이나 과거 성공 재해석을 하지 않는다.

기존 migration wrapper가 mutable API interpreter와 checkout을 root로 실행하는 경계를
발견해 [고정 release-operator adapter](../operations/RELEASE_OPERATOR_RUNTIME.md)로 좁혔다.
이 adapter는 기존 Alembic/role bootstrap을 재사용한다. 새 service/queue/worker protocol은
만들지 않는다. root-private reviewed source/wheels/context와 보호 interpreter를 먼저 입장시키고,
exact `20261010_0051` 및 기존 role reconciliation만 허용한다. 이 경계로 후속 `ad3ed8ca`
공유 release의 실제 migration·설치·검증을 완료했다. 배포 전 baseline과 실패한 admission은
아래에 역사적 증거로 보존한다.

마지막 배포 검사도 기존 API verifier의 public `verify_runtime_isolation()`을 보호된
interpreter와 admitted wheel에서 호출하도록 같은 adapter의 닫힌 callback에 연결했다.
이 검사는 DB secret을 읽지 않는다. 기존 fixed child는 service namespace 입장 후
`setpriv`로 실제 API UID에 내려간 **뒤** API interpreter를 실행한다. 격리 기준이나
service 권한은 바꾸지 않는다. 변경 가능한 API console entrypoint를 root로 실행하는
기존 배포 경로는 사용하지 않는다.

## 남은 실제 실험과 사람 검토

### 배포 전 실제 operator admission과 발견한 차이

`4fa29774f527a960e7b15f2d84f8044b388fab2b`의 source archive/3 wheels를
fresh root-private `/var/lib/eom-release-operator-stage.4fa29774-nTZ4k7`에 준비했다.
setuptools 중간 파일이 생긴 build `source/`는 복사하지 않고 exact `source.tar`를
검증·추출했다. context SHA는 `8955cbd48c444f1e202f3ee97d86c9d5a2d1fdc73be8669583de2ae99b746514`,
source snapshot SHA는 `a20184ca74f79c9de3411b858077398c57ddf3f112fcc3afc4d9e9f5d232bbb0`이다.
보호 interpreter/source/wheel의 실제 `ADMIT_PASS`를 확인했다. admission은 운영 배포가 아니다.

그 뒤 `PDF_RUNTIME_VERIFY`가 `RELEASE_OPERATOR_PDF_RUNTIME_INVALID`로 실패했다.
API와 보호 CPU의 `pymupdf/__init__.py`는 root:root:0644, `_extra.so`는 root:root:0755이며
양쪽 bytes/hash가 각각 일치했다. native SHA는
`218b6076f130f2a5d159e64909f5ffe8b966719e177c908af3db1305f8cb1dc1`이다.
정상 배포 native의 비쓰기 0755를 data-only reader가 0644로만 제한한 현재 source 결함이다.
exact `_extra.so`에만 0644/0755를 허용하고 다른 executable/writable/alias는 거부하는
source 회귀 86 PASS로 수정했다. 설치 파일 권한을 바꾸지 않았다. 기존 실패 stage/admission을
보존하고 수정 후보 `ad3ed8ca`를 새로운 build/context로 준비해 배포했다. 기존 no-forward
probe를 다시 실행하는 작업이 아니다.

owner의 읽기 전용 조회에서 비교 protocol `workflow-role/1.29.0`의 초기 등록이 없음을
확인했다. PREPARE의 초기 등록은 기존 Orchestrator protocol registration 경계에서
실제 현재 관리자 인가·정확 released schema hash·definition/capacity/candidate 입장을 검증한
뒤 처리하도록 후속 source를 보강했다. 직접 SQL 삽입이나 RELEASE 중 누락 복구는 사용하지
않는다. 실제 명시적 owner PREPARE는 아직 실행하지 않았으므로 초기 protocol/control 발행
gate는 계속 PENDING이다.

배포 전 공유 runtime baseline은 `83884224651d8b9516a7a54370077757138c518c`, DB head는
0050이었다. 그 release record의 3 wheel SHA와 보존된 rollback 입력의 SHA/RECORD가 일치했다.
0051 이후 옛 0050 platform으로 blind downgrade할 수 있다는 뜻은 아니다.
당시 chat nonsecret source pin도 같은 838842였다. 후속 배포에서 기존 supported atomic
pin-update로 `ad3ed8ca`에 정렬했다. API/일반 chat/worker/broker와 HWPX builder,
kordoc, content-team을 포함한 quiescence와 service 복원은 모델 실험과 별도의 운영 배포
gate다. 이 배포 전 baseline·실패 시점에는 service stop/migration/package replacement/model
forward를 하지 않았으며, 이후 완료된 공유 배포는 다음 기록과 구별한다.

### `ad3ed8ca` 실제 호환 공유 배포

2026-10-10 **16:07:55 UTC**에 source
`ad3ed8caf43f3a4ece5abce25b9b59801451803e`, tree
`a974e0754aaa8125cf8d481eda7d3c5cdc29b794`의 공유 release를 완료했다.

- fresh operator stage: `/var/lib/eom-release-operator-stage.ad3ed8ca-CJ7YAJ`.
- context SHA-256: `3cb2b8e14aa0d6b0e5074ffa77de68a5c8469193bc9e37870f812f9df3ee833d`.
- source snapshot SHA-256: `d805c8330f4ff368c6f47b44452d14d5359a49901abc782197c418bec100b4b7`.
- 보호 runtime/context `ADMIT`, migration 0051, 일곱 closed callback, API ready 검증: PASS.
- **16:10–16:11 UTC경** 최종 조회: 관련 8개 service 모두 active·enabled·positive PID.
- 일반 chat의 nonsecret runtime pin: `ad3ed8ca`; 전용 slot: READY.
- 실제 authenticated metadata/corpus read, CPU forward, selected pair 제출: 아직 수행하지 않음.
- 보호된 owner console과 UID 990 private 입력 경계 준비 완료; 실제 `guiadmin` TTY 로그인
  프롬프트 준비는 인증 성공 증거가 아님. 후속 종료 관측은 아래와 구분한다.

처음 admission한 build는
`/tmp/eom-api-build/ad3ed8caf43f3a4ece5abce25b9b59801451803e.CJ7YAJ`다.
기존 deploy는 같은 commit을 다시 build하므로 실제 설치된 wheel은
`/tmp/eom-api-build/ad3ed8caf43f3a4ece5abce25b9b59801451803e.BrDlZ9/dist`에서 왔다.
source commit/tree가 같아도 두 build의 raw ZIP SHA를 동일하다고 취급하지 않는다.

두 build의 data-only 비교에서도 source archive SHA가
`98155a371c03604d8eea9c04e797e004146ab6feb8ba66203329c054fb89b2c4`로 일치했다.
Platform 1,361개 및 API-contracts 99개 member의 payload/RECORD/order는 동일하다.
API 104개 member에서는 `build-info.json`의 `build_timestamp_utc` 한 필드와 이를 반영한
RECORD만 다르다. 세 wheel의 exhaustive RECORD 검증은 양쪽 모두 PASS다. raw ZIP의 시각
차이를 source/policy/protocol drift나 동일 Artifact identity로 해석하지 않는다.

실제 API identity로 읽어 검증한 정본 deployment record는
`/var/lib/eom-api/deployments/ad3ed8caf43f3a4ece5abce25b9b59801451803e.json`이다.
설치 wheel SHA-256은 이 record의 값이며, 최초 operator stage의 wheel SHA와 별개다.

| 설치 component | 정본 deployment record의 wheel SHA-256 |
|---|---|
| API contracts | `dfed170bf5b55a3db92192cc2fcb465ee8b35ea61b99e735c859fb6cd6ed80c5` |
| Application API | `ddd2dc4f340102e7519200d11195d2667343bb6f23211f32ec5e453802e9f7fd` |
| Platform | `ffb8ac66b31d134e2143a8efb534be274c313840cf90a478168cd32bc68351ed` |

이 결과는 설치·migration·격리·service 복원의 실제 증거다. 새 비교 목적의 protocol 초기
등록·control PREPARE/RELEASE, `guiadmin` 실제 session, corpus snapshot과 embedding/Codex
실험은 아직 PASS로 승격하지 않는다. 기존 no-forward 실패와 4fa stage/admission도 보존한다.

### 최초 실제 owner 로그인 시도의 종료

16:14:44.529 UTC API journal에는 `/auth/login` POST 한 건
(`req_a3cc8526dd2207154f92ff37812f31d2`)이 기록됐다. 콘솔은
`OWNER_CONSOLE_BOUNDARY_FAILED`로 종료했고, 실제 pane foreground가 bash로 복귀한 것을
확인했다. 이 관측 구간에 `/me`나 corpus read 요청은 보이지 않았다. 기존 request-completed
log에는 HTTP status가 없고 콘솔은 상세 예외를 의도적으로 출력하지 않으므로, 이 증거만으로
잘못된 비밀번호·현재 권한·응답 계약 중 어느 원인이라고 단정하지 않는다.

실제 owner UID의 metadata-only 검사에서 `owner-input-s9vek0xd` 아래 입력·prepare·query·
result receipt 네 개가 모두 ABSENT였다. 고정 콘솔은 이 receipt와 explicit RUN_EXPERIMENT
이후에만 CPU launcher를 호출하므로, 이 시도는 모델 실행이나 Artifact 발행 단계에 도달하지
않았다. 실패한 원래 코드·보호 복사본·private 입력 경계는 보존한다. 자동 relaunch나 새 CPU
identity 우회는 없으며, 사용자 입력 확인과 secret-safe phase/code 진단은 별도 후속 단계다.

사용자는 입력한 비밀번호가 실제 Studio 로그인 비밀번호였다고 확인했다. 따라서 잘못된
비밀번호라고 추정해서 계정·권한·비밀번호를 바꾸지 않는다. 원래 코드를 보존하고 단계명과
allowlisted stable error code만 추가한 one-off 진단 presentation을 준비했다.

- 진단 코드 SHA-256:
  `8c3a2d53043e9d2285a72d9e86f38730229c2bc1091eace9debfcb8da7fb37a7`.
- 보호 복사본: 원래 libexec의 `owner-diagnostic.py`; root:root:0644, 새 single-link inode.
- private 증거: `/var/lib/eom-inference-console-diag-kd1ob7jb/owner-diagnostic.py`.
- 독립 focused 합성 검사 38 PASS, Ruff check/format PASS, strict mypy 2 files PASS.
- 진단 statements를 제거한 AST는 원래 identity/auth/input/hash/model/budget/explicit
  RUN_EXPERIMENT 동작과 동일하다. 예외 message·token·password·응답 본문은 출력하지 않는다.
- 실제 identity/private-input 검증 뒤 PASSWORD_PROMPT에 도달했고, 사용자 재입력 후
  16:24:36.529 UTC `/auth/login` POST
  (`req_0965aa9a67f11a5c25df3fb16f73e07e`)가 기록됐다. 진단 콘솔은 LOGIN 단계에서
  `CONTROL_AUTHORIZATION_REQUIRED`로 종료했다. `login_guiadmin=ENTERED`, 별도의
  current-principal read는 NOT_ENTERED이고 이 관측 구간에 `/auth/me` 요청도 없었다.
  따라서 corpus·권한별 자료 조회·CPU 실행 전의 로그인 거절로 분류한다. native transport는
  login HTTP 401/403/429를 같은 stable code로 표현하고 journal은 HTTP status를 기록하지
  않으므로, 비밀번호 불일치·계정 잠금/비활성·rate limit 중 어느 하나로 단정하지 않는다.
  자동 재로그인, credential reset, auth 경계 완화는 하지 않았다.
  이전과 같은 private 입력 경계를 사용하며 새 CPU execution identity를 만들지 않았다.

source-only 독립 진단에서 지원된 다음 조회는 기존 실제 브라우저 session의
`/api/v1/auth/account`와 fresh ADMIN `OPERATOR_READ`의 `/api/v1/operators`다.
표시 이름 `GUI admin`은 로그인 username `guiadmin`의 alias가 아니며 현재 username은
사용자가 변경했을 수 있다. Operator 조회에는 상태·역할·실제 username이 있지만 credential
hash나 잠금 상태는 없다. public ApiAuditEvent read 계약도 확인되지 않았으므로, root 권한으로
private auth 테이블을 읽어서 실제 사용자 인증을 우회하지 않는다. 현재 사용자에게
`guiadmin`의 실제 브라우저 로그인 가능 여부를 확인 중이며 해당 답변 없이는 추가 로그인이나
코퍼스/모델 실행을 시작하지 않는다.

이후 사용자는 이전 입력이 잘못된 비밀번호였다고 직접 확인했다. 이것은 사용자 피드백이며
과거 API 응답의 상세 상태나 실제 로그인 성공을 새로 증명하지 않는다. 해당 확인 뒤 같은
보호된 진단 코드와 private 입력 경계로 새 입력 창을 한 번 열었고, 실제 foreground 실행이
PASSWORD_PROMPT에 도달한 것을 확인했다. 비밀번호 자동 입력, 계정 변경, model forward,
새 CPU execution identity 생성은 하지 않았다. 실제 인증 성공은 새 입력 이후의 native
current-principal/corpus read 증거로 별도 확인한다.

### 실제 재입력 인증과 original corpus 조회

16:31:19 UTC 재입력 이후 native `login_guiadmin`과 명시적 current-principal read가
RETURNED에 도달했고, 공식 `/assessment-learning-corpus`와 `/execution-presets` 조회가
완료됐다. 이는 이전 거절 기록과 별개의 실제 인증 성공 증거다.

- original occurrence-backed approved Item count: **520**.
- original target solution report: **520/520**.
- Graph revision: `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9`.
- Graph semantic SHA-256:
  `sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`.
- 조회된 ACTIVE `knowledge-grounded-item` preset:
  `execpreset_ae1ba40431514551ba86e8148c985f9c`.
- 해당 RELEASED current revision:
  `execpresetrev_8dcefbb3518c4d7d8b3289d7f154414c`.
- preset content SHA-256:
  `sha256:bdb3772ce54c86dbc7d5a5a190395b35970fdc15d8dfcb5472607002c91a1c26`.

같은 실제 session으로 exact Graph/policy metadata를 확인하고 query-free inventory 조회를
시작했다. 이 경로는 기존 출제 preset의 retrieval scope만 pin하며 그 preset을 비교 worker
실행 목적으로 바꾸지 않는다. inventory·고정 query·입력 receipt·CPU 실행 결과는 각각 실제
반환과 검증 이후 기록한다. 이 시점의 corpus 완료 수는 profile encodability나 비교 품질,
model forward 실행의 증거가 아니다.

16:34:11.711 UTC snapshot POST `req_9044d63519bde9fb1eef0c6c4762baa8`가
120,107.849 ms에 종료됐고 콘솔은 INVENTORY_READ의 `OWNER_CONSOLE_BOUNDARY_FAILED`로
terminal 종료했다. 기존 API→Catalog snapshot socket과 owner HTTP 경계는 각각 120초다.
이는 해당 timeout 경계와 일치하는 증거이며 모델 실패나 로그인 실패로 재분류하지 않는다.
동기 Catalog handler가 실제로 완료됐는지는 클라이언트 종료만으로 증명하지 않는다.
입력 stage/CPU launcher에 도달하지 않았고 자동 재제출은 하지 않았다. source inspection의
공유 extraction provenance 반복 검증 비용과 요청범위 재사용 설계는 구현 계획에 기록했다.
성능 개선 효과와 실제 520개 snapshot 재조회는 수정·검증 이후 별도 증거가 필요하다.

16:39:08 UTC Catalog의 MainPID 298424와 OS thread 목록을 조회했다. 남은 두 thread는
각각 16:07:43, 16:07:45 시작으로 해당 16:32 snapshot 요청보다 먼저 존재했다. 당시
ThreadingMixIn의 요청별 handler thread는 관측되지 않았다. 이는 그 timeout 요청이 계속
실행 중이라는 증거가 없다는 확인이며 전체 Workflow queue/lease의 quiescence는 아니다.

후속 source 수정은 `past_exam_source_provenance.py`의 요청범위 typed provenance와 immutable
index를 기존 source resolver/cache에 연결한다. exact member key는 Artifact/revision/member/
raw SHA/schema/media/byte bound와 decoder kind를 포함한다. 보존 상한은 source JSON 64 MiB,
member 1,024개, index row 100,000개다. 상한 초과 시 전체 검증한 값을 반환하되 캐시에
보존하지 않는다. 실패는 캐시하지 않고 현재 Item 승인·decision·revision·lineage 검사를
생략하지 않는다. 전역 cache, 새 schema/migration/dependency, 원문 수정은 없다.

- 변경 경계의 focused source/source-resolution/retrieval/snapshot 검사: **154 PASS**.
- root 재검사에서 동일 suite와 dependency-boundary 검사를 함께 실행해 **160 PASS**;
  unused decoder 제거와 새 leaf의 필수 wheel inventory 반영 후 source/deployment 경계
  검사 **93 PASS**. 이들은 겹치는 suite이므로 합산한 고유 test 수로 보고하지 않는다.
- 소스 3개 strict mypy PASS, 새 unit test strict mypy PASS, 수정 Python 5개 Ruff/format PASS.
- 합성 520회 공유-member 조회에서 manifest/acceptance/result/layout의 전체 검증은 각각
  1회였다. 8/64 work-unit fixture에서도 full-batch validation 각각 1회를 확인했다.
  이것은 반복 비용의 복잡도 개선 증거이지 실제 520개 latency 측정은 아니다.
- 기존 inventory 실패의 native `SnapshotReadFailure`만 stable code로 표시하도록 one-off
  presentation successor를 준비했다. 원래 identity/auth/pins/budget/RUN 동작은 AST 대조로
  보존했다. 53개 secret-safe 합성 검사와 Ruff/strict 타입검사 PASS. 원래 코드·진단 코드와
  실패 관측은 덮지 않는다. successor SHA-256:
  `0595863d1b26be7c1c204fad52fc0a64beab2576233c9356b20a815c9988150b`.

이 source 수정의 실제 runtime 검증은 다음 후속 관측에 기록한다. 동일 공식 snapshot
재조회는 fresh 인증 전까지 PENDING이다.
격리 CPU 수치/launcher closure와 새 Catalog leaf는 겹치지 않으므로 이 수정만으로 CPU
환경을 재설치하거나 이미 승인된 no-forward probe를 반복하지 않는다.

### 요청범위 source 비용 수정의 실제 compatible 설치

16:50:32.991392 UTC 정상 배포 record와 실제 API UID의 installed build 조회로 다음을
확인했다. 최초 ad3 설치·실패·인증·timeout 기록과 별개의 successor다.

- installed source: `7383d1c60efcd1fdd80d0cf49e644bcc55b0c62b`.
- installed tree: `e4858223947ac7f1fdb4871384c70a9d079080c1`.
- migration head: `20261010_0051` 그대로; 새 migration/upgrade 없음.
- normal install wheel directory:
  `/tmp/eom-api-build/7383d1c60efcd1fdd80d0cf49e644bcc55b0c62b.sD8kJI/dist`.
- installed wheel SHA-256:
  - API contracts: `e317ba3f2bbc066158ffe4c44ff899cd46223701f5e6c1596a65055233f82b15`.
  - Application API: `0d9a37b34097e21041217a535efbaa79c98b0adf98eaf20d16f7901a2248aec6`.
  - Platform: `04f3113d88f01dfc522dce5a77085086e4361677165351428f86af1e76a8d5de`.
- source archive: `sha256:25600ef02c0aa25c4c20564793282be7f4628ecef39e2a19d6e97d9b7f8c98ad`.
- protected operator data stage: `/var/lib/eom-release-operator-stage.7383d1c6-Pt46NV`;
  context SHA `059665712883923013e03c235f0ca2c6a97d2fbefb314763ecbe3df3c24157c2`;
  source snapshot SHA `6d9bc6d783589b957e7f77cded0204e975cd581e943300bead6e553f6e90edde`.
  기존 ad3 보호 libexec와 CPU runtime을 그대로 재사용하고 새 context ADMIT를 통과했다.
- normal deployment의 6개 callback(PDF runtime, migration verify, API role, Catalog role,
  HWPX role, API isolation) 모두 실제 PASS; deployment admission READY.
- 별도 Chat release pin은 기존 보호 adapter의 atomic predecessor update로 갱신했다.
  auth/model/secret/unit bytes는 변경하지 않았다. 16:51:42 UTC 8개 서비스 모두
  active/running/enabled/positive MainPID, API live/ready smoke PASS.
- 최초 Pt46NV stage wheel과 normal sD8kJI wheel은 raw SHA가 별개다. 두 빌드 RECORD PASS;
  Platform 1,362개·API contracts 99개 payload 전부 동일, API 104개 중 build timestamp와
  해당 RECORD만 달랐다. 최초 stage identity를 설치 identity로 덮지 않는다.
- source resolver를 사용하는 Chat/pair-authority 추가 회귀 **76 PASS**. 앞선 suite와
  합산한 고유 test 수나 실제 사용자 기능/비교 품질 PASS로 해석하지 않는다.
- snapshot 진단 successor를 새 candidate libexec에 보호 복사했다. 원래 콘솔·old diagnostic
  보존; private copy `/var/lib/eom-inference-console-snapshot-diag-ay17euhl`.
- actual owner UID metadata 검사에서 같은 `owner-input-s9vek0xd`의 4개 output receipt는
  모두 ABSENT였다. 이전 timeout을 우회하는 새 CPU execution identity는 만들지 않았다.

원래 인증 session은 timeout으로 콘솔이 terminal 종료되면서 소멸했다. fresh guiadmin TTY
로그인 이후 같은 private 입력 경계에서 공식 snapshot 재조회를 진행한다. 아직 snapshot
latency 개선, 고정 corpus embedding, pair worker, human transfer quality는 확인하지 않았다.

이것은 임시 operator presentation이며 새 worker protocol, auth grant, HTTP status 관측이나
production search 활성화가 아니다. 원인 분류 이후 임시 진단 호출부를 회수하고 검증 기록은
보존한다. 실제 로그인·corpus/모델 실행 PASS를 대신하지 않는다.

- 격리 no-forward probe PASS: **PASS_AFTER_ONE_APPROVED_RETRY / FIRST_FAILURE_PRESERVED**.
- compatible shared release: **7383d1c6 PASS**; migration 0051 unchanged, service 복원 PASS.
- 실제 `guiadmin` 인증·metadata·original corpus read: **PASS**; profile inventory 별도.
- 명시적 비교 owner PREPARE/RELEASE 및 초기 protocol/control 발행: **PENDING**.
- 고정 4-query, top-k 8, batch 4, threads 4 CPU 실험: **NOT_RUN**.
- 최대 2개 selected pair의 지원된 Orchestrator/Codex 비교: **NOT_RUN**.
- 사람의 풀이 전이 품질: **NOT_EVALUATED**.

E5의 512-token 범위를 넘는 자료를 자르거나 성공한 subset을 전체 520개처럼 보고하지
않는다. common encodable pool과 고정 query 조건을 만족하지 못하면
`INSUFFICIENT_ENCODING_COVERAGE`라는 측정 결과를 보존한다. Artifact commit 완료와
유효 benchmark 완료, 사람 평가 완료는 다른 상태다.

사람에게 최종적으로 모아줄 검토는 exact pair·자료 pins·후보 근거·대응하는 조건과
착상·대응하지 않는 부분·새 추론·rubric이다. model 출력으로 사람 평가나 교육 품질 PASS를
만들지 않는다. 사용자의 추가 선택이 필요한 successor 정책은 별도 gate로 남긴다.
