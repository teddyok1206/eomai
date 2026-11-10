# 문항 DB와 Graph 등록

자료 학습의 문항/설명 Graph publication은
`services/catalog_service/eom_catalog_service/material_claim_renewal.py`로 기존
coordinator claim을 유지한다. 이 범위는 새 실행 권한/queue가 아니며 만료·교체된
token을 부활시키지 않는다. task 완료는 범위 종료 후 기존 row/token fence로 기록한다.
실제 의미와 운영 반영 여부는 자료 학습 설계/운영 기록에서 확인한다.

## 출처와 상태를 분리

사용자 분류는 기출·창작·AI이며 교과서는 별도 근거 출처다. 창작은 가져온 기존 제작 문항,
AI는 EOM에서 생성한 문항이다. 분류에 승인 여부를 섞지 않는다. 화면의 고유번호와
논리 Item ID·Item Revision ID·Artifact ID·hash도 별개다. 내부 ID를 사용자 기본 화면에
되살리는 방식으로 조회 기능을 붙이지 않는다.

외부 원본의 메타데이터와 Registry에 등록된 Item이 별도 조회 경로를 가질 수 있으나,
등록됐다는 이유로 원본 메타데이터/필터가 사라져서는 안 된다. 원본 파일·등록 문항·
풀이보고서는 lineage를 통해 연결한다. Graph는 교과서·기출·창작·AI를 공통 개념/관계와
출처 포인터로 잇는다. layer 구분은 분리된 독립 검색 DB를 만드는 근거가 아니다.

DB 문항 정보의 소속 단원은 원본 Q/R만 표시한다. Graph 후보에서 열어도
`item-db/registrations/{revision_id}/source`가 exact Item manifest와 등록 당시 source
revision을 Catalog에서 조회한다. Graph 자동 연결 단원으로 빈 원본 값을 대신하지 않는다.
원본 조회 권한·오류·정보 없음은 구분하며, Graph/임베딩 자체의 연결은 그대로 유지한다.

## Map

`데이터 → Map`은 기존 published Graph의 읽기 전용 인접 탐색이다.
`knowledge_map_read.py`가 snapshot/hash와 노드·관계·출처 메타데이터를 bounded SQL로 읽고,
`knowledge-map.js`가 표시한다. 기존 학습 범위·품질 보고서는 `knowledge-quality` view에
보존한다. AI/창작은 origin profile 또는 정확한 과거 등록 Workflow family로 구분하며,
worker RAG policy나 evidence receipt를 우회하지 않는다. 문항 열기는 동일 Item revision/hash의
새로운 DB 읽기다. 상세 설계: `docs/architecture/KNOWLEDGE_MAP_READ_DESIGN.md`.

Map의 선택적 `layer` query는 기존 Map V2/출처 enum을 그대로 쓰고 서버에서 seed 제한
전에 source membership과 교차한다. `knowledge_map_layers.py`의 작은 불변 rule tuple이
표시와 SQL 분류를 함께 소유한다. 처음 열 때 다섯 출처를 조금씩 선택하며, Layer 변경은
같은 snapshot pin을 유지한다. 화면의 현재 노드만 숨기는 필터가 아니다. 선택한 점의
근거도 같은 Layer로 제한하고, 공통 개념은 복제하지 않고 여러 색으로 표시한다.

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

분석의 최초 멱등 key가 FAILED를 가리켜도 `KnowledgeAnalysisApplicationService.resolve_retry`
가 명시적 predecessor chain의 같은 source/operator/preset/hash만 따라간다. cohort의
cached failed 분석도 이 owner에서 확인한 뒤 보류를 판정한다. terminal worker 실패와
process가 없는 고아 실행의 명시적 successor는 기존 `external_item_learning_recovery.py`의
별도 execution-proof route다. 살아 있는 unit/lease·commit 이력이 있으면 실행하지 않는다.
설계·검증 경계는 `CREATIVE_COHORT_RECOVERY_CONTINUITY.md`를 참고한다.

