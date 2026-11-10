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
