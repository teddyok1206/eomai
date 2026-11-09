# Excel 브라우저 복구와 DB 목록 가져오기

2026-11-09. 원설계 §5·18.4의 완료 보완이며 새 runtime authority가 아니다.

- 정본은 Catalog의 기존 immutable 편성 revision·command receipt다. 화면 경로는
  콘텐츠·판·revision·구간의 검증 가능한 ID만 URL에 보존한다. 복원도 실제 로그인
  사용자의 기존 READ_EDITION/READ_SECTION을 호출하고 다른 revision으로 대체하지 않는다.
- DB 임시 배치 목록은 기존 typed selection을 순서대로 새 자리들에 복사한다. DB 목록,
  파일, 문항 revision은 변경하지 않는다. 여러 선택은 한 번 검증·배열 생성 후 반영하며
  중간 실패로 일부만 들어가지 않는다. 같은 문항 반복은 새로운 placement identity다.
- 제출한 요청만 같은 브라우저 탭의 `sessionStorage`에 owner별로 보관한다. 저장 내용은
  허용 endpoint 분류·원래 멱등 key·typed command body뿐이다. 비밀번호·cookie·session·
  CSRF·권한·실제 파일은 저장하지 않는다. UTF-8로 인코딩한 envelope 최대 4MiB이며
  일반 미제출 초안 자동 저장이 아니다. 한글 문자 수를 바이트 수로 착각해 전송 한도를
  넘는 요청을 복구 대기에 남기지 않도록 저장 전 검사한다.
- 새로고침·재인증 후 같은 owner만 원래 요청을 확인할 수 있다. 다른 owner에게 표시하거나
  자동 실행하지 않는다. `같은 요청 다시 확인`은 기존 API가 현재 권한과 동일 key/body를
  재검증한다. 성공 응답 후만 제거하며 실패·timeout을 새 key로 바꾸지 않는다.
- 서버가 정확한 `CONTENT_EDITION_REVISION_STALE`로 저장 거부를 확정한 경우에는
  사용자가 변경을 버리겠다고 명시했을 때만 기존 요청을 닫고 현재 저장본을 읽는다.
  일반 timeout과 구분하며, 충돌을 받았다는 이유만으로 편집 내용을 자동 삭제하지 않는다.
- 캐시 손상은 명시 오류로 새 저장을 막는다. 저장소 쓰기 실패는 POST 전에 드러난다.
  탭 저장소를 제공하지 않는 환경에는 기존 메모리 재시도만 있고 새로고침 복구는 보장하지 않는다.
- URL은 주소당 작은 O(1) pointer이며 요청 cache는 owner당 현재 제출 1건, JSON 직렬화는
  변경 자리 수 O(P)다. 서버 저장 결과를 복제하는 cache/DB나 별도 queue는 만들지 않는다.
- 원래 메모리-only 요청은 페이지를 닫거나 인증 화면으로 돌아오면 key를 잃었다.
  URL만으로는 제출된 command body·key를 복원할 수 없어 작은 replay envelope를 분리했다.
- 선택 복사 클립보드는 저장된 원본 assembly revision/hash/placement provenance만 담는
  탭 메모리 값이다. 페이지 간 선택은 Set, 순서는 저장된 원본 순서다. 붙여넣기는 새 자리
  identity를 만들고 기존 draft/SAVE_SECTIONS를 사용하며 계정 변경 시 클립보드를 지운다.

검증: `content_planning_location_*`, `content_planning_pending_checks.mjs`,
`content_planning_browser_checks.mjs`, `item_db_browser_checks.mjs`. 운영 설치 여부는
기존 Excel implementation checkpoint에 별도로 기록한다.