## Excel 콘텐츠 편성

`docs/architecture/EXCEL_CONTENT_PLACEMENT_DESIGN.md`가 승인된 설계다. 기존 Deliverable과
Form, curated Assembly를 확장하며 별도 문항/파일 registry를 만들지 않는다.
`content_planning.py`/`curated_document_slots.py`가 판·구간·빈 자리·반복 occurrence 계약,
`content_planning_layout.py`가 순수 이동/복사/번호·인쇄 범위 계산을 소유한다.
`content_planning_models.py`, `content_print_models.py`, `curated_document_slot_models.py`가
indexed 소속·읽기·불변 이력 저장을 담당한다. migration `20261109_0075`/`0076`의 실제 적용과
후속 복구·복사·인쇄 연결 기능의 설치 여부는 분리한다. source 존재나 임시 DB PASS를
운영 설치로 해석하지 않는다. 진행·검증 경계는
`docs/operations/EXCEL_CONTENT_PLACEMENT_IMPLEMENTATION_2026-11-09.md`를 확인한다.

새 V3 draft/V2 manifest는 placement ID가 고유하며 Item 반복·빈칸·200 초과를 허용한다.
구 V1/V2 draft와 V1 manifest 의미를 바꾸지 않는다. 개인 조립과 콘텐츠 Form 조립의 권한은
별도이며 `content_delivery_service.py`가 선택 scope를 기존 curated 출력에 연결한다.
`content_usage_projection.py`의 current/print membership을 이력·summary·연도별 사용 필터가
공유한다. `creative_source_registration.py`의 공식 lineage만 원본과 등록 Item을 연결하며
숫자/제목의 유사함으로 합치지 않는다. `content_prior_usage_read.py`는 연도 없는 옛 ledger를
별도 읽는다. 필터는 pagination 전에 적용하며 이력 조회로 새 인쇄 사실을 만들지 않는다.

Web의 `content-planning-location.js`는 exact 콘텐츠/판/revision/구간 URL만 검증하고,
`content-planning-pending.js`는 제출된 요청의 owner별 key/body를 복구한다. 브라우저 상태는
권한이나 정본이 아니며 기존 Catalog 읽기/멱등 저장에서 재검증한다. `content-planning-copy.js`는
저장본의 선택 범위를 작은 provenance 포함 슬롯으로 읽어 기존 SAVE_SECTIONS에 전달한다.
현재 배포 경계와 설계는 `EXCEL_BROWSER_RECOVERY_BOUNDARY.md`,
`EXCEL_SELECTED_COPY_BOUNDARY.md` 및 위 운영 checkpoint를 확인한다.

Excel로 문항을 고르는 동안 `item-db-assembly.js`는 기존 `createPlanningDraft`의
ordered occurrence를 임시 선택 목록으로 재사용한다. 개인 조립의 200개·고유 문항 계약을
확장하거나 개인 초안을 덮어쓰지 않는다. 100행씩 표시하고 반복 포함 전체를 한 번에
전달한다. `EXCEL_DB_SELECTION_BOUNDARY.md`와 실제 DB browser 회귀를 함께 확인한다.
DB에서 먼저 선택한 문항은 `content-planning-destination.js`의 읽기 전용 선택창에서
콘텐츠·판·회차·삽입 위치를 고른다. `content-planning.js`가 정확한 저장본의 슬롯을 읽고
임시 초안을 검증한 뒤 현재 초안에 반영한다. 취소·조회 실패 때 기존 초안은 보존하며
저장은 기존 SAVE_SECTIONS만 사용한다. 사용 이력의 편성 열기는 해당 revision뿐 아니라
section/placement/position을 확인해 그 문항이 있는 페이지로 이동한다.

