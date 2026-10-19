# 생성 문항 검토 기록의 증분 연결 — 개발 중간 검증

최초 기록: 2026-10-19 12:43 UTC. 후속 기록: 13:34 UTC.
사용자 요청으로 활성화한 목표는 **진행 중**이다.
이 문서는 개발 중간 증거이며 최종 release 또는 운영 acceptance가 아니다.
설계: [통합 설계](../architecture/REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md),
[원 검토 기록의 의미](../architecture/REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md).

## 구현·검증된 기반

- 현재 승인 Item과 최종 authoring/review, 등록 정본, trusted receipt를 bounded batch로
  해석한다. 단일 resolver를 문항 수만큼 호출하지 않는다. read-only 해석과 쓰기 root의
  공유 잠금은 구분한다. proof는 정확한 root와 선택적 savepoint에만 귀속한다.
- source-plan2는 실제 accepted base ID를 별도로 보존한다. 검토 Job을 V10 분석 ID로
  위장하지 않는다. profile2의 원 공개 결론과 기존 기출 profile1을 명시적으로 구분한다.
- binding2/index2/registry2와 혼합 namespace를 추가했다. native encoding key/input/result,
  shard1과 수치 공간은 유지한다. namespace2는 새 논리 index이며 old index를 개명하지 않는다.
- ordinary 최신 생성 Item의 Graph 출판은 옛25문항 전용 경로를 확장하는 대신 명시적
  successor로 기존 Graph owner를 사용한다. 실제 accepted V2 분석이 선행해야 하며,
  이번 기능이 분석 row를 만들거나 모델 풀이를 다시 실행하지 않는다.
- 실제 최신 grounded plan19/23/24는 기존 공개 plan parser로 확인한다. source별 role
  provenance 규칙이나 실행계획 검증을 별도로 재구현하지 않는다.
- `20261019_0058`은 기존 base FK를 유지하고 evidence-kind XOR, REVIEW Job FK,
  registered 분기의 partial UNIQUE/lookup index를 추가한다. 새 history가 존재하면
  downgrade를 거부한다. 기존 row나 실패 기록을 갱신하지 않는다.

## 실제 임시 PostgreSQL 검증

운영 DB가 아닌 공식 disposable DB를 준비하고 기존 guard/명령을 사용했다.

| 실행 | 결과와 의미 |
|---|---|
| fresh upgrade →0058→downgrade0057→upgrade0058 | PASS |
| disposable runtime role reconcile | PASS; 운영 credential 변경 아님 |
| 첫 embedding 통합 | 123 PASS /8 FAIL; 새 association helper의 잘못된 full-source equality 발견 |
| source identity 규칙 공유 후 통합 | 130 PASS /1 FAIL; EXPLAIN tree의 Bitmap child 누락 발견 |
| 해당 EXPLAIN case의 bounded 재확인 | 1 PASS /130 deselected; 전체 PASS로 합산하지 않음 |
| 최종 기반 embedding 통합 | **131 PASS /286.90초** |

최종 XML: `/tmp/eom-registered-review-embedding-pg-final.xml`.
DB state: `/tmp/eom-api-testdb-20261019122216_29c4485b`.
이 경로는 당시 임시 DB의 이력이다. 모든 해당 검증을 마친 뒤13:31 UTC에
read-only identity/0058/다른 연결0을 확인하고 공식 cleanup으로 DB·전용 역할·임시
환경 파일을 삭제했다. 운영 DB·원 자료·Artifact는 삭제하지 않았다. 위 XML은 보존했다.

후속 공식 purpose 실행:

- `local-indexing-service-tests`: 두 단계 각각 **113 PASS /18.47초**, **20 PASS /3.98초**.
  앞선 policy 검증에서 실제 `POLICY_STALE` 차단은 정상이고 테스트의 error-message
  regex만 잘못됐던 이력을 보존한다. `.code`를 검사하도록 고쳤다.
