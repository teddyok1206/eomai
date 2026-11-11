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

INDEX의 같은 DB root에서 반복하는 전체 풀이 해석은 `public_solution_index_read_set`이
한 번만 수행한다. 매 호출의 현재 service 권한·source 관계·producer provenance 검사는
유지한다. `public_solution_population_dependencies`는 저장된 검색 결과와 INDEX가 함께
쓰는 bounded SQL 의존관계 관측이며, 권한 cache가 아니다. root가 바뀌면 원본 파일과
보고서를 다시 strict capture한다. 완성 vector/report나 입력 text는 수정하지 않는다.
Registry의 clean savepoint에서는 그 정확한 transaction frame 안에서만 capture를 재사용한다.
frame 진입·종료·rollback·형제 전환 및 dirty session은 strict capture로 돌아간다.
rollback된 capture를 outer root로 가져오지 않는다. 사람/QUERY 관측의 clean-root 조건은
그대로다. INDEX의 별도 frame 검사 진입점이 같은 SQL closure 구현을 사용한다.
설계와 측정 범위는 `docs/architecture/PUBLIC_SOLUTION_INDEX_CAPTURE_REUSE.md`를 참고한다.

공개 QUERY도 `public_solution_index_read_set.capture_public_solution_query_population`에서
같은 root의 전체 보고서 해석을 재사용한다. 실제 사용자/scope/recipe와 fresh SQL closure는
매번 확인하고, 새 root·다른 thread·nested QUERY에서는 재사용하지 않는다. membership은
`local_indexing_source_paging.read_candidate_source_pages`가 제한된 작은 ID 목록을 한 번
읽어 기존 bounded page로 나눈다. 원본 자료와 보고서의 페이지별 검증 한도는 그대로다.
전후 전체 membership·dependency SHA는 기존 방식과 같아야 한다. 설계/측정 경계는
`docs/architecture/SIMILARITY_SEARCH_READ_COST.md`에 기록한다.

후속 비용 개선은 `docs/architecture/INDEX_PUBLICATION_READ_COST.md`에 기록한다.
Catalog의 hash-pinned schema별 validator/resolver와 root-local 불변 shard/result 해석을
재사용하지만, 각 payload 검증·source 권한·현재 provenance·벡터 finite/L2 검사는 유지한다.
입력 text/모델/space/수치 batch size는 바꾸지 않는다. 실제 운영 선택은 release 기록으로 확인한다.

공개 index3/4/5의 전체 manifest는 `raw_public_solution_contract_value`의16,384 경계를
쓴다. membership 재검증·version dispatch·receipt의 전체 index를 legacy1,024 reader로
먼저 감싸면 정상 저장된 큰 head도 다음 discovery에서 거부된다. legacy1/2·개별 shard와
페이지 제한은 그대로이며, manifest 용량과 구형 workflow/source-plan 입력 용량을 혼동하지
않는다. 현행 INDEX5 복구 근거는
`docs/operations/INDEX_PUBLICATION_PERFORMANCE_2026-11-09.md`의2026-11-10 후속 기록과
`tests/unit/test_public_index_refresh_capacity.py`를 확인한다.

QUERY의 `embedding_device_index_pair.validate_resolved_embedding_index`도 전체 manifest를
같은 version dispatcher에 직접 넘긴다. 먼저 legacy raw reader로 감싸면 정상적으로
등록한 1,024개 초과 public head가 장치 선택 전에 거부된다. 개별 pointer 검증과
CPU/CUDA space·Graph·policy·공통 source 증명은 유지하며 legacy 한도를 늘리지 않는다.

GPU controller가 `FILE_UNPROTECTED`로 끝나면 owner의 EOF는 선행 오류가 아닐 수 있다.
고정 proc member는 dumpability 전환으로 storage UID0/worker가 바뀔 수 있으며 actual
프로세스 자격과 구분한다. `read_live_native_process_member`는 identity 오류와 실제
허용 UID 전환이 함께 있을 때만 protected read를 한 번 재시도한다. 일반 파일 보호와
caller의 UID/GID·birth·unit 검사는 그대로다. INDEX 전용 controller delegation을 쓰면
QUERY/controller 주 진입점·수치 runtime은 보존할 수 있다. 상세 검증은 위 운영 기록과
`tests/unit/test_embedding_native_process_member_transition.py`를 확인한다.

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

