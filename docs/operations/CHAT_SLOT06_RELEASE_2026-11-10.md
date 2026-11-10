# ChatGPT의 기존 6번 슬롯 전환

2026-11-10 UTC. 사용자가 선택한 고정 전용 방식이다. 동적 빈 슬롯 배정이 아니다.

## 운영 반영

- 최초 API/platform/Catalog/runner/chat/Web: `0562b78373b64ee29e19d4da4cd110d406f10e46`.
  Source tree: `342d6fd65a4e6528dcfa4ff4f239623b56710abe`.
  슬롯 조회 회귀 수정은 `59597100a1ae95936c3934387834794f71f19ea0`,
  아래 부분 정책 갱신 회귀 수정 후 현재 호환 release는 `acb834acb99d77cce86b29f2142ae20718ef403a`이다.
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
최초 배포 보고에서는 새 Studio 메시지 확인을 PENDING으로 남겼다. 이후 사용자가
`채팅은 잘 되는데`라고 실제 응답 성공을 확인했다(`59597100` 반영 이후).
사용자 답변 확인과 서버 turn의 개별 COMPLETED 기록 대조는 구분한다.
아래 정책 복구에서 새 메시지나 기존 실패 대화 재실행은 요청하지 않았다.

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

## 후속 슬롯 목록 조회 오류 복구 — 07:36 UTC

사용자 보고 `webreq_1d4b4fec7dd4719b581fe0e8` 이후 같은 시간대의 `/codex-accounts`
실패를 확인했다. API가 새 capacity 전체 ORM 행을 조회했으나 실제 API DB 역할에는
해당 테이블 권한이 없었다. 이전 최소 권한 검사는 chat owner를 검증했고 API 역할은
놓쳤다. 권한 예외를 숨기거나 빈 슬롯 목록을 반환하지 않고 실제 read 경계를 수정했다.

- `ControlPlaneAdapter`는 공개 점유 상태 열만 한 번 조회한다. API role은 6개 제어
  metadata 열만 SELECT한다. claim token·대화·메시지 내용은 계속 접근 불가다.
- 같은 원인으로 실패할 control/auth 경계의 capacity 잠금도 전체 ORM 행 대신 singleton
  key만 잠근다. PostgreSQL 잠금에 필요한 key 열 UPDATE만 허용하며 예약·claim·heartbeat
  변경, INSERT/DELETE는 허용하지 않는다. 기존 잠금 순서와 state machine은 그대로다.
- source 회귀 70 PASS, 실제 제한 API 역할을 포함한 disposable DB 검사 2 PASS.
  임시 DB에서 6개 목록·control 잠금 성공 및 private 열/대화/상태 변경 거부를 검증했다.
- API/Web wheel·RECORD·설치 simulation, formatter/lint/type 검사 PASS.
  DB head `20261110_0077` 유지, 새 migration·모델 실행·인증 변경 0회.
- `59597100` API/platform/Catalog/runner/chat/Web 호환 배포 완료. QUERY provider pin을
  함께 반영했다. 기존 creative producer를 자연 drain 후 재개했으며 GPU INDEX와
  material 서비스의 PID/InvocationID 및 설정은 위 기준선 그대로다.
- 실제 설치본을 `eom-api` OS identity와 `eom_api_runtime` DB 역할로 실행하여
  **6개 슬롯 목록 조회와 06 capacity 잠금 PASS**. 단순 READY 응답과 구분한다.
  HTTPS ready도 PASS. 사용자 화면 확인은 요청한 상태이며 새 Studio 채팅 답변 확인과도 별개다.
- 최초 운영 검증 wrapper는 API UID가 protected env 파일을 직접 읽으려 해 거부됐다.
  파일 권한을 완화하지 않고 실제 서비스와 동일한 systemd EnvironmentFile 주입으로
  고친 뒤 성공했다. 이 실패는 검증 invocation 실패이며 운영 API 실패가 아니다.

운영 배포 기록: `/var/lib/eom-chat-slot06-release-20261110-59597100a1ae/`.
`prepared.json`, `installed.json`, `activated.json` 및 이전 설정 bytes를 보존한다.
기존 FAILED 대화·Job·검증 이력은 재실행/수정하지 않았다.

## 후속 1–5번 일부 기능 제한 복구

슬롯 목록 오류가 해결된 뒤 1–5번이 모두 `CAPABILITY_OBSERVATION_FAILED`인 것을
확인했다. 원인은 사용량이 아니라 단일 슬롯 검증 결과의 정책 반영이었다.
`render_compatibility_policy`가 scoped predecessor 전체를 제거하여, 06만 검증한
정책에는 기존 01–05의 `gpt-5.6-terra` scope가 남지 않았다.

- `acb834ac`은 검증한 슬롯의 기존 scoped 모델만 교체한다. 검증하지 않은 V3 슬롯은
  runtime/binding/assignment/slot/role이 정확히 같을 때만 보존한다. 재검증 실패,
  계정 변경, runtime 변경에는 과거 PASS를 재사용하지 않는다. 출제·검토 공통 pair 유지.
- source 회귀 211 PASS, formatter/lint/type, API/Web wheel/RECORD/설치 simulation PASS.
  전 슬롯 → 06 단독 검증 → 재전송, 실패 재검증, 계정 변경·역할 이동·실행 파일 변경을
  각각 검증했다. DB schema/state machine/worker protocol 변경은 없다.
- 보호된 직전 정책 `c4aee306…`과 현재 정책 `6c8e0edf…`, 정본 06 보고서
  `codexcompat_e4cf4ddeb6e04a35bb5c34c6b82f4d20`의 Artifact/hash를 대조했다.
  현재 계정 연결과 runtime이 동일함을 확인한 후, 공식 projection/atomic installer로
  `sha256:d5a537e9ee03bbe6c77daf73762366b655693376f48773dcc895daeb3d1e5b98`를 설치했다.
  01–05 scope는 직전 정책과 동일하고 06 scope는 현재 정상 채팅 정책과 동일하다.
- 새 모델 호출 0, 인증 변경 0, DB row 직접 보정 0, FAILED 이력 변경 0.
  이전 정책 bytes/복구 기록은 보존하며 공식 maintenance가 새 실제 관측을 기록한다.
- API/platform/Catalog/runner/chat/Web 호환 배포와 QUERY provider pin 갱신 완료.
  GPU INDEX PID `3493954`, material PID `1049221` 및 InvocationID는 그대로다.
  실제 API 역할의 슬롯 목록·control 잠금과 HTTPS ready PASS.

배포·정책 복구 기록은 `/var/lib/eom-chat-slot06-release-20261110-acb834acb99d/`의
`prepared.json`, `installed.json`, `activated.json`, `policy-recovery.json`이다.
최종 슬롯 상태는 아래 후속 실제 관측으로 확인한다.

08:03 UTC 실제 API 역할 조회에서 **01–06 모두 READY, reason_code=null**을 확인했다.
01–05의 새 auth/capability 관측은 기존 maintenance가 08:00:21–08:02:26 UTC에
순차 기록했다. 06은 GENERAL_CHAT/READY를 유지한다. 정책 재적용도 `REPLAYED`이며
새 모델 실행·상태 강제 변경·파일 내용 변경 없이 같은 SHA가 유지된다.
이 확인은 정책/인증/조회 복구 증거이며 새 문항 생성 canary를 수행했다는 뜻은 아니다.
