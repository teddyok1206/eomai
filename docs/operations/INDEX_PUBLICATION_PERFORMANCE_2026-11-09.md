# 2026-11-09 INDEX 등록 처리량 개선

사용자 요청: 완료된 풀이·벡터와 같은 결과를 유지하면서 임베딩 처리를 빠르게 한다.
설계: [INDEX_PUBLICATION_READ_COST](../architecture/INDEX_PUBLICATION_READ_COST.md).

## 원인과 변경

기존 INDEX `2229937a37777eeb4b2905d5e38a98fd959ff4a8`의 4-target 묶음은
15:08:53.179956–15:56:45.316366 UTC에 47분 52.136초 걸렸다. GPU 계산 외의 Catalog 전체 자료 해석,
반복 schema-validator 구성과 shard JSON 해석이 병목이었다. 20초 비차단 stack
표본에서도 active 12.95초 중 8.05초가 schema registry combine에 있었다.

수정 commit: `8c4cf4dbb4e40fc1e2d8b096c6a49770273e3ecd`.

- hash-pinned 설치 schema의 validator만 재사용하며 입력 검증 결과는 저장하지 않는다.
- Registry의 정확히 같은 clean savepoint 안에서는 전체 source 해석을 재사용한다.
  현재 SQL 관계·권한·Artifact provenance는 매번 확인한다. frame이 바뀌면 새로 읽는다.
- 기존 bounded Artifact reader에서 immutable shard/result 해석을 재사용한다.
  파일 identity/hash와 finite/L2 수치 검사는 생략하지 않는다.

모델·입력 projection·CPU/CUDA space·수치 batch size·4-target window·namespace와
Graph/policy 범위는 그대로다. DB migration, 완료 데이터 수정, 새 queue/캐시는 없다.

## 검증

- broad unit 180 PASS; 신규 최적화 unit 52 PASS.
- disposable PostgreSQL registry/read-set 31 PASS: 동시 등록·CAS·재전송,
  savepoint commit/rollback, 별도 connection의 현재 source 변경 거부.
- 변경 core 5개 mypy, Python 10개 Ruff/format, diff 검사 PASS.
- 공식 build-only wheel/RECORD PASS. 별도 설치본에서 소스 package 경로를 제외한
  validator/read-set/shard/resources 63 PASS.
- 이전 설치본의 기존 Catalog schema 변경·삭제 0건, protocol tree 동일.
  새 wheel에는 이전 main에서 검증된 Excel/조립의 additive schema가 포함되어 있다.
- 작은 CPU 규칙 구성 비교는 약 16.57배, shard 반복 해석은 50회→2회다.
  이 수치를 전체 운영 처리량 개선율로 사용하지 않는다.
- 새 운영 owner의 20초 비차단 stack 표본에서 Registry.combine 표본비용은
  이전 8.05초→0.15초였다. 남은 0.15초는 다른 worker protocol 경로이며 Catalog의
  반복 validator 구성 hotspot은 사라졌다. 표본의 실행 단계가 서로 다르므로 이 비율도
  전체 묶음 처리속도로 해석하지 않는다. 등록 시 모집단 조회·DB 객체 구성·원본 파일
  확인은 계속 수행된다.

wheel SHA-256:

```text
platform e36707dbb79c6bbe4d9901d59da7e2b7de9c5af5cfbcce53c84991e66da16dad
api-contracts bdd354385684c06d56562e8ec73412131b06eb323c73f8cf50aa1857641efb6d
```

## 운영 인계

INDEX owner만 새 설치본으로 선택한다. 수치 controller/runtime
`c915281ea3acda63ea066ba9de397f7bbc335295`와 API/Web/QUERY/창작 runner는 변경하지 않는다.
기존 owner revision, unit/config, wheel은 보존한다. rollback도 실행 중 작업을 강제 종료하지
않고 같은 공식 identity/policy 및 자연 완료 인계 경계를 사용한다.

16:40:37 UTC 기존 PID 2098975에 supported graceful drain을 요청했다. 이미 시작한
작업을 계속 완료하게 하며, 기존 실패 이력을 성공으로 바꾸지 않는다. 정상 종료와
원래 RUNNING 작업의 COMPLETED를 확인한 뒤에만 새 owner를 활성화한다.

