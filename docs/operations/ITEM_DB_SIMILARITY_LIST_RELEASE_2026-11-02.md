# DB 유사도 목록·기록·결과 재열람 운영 체크포인트

2026-11-02 13:13 UTC 관측. **호환 배포 완료, 실제 신규 목록 검색 검증은 PENDING**이다.
서비스 READY와 합성 브라우저 검사를 실제 검색 성공의 대체 증거로 쓰지 않는다.

## 범위

사용자가 기존 단일 검색의 결과 문항을 DB 조회에서 열었다고 확인한 상태를 보존하고,
목록1–32개·문항마다 상위1–64개·최근 사용자별 검색·선택 기준 미리보기를 추가했다.
완료 결과 확인은 원 selector의 읽기이며 새 계산을 시작하는 버튼과 분리한다.
검색 기록은 활성화 이후 실제 접수부터 저장한다. 과거 검색을 신규 기록으로 위장하지 않는다.

[설계와 최종 설명 근거](../architecture/ITEM_DB_SIMILARITY_BATCH_HISTORY.md).

## 실제 설치 묶음

| 구성요소 | 고정 source |
| --- | --- |
| API / shared platform / API contracts | `217d28bf8c918f501fcf6396066a2abcf1579e15` |
| Catalog 별도 설치본 | `6ad2e4c08332be0a6276a4d879f9ab429f27a22b` |
| Web | `1dc35993fd557fba89a455a6ce2aeef9aefc6fc2` |
| QUERY 수치 owner | `7ba7524da3d7fd8dc86892b1654af89031380641`, 코드 변경 없음 |
| QUERY root controller | `0d7dbf22afa3ff6a36c3d350c15b74babe7fd4ba` |
| INDEX root controller / 수치 환경 | `a70cd43415598db500763ccf329cd762177cbe3c` / 기존 고정 환경 보존 |
| INDEX | `aac484339651b53f9bd5e2d29e1215a052754f08`, process `3284474` 유지 |
| DB head | `20261102_0069` |

Catalog는 이미 운영되던 `6589d16d`의 조회 개선을 보존한 successor다. API 소스 기준의 이전
Catalog reader로 되돌리지 않았다. 패키지 비교에서 삭제0, 새 V2 계약/스키마2개와 관련
validation/dispatch/selection만 변경됐다. Catalog의 기존 API 계약 bytes는 동일하다.

API provider code-member pin과 QUERY cohost/private 관계는 새 API 설치본의 정확한 bytes로
갱신했다. QUERY 모델·controller·환경·device routing, INDEX 설정·PID와 기존 실행은 보존했다.
API 서비스 정의와 인증 시간·비밀값도 변경하지 않았다. Web 재시작으로 브라우저 재로그인은 필요하다.

## 검증된 것

- schema-first V2 목록과 순서·중복·범위·실제 actor 검증, 원 V1 계약 보존.
- focused154개, 이후 OpenAPI/header/access-capture 연동45개 PASS. 범위가 겹치므로 합산하지 않는다.
- disposable PostgreSQL6개 PASS: 같은 key 동시4접수, 원 intent 불변, owner 분리, keyset,
  최초 pin 유지와 늦은 PENDING의 완료 역행 방지. 제한 runtime role의 원 input/owner/key UPDATE 거부.
- migration68↔69 임시 DB 왕복, 실제 운영은 독립 보호된 release-operator1.16으로69 적용·확인 PASS.
  공식 API runtime role bootstrap도 통과했다. 운영 DB에는 pytest를 실행하지 않았다.
- changed runtime14모듈 strict mypy, 후속 route/BFF3모듈 mypy·Ruff/format PASS.
- 실제 Chromium에 저장소 화면과 합성 API를 연결한 목록·preview 영역·기록·결과 이동·A/B 경합 PASS.
  이는 실제 로그인·실제 PDF 픽셀 검증이 아니다.
- API/Catalog/Web wheel/RECORD·독립 설치 검증 PASS. API 첫 빌드의 OpenAPI snapshot 미갱신은
  운영 변경 전에 발견·수정했으며 실패 이력을 보존했다. 새 호환 묶음은 다시 빌드해 PASS했다.
- 배포 뒤 실제 `eom-catalog-manager` UID에서 설치된 V2 schema hash와 dispatcher를 검증했다.
  서비스 미제공 합성 요청은 정확한 V2 `UNAVAILABLE`로 반환했다. DB/모델 실행0이며 실제
  사용자 권한으로 source를 해석하거나 검색한 증거는 아니므로 아래 GUI 검증은 여전히 남는다.

