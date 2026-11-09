# 문서 미리보기와 출력과 자료 검토

Excel 편성 successor는 `curated_occurrences.py`의 build-input2/render4/native-item2를
기존 Catalog→Manager→Builder 경로에 명시적으로 dispatch한다. 구 계약의 200개·고유 target
의미는 유지하고 새 occurrence만 반복 문항·200개 초과를 허용한다. 범위 준비는
`content_delivery_service.py`, 권한은 Catalog가 소유한다. 합본 acceptance는 header의
refList를 매 문항 복사하지 않고 작은 옵션만 비교한다. 원본 XML 한도는 유지하며 생성한
합본만 기존 총 출력 예산 내에서 허용한다. 운영 활성화 여부는 Excel 구현 체크포인트를 본다.

완성 합본의 committed artifact 해석은 Catalog Artifact adapter
`curated_output_publication.read_curated_committed_output`을 Manager 복구와
`content_print_output.resolve_content_print_output`이 공유한다. Catalog가 Manager private
table/API를 직접 읽지 않는다. 선택적 인쇄 파일 연결은 exact scope/revision/출력 hash를
검증하며 파일 제작만으로 인쇄 사실을 만들지 않는다. `EXCEL_PRINT_OUTPUT_LINK.md`와
`test_content_print_output.py`를 함께 확인한다.

Manager의 PostgreSQL 권한 정본은 `eom_hwpx_manager/runtime_privileges.py` 하나이며,
`scripts/hwpx/bootstrap_manager_runtime_role.py`와 실행 전 readiness가 같은 목록을 쓴다.
Excel 출력은 실행·중단 복구 모두 Catalog의 `read_content_delivery`로 exact scope,
Edition/Form/slot snapshot과 원본 batch lifecycle을 다시 읽으므로 이 읽기 closure의
SELECT도 필요하다. 콘텐츠 편집·인쇄 기록 쓰기나 credential 읽기 권한은 부여하지 않는다.
권한이 빠지면 RUNNING claim 뒤 SQL42501로 renderer 진입 전 복구가 반복될 수 있다.
`test_content_planning_runtime_role.py`는 임시 DB의 실제 Manager table matrix로
scope 재검증·FIFO·동일 build 복구를 검사한다. API/DB owner 권한의 PASS로 대체하지 않는다.

## 세 경로를 혼동하지 않기

Item Preview는 정본 content/image pointer의 읽기 투영이다. 원본 문항 파일의 PDF 미리보기는
HWP/HWPX를 변환한 별도 결과다. HWPX 제작은 Manager가 검증한 입력을 Builder가
출판 package로 조립하는 delivery다. 미리보기 성공이 HWPX 내부 이미지 포함을 증명하지 않는다.

그림 누락은 선택한 revision/ordinal → 실제 PNG Artifact → Manager handoff → Builder의
binary/relationship → authenticated download bytes 순으로 본다. PNG가 package 내부 member를
가리키는지와 external filesystem 경로가 남지 않는지를 따로 검사한다. ZIP 정상과 실제 한글
화면 검수도 구분한다. 현재 소스를 과거 실패 build에 덮어 성공으로 바꾸지 않는다.

단일 그림은 빈 두 번째 칸과 `(가)/(나)` 없이 넣는다. 두 그림은 서로 다른 ordered PNG와
편집 가능한 panel label이다. 표-only와 그림/표 혼합, authored order를 임의로 PNG 여러 개나
고정 1행 2열로 바꾸지 않는다. Preview 아래 내부 그림 지시문을 학생용 내용처럼 붙이지 않는다.

## 자료 검토

원본 Office PDF의 현재/역사적 변환기는 `office_conversion_profiles.py`의 닫힌 profile로
구분한다. legacy bundle/unit/key를 덮어쓰지 않고, 현재 DB PDF와 새 Office 검토 입력은
수식 호환·선택지 칸 보정의 후속 profile을 선택한다. 수식 보존 이전 profile도 남는다.
`ConvTable`의 보정은 작은 셀의 단독①–⑤에 한정해 과도한 문단 여백만 줄이며,
일반 표/내용·공유 style은 바꾸지 않는다. `external_item_preview_projection.py`의 새 파생물 key는
source revision/edition/profile/bundle SHA를 포함하며 같은 key의 준비는 기존 publication
lock으로 직렬화한다. 재조회는 변환하지 않는다. `office_pdf_quality.py`는 알려진 Math
오류 표시만 bounded 검사하며 모든 수학적 정확성이나 한글 배치 일치를 보장하지 않는다.
새 변환기의 고정 unit은 보호된 설치 source에 pin하고 공용 API/기존 학습 runtime을
교체하지 않는 경계를 우선한다. 설계와 활성화 범위는
`docs/architecture/OFFICE_PDF_EQUATION_FIDELITY.md`와 설치 기록을 확인한다.

