# ChatGPT 답변 실패 — Codex moderation metadata 호환 수정 인계

2026-10-24 UTC. **호환 운영 배포와 새 채팅 실제 응답 검증을 완료**했다.
수정 source는 `1a4e3c678bedb1ad5b57497f01c3577ce0d3f6e1`이며 main에 push했다.
메인 대화의 GPU 우선·묶음 임베딩 작업과 독립된 변경이다. 아래 소스 인계 시점의
미배포 기록은 역사적 상태이며, 최신 결과는 마지막 운영 검증 절을 따른다.

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

## 운영 배포와 실제 검증 — 2026-10-24 14:27 UTC

- 위 코드·회귀 테스트·인계 문서3개만 별도 commit/push했다. 미완성 GPU 소스15개는
  명시적 경로의 recoverable Git stash로 보존했고 실제 release archive/wheel에서 제외했다.
  GPU 기본값·새 batching 모듈이 이번 채팅 수정과 함께 운영 활성화된 것은 아니다.
- 메인 재검증: 관련4개 묶음174 PASS, worker 포함184 PASS, 추가 native 계약/선택/인계
  92 PASS. 서로 겹치는 테스트를 합산하지 않는다. 전체 채팅은833 PASS / 인계에 기록된
  기존 owner SupplementaryGroups 기대값 불일치1 FAIL를 재확인했다. unit/해당 test는
  이번 수정 전후 동일하다. scoped Ruff·format·native strict mypy PASS다.
- 활성 채팅0, 인증 변경0, 유효 worker lease0, 실제 native/GPU 실행 없음 확인 후 공유
  consumer를 정상 중지하고 기존 release operator와 installer로 platform/API를 설치했다.
  source archive·wheel RECORD·설치 metadata·API 실제 격리 검사 PASS, DB head0058 유지다.
- 독립 build-only 후보는 `/tmp/eom-api-build/1a4e3c678bedb1ad5b57497f01c3577ce0d3f6e1.WABb5c`;
  실제 설치 delivery는 같은 source의 `1a4e3c678bedb1ad5b57497f01c3577ce0d3f6e1.vusL3p`다.
  두 ZIP raw hash는 동일 source라고 해서 같다고 주장하지 않는다. 실제 설치 SHA-256:
  - platform: `ebe95db10b25c19f151994c58f58002d8a1dddb8b37dcbf572d24222350958a2`
  - API: `1b663b52b7b6e743fd96b136c02c61a41037805961474410745f6776b996119b`
  - API contracts: `ffd19c9674b4b9c66d19ad7700e7e80dbce4c6ec406ed83f1ef050084dc91247`
- 보호된 operator context는 `/var/lib/eom-release-operator-stage.1a4e3c67-ts8ixz2m`이며,
  context SHA는 `fc9b47c7acab9c665ff7387487d32d87fb01e0b70a4b762d67d1bd3e448e6dd8`다.
  기존 QUERY SDK `2eef9b20`은 유지하고 실제 API source/wheel과 기존12개 provider code의
  동일 bytes를 확인해 네 public 설정만 CAS successor로 연결했다. 원 Graph·access policy·
  namespace·model은 불변이며 변경 전/후/intent는 `/var/lib/eom-query-provider-chat-1a4e3c67`에 있다.
- 일반 대화 owner의 비밀이 아닌 source provenance pin만 새 commit으로 정렬했다.
  prompt/model/tool policy, 계정 비밀번호·Codex 인증 파일은 변경하지 않았다. Web은 이번
  변경 대상이 아니며 기존 f15e66b8을 유지했다. 공유 API wire 계약 변경은 없다.
- 설치된 handler raw SHA가 인계 수정본 `39d9e1…f2630`과 일치한다. API/Chat owner·worker/
  QUERY/auth broker 정상 기동, HTTPS login200·readiness READY, 실제 QUERY OWNER_READY 확인.
  INDEX PID130161 / invocation053c5ab467ff4e29b4901cfabf037b4b는 변경하지 않았다.
- 사용자 새 메시지1건 `chatturn_abecc515cf9a8ea50b8c800981c331ce`는
  14:27:18.547924→14:27:26.612505 UTC, 약8.065초 뒤 COMPLETED / SUCCEEDED다.
  output Artifact `artifact_5ff92ae2c3554e65977ae1b4edf16fba`, revision
  `rev_e5bbd82ae73d4fef97c3ee72eff0eeee`가 기록됐고 output/result hash는
  `sha256:3dfe318f6e67f450f54690994ab32e8420a01f9c3208afbdf20cf3553c2b7ff7`다.
  사용자가 실제 답변 표시를 확인했다. 여기의 hash는 운영 metadata 관찰이며 별도 NAS byte
  재검증이나 두 번째 모델 호출을 수행했다는 뜻이 아니다.
- 원 실패 turn의 FAILED/code/생성·종료 시각이 전후 동일함을 읽기 전용으로 확인했다.
  기존 실패 대화의 재실행·성공 변환·DB 직접 수정은 하지 않았다. 실제 canary 외 모델 재호출0.
- rollback record: `/var/lib/eom-api/deployments/1a4e3c678bedb1ad5b57497f01c3577ce0d3f6e1.json`.

```text
SOURCE_FIX=COMMITTED_AND_PUSHED
PLATFORM_API_INSTALLED=1a4e3c67
QUERY_PROVIDER_ALIGNMENT=PASS
HTTPS_READY=PASS
USER_VISIBLE_REPLY=PASS
LIVE_NEW_TURN_COMPLETED=PASS
ORIGINAL_FAILED_HISTORY=PRESERVED
GPU_CANDIDATE_IN_THIS_RELEASE=EXCLUDED
```
