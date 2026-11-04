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

## 검증과 근거

- `tests/unit/test_creative_item_graph_learning.py`, `tests/unit/test_creative_parallel_execution.py`
- `tests/unit/test_office_picture_use_publication.py`, `tests/unit/test_external_item_preview_projection.py`
- `docs/architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md`
- `docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md`
