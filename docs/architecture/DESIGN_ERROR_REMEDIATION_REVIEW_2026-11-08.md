# EOM 설계 원칙과 오류 기반 수정 목록

최종 후속 상태(2026-11-08 18:01 UTC): **R01–R05 구현·검증·호환 운영 반영 완료**.
아래 OPEN/STRUCTURAL_FOLLOWUP은 최초 검토 시점의 분류다. 실제 결과는 이 문서의
수정 작업 기록과 [운영 릴리스 기록](../operations/ARCHITECTURE_REMEDIATION_RELEASE_2026-11-08.md)을 따른다.

기준: 2026-11-08 UTC, Git `8b5848dfa864aa1c13e0347ab5a2867d1ecac4c0`.
검토 목적은 OOP·캡슐화·책임 분리의 유지 여부와 국소적인 오류 대응이 남긴 복잡성을 확인하는 것이다.
이 목록은 구현·배포 결과가 아니다. 운영 코드, DB, 실행 중 작업, 원본, 실패 이력은 변경하지 않았다.

## 결론

계약·도메인과 인프라의 큰 의존 방향은 유지되고 있다. Worker의 직접 저장을 허용하거나
새 검색·큐 프레임워크로 기존 구조를 대체해야 할 근거는 발견하지 않았다. 다만 기존 구조 검사가
놓치는 의존 관계가 있고, 종료 처리와 오류 전달에는 실제 장애와 연결되는 보완점이 남아 있다.

현재 수정 대상은 **직접 보완 3건(R01–R03)**과 **과거 오류가 발생한 경계의 구조 정리 2건(R04–R05)**이다.
후자의 과거 기능 오류는 이미 수정됐다. 현재 같은 장애가 재현된다는 뜻이 아니라, 남아 있는
책임 집중과 암묵적 초기화 의존을 제한적으로 정리할 대상이라는 뜻이다. 별도 확인 후보 5건은
확정 수정 건수에 포함하지 않는다. 해결된 오류도 아래 회귀 목록에 보존한다.

가장 중요한 판단 기준은 클래스·파일 수가 아니다. **하나의 규칙을 어디에서 결정하는지,
정상 사용자 요청을 따라가며 얼마나 많은 내부 구현을 알아야 하는지, 같은 검사를 왜 다시 하는지**다.
같은 결과와 불변식을 더 단순하게 유지할 수 있다면 함수 추출·명시적 구성·기존 모듈 확장을 우선한다.

## 수정 대상으로 올리는 기준

다음 두 조건을 함께 충족해야 한다.

1. AGENTS.md 또는 기존 설계의 책임·의존 방향·정본·포인터·트랜잭션·자료구조 원칙에서 벗어난 사실이 있다.
2. 해당 경계에서 실제 운영 오류 또는 재현 가능한 검증 오류가 확인됐다.

근거는 세 종류로 구분한다. `운영 기록`은 당시의 실제 실패와 복구 기록, `격리 재현 기록`은
과거 테스트에서 확인한 경합·중단 오류, `이번 재현`은 이번 검토에서 직접 확인한 오류다.
같은 파일에 오류가 있었다는 이유만으로 모든 복잡성이 원인이라고 단정하지 않는다.

규칙 위반을 정상적으로 거부한 것, 아직 지원하지 않는 원본 형식, AI 결과의 부정확성은
그 자체로 deterministic 코드 결함이 아니다. 기존 pin을 몰래 최신 값으로 바꾸지 않는 것도
수정할 오류가 아니다. 이미 해결한 문제를 다시 구현하거나 모든 예외를 무조건 retry하지 않는다.

## 전체 흐름에서 본 단순화 방향

| 사용자 흐름 | 유지할 책임 분리 | 국소 대응 대신 적용할 방향 |
| --- | --- | --- |
| 유사도 검색 → 결과 → 문항 열기 | 계산 결과는 immutable, 현재 열람 권한은 매번 확인 | 완료 조회에서 계산·전체 풀이 해석을 반복하지 않는다. 이미 도입한 저장 ranking을 유지하고 남은 지연은 구간별로 측정한다. |
| 원본 → 풀이 → 등록 → Graph → 임베딩 | 분석·Graph 발행·수치 계산·인덱스 발행은 다른 상태 | 한 담당의 오류를 새 전체 작업 생성으로 우회하지 않는다. accepted 결과를 다음 담당이 같은 pointer로 이어받는다. |
| 배치 → HWPX → 다운로드 | Catalog 입력/권한, Manager 작업/복구, Builder 변환/조립, Orchestrator Artifact commit | 이 경계를 합치지 않는다. 개별 출력물을 중간 NAS 정본으로 계속 늘리지 않고 기존 local materialization과 최종 commit을 재사용한다. |
| 로그인 → 계정 변경 → 재조회 | Identity가 계정 상태·잠금·철회, API가 전송·멱등 응답, Web이 session 표현 | 화면별 임시 인증 예외 대신 같은 계정/세션 규칙을 사용한다. 성공 로그인까지 실패 제한에 넣었던 문제를 되풀이하지 않는다. |
| 배포 → 진행 작업 종료 → 재개 | 실행 pin과 호환 release set, 원래 작업 identity | 새 hotfix wrapper를 계속 붙이기 전에 기존 종료·복구·설치 담당을 고친다. shared ORM 결합을 숨긴 채 독립 서비스처럼 배포하지 않는다. |