## 운영 보존과 현재 미완료

13:13 UTC GPU 공통 입력은356/1003 bindings, CPU는328/1003이다. 장치별 분모를 합산하지 않는다.
GPU가 배포 전348에서356으로 진행했고 INDEX PID·설정은 유지됐다. 구 벡터는 삭제하지 않았다.

창작 풀이보고서 서비스는 이 체크포인트 이전부터 PID0 상태이며, 이번 검색 기능 배포가 이를
재개했다거나 여러 슬롯이 실행 중이라고 보고하지 않는다. 별도 장애 복구를 본 기능 완료로 대체하지 않는다.

다음 실제 검증은 한 로그인 브라우저로 단일 검색, 이미 준비된 결과 문항을 포함한2문항 검색,
top_k3/5, 원문 미리보기, 결과→DB, 최근 기록 재열람과 새로고침 후 복원이다.
같은 완료 요청의 재조회 전후 native/Workflow 개수와 output hash도 대조한다.
GPU 공유 배치·모델 재사용 경로의 실제 장치·호출 수·소요시간을 따로 확인한 뒤 완료 판정한다.

## 증거 위치

- protected release/admission: `/var/lib/eom-db-search-history69-20261102/` 및
  `/var/lib/eom-release-operator-stage.db-search-history69-hi9cf6zk/`.
- build-only logs: `/tmp/eom-db-list-20261102.api-build-v2`, `.catalog-build`, `.web-build-v2`.
- source tests: `/tmp/eom-db-list-final-20261102.tests`,
  `/tmp/eom-db-list-20261102.check-key-tests`, `.mypy-followup`.
- disposable tests: `/tmp/eom-db-search-list-20261102.integration-tests-v4`.
- release metadata: `/tmp/eom-db-list-post-release.metadata` (읽기 전용·mutation0, 내용/인증 미수집).

임시 로그는 장기 보관본이 아니며 Git에 복사하지 않는다. 정본 문항·보고서·기존 실패와 모델
산출물은 원래 저장소/Artifact 경계를 그대로 유지한다. 최종 실제 검증 결과는 이 문서에 후속 기록한다.

## 실제 단일 검색 체크포인트 — 2026-11-02 16:38 UTC

검증 터미널의 인증 실패를 반복하지 않고, 사용자가 이미 정상 로그인한 실제 Studio에서
검색을 시작했다. 비밀번호 재설정·잠금 해제·계정 가장은 하지 않았다. 실패 로그인은 보존했다.

- 새 목록 검색 `dbsearch_db664acd6a0af51a3561b605f3c3f853`, 실제 입력1개/top_k3.
- Workflow `workflow_980e0bc97b7742bdae1c6e6419de2c1d`, COMPLETED.
- 원 native launch `job_e2591229f1b44403893859441512ed18`, SUCCEEDED.
- 원 output SHA `sha256:7640cab1b905ea289ff4c66c102d93028a93e306478204080634f26838ff614e`.
- 사용자가 결과3개 표시, 결과→조회, 완료한 ‘결과 확인’이 정상이라고 직접 확인했다.
- 확인 전/후 공식 coordinator read에서 정확한 key의 Workflow1/native launch1과 동일 output SHA를
  확인했다. 완료 확인을 새 임베딩 계산으로 대신하지 않았다. 새 검색·실패 재해석0.

실제 routing receipt는 `GPU_BUSY_CPU_FALLBACK`이었다. GPU가 시험에 사용됐다고 주장하지
않는다. 원 GPU INDEX를 멈추거나 CPU/GPU 벡터 공간을 섞지 않았다.

관측 시간은 접수16:26:31 → Workflow 완료16:31:28 → 화면용 결과 조회 응답 종료16:34:05 UTC다.
공식 CPU unit은16:29:37–16:30:29에 실행됐다(약52초, CPU사용53.2초). GET 결과 읽기는
142.929초, 전체 약7분34초다. 이 차이를 모두 모델 연산 시간이라고 설명하지 않는다.
실제 결과 읽기는 원 vector/index와 source/policy를 검증·조합하며, 같은 화면의 완료 확인은
이미 표시한 목록을 유지한다. 기록 재열람의 canonical GET은 별도 검증 시간이 든다.

