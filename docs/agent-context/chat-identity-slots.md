# 일반 대화와 계정과 슬롯

## 일반 대화

`일반 → ChatGPT`는 별도 Codex 실행을 대화 UI로 제공하는 기능이다. 외부 ChatGPT/LLM API로
바꾸는 기능이 아니다. Web은 Markdown을 안전하게 렌더링하고 API는 대화·turn·삭제와
권한을 관리한다. Orchestrator의 general chat owner가 실제 worker와 broker를 연결한다.

내부 자료를 참고하려면 설치 runtime에 실제 노출된 read tool과 Catalog source resolver를
쓴다. 검색·읽기·교과서 근거·유사도 연결은 서로 다른 도구/consumer 경계일 수 있다.
도구 이름을 프롬프트에 썼다는 사실이 운영 연결이나 사용 권한은 아니다. 답변은 materialize된
근거만 인용하고 권한과 Graph/source/report pin을 후속 대화에서도 검증한다.

Codex 알림의 추가로 대화가 실패하면 thread/turn을 확인한 adapter에서 프로토콜을 처리한다.
알 수 없는 알림을 전부 답변으로 붙이거나 모든 schema 검사를 끄지 않는다. 기존 실패 turn을
자동 재실행/성공으로 바꾸지 않는다. 대화 삭제는 사용자 소유와 lifecycle 경계를 따른다.

한도 초과 같은 `error` 알림은 그 자체로 turn 종료가 아니다. 정확한 thread/turn의
terminal 실패를 확인하고 정상 thread 정리를 마친 경우에만 worker를 유지한다.
timeout·잘못된 identity·정리 실패는 기존대로 폐기한다. 자동 추론 재전송은 없다.
현재 공개 실패 코드와 안전한 native 원인 로그를 구분하며, worker 정상과 계정 한도
회복도 다르다. 상세는 `GENERAL_CHAT_CODEX_RUNTIME_EVOLUTION.md`의 terminal 실패 절을 본다.

## 로그인과 계정

Web session/cookie/CSRF와 API access/refresh/re-authentication 경계는 별개다.
인증 성공·사용자 권한·실행 owner의 권한 capture를 같은 것으로 간주하지 않는다.
세션 만료 때 새 요청을 우회 생성하거나 관리자로 위장하지 않는다. rate limit은 정상 로그인
성공까지 실패 횟수로 누적하지 않는지, 공식 비밀번호 복구 후 이전 제한이 남지 않는지 본다.

계정 생성/역할/삭제는 관리자 use case를 통해 처리한다. 개발 문맥에는 실제 비밀번호,
토큰·cookie·인증 파일·사용자별 로그인 자료를 넣지 않는다. 실제 인증이 필요하면 기존 공식
입력 경계와 현재 유효 세션을 재사용하되, 입력하지 않은 인증을 성공한 것으로 꾸미지 않는다.

관리자 계정 카드의 일반 작업(역할 추가·다시 사용)과 주의 작업은 분리한다. 역할 해제·
정지·세션 종료는 기본 닫힌 `주의가 필요한 작업` 안에 모으고 영구 삭제는 맨 아래에
따로 둔다. 사유·삭제 확인·권한·자기 계정 보호는 기존 handler/application 경계를 유지한다.

관리자 변경의 ETag 검사는 Identity application이 target row를 잠근 뒤 수행한다. API의
`run_operator_command`는 idempotency receipt와 Operator 변경을 한 DB transaction에 묶는다.
`OperatorService.join_transaction`은 그 한 호출만의 facade이며 공유 service/worker 인증을
바꾸지 않는다. API token refresh와 자격 변경은 session → token 순서로 잠그며, access도
session lock을 기다린 뒤 token 철회를 재확인한다. Web의 자격 변경·자동 refresh는 같은
세션 lock을 공유한다. 실패 이력을 성공 처리하는 복구가 아니라 새 race의 예방이다.

## 슬롯과 사용량

모델 실행 Job/유효 lease/물리 worker, 계정의 주간 사용량, capability 검증,
관리자의 enable/disable 상태는 다른 값이다. quota 소진은 정상적인 사용량 제한이지
모든 기능의 기술 장애가 아니다. 실행 중이어도 독립 상태·사용량 관측이 동작해야 한다.
계정 변경 후 이전 계정의 모델 검증 결과를 새 계정의 승인으로 재사용하지 않는다.