반복 검사를 모두 제거하는 것은 단순화가 아니다. 같은 immutable bytes의 파싱·해시·목록 순회와,
시간에 따라 달라지는 권한·철회·lease·commit 직전 검사는 구분해야 한다. 앞쪽은 검증된 동일
materialization 범위에서 재사용할 수 있지만, 뒤쪽은 없애거나 장기간 캐시하지 않는다.

## 직접 보완 대상

### R01 창작 Graph 발행 종료와 서비스 중단 예산

- **우선순위 / 상태:** P1 / OPEN. 배포·정상 종료 경계의 현재 불일치.
- **원칙:** application이 작업 생명주기를 소유하고, infrastructure 종료 한도와 합의된 경계를 가져야 한다.
- **오류 근거:** 11월 5일 배포에서 publication 종료 대기가 systemd 3분을 넘어 timeout으로 종료됐다.
  [운영 기록](MODULE_BOUNDARIES.md)의 마지막 운영 반영 절에 실패와 같은 scope 재개가 기록돼 있다.
- **현재 코드:** [병렬 실행 close](../../services/catalog_service/eom_catalog_service/creative_cohort_parallel_execution.py)의
  `close()`는 `executor.shutdown(wait=True, cancel_futures=False)`로 무제한 대기한다.
  [runner](../../services/catalog_service/eom_catalog_service/creative_learning_runner.py)는 `finally`에서 이를 호출하며,
  [service template](../../infra/systemd/eom-creative-learning.service.in)은 `TimeoutStopSec=180`이다.
- **가장 작은 수정:** 기존 application과 unit의 종료 예산·중단 상태를 함께 정의한다. 먼저 신규 투입을 멈추고,
  진행 publication은 기존 commit/멱등 복구 경계로 끝내도록 한다. 종료 대기가 실제 DB/발행 상한 안에
  들어오는지 확인한 뒤 timeout을 정렬한다. 단순히 숫자만 키우거나 `wait=False`로 fence를 먼저 풀지 않는다.
- **완료 기준:** 발행 전·DB commit 전후·응답 직전 중단을 disposable DB에서 검증한다. 다음 owner가
  같은 accepted source를 재사용하고 중복 Graph 발행·모델 재실행이 없어야 한다. 느린 발행 중 stop의
  실제 종료시간도 측정한다. 정상 처리 경로에 새 polling service나 queue를 추가하지 않는다.

### R02 임베딩 readiness 오류의 원인 전달

- **우선순위 / 상태:** P1 / OPEN. 오류 진단 계약의 정보 소실이며, 계산 결함 자체의 원인 확정은 아니다.
- **원칙:** adapter는 외부 실패를 안정된 의미로 번역하고 application은 그 의미로 중단·재시도를 결정한다.
- **오류 근거:** 11월 8일 15:46:49 UTC INDEX가 다음 CPU command readiness의
  `WorkflowRuntimeNotReady`로 종료됐다. 같은 설치환경의 후속 검사는 통과했으며 당시 하위 사유는
  남지 않았다. [실제 복구 기록](../operations/RETIRED_INDEX_PUBLICATION_RECOVERY.md)의
  ‘백그라운드 INDEX 재개’ 절이 이 한계를 명시한다.
- **현재 코드:** [고정 runtime verifier](../../services/workflow_runner/eom_workflow_runner/local_indexing_runtime_verification.py)의
  `assert_current()`는 출력 폐기 후 모든 Exception을 같은 ValueError로 바꾸고 원인을 제거한다.
  [native executor](../../services/workflow_runner/eom_workflow_runner/local_embedding_native_executor.py)의
  `evaluate()`도 ValueError/OSError를 한 readiness 코드로 합친다. 당시 어느 하위 분기가
  실행됐는지는 이 코드만으로 복원할 수 없다.
- **가장 작은 수정:** 해당 두 담당 사이에서 제한된 사유 코드만 보존한다. 예를 들어 timeout,
  파일 identity 변경, 실행 실패, control mismatch를 구분하되 외부 메시지는 기존 안전한 오류를 유지한다.
  원문 stderr·경로·환경 변수·인증값을 로그로 풀지 않는다. 이미 있는 readiness 결과와 안전한
  운영 관측 경계를 확장하고 새 진단 시스템은 만들지 않는다.
- **완료 기준:** 각 오류의 안전한 내부 사유가 서로 다르고 secret이 노출되지 않아야 한다.
  실패가 READY로 바뀌지 않으며 알 수 없는 오류는 계속 중단한다. 이 수정만으로 일시적인 오류의
  자동 재시도를 승인하지 않는다. 이번에 실행한 기존 verifier 4개 검사는 이 구분까지 보장하지 않는다.

### R03 의존 방향 검사의 누락

- **우선순위 / 상태:** P1 / OPEN. 이번에 재현한 검증 오류. 특정 운영 장애의 직접 원인으로 주장하지 않는다.
- **원칙:** 순환 의존과 계층 역전을 자동으로 검증해야 하며, PASS가 실제 검사 범위를 과장하면 안 된다.
- **현재 코드:** [dependency test](../../tests/unit/test_dependency_boundaries.py)의
  `_imports()`는 `package.submodule`을 반환하지만 cycle test는 `target in roots`로 비교한다.
  하위 모듈 import가 graph edge에서 누락된다. `_first_party_roots()`의 `*/eom_*` 탐색은
  `eomctl` 15개 Python 파일을 놓치며, source package가 아닌 `.egg-info` 6개 디렉터리도 잡는다.