PDF·HWP·HWPX 입력을 검증하고, Office 입력에는 앞단 변환을 붙여 검토용 PDF/페이지를
사용한다. 문제지·해설지는 각 역할과 source/page identity를 유지한다. 원본 PDF 자체는
고치지 않는다. 위치 표시와 annotation/comment-panel PDF는 별도 파생 결과다. HWPX 교정은
선택된 검토사항을 원본과 연결해 새 출력으로 만들며 수정 글자는 빨간색으로 구분한다.

검토 근거와 교과서 검증은 `document_review_evidence_service.py`,
`review_textbook_evidence_service.py`와 Orchestrator receipt validation을 함께 본다.
단순 COMPLETE 플래그가 모든 과학적 판단이나 실제 출판 품질의 증명은 아니다.
worker 결과 스키마 검증 실패와 변환 결과 없음, 페이지 투영 실패, 주석 저장 실패는 다른 경계다.

## DB 조립의 native 출력

`curated_document_assembly_service.py`는 혼합 원본·등록 문항의 ordered input manifest를
저장한다. 입력 저장을 HWPX 제작 완료로 해석하지 않는다. `curated_renderer.py`의 V1은
HWPX 전용이고 V2는 고정된 HWP 변환 bundle을 명시적으로 pin한다. native merger는 문서별
resource·binary·object ID를 먼저 map으로 할당한 뒤 역매핑으로 XML과 media를 확인한다.

HWP 변환은 `native_hwp_converter.py`가 보호된 설치 JAR/Java identity와 소스/후보 hash를
검사하고, `native_hwp_preservation.py`가 문단·표·수식·binary·도형 evidence를 대조한다.
`hwp_conversion_package.py`는 고정 writer의 빈 style name·동일 크기 0 축약·ZIP을 정규화한다.
`native_intent_box.py`는 제목/본문만 있는 알려진 inline 출제의도 묶음에 한해 편집 가능한
native cell로 바꾸고 원래 크기/anchor와 바깥 XML을 역검증한다. 그림·수식이 있는 그룹이나
다른 글상자는 바꾸지 않는다. 캐시만 제거했던 첫 시도는 Hancom에서 실패했으므로 활성
방식으로 재사용하지 않는다. 확정 방식과 설치/사용자 확인은 아래 운영 체크포인트를 본다.
페이지 PNG 대체나 원본 덮어쓰기는 하지 않는다. 이 코드·설치본 검증을 운영 GUI 활성화로
간주하지 말고 아래 현재 체크포인트와 실제 release를 대조한다.

가변 canonical Item/1.0은 Manager `native_item_projection.py` → local
`native-item-render-request/1.0` → Builder `native_item_renderer.py`로 투영한다. 원본 content와
effective visual content hash를 분리해 pin하고 그림 use와 binary 파일을 구분한다.
계약의 `native_item_format.py`/`native_item_semantics.py`는 저장소나 DB에 접근하지 않는
순서·표·수식·uncropped picture 검증이다. content-team/2.0·3.0과 구 고정 예제 profile은
그대로 남는다. 저장된 배치의 영속 delivery와 API/GUI 연결 여부는 별도로 확인한다.

local `curated-hwpx-render-request/3.0`은 원본 문서·canonical Item/1.0·content-team/2.0·3.0을
한 순서로 섞는다. `curated_materialization.py`는 exact source/effective/recovery pointer를
읽고 기존 공개 `ContentTeamHwpxService.resolve_members`의 batch 경계를 재사용한다.
각 그림 포인터를 확인한 뒤 같은 SHA의 local PNG만 공유한다. 원본 content를 예전
고정형 출력으로 재해석하거나 rendered segment를 개별 NAS Artifact로 만들지 않는다.

`curated_mixed_renderer.py`는 handoff/runtime과 generic template를 합본에서 한 번 준비하고
기존 개별 출력기와 native merger를 사용한다. 새 profile의 `curated_editorial_layout.py`만
고정 template의 중복 번호·중첩 표 폭·내용에 비해 낮은 cell 높이를 조정하고 line cache를
제거한다. 텍스트·수식·그림 viewport는 전후 비교하며 원본 HWP/HWPX와 기존 released
single/exam 경로의 geometry는 바꾸지 않는다. native table 수에는 layout table도 포함된다.

`curated_application_service.py`는 별도의 `hwpx_curated_builds`에서 actor/key 멱등 요청,
partial FIFO claim, 같은 build의 advisory lock과 중단 복구를 소유한다. input plan에는
`curated-hwpx-build-input/1.0`의 source/effective content·handoff·converter pointer만 저장한다.
예정 Job/Artifact/revision identity를 실행 전에 pin하며 완료 조회는 render를 호출하지 않는다.
실제 파일 실행·commit·다운로드 adapter와 API/GUI wiring은 이 queue 코드 자체와 구분한다.

기존 단일 문항의 startup 복구도 `application_service.py`와 각 renderer port가 소유한다.
`renderer_recovery.py`는 같은 indexed Job key와 task/source revision/hash, 승인 output pointer를
대조한다. fixed unit이 살아 있거나 불명확하면 기다리고 새 render는 하지 않는다. 원래
SUCCEEDED Job의 receipt만 연결하며, 미완료 orphan은 상태기계로 중단 기록을 남긴다.
`recover_interrupted_item_result`와 whole-exam의 복구 port를 혼동하지 않는다.

