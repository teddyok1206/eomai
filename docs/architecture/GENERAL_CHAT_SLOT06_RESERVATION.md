# 기존 6번 슬롯의 채팅 전용 전환

2026-11-10 사용자 결정: 과거 실행 설정은 화면에서 제거하되 참조 이력은 보존한다.
`일반 → ChatGPT`는 기존 6번 슬롯을 상시 전용으로 사용하고 일반 작업은 1~5번을 쓴다.
빈 슬롯 자동 선택이나 턴 사이에 6번을 일반 작업으로 반환하는 기능은 이번 범위가 아니다.
이 문서는 설계이며 운영 활성화 증거는 아니다.
실제 설치·모델 검증·사용자 확인 상태는
[운영 릴리스 기록](../operations/CHAT_SLOT06_RELEASE_2026-11-10.md)을 따른다.

## 경계와 정본

- 실행 설정 UI는 logical preset의 `current_revision_id`만 표시한다. 새 draft 작성/검증
  흐름은 유지하고 과거 revision/evaluation/plan/Artifact는 삭제하거나 재해석하지 않는다.
- 채팅의 기존 FIFO, private history, RAG tool broker, turn claim, handoff를 재사용한다.
  채팅을 가짜 Workflow/Job으로 만들거나 두 번째 scheduler/lease 체계를 만들지 않는다.
- 물리 슬롯 예약의 정본은 기존 `general_chat_capacity` 한 행의 nullable
  `worker_slot_id` FK다. NULL은 기존 별도 채팅 실행, `06`은 명시적 전용 예약이다.
  슬롯 역할·계정 인증 상태·사용량·사용자 중지 상태와 예약 목적은 별개다.
- 일반 lease 획득은 예약된 슬롯을 제외한다. heartbeat 만료/채팅 유휴가 예약을 해제하지
  않으므로 채팅 장애 때문에 일반 작업이 같은 HOME을 사용하지 않는다.

### API 슬롯 표시의 읽기 경계

슬롯 목록의 정본은 기존 capacity singleton이다. 새 entity/revision/cache/queue는 없다.
API control-plane read adapter는 `slot_key` indexed lookup으로 물리 예약·runtime identity·
heartbeat·active turn pointer·expiry의 작은 불변 projection만 읽는다. 기존 FK와 claim
owner를 바꾸지 않으며 transcript나 claim token은 읽지 않는다. 규모/비용은 슬롯 수와
무관한 단일 PK 조회이며 같은 목록의 여섯 슬롯에 재사용한다.

API runtime에는 이 여섯 column의 SELECT를 공식 privilege profile로 부여한다.
전체 ORM 행 로딩은 금지하고 명시적 열 조회를 쓴다. 상태 변경·사적 대화 읽기는
계속 owner 전용이다. 기존 계정 명령의 binding → capacity row lock에만 필요한
`UPDATE(slot_key)`는 CHECK로 'chat'에 고정된 singleton key에 한정한다. claim·예약·
heartbeat는 변경할 수 없고 전체 UPDATE/INSERT/DELETE도 부여하지 않는다.
현재 상태 목록 읽기에는 잠금·재시도·새 멱등 기록이 필요 없고,
heartbeat 만료는 UNAVAILABLE로 표시한다. 별도 상태 복사나 신규 RPC 대신 이미 존재하는
control-plane read 경계를 쓰며, table-wide SELECT보다 좁은 권한으로 검증한다.
실제 제한 API 역할로 목록 조회·금지 열/쓰기/사적 대화 접근 거부를 disposable DB에서
검증한다. owner 역할 테스트만으로 API 배포 검증을 대신하지 않는다.

## 데이터와 동시성

1. 논리 채팅/turn/claim/immutable dispatch/result identity는 그대로 보존한다. 예약은
   배포 시 변경하는 운영 구성이고 이전 실행의 source/revision/hash는 바꾸지 않는다.
   새 claim은 turn 행에 정확한 worker slot과 auth assignment revision을 한 번 기록한다.
   역사적 turn의 이 두 값은 NULL로 남기며 실행 계정을 추정하여 채우지 않는다.
2. 슬롯 FK, binding/current assignment, 활성 enrollment/control command, held workflow
   lease와 실제 서비스 종료를 확인한 뒤 예약한다. 실행 중 6번 작업의 pin을 바꾸지 않는다.
3. 접근은 singleton 예약 조회, indexed binding lookup, FIFO turn claim이다. 작은 nullable
   FK와 기존 PK/queue indexes면 충분하며 O(1) 예약 조회, indexed FIFO 접근을 유지한다.
4. 채팅 claim과 계정 변경은 기존 capacity 행의 짧은 잠금으로 직렬화한다. Control 측은
   기존 binding → capacity 순서를 유지하고, 채팅 owner는 capacity를 잠근 뒤 binding을
   제한 SELECT로 확인한다. 채팅 owner에 binding UPDATE 권한을 주지 않는다. 인증 변경의
   시작과 claim 모두 같은 capacity 잠금 안에서 상대의 진행 상태를 재확인한다.
   채팅 active claim은 인증 변경/모델 probe와 충돌하지 않도록 기존 maintenance 검사에
   포함한다. 사용량 읽기 전용 관측은 계속 허용한다.