- **이번 재현:** 현행 알고리즘은 SCC 0개, 최상위 package를 정규화한 알고리즘은 기존에 알려진
  Catalog·Identity·Orchestrator·Runner의 4개 service SCC를 찾는다. 허용 cluster 밖의
  두 package가 dotted import로 서로 참조하는 작은 합성 예제도 기존 알고리즘은 통과시킨다.
- **가장 작은 수정:** 기존 AST 검사에서 source root 탐색과 import 정규화만 고친다.
  package-relative import도 실제 소속으로 해석하고 graph vertex를 명시한다.
  새 검사 프레임워크·런타임 의존성은 필요 없다. 복잡도는 기존 O(V+E)를 유지한다.
- **완료 기준:** dotted import·relative import·CLI·허용 cluster 밖 cycle을 검사하는
  음성 예제가 실제 실패해야 한다. 기존 4-service cluster는 인정된 부채로 표시하되 확장은 막는다.
  Python import 외 동적 실행·JavaScript·SQL 소유 경계까지 자동 보장한다고 표시하지 않는다.

## 과거 오류 경계의 구조 정리 대상

### R04 QueryAdapter의 책임 집중과 pointer 의미

- **우선순위 / 상태:** P2 / STRUCTURAL_FOLLOWUP. 과거 STALE 오류는 수정됨.
- **원칙에서 남은 이탈:** `QueryAdapter` 하나에 문항·학습·자료 검토·고객 지원·HWPX·운영 조회의
  서로 다른 변경 이유가 모여 있다. 현 기준 직접 정의된 메서드는 119개다. 메서드 수 자체가
  결함의 증명은 아니지만, 서로 다른 도메인 규칙과 표현 변환이 함께 놓인 것은 확인된다.
- **실제 오류와 인과 범위:** 결과 문항 열기에서 canonical member `assessment-item-content.json`과
  worker 입력 alias `item-content.json`을 같은 의미로 비교해 `ITEM_DB_SIMILARITY_RESULT_STALE`가
  발생했다. [11월 2일 오류·수정 기록](../operations/UNIFIED_ITEM_EMBEDDING_GPU_CHECKPOINT_2026-10-31.md)의
  ‘GUI 결과의 잘못된 STALE 판정 수정’ 절에 재현과 배포가 있다. 잘못된 비교가 직접 원인이고,
  큰 클래스가 단독 원인이라고 입증된 것은 아니다.
- **현재 코드:** [QueryAdapter](../../apps/application_api/eom_api/services/query_adapter.py)의
  `_candidate_content_matches_source()`는 이미 `source.artifact_member.member_path`를 비교한다.
  이 정답을 다시 바꾸는 작업이 아니다. 같은 파일의 `selected_production_item_candidates()`와
  `production_item_candidates()`가 Graph·Item·분석 포인터 해석과 화면용 투영을 함께 맡고 있다.
- **가장 작은 수정:** 공개 facade는 유지하고, 우선 실제 오류 경계인 ‘검색 결과 → exact Item 조회’만
  목적별 조회 모듈로 분리한다. canonical member와 staging alias의 대응은 한 위치에 둔다.
  이후 자료 검토 등은 실제 변경 수요가 있을 때 분리한다. 조회 adapter의 SQL read는
  [기존 CQRS 설계](API_COMMAND_QUERY_BOUNDARY.md)가 허용하므로 모두 RPC로 바꾸지 않는다.
- **완료 기준:** 같은 canonical/alias 사례, hash·revision·권한 거부, 결과 순서와 GUI 문항 열기를
  보존한다. 현재 bounded batch 조회를 문항별 N+1 호출로 바꾸지 않는다. 추출 전후 SQL 횟수와
  대표 조회 시간을 비교하고 새로운 universal repository나 wrapper 계층은 만들지 않는다.

### R05 공유 ORM 초기화의 암묵적 소유 관계

- **우선순위 / 상태:** P2 / STRUCTURAL_FOLLOWUP. 확인된 curated FK 오류는 수정됨.
- **원칙에서 남은 이탈:** Catalog·Identity·Orchestrator·Runner의 양방향 의존은
  [기존 모듈 경계](MODULE_BOUNDARIES.md)와 [ADR 0162](../adr/0162-module-boundary-enforcement-and-schema-cache.md)가
  유예한 구조 부채다. 공유 transaction의 실익은 있지만 외부 owner의 ORM 초기화 순서를 알아야
  호출할 수 있는 부분은 캡슐화가 약하다. HWPX Manager의 cross-owner FK는 이 SCC와 별도이지만
  같은 공유 metadata 조립 문제를 보여준다.
- **실제 오류:** 좁은 API import 경로에서 curated queue의 FK 대상 Table이 없었다.
  전체 테스트의 앞선 import가 문제를 가렸다. 실제 Table/column 참조와 subprocess cold-import
  검사로 수정했다. [운영 체크포인트](../operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md)의
  ‘실제 실행에서 수정한 두 경계’를 참고한다.
- **현재 코드:** [curated build model](../../services/hwpx_manager/eom_hwpx_manager/curated_build_models.py)은
  정확한 owner column을 직접 참조하며 [cold metadata test](../../tests/unit/test_curated_hwpx_cold_metadata.py)는
  이번에도 통과했다. 이 FK를 다시 고칠 근거는 없다. 다른 public entrypoint의 초기화가 같은 방식으로
  독립 검증되는지는 coverage를 넓혀 확인할 필요가 있다.