- `embedding-encoding-tests`: **24 PASS /43.64초**, XML
  `/tmp/eom-mixed-encoding-reservations-pg.xml`. 새 ownership2 launch 두 개가 동일 수치
  batch를 동시에 claim해도 encoding별 기존 Job1은 하나이며, 원 owner2를 보존한
  OWNED/BORROWED와 같은-key replay의 event 수 불변을 확인했다. 실제 PostgreSQL
  동시성 증거이며 실제 IAM/NAS/모델 실행 증거는 아니다.
- `embedding-stage-tests`는 후속 runner 회귀 실행 중이다. 새 protocol2 준비·검사
  테스트 추가 후 encoding purpose도 최종 frozen tree에서 재실행할 예정이다.

13:26 UTC 후속 결과(위 실행 중 상태의 후속이며 live 검증은 아님):

- encoding/protocol 동시성 purpose 최종 **25 PASS /43.80초**:
  `/tmp/eom-mixed-encoding-reservations-pg-isolated-final.xml`.
- 기존 목적들을 같은 DB에서 반복한 stage 실행은 먼저 241 PASS /16 FAIL,
  이후 223 PASS /18 ERROR였다. 각각 "private history가 없어야 하는 migration guard",
  "active foreground 작업이 없어야 하는 CPU scheduling fixture"의 명시적 사전조건과
  이미 commit된 다른 시험 이력이 충돌한 것이다. 기존 row를 삭제하거나 terminal로
  고치지 않았다. migration guard는 별도 공식 `private-chat-context-tests` purpose로
  분리했고, CPU scheduling suite는 새로운 DB에서 처음 실행했다.
- 독립 빈 DB의 private context migration/immutability/concurrency **16 PASS /5.51초**:
  `/tmp/eom-private-context-fresh-pg.xml`. 해당 disposable DB와 전용 역할·임시 환경 파일은
  공식 cleanup으로 삭제했다. 원래 자료/서비스/Artifact는 삭제하지 않았다.
- 별도 새 DB의 stage purpose 전체 **241 PASS /265.26초**:
  `/tmp/eom-mixed-native-stage-fresh-pg.xml`.
  해당 DB도 검사 후 공식 cleanup으로 정리했다. 세 disposable DB 모두 정리됐으며
  위 결과 XML과 실패 이력은 DB state 디렉터리 밖에 보존한다.
- benchmark timing fixture는 ordinal만으로 고정 publication key를 써 독립 실행의
  bytes를 같은 key에 제출하는 문제가 있었다. 원 invocation execution ID를 key에
  포함했다. 같은 invocation replay는 그대로이며 실제 publication conflict/unknown
  outcome 검사를 완화하지 않았다. fixture 회귀10 PASS 후 encoding purpose25 PASS다.
- dependency/package/installed boundary **115 PASS /48.63초**, mixed registry/schema/
  copied-field/migration source **166 PASS /8.44초**.
- INDEX4/reconciliation2 최종 **333 PASS /59.22초**, QUERY config2/CPU factory와
  순수 cohost guard **78 PASS /21.19초**, primary/private/cohost 경계 **51 PASS /6.46초**.

위 source cohort들은 서로 겹친다. 합계로 고유 테스트 수를 주장하지 않는다.
실제 API `/api/v1/health/live`와 `/ready`는 13:10 UTC LIVE/READY였고, 기존 INDEX18
PID3697151도 유지했다. 잘못된 비접두사 `/health/live`의404는 API 장애가 아니었다.

첫 회귀는 admitted past-exam V3의 페이지·occurrence lineage를 accepted report의 V2 core와
전체 객체 equality로 비교한 원인이었다. 기존의 동일 Item/member core 규칙을 공개 순수
함수로 공유했다. 전체 lineage는 원 owner가 그대로 보존·재인가하며 fixture를 잘라내지 않았다.

EXPLAIN 검증은 인덱스 조건을 없애지 않았다. `Bitmap Index Scan`의 index 이름이
Relation Name 없는 자식에 있을 수 있어 정확한 부모 relation만 이어받도록 tree traversal을
고쳤다. PK/동일 identity UNIQUE를 사용하는 기존 조건은 유지한다.