배포 전 보존 기준: encoding 5,038, source binding 133,622, index revision 598,
accepted analysis 2,883, registered report Artifact revision 1,038. 각 기존 identity별
metadata hash를 비교하며 새 행 추가는 허용하고 변경·삭제는 거부한다.

보호된 실행 기록:

- `/var/lib/eom-index-performance-release-20261109`
- `/var/lib/eom-index-performance-audit-20261109`

## 실제 결과

기존 묶음은 16:45:24.668744 UTC `BATCH_COMPLETED`, 2,859,345ms로 정상 종료했다.
기존 CPU 작업도 같은 시각 SUCCEEDED였다. 과거 실패와 실행 중 계산을 중단·재해석하지 않았다.
16:46:12 UTC INDEX owner를 선택·시작했고, 새 PID 2719114가 16:46:34.649016 UTC
다음 CONCRETE_FACETS 묶음을 시작했다. API/Web/QUERY/창작 runner의 PID·invocation은
배포 전후 모두 동일하다. 임시 PostgreSQL과 해당 전용 role은 공식 cleanup으로 제거했다.

새 CUDA 묶음 `workflow_1eddcdeb45e74a76b644be818785d5b6`은
17:10:20.589764 UTC `BATCH_COMPLETED`로 실제 등록까지 완료됐다.

| 실운영 묶음 | 전체 시간 | 대상·scope |
| --- | ---: | --- |
| 이전 참고 기준 | 47분 52.136초 | 4 targets, eligible 1,556, CONCRETE_FACETS |
| 배포 직전 묶음 | 47분 39.345초 | 4 targets, eligible 1,556, CONCRETE_FACETS |
| 새 owner 첫 묶음 | 23분 45.940초 | 4 targets, eligible 1,556, CONCRETE_FACETS |

직전 묶음 대비 소요시간 약 50% 감소, 처리속도 약 2.0배다. 동일 Graph와 입력 규칙·모델·
수치 설정·window의 다음 문항 묶음 비교이며 같은 문항의 재계산은 하지 않았다.
캐시 초기 상태·CPU 동시 실행량과 문항 길이 차이가 있으므로 모든 미래 묶음의 고정
개선율로 보장하지 않는다. 새 요청의 missing bindings 572는 이 view의 상태이며
전체 자료·모든 view의 완료율로 확대 해석하지 않는다.

이전 참고 구간의 ADMIT/REPORT 호출 361회는 새 구간 223회로 줄었다.
누적 ADMIT 792.892초→197.117초, REPORT 947.840초→205.537초,
population revalidation 33회/463.829초→22회/243.341초다.
겹치는 stage와 CPU 병행을 포함하므로 합산하지 않고 원인 확인용으로만 사용한다.

17:11 UTC 최종 read-only 보존 검사: 기존 encoding 5,038, binding 133,622,
index revision 598, accepted analysis 2,883, report revision 1,038 전부
변경·삭제 0건. 새 encoding 4, binding 4, index revision 1만 추가됐다.
실제 Workflow 조회도 CUDA COMPLETED와 encode/complete step SUCCEEDED를 확인했다.
CPU counterpart는 별도 기존 경로로 RUNNING이며, 실패 이력이나 원본을 재해석하지 않았다.
17:11:20.596684 UTC 다음 CUDA reconciliation 시작을 확인했다. INDEX PID 2719114,
NRestarts 0, active 상태이며 기존 background 관측을 유지한다. 전체 corpus 완료 선언은 아니다.

비교 기준은 `LOCAL_INDEXING_RECONCILIATION_OBSERVED`의 `BATCH_COMPLETED`,
selected targets 4, view CONCRETE_FACETS, 전체 대상 1,556인 CUDA 처리다.
`elapsed_ms`는 discovery·수치 실행·등록까지 포함하며 순수 GPU kernel 시간이 아니다.
다음 묶음은 다른 문항이므로 동일 설정·묶음 크기의 실운영 비교로만 해석한다.
이전 15:56:50의 CPU 완료나 겹치는 stage 누적시간을 CUDA 전체시간과 합치지 않는다.

## 2026-11-10 — 공개 인덱스 재검증의 크기 경계 복구