GPU allocation의 준비·완료 확인 시간과 모델 계산 제한은 다르다. 새 allocation은
유한 control allowance를 포함하지만 기존 absolute expiry를 갱신하지 않는다. worker의
kernel timer는 backend lifetime을 감싸며 출력 ACK에는 원 allocation deadline을 적용한다.
실측 실패와 호환 배포 경계는 `docs/architecture/EMBEDDING_ALLOCATION_SETTLEMENT_BUDGET.md`다.

INDEX의 OS 상태 조회는 Identity `local_indexing_runtime._unit`에서 timeout만
2/5/10초로 제한 재시도한다. 임베딩 submit/commit이나 전체 workflow 재실행이 아니다.
응답을 얻으면 기존 invocation/파일 검사를 그대로 수행하고, 실제 변경·잘못된 응답과
지속된 조회 불가는 거부한다. 복구 근거는
`docs/operations/INDEX_UNIT_OBSERVATION_RECOVERY_2026-11-07.md`를 확인한다.

숫자 계산과 encoding commit은 성공했지만 INDEX_PREPARED 이후 릴리스가 바뀐
요청은 `index_publication_recovery`의 명시적 root/schema-owner 유지보수로만 이어간다.
정확한 원래 request/intent/registration hash와 현행 동등 source grant를 확인한다.
CPU/CUDA 장치와 모델은 원래 request에 고정하며 계산 실행은 둘 다 금지된다.
새 source discovery·submit·수치 실행을 할 수 없는 executor가 기존 Runner와 Catalog/
Orchestrator publication을 재사용하며, 일반 서비스 권한이나 GPU PID는 바꾸지 않는다.
설계·실제 완료 여부는 `docs/operations/RETIRED_INDEX_PUBLICATION_RECOVERY.md`를 참조한다.
기존 prepared head가 이미 앞선 경우 원래 revision의 등록을 강행하지 않는다.
`index_publication_successor`는 명시적으로 pin한 새 predecessor와 성공한 encoding을
검증해 새 index만 등록하며, 원래 요청은 publication 대체 사유로 종료한다. 일반
INDEX/QUERY 경로와 encoding 성공 이력은 바꾸지 않고 같은 복구 계획은 재사용한다.

CPU counterpart 준비는 선택한 일부 자료의 세대가 아니라 원 요청의 public envelope를
유지한다. 전체 population이 5.0인데 선택분이 구형이라고 request4로 낮추지 않는다.
이 차이로 INDEX_PREPARED 전에 중단된 과거 요청은 recovery2의 allocation checkpoint와
staged member hash를 함께 고정해 같은 successor 경계에서만 복구한다.
`docs/operations/INDEX_COUNTERPART_ENVELOPE_RECOVERY_2026-11-09.md`에 재현·검증을 기록한다.

## DB 화면의 실제 검색 경로

조회에서 기준 문항을 골라 유사도 탭으로 넘기고, 기준 목록·상위 결과 수·요청 identity를
보존한다. 목록 검색은 API의 `item_db_similarity_searches.py`, 개별 요청은
`item_db_similarity.py`에서 시작한다. 준비 → 실행 → 결과 조회를 각각 추적한다.
완료 결과 확인과 최근 기록 열기는 새 검색 생성이 아니다. 로그인 복귀·head 이동·늦은
응답 때문에 원래 pin을 잃고 새 계산을 제출하지 않도록 한다. 결과 문항은 정본 revision으로
DB 조회와 조립 선택에 돌아가야 한다.

검색 결과의 exact Item 해석은 API `item_candidate_navigation.py`가 담당한다.
`QueryAdapter.selected_production_item_candidates()`는 공개 진입점을 유지하며 기존
후보 조회를 한 번만 호출한다. canonical artifact member와 worker staging alias는
서로 다른 값이며, revision/hash/schema/media를 검사한 뒤 요청 순서로 돌려준다.
문항마다 다시 조회하거나 latest로 대체하지 않는다.

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

