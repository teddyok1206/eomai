# 일반 채팅 대화 삭제 운영 배포

2026-10-26 UTC. `일반 → ChatGPT`의 본인 대화 논리 삭제를 운영에 반영했다.
기능 소스는 `c9889580`, OpenAPI 정합성 보정과 실제 설치 소스는
`e70b4cdb8485d1d02e3ddf8dd3fa0ee6de793484`이다. 후속 상태 문서 commit은
설치 소스와 구별한다.

## 적용 경계

- DB migration `20261026_0059`를 기존 `20261019_0058`에서 보호된 release operator로
  적용했다. 삭제 시각과 멱등 요청 해시만 대화 row에 추가한다. transcript, turn,
  Artifact, 계정, 자료 corpus는 삭제하지 않는다.
- 공유 platform/API와 Web wheel을 호환 소스로 설치했다. 실제 API 설치 wheel SHA-256은
  `62be2932031815e7089b6260eb51579dc03c76a126a8000b27b2015b7c31d0fd`,
  Web wheel SHA-256은 `daf70d44896664f7a891fab8ab53ab0cb144eb9f2cb263782f2e9555940b7c97`이다.
- 기존 QUERY owner SDK `07ec7b32`와 모델/Graph/정책은 유지했다. 세 QUERY 구성과 unit의
  API provider pin만 실제 새 wheel로 CAS 갱신했다. 12개 provider 코드 member의 bytes는
  이전과 동일했다.
- 대화 모델 `gpt-6.1-sol`, 기존 RAG policy와 CLI identity는 보존하고 대화 서비스의
  비밀이 아닌 release pin만 새 소스로 전환했다. GPU INDEX PID `734655` 및 invocation
  `9718f2ed05ac404e84ce7a69559b110c`는 전환 전후 동일하다.

## 검증과 관찰

- 삭제/API/owner/Web/운영 callback 집중 테스트 108개, OpenAPI/프론트엔드 정합성
  테스트 13개 PASS. API 3-wheel RECORD 및 Web 설치 시뮬레이션 PASS.
- 보호된 operator admission, migration upgrade, migration verify, API 격리 검사 PASS.
  API release record는
  `/var/lib/eom-api/deployments/e70b4cdb8485d1d02e3ddf8dd3fa0ee6de793484.json`이다.
- HTTPS 첫 화면 최종 200, 채팅 JS HTTPS 200 및 소스와 동일 SHA-256, API live/ready 200.
  삭제 route의 무인증 요청은 401. API/Web/Chat owner·worker/auth broker/QUERY/INDEX는
  모두 active다. QUERY는 Chat owner보다 먼저 시작한 첫 시도에서 transport 미준비로
  종료됐고, Chat owner 준비 후 동일 고정 구성으로 정상 기동해
  `REFERENCE_QUERY_OWNER_READY`를 기록했다. 실패 기록은 보존했다.
- 사용자가 실제 화면에서 삭제 기능이 정상 동작한다고 확인했다. 이후 읽기 전용
  projection에서 삭제 표시가 있는 대화 9건, 활성 turn 0건, DB head 0059를 확인했다.
  9건 모두가 이번 수동 검증에서 생겼다고 추정하지 않는다. transcript/turn 상태는
  배포 전후 `COMPLETED=34`, `FAILED=12`로 유지됐다.

복구 시 삭제된 대화를 화면에 되살리는 schema downgrade를 임의로 하지 않는다.
새 기능에 문제가 생기면 0059-compatible release에서 기능을 차단하고 원 row와
실행 이력을 보존하는 방향으로 판단한다. 이 배포는 별도 GPU 우선 임베딩 목표의
완료나 QUERY3 활성화를 의미하지 않는다.
