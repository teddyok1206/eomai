# 창작 문항 순차 풀이·Graph 등록 실행

2026-10-28 UTC. 사용자가 실제 슬롯 실행과 순차 Graph 등록을 승인했다. 이전의 실행 직전 준비 종료선과 구분한다.

## 실행 범위와 순서

- 입력은 완료된 import `extimport_d2019be75aa943636bfa8b7fb7f4a92e`의 정확한 최종본 연결 후보 1,053개다. 전체 관찰 1,297행을 완료 문항 수로 세지 않는다. 초안·반려·파일 연결 예외 14개를 자동 승격하지 않는다.
- 기존 표본 고유번호 `10310`의 준비된 Workflow부터 시작한다. 기존 support 슬롯 `05`, 동시 상한 1, 고정된 `gpt-5.6-terra/xhigh` 실행 계획을 사용한다. 다른 슬롯·Codex 인증·기출/교과서·GPU runtime pin은 바꾸지 않는다.
- 원본과 기출 첨부 영역을 분리한 구조화 추출·풀이 제안을 먼저 확인한다. 실제 결과 수락, 정본 Item/출처 연결, accepted 분석, Graph CAS, 창작 풀이보고서 successor의 역추적이 준비되기 전에는 전체를 실행하지 않는다.
- `NEEDS_DECISION`, 정답 불일치, 미해결 이미지나 source 철회는 해당 문항만 격리한다. 형식 통과를 과학적 정확성이나 Graph 게시 완료로 간주하지 않는다. 공개 가능한 풀이 단계와 검증 요약만 남긴다.

## 시작 경계의 설계 결정

1. 책임: Workflow application은 준비된 작업의 START 명령만 소유한다. 실제 인증과 현재 원본 인가는 기존 Identity/Catalog, 페이지 Artifact 검증은 Orchestrator를 사용한다.
2. 정본: 저장된 Workflow의 original request, READY step, resolved V27 plan과 Catalog 원본/페이지 Artifact다. CLI 파일은 기존 `ExternalItemLearningRoleSelection` 계약의 작은 선택값이며 권한이 아니다.
3. identity: Workflow·step·plan ID와 각각의 고정 hash를 비교한다. source revision과 Artifact revision을 경로나 고유번호로 대체하지 않는다.
4. 해석 검사: 원본과 현재 권한, immutable request/plan 및 페이지 file-set의 schema/media/member/hash/lifecycle을 기존 resolver로 재검증한다. stale이면 latest로 바꾸지 않는다.
5. 접근: Workflow/step/plan PK 조회, Workflow별 START command indexed lookup과 원자적 단일 claim이다.
6. 구조: 기존 Workflow row lock, command unique key, 기존 FIFO command queue·worker lease를 재사용한다. 새 queue/table/index/worker protocol은 없다.
7. 규모: 시작은 고정 수 indexed lookup과 한 문항의 bounded 페이지 검증이다. 후보 순회는 기존 U keyset projection의 25개 이하 페이지를 재사용하고 전체 원본을 매번 복사하지 않는다.
8. 경합: 한 caller root transaction에서 Workflow lock→source/page 검증→기존 START 확인/생성→늦은 재인가를 수행한다. 긴 모델 실행 동안 DB transaction을 유지하지 않는다.
9. 의존 방향: CLI 인증 adapter→Workflow 시작 application→기존 계약/port. Catalog adapter가 source 권한을 구현하고 Orchestrator가 파일·NAS commit을 소유한다. worker 간 통신이나 worker의 DB/NAS 쓰기는 없다.
10. 실패/재전송: START identity는 고정 selection과 실제 owner에서 도출한다. 중복 시작은 원래 명령을 반환하며 FAILED 이력을 성공으로 바꾸거나 새 요청으로 우회하지 않는다. 시작 후 처리 여부가 불명확하면 원래 명령을 조회한다.
11. 배제한 대안: DB에 명령을 직접 INSERT하거나 일반 CLI의 합성 human actor로 시작하면 실제 원본/권한 경계를 건너뛰므로 사용하지 않는다. 준비 단계에 `--start` boolean을 붙이지 않고 별도 시작 use case를 둔다.

## 현재 상태

시작 application과 검증을 연결하는 중이다. 아직 이 문서만으로 실제 슬롯 실행·정본 수락·Graph 게시를 완료했다고 주장하지 않는다. 표본부터 실제 불변 output/receipt로 기록한 후 bounded 순차 실행을 연다. 진행률은 원본 준비·실행·제안 수락·정본 등록·Graph 게시·보고서·격리로 나누고 정기 확인은 30분 간격으로 제한한다.
