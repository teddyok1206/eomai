# 동일 비교의 실패 보존형 재실행

상태: 2026-10-12 UTC, 사용자 진행 승인 이후의 구현 설계. 실제 재실행 PASS가 아니다.

## 경계와 불변성

1. **책임:** 기존 API의 인증·현재 source 재인가, 비교 StartAdapter의 transaction,
   기존 Runner START_WORKFLOW와 Orchestrator의 작업/Artifact owner를 재사용한다.
   RETRY_STEP enum을 일반 workflow 복구 framework로 구현하지 않는다.
2. **정본:** 원 비교 selection, 원 FAILED Workflow/Step/Job, exact 실행 계획과 새
   실행의 정본 Artifact다. 실패 후보를 수동 수정·게시하지 않는다.
3. **identity:** released definition1.1.0은 max_step_attempts=1이고 결과 owner도 attempt1을
   요구한다. 같은 Workflow에 attempt2를 넣으면 이 의미를 바꾸므로 하지 않는다.
   같은 comparison request/profile/Graph/policy와 원 selection/key는 유지하며, 새 명시적
   retry operation의 고정 key에 연결된 **successor Workflow**가 자체 attempt1을 실행한다.
   원 key replay는 여전히 원 FAILED Workflow를 반환한다. 새 결과를 원 결과라고 표시하지 않는다.
4. **pointer:** request는 원 Workflow와 failed step/attempt 및 기존 bounded selection만
   담는다. actor/authority/preset/model/완전한 profile bytes는 받지 않는다. 실제 creator,
   현재 source 권한·policy·schema·hash·definition·role protocol과 부모 실행 계획의 control
   pins를 검증한다. successor의 plan ID/hash/time은 새 identity지만 control pins는 같아야 한다.
5. **access:** exact parent/step/plan/key lookup, 단일 successor membership, event append다.
   전체 corpus 재임베딩·풀이보고서 재생성·HWPX 생성은 하지 않는다.
6. **구조:** frozen retry DTO와 canonical hash, 기존 indexed Workflow/Step/Command,
   부모 row lock과 기존 event sequence를 사용한다. 새 queue/table/index/dependency는 없다.
7. **복잡도:** parent/step/key는 indexed lookup, event는 한 Workflow에 한정된 lookup이며
   기존 snapshot PREPARE/READ 비용은 그대로다. bounded selection은 40KiB 이하이며
   profile bytes의 materialization은 기존 공식 authorizing/start 경계에서만 수행한다.
8. **transaction:** 부모 FOR UPDATE 아래 latest failed step, active command/lease 없음,
   원 Job의 실제 FAILED·결과 commit 없음·retry lineage 없음·expected version을 확인한다.
   child creation/plan/START/event를 같은 transaction으로 commit한다. concurrent 다른 key도
   부모당 successor 최대1개이고, 같은 operation key replay는 같은 child만 반환한다.
9. **의존성:** router/owner HTTP → 작은 retry application → 기존 submission/start ports.
   PostgreSQL은 기존 start adapter 소유다. Catalog 현재 own-creator read가 source 권한을
   확인하고 Runner/Orchestrator도 실제 creator를 다시 인가한다. worker 권한은 바뀌지 않는다.
10. **실패/replay:** cached HTTP reply 전에 source 재인가한다. expected version은 최초
    creation에서만 검사하고 exact key replay는 이전 입력·부모/child lineage를 검사한다.
    timeout은 UNKNOWN이며 같은 retry key 조회/replay만 가능하다. 새 logical pair/key로
    우회하거나 failed history를 SUCCESS로 바꾸지 않는다. retry child의 재귀 재시도는 거부한다.
11. **더 단순한 대안:** FAILED→READY나 max_attempts 확대는 released 의미와 실패 이력을
    훼손한다. 일반 RETRY_STEP state machine은 이번 목적에 불필요하다. source를 확인하지
    않는 새 START POST는 임의 새 실행일 뿐 retry lineage/단일 successor를 보장하지 못한다.
    기존 start를 atomic retry leaf에서 재사용하는 것이 가장 작은 정합한 방법이다.

## 공개 계약과 검증

- POST `/api/v1/knowledge/inference-transfer/workflows/{workflow_id}/retries/v1.1`.
- JSON Schema2020-12 `item-inference-transfer-retry/1.0`을 먼저 정의한다.
- 기존 WORKFLOW_START/WORKFLOW_READ와 비교 source 권한을 사용한다. 권한 확대는 없다.
- If-Match와 operation idempotency key는 기존 API 계약을 사용한다. 응답은 기존
  CommandResult이며 successor Workflow/status URL을 명시한다.
- 이 retry POST만 parent owner read120 + 기존 PREPARE120/READ120×2 + margin30의
  고정 합성 budget510초를 쓴다. 원 비교 POST390·GET120·OBSERVE·auth TTL은 그대로다.
  DB/권한/lease 대기의 완료 보장이 아니며 timeout은 여전히 UNKNOWN이다.
