# ChatGPT 답변 실패 — Codex moderation metadata 호환 수정 인계

2026-10-24 UTC. 보조 대화에서 확인·수정한 소스 후보이며 **운영 미반영**이다.
메인 대화의 GPU 우선·묶음 임베딩 작업과 독립된 변경이다.

## 확인한 장애와 원인

- 최근 실패 turn: `chatturn_079f08f35ebf9633e2625d6edf206643`.
- 생성 시각 `2026-10-24T14:10:30.103011Z`, 실패 시각
  `2026-10-24T14:10:38.122337Z`; `FAILED / CODEX_PROTOCOL_INVALID`.
- 같은 시각 worker journal:
  `GENERAL_CHAT_NATIVE_FAILURE method=turn/moderationMetadata code=CODEX_PROTOCOL_INVALID stage=NONE`.
- 설치 CLI는 `0.162.1`, 현재 shared API/platform source는
  `f15e66b8110900296fc37676502469dee15df741`이다.
- 설치본 `general_chat_native.py`에는 해당 알림 처리 분기가 없다.
  설치 파일 SHA-256은 `f01e441db2060cf17e535f4d3b0289d83b3338174f8eca4ca1d1eca9f62aef8e`다.
- 새 알림은 답변·도구 호출이 아닌 turn 부가 정보다. 이를 알 수 없는 protocol로
  처리하면서 정상 응답도 중단되고 worker가 재시작됐다. 로그인 실패나 GPU 문제가 아니다.

## 확인한 외부 계약

[OpenAI App Server 문서](https://developers.openai.com/codex/app-server/)의
버전별 schema 생성 절차에 따라 설치 CLI의 JSON Schema를 생성해 확인했다.
외부 LLM API·모델 추론·인증 정보 조회는 하지 않았다.

`TurnModerationMetadataNotification`은 `threadId: string`, `turnId: string`,
필수 opaque `metadata`를 갖는다. `metadata`는 임의 JSON 값이며 `null`도 가능하다.
이 값의 존재가 답변 성공이나 허용된 실행을 의미하지 않는다.

생성한 해당 schema의 raw SHA-256:
`90fe9ade83c46fd42af9d023737a9990595dac71e059158744950f538e802876`.
전체 생성 bundle은 임시 `/tmp/eom-chat-schema-20261024.pvXxoX`에 있고 Git에 추가하지 않았다.

## 변경 소유 범위

1. `services/orchestrator/eom_orchestrator/general_chat_native.py`
   - 기존 thread/turn ID 검증 **이후** 정확한 `turn/moderationMetadata`만 처리한다.
   - 필수 `metadata` 키를 확인하고 opaque 내용은 답변·로그·도구 권한으로 사용하지 않는다.
   - 전역 NON_CONTENT whitelist나 임의 `turn/*` 무시 규칙은 추가하지 않았다.
   - 답변 성공에는 여전히 completed turn과 실제 final answer가 필요하다.
2. `tests/unit/test_general_chat_native.py`
   - response 전후 알림, null/객체 metadata, 내용 비노출, thread/turn mismatch,
     필수 키 누락, 답변 없는 종료, server execution request 위장 거부를 검증한다.
3. 이 인계 문서.

현재 native 소스 파일 SHA-256:
`39d9e1bbbb26e61980e2207dbdc181a46d9a4a7d9c3bdad6ff36ce02276f2630`.
schema family, DB migration, 의존성, prompt, 모델·계정 설정 변경은 없다.
실패 이력, 사용자 대화 내용, auth 파일은 변경하지 않았다.

## 검증

- 수정 전 신규 재현: 정상 metadata 사례 6개 모두 같은 protocol 오류로 실패했다.
- 수정 후 최초 관련 native/grounded/RAG/tools/resident 집중 검사: 199 PASS.
- 추가 negative 2개 포함 최종 동일 집중 검사: **201 PASS**.
- 추가 negative 2개를 포함한 전체 `test_general_chat*.py`: **833 PASS, 기존 불일치 1 FAIL**.
  실패는 `test_general_chat_os_isolation.py`의 owner SupplementaryGroups 기대값이
  기존 unit의 `eom-general-chat` 포함과 다른 것이며 이 작업에서 unit/해당 test는 수정하지 않았다.
- scoped Ruff, formatter, native module strict mypy PASS.
- 운영 DB는 read-only metadata SELECT만 사용했다. 운영 pytest·row 수정·모델 실행 0회.

## 운영 반영 경계 — 메인 대화에서 수행

현재 worker는 `/srv/eom/conda/envs/eom-api`의 shared platform wheel을 사용한다.
설치 파일 직접 덮어쓰기, RECORD 조작, 별도 임시 PYTHONPATH 주입은 하지 않는다.
메인 작업의 고정 환경을 깨뜨릴 수 있으므로 이 보조 세션은 wheel 설치·서비스 재시작·
release source pin 갱신을 실행하지 않았고, 다른 작업의 파일도 커밋하지 않았다.

1. 위 두 코드/test 파일과 이 문서만 구분해 검토한다. 메인 작업 변경을 무차별 staging하지 않는다.
2. native 작업·채팅 active turn의 실제 quiescence를 확인한 시점에 기존 호환 release 절차로
   shared platform/API와 필요한 component를 반영한다. 고정 numerical prefix는 변경하지 않는다.
3. 새 wheel/RECORD와 실제 installed handler를 확인한다. 기존 QUERY provider가 shared
   release member를 pin하므로 해당 compatibility도 함께 확인한다.
4. Chat owner/worker의 source policy 일치를 확인한 뒤 정상 시작한다.
5. 사용자가 새 메시지를 1회 전송해 COMPLETED와 실제 화면 응답을 확인한다.
   원 FAILED turn을 성공으로 바꾸거나 자동 재실행하지 않는다.

`SOURCE_FIX=READY`, `PRODUCTION_DEPLOYMENT=PENDING`, `LIVE_CHAT_VERIFICATION=NOT_RUN`.