- **가장 작은 수정:** 기존 composition에서 각 공개 진입점이 요구하는 metadata 초기화를 명시하고
  해당 진입점만 fresh process에서 검사한다. import 순서에 기대는 관계가 실제 발견될 때만
  owner column 참조나 기존 composition을 수정한다. 당장 shared DB를 나누거나 ORM 전체를
  새 공통 package로 옮기지 않는다.
- **완료 기준:** API request-only, Catalog, Runner, Manager의 독립 import/DDL 검증과
  disposable DB의 기존 atomic commit·FK·role 검사를 유지한다. ‘import가 되도록’ unrelated
  전역 import를 계속 추가하지 않는다. cycle 감소만을 위해 transaction을 여러 서비스로 쪼개지 않는다.

## 해결된 오류의 회귀 목록

아래는 새 수정 작업이 아니다. 현재 변경이 해당 경계를 건드릴 때 기존 검증을 재사용한다.
`운영 기록`과 `격리 재현 기록`은 구분했으며, 이 검토에서 각 운영 시나리오를 재실행한 것은 아니다.

| ID | 원칙과 실제 오류 | 현재 조치 및 담당 | 근거 |
| --- | --- | --- | --- |
| C01 | 파생 제한 상태가 계정 상태와 분리되어 정상 로그인·비밀번호 복구 뒤에도 차단 | 실패만 제한에 반영, 성공 시 해제, 공식 복구와 UI 401/429 구분. Identity/API/Web 경계 유지 | [운영 로그인 복구](../operations/LOGIN_FAILURE_BUDGET_RECOVERY_2026-10-24.md) |
| C02 | 외부 protocol 변화가 adapter에서 해석되지 않아 정상 채팅을 실패 처리 | 현재 thread/turn 확인 후 `turn/moderationMetadata`만 안전하게 무시. Orchestrator `general_chat_native.py` | [운영 채팅 복구](../operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md) |
| C03 | Web 호출부와 전송 helper가 JSON을 두 번 직렬화하고 CSRF mutation 표식을 누락 | 공통 전송 계약에 맞춰 한 번 직렬화. 실제 연결 함수까지 회귀 검사 | [운영 CSRF hotfix](../operations/ITEM_DB_SIMILARITY_CSRF_HOTFIX_2026-10-31.md) |
| C04 | 사용자 순서 목록을 canonical set과 동일시해 2문항 검색 준비 실패 | 캡처 집합만 정렬, 결과는 원래 순서. Catalog selection 담당 | [운영 2문항 준비 오류](../operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md) |
| C05 | 완료 조회마다 전체 자료/벡터 해석을 반복해 150–180초 수준의 결과 조회·응답 한도 도달 | Catalog의 저장 ranking과 fresh metadata 검증으로 분리. 실제 같은 기록 재조회 17.633초 관측. 추가 성능 보장은 아님 | [저장 결과·실측](../operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md) |
| C06 | 로컬 결과 수령 ACK와 전체 source 재검증을 섞어 정상 GPU 결과 뒤 ALRM/BrokenPipe | ACK에서 중복 source roundtrip 제거, 공개 전 권한/정본 검사 유지 | [운영 GPU 인계 수정](../operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md) |
| C07 | 계산 timer가 최종 통신 ACK까지 포함하고 allocation 준비 예산도 불일치 | 기존 numerical worker와 control에서 compute/settlement 상한 분리 | [설계](EMBEDDING_ALLOCATION_SETTLEMENT_BUDGET.md), [운영 실행 결과](../operations/EMBEDDING_SETTLEMENT_RECOVERY_2026-11-07.md) |
| C08 | OS 상태 관측의 일시 2초 timeout이 INDEX 전체 실패로 전파 | Identity adapter에서 해당 읽기 timeout만 2/5/10초 bounded retry. 잘못된 identity·권한은 계속 거부 | [운영 관측 복구](../operations/INDEX_UNIT_OBSERVATION_RECOVERY_2026-11-07.md) |
| C09 | source-local PDF 변환 실패 하나가 전체 창작 처리 중단 | 기존 driver가 정확한 source-local 오류만 보류하고 나머지 처리. 새 queue 없음 | [운영 재현과 격리 설계](CREATIVE_SOURCE_PREVIEW_FAILURE_ISOLATION_2026-10-31.md) |
| C10 | 최초 FAILED 분석만 따라 accepted retry를 놓쳐 완료 문항을 보류로 집계 | KnowledgeAnalysis의 공식 `resolve_retry` 사용, 원래 실패 보존 | [운영 창작 복구](../operations/CREATIVE_COHORT_RECOVERY_2026-11-07.md) |
| C11 | outer transaction 권한 fence를 savepoint에서 재호출할 때 거부 | 동일 root/session/thread의 검증된 admission만 재확인 허용. Registry atomic rollback 유지 | [운영 실패·격리 재현·복구](../operations/RETIRED_INDEX_PUBLICATION_RECOVERY.md) |
| C12 | 자원 장애를 정상 작업 재개 정책과 연결하지 못해 publication/INDEX 중단 | 기존 owner의 disk backpressure·명시 SQLSTATE 재개·OS 유지보수 관측. worker/정본 재생성 없음 | [운영 자원 장애](../operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md) |
| C13 | 정본 HWP/HWPX 그림 대신 추정 PDF 사각형으로 파생해 그림·표기 잘림 | 본문 picture use와 binary를 구분해 원본 내장 그림 등록. 모호한 원본은 명시 보류 | [실제 시각 오류와 복구](CREATIVE_SOURCE_VISUAL_RECOVERY.md) |
| C14 | 공유 reader가 실행된 native checkpoint successor를 해석하지 못함 | 호환 Catalog reader에 두 released family 설치, 기존 결과 재사용. schema relabel 금지 | [운영 QUERY reader 정렬](../operations/REFERENCE_QUERY_READER_ALIGNMENT_2026-10-16.md) |
| C15 | 단일 HWPX 중단 후 RUNNING 잔류 | Manager startup/renderer port의 같은 Job 복구. 별도 render로 우회하지 않음 | [11월 5일 격리 재현·배포](MODULE_BOUNDARIES.md), [현재 복구](../../services/hwpx_manager/eom_hwpx_manager/renderer_recovery.py) |
| C16 | session/token 잠금 역전·대기 중 철회·Web token 교체 경합 | Identity session→token 순서·재확인, Web 동일 session lock | [11월 5일 격리 경합 검증](MODULE_BOUNDARIES.md) |
| C17 | 관리자 ETag 선검사와 계정 변경/멱등 응답 저장의 분리 | target lock 안 CAS, API `run_operator_command` + Identity `join_transaction`의 같은 transaction | [11월 5일 격리 crash/replay 검증](MODULE_BOUNDARIES.md), [현재 호출](../../apps/application_api/eom_api/routers/common.py) |
| C18 | 문서 lease/응답 예산·실제 body 제한·ORM/migration·schema resource 검사의 불일치 | 기존 composition 예산 정렬, 실제 byte 413, ORM 물리 선언 정렬, 독립 schema resource 검사 | [11월 5일 변경별 검증과 운영 반영](MODULE_BOUNDARIES.md) |

