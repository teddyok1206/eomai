# 문항 DB와 Graph 등록

자료 학습의 문항/설명 Graph publication은
`services/catalog_service/eom_catalog_service/material_claim_renewal.py`로 기존
coordinator claim을 유지한다. 이 범위는 새 실행 권한/queue가 아니며 만료·교체된
token을 부활시키지 않는다. task 완료는 범위 종료 후 기존 row/token fence로 기록한다.
실제 의미와 운영 반영 여부는 자료 학습 설계/운영 기록에서 확인한다.

자료 학습 child의 실제 안내문은 공용 Workflow Runner의
`PlatformRoleJobExecutor`가 `eom_workflow.material_learning_prompt`에서 가져온다.
Material owner의 private SDK나 Pack만 갱신해도 이 전역 executor의 이미 import한
안내문이 바뀌는 것은 아니다. 프롬프트 수정의 운영 반영은 실제 실행자 설치/재시작과
새 worker 입력 provenance로 확인하고, 과거 입력은 바꾸지 않는다.

등록 base의 node-type/ID 제약도 같은 실제 ROLE Runner 안의
`eom_workflow.schemas.constrained_result_schema`와 request-aware 결과 수신 검증이 소유한다.
Catalog/Material private SDK만 바꿔 이 제약까지 활성화됐다고 보고하지 않는다. 실제
Runner의 immutable import 경로·source 환경과 모델에 보낸 schema를 확인하며, historical
generic 결과 validator는 좁히지 않는다. 설계는 `REGISTERED_ITEM_BASE_REFERENCE_RECOVERY.md`다.

Native 시험지의 QUESTION은 기존 one-AI lane을 유지하면서 최대25개 ordinal 구간의
accepted base/공개 풀이를 준비한 뒤 공통 Graph를 한 번 게시할 수 있다.
task ordinal은 행정 처리 순서이지 인쇄된 문항 번호가 아니다. 복구·감사에서 상수 뺄셈으로
문항 번호를 계산하지 않는다. 원문 번호는 공식 task detail의 `printed_label`과
`material_native_printed_number`, 또는 검증된 Native source의 `metadata.item_number`를
사용하고, 순서와 문항 identity의 연결은 exact task/unit 및 source binding으로 확인한다.
`material_question_processing_window`는 terminal 행도 구간에 포함하고 EXPLANATION에서
멈춘다. processing의 checkpoint는 공개 풀이·Item/base·hash를 pin하며, 실제 publication
뒤 동일 claim의 한 transaction에서만 GRAPH_READY를 연결한다. `publish_items`는 기존
automatic publisher와 exact-member replay를 재사용한다. non-native/설명/발견 경로는
기존 순서다. 설계·후보 검증과 실제 SDK 활성화는 `NATIVE_EXAM_ITEM_INTAKE.md` 및 운영
checkpoint에서 구분한다. 새 worker schema/DB queue를 만드는 기능이 아니다.

Native의 정확한 문제/해설 번호·원본 대응과 완료 거부는
`material_native_discovery.py`가 소유하고 coordinator의 기존 binder 이름은 유지한다.
번호/출처가 맞는다는 것과 모델이 범위를 완전히 읽었다는 것은 다르다. incomplete task
선정은 원래 flag를 COMPLETE로 바꾸지 않는다. 후속 복구 설계·미활성 경계는
`docs/architecture/NATIVE_DISCOVERY_COMPLETENESS_REANALYSIS.md`와 운영 checkpoint를 따른다.
`material_discovery_reanalysis.py`는 기존 intake retry에서 정확한 incomplete 실패만
받아 producer history로 재분석 대상을 정한다. revision→run 잠금 아래 새 linked task만
생성하며 정상 발견·PREPARE는 그대로 상속한다. 새 입력이나 실행 권한을 모델이 고르지 않는다.

