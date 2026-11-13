# 자료 검토 업로드의 동일 요청 이어가기

U04/U05/U06 후속 수정이다. 오래 걸리는 변환을 새 queue나 Web background task로
옮기지 않고, 기존 API upload intent/set과 Catalog 처리 소유권을 유지한다.

## 경계와 정본

- 책임은 Web의 업로드 응답·재진입 복구다. 처리 정본은 기존 API의 operator 소유
  `PdfDocumentReviewUploadIntentRecord` / `DocumentReviewSetRecord`와 멤버 상태다.
- 원본 logical ID·revision·Artifact·SHA와 workflow identity는 기존 application이 고정한다.
  Web이 PROCESSING을 성공으로 바꾸거나 다른 upload intent로 우회하지 않는다.
- 같은 사용자의 정확한 intent/set ID만 인증된 기존 GET으로 읽는다. 권한·현재 session은
  API가 다시 검사하며 브라우저 저장값을 권한으로 사용하지 않는다.

## 계약과 접근 방식

새 의미의 wire schema나 DB migration은 없다. 기존 intent V2와 paired set DTO/schema를
Web의 GET `/pdf-document-reviews/upload-intents/{id}`와 `/sets/{id}`에도 노출한다.
모든 state·workflow pointer·failure code·version·hash는 기존 typed validator를 따른다.

주 연산은 operator/intent PK 조회, paired set의 두 멤버 조회, 같은 intent의 상태 polling이다.
기존 인덱스와 작은 typed 응답으로 충분하다. 한 번의 조회 비용은 기존 indexed lookup과
상수 개수(두 멤버)의 투영이며, 파일 bytes·전체 문항을 복사하지 않는다.

Web PUT의 upstream transport가 실패하면 **동일 intent/set 상태를 한 번만** 조회한다.
서버가 PROCESSING/STARTING 또는 해당 멤버 COMMITTED/전체 STARTED를 확인한 경우에만
진행 상태로 반환하고, 화면은 같은 GET을 조회한다. 상태가 없거나 AWAITING인 경우에는
원래 transport 오류를 유지한다. 재조회에서 확인한 401/403은 숨기지 않고 그대로 반환한다.
자동 PUT replay나 새 key 생성은 하지 않는다.

API의 기존 `run_in_threadpool`과 durable processing claim이 원래 변환을 계속 소유한다.
서버 재시작/lease 만료 뒤 복구가 필요하면 기존 같은-key 재제출·reconcile 규칙을 따른다.
Web GET은 처리 claim을 만들거나 갱신하지 않는다. 기존 FAILED 이력도 보존한다.

## 재진입과 형식 판별

브라우저는 owner별로 작은 intent/set ID·원래 idempotency key·요청 fingerprint hash만
보관한다. credentials, session, 파일 bytes, 자연어 지침은 보관하지 않는다. 다른 계정은
이를 재사용하지 않으며, 불명확한 이전 요청을 버리고 새 identity를 만들지 않는다.

확장자 hwp인데 실제 ZIP/HWPX인 파일은 새 intent를 만들기 전에 bounded header로
HWPX 후보로 선택한다. 저장된 과거 계약의 파일명/format 일치를 바꾸지 않도록 새 제출명은
원래 이름에 `.hwpx`를 붙인다(예: `교재.hwp.hwpx`). 원래 File 객체·이름·bytes는 바꾸지
않고 화면에서 원래 이름과 제출명을 함께 안내한다. 등록되는 `original_filename`은 이
정규화한 제출명이다. 원래 이름이 prefix로 남는 것이지 별도 원래 이름 필드가 저장되거나
byte-for-byte 동일한 filename provenance가 추가됐다고 주장하지 않는다.
API의 고정 media/hash 검사와 Catalog
`validate_office_source`의 ZIP member·mimetype·크기/경로 검증은 그대로 유지한다.
header 판별만으로 임의 ZIP이 문항 원본으로 등록되는 것은 허용하지 않는다.

단순히 timeout을 모두 늘리면 proxy/session 한계가 다시 나타나고, API 변환을 새로운
untracked task로 옮기면 중단 시 소유권이 사라진다. 따라서 기존 상태 조회와 동일 요청
복구만 연결한다. 실제 변경은 owner-scoped epoch/상태 검사와 bounded polling으로 검증한다.