보관/복원은 `content_lifecycle_service.py`가 기존 Product/Edition 상태와 이벤트를 사용한다.
정본 revision이나 사용·인쇄 이력을 삭제하지 않는다. 편집은 Product 공유 잠금 이후 Edition
잠금, 보관은 Product 배타 잠금으로 순서를 통일한다. `EXCEL_LIFECYCLE_BOUNDARY.md`와
`test_content_lifecycle.py`의 실제 동시성/멱등 검사를 따른다.

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

DB의 `item-db-assembly.js`는 간편 출력·Excel용 임시 선택만 소유한다. 한 번의 출력 클릭이
기존 draft V2 저장과 HWPX 제작으로 이어지며, 같은 선택은 receipt와 멱등 key를 재사용한다.
개인 저장본·다운로드·목록 삭제는 Excel의 `curated-output-library.js`에서 관리한다.
정확한 저장본을 기존 `placeSelections`로 가져오되 명시적 배치 저장 전에는 사용 이력을
만들지 않는다. 간편 출력도 인쇄 사실이 아니다. 기존 모의고사 자동 계획 UI는 퇴역했지만
application/API와 역사 출력은 남아 있다. 다문항 AI 생성은 별도 후속 범위다.
설계/배포 구분은 `docs/architecture/DB_QUICK_OUTPUT_EXCEL_CONSOLIDATION.md`를 확인한다.

title은 조립의 작은 불변 metadata다. 목록 삭제는 소유자의 노출만 제거하며 revision/placement,
진행 중 제작과 HWPX 참조를 물리 삭제하지 않는다. 재전송은 exact revision/hash와 동일 key다.
`packages/catalog_contracts/eom_catalog_contracts/curated_document_assembly_library.py`의
closed RPC, `curated_document_assembly_service.py`의 저장·목록 구현과 migration73을 확인한다.
이전 V1 계약은 바꾸지 않으며 교체 대상은 가변 행 번호가 아니라 원 pointer다.

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

자료 문항 공개 풀이는 `KnowledgeAnalysisApplicationService`의 내부
`create_material_solution_with_pinned_preset`이 전용 logical key와 불변 preset을 대조한다.
공개 solution command의 원래 literal이나 RPC를 확장한 경로가 아니다. 실제 전용 preset을
쓰는 `test_material_item_registration_storage.py`의 V11/common-text 회귀를 함께 확인한다.

`MaterialLearningIntakeService.control`은 기존 run의 pause/resume를 actual actor와
updated_at CAS로 처리한다. BFF/GUI 버튼은 같은 control을 호출한다. 자료 coordinator는
별도 모델 Runner를 만들지 않으며 원래 global Workflow Runner가 자식 command를 실행한다.
PDF command port는 기존 sandbox, 한글 conversion port는 기존 Catalog-manager workspace를
사용한다. 각 adapter의 실제 설치 증거와 후보 상태는 operations checkpoint에서 구분한다.

`material_learning_recovery.py`의 retry는 원래 FAILED run/task를 변경하지 않고 같은 자료
revision의 successor run과 작은 checkpoint 참조를 만든다. 완료된 준비/추출/등록·accepted
base는 재사용하며 새 worker가 필요한 실패 단위만 기존 명령으로 다시 제출한다. 부모
revision→run 잠금과 deterministic successor ID로 동시 재전송을 처리한다. 살아 있는
Workflow/분석·미정리 worker lease가 있으면 공식 reconcile 전에는 새 시도를 만들지 않는다.
원본/구조 EXCEPTION은 그대로 보류하고, 준비 전의 원본 문제를 무한 재실행하지 않는다.

`material_task_history.py`는 최대32단계 predecessor를 하나의 indexed recursive query로
읽는다. 서로 다른 자료·업로더·단위 또는 변경된 input/output은 이어받지 않는다. 전역 unique
child owner는 원래 task에 남긴다. `material_task_source_read.py`는 명시적인 위치 조회에서만
source bytes를 읽고, routine progress는 metadata만 조회한다. 추출 입력이 없는 구조 예외는
coordinator의 같은 `read_material_discovery_plan`을 재사용해 원래 페이지/번호를 보여준다.

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
