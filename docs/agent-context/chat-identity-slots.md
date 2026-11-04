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

## 로그인과 계정

Web session/cookie/CSRF와 API access/refresh/re-authentication 경계는 별개다.
인증 성공·사용자 권한·실행 owner의 권한 capture를 같은 것으로 간주하지 않는다.
세션 만료 때 새 요청을 우회 생성하거나 관리자로 위장하지 않는다. rate limit은 정상 로그인
성공까지 실패 횟수로 누적하지 않는지, 공식 비밀번호 복구 후 이전 제한이 남지 않는지 본다.

계정 생성/역할/삭제는 관리자 use case를 통해 처리한다. 개발 문맥에는 실제 비밀번호,
토큰·cookie·인증 파일·사용자별 로그인 자료를 넣지 않는다. 실제 인증이 필요하면 기존 공식
입력 경계와 현재 유효 세션을 재사용하되, 입력하지 않은 인증을 성공한 것으로 꾸미지 않는다.

## 슬롯과 사용량

모델 실행 Job/유효 lease/물리 worker, 계정의 주간 사용량, capability 검증,
관리자의 enable/disable 상태는 다른 값이다. quota 소진은 정상적인 사용량 제한이지
모든 기능의 기술 장애가 아니다. 실행 중이어도 독립 상태·사용량 관측이 동작해야 한다.
계정 변경 후 이전 계정의 모델 검증 결과를 새 계정의 승인으로 재사용하지 않는다.

GUI의 네 슬롯 RUNNING만으로 Graph 등록·INDEX가 정상이라고 판정하지 않는다.
반대로 publication·source 준비 구간에서 슬롯이 잠시 비면 실제 queue/claim을 확인한다.

## 먼저 열 파일

- `apps/web_gui/eom_web_gui/static/general-chat.js`
- `apps/web_gui/eom_web_gui/static/chat-markdown.js`
- `apps/application_api/eom_api/services/general_chat_service.py`
- `services/orchestrator/eom_orchestrator/general_chat_owner.py`
- `services/orchestrator/eom_orchestrator/general_chat_tool_broker.py`
- `apps/application_api/eom_api/services/auth_service.py`
- `services/identity_service/eom_identity_service/auth_service.py`
- `services/orchestrator/eom_orchestrator/worker_usage.py`
- `services/orchestrator/eom_orchestrator/auth_enrollment_capabilities.py`

## 검증과 근거

- `tests/unit/test_private_chat_document_read.py`
- `tests/unit/test_postgres_local_indexing_fence.py`
- `docs/architecture/GENERAL_CHAT_TEXTBOOK_RAG_DESIGN.md`
- `docs/operations/CODEX_AUTH_AUTOMATIC_MODEL_VERIFICATION_RELEASE.md`
- `docs/operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md`