이 테스트는 개발 중 작업 트리의 기반 검증이다. 이후 carrier/owner 코드가 추가되고 있으므로
최종 release의 source/wheel pin과 영향 gate를 별도로 고정·재실행해야 한다.

## 별도 소스 회귀

아래 suite들은 겹칠 수 있으며 합산해 총 테스트 수로 보고하지 않는다.

- batch resolution: 151 PASS; 별도 dependency/application 경계30 PASS.
- source-plan2와 legacy admission/coordinator/receipt: 316 PASS.
- mixed assembly와 legacy assembly/contract: 115 PASS.
- mixed data policy1.2와 legacy owner 경계: 140 PASS.
- ordinary Graph/receipt/current-source capture/projection: 167 PASS.
- 기존 Registry adapter/read/indexing owner: 164 PASS, XML
  `/tmp/eom-registered-review-owner-regression-final.xml`.
- mixed/index Artifact store와 registration application: 68 PASS.
- copied pointer/shard/nested-field audit와 관련 계약: 138 PASS.

## Native metadata2 연결 후속

- 독립 request2/ownership2/receipt2/definition2를 추가하고 기존 request1 parser와
  numerical Job/input/result/shard1을 유지했다. coordinator launch Job은 실제 metadata
  ownership2 protocol/hash를 사용하며 기존 encoding Job을2로 재분류하지 않는다.
- 기존 coordinator의 같은4단계와 append/replay를 재사용한다. 새 queue나 executor
  state-machine을 만들지 않는다. 배포 owner의 protocol2 준비와 runtime의 읽기 전용
  prerequisite 검사를 분리한다. 다른 hash가 있으면 덮어쓰지 않는다.
- 기존 Artifact file-set publisher로 completion2를 실제 commit·replay하고 Catalog에서
  원 producer/member/hash를 확인해 읽는 테스트가 통과했다. owner1의 완료를 새
  request2가 참조할 때도 원 read/completion1을 그대로 반환한다.
- source-plan2의 이미 검증된 registry row는 reservation/수치 실행에서 제외한다.
  전체가 재사용 가능한 metadata 갱신은 numerical unit을 실행하지 않는다.

검증 묶음은 서로 겹치므로 합산하지 않는다:

| 범위 | 결과 |
|---|---|
| 독립 mixed carrier +기존 회귀 | 320 PASS /52.19초 |
| owner admission2 +기존 policy/owner | 228 PASS /18.21초 |
| definition2/compiler/static admission | 143 PASS |
| coordinator2/launch +기존 coordinator/carrier | 89 PASS /35.52초 |
| repository/submission/control publisher | 84 PASS /25.51초 |
| runtime compatibility 초기 연결 | 105 PASS /19.42초 |
| completion/encoding/handoff 기존 owner | 91 PASS /18.59초 |
| explicit protocol guard +원 owner/신규 read 경계 | 48 PASS /11.52초 |
| executor/Artifact store | 67 PASS /6.84초 |

Artifact store의 import-boundary 회귀에서 새 순수 계약4개가 기존 allowlist에 없어
처음 66 PASS /1 FAIL이었다. 해당 순수 계약 이름만 명시적으로 추가했다.
DB/network/process/Git import 금지와 모든 기존 검사 조건은 그대로다.

후속 Slack milestone: `devreport_16e9d23ecf7e41129267f62d0c39e922` SENT.
배포·운영 완료가 아닌 새 source/임시DB ownership 검증 단계로 보고했다.

재검토에서 복사된 frozen model의 미선언 필드가 serialization 중 사라지는 두 경계를
발견했다. 직렬화 전 raw 검증을 적용했고, 기존 raw leaf를 하위 모듈로 옮겨 INDEX와 QUERY가
동일 규칙을 사용한다. 새 parser나 순환 import를 우회하는 별도 loader는 만들지 않았다.
Catalog의 새 Workflow provenance adapter는 명시적 mixed runtime composition에서만 조합한다.