11월 9일 23:07:01 UTC INDEX가 `IndexRefreshContractError`로 종료됐다. 실제 설치본
`8c4cf4db`의 `embedding_index_refresh_plan:302`가 public index4/5를 읽기 전에
구형 `raw_similarity_contract_value`를 호출했고, 해당 parser의 1,024개 배열 상한
(`embedding_contract_values:55`)에 걸렸다. 공개 index3/4/5의 released schema와
기존 전용 raw parser는 이미 16,384개를 허용한다. GPU/로그인 오류가 아니다.
11월 10일 03:10 UTC read-only 관측은 고정 기출520 중 CUDA 등록471, 잔여49,
non-terminal Workflow0이었다. 이는 모든 종류·모든 view의 완료율은 아니다.

수정 경계는 Catalog의 순수 membership 비교다. 기존 public schema-first 모델의 전용
raw parser로 이전 manifest를 검증하고, legacy index1/2의 1,024개 제한은 유지한다.
정본은 기존 Artifact pointer와 hash-pinned index이며, source/권한/provenance 검사,
정렬·중복·포인터 hash·현재 Graph/space 일치는 생략하지 않는다. 접근은 bounded
tuple의 O(N log N) 정렬과 O(N) map/set 비교이며 새 영속 데이터·캐시·DB 변경은 없다.
실패 이력을 덮거나 제한을 전역 해제하지 않고, 완료 encoding/report/index를 재사용한다.

검증 순서: 기존 source에서 1,024 초과 회귀 재현 → public3/4/5와 legacy 경계·변조
검증 → 설치 wheel 및 owner-only 호환 릴리스 → completed 데이터 보존 대조 →
기존 자동 INDEX 재개 → 실제 다음 등록과 기출 증가 확인. API/Web/QUERY와 수치
runtime/model/projection/device space는 바꾸지 않는다. 무수정 restart만 하면 같은
오류가 반복되므로 재시작을 해결의 증거로 삼지 않는다. 아래에 실제 결과를 기록한다.

### 원인 확정과 소스 검증

읽기 전용 head 조회로 CUDA 공통 인덱스가 **1,028 bindings**, CPU972, eligible1,556임을
확인했다. CUDA head의 commit은 11월 9일22:31:48 UTC이며, 해당 묶음의 정상 종료와
후속 CPU 성공 이후 다음 discovery가 구형 parser에서 멈췄다. 생성 결과의 실패가 아니다.

공개 전체 index의 refresh, version dispatcher, index3 schema-first, receipt3의 index
재검증만 수정했다. 기존 JSON Schema bytes·배열 한도·모델·수치 입력은 바꾸지 않았다.
유효한 1,028개 fixture를 구 코드에 전달했을 때 index3/4/5 모두 동일 실패를 재현했다.
수정본 capacity33개, 기존 index/owner/producer92개, completion/device/selection38개
unit PASS. 중복·hash·constructed extra 거부와 legacy1/2의1,024 제한을 유지한다.
Ruff/format과 변경 core4개 mypy PASS. 임시 DB registry/transaction 검증은 별도 진행한다.

검토에서 발견한 별도 경계는 현재 INDEX5 복구에 섞지 않았다: source-plan3의
NativeEmbeddingContract 전체 입력 제한, QUERY 전용 device-index-pair raw wrapper.
현재 source-plan4/5와 DOCUMENT INDEX에서는 해당 경로를 호출하지 않는다. 이번 변경은
공개 인덱스 **manifest**의 크기 규칙을 바로잡는 것이며 구형 workflow 용량 확대나
QUERY 신규 릴리스로 확대 해석하지 않는다.

### 복구 배포와 진행 확인

- 수정 commit `47fc5366161a6179f9b282b823e86319bc3d9340`.
- source unit163 PASS, 임시 PostgreSQL의 registry/transaction74 PASS(483.32초).
  새 DB `eom-api-testdb-20261110032238_fc674cf4`에서만 migration 왕복과 검사를 수행했다.
- 별도 immutable 설치본의 capacity33 PASS(62.85초). 변경된4모듈이 정확한 설치 source에서
  로드됨을 확인했고 source package 경로는 제외했다. pytest cache의 `/dev` 쓰기 경고는
  결과에 영향 없으며 운영 디렉터리나 권한은 바꾸지 않았다.