원 기준 문항의 작은 PDF 미리보기에서 공통 `DENY`/`frame-ancestors 'none'` 헤더가 내부
iframe도 막는 문제를 회귀 테스트로 확인했다. 인증된 정확한 preview.pdf의200 PDF 응답만
SAMEORIGIN/`'self'`로 허용하는 Web 수정과53개 회귀·타입/린트 검증을 완료했다.
로그인/관리/오류/다른 다운로드는 계속 DENY다. 이 후속 Web 수정은 이 문단 기록 시점에
**운영 미배포**이며, 진행 중 사용자 검증·GPU 작업을 중단하지 않는 시점에 반영한다.

다음은 실제2문항/top_k5 및 각 기준 결과·기록 재열람, GPU 묶음 사용 여부와 같은 결과 재조회다.
단일 성공을 이 남은 범위의 PASS로 확대하지 않는다.

## 두 문항 준비 오류 수정 — 2026-11-02 16:52 UTC

사용자의2문항/top_k5 요청은 원 자료 캡처 전에 `ITEM_DB_SIMILARITY_UNAVAILABLE`가 됐다.
이는 보고서 누락을 확인한 결과가 아니다. 실제 저장 intent의2개 revision은 서로 다르고,
Graph 소속 조회도 성공했으나 선택 순서는 내부 canonical set의 정렬 순서와 달랐다.

`SelectedEmbeddingSources`는 원래부터 정렬·중복 제거된 집합을 요구한다. 새 GUI의 순서 있는
목록을 그대로 전달한 구현 결함을 역순2문항 테스트로 재현했다. 캡처에만 정렬된 revision tuple을
전달하고, 결과 keyed map·query/anchors에는 원 사용자 순서를 그대로 유지하도록 수정했다.
기존 집합 계약을 느슨하게 하거나 Graph/보고서를 새로 등록해서 우회하지 않았다.

- main 수정 `4c0305c1`, 서비스 successor `89dab6fa8ea8f0bb162d0984e63d7cad7cb3bd56`.
- focused44 PASS, strict mypy/Ruff/format PASS. 정상순서·역순서 모두 query 순서 보존을 확인했다.
- Catalog만 새 검증 wheel/RECORD 설치본으로 교체했다. API/Web/QUERY/INDEX PID와 모든 해당
  runtime·인증 설정은 보존했다. source protocol·DB migration 변경0, 사용자 로그아웃0.
- 일반 오류는 기존의 비밀값 없는 failure-site observer로 진단하고 내용/예외 문구는 기록하지 않는다.
- 실제2문항 성공은 아직 PENDING이다. 새 identity를 만들지 않고 사용자가 현재 요청의
  ‘결과 확인’을 눌러 같은 의도와 선택을 이어가는 경계로 검증한다.

## 실제 두 문항 GPU 실패와 결과 인계 수정 — 2026-11-02 17:24 UTC

위 준비 오류를 수정한 뒤 동일 요청 `dbsearch_4fe4b8b955f30ad17e46ff0d6d74decf`가 실제
CUDA로 진행됐다. 두 child는 하나의 GPU batch에서 모델을 공유했지만 **최종 성공은 아니다**.
원 parent의 SUCCEEDED는 계획 binding만 뜻한다.

- 원 allocation `embeddingallocation_75e75cff15fe4eff84bec02c7403a134`의 native는
  `RESULT_READY`를 보냈다. 최종 source RPC를 기다리는 중17:00:02 UTC에 `14/ALRM`으로
  종료됐고 root의 최종 ACK 전송은 BrokenPipe로 실패했다. OOM/비밀번호 오류로 분류하지 않는다.
- 검색 기록은17:04에 FAILED가 됐다. 원 두 Workflow의 RUNNING/ALLOCATION 잔여는 실제
  GPU 실행 중이라는 뜻이 아니다. native/controller 종료·retirement 기록을 보존한다.
  FAILED를 성공으로 바꾸거나 같은 allocation을 다시 실행하지 않았다.
- main `24133d2e`는 ACK 전 중복된 전체 source 순회를 제거하고, 원래 있던 **retirement 후
  모든 source의 현재 권한/정본 검증**으로 공개를 계속 차단한다. ACK는 검증한 로컬 bytes의
  수령 확인일 뿐 publication 승인이 아니라는 기존 wire 의미를 지킨다. hash/FD/원 unit/lease,
  계산 전·중 source check, 실제 terminal/retirement 및 상위 commit fence는 유지한다.