R04의 canonical/alias 오류와 R05의 FK 오류는 각 항목에 직접 기록했으므로 이 표에서 다시 세지 않는다.
C15–C18은 주로 격리 재현으로 확인한 문제이며, 모두 실제 사용자 사고였다고 확대하지 않는다.

## 추가 확인 후보

| ID | 관측과 범위 | 아직 확정 수정으로 올리지 않는 이유 | 다음 한 가지 |
| --- | --- | --- | --- |
| Q01 | INDEX의 작은 batch 처리 뒤 source 검증·발행이 오래 걸림. 11월 7일 reconciliation 2,011,076ms 기록 | 계산보다 후속 처리가 길다는 사실만으로 어떤 검사가 불필요한지 결정할 수 없음 | 기존 phase별 시간/SQL/parse 횟수를 측정해 immutable 중복과 fresh authorization을 분리 |
| Q02 | 저장 ranking 재조회도 한 관측에서 17.633초. 현재 `completed_public_ranking_read.py`는 hit에도 전체 의존 metadata를 전후 확인 | 전체 후보 source 철회 감지는 현 계약의 요구다. 무조건 top-k만 검사하면 같은 결과의 의미가 달라짐 | 실제 hit의 DB·artifact·권한·projection 비용을 분리 측정한 뒤 기존 관측 함수 안에서 최적화 |
| Q03 | 원본 11669·11753은 choice-layout-v3 PDF가 준비됐지만 학습 경로는 legacy profile. `creative_preview_preparation.py`와 `creative_item_graph_learning.py`가 기본 legacy service 구성 | 과거 pin 보존은 정상. 최신 profile을 쓰는 명시적 successor 입력 연결의 누락이지, 오래된 기록을 덮어쓸 이유가 아님 | 허가·준비·worker staged input이 같은 새 profile을 pin하는 작은 후속 설계를 먼저 확인 |
| Q04 | WorkflowCatalogService가 역할 준비·그림·등록까지 맡고 Web Gateway도 큰 인터페이스 | 실제 facade 역할일 수 있으며 메서드 수만으로 인과관계를 확인할 수 없음 | 다음 관련 오류/변경의 호출 경로에서 불필요한 의존이 실제 필요한지 확인 후 목적별 port만 분리 |
| Q05 | `eomctl`의 일부 명령이 여러 application 단계를 조합하고 같은 package의 private helper를 사용 | CLI orchestration이 두꺼워질 징후는 있지만 그 코드로 인한 실제 실패를 이번에 특정하지 못함 | CLI와 service에 중복된 업무 순서가 있는지 한 use case씩 대조. 단순 인자검증·구성은 그대로 유지 |

Q01 근거: [실제 INDEX 완료 기록](../operations/EMBEDDING_SETTLEMENT_RECOVERY_2026-11-07.md).
Q02 근거: [결과 재조회](../operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md)와
[현재 저장 ranking](../../services/catalog_service/eom_catalog_service/completed_public_ranking_read.py).
Q03 근거: [원본 보류 분류](../operations/CREATIVE_COHORT_RECOVERY_2026-11-07.md).
Q04–Q05는 구조 관측이며 운영 오류로 집계하지 않는다.

## 검토 범위와 검증

### 정적 검사

- `apps/`, `packages/`, `services/`의 추적된 Python **1,648개 파일**을 AST로 읽었다.
  apps 191, packages 450, services 1,007개다. 모든 함수의 의미를 전수 증명한 것은 아니다.
- 기존 탐색의 유효 source package는 25개이며 누락된 `eomctl`을 포함하면 26개다.
  `.egg-info`를 source package로 세지 않는다.
- 최상위 import 정규화로 확인한 service SCC는 기존에 알려진 4개다.
  계약·도메인의 infrastructure 역의존과 service의 app 의존은 기존 검사가 통과했다.
