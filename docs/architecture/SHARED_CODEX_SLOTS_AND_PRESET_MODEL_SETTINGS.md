# 공용 Codex 슬롯과 프리셋별 모델 설정

2026-11-12 UTC. 사용자 요구: ChatGPT만 전용 슬롯을 유지하고 다른 Codex 작업은 빈 자리를
탐색한다. 관리자 모델 설정은 기능별로 일관되게 제공하되 전역 모델 하나를 강제하지 않고,
각 프리셋의 역할별 모델·추론 깊이를 변경한다. 이 문서는 구현/검증 계획이며 운영 활성화가 아니다.

## 책임과 정본

- 실제 작업의 정본은 기존 Workflow·ResolvedExecutionPlan·WorkerLease다. 별도 queue,
  worker 간 통신, DB/NAS 접근을 만들지 않는다.
- 기능의 모델은 발행된 ExecutionPreset의 role/model_candidates, 자원 한도·슬롯 후보는
  capacity revision이다. Linux 사용자/격리 경계와 실행 역할을 분리한다. 슬롯01이 출제를
  위한 계정이라는 과거 기본값을 물리적 전용 자리로 해석하지 않는다.
- ChatGPT의 06번 예약은 기존 GeneralChatCapacity의 정본을 유지한다. 공용 후보는01–05다.
  채팅 모델·추론 깊이도 같은 관리자 화면에서 변경한다(사용자 확인).
  채팅 설정을 일반 Workflow 프리셋으로 위장하거나 일반 slot 정책으로 암묵 변환하지 않는다.
- 기존 released policy/schema와 실행 기록은 보존한다. 새 공용 capacity successor를 발행하고
  신규 실행에서 pin한다. 진행 중인 기존 plan·cohort·자료 학습 pin을 몰래 바꾸지 않는다.

## 공용 배정

일반 역할과 기능별 풀은 작업 목적/동시성 제한을 표현하며, 물리 슬롯은 공유한다.
새 capacity1.7은 일반 슬롯01–05와 authoring/image/review/item_management/support의
명시적 허용 관계를 갖는다. 06번은 포함할 수 없다. 호스트의 검증된 동시 실행 상한4,
슬롯당1, GPU1을 유지하며 이번 요구로 동시 실행 상한을5/6으로 올리지 않는다.

기존 `acquire_worker_lease`에서 host lock→capacity/pool→eligible slots 순서를 유지한다.
각 Job의 안정적인 시작 위치에서 슬롯 후보를 순환 탐색하고, enabled·현재 인증/계정에
귀속된 모델 검증·사용량·유효 claim·채팅 예약 조건을 만족하는 첫 빈 자리를 확보한다.
여러 Job이 같은 자리를 골라도 기존 unique held-slot constraint가 최종 중복을 막는다.
실행 가능한 자리가 없으면 기존 대기/재시도 계약을 유지하며 다른 모델로 바꾸지 않는다.

접근 패턴은 고정5개의 후보 탐색과 membership/uniqueness다. 순환 tuple과 set, 기존 indexed
lease/capability 조회면 충분하다. 후보 탐색 O(S), S≤5. 별도 cursor/cache/할당 테이블은 없다.
정본에 필요 없는 선택 결과를 다른 테이블에 복제하지 않고 Lease에 실제 slot을 기록한다.

## 고정 OS 경계와 실행 시간

공용 배정은 권한 공유가 아니다. 각 작업은 실제로 선택된 Linux 사용자·개인 workspace·
인증만 사용한다. root Codex 인증 복사, 다른 worker 파일/NAS 접근, 외부 LLM API는 금지다.
원래 역할별 프롬프트·결과 schema·model/effort는 plan에 pin하고 materializer가 전달한다.

기존 고정 systemd unit의900/1800/3600/7200초 계약을 약화시키지 않는다. 공용 실행도
정확한 timeout의 검증된 고정 unit을 선택해야 한다. 클라이언트 timeout만 늘리거나,
짧은 작업을7200초 unit에서 돌려 프로세스가 남게 하지 않는다. 기존 unit/hash 계약은
그대로 두고 공용 unit successor를 추가하며 실제 unit 설치/권한 검사 후 활성화한다.

## 프리셋별 모델 화면

`관리자 설정 → 모델·추론 설정`에서 현재 발행된 프리셋을 선택한다. 출제·검토뿐 아니라
자료 검토·교과서/자료 학습·풀이보고서·문의 등 support-only 프리셋도 표시한다.
프리셋의 역할·후보 순서와 개수(예: 기본/정밀 검토)는 보존하고 model/effort만 변경한다.
프롬프트·Graph 접근 정책·timeout·권한·Bundle pin을 같은 편집에서 바꾸지 않는다.