Native 원문 배점 판독은 `eom_hwpx_contracts.native_item_score`의 bounded XML parser와
Catalog의 `material_native_score.py`가 담당한다. 후자는 이미 source/split lineage를 확인한
정확한 question descriptor만 읽고 전후 재인가한다. ABSENT/AMBIGUOUS를 미인쇄/0점으로
간주하지 않는다. draft2/extraction2와 block content1.1은 정확한 반점 문자열을 전달하는
successor이며 기존 정수 계약의 bytes/의미는 유지한다. 원문과 모델/등록 배점의 비교 및
운영 활성화는 별도 경계다. 상세 설계와 남은 연결은
`docs/architecture/NATIVE_PRINTED_SCORE_FIDELITY.md` 및 자료 학습 운영 checkpoint를 따른다.
새 Material request3/plan41의 `native_printed_score`는 같은 Catalog source owner의
`authorize_exact_score_input`이 실제 question descriptor에서 계산한다. Role1.40/result3은
기존 isolated Support lane을 유지하며 DB에는 receipt3의 다섯 작은 값만 남긴다. 전체 결과와
그림 coverage는 기존 Artifact다. 제출/재인가/결과 읽기는 exact request/plan/receipt를
비교하고 다른 배점·구 role로의 재전송을 거절한다. Source 구현이 등록·HTTP 소비 경계와
운영 활성화를 대신하지는 않는다. `test_material_learning_execution_v3.py`가 owner 구성을 검증한다.
등록의 exact family는 `material_item_registration.py`의 Pack1.4/Native1.5와 Lineage3이며,
같은 Registry key 잠금 안에서 Native 원문 배점을 다시 확인한다. content1.1의 canonical GET은
기존 request10/new response19, 표시 읽기는 visual response2를 사용한다. 정수/미인쇄는 content1.0을
유지하고 원문 문제·해설 OTHER pointer/metadata는 그대로다. 모델·추론·권한·capacity를 바꾸지 않는
1.39→1.40 설정 갱신은 기존 `material_learning_coverage_controls.py`의 exact-score 진입점이 맡는다.
이는 source 후보이며 설치·실제 canary와 구 오류 Revision 복구는 운영 checkpoint에서 따로 확인한다.
`test_material_exact_score_read.py`와 guarded `test_material_exact_score_registration_storage.py`가
새 조회·source mismatch·등록·동시 재전송·중단 복구를 검사한다.

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

공통 Graph publication은 읽기 transaction마다 기존 `PastExamSourceResolutionCache`를
하나 생성해 공유 기출 provenance의 반복 해석만 줄인다. 현재 승인·권한·source lineage와
페이지 member 검사는 문항마다 유지하며, cache를 최종 쓰기 transaction이나 service에
보관하지 않는다. `test_knowledge_graph_publication_source_cache.py`가 출력 동등성과
읽기 횟수·철회·예산 fallback을 검증한다. source 후보와 실제 설치는 구분한다.

등록 문항의 공개 풀이는 `registered_item_solution_base.py`에서 원 accepted proposal과
모든 anchor/member를 보존하고, 기존 typed-reference schema로 표현 가능한 노드만
후속 reference index에 투영한다. 새 registered base는 같은 owner의 pointer/excerpt
검증을 통과해야 승인된다. 필수 역할 부족과 모델이 쓴 locator/excerpt 오류만 Material의
해당 task를 실패 처리하며, 출처·권한·Artifact hash 오류는 이 경계에서 숨기지 않는다.
이미 승인된 invalid base는 `material_registered_base_recovery.py`의 명시적 linked-task
scope와 Knowledge application의 복구 전용 생성으로만 후속 분석을 만든다. 기존 task pin과
accepted members는 바꾸지 않고, ordinary retry에 ACCEPTED predecessor를 허용하지 않는다.
후보 구현/활성 범위와 복구 검증은
`docs/architecture/REGISTERED_ITEM_BASE_REFERENCE_RECOVERY.md`를 확인한다. 기존 전체 설계는
`docs/architecture/CREATED_ITEM_GRAPH_AND_SOLUTION_REPORT_SUCCESSOR.md`를 확인한다.

