# 유사도 검색과 증분 임베딩

## 정본과 검색 후보

GraphRAG는 출처·개념 관계·접근 권한을, 벡터는 후보 순위화를 돕는다. 벡터로 Graph를
대체하거나 별도 source DB를 만들지 않는다. 기출·창작·AI의 공개 풀이와 내용/metadata를
어떤 view/profile로 입력하는지는 정본 projection과 source binding으로 확인한다.
입력 텍스트·profile·view·model/runtime space가 다르면 같은 문항도 같은 벡터가 아니다.

공개 풀이보고서의 관계/판단 근거를 쓰되, 단순히 공통 과목·유형이 같다는 것과 실제
풀이 착상이 가깝다는 것을 구분한다. 유사도는 풀이 동일성의 확률이나 표절 판정이 아니다.
필요한 설명은 `docs/architecture/ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md`와
`SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md`에서 확인한다.

## 두 독립 실행 경로

INDEX는 eligible source와 공개 풀이를 capture해 delta를 계산하고, 기존 encoding을
재사용하거나 CPU/CUDA 수치 실행 뒤 shard/binding/index head를 commit한다.
QUERY는 사용자가 선택한 기준 문항과 고정한 Graph/policy/index 범위를 받아 검색한다.
전체 INDEX 완료를 기다리지 않고 준비된 subset을 검색할 수 있어야 한다.

CPU와 CUDA의 space identity를 섞지 않는다. GPU가 잠시 idle이어도 source 준비·인덱스
저장·다른 device namespace 처리가 진행 중일 수 있다. 모델 연산 성공과 인덱스 commit,
Workflow COMPLETED는 각각 확인한다. 같은 encoding의 재사용과 최신 Graph membership의
새 binding/index 반영도 서로 다르다.

새 등록 문항의 V11 보고서는 직접 공개 조회 성공과 INDEX/QUERY의 strict reader 성공을
따로 확인한다. `solution_evidence_resolution.accepted_public_solution_successor_predicate`가
기출 V10과 등록 V11의 accepted successor를 함께 선택한다. source pool의 한정된 bulk
prefetch와 dependency observation이 같은 조건을 쓴다. 필요한 Artifact가 준비되지 않았을
때 검증을 생략하거나 문항마다 개별 DB 조회로 우회하지 않는다.

공개 풀이 INDEX의 신규 미계산 대상은 기존 preparation이 출처별로 번갈아 선택한다.
기출을 먼저 선택하고 같은 출처 안에서는 revision 순서를 유지해, 늘어나는 등록 문항의
ID prefix가 기출 backlog를 계속 밀지 않게 한다. legacy namespace·고정된 기존 요청·
이미 계산한 encoding 재사용과 membership-only 규칙은 바꾸지 않는다. CPU standby는
같은 owner의 기존 queue/Runner를 사용한다. routed owner의 `local_indexing_cpu_lane`은
outstanding 호출 하나만 별도 thread에서 실행해 GPU discovery를 막지 않는다. 별도
service/queue가 아니며, CPU-only 구버전은 순차 동작을 유지한다. stop/failure 시 이미
시작한 호출을 drain한 뒤 runtime capture/Engine을 닫는다. QUERY 우선과 두 장치의
서로 다른 space, 정확한 공통 published scope는 그대로다. 설계는
`docs/architecture/LOCAL_INDEXING_CPU_GPU_OVERLAP.md`를 참고한다.

## DB 화면의 실제 검색 경로

조회에서 기준 문항을 골라 유사도 탭으로 넘기고, 기준 목록·상위 결과 수·요청 identity를
보존한다. 목록 검색은 API의 `item_db_similarity_searches.py`, 개별 요청은
`item_db_similarity.py`에서 시작한다. 준비 → 실행 → 결과 조회를 각각 추적한다.
완료 결과 확인과 최근 기록 열기는 새 검색 생성이 아니다. 로그인 복귀·head 이동·늦은
응답 때문에 원래 pin을 잃고 새 계산을 제출하지 않도록 한다. 결과 문항은 정본 revision으로
DB 조회와 조립 선택에 돌아가야 한다.

CPU/GPU head는 다른 Graph까지 진행할 수 있다. 최초 DB 검색은 registry의
`common_public_namespace_revisions`로 두 장치의 이미 게시된 공통 scope를 고정한다.
public prepare는 `public_revision_for_scope`로 그 Graph/policy의 exact revision을 읽는다.
최신 GPU head와 다른 CPU head를 섞거나 Graph/hash 검사를 생략하지 않는다. 이 공통
게시 범위 밖의 새 source는 준비 필요이며, 이를 모든 GPU binding의 검색 완료로 과장하지 않는다.

DB의 완료 결과 재열람은 `completed_public_ranking_read.py`가 원 QUERY의 검증된 후보·점수와
exact revision을 작은 immutable `ranking.json`으로 저장해 재사용한다. 기존 Orchestrator
`ControlFileSetPublisher`와 고유 Job key를 사용하며 새 DB/queue/model service는 없다.
hit도 실제 사용자·고정 Graph/policy와 fresh SQL dependency fingerprint를 확인한다.
전체 풀이/NAS 문항/벡터를 다시 decode·순위 계산하지 않으며, 달라진 source나 손상된 저장
결과를 latest/새 계산으로 숨기지 않는다. 최초 저장은 기존 전체 검증을 한 번 거친다.

## 먼저 열 파일

- `apps/application_api/eom_api/services/item_db_similarity_searches.py`
- `apps/application_api/eom_api/services/item_db_similarity.py`
- `apps/web_gui/eom_web_gui/static/item-db-similarity-list.js`
- `apps/web_gui/eom_web_gui/static/item-db-similarity.js`
- `services/workflow_runner/eom_workflow_runner/local_indexing_service_entry.py`
- `services/workflow_runner/eom_workflow_runner/local_indexing_cpu_lane.py`
- `services/workflow_runner/eom_workflow_runner/local_indexing_routed_namespace.py`
- `services/workflow_runner/eom_workflow_runner/reference_query_prepare_application.py`
- `services/catalog_service/eom_catalog_service/public_solution_source_capture.py`
- `services/catalog_service/eom_catalog_service/embedding_registry_models.py`
- `services/catalog_service/eom_catalog_service/completed_public_ranking_read.py`
- `services/catalog_service/eom_catalog_service/completed_public_ranking_dependencies.py`
- `services/orchestrator/eom_orchestrator/completed_public_ranking_artifact.py`

## 고장이 났을 때

QUERY의 실패 단계와 같은 요청의 실제 상태를 먼저 본다. API READY/테스트 PASS를
GUI 결과 목록 성공으로 대체하지 않는다. `결과 확인`의 부작용, CSRF/session 갱신,
stale pin, 결과 materialization을 구분한다. 새로운 key로 우회하기 전에 원래 요청을 읽는다.

구형 벡터는 모든 참조 전환과 새 검색 검증 전에는 지우지 않는다. 기존 520개 기출 모집단,
승인 Item 수, view별 binding 수, 재시작 후 traversal 수는 다른 분모다.

## 검증과 근거

- `tests/api/test_item_db_similarity_searches.py`
- `tests/unit/test_native_office_public_embedding.py`
- `tests/unit/test_background_resource_recovery.py`
- `tests/unit/test_public_indexing_target_selection.py`
- `tests/unit/test_local_indexing_cpu_overlap.py`
- `tests/integration/test_local_embedding_runner.py`
- `tests/unit/test_completed_public_ranking.py`
- `tests/integration/test_completed_public_rankings.py`
- `docs/operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md`
- `docs/operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md`