- SIGALRM 시간 자체·GPU 모델·수치 prefix·저장 vector·DB schema 변경0이다. 실제 worker가
  ACK를 기다리는 중 불필요한 source roundtrip을 제거하는 root 담당 변경이다.
- root controller는 기존A70의 작은 successor `0d7dbf22`로 별도 설치했다. wheel 대조에서 추가는
  목적별 INDEX controller 선택 모듈1개, 변경은 controller/bootstrap/RECORD뿐이며 API contracts는
  byte 동일하다. 진행 중 INDEX는 원A70 controller로 넘기고 QUERY만 새 controller를 사용한다.
  INDEX config/PID3284474/InvocationID/수치 worker bytes는 변하지 않았다.
- 관련 source 집중124 PASS, 최종 owner revoke14 PASS, 호환 branch94 PASS·mypy3·Ruff/format·
  build/RECORD PASS. 실행 범위가 겹치므로 합산하지 않는다. ACK 뒤 source가 취소되면
  ROOT_COMPLETED도 반환하지 않는 회귀를 추가했다. 새로운 DB mutation 경계는 없다.
- 첫 설치 시도는 보호된 shell script를 직접 exec해 EACCES로 실패했고 서비스 변경0이었다.
  `/bin/bash`로 공식 script를 호출해 cold 설치한 뒤, primary의 non-routed config를 routed라고
  가정한 preflight가 중단됐다. 이미 설치한 wheel은 재설치하지 않고 현재 구성을 확인해
  non-routed 설정은 그대로 보존하는 준비 단계만 이어갔다. 실패 로그도 보존했다.
- QUERY/Catalog만 호환 선택 후 실제 QUERY READY를 확인했다. 초기 즉시 관측의 NOT_READY와
  이후 READY를 구분한다. API READY 및 HTTPS 로그인200을 확인했다. 잘못된 외부 API health
  URL의404는 관측 URL 오류이며 실제 내부 `/api/v1/health/ready`는 READY다.
- 후속 Web1dc35993도 배포했다. 정확한 인증 PDF 미리보기200 응답만 SAMEORIGIN, 나머지는
  DENY다. 실제 installed Web UID/RECORD53파일 검증 PASS. Web 시작 순간 login502 한 번은
  제한된 재조회로200이 됐고 API/QUERY/Catalog/INDEX PID는 Web 배포 동안 그대로였다.
- 공개 풀이 projection의17:22 UTC metadata는 CUDA376/1003, CPU352/1003이다. 합산하지 않는다.
  기존 전체 INDEX를 중단/재시작하지 않았다. 새 GPU commit 증가를 이 관측만으로 주장하지 않는다.

**다음 실제 gate:** 새 코드로 명시적2문항/top_k5 검색1건을 사용자 GUI에서 시작해 각 결과,
결과→DB, 같은 결과 재확인, 최근 기록 재열람·원 문항 미리보기를 확인한다. 실패 요청은 자동
재실행하지 않는다. 사용자는 일반 Studio 로그인만 사용하며 터미널 비밀번호를 재요청하지 않는다.
실제 두 문항 결과는 이 문단 시점에 아직 PENDING이다.

증거: `/var/lib/eom-query-local-ack-0d7dbf22-20261102-r2/`,
`/var/lib/eom-db-preview-web-1dc35993-20261102/`,
`/tmp/eom-db-list-gpu-terminal-proof-20261102.metadata`,
`/tmp/eom-db-list-local-ack-20261102.ready`,
`/tmp/eom-db-list-preview-web-20261102.activated`,
`/tmp/eom-db-list-local-ack-compatible-20261102.tests`。

## 실제 두 문항 CUDA 완료와 기존 결과 조회 개선 — 2026-11-02

사용자가 검색이 정상으로 보인다고 확인했다. 준비 실패까지만 있던 원 intent
`dbsearch_bc7157f963ce4c604527d556c0995c57`는17:36:32 UTC에 READY가 됐다.
이는 이미 native가 실패한 `dbsearch_4fe4b8b955f30ad17e46ff0d6d74decf`를 성공으로 바꾼
것이 아니다. 후자의 FAILED와 원 종료 기록은 그대로 남아 있다.

- 입력2/top_k5, 실제 CUDA child Workflow 두 건 모두 COMPLETED/step SUCCEEDED이며
  coordinator는 ALLOCATION/EXECUTED/PUBLISHED/COMPLETED를 갖춘 SUCCEEDED다.