분석의 최초 멱등 key가 FAILED를 가리켜도 `KnowledgeAnalysisApplicationService.resolve_retry`
가 명시적 predecessor chain의 같은 source/operator/preset/hash만 따라간다. cohort의
cached failed 분석도 이 owner에서 확인한 뒤 보류를 판정한다. terminal worker 실패와
process가 없는 고아 실행의 명시적 successor는 기존 `external_item_learning_recovery.py`의
별도 execution-proof route다. 살아 있는 unit/lease·commit 이력이 있으면 실행하지 않는다.
설계·검증 경계는 `CREATIVE_COHORT_RECOVERY_CONTINUITY.md`를 참고한다.

## Excel 콘텐츠 편성

표준 빈 XLSX의 가져오기는 `content_workbook_reader.py` →
`content_workbook_resolution.py` → `content_workbook_import_service.py`를 따른다.
업로드는 proposal 미리보기까지만 만들고 명시적 저장에서 기존 Edition/Form/slot owner를
사용한다. 고유번호를 원본 source namespace별로 대조하며, 모호한 번호를 제목이나 유사도로
임의 연결하지 않는다. 반복 사용은 별도 occurrence다. 원본 XLSX/해석 결과는 Artifact,
DB에는 기존 receipt의 작은 proposal/edition pointer만 보관한다. 인쇄 완료를 사용자가
명시한 파일만 기존 print owner로 같은 트랜잭션에서 기록한다. 원본 문항·Graph를 바꾸는
문항 등록 기능이 아니다. UI는 `content-planning-import.js`, 상세 설계는
`docs/architecture/EXCEL_STANDARD_WORKBOOK_IMPORT.md`를 본다. 소스 구현과 운영 활성화는 구분한다.

양식 행 수와 실제 GROUP/FORM 수는 다르다. `content_workbook_layout.require_workbook_layout`가
실제 layout과 같은 bounded iterator로 기존 Edition 10,000 section 한도를 준비·조회·저장에
적용한다. 초과 proposal을 준비 완료로 표시하지 않고 `CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE`로
거절하며, 보관된 Artifact/receipt는 수정하지 않는다. V1 `can_commit` 의미도 유지한다.

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

유사도 결과의 단원도 동일한 원본 Q/R을 쓴다. `item_db_similarity_candidates`가
`QueryAdapter.original_item_units`를 통해 Catalog `read_creative_registration_sources`의
최대64개 exact Item/manifest batch를 읽는다. 단건 상세도 같은 source resolver를 사용한다.
Graph 단원이나 최신 source로 대체하지 않으며, 원본이 없으면 빈 표시로 남긴다.
완료 ranking/벡터/점수는 바꾸지 않는다.

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

Native 시험지 입력의 metadata2는 `material_native_item_read.py`가 기존 material/Item
revision과 6개 component, committed binding/intake, 원본·권리·XLSX Artifact의 lifecycle을
확인해 읽는다. 실제 읽는 사람의 `ITEM_READ`·`CONTENT_INTAKE_READ` 권한을 사용하며
원본 업로더로 가장하지 않는다. DB 목록은 `MaterialNativeItemDbEntryView` successor,
원본 단원은 XLSX의 raw `original_unit`이고 Notion 행이나 Graph 단원으로 위장하지 않는다.
문항·해설 HWPX 다운로드는 canonical `OTHER:0/1` pointer를 그대로 연다. 이 두 파일을
기존 V1 native 조립 입력으로 이름만 바꾸어 전달하지 않으며 pair 합본은 별도 후속 경계다.
구현 존재와 실제 배포·450문항 처리 완료는 운영 evidence로 구분한다.

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

prepared checkpoint도 없는 PREPARE 실패의 profile 교체는 일반 retry가 아니다.
`packages/catalog_contracts/eom_catalog_contracts/material_preparation_recovery.py`의 닫힌
계약과 `services/catalog_service/eom_catalog_service/material_preparation_recovery.py`를
확인한다. 원래 actor/source/rights·입력 pin을 다시 검증하고, 고정 service/child drain은
`material_preparation_drain.py`가 관측한다. 부분 EducationalDocument 등록뿐 아니라 고정
document Artifact job이 먼저 생긴 경우도 거절한다. 같은 material revision에 새 입력을
가진 predecessor-linked PREPARE attempt를 만들고 기존 input·FAILED 이벤트를 보존한다.
`material_learning_store.material_preparation_task`가 이 task를 원래 coordinator에 연결한다.
동시성·중단·재전송 검증은 `test_material_learning_recovery_storage.py`와 native 등록 DB
suite를 함께 본다. 원문 JPEG의 CMYK→RGBA PNG 정규화는 기존 image adapter의 책임이며,
unsupported EMF를 성공한 raster로 간주하지 않는다. 실제 설치·복구 상태는
`docs/operations/NATIVE_EXAM_ITEM_INTAKE_CHECKPOINT.md`에서 따로 확인한다.