모델 목록은 현재 해당 슬롯 계정의 native catalog∩검증된 정책∩해당 풀에서 가능한 조합이다.
채팅 예약 슬롯은 일반 프리셋의 목록/검증에도 이용하지 않는다. 새 draft→기존 비모델
호환성 검사→명시적 release를 재사용한다. 프리셋A 변경은 B나 실행 중인 A를 바꾸지 않는다.
최신 모델로 자동 대체하거나 과거 실패를 새 모델의 성공으로 재해석하지 않는다.

## 소비 경로와 적용

단일 문항·변형은 현재 승인된 각 프리셋을 신규 plan에 고정한다. 자료 학습/배경 보고서처럼
설치된 정확한 revision을 쓰는 owner는 신규 실행에 적용할 설정 선택과 실행 중 pin을
구별해야 한다. UI에 저장됐다는 이유만으로 이미 떠 있는 resident owner가 바뀌었다고
보고하지 않는다. ChatGPT의 resident worker/model pin도 동일 원칙으로 검증한다.

### ChatGPT 설정의 좁은 독립 경계

채팅은 Workflow가 아니므로 가짜 ExecutionPreset을 만들지 않는다. 같은 관리자 설정
영역의 채팅 카드에서 모델·깊이를 고른다. 기존 슬롯06의 현재 계정에 검증된 모델 목록을
재사용한다. `general_chat_model_settings`의 단일 current pointer와 immutable revision에
작은 설정만 저장한다. 정본은 revision ID·내용 hash·model/effort이며 원문/인증은 없다.
접근은 singleton PK 조회 O(1), revision PK 조회 O(log R), 이력 공간 O(R)이다.

API의 기존 관리자 권한·재인증·CSRF·멱등 처리를 사용하고 변경 시 current row를 잠근 후
예상 버전을 비교한다. 채팅 owner는 설정을 읽기만 하며 worker는 DB에 접근하지 않는다.
채팅 worker policy6/dispatch6가 설정 revision/hash와 model/effort를 pin한다. private
owner의 request5로 prompt/runtime/격리를 유지하는 모델 변경만 admission 시 전달한다.
실행 중에는 변경하지 않고 다음 turn 전에 적용한다. 결과 복구는 저장된 원래 ticket을
조회하므로 설정이 바뀌어도 재생성하지 않는다. 설정이 없으면 설치 기본값을 보존한다.

worker의 기존 turn 실행 lock과 client의 짧은 admission lock을 사용한다. 답변 실행 동안
heartbeat를 막는 긴 lock을 만들지 않는다. 전체 owner 재시작이나 root 환경파일 덮어쓰기를
설정 UI의 정상 경로로 쓰는 것보다 이 작은 typed handoff가 기존 진행 중 답변을 보존한다.

## 실패·동시성·검증

공용 전환의 입력은 검토된 **현재 발행 revision**이며 과거 미발행 초안이 아니다.
운영에서 한 달 전의 다른 모델 초안이 전환을 막은 사례를 반영해, 같은 정책 hash의
전환 초안만 재사용한다. 무관한 초안은 수정·발행·삭제하지 않고 기존 lifecycle로
새 revision을 추가한다. 같은 전환에 일치하는 초안이 여러 개면 모호하므로 거부한다.
기존 논리 preset row lock과 advisory lock 안에서 O(D)로 비교하며, 다른 current가
된 경우의 거부·실행 pin·평가/발행 경계는 유지한다. 새 schema/DB/queue는 필요 없다.
초안을 모두 삭제하거나 편집내용을 현재값에 합치는 대안은 사용자 작업을 잃거나
미승인 모델을 발행하므로 사용하지 않는다.

lease와 역할/모델의 권한 불일치, dangling/revoked/hash mismatch는 명시적으로 거부한다.
계정 변경 후 이전 capability를 재사용하지 않는다. 관리자 변경은 기존 optimistic version과
멱등 receipt로 처리한다. 설치·실행이 불명확하면 새 작업을 중복 제출하지 않는다.

검사는 (1) protocol/schema와 과거 family 보존, (2) 모든 역할의 pool/CLI/timeout 매칭,
(3) busy/소진/인증/미지원 건너뛰기·06 제외, (4) disposable PostgreSQL 동시 claim·replay·
중단·rollback, (5) 프리셋별 독립 변경/기존 pin 보존, (6) 실제 브라우저의 모든 프리셋·역할
편집/검증/적용을 포함한다. 운영 DB를 pytest 대상으로 사용하지 않는다.

단순한 대안인 역할 필터 제거만으로는 systemd timeout/모델 검증/채팅 예약을 깨뜨린다.
새 범용 스케줄러 대신 기존 capacity/lease owner에 공용 successor를 추가하는 이유다.
