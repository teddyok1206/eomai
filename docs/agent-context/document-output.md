# 문서 미리보기와 출력과 자료 검토

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
`hwp_conversion_package.py`는 고정 writer의 빈 style name·동일 크기 0 축약·ZIP만 정규화한다.
페이지 PNG 대체나 원본 덮어쓰기는 하지 않는다. 이 코드·설치본 검증을 운영 GUI 활성화로
간주하지 말고 아래 현재 체크포인트와 실제 release를 대조한다.

가변 canonical Item/1.0은 Manager `native_item_projection.py` → local
`native-item-render-request/1.0` → Builder `native_item_renderer.py`로 투영한다. 원본 content와
effective visual content hash를 분리해 pin하고 그림 use와 binary 파일을 구분한다.
계약의 `native_item_format.py`/`native_item_semantics.py`는 저장소나 DB에 접근하지 않는
순서·표·수식·uncropped picture 검증이다. content-team/2.0·3.0과 구 고정 예제 profile은
그대로 남는다. 저장된 배치의 영속 delivery와 API/GUI 연결 여부는 별도로 확인한다.

`curated_application_service.py`는 별도의 `hwpx_curated_builds`에서 actor/key 멱등 요청,
partial FIFO claim, 같은 build의 advisory lock과 중단 복구를 소유한다. input plan에는
`curated-hwpx-build-input/1.0`의 source/effective content·handoff·converter pointer만 저장한다.
예정 Job/Artifact/revision identity를 실행 전에 pin하며 완료 조회는 render를 호출하지 않는다.
실제 파일 실행·commit·다운로드 adapter와 API/GUI wiring은 이 queue 코드 자체와 구분한다.

Catalog `authorize_delivery_build`와 `read_for_delivery`는 각각 기존 HWPX 제작/조회 권한을
재확인한다. 선택 시에는 current Graph, 저장된 조립의 delivery에는 그 exact published Graph를
사용한다. 원본 metadata는 batch join으로 확인하고 status poll에서 모든 파일을 다시 hash하지
않는다. bytes와 actual visual proof는 명시적인 stage·검증 경계에서 다시 대조해야 한다.

이 Python use case의 존재는 private Catalog RPC 활성화 증거가 아니다. API 쪽 연결은
기존 `catalog_application_client.py`/Catalog `application_server.py` 경계를 유지한다.
API의 입력 pinning 때문에 NAS 접근·native 변환 dependency를 API에 추가하지 않는다.
실제 mixed-render adapter와 RPC/API/Web wiring의 남은 범위는 체크포인트에 기록한다.

## 먼저 열 파일

- `apps/web_gui/eom_web_gui/static/item-preview.js`
- `apps/web_gui/eom_web_gui/item_preview_projection.py`
- `services/hwpx_manager/eom_hwpx_manager/application_service.py`
- `services/hwpx_manager/eom_hwpx_manager/curated_application_service.py`
- `services/hwpx_manager/eom_hwpx_manager/curated_build_models.py`
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
- `tests/unit/test_document_review_pdf_annotation.py`
- `tests/unit/test_single_document_review_textbook_v5.py`
- `docs/architecture/HWPX_APPLICATION_API_V0.md`
- `docs/architecture/PDF_DOCUMENT_REVIEW_V1_IMPLEMENTATION_PLAN.md`
- `docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md`: 가변 구조 원본의 HWPX 재출력 후속 범위.
- `docs/architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md`
- `docs/operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md`
