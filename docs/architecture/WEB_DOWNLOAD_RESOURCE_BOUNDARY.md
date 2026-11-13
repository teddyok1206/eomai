# Web 다운로드 자원 경계

사용자 오류 위험 검토 U03의 수정 설계다. 정본/HTTP wire schema는 변경하지 않는다.

- 책임: Web HTTP adapter가 인증된 API 응답을 검증한 뒤 브라우저로 전달한다.
  소스 권한·Artifact lifecycle·원본 hash 정본은 기존 API/Catalog가 소유한다.
- 정본과 revision: 임시 spool은 정본이 아니며 새 Artifact/DB/revision을 만들지 않는다.
  기존 download URL의 exact source/build/revision을 그대로 사용한다.
- 해석 검사: 기존 MIME/disposition/hash/길이/prefix 검증을 보존한다. 헤더를 먼저 검사하고,
  실제 수신 길이를 매 chunk 제한한다. 전체 해시 확인 전에는 사용자에게 bytes를 내보내지 않는다.
- 접근/구조: 순차 수신·SHA-256·순차 송신이다. 64KiB chunk, 1MiB까지만 RAM에 보관하는
  private tempfile spool을 사용한다. 작은 응답은 검증 후 bytes로 반환해 기존 호출자를 보존한다.
- 규모/복잡도: 파일 크기 n에 O(n) 시간, 각 요청 O(1MiB + chunk) 메모리. 큰 파일은
  임시 디스크를 사용하며 최대 두 개의 검증/송신 spool만 동시에 보유한다.
- 동시성: gateway의 작은 bounded semaphore를 사용한다. 큰 spool은 브라우저 송신 종료까지
  permit을 보유한다. 5초 내 여유가 없으면 명시적인 재시도 가능 오류를 반환한다.
- 계층: 임시 파일·HTTP 수신·ASGI cleanup은 Web infrastructure에만 둔다.
  domain/contract나 API에 파일 경로/세션/DB 권한을 추가하지 않는다.
- 종료/실패: upstream 오류·초과·hash 불일치·취소는 spool/HTTP를 닫는다.
  ASGI 성공·disconnect·send 예외·취소도 finally에서 spool과 permit을 회수한다.
- 인증/retry: 기존 session refresh lock과 401 재확인을 사용한다. GET 다운로드만 stream하며
  body가 있는 변경 요청의 재전송 규칙은 변경하지 않는다. 오류 본문도 64KiB로 제한한다.
- 대안: 단순 메모리 증설/단일 다운로드 제한은 한 파일의 전체 buffering peak를 막지 못한다.
  검증 전에 바로 프록시 stream하면 마지막 hash 불일치를 정상 다운로드처럼 보낼 수 있다.
  따라서 검증된 bounded spool이 이 경계에 필요한 최소 materialization이다.
- DB transaction/migration과 공개 wire schema 변경은 없다. 기존 Starlette의 설치 의존성인
  AnyIO를 Web의 직접 의존성으로 명시한다. 취소된 ASGI scope에서도 기존 HTTP close를
  5초 한도로 shield하며 별도 미추적 cleanup task를 만들지 않기 위해서다.

검증은 실제 모델/GPU/운영 파일 없이 합성 HTTP stream과 ASGI send/disconnect로 수행한다.
동시 큰 파일의 peak allocation 및 임시 파일/permit 회수를 검사한다.