## 남은 종료 조건

1. 독립된 native2 request/ownership/receipt/definition을 기존 claim·lease·checkpoint·
   completion에 연결한다. 기존 Job1의 완료 이력을2로 바꾸지 않고 수치 row를 재사용한다.
2. mixed index/profile2를 실제 QUERY/context/read 계약과 소비자에 연결한다. 기존 pinned
   요청은 원 namespace/index revision을 재인가하며 최신으로 바꾸지 않는다.
3. 최종 core source/타입/스타일/의존성/disposable gate, wheel·RECORD·설치 호환성과
   rollback을 검증한 뒤 새 immutable owner identity로 배포·활성화한다.
4. 실제 승인 source delta, encode/reuse 수, 같은-key replay, 검색 결과와 권한 철회/복구를
   검증하고 README/GitHub/Slack을 최종 상태로 갱신한다.

기존 CPU 서비스·기출520·벡터·불변 history는 보존한다. 이번 작업에서 운영 설치/Graph 출판,
실제 문항·모델·GPU 실행은 하지 않았다. 원래 여섯 CPU/CUDA 측정은 별도 NOT_STARTED이며
이 목표의 선행조건이 아니다. 소스/임시DB PASS를 운영 연결 완료로 해석하지 않는다.

## 운영 호환성 후속 — 13:34 UTC

- QUERY 소켓의 primary1/private1을 대체하지 않고 실제 prepare2만 선택적인 mixed
  구성으로 분기한다. 같은 프로세스·인증 capture·수치 실행 한도를 유지하며 별도 queue나
  service를 만들지 않는다. 부재한2 설정은 명시적으로 거부한다.
- Catalog read2 역시 별도 보호 설정을 사용하고 기존 읽기 전용 DB identity를 각각
  검증한다. 신규 reader/factory 회귀184 PASS, strict4와 스타일 검사를 통과했다.
- INDEX를 mixed-only로 바꾸면 Graph 전진 이후 기존 namespace1의 current head가
  갱신되지 않아 새 QUERY1/Chat1 준비가 실패한다는 실제 코드·회귀 근거를 확인했다.
  따라서 같은 successor INDEX 프로세스에서 기존 namespace1 metadata 갱신도 유지한다.
  legacy/mixed 권한은 새 실제 신원에 각각 귀속하며 INDEX18 grant를 차용하지 않는다.
- 공식 release operator context1.7에 exact0057→0058만 추가했다. 기존1.0–1.6 schema와
  이전 callback 의미는 유지했다. operator/install inventory325 PASS와 strict/style/shell
  검사를 통과했지만 실제 migration·설치 실행은 아직0이다.
- README의 반복 시간순 인증·실패 설명은 현재 상태 요약과 원 운영 기록 링크로 정리했다.
  실패 기록이나 canonical 실행 이력을 삭제하거나 성공으로 바꾸지 않았다.

## 최종 소스 동결 검사

- 변경된 운영 Python119개 파일을 하나의 strict mypy invocation으로 확인했다.
  변경 Python185개 Ruff/format과 diff-check도 통과했다.
- mixed/기존 소비자24 suite **596 PASS**: 최종293 PASS/144.95초와 별도303 PASS/49.88초.
  `/tmp/mixed-similarity-consumer-freeze.xml`,
  `/tmp/mixed-similarity-consumer-supplement-final.xml`.
  이는 다른 이 문서의 source cohort와 겹칠 수 있어 전체 합계로 다시 더하지 않는다.
- optional legacy/mixed INDEX 동시 구성6 suite **185 PASS/13.96초**:
  `/tmp/eom-dual-index-owner.xml`. 같은 실제 capture/launcher, 별도 current grant,
  최대6개 정확한 namespace와 기존 round-robin을 확인했다. 별도 읽기 전용 재검토도 PASS다.