- 원 비교 key replay2건, retry key replay1건, 성공한 successor와 둘째 원 Workflow의
  MEMBER_VERIFIED를 각각 확인한다. 모델 판단은 사람의 전이 효과 증명이 아니다.

필수 회귀: absent/stale/foreign parent/step, wrong selection/hash/pin, 현재 권한 철회 후
cached replay 거부, completed/cancelled/active parent·committed result·active lease 거부,
한 부모의 concurrent creation1개, 동일 operation replay, 재귀 retry 거부, 실패 기록 불변,
released definition/schema bytes 불변과 기존 V1.0/V1.1 읽기·제출 동작 유지다.

2026-10-12 사용자는 추가 승인 요청 없이 목표를 달성하도록 진행을 지시했다. 승인 범위의
implementation/deployment와 동일 pair 재실행은 진행하되 credentials·실제 권한·secret
경계를 우회하지 않는다. 처음의 same-Workflow proposal은 위 released1회 제약 때문에
명시적 successor execution으로 정정했다. 새로운 comparison이나 embedding 실험이 아니다.

## 실패 단계 조회의 최소 권한 (2026-10-12)

운영 API는 `workflow_step_runs`를 SELECT만 할 수 있다. terminal step에 불필요한
`FOR UPDATE`를 요청하면 PostgreSQL이 UPDATE 권한 부족으로 거부한다. 이를 고치려고
worker 소유 단계의 수정 권한을 API에 추가하지 않는다. successor membership와 생성은
기존 부모 Workflow row lock 아래 직렬화하고, 정확한 FAILED attempt1 단계는 일반 SELECT로
읽는다. 실제 FAILED Job의 기존 허용된 잠금, output/Artifact 없음, active command와 held
lease 없음, expected version 및 같은 transaction의 child/START/event 검증은 유지한다.
이는 모든 step 변경이 부모 잠금을 얻는다는 일반 보장이 아니다. 원래 terminal 비교와
released1회 계약을 확인하는 좁은 admission이며 기존 실패 기록을 수정하지 않는다.
회귀는 실제 API runtime 권한 matrix를 적용한 격리 DB에서 step SELECT 허용·UPDATE 거부를
먼저 확인하고 retry/replay·실패 이력 불변을 검증한다. 원래 parent-lock concurrency 회귀도
유지하며 운영 권한, released schema/definition 및 worker state-machine은 바꾸지 않는다.

## 소스·격리 DB 검증 — 2026-10-12 UTC

- 전체 관련 source/합성 console 회귀 **2,952 PASS /77.97초**. 추가 기존 API invocation/
  snapshot/metadata 회귀는 **160 PASS /27.88초**로 별도 실행했고 겹치는 수를 합산하지 않는다.
- 변경 Python 및 보호 console/합성 fixture21파일 strict mypy PASS. Ruff/format/diff 검사 PASS.
  console fixture의 dynamic module typing/lint 초기 오류는 정상 fixture 형태로 정렬했다.
- 새 retry 계약62tests 및 이전 invocation/generation 회귀165 PASS. 기존295개 source/package
  schema resources의 bytes/registry snapshot과 released definition/role bundle은 불변이다.
- marker-guarded disposable PostgreSQL에서 새 retry4cases와 기존 START/plan regression을
  함께 실행해 **25 PASS /5.25초**. same/different-key 경쟁에서 child1개, same-key replay,
  원 FAILED Workflow/Step/Job의 상태·입력·해시 보존과 stale version rollback을 확인했다.
  첫 새 DB 실행은3 PASS/1개 fixture 오류(`ApiError.code` 대신 `error_code`)였다. 실제 core는
  다른 key의 두 번째 retry를 올바르게 거부했다. fixture만 고친 후 위25개를 재실행했다.
- disposable state `/tmp/eom-api-testdb-20261012094142_d7655656`는 기존 manifest/DB/schema
  marker를 검증하고 개발 DB operator의 기존 접근 권한으로 준비·0051 migration cycle을
  수행했다. 생성/정리는 eom UID에서 기존 guard/script를 재사용한 임시 adapter로 실행했다.
  보호 환경의 root Python/source 실행은 하지 않았다. 이 테스트는 운영 DB/worker/model/NAS
  호출이 아니다. 준비한 DB/roles/private env는 검증 후 같은 guard로 정리했다.
- 기존 Starlette/httpx deprecated 경고 및 의도적 불량 model-copy의 Pydantic serializer
  경고가 있었다. 새로운 dependency를 추가하거나 경고를 교육/운영 성공으로 재해석하지 않는다.

이는 source/native persistence 검증이다. 실제 배포·인증 pair read·successor worker 실행·
두 MEMBER_VERIFIED·세 original/retry key replay와 최초 설계의 최종 LIVE 대조는 아직 남아 있다.