5. 알 수 없는 실행 결과는 기존 exact-claim 복구 대상이며 자동 재추론하지 않는다.
   같은 요청 재조회는 기존 committed result/handoff를 사용한다. FAILED 이력은 보존한다.
6. 기존 reservation 변경은 일반 host claim과 같은 배제 경계 안에서 재검사한다.
   예약 이후 새 ordinary claim은 불가하고 이전 실행이 있으면 전환 자체를 거부한다.
   실행 가능성은 maintenance와 같은 read predicate를 재사용한다. 정확히 연결된 부모와
   step이 FAILED/CANCELLED이고 활성 명령도 없는 과거 CLAIMED/RUNNING 기록만 제외한다.
   lease·물리 실행 검사는 별도로 유지하고 과거 Job 상태를 변경하지 않는다.

## 실행 및 의존 방향

- Orchestrator application이 예약/claim/인증 정합성을 소유한다. DB 조회는 repository/
  adapter에서 수행하며 worker는 DB/NAS에 접근하지 않는다.
- 기존 06 계정의 HOME/auth를 그대로 사용한다. root/별도 chat 계정의 인증을 복사하지 않는다.
  채팅용 고정 config는 systemd namespace의 read-only bind로 제공하여 기존 06 config를
  덮어쓰지 않는다. 다른 worker HOME, NAS, repository 접근 차단은 유지한다.
- owner/socket/FIFO는 상시 유지하되 native app-server는 answer 실행 범위에서 생성하고
  종료를 확인한다. 계정 변경 후 이전 세션의 인증 캐시를 재사용하지 않는다. 대화 문맥은
  기존 owner가 매 turn 전달하므로 세션 재생성이 대화 삭제를 의미하지 않는다.
- 자료 검토/고객지원/풀이 비교/기존 문항 추출의 현행 06 전용 pool은 새 실행용 successor에서
  05로 이동한다. 900/3600초 지원 unit을 추가하고 추출은 기존 7200초 05 unit을 쓴다.
  기존 실행 계획은 drain 후 보존한다. 기존 06 unit도 과거 조회/복구용으로
  당장 제거하지 않는다. GPU INDEX의 고정 설치본·현재 실행은 변경하지 않는다.
  전환 application은 정확한 네 preset predecessor와 V3/V4 capacity predecessor를
  확인하고 기존 schema/record/draft/evaluation/release 함수를 사용한다. frozen fixed-host
  V4는 06을 계약으로 고정하므로 수정하지 않는다. 기존 generic capacity 1.0의 독립
  `slot05-interactive-support` policy를 만들고 네 preset의 capacity 참조만 연결한다.
  customer-support/legacy-extraction 두 pool은 같은 05의 물리 lease로 상호 배제된다.
  이 policy는 해당 네 작업 전용이며 기존 분석용 capacity나 fixed-host current는
  바꾸지 않는다. 실제 역할 pool의 변경은 slot06→slot05뿐이고 prompt/model/retrieval/timeout은
  그대로 복사한다. 명시적인 NON_LIVE 구조·호출 검증 보고서를 Artifact로 등록한 후 네
  preset을 같은 transaction에서 공개한다. 같은 successor 재실행은 기록을 재사용하고
  중간에 관리자가 현재판을 바꿨으면 덮어쓰지 않는다. 이 검사는 실제 답변 품질 평가가 아니다.
  generic 1.0의 분석 한도는 1이다. 새 legacy 추출은 다른 분석 작업이 있으면 기다릴 수
  있지만 기존 분석 preset의 한도는 바꾸지 않는다. frozen bootstrap의 재실행은 새 current와
  충돌하면 거부하며 successor를 과거판으로 되돌리지 않는다.

## 단순한 대안과 검증

서비스의 User만 06으로 바꾸면 ordinary worker·로그인 변경과 경합한다. 06을 DISABLED로
만들면 예약 목적과 관리자의 중지를 혼동한다. 전체 worker lease를 새 owner union으로
확장하는 방법은 턴 단위 공유에는 필요하지만 사용자가 선택한 전용 예약에는 불필요하다.

검증: 현재판 UI/편집 흐름, 예약 전환 멱등성, ordinary claim과 예약 경합, chat claim과
enrollment 경합, busy OBSERVE, 관리자 중지, 종료 불명확 시 claim 보존, 서로 다른 계정의
native session 재사용 금지, 05 자료 검토 unit·timeout·정책, 설치 wheel/격리 검사.
DB 변경·동시성은 disposable PostgreSQL에서 검증한다. 실제 활성화는 지원되는 배포 경계로
호환 API/platform/runner/Web을 반영한 뒤 새 채팅 1건의 응답/COMPLETED와 슬롯 표시를 확인한다.
서비스 READY나 source test PASS만으로 실제 답변 성공을 선언하지 않는다.

0077은 additive migration이다. 예약 활성화 전의 rollback은 이 새 head를 읽을 수 있는
검증된 fallback 설치본으로만 한다. 06 예약이나 새 실행 pin이 저장된 이후에는 옛 예약을
모르는 런타임으로 자동 복귀하지 않는다. 해당 경계를 중지하고 정확한 실패 지점을 복구한다.