모든 native discovery가 완료됐지만 번호 표기 최종화에서 실패한 경우는 worker retry가
아니다. `material_discovery_finalization_recovery.py`의 닫힌 명령/application은 기존 native2
prepared와 완료 결과·역할·권리·hash를 검증하고, 같은 pointer를 상속한 linked run만 만든다.
새 모델·문항·파일을 복제하지 않는다. 번호의 순수 reader는 그대로이며
`material_native_solution_number`만 명시적인 정답 머리말을 읽는다. 문항/metadata reader를
느슨하게 바꾸지 않는다. 설계와 실제 설치 상태는 위 native 문서 두 개에서 구분한다.

`material_task_history.py`는 최대32단계 predecessor를 하나의 indexed recursive query로
읽는다. 서로 다른 자료·업로더·단위 또는 변경된 input/output은 이어받지 않는다. 전역 unique
child owner는 원래 task에 남긴다. `material_task_source_read.py`는 명시적인 위치 조회에서만
source bytes를 읽고, routine progress는 metadata만 조회한다. 추출 입력이 없는 구조 예외는
coordinator의 같은 `read_material_discovery_plan`을 재사용해 원래 페이지/번호를 보여준다.

편집 가능한 시험지·해설지 원문 분할은 `docs/architecture/NATIVE_EXAM_ITEM_INTAKE.md`와
`material_native_preparation.py`의 공식 준비 경로를 따른다. API의
`POST /material-learning/native-exams`는 기존 원본 업로드 receipt 두 개와 actor-free
metadata JSON 한 줄, 최대8MiB XLSX를 받는다. 실제 actor·byte length·SHA는 API가 확정하고,
동일 Catalog socket의 `PREPARE_NATIVE_MATERIAL_EXAM`으로 전송한다. XLSX/native parsing과
Artifact commit은 Catalog/격리 parser의 책임이며 API에서 수행하지 않는다. 이 작업만300초
대기하고 일반 RPC timeout은 늘리지 않는다. 명시적 create/2.0의 native bundle을 원래
`parse_material_learning_create`로 해석하며 V1 입력을 새 계약으로 재해석하지 않는다.
Catalog UID는 transient unit을 만들지 않는다. `native_exam_preparer.py`가 고정된
`eom-native-exam-preparer@nativeexam_<32hex>`만 시작하고, 별도 eom-image UID가 단일
job bind mount의 0640 입력을 읽어 0640 결과 ZIP을 쓴다. Catalog 부모·NAS·DB socket과
인증 경로는 worker에서 차단한다. 기존 Builder 설치본·request/result 계약은 재사용하며
불확실한 실행의 workspace는 삭제하지 않는다. 이 경계는
`tests/unit/test_native_exam_systemd_preparer.py`에서 검증한다.
관련 입출력 검증은 `tests/api/test_material_native_upload_routes.py`와
`test_material_native_upload_client.py`를 본다. 구현 후보의 존재는 운영 활성화 증거가 아니다.

원문 파일이 연결된 외부 문항은 Notion source ID를 만들지 않는다.
`material_native_item_read.py`가 실제 권한·Item revision/manifest·등록 binding·원문 intake를
해결하고, API `GET /item-db/registrations/{revision}/native-source`와 `native-document`가
같은 private Catalog operation을 사용한다. 다운로드는 MAIN/SOLUTIONS 역할만 받고
편집 가능한 개별 HWPX의 실제 SHA/길이를 스트림 종료까지 검사한다. arbitrary Artifact
경로나 model이 만든 파일 identity를 입력받지 않는다. 회귀 검증은
`tests/api/test_material_native_item_read.py`다.