- 기존 schema1237개 bytes 보존, wheel/RECORD와 실제 수치-owner interpreter import PASS.
  설치본에는 앞선 main의 미사용 함수 제거도 포함된다. 기존 numerical runtime과 독립된
  owner package이며 이 재배포에서 API/QUERY 또는 수치 interpreter를 교체하지 않는다.
- platform wheel SHA-256
  `4b6f4a702a88ca84e854d74453d44f06be0882607edfb1d06993163fa7622faf`,
  API-contracts wheel SHA-256
  `1b8e812765200a6ef6459dc3d5e4801319e461c49b188a5c2ca1df8e4c2cb83f`.
- 기존 보호된 owner installer, PREPARE/PUBLISH/ACTIVATE application 경계를 재사용했다.
  이전 INDEX failed/PID0, native drained, nonterminal0을 확인했고 과거 실패를 재해석하거나
  진행 중 Workflow를 강제 종료하지 않았다. SOURCE47fc5366/PREVIOUS8c4cf4db,
  numerical controller `c915281ea3acda63ea066ba9de397f7bbc335295`를 고정했다.
- 2026-11-10 **03:32:50 UTC** INDEX 자동 처리 시작, PID3462543,
  invocation`7dd0631b7adf495b8b64079d85eeba92`. 03:33:12에 CPU overlap과 다음
  CONCRETE_FACETS reconciliation 시작을 실제 관측했다. 아직 새 묶음 완료 판정은 아니다.
- API2638304/Web2857633/QUERY2638500/creative2639715와 InvocationID 모두 보존.
  baseline encoding5126/binding133710/index revision620/accepted analysis2883/
  registered report1038의 기존 identity별 변경·누락0. 새 등록 이후에도 최종 대조한다.
- 보호된 release/rollback 기록 `/var/lib/eom-index-capacity-release-20261110`,
  완료 데이터 비교 `/var/lib/eom-index-capacity-audit-20261110`.

실행 중 보정: 첫 도구 호출의 문자열 구문 오류는 실행 전 실패였으며 다시 올바르게
요청했다. installer 직접 실행은 실행 비트가 없는 보호 파일이라 거부됐고, 기존 방식의
`bash` 실행으로 설치를 완료했다. 두 실패 모두 runtime 활성화 전이며 기록을 보존했다.
최종 판단은 아래 실제 신규 등록·고정 기출520 진행 증가로 닫는다.

임시 PostgreSQL은 공식 `testdb_cleanup.sh --confirm`으로 제거했다. 최초 cleanup 호출은
필수 `--confirm` 누락으로 쓰기 없이 거부됐고, 명시적 대상 재확인 후 정상 제거했다.
테스트 결과 로그는 유지하며 운영 DB·완료 Artifact는 삭제하지 않았다.
03:36:51 UTC 개발 Slack `IN_PROGRESS` 전달 성공. source/설치 검증과 실제 다음 묶음의
등록 완료가 별도임을 보고했으며 목표는 아직 ACTIVE다.

### 첫 재개에서 드러난 pre-grant 실패

03:37:10 UTC 새 owner는 `EMBEDDING_BENCHMARK_CHANNEL_EOF`로 종료했다. 실제 선행 오류는
root controller의 `INSTALLED_RUNTIME_FILE_UNPROTECTED`다. attempt
`e8844d6c0955439d8c64788aef6ac0d4`에서 numeric process는 시작됐지만 READY 관측 파일과
compute grant는 없고 input/result/vector는 비어 있었다. 실패를 모델 계산 성공/실패로
재해석하지 않는다. root가 numeric unit 시작 후 프로세스 상태를 검사하고, 예외 시 원
프로세스 종료를 최대60초 기다리는 구조는 실제60초 간격과 일치한다. 과거 로그의 마지막
두 프레임만으로 실패한 정확한 proc member를 확정할 수는 없다.

별도 실제 Linux child에서 `lstat`와 protected open 사이에 dumpability만 전환하면
proc leaf 소유자0↔worker가 바뀌고, actual UID/GID와 start ticks는 그대로인데 같은
`FILE_UNPROTECTED`를 재현했다(stat/status/cgroup 양방향6건). 이것은 확인된 코드 경합
결함이며, 운영 사건의 정확한 leaf까지 증명한 것은 아니다.

