# 문항 DB와 Graph 등록

## 출처와 상태를 분리

사용자 분류는 기출·창작·AI이며 교과서는 별도 근거 출처다. 창작은 가져온 기존 제작 문항,
AI는 EOM에서 생성한 문항이다. 분류에 승인 여부를 섞지 않는다. 화면의 고유번호와
논리 Item ID·Item Revision ID·Artifact ID·hash도 별개다. 내부 ID를 사용자 기본 화면에
되살리는 방식으로 조회 기능을 붙이지 않는다.

외부 원본의 메타데이터와 Registry에 등록된 Item이 별도 조회 경로를 가질 수 있으나,
등록됐다는 이유로 원본 메타데이터/필터가 사라져서는 안 된다. 원본 파일·등록 문항·
풀이보고서는 lineage를 통해 연결한다. Graph는 교과서·기출·창작·AI를 공통 개념/관계와
출처 포인터로 잇는다. layer 구분은 분리된 독립 검색 DB를 만드는 근거가 아니다.

## Map

`데이터 → Map`은 기존 published Graph의 읽기 전용 인접 탐색이다.
`knowledge_map_read.py`가 snapshot/hash와 노드·관계·출처 메타데이터를 bounded SQL로 읽고,
`knowledge-map.js`가 표시한다. 기존 학습 범위·품질 보고서는 `knowledge-quality` view에
보존한다. AI/창작은 origin profile 또는 정확한 과거 등록 Workflow family로 구분하며,
worker RAG policy나 evidence receipt를 우회하지 않는다. 문항 열기는 동일 Item revision/hash의
새로운 DB 읽기다. 상세 설계: `docs/architecture/KNOWLEDGE_MAP_READ_DESIGN.md`.

## 가져오기와 실제 그림

파일 확장자보다 검증한 실제 media/container를 따른다. `.hwp`여도 내용이 HWPX면
HWPX로 판별하는 경계를 유지한다. 기본 최종본 선택은 3교, 없으면 반려되지 않은 2교이며
1교는 최종본이 아니다. 재수입은 기존 source/revision/observation identity로 판정한다.

그림은 한글 본문 내장 이미지의 실제 picture use를 가져온다. member 파일만 무작정
모두 저장하거나 추정한 PDF 사각형 crop을 기본으로 쓰지 않는다. viewport·회전·라벨·
본문 순서를 보존한다. 참고 기출/해설 위치의 사용 개체를 제외하되, 본문에서도 쓴
동일 binary member까지 지우지 않는다. 정확히 표현할 수 있는 표·수식은 native로 남긴다.

## 순차 처리와 공개 풀이

`creative_cohort_execution.py`가 원래 selection의 Workflow를 읽고 registered source와
accepted analysis를 잇는다. 병렬 driver는 bounded source window와 단일 Graph publication
future를 소유한다. 슬롯이 RUNNING이어도 후속 Graph owner가 멈췄을 수 있고,
반대로 publication/입력 준비 중에는 일부 슬롯이 비어 있을 수 있다.

`creative_item_graph_learning.py`는 같은 accepted report를 기존 shared Graph에 반영한다.
source/operator 권한과 report lineage를 다시 검증한다. publication 후 공식 공개 풀이 조회는
저장된 경고/이상 기록까지 보이는지 확인한다. 내용상 문제를 기록하는 것과 기술적 실패를
성공으로 꾸미는 것은 다르다. 기존 FAILED는 보존하고 지원된 reconcile/retry만 쓴다.

## 먼저 열 파일

- `apps/application_api/eom_api/routers/item_db.py`
- `apps/application_api/eom_api/services/external_item_db_read.py`
- `services/catalog_service/eom_catalog_service/external_item_read_service.py`
- `services/catalog_service/eom_catalog_service/external_item_models.py`
- `services/catalog_service/eom_catalog_service/creative_cohort_execution.py`
- `services/catalog_service/eom_catalog_service/creative_cohort_parallel_execution.py`
- `services/catalog_service/eom_catalog_service/creative_item_graph_learning.py`
- `services/orchestrator/eom_orchestrator/office_picture_use_publication.py`

`apps/web_gui/eom_web_gui/static/item-db.js`가 조회 UI의 시작점이다. 조립은
`curated_document_assembly_service.py`와 관련 typed manifest를 확인한다. 조립 순서 저장이
원본-only 문항의 편집 가능한 HWPX 합본 완료를 뜻하지는 않는다.

