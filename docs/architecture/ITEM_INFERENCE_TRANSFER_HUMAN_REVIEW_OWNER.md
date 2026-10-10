# 착상 전이 사람 평가: 작은 owner 연결

2026-10-10. F5의 기존 사람 label 계약과 순수 지표 함수를 실제 검토 묶음·인가된
정본 기록에 연결한다. 새 평가 GUI, DB, queue, worker 호출, 문항 승인 기능은 만들지 않는다.
모델 비교 가설과 사람이 입력한 평가는 별개다. 실제 사람 label이 없으면
`HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`를 유지한다.

1. **책임/경계:** owner-local `eomctl control-plane inference-transfer`가 작은 typed
   명령을 받는다. Orchestrator application leaf가 공식 API session의 현재 principal,
   exact 비교 결과와 현재 source 권한을 확인하고 기존 control Artifact owner를 호출한다.
   worker는 이 저장 경로에 접근하지 않는다. 초기 범위는 승인된 guiadmin 실험이다.
2. **정본:** 기존 승인 source/report/profile와 `MEMBER_VERIFIED` 비교 Artifact가 근거다.
   사람용 bundle은 이 두 문항의 공식 snapshot READ 결과와 모델 가설을 구분한 bounded
   materialization이다. label 기록은 bundle pointer와 기존 `HumanTransferEvaluation`만
   참조하며 문항·풀이·이미지 bytes를 다시 복제하지 않는다.
3. **identity/revision:** bundle 논리 ID·revision·canonical hash, 평가 논리 ID·revision·
   canonical hash, 게시 Artifact ID·revision·raw member SHA를 각각 구분한다. bundle
   request ID/revision/created_at은 고정된 요청 metadata이지 권한이 아니다. 평가의
   evaluated_at은 사람이 제출한 UTC 판단 시각이고, 실제 게시 UTC는 owner clock으로 만든
   Job/manifest다. replay에서 최초 게시 UTC를 덮지 않는다.
4. **resolution:** additive JSON Schema 2020-12와 frozen DTO를 먼저 정의한다. bundle은
   exact selection·workflow·Graph/policy·A→B profile·rubric·source closure를 검증한다.
   every prepare/publish/read/replay에서 current official principal과 exact pair/source를
   재인가한다. fresh ADMIN(15분), 실제 session expiry/identity, 기존 source read permissions를
   유지한다. label reviewer는 반드시 현재 operator와 같고 bundle도 같은 operator의 것이다.
   model/caller-supplied role·actor·hash·Artifact pointer는 authority가 아니다.
5. **access pattern:** exact workflow/pointer lookup, 두 source의 keyed lookup, append-only
   bundle/평가 publication과 exact replay다. whole corpus를 새로 평가하거나 N+1 검색하지 않는다.
6. **구조/index:** 기존 공식 snapshot PREPARE/READ 및 comparison read와 typed tuple/map을
   재사용한다. 기존 publisher Job idempotency unique/advisory lock이 게시를 직렬화한다.
   새 DB/index와 persistent permission cache는 없다. bundle/record 각각 최대 2 MiB이며
   큰 source는 거부하고 잘라서 성공시키지 않는다.
7. **복잡도/규모:** 한 bundle은 정확히 두 문항, record는 pointer+bounded label이다.
   기존 query-free PREPARE 비용 외 검증은 두 문항의 text/refs에 선형이고 저장은 bounded
   bytes에 선형이다. 이 기능은 임베딩 CPU closure를 변경하지 않는다.
8. **transaction/concurrency:** source 재인가는 공식 Catalog read transaction이다.
   publication은 기존 Orchestrator `ControlArtifactPublisher.publish_bytes` 경계다.
   이 둘을 분산 atomic transaction이라 부르지 않는다. 게시 직전 principal/source를
   다시 확인하며 저장된 bundle/hash를 permission cache로 쓰지 않는다.
9. **dependency/ownership:** pure contracts는 infrastructure를 import하지 않는다.
   human application에는 principal/comparison/snapshot/artifact/publisher port를 주입한다.
   실제 composition은 기존 fixed HTTP session와 Orchestrator Artifact resolution/publisher를
   재사용한다. CLI는 bounded input 검증·composition·결과 표시만 한다. 새 dependency는 없다.