보완 책임은 기존 `read_live_native_process_member`다. 허용된 고정 proc 경로에서 해당
identity 오류와 실제0↔worker 소유자 전환이 함께 관측될 때만 protected read 전체를
한 번 재시도한다(O(1), 최초 포함최대2회). 계속 변동하거나 UID/권한/크기/경로가 다른
경우 거부한다. 일반 설치파일 검증과 caller의 actual UID/GID/birth/cgroup fence는
유지한다. 새 schema·DB·queue·수치 입력 변경은 없다. 일반 reader 허용 소유자를 넓히는
대안은 불필요한 범위 확대여서 사용하지 않는다.

새 controller는 기존 INDEX 전용 delegation으로만 선택한다. 공용 c915 bootstrap과
QUERY 설정은 유지하고, root env의 INDEX release/hash pair와 INDEX owner의
controller_release만 일치시킨다. owner47fc/runtime grant 및 CPU/CUDA numerical
installation·정책·모델·space는 보존한다. 이 선택은 아직 검증·설치 후 적용 단계다.

추가 kernel 재현은 lstat 직후와 실제 read 중의 양방향 전환까지12건으로 확장했다.
기존 kernel/identity/controller/observation 관련398건 PASS(36.29초), 별도 root 진단32건
PASS(10.08초), Ruff/format/core mypy PASS. 진단은 FILE_UNPROTECTED의 기존 두 위치만
가장 가까운 호출 모듈과 마지막 검사 함수로 바꿔, 재발 시 caller를 확인할 수 있게 했다.
예외 문구·파일 경로·내용은 기록하지 않는다. 첫 진단 테스트는 오래된 noneditable 설치본을
읽어 신규1건이 실패했고, 명시적 source 경로로 재실행해 모두 통과했다.

원 실패의 parent `job_5d73760cf1544b758c05591a97438105`는 CLAIMED/route없음/bound없음이었다.
보호된 원 allocation과 종료된 두 unit을 official unbound reader로 대조했다. 초기 PREPARE는
할당 시간이 아직 남아 거부됐으며 DB/Artifact 쓰기는 없었다. 시간이 만료된 뒤 같은 원
실행의 PREPARE를 완료했고, 원 실패 기록·동일 증거 replay는 기존 application에서 수행한다.

원 실패의 공식 RECORD와 동일 증거 replay는 PASS다. 실패 증거 Artifact는
`artifact_ae9026888f324dc0ac6c08533f09765b/rev_772e7c14ff5f41bbb842d1251e6b83b8`,
`controller-failure.json`, SHA-256
`941b8d926750a5ec16f978645bca9ebc7b57150c968d1658eca664035e354a5d`다.
실패는 FAILED로 보존했고 이 단계의 모델 실행·재시도는0이다.

controller 보완 source `df57dac24f31ad8448c518b7804e8d3ad8284c20`의 wheel/RECORD,
별도 immutable 설치본114 tests(8.81초), 실제 root interpreter import PASS.
platform SHA-256 `9b4eca730d2c2c49419413cf652a6779677d0ae20a6d5373328db1a8604a463c`,
API-contracts SHA-256 `cbdb7f58660290ef3bf7ccf8fff5163373f0fd5a2e9e1a2f36d88e4e8d83629b`.
INDEX controller 전용2파일 선택을 적용했고12개 보존 파일과5개 peer의 PID/Invocation을
전후 대조했다. owner source47fc5366와 service/runtime grant는 그대로다.
선택/롤백 기록은 `/var/lib/eom-index-proc-controller-20261110`에 있다.
각 파일 교체는 원자적이지만 두 파일 전체가 분산 transaction인 것은 아니며, 중간 실패면
INDEX를 정지한 상태에서 before/after를 대조하는 기존 복구 원칙을 유지한다.

03:54:45 UTC INDEX를 재개했다(PID3493954,
invocation`62cd90e93dfa4b7992fd120681214e40`). 03:55:07에 CONCRETE_FACETS reconciliation이
시작됐고03:56에 public reports/population 재검증이 통과했다. 여기까지는 신규 등록 완료
증거가 아니므로 fixed past-exam471/520 기준선과의 증가 확인은 계속 진행한다.