- 전체 Python AST 검사와 별도로 Web/BFF 전송, 배포/unit, 문서 입출력의 오류 기록과
  관련 현재 코드를 검토했다. JS·shell·Java/OXT·실제 운영 권한 전체를 전수 실행한 검증은 아니다.

### 주요 영역별 판단

| 영역 | 판정과 연결 |
| --- | --- |
| protocol·identifier·workflow·catalog/API/image/HWPX 계약·operator identity | 하위 계층 유지. 구 버전 보존을 중복 코드라는 이유로 삭제하지 않음. R03의 검증 보완 필요 |
| API·Web·eomctl | R04 책임 집중, C01/C03/C04/C16/C17 해결 경계, Q05 추가 확인 |
| Catalog·Item Registry·Content Intake/Pack·Graph | 정본/파생/accepted 분석 구분 유지. R05 공유 초기화, R01 종료, C09/C10/C13 |
| Orchestrator·Runner·Identity | routing/claim/lease/commit 유지. R02 오류 번역, R05 공유 구성, C02/C07/C08/C11 |
| INDEX·QUERY·GPU lease | CPU/GPU vector space와 실행/발행 분리 유지. C05–C08/C14, Q01/Q02 |
| HWPX Manager·Builder | Manager와 renderer port 분리 유지. 단일/시험지/native 합본을 무리하게 하나의 renderer로 합치지 않음. C15/R05 |
| 자료 검토·Office 변환·이미지 intake | 원본·검토 PDF·등록 PNG·교정 출력의 의미 구분 유지. C09/C13/C18, Q03 |
| 이미지 provider·candidate runner·trainer·image contracts | import 경계 정적 확인. 이번에 새 OOP 관련 장애 인과를 특정하지 못함. GPU 시각 품질/학습 실행은 평가하지 않음 |
| 관측·개발 보고·설치 도구 | production이 optional 개발 reporter에 의존하지 않는 기존 검사 통과. observer 상태를 완료 판정으로 대체하지 않음 |

### 이번 실행

명시적 `/srv/eom/conda/envs/eom-api/bin/python -B`와 source별 `PYTHONPATH`를 사용했다.
production DB·모델·GPU·운영 unit 실행은 없었다.

- `test_dependency_boundaries.py`, `test_catalog_application_boundary.py`,
  `test_code_context_navigation.py`: **48 PASS**. cycle 검사의 사각지대는 별도 R03으로 남긴다.
- `test_local_indexing_runtime_verification.py`, `test_creative_parallel_execution.py`,
  `test_curated_hwpx_cold_metadata.py`, `test_creative_item_graph_learning.py`: **36 PASS**.
- 현재 cycle 계산과 정규화 계산 비교, 허용 cluster 밖 dotted-import 2-cycle 합성 재현:
  **기존 검사 false-negative 확인**. 이를 PASS 테스트 수에 섞지 않는다.

## 권장 수정 순서와 완료 조건

1. **R03:** 작은 구조 검사부터 바로잡아 이후 정리의 보호 장치를 신뢰할 수 있게 한다.
2. **R02:** 다음 INDEX 실패에서 원인이 소실되지 않게 하여 추측성 retry/핫픽스 누적을 줄인다.
3. **R01:** 종료 예산과 원 작업 복구를 함께 검증한 뒤 안전한 배포 시점에 반영한다.
4. **R04:** 검색 결과의 문항 해석 경계부터 한 번에 하나씩 분리한다. 전체 QueryAdapter 교체는 하지 않는다.
5. **R05:** 실제 공개 진입점의 cold-import 검사를 넓힌 뒤 실패한 초기화 의존만 정리한다.
6. **Q01–Q05:** 추가 증거가 생긴 항목만 승격한다. 특히 성능 개선은 현재 측정과 계약 의미를 먼저 확인한다.

각 구현 전에는 현재 source와 운영 release를 다시 대조한다. 이미 고쳐진 항목은 닫고,
같은 결과를 내는 더 작은 변경이 있으면 그쪽을 선택한다. 수정할 때마다 다음을 기록한다.

- 실제 오류 → 책임 모듈 → 가장 작은 변경 → 영향을 받는 사용자 흐름.
- 없앤 중복/분기와 추가한 복잡성. 별도 abstraction이 필요하면 기존 담당으로 해결할 수 없는 이유.
- 동일 입력·결과·권한·pin·순서 보존. immutable 이력과 실패 기록은 재작성하지 않음.
- 해당 단위 검사와 필요한 중단·경합·재전송 검사. DB mutation 검사는 disposable DB에서만 실행.
- query/parse/hash/IO 횟수와 처리시간에 영향을 주면 전후 비교. 파일 수 감소만을 성과로 삼지 않음.
- source 검증, 설치 검증, 실제 사용자 경로를 구분. 필요한 운영 반영은 별도 승인 범위에서 수행.

이 목록을 이유로 새 범용 framework, queue, 권한 우회, 전체 microservice 분리, 일괄 재임베딩,
과거 계약·벡터·Artifact 삭제를 시작하지 않는다. 현재 문제를 기존 책임 경계에서 단순하게
해결하고, 그 경계를 다음 유지보수자가 바로 찾을 수 있게 만드는 것이 목표다.

## 수정 작업 기록 — 2026-11-08

위 목록은 수정 전 기준선이다. 아래는 사용자가 승인한 구현·검증·배포 작업의 후속 기록이며,
설치 및 실제 운영 검증 전에는 OPEN 항목을 운영 해결로 재분류하지 않는다.

### 최소 변경 설계