10. **failure/retry:** stale/revoked/hash/schema/media/actor/pair/rubric mismatch는 명시적
    실패다. 동일 operator·logical revision에서 다른 payload는 기존 idempotency conflict다.
    timeout 뒤 다른 ID로 재게시하지 않는다. 같은 typed request/label과 key로만 supported
    replay하며, 실패 history를 성공으로 재해석하지 않는다. bundle request의 fixed timestamp와
    사람 판단 시각은 재시도에서 바꾸지 않는다. generic logs/Slack에 내용·credential을 내보내지 않는다.
11. **단순한 대안/검증:** JSON 파일과 pure metric만으로는 현재 권한·reviewer·canonical
    publication을 보장하지 못한다. 기존 owner에 작은 leaf를 추가하는 것이 충분하며 새
    endpoint/평가 framework는 불필요하다. fixture tests는 current principal/source revoke,
    session swap, forged reviewer, stale pair/rubric, exact read/hash, duplicate/conflicting replay,
    encoded bound, frozen DTO bypass와 unchanged predecessor schema를 검증한다. 실제 pair와
    사람 label이 없는 source PASS를 live human 품질 PASS로 확대하지 않는다.

## Additive 값과 실행

- `InferenceTransferHumanBundleCommand`: bundle ID/revision/created_at + exact pair selection +
  workflow ID. CLI가 제출 metadata를 고정하고 source commit은 설치 identity에서 가져온다.
- `InferenceTransferHumanReviewBundle`: 위 command, 실제 prepared_by operator,
  canonical comparison read, A/B 순서의 snapshot record 두 개, canonical bundle SHA.
  원문 text/풀이 근거는 공식 read가 제공한 범위뿐이며 PDF/PNG 육안 확인을 주장하지 않는다.
- `InferenceTransferHumanRecordCommand`: exact bundle Artifact member pointer + 기존
  `HumanTransferEvaluation`. 사람의 label/reason/where_helped를 자동으로 채우지 않는다.
- `InferenceTransferHumanReviewRecord`: 같은 pointer + evaluation + canonical record SHA.
  pair/rubric/reviewer/time/hash를 bundle 및 실제 principal과 대조한 후에만 게시한다.
- owner `publish_bundle`, `publish_evaluation`, `read_bundle`, `read_evaluation`과 CLI
  `human-bundle`, `human-evaluate`, `human-read`를 연결한다. CLI는 명시적인 TTY 로그인 또는
  기존 protected bearer FD를 사용하고 password/token을 argument·file·출력에 남기지 않는다.

bundle/record는 별도 schema의 `result.json` 한 member로 게시한다. Artifact member의 schema,
media, raw SHA, 승인 lifecycle 및 bounded bytes는 기존 Orchestrator reader가 검증한다.
사람 label이 `UNDETERMINED`이거나 일부 pair만 평가됐으면 기존 순수 지표의 judged-pool
범위와 PARTIAL/NOT_EVALUATED 의미를 그대로 유지한다. 미래 팀장 GUI/권한 확대는 별도
제품 요구로 판단하며 이번 구현에서 활성화하지 않는다.

## Source 검증 checkpoint

root 집중 회귀 13개 파일의 **480 tests PASS**. 신규 계약 71개·owner 94개·CLI 25개는
이 480개에 포함되며 별도로 합산하지 않는다. 기존 사람 지표/기출 계약/snapshot/HTTP/
CLI와 original design hash·29 predecessor workflow bundle·wheel inventory 회귀를 포함한다.
strict mypy 9개 source/test 파일, Ruff·format 10개 파일, shell syntax와 diff 검사 PASS.
CLI 테스트의 타입 annotation 수정 뒤 해당 25개도 재실행 PASS이며 480개에 추가 합산하지 않는다.

교차 검토에서 기존 publisher의 `control_` Artifact type 요구와 release schema inventory
누락을 발견해 보완했다. human-read는 알려진 schema뿐 아니라 `result.json`과
`application/json`을 입력 단계에서 확인한다. malformed input, current actor/session/role/
permission 회수, source/hash/Graph/policy 변경, exact 재게시/충돌, 게시 직후 권한 회수,
게시 outcome 불명 시 무자동 재제출, owner UTC와 제출된 판단 시각 분리를 검증했다.

이는 source/fake-port 검증이며 실제 DB/NAS 게시나 사람 평가 증거가 아니다. 새로운
migration·모델/GPU/worker 호출은 없다. 기존 `7383d1c6` 운영 설치와 새 human leaf 후보는
구분한다. 실제 bounded corpus/pair 실행과 이 leaf의 설치/실제 label 기록은 후속 gate다.
