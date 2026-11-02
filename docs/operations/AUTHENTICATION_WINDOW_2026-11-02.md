# 로그인·재인증 유지 시간 조정

사용자가 2026-11-02에 현재 기간의3배 적용을 요청했다. 운영 API의 fresh-auth900초를2700초로,
Studio session1800초를5400초로 설정한다. access/refresh token 수명, API session absolute/idle,
비밀번호, 권한, 로그인 실패 횟수·잠금, TLS/CSRF는 바꾸지 않는다.

QUERY가 API와 달리900초를 상수로 사용하므로 API 설정만 바꾸지 않는다. 기존 설치된 Identity
provider adapter가 현재 API process/설정 hash/held FD를 검증한 뒤 그 설정의 fresh-auth 값만
읽어 QUERY의 기존 session fence에 전달한다. 60–3600초라는 기존 Identity 상한을 유지한다.
이 값은 인증정보나 실행 허가가 아니며, 요청마다 실제 session/token/permission 검사를 유지한다.

정본은 보호된 API/Web 운영 설정과 각 installed release다. 설정은 mutable current policy이며,
QUERY provider configuration SHA·owner source/cohost/Catalog digest는 호환 묶음으로 갱신한다.
새 wire/schema/DB/queue/cache는 없다. 기존 설정 FD의 bounded read O(config bytes), 고정 key
lookup O(1)을 사용하고 별도 모델/사용자 레지스트리를 만들지 않는다. root-only atomic config
교체와 before/after hash·rollback을 남기며 API/QUERY/Web를 다시 읽힌다. GPU INDEX와 진행 중
native INDEX는 재시작하지 않는다. 실제 진행 중 QUERY가 있으면 그 계산 종료 후에만 전환한다.

실패 시 적용된 단계부터 확인하고 기존 실패/완료 기록은 보존한다. 설정 hash나 provider process가
달라지면 fail-closed하며 최신/기본900초로 조용히 대체하지 않는다. `auth` 생략만 기존 API 기본900초다.
상수2700으로 교체하는 대안은 API와 다시 불일치할 수 있어 사용하지 않는다. 설정 읽기는 기존
Identity infrastructure adapter 소유이며 API/domain에 filesystem 의존성을 새로 넣지 않는다.

Web는 메모리 session adapter이므로 반영 시 기존 브라우저 session은 한번 재로그인이 필요하다.
그 뒤 새 session은90분, 민감 동작 재인증은45분이다. 계정별 권한이 바뀌는 기능은 아니다.