- 원 child는 `workflow_3e55c6b4cc48487ca02147bf8fe5ed08`,
  `workflow_f24ee8f312ff45d6bc86a292f7b822d1`이다. 각각 native identity1건이며 동일한
  batch receipt Artifact/revision/hash의 ordinal0/1을 가리킨다. 수치 결과 공유 batch를
  확인했으며 QUERY당 새 프로세스로 모델을 두 번 올린 것으로 설명하지 않는다.
- 실제 batch receipt는 `artifact_674fd60aded049dc9c5b51454a7710f2` /
  `rev_b236099f39f54c6498bd85d7f4784626`, SHA
  `sha256:071a12890f617c8ef4ea1bf8db823b9d78edb719b054d7c1d4752241139b2c1e`다.
- 사용자에게 기존 결과 열람이 느리다는 피드백을 받았다. 완료 GET
  `req_2a27fed1bafc110e841127f6bd5db348`는146.284초였다. 새 임베딩이 아니라 공식
  완료 QUERY proof와 source/index/vector read·조합을 하는 요청이다.
- 같은 SQL root의 전체 source를 시작·index 내부·마지막에3회 읽었다. 기존
  `SimilarityDocumentReadWindow`를 public에도 사용해 처음 두 번을 공유하고 마지막
  실제 전체 capture/권한·정본 재검증은 유지했다. source 순회3N→2N을 회귀로 확인했다.
  service singleton에 요청 state를 저장하지 않고 새 owner-local window를 쓴다.
- main `b23ec8c6`, Catalog-only 호환 successor `6ad2e4c0`를 commit/push·배포했다.
  wheel의 실제 변경은 Catalog3모듈+RECORD이며 API contracts bytes는 그대로다.
  API/Web/QUERY/INDEX PID·InvocationID·각 설정/수치 환경은 보존했다. 기존 Catalog의
  요청 socket이 비어 있을 때만 교체했다. 사용자 로그인 세션·검색 이력·모델 실행 변경0.
- main focused71 PASS, 마지막 권한·파일/승인 거부5 PASS, 호환 branch51 PASS다.
  main strict mypy3·Ruff/format·build/RECORD PASS. 호환 branch의 전체 import 추적은
  수정하지 않은 legacy `similarity_context_service.py:381`의 기존 profile union 오류1개가
  있었고 **수정 전89dab6fa에서도 동일하게 재현**했다. 변경3파일의 focused strict type check는
  PASS다. 이 범위에서 무관한 legacy composer나 수치 runtime을 다시 설계하지 않았다.
- source backport 첫 cherry-pick은 linked worktree의 HEAD를 잘못 기준 삼아 이미 포함된
  commit으로 빈 적용이 됐다. 변경 없이 skip 후 명시적 source commit을 적용했다.
  이전 preparation 경로의 테스트 conflict는 그 경로를 보존하고 이번 완료 read만 반영했다.
  실제 호환 branch 자체의51 PASS·wheel diff로 검증했다. 실패/중단된 이전 테스트는 보존했다.

증거: `/tmp/eom-db-list-two-gpu-completed-20261102.metadata`,
`/tmp/eom-db-list-existing-read-20261102T1744.metadata`,
`/tmp/eom-db-result-read-window-final-20261102.tests`,
`/tmp/eom-db-result-read-window-security-20261102.tests`,
`/tmp/eom-db-result-read-window-compatible-20261102.tests`,
`/tmp/eom-db-result-read-window-predecessor-20261102.mypy`,
`/var/lib/eom-db-result-read-window-6ad2e4c0-20261102/`。

배포 뒤 API READY·HTTPS 로그인200을 확인했다. **조회 시간 단축의 실제 수치는 아직
미측정**이다. 사용자가 기존 완료 기록을 다시 여는 같은 GET으로 비교하며, 새 검색이나
새 임베딩으로 속도 개선을 대신하지 않는다. 두 기준 모두의 실제 목록/미리보기와 기록 복원은
사용자 확인 범위에 맞춰 별도로 기록한다.

화면 후속 수정은 `NOT_REGISTERED`/`NOT_INDEXED`만 ‘준비 필요’로 구분하고, 일반 연결 오류는
‘연결 확인 필요’로 표시한다. 승인 상태·공개 풀이·벡터 준비를 같은 상태로 설명하지 않는다.
이 화면 문구와 앞의 PDF header 수정은 별도 Web 배포 후 실제 기록 재열람에서 확인한다.