API `GET /item-db/materials`와 DB 외부 분류는 current shared Graph membership을 확인해
작은 등록 metadata를 읽는다. Notion 행이나 임의 고유번호를 만들지 않는다. Map V2는 같은
Graph에서 외부 layer를 표시하며 V1 bytes/소비를 보존한다. 새 설명 source V5는 retrieval
owner의 명시적 material evidence V6 경로로 읽고 구 consumer로 억지 전달하지 않는다.
`public_solution_source_capture.py`는 source category와 representation을 분리하여 새 외부
문항을 원래 Notion 보고서로 잘못 해석하지 않고 실제 accepted V11/common projection을 쓴다.

한글 문제·해설과 문항 정보 XLSX의 신규 입력 후보는
`docs/architecture/NATIVE_EXAM_ITEM_INTAKE.md`를 먼저 읽는다. 기존 자료 학습 화면의
선택 엑셀은 `POST /material-learning/native-exams`의 제한된 JSON 한 줄 + XLSX stream을
공식 API로 전달하고, 실제 actor·원본 receipt·권한·파일 hash 검증은 API/Catalog가 소유한다.
엑셀 없이 올리면 기존 일반 학습 경로이며, 문항별 편집 원본을 보존하는 현재
Native 입력은 문제·해설 HWP/HWPX와 실제 XLSX가 모두 필요하다. 엑셀 없는 Native pair는
아직 후속 지원 범위다. 빈 고유번호를 허용하는 것과 XLSX 자체가 없는 것은 다르다.
`material_native_preparation.py`는 보호된 CPU 도구로 원본을 문항별 native HWPX로 준비하고
`material_native_publication.py`가 기존 Artifact owner에 primary HWPX와 단일 공유 Excel을
등록한 뒤 원래 intake.create에 V2 bundle pointer만 넘긴다. worker가 NAS에 쓰거나 XLSX의
빈 고유번호를 새로 만들지 않는다. 원본·문항 번호·고정 producer/plan이 native 문항 identity를
결정하며 Excel hash/고유번호의 추가만으로 native 파일을 재등록하지 않는다. V1 intake는
그대로 유지하고 `material_intake_read.py`와 명시적 checkpoint-chain 검증이 V1/V2를 구분한다.
이 경로의 source/test 존재는 운영 활성화나 전체 원본의 native 보존 승인 증거가 아니다.
DB의 외부 목록은 `material-item-db-entry/1.0`과 native `2.0`을 명시적으로 구분한다.
원본 Excel의 소속 단원·분류·문항명·비어 있을 수 있는 고유번호를 표시하며, 등록 문항의
`/source` 조회도 같은 native metadata2를 읽는다. 원본 문항/해설 HWPX 다운로드는
`/registrations/{revision}/native-document`에 고정 manifest hash와 MAIN/SOLUTIONS 역할만
넘긴다. 임의 Artifact/path를 받지 않고 기존 API/Catalog owner가 현재 권한을 확인한다.
Web은 bytes의 media/length/SHA를 검증해 전달하며, 이 원본 다운로드와 새 HWPX 렌더링·합본은
다른 사용 경로다. GUI/stream 회귀는 `tests/web_gui/test_material_native_items.py`와 기존
`item_db_browser_checks.mjs`를 본다.