1. 책임은 기존 creative application의 중단, INDEX verifier의 안전한 원인 번역,
   API exact-result navigation, 각 실행기의 ORM composition이다. 새 서비스는 없다.
2. 정본은 기존 accepted source/Graph, 고정 runtime, Item Revision과 artifact다.
   종료 status와 readiness detail은 관측값이며 실행 권한이나 완료 영수증이 아니다.
3. 논리 ID·revision·artifact·hash 모델을 바꾸지 않는다. 새 DB/wire schema가 없어
   released schema bytes와 migration head를 유지한다.
4. navigation의 revision/hash/schema/media/member 검사는 그대로이며 staging alias를
   canonical member 대신 쓰지 않는다. runtime의 전후 파일 identity 검사도 유지한다.
5. 주 접근은 stop flag 조회, 하나의 in-flight publication 대기, 제한된 batch lookup,
   AST graph traversal, fresh process의 metadata FK 해석이다.
6. 기존 Event/Future·cohort flock·dict/set·SQL batch와 FK를 재사용한다.
   새 queue/cache/index/registry를 만들지 않는다.
7. navigation은 최대 64개 입력에 O(n) map, 기존 후보 batch 조회 호출 1회다. 의존 검사는 O(V+E),
   원인 전달은 O(1)이며 기존 파일 검증 비용을 늘리지 않는다.
8. stop 시 신규 advance/publication을 막고 이미 시작한 발행을 join한 뒤 fence를 해제한다.
   DB commit·unique/CAS·재조회·replay는 원래 소유 서비스가 계속 담당한다.
9. public facade는 유지한다. HWPX/Runner의 실제 누락된 occurrence FK만 기존
   composition에 명시한다. domain으로 SQL/OS 처리를 옮기지 않는다.
10. failure는 실패로 남고, 알려지지 않은 verifier 오류도 제한된 코드로 거부한다.
    중단 요청과 기술 오류가 동시에 발생해도 `STOPPED`로 실패를 덮지 않는다.
11. `wait=False`·전체 ORM 무조건 import·top-k만 권한 검사·새 범용 repository보다
    기존 owner의 작은 수정이 불변식과 복구 경로를 보존한다.

### R01–R05 구현 범위

- R01: stop callback을 parallel application에 전달해 중간 종료 후 신규 작업을 막는다.
  runner는 `DRAINING → close → STOPPED → fence release` 순서를 지키고 close 실패와
  원 작업 실패를 그대로 기록한다. systemd 종료 한도는 180초에서 **1,800초**로 정렬한다.
  이는 과거 180초 SIGKILL보다 긴 **명시적 유지보수 예산**이며 무한 I/O 성공 보장이 아니다.
  배포는 SIGINT 선행 drain 후 quiescence를 확인하며 강제 종료로 시간을 맞추지 않는다.
- R02: verifier timeout/파일 변경/실행 거부/OS 오류/control 불일치를 closed enum으로 구분.
  readiness 원래 외부 코드는 유지하고 안전한 내부 detail과 한 줄 warning만 제공한다.
  원문 exception·stderr·경로·secret을 기록하거나 자동 재시도하지 않는다.
- R03: 실제 Python package만 탐색해 CLI도 포함하고 egg-info를 제외한다.
  dotted/relative import를 정규화하며 기존 service SCC 외 순환 의존을 검출한다.
- R04: `item_candidate_navigation.py`로 exact 결과→문항 검증만 이동했다.
  기존 SQL adapter·permission·필터·batch limit은 그대로이고 후보 batch 조회 호출 수는 1회다.
  순서 유지·중복/누락 거부·canonical alias 회귀 검사를 추가했다. 속도 향상을 주장하지 않는다.
- R05: 독립 API/Catalog/Runner/Manager import 검사에서 Runner/Manager의 occurrence
  FK 정의 누락을 실제 재현했다(첫 실행 96 PASS, 2 FAIL). 두 composition에 정확한
  owner model만 추가해 네 진입점의 fresh-process FK/DDL 검사를 통과시켰다.
  shared transaction과 기존 허용 service SCC를 재설계하지 않았다.

### Q01–Q05 판정

- Q01: 기존 INDEX 로그의 긴 reconciliation은 확정이지만 전체 시간이 어느 SQL/권한/
  NAS 단계의 반복 비용인지 분해된 증거는 없다. 현재 `local_indexing_service_entry`의
  phase/elapsed 관측을 유지한다. 무관한 재임베딩·대형 cache를 만들지 않는다. 추가 측정 대상.
- Q02: 저장 ranking hit가 벡터 재계산 없이 immutable snapshot을 읽고, 전후 전체
  dependency fingerprint로 철회를 검사하는 것을 코드에서 확인했다. top-k만 검사하면
  계약 의미가 바뀐다. R04의 단일 batch 및 재조회 회귀를 보존하고 임의 검사를 삭제하지 않는다.
- Q03: legacy preview pin과 새 choice-layout-v3 pin의 차이는 호환성/기능 확장 항목이다.
  기존 cohort의 자료를 최신 PDF로 몰래 바꾸지 않는다. 이 설계 보완 릴리스에서는 입력 유지.
- Q04: facade의 크기만으로 오류 인과관계가 확인되지 않았다. R04의 실제 문제 경계만
  분리하고 WorkflowCatalog/Web 전체 분해는 하지 않는다.
- Q05: `eomctl.cli.job_submit`은 기존 Orchestrator 제출을 호출하며 read 명령은 운영 조회다.
  private helper 참조만으로 별도 오류를 확인하지 못했다. R03에서 CLI 검사 누락은 고쳤고,
  검증되지 않은 새 orchestration 계층은 만들지 않는다.