- root source/runtime 경계 **116 PASS/27.70초**, resource/의존성 경계
  **132 PASS/39.25초**. 기존 binding/receipt/hash/namespace 조건은 완화하지 않았다.
- 실제 offline wheel에 새 schema/entry가 포함되고, checkout 경로 없이 두 가지 독립
  import 순서로 Catalog/runner/reservation을 불러오는 검증 PASS/11.36초:
  `/tmp/eom-mixed-wheel-import-inventory.xml`. 운영 설치 증거는 아니다.
- final schema4 canonical/mirror raw SHA는
  `161027494d7be6b2736c41f1257689a04904282bf1e9e59927ff56c239d22188`이다.
  기존1/2/3 schema bytes는 보존했다.
- 마지막 독립 검토에서 request2의 정상 부재 분기가 reply1을 돌려주는 결함을 발견했다.
  검사를 느슨하게 하지 않고 하나의 응답 factory로 success/failure/absence의 family를
  선택했다. 실제 두 부재 분기의 RED2를 보존했고 수정 후4 suite92 PASS/26.52초,
  strict/Ruff/format이 통과했다. `/tmp/mixed-query-absence-family-green.xml`.
  앞선596 PASS만으로 이 후속 수정까지 검증했다고 해석하지 않는다.

다음 실행은 [호환 배포 runbook](REGISTERED_REVIEW_INCREMENTAL_COMPATIBLE_RELEASE_RUNBOOK_2026-10-19.md)을
따른다. 0058 적용 후에는 DB를58로 보존하고 같은58-compatible binary/새identity19의
legacy-only warm baseline으로 feature recovery한다. 옛881 binary를 다시 설치하면
DB58에서 READY가 된다고 주장하지 않는다. 실제 운영 migration/설치/활성화는 아직 수행 전이다.

## 커밋·공식 build와 입력 사전 관측

소스는 `a8f9965bfb2ccc018787d5fa07c753c36f674b00`으로 main/origin에 반영했다.
공식 build-only의 RECORD 검사는 통과했지만 installed OpenAPI와 정적 리소스의 exact
비교에서 실패했다. 새 PREP2/READ2의 공개 schema가 정적 파일에 아직 반영되지 않은
원인이었다. 비교를 완화하지 않고 기존 공식 export로 JSON·checksum을 갱신했다.
수정 후5 suite117 PASS/33.41초이며 기존 동일성 RED와 GREEN XML을 보존했다.
이 시점까지 실제 설치·migration은 하지 않았다.

13:48:41–42 UTC에 기존 installed881 API의 공개 QueryAdapter를 실제 eom-api UID의
단발 격리 진단에서 사용했다. 모든 DB transaction은 READ ONLY와10초 statement 한도였다.
Nas/모델/문항 내용은 읽지 않았고 사용자 인증·자료 권한·V2/receipt 자격을 승인하지 않았다.
최초 명령의 mount namespace 인자 오류는 interpreter 실행 전에226/NAMESPACE로 실패했고
그 이력을 보존했다. 수정된 진단은 별도 unit으로 한 번 실행해 다음 metadata를 관측했다.

- accepted 분석1870, 그중 approved-Item-revision source metadata1311.
- active Item631, current APPROVED626, accepted metadata가 있는 current revision545.
- 최신32개 교집합의 상세는 옛 production25개(@10 Review)와 legacy7개였다.
  두 목록은 끝까지 조회했지만 상세는32개 제한이므로 전체 ordinary eligible0이라고
  결론내리지 않는다. 실제 새 source 존재 여부는 후속 bounded metadata와 공식 resolver로 확인한다.

또한 현재 공개 API에는 source1개만 철회·복구하는 ACL이 없다. Item retirement는
restore 전이가 없고 immutable policy 새 발행은 기존 pinned query 철회가 아니다.
guiadmin의 ADMIN 전체 권한을 검증 편의로 떼지 않는다. 실제 좁은 철회/복구 검증은
미수행으로 남기며 단위 검증을 그 증거로 대체하지 않는다.