Native 그림 보완의 [prepared3 계약](../../packages/catalog_contracts/eom_catalog_contracts/material_native_visual_preparation.py)은
exact base prepared2와 원본·PDF·페이지 포인터를 보존하며 Work의 office catalog만 검증한
V1 후속 revision으로 바꾼다. [그림 범위 계산](../../packages/catalog_contracts/eom_catalog_contracts/material_native_visual_selection.py)은
문항의 실제 BODY picture use를 whole pixel·view SHA/크기로 유일하게 대응시키며 ZIP의
전체 binary 목록이나 같은 binary의 모든 use를 허용하지 않는다. 안내 suffix는 권한이
아니며 SourceAuthorizer는 실제 native bundle/checkpoint와 base 페이지를 재검증한다.
같은 HWPX의 view 후보가 여러 개일 때만 기존 native subtree SHA 보조 index로 유일성을
증명한다. 원본 HWP와 변환 HWPX의 native bytes를 같은 것으로 간주하지 않는다.
그림 decoder의 color-mode map은 일반/기존 회색조/BLACK_WHITE를 구분하며,
[color-mode owner](../../services/image_provider/eom_image_provider/office_picture_color_mode.py)는
흑백 사용본에만 정수 MONO 연산을 적용하고 원 PNG/alpha를 보존한다.
준비 단계의 지원불가 그림·모호한 use 두 코드는 Coordinator에서 기존 source-error로
번역하고 Processing의 해당 run/task FAILED 전이로 격리한다. hash/권한/profile/인프라
오류를 source 품질 오류로 숨기지 않는다.
[Native visual owner](../../services/catalog_service/eom_catalog_service/material_native_visual_preparation.py)는
등록 시에도 실제 native 문항 파일로 범위를 독립 재계산한다. 공개 worker wire는 그대로다.
visual recovery는 accepted 결과·Item·분석·Graph pin이 없는 실패 QUESTION을 가진 terminal
run에 한정하며 성공 task의 기존 pins를 상속한다. 설계는
[문항별 그림 범위와 geometry 보완](../architecture/NATIVE_EXAM_ITEM_INTAKE.md#문항별-원그림-범위와-정확한-geometry-보완),
읽기·입력·권한 회귀는 `test_material_native_visual_prepared_read.py`,
`test_material_native_visual_work.py`, `test_material_native_visual_authorization.py`를 본다.
이 문맥은 코드 탐색용이며 운영 활성화나 실제 그림 검수의 증거가 아니다.

후속 Native visual coverage는 별도 Root ROLE1.39/result2 envelope에서만 받는다.
[완료 결과 reader](../../services/catalog_service/eom_catalog_service/material_task_results.py)는
저장된 실제 job request와 그 실행 계획을 함께 읽어 범위·coverage를
검사하며, 역사 ROLE1.37/result1을 새 계약으로 재해석하지 않는다. 작은 receipt/lineage는
[receipt](../../packages/catalog_contracts/eom_catalog_contracts/material_learning_role_receipt.py)와
[lineage](../../packages/catalog_contracts/eom_catalog_contracts/material_item_lineage.py)의 명시적
1/2 parser로 읽고, 전체 Root 결과 Artifact hash가 coverage를 묶는다. lineage의
`result_sha256`는 이전처럼 내부 learning result의 hash다. `material_item_registration.py`는
Root1의 generic/native Pack1.0/1.1과 Root2의 Pack1.2/1.3을 정확히 구분한다. metadata1/2와
native binding1은 그대로이며 새 lineage2 포인터는 새 결과에만 생성한다.
[순수 coverage validator](../../packages/catalog_contracts/eom_catalog_contracts/material_native_visual_coverage.py)는
선언·블록·원본 범위의 closure를 검사하며 과학적 의미의 동일성을 보증하지 않는다.
후보 구현과 실제 Runner/Pack/서비스 활성화는 설계·릴리스 기록에서 별도로 확인한다.

source `1b30a580`의 검토된 그림 한 개 보완은
[correction owner](../../services/catalog_service/eom_catalog_service/material_native_visual_correction.py)의
prepare/import_reviewed/validate_applied가 원본·권한·실제 current와 image-only 변경을 확인한다.
[후속 분석 owner](../../services/catalog_service/eom_catalog_service/material_native_visual_correction_learning.py)는
같은 receipt의 새 base/공개 풀이·공통 Graph를 연결한다. old task/분석 pin을 덮지 않으며
실패한 분석을 새 key로 자동 우회하지 않는다. reviewed import의 동일 key staging은 기존
`item_content_import.py`가 transaction lock으로 직렬화한다. 기존 approved-Item 분석의
JSON 읽기를 PNG 픽셀 검수라고 해석하지 않는다. 실제 활성화는 operations checkpoint를 본다.

- `tests/unit/test_creative_item_graph_learning.py`, `tests/unit/test_creative_parallel_execution.py`
- `tests/unit/test_office_picture_use_publication.py`, `tests/unit/test_external_item_preview_projection.py`
- `docs/architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md`
- `docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md`
