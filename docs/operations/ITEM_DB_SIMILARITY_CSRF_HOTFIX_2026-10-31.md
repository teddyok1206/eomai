# DB 유사도 검색 요청 hotfix

2026-10-31 UTC. 사용자 문의 `webreq_806d1e668ffdbcf85dba7c20`:
`CSRF_TOKEN_INVALID`로 유사도 검색 시작/상태 확인이 실패했다.

## 원인과 수정

`app.js`의 실제 `searchSimilar` 연결 함수가 공통 `api()`에 `mutation: true`를
전달하지 않아 `X-CSRF-Token`이 없었다. 요청 본문도 연결 함수와 공통 전송
함수에서 각각 JSON 직렬화해 object 대신 JSON 문자열을 보냈다.

두 호출 규칙을 공통 전송 함수의 계약대로 수정했다. 서버의 CSRF·권한 검증은
그대로 유지한다. 실패 요청을 자동 재제출하거나 새 검색 identity로 바꾸지 않는다.
원래 선택 pointer·idempotency key·pinned query를 그대로 전달한다.

## 검증과 배포

- 소스 commit: `ed35324962dc1771d765f48ee491dc8e3d9eb6c4`.
- 실제 production 연결 함수와 `api()`를 함께 실행하는 Node 회귀 추가:
  최초 검색/기존 pinned query 조회, 현재 CSRF, 한 번의 JSON 직렬화,
  같은 멱등 key·정확한 경로 검증.
- BFF CSRF/권한 및 관련 DB GUI/API/alignment 회귀: 63 PASS.
- Web wheel SHA: `e61ba89886d304612df606f0e3cf542a69de5602e160b06ea0dfcae7f4e70393`.
- non-editable 설치 시뮬레이션 및 실제 `eom-web` identity RECORD: 52개 파일 PASS.
- 기존 공식 installer로 Web만 배포·재시작. API/QUERY/Catalog/INDEX/창작 슬롯은
  재시작하지 않았다. 기존 API `f419383c`와 wire contract 변경 없음.
- 실제 HTTPS ready = READY. HTTPS `app.js`와 수정 source bytes 일치 확인.

인증된 사용자의 실제 검색 버튼 재확인은 아직 사용자 확인 전이다. 기존 검색의
서버 처리 성공을 이 전송 회귀만으로 주장하지 않는다. 페이지 새로고침 후
진행 중인 검색은 ‘결과 확인’으로 같은 요청을 이어서 조회한다.

롤백은 직전 Web `f419383c` 검증 wheel을 기존 installer로 복구하고 Web만
재시작한다. DB migration·비밀번호·사용자 인증 파일 변경 없음.