목록 UI는 `REFERENCE_QUERY_PREPARE_UNAVAILABLE` 관측 실패만 같은 search ID로
5/10/20초에 제한 재확인한다. 새 검색 제출·인증 우회가 아니며 계정/요청 변경 또는
다른 오류에는 자동 재확인하지 않는다. parent batch의 SUCCEEDED는 CPU fallback에서
binding 준비 완료일 수 있다. 결과 완료는 child Workflow/selection으로 확인한다.
CPU fallback의 root 준비 entrypoint는 QUERY owner와 별도 env로 선택된다. 배포 때
`embedding-native-query-owner.env`가 실제 선택한 설치 parser로 현재 Workflow5 입력을
검증해야 한다. owner READY나 numerical QUERY2 parser PASS만으로 이 경계를 대신하지 않는다.

## 먼저 열 파일

- `apps/application_api/eom_api/services/item_db_similarity_searches.py`
- `apps/application_api/eom_api/services/item_db_similarity.py`
- `apps/application_api/eom_api/services/item_candidate_navigation.py`
- `apps/web_gui/eom_web_gui/static/item-db-similarity-list.js`
- `apps/web_gui/eom_web_gui/static/item-db-similarity.js`
- `services/workflow_runner/eom_workflow_runner/local_indexing_service_entry.py`
- `services/workflow_runner/eom_workflow_runner/local_indexing_cpu_lane.py`
- `services/workflow_runner/eom_workflow_runner/local_indexing_routed_namespace.py`
- `services/workflow_runner/eom_workflow_runner/reference_query_prepare_application.py`
- `services/catalog_service/eom_catalog_service/public_solution_source_capture.py`
- `services/catalog_service/eom_catalog_service/public_solution_index_read_set.py`
- `services/catalog_service/eom_catalog_service/public_solution_population_dependencies.py`
- `services/catalog_service/eom_catalog_service/embedding_registry_models.py`
- `services/catalog_service/eom_catalog_service/completed_public_ranking_read.py`
- `services/catalog_service/eom_catalog_service/completed_public_ranking_dependencies.py`
- `services/orchestrator/eom_orchestrator/completed_public_ranking_artifact.py`

## 고장이 났을 때

QUERY의 실패 단계와 같은 요청의 실제 상태를 먼저 본다. API READY/테스트 PASS를
GUI 결과 목록 성공으로 대체하지 않는다. `결과 확인`의 부작용, CSRF/session 갱신,
stale pin, 결과 materialization을 구분한다. 새로운 key로 우회하기 전에 원래 요청을 읽는다.

`ADMIT_PROVIDER / OWNER_SESSION_PROVIDER_UNAVAILABLE`는 사용자 비밀번호 오류와 다르다.
Identity의 installed provider observer가 실제 API process/file identity를 검사한다.
systemd 읽기 timeout만 2/3초로 한 번 재시도하며, 잘못된 응답·교체된 프로세스·파일은
그대로 거부한다. 로그인·session capture·검색 submit을 재시도하거나 권한을 캐시하지 않는다.
QUERY driver 진단은 제한된 authority 오류 코드와 위치만 남기며 원문/인증값은 남기지 않는다.

`reference_query_routed_execution`은 원 CUDA allocation이 BOUND 전에 마감되면
기존 FAILED 읽기 결과를 반환한다. PENDING 재조회가 원 GPU channel을 다시 시작하지
않는 규칙은 유지한다. BOUND/완료 결과는 이 준비 마감 판정에서 제외한다. 이 projection은
과거 Job/Workflow를 변경하거나 물리 종료·새 실행 권한을 증명하지 않는다.

GPU descriptor 설치의 `daemon-reload`는 해당 unit만이 아니라 PID1 전체 설정을 읽는다.
`embedding_gpu_batch_unit_descriptor`는 실측10초 초과 reload를 허용하는30초 단일
대기를 사용한다. timeout 후 reload/dispatch를 재시도하지 않으며 계산 제한과 원래
allocation 마감은 그대로다. QUERY controller 교체 시 기존 INDEX purpose delegation과
its controller pin을 보존한다.

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