실제 후속 attempt `609e176fb35142e4b439c2cf7cdaa306`은 df57dac2 controller로 실행됐다.
보호된 READY 관측 파일이 존재하고04:00 typed observer는 CUDA RUNNING1을 보고했다.
04:01:51 UTC root controller가 Result=success/ExecMainStatus=0으로 끝났고 원 numerical
unit은 성공 종료 후 기존 retirement 경로로 정리됐다. 기존 실패 이력은 그대로다.
04:02 현재 owner는 결과 인덱스 등록을 수행 중이며, 새 head/기출 count 검증은 별도다.
04:01:19 UTC 개발 Slack PROGRESS 전달 성공(등록 완료로 표시하지 않음).

### 실제 새 등록 및 기존 완료 데이터 보존

- 04:06:26.538122 UTC CUDA의 새 head
  `embeddingindexrev_e154ca9908b21ea1a8f76f0705c68138`가 등록됐다.
  CONCRETE_FACETS/ALL_ADMITTED_GRAPH_ITEMS/public-solution-text1.0,
  동일CUDA space`39bc2c310299…`에서 binding1,028→1,032, eligible1,556 유지.
  CPU head972는 그대로다. 이는 테스트 fixture가 아닌 운영 registry의 read-only 관측이다.
- 04:10:01 UTC 기존 정기 typed observer는 고정 원기출520 모집단에서
  CUDA registered target471→473, 잔여49→47을 보고했다. target-set hash 및 CUDA space
  hash는 기존과 동일하고 historical failed Workflow 분류/수도 유지됐다.
  이 수치를 사용자 GUI 검색 acceptance나 전체520 완료로 확대 해석하지 않는다.
- 새 등록 후 원 baseline과 비교한 `VERIFY_FINAL`: accepted analysis2,883,
  registered report1,038, encoding5,126, binding133,710, index revision620의
  기존identity별 변경/누락은 모두0. 신규 encoding4/binding4/index revision1만 추가됐다.
  완료 vectors/reports를 재생성하거나 과거 index를 지우지 않았다.
- 원 Goal의 마지막 확인은 현재 묶음 terminal completion과 다음 discovery 진입이다.
  04:12 현재 owner PID3493954는 같은 invocation으로 살아 있고 마무리 검증을 수행 중이다.

### 복구 목표 완료 — 2026-11-10 04:21 UTC

- 04:19:09.939116 UTC `BATCH_COMPLETED`, selected target4를 실제 관측했다.
  exact Workflow `workflow_ddbc984e6f6843ef9eb86471774bb7a9`를 운영 저장소에서 읽어
  COMPLETED, command `wfcmd_cc3c5707f3a548fea235a96a7e91549d`는 SUCCEEDED/attempts1임을
  확인했다. 전체 묶음 시간1,442,894ms에는 discovery·검증·등록이 포함되며 GPU kernel
  실행시간으로 해석하지 않는다.
- 04:20:09.947529 UTC 같은 owner가 다음 CONCRETE_FACETS reconciliation에 진입했다.
  새 요청을 수동 중복 제출하거나 이미 완료된4건을 재계산하지 않았다. CPU standby는
  기존 overlap 경로에서 RUNNING이며 INDEX 자동 처리와10분 관측 timer는 유지한다.
- 원 기출520 target-set 및 CUDA space의04:20 typed 관측은473/520(잔여47)이다.
  GPU head1,032·기존 완료 identity 변경/누락0·exact Workflow/command 성공을 함께
  확인했으므로 이번 **1,024 경계 오류 수정과 자동 처리 복구** 목표는 완료다.
  전체520 임베딩 완료, 모든 소비 경로 재검증 또는 QUERY 후속 개선을 완료한 것은 아니다.
- API2638304/Web2857633/QUERY2638500/creative2639715와 기존 invocation을 최종에도 보존했다.
  INDEX owner47fc5366, INDEX 전용 root controllerdf57dac2, 공용 c915bootstrap 및 수치
  model/runtime/input recipe/device space 불변의 release 구분을 유지한다.
- 임시 검증 DB와 그 자격증명 state directory만 공식 cleanup으로 제거했다.
  이는 재생성 가능한 테스트 데이터이며 운영 DB·Artifact·백업 삭제는0이다.

최종 증거는 protected release/audit 기록과 해당UTC journal, task별
`eom-index-cap-live-completion-20261110.log`, `eom-index-cap-final-heads-20261110.log`,
`eom-index-cap-final-preserved-20261110.log`의 비밀값 없는 요약으로 추적한다.