Catalog `authorize_delivery_build`와 `read_for_delivery`는 각각 기존 HWPX 제작/조회 권한을
재확인한다. 선택 시에는 current Graph, 저장된 조립의 delivery에는 그 exact published Graph를
사용한다. 원본 metadata는 batch join으로 확인하고 status poll에서 모든 파일을 다시 hash하지
않는다. bytes와 actual visual proof는 명시적인 stage·검증 경계에서 다시 대조해야 한다.

이 Python use case의 존재는 private Catalog RPC 활성화 증거가 아니다. API 쪽 연결은
기존 `catalog_application_client.py`/Catalog `application_server.py` 경계를 유지한다.
API의 입력 pinning 때문에 NAS 접근·native 변환 dependency를 API에 추가하지 않는다.
`curated_delivery_inputs.py`는 Catalog의 metadata-only pin, `curated_output_acceptance.py`는
Manager의 독립 package/원문 대조다. `curated_service.py`는 예정 Job identity로 local
result와 기존 Catalog Artifact commit intent를 복구하며 새 출판 framework를 만들지 않는다.
API는 `curated_delivery_gateway.py`를 통해 Catalog authorization/pin RPC만 사용한다.
`curated_composition.py`는 Runner에서만 파일 실행·commit adapter를 구성한다.
`curated_document_assemblies.py`와 Web `item-db-delivery.js`가 저장된 순서에서 제작·조회·
다운로드를 연결한다. download/2.0만 256MiB를 허용하며 구 1.0의 64MiB는 그대로다.
코드 존재·fixture PASS와 새 설치본/운영 활성화를 구분하고 체크포인트의 남은 gate를 확인한다.
DB의 선택 담기는 예전 `hwpx_exam_eligible`로 막지 않는다. 그 flag는 기존 production/exam
계약의 의미이고, 새 curated 조립의 입력 저장과 실제 제작 admission은 각 Catalog/Manager
owner가 검증한다. 예전 시험지 flag=false인 canonical 기출도 선택 가능해야 한다.
등록 문항 상세의 담기도 같은 규칙이다. 다만 정본 등록/사람 승인과 accepted analysis/
Graph source membership은 별개다. Graph 후보가 없을 때 후보를 꾸며내지 말고 입력의
선행조건과 출력기 지원 범위를 구분해 기록한다.

`test_curated_hwpx_publication.py`의 opt-in real-render 검사는 격리 DB·local Artifact store와
설치된 Builder를 조합한다. 기본 발행 테스트의 가짜 렌더 bytes를 실제 HWPX 증거로
보고하지 않는다. 잘못된 legacy 그림 dimensions를 전체 시험지 이미지로 강제 대체하지
않으며 `test_native_item.py`의 관련 회귀를 유지한다.

## 먼저 열 파일

- `apps/web_gui/eom_web_gui/static/item-preview.js`
- `apps/web_gui/eom_web_gui/item_preview_projection.py`
- `services/hwpx_manager/eom_hwpx_manager/application_service.py`
- `services/hwpx_manager/eom_hwpx_manager/renderer_recovery.py`
- `services/hwpx_manager/eom_hwpx_manager/curated_application_service.py`
- `services/hwpx_manager/eom_hwpx_manager/curated_build_models.py`
- `services/hwpx_manager/eom_hwpx_manager/curated_materialization.py`
- `packages/hwpx_contracts/eom_hwpx_contracts/curated_mixed.py`
- `services/hwpx_builder/eom_hwpx_builder/curated_mixed_renderer.py`
- `services/hwpx_builder/eom_hwpx_builder/curated_editorial_layout.py`
- `services/hwpx_builder/eom_hwpx_builder/hwp_conversion_package.py`
- `services/hwpx_builder/eom_hwpx_builder/native_intent_box.py`
- `services/hwpx_builder/eom_hwpx_builder`
- `packages/hwpx_contracts/eom_hwpx_contracts/curated_document.py`
- `services/hwpx_builder/eom_hwpx_builder/curated_renderer.py`
- `services/catalog_service/eom_catalog_service/office_document_converter.py`
- `services/catalog_service/eom_catalog_service/office_document_review_intake.py`
- `services/catalog_service/eom_catalog_service/document_review_pdf_annotation_service.py`
- `services/catalog_service/eom_catalog_service/document_review_hwpx_correction_service.py`
- `services/catalog_service/eom_catalog_service/review_textbook_evidence_service.py`

## 검증과 근거

- `tests/api/test_hwpx_download_boundary.py`
- `tests/integration/test_hwpx_item_recovery.py`
- `tests/unit/test_document_review_pdf_annotation.py`
- `tests/unit/test_single_document_review_textbook_v5.py`
- `docs/architecture/HWPX_APPLICATION_API_V0.md`
- `docs/architecture/PDF_DOCUMENT_REVIEW_V1_IMPLEMENTATION_PLAN.md`
- `docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md`: 가변 구조 원본의 HWPX 재출력 후속 범위.
- `docs/architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md`
- `docs/operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md`
