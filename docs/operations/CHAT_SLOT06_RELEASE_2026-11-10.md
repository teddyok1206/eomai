# ChatGPT의 기존 6번 슬롯 전환

2026-11-10 UTC. 사용자가 선택한 고정 전용 방식이다. 동적 빈 슬롯 배정이 아니다.

## 운영 반영

- API/platform/Catalog/runner/chat/Web: `0562b78373b64ee29e19d4da4cd110d406f10e46`.
  Source tree: `342d6fd65a4e6528dcfa4ff4f239623b56710abe`.
- DB: additive migration `20261110_0077`. 공식 migration/권한 callbacks 통과.
- `general_chat_capacity.worker_slot_id=06` 공식 예약 완료. 일반 claim은 06을 제외한다.
- 채팅은 기존 06 HOME/auth를 사용한다. 인증 복사·비밀번호 변경·외부 API 추가 없음.
- 새 자료 검토·고객지원·풀이 비교·legacy 추출은 공식 preset successor에서 05를 사용한다.
  과거 실행 pin과 frozen V3/V4 capacity는 보존한다.
- 실행 설정 화면은 현재 released revision과 편집 중 draft만 표시한다.
  과거 revision/evaluation/실행 기록을 물리 삭제하지 않았다.
- GPU INDEX PID `3493954`, InvocationID `62cd90e93dfa4b7992fd120681214e40` 유지.
  material PID `1049221`, InvocationID `f1ddf3d2f12543f09ca83d081512ddec` 유지.
  이 사실은 실행 보존 증거이지 전체 임베딩 완료나 처리량 증거가 아니다.
- 기존 창작 producer는 작업이 없는 시점에 drain 후 재개했다. 네 일반 runner와
  maintenance/auth broker/API/Web/HWPX/QUERY/chat 서비스가 active임을 확인했다.
- HTTPS `/studio/api/v1/health/ready`와 API ready 통과. HTTPS의 `app.js`,
  `execution-preset-editor.js`, `general-chat.js` bytes가 최종 소스와 일치한다.

## 실제 실행 검증과 남은 확인

06의 현재 계정에서 `gpt-6.1-sol` / `medium` 공식 scoped 검증을 한 번 실행하여 PASS.
CLI `0.162.1`, model call 1회, 이전 실패 대화 재실행 0회.

- 검증 run: `codexcompat_e4cf4ddeb6e04a35bb5c34c6b82f4d20`.
- 결과: `artifact_8130d063ec614e09898f9e9c88848cda` /
  `rev_b3f2e38275be41689ad8f4ff88830007` / `report.json`.
- 결과 SHA: `d185e96b488f2e4a6145598ec78cad2a38031785751ccd4d761c16f5e6d433e5`.
- 공식 scoped-policy 설치 SHA: `6c8e0edfda82989152a1e40c6fe0a66316e7b1b7615e7ea6f97f62d28774e373`.
- 실제 CLI와 현재 assignment를 재확인한 공식 LOCAL_OBSERVATION snapshot:
  `capsnap_2b616c30e7e8440b90fe3324416bf55c`. 운영자 계정 가장이나 auth TTL 연장 없음.

모델 probe PASS는 Studio 채팅 성공과 구분한다.
**새 Studio 메시지의 실제 답변·COMPLETED 및 화면 확인은 현재 PENDING.**
사용자에게 새 대화의 짧은 질문 한 번을 요청했다. 기존 실패 대화는 그대로 남는다.

## 배포 중 확인하여 수정한 문제

1. API의 새 assignment DTO 세 필드와 생성 OpenAPI가 달랐다. 문서를 재생성해
   source/설치 wheel/OpenAPI 일치를 검증했다.
2. 최소 권한 owner의 EXISTS가 `SELECT *`를 생성했다. `SELECT 1`로 수정했으며
   DB 권한을 넓히지 않았다. 실제 제한 계정 검사 14 PASS.
3. 11월 4일 지원 Job은 RUNNING이지만 정확히 연결된 부모 Workflow와 step은 FAILED,
   명령·lease·물리 worker는 없었다. 예약의 raw-state 검사는 기존 maintenance보다
   지나치게 넓었다. 기존 실행 가능성 판정을 `job_execution_queries`로 추출하여 재사용했다.
   정확한 terminal 부모/step와 명령 부재가 입증될 때만 과거 기록으로 구분한다.
   활성 lease, 실행 중 부모/step, validation/commit 단계는 계속 차단한다.
   해당 Job·FAILED·이벤트 이력은 수정하지 않았다.

최초 설치 `67791407`에서 0077·권한·05 unit·06 namespace를 준비했다. 마지막 수정
`0562b783`은 같은 정지 창에서 새 wheel로 반영했다. 이때 migration·인증·모델 검증을
반복하지 않고 API provider/QUERY/Catalog/chat source pin을 호환 조합으로 갱신했다.

## 검증 범위

서로 겹치는 검사 수는 합산하지 않는다.

| 경계 | 결과 |
| --- | --- |
| native/chat/worker 회귀 | 1,016 PASS |
| 마지막 handoff/install 집중 검사 | 191 PASS |
| reservation/control/auth source | 212 PASS |
| 최종 chat disposable DB | 72 PASS |
| 최소 권한 실제 DB 역할 | 14 PASS |
| 4개 preset 소비 경로 | 106 PASS 및 disposable 동시성/재전송 |
| API/Web assignment | 291 PASS |
| 현재판 preset UI | 97 PASS, Chromium 포함 |
| 최종 sealed-history 수정 | source 71 PASS, disposable DB 11 PASS |
| API/Web 최종 wheel/RECORD/설치 simulation | PASS |
| owner/06 실제 OS namespace 격리 | PASS, native call 0 |
| formatter/lint/type/dependency/context | 변경 범위 PASS |

0077 upgrade/downgrade/upgrade는 disposable DB에서만 확인했다. 운영 downgrade 없음.
격리 검사는 최초 host 시작 전에 수행했다. 이후 수정은 실행 가능성 read predicate이며
unit·권한·파일 경계를 변경하지 않아 동일 namespace 증거를 재사용한다.

## 운영/복구 경계

채팅 owner/socket은 상시 유지하고 native app-server는 답변마다 생성·종료한다.
계정 변경 후 이전 세션의 인증 캐시를 재사용하지 않는다. 실제 active chat claim은
로그인 변경·모델 probe와 배제되며 사용량 읽기 관측은 허용한다.

새 capacity: `capacityrev_b09ec1cf703b3f6708bba2b5ddb9466b`.
네 successor와 이전 핀은 공식 control Artifact/DB 이력으로 추적한다.
새 legacy 추출은 generic 1.0의 analysis 한도 1을 따르므로 다른 분석 작업이 있으면
기다릴 수 있다. 기존 분석 preset의 한도를 바꾸지는 않았다.

예약 전용 fallback `01121ac58f07929afb2324ef350296867301eb30`을 준비했지만 사용하지 않았다.
**지금은 06 예약이 활성화됐으므로 이 fallback이나 예약을 모르는 구 runtime으로
자동 복귀하면 안 된다.** 실패한 경계만 멈추고 후속 호환 릴리스로 복구한다.
예약 전 fallback에도 공식 owner ACL reconcile와 정확한 handoff ownership receipt 복원이
필요하며, migration downgrade나 재귀적인 HOME 변경은 복구 방법이 아니다.

설계: [6번 예약 경계](../architecture/GENERAL_CHAT_SLOT06_RESERVATION.md).