조립 초안·제목·최근 저장본·목록 삭제의 화면 책임은 `item-db-assembly.js`에 있다.
제목을 받는 draft V2는 기존 V1 placement selection으로 정규화하며, title은 논리 조립의
작은 불변 metadata다. 삭제는 소유자의 목록에서 숨기는 공식 명령이다. revision/placement,
진행 중 제작과 기존 HWPX 참조를 물리 삭제하지 않는다. 삭제 재시도는 exact revision/hash와
동일 key를 유지한다. `curated_document_assembly_library.py`의 별도 closed RPC와 migration73을
확인하고 이전 V1 계약을 고치지 않는다. 교체 대상은 가변 행 번호가 아니라 원 pointer다.

선택형 필터 값은 `external_item_filter_options.py`의 명시적 categorical fields와 Catalog의
`read_external_item_filter_options`를 따른다. 원본 Excel에는 Notion 속성 타입 선언이 없으므로
이를 복원했다고 주장하지 않는다. namespace의 COMPLETED import/current revision에서 실제
원문 값을 한 SQL DISTINCT/window 연산으로 최대200개씩 읽는다. 줄글 필드는 그대로 입력하고,
복합 원문 값을 임의로 분할하지 않는다. 선택지 제한/조회 실패에도 직접 입력 경로는 유지한다.

## 검증과 근거

통합 업로드 학습은 `docs/architecture/MATERIAL_LEARNING_UPLOAD_PIPELINE.md`와 두 번의
설계 검토 기록을 먼저 읽는다. 현재 구현 후보의 `material_learning_*`는 원래 Notion
archive 파이프라인과 다른 입력 lineage를 쓰되 기존 Artifact/Document/Registry/Graph
소유자에 연결한다. `material_page_source_read.py`가 준비·실행 재인가·설명 분석의
canonical page membership을 함께 검증한다. 일반 설명 source V5/request V12와
snapshot V10은 구 교과서 계약을 완화한 것이 아니다. source/role receipt, 등록 Pack이
있다는 사실만으로 전체 coordinator나 운영 활성화가 완료됐다고 추정하지 않는다.
최신 미완료 항목은 `docs/operations/MATERIAL_LEARNING_IMPLEMENTATION_CHECKPOINT.md`.

자료 설명 append는 기존 structured Graph V2–V6에 해당하는 공식 publication을 선택한다.
미출시 snapshot V10이 일반 자료 source를 보존하며, 설명을 추가하려고 기존 교과서
Graph에 가짜 기출/문항 placement나 구조 V6를 강제하지 않는다. 실제 임시 DB 경로는
`tests/integration/test_material_learning_graph_pipeline.py`, 일반형 등록 문항의 base/V11
공개 풀이·공통 embedding text 경계는 `test_material_item_registration_storage.py`를 본다.

새 통합 업로드 문항의 사용자 분류는 외부 / `EXTERNAL`이다. 기존 Notion 창작 /
`CREATIVE`, 기출, AI를 바꾸지 않는다. `material_item_registration.py`가 원문/그림과
작은 lineage를 원래 Registry에 등록하고 `material_graph_learning.py`가 실제 base 및
V11 공개 풀이를 기존 analysis owner로 만든다. `material_learning_processing.py`와
coordinator가 작은 task checkpoint와 자료 전체 단일 AI lane을 소유한다. 모델 명령·물리
슬롯·host 동시 제한은 원래 Workflow/Orchestrator의 책임이다. runtime/service 후보가
존재한다는 사실을 운영 활성화 증거로 쓰지 않는다.

`MaterialLearningIntakeService.control`은 기존 run의 pause/resume를 actual actor와
updated_at CAS로 처리한다. BFF/GUI 버튼은 같은 control을 호출한다. 자료 coordinator는
별도 모델 Runner를 만들지 않으며 원래 global Workflow Runner가 자식 command를 실행한다.
PDF command port는 기존 sandbox, 한글 conversion port는 기존 Catalog-manager workspace를
사용한다. 각 adapter의 실제 설치 증거와 후보 상태는 operations checkpoint에서 구분한다.

API `GET /item-db/materials`와 DB 외부 분류는 current shared Graph membership을 확인해
작은 등록 metadata를 읽는다. Notion 행이나 임의 고유번호를 만들지 않는다. Map V2는 같은
Graph에서 외부 layer를 표시하며 V1 bytes/소비를 보존한다. 새 설명 source V5는 retrieval
owner의 명시적 material evidence V6 경로로 읽고 구 consumer로 억지 전달하지 않는다.
`public_solution_source_capture.py`는 source category와 representation을 분리하여 새 외부
문항을 원래 Notion 보고서로 잘못 해석하지 않고 실제 accepted V11/common projection을 쓴다.

- `tests/unit/test_creative_item_graph_learning.py`, `tests/unit/test_creative_parallel_execution.py`
- `tests/unit/test_office_picture_use_publication.py`, `tests/unit/test_external_item_preview_projection.py`
- `docs/architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md`
- `docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md`