모델 허용 정책을 부분 검증 결과로 갱신할 때는 `codex_compatibility_policy`가 검증 대상
슬롯의 기존 scoped 설정만 교체한다. 검증하지 않은 V3 슬롯은 runtime·binding·assignment·
slot·role이 모두 그대로일 때만 보존한다. 새 실행 파일이나 다른 계정에 과거 PASS를
옮기지 않는다. 출제/검토의 공통 모델 조건도 다시 확인한다. 단일 슬롯 검증 결과를
전체 allowlist로 취급하면 나머지 슬롯이 `CAPABILITY_OBSERVATION_FAILED`가 된다.
정책 설치 후에는 기존 공식 OBSERVE/maintenance로 실제 상태를 갱신한다. DB의 상태
문자열을 READY로 직접 바꾸지 않는다. 회귀 검사는 `test_codex_compatibility_policy_install.py`다.

GUI의 네 슬롯 RUNNING만으로 Graph 등록·INDEX가 정상이라고 판정하지 않는다.
반대로 publication·source 준비 구간에서 슬롯이 잠시 비면 실제 queue/claim을 확인한다.

6번 채팅 전용 예약은 `general_chat_capacity.worker_slot_id`가 정본이다. 일반 claim은
예약된 슬롯을 제외하고, 채팅 claim은 현재 auth assignment를 pin한다. 별도 채팅 queue를
Workflow lease로 위장하지 않는다. API의 `active_chat_count`는 held chat claim이며
`chat_runtime_state`는 heartbeat/admission 관측이다. stale 점유도 계정 변경을 계속 막지만
읽기 전용 사용량 관측은 허용한다. 실제 활성화는 예약 행과 설치 release를 확인해야 한다.
설계·운영 경계는 `docs/architecture/GENERAL_CHAT_SLOT06_RESERVATION.md`를 본다.
슬롯 목록은 capacity 전체 ORM 행이 아니라 공개 점유 상태 열만 한 번 조회한다.
API 역할의 column grant와 실제 SELECT 열을 함께 검증한다. control의 capacity 잠금도
singleton key만 SELECT FOR UPDATE 하며, key의 제한된 UPDATE 권한은 PostgreSQL의
잠금 전제이지 claim·예약·heartbeat 변경 권한이 아니다. 최소 권한 owner 검사만으로
API 계정의 목록/새로고침이 동작한다고 판단하지 않고 실제 API 역할 DB 검사도 수행한다.
예약 전환과 호환성 maintenance의 실행 가능 Job 판정은 `job_execution_queries`를 공유한다.
정확히 연결된 step·parent가 모두 FAILED/CANCELLED이고 실행 command가 없는 과거
CLAIMED/RUNNING만 역사로 분류한다. Job 이력을 고치거나 실제 unit·held lease 검사를 생략하지 않는다.

실행 설정 화면은 current released revision과 편집 중인 새 draft만 다룬다. 과거 revision을
숨기는 UI 정책은 evaluation/실행 plan의 immutable 참조 삭제를 뜻하지 않는다.

## 먼저 열 파일

- `apps/web_gui/eom_web_gui/static/general-chat.js`
- `apps/web_gui/eom_web_gui/static/chat-markdown.js`
- `apps/application_api/eom_api/services/general_chat_service.py`
- `services/orchestrator/eom_orchestrator/general_chat_owner.py`
- `services/orchestrator/eom_orchestrator/general_chat_tool_broker.py`
- `apps/application_api/eom_api/services/auth_service.py`
- `services/identity_service/eom_identity_service/auth_service.py`
- `services/identity_service/eom_identity_service/tokens.py`
- `services/identity_service/eom_identity_service/service.py`
- `apps/application_api/eom_api/services/idempotency_service.py`
- `services/orchestrator/eom_orchestrator/worker_usage.py`
- `services/orchestrator/eom_orchestrator/auth_enrollment_capabilities.py`
- `services/orchestrator/eom_orchestrator/chat_slot_reservation.py`
- `services/orchestrator/eom_orchestrator/job_execution_queries.py`
- `services/orchestrator/eom_orchestrator/chat_support_routing.py`
- `apps/application_api/eom_api/services/control_plane_adapter.py`

## 검증과 근거

- `tests/unit/test_private_chat_document_read.py`
- `tests/unit/test_postgres_local_indexing_fence.py`
- `tests/api/test_identity_integration.py`
- `tests/api/test_api_integration.py`
- `docs/architecture/API_IDEMPOTENCY.md`
- `docs/architecture/OPAQUE_TOKEN_SESSIONS.md`
- `docs/architecture/GENERAL_CHAT_TEXTBOOK_RAG_DESIGN.md`
- `docs/operations/CODEX_AUTH_AUTOMATIC_MODEL_VERIFICATION_RELEASE.md`
- `docs/operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md`