Q 항목은 수정 완료로 가장하지 않으며 **이번 릴리스 필수 결함으로 승격하지 않음**으로 판정한다.
새 원인 증거가 나오면 기존 담당 모듈에서 후속 작업으로 다룬다.

### 소스·DB 검증 결과

- focused source/경계/navigation/독립 ORM/실제 Future drain: **158 PASS**.
- 개발 문맥 링크/index 검사: **13 PASS**. Ruff format/check, focused mypy 8개 source PASS.
- disposable PostgreSQL migration 왕복/head·role 검증 PASS.
  Graph acceptance·중복 생성·원 retry 재조회·원자성 **10 PASS**, 검색 history·동시 replay
  **6 PASS**, INDEX identity/fence/source policy **258 PASS**, HWPX persistence **30 PASS**.
- HWPX suite의 별도 설치 Builder end-to-end 1건은 opt-in 미설정으로 SKIP.
  이번에는 Builder·HWPX bytes/renderer를 바꾸지 않아 새 출력 acceptance를 만들지 않았다.
- 최초 cold-import 2건 실패를 재현 후 수정했고, 후속 fresh-process 4개 진입점은 PASS.
  한 차례 suite 파일명 오기(`test_catalog_api_boundary.py`)는 수집 실패였으며
  올바른 `test_catalog_application_boundary.py`로 위 focused suite를 다시 실행했다.
- 운영 DB에는 pytest를 실행하지 않았다. 설치·배포·운영 상태는 후속 증거로 별도 기록한다.

### 종료 검증의 최종 보강

마지막 완료 기준 대조에서 기존 Graph replay 검사만으로는 DB commit 직전·직후 중단을
직접 재현한 증거가 부족함을 확인했다. production 코드를 추가로 바꾸지 않고
`test_graph_publication_interruption.py`를 기존 disposable `creative-graph-tests`에 연결했다.

- Artifact 작성 전, Artifact 작성 후/Graph DB 작업 전, DB commit 직전, commit 후/응답 전
  네 지점에 한정한 예외를 주입했다. 새 application instance가 같은 요청으로 복구한다.
- commit 전에는 Graph corpus/publication row가 남지 않고, commit 후에는 하나의 정본이
  이미 존재한다. accepted 분석·workflow·worker job identity는 유지되며 모델 재실행이 없다.
- 이미 작성된 Artifact는 재사용한다. 복구 후 같은 요청 재조회에서도 publication 1개이고
  Artifact/Job/analysis row가 추가되지 않는다.
- shared Graph publication의 기존 V1 격리 fixture로 실제 PostgreSQL transaction을 검사한
  것이며, 운영 창작 문항을 재생성하거나 새 V11 결과를 모델에 요구한 검사가 아니다.
  창작 accepted membership 재사용은 기존 application unit tests가 별도로 보호한다.
- 보강 suite **14 PASS**. 최초 세 번의 실행은 새 fixture의 UTC 직렬화, 생성 전/승인 후
  job baseline 시점, surrogate PK 조회 오류로 실패했다. 모두 test-only 수정이며 실패 로그를
  보존했다. 운영 코드 오류로 분류하거나 최초부터 PASS였다고 보고하지 않는다.

실제 서비스 인계와 설치 후 검증은
[운영 릴리스 기록](../operations/ARCHITECTURE_REMEDIATION_RELEASE_2026-11-08.md)을 참조한다.

### R04 전후 조회 비용 대조

17:36 UTC, 최초 기준 `8b5848df`의 두 navigation 메서드와 설치된 `b9007cbd` 메서드를
동일 read-only adapter·실제 승인 문항 3개로 비교했다. 기존 메서드 추출은 개발 검증
harness에만 사용했으며 운영 package가 Git/source를 읽게 만들지 않았다.

- 전후 결과/순서와 실행된 SQL statement 목록 동일. 각 요청 SQL **7회**.
- 전: 8.8ms / 7.0ms, 후: 7.1ms / 7.0ms. 작은 read-only 표본이며 속도 향상 주장이 아니다.
- 앞서 쓴 ‘SQL 1회’는 후보 batch application 호출 1회와 혼동한 표현이어서 바로잡았다.
  문항별 N+1 호출은 추가하지 않았다. 전체 ranking/GUI 지연을 이 측정으로 대신하지 않는다.
- 첫 비교 harness는 제거된 import(`TypeAdapter`)를 주입하지 않아 실패했다. 검증 도구만
  수정하고 같은 읽기 검사를 완료했으며 운영 source/DB/모델 실행은 바꾸지 않았다.

### 최종 판정

R01–R05는 source와 설치 검증을 거쳐 기존 담당 서비스에 반영했다. INDEX는 실행 중이던
CPU/CUDA 요청 두 건을 정상 완료시킨 뒤 인계했다. 진행 중 요청의 pin을 바꾸거나 결과를
재작성하지 않았다. 종료 직전 생성된 미실행 CPU standby 1건은 기존
`local-indexing-unstarted-cancellation/1.0`의 무시도·무lease·무step 검증과 취소 영수증으로
정리했다. 직접 row 변경, 실행된 계산 취소, 실패→성공 변환은 없다.

Q01–Q05의 확인 결과와 한계는 위 판정을 유지한다. 특히 긴 source reconciliation의
단계별 성능 개선은 별도 측정 대상이지 이번 구조 변경으로 해결됐다고 주장하지 않는다.
