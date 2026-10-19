# 생성 문항 검토 기록의 증분 연결 — 개발 중간 검증

최초 기록: 2026-10-19 12:43 UTC. 후속 기록: 13:34 UTC.
사용자 요청으로 활성화한 목표는 **진행 중**이다.
이 문서는 개발 중간 증거이며 최종 release 또는 운영 acceptance가 아니다.
설계: [통합 설계](../architecture/REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md),
[원 검토 기록의 의미](../architecture/REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md).

## 운영 후속 — 16:50 UTC

- 실제 source `37f10967bde4dfd88913cd2004c432c540b2d23e`를 공식 설치했고,
  migration0058 upgrade/verify와 API 격리 검증이 통과했다. 실제 설치 delivery는
  `/tmp/eom-api-build/37f10967bde4dfd88913cd2004c432c540b2d23e.X0Yx5Q/dist`이며
  앞선 build-only `.flKtl9`와 구분한다. 실제 API wheel rawSHA는
  `849bfb7cfe2b08bf00ad61eed0eb66ee21b540a116047387727039c130bfdd3a`다.
- 변경 전 공식 PostgreSQL 백업과 manifest를 보존했다:
  `/mnt/nas/eom/backups/postgresql/eom_20261019T162141Z_62e091033e53.manifest.json`.
  dump SHA는 `62e091033e53f483e892ff14311505a2c456d0ee2e28a801f3478c5a9a5207ff`다.
- 기존 INDEX18 실행1건은 정상 완료됐고 미착수2건은 public cancellation으로
  CANCELLED를 기록했다. 새 identity가 옛 command를 재분류해 실행하지 않았다.
- 사용자 승인 범위의 첫 Graph 분석1회는 실제 ACCEPTED다:
  `analysisrun_c27ed152738e45e38ada736ca1fa06fc`. 그 전에 timeout/preset 불일치로
  worker 시작 전 실패한 원 실행은 FAILED로 보존했다. 추가 출제/검토/풀이 모델
  재실행이나 가짜 V10 생성은 없었다. ordinary Graph publication 자체는 아직 실행 전이다.
- INDEX19 등록·활성화와 실제 policy Artifact2건, 권한1.1/1.2를 공식 owner로 게시했다.
  같은37f/DB58/identity19의 legacy warm baseline은16:32:30 UTC에 실제10개 service,
  QUERY READY·INDEX STARTED·Chat slot READY·API LIVE/READY로 확인했다.
  증거 `/tmp/eom-registered-review-release.u0p6TvJa/legacy-warm-baseline-after-chat-result.json`,
  rawSHA `4250a038c19741977a651d7c61d00b096627cb6adc1cc9228bb66e3ba5e1078f`.
- 첫 QUERY 기동은 Chat의 private source socket보다 빨라 종료됐다. 실패 기록은
  보존했고 Chat READY 후 정상 기동했다. 후속 배포 순서는 **Chat source 준비→QUERY**다.
- mixed 설정 선택 후 INDEX는 STARTED했으나 실제 source capture에서42501로 종료됐다.
  PostgreSQL이16:37:04 UTC에 `permission denied for table item_components`를 기록했다.
  설정의 `database_owner=eom_app`는 fence 함수 소유자이며 실행 credential인
  `eom_catalog_manager_runtime`과 다르다. 관리자 credential로 재실행하지 않았다.
- DB trigger로 불변인 leaf에까지 FOR SHARE를 요구한 것이 원인이다. mutable
  ItemRevision/Workflow/step/Job 잠금과 기존 source/hash/receipt 검증을 유지하면서
  불필요한 leaf 잠금만 제거하는 수정이다. DB 권한·schema를 확대하지 않는다.
  실제 제한 로그인 PG 회귀를 별도로 추가했다. 기존 소유자 계정 테스트만으로는
  이 권한 차이를 증명할 수 없다는 검증 공백을 닫는다.
- owner4→실제 finalized owner2 한 파일의 inverse CAS로 INDEX19 legacy 설정을
  복구·기동했다. DB58/source37f/identity19/CPU/원520개·벡터·이력은 보존한다.
  mixed QUERY/read2 설정 선택과 실제 증분·검색 acceptance는 서로 다르다.
  실패한 mixed 기동을 성공으로 바꾸거나 새 Graph/delta/search 완료로 보고하지 않는다.

다음은 제한 역할 회귀와 수정 compatible release, 실제 ordinary Graph1건 반영,
자동 delta/재사용·mixed 검색/replay·철회/복구다. 원 여섯 CPU/CUDA 비교는 NOT_STARTED다.

### 제한 역할 회귀와 Catalog 시작 검사 후속

- 불필요한 leaf 잠금 제거 후 핵심73개, 관련 회귀251개, Graph/조회 관련81개가
  통과했다. 이 묶음은 겹치므로 고유 테스트 수로 합산하지 않는다.
- fresh disposable DB `20261019164834_33e639a4`에서 공식 embedding purpose는
  134 PASS /1 FAIL이었다. 실패는 새 테스트가 공개 Entry에 없는 `evidence_kind`를
  직접 참조한 assertion 오류였다. 실제 제한 로그인 capture는 그 전에 성공했다.
  실제 계약의 `profile.source_basis.review_evidence`를 검사하도록 수정한 뒤 새4개를
  동일 guarded DB에서 재실행해 **4 PASS /4.01초**를 확인했다. 앞선 전체 실행을
  135 PASS로 재해석하지 않는다. XML `/tmp/eom-registered-review-lock-restricted-pg-green.xml`.
  synthetic 제한 로그인 ACL 테스트와 실제 migrated app의 불변 trigger 테스트는
  증명 범위가 다르며 IAM/NAS/실제 모델 성공을 주장하지 않는다.
  검증 후 공식 cleanup으로 해당 disposable DB·전용 역할·임시 credential을 제거했고
  XML과 실행 결과는 보존했다. 운영 DB나 Artifact를 삭제하지 않았다.
- 별도로 Catalog startup 반복 실패를 발견해 해당 service의 재시작을 중지했다.
  mixed reader JSON 설치가0444였으나 기존 reader의 계약은0640/0644다. 이는
  DB 권한이나 Graph source 문제가 아닌 배포 파일 metadata 불일치다. 고정 hash와
  root 소유권을 유지한 한 파일의0644 metadata 보정을 진행하며, 실제 재기동 확인 전
  Catalog 정상·전체 서비스 정상으로 보고하지 않는다. 과거 실패 journal은 보존한다.

## 운영 후속 — 17:52 UTC: 호환 런타임 복구와 출판 역할 경계

- 실제 설치 source는 `66f387bfa5ef3b5d16858d515ad0982dee8789c4`다. 공용 delivery의
  API wheel SHA는 `27270fda4fb64c5267f04326b16837d29ca8959459fe4067533d734a4939a803`이며
  build-only wheel과 구분한다. DB0058은 VERIFY만 했고 새 migration/grant는 없다.
- Catalog 파일 metadata 보정은 실제 재기동에 성공했다. 공용5개, broker/Chat2개와
  INDEX/QUERY를 포함한 기존10개 서비스를 복구했다. QUERY READY17:46:00,
  INDEX20 STARTED17:45:59 및 versioned API LIVE/READY를 실제 확인했다.
- INDEX20의 같은 revision `localindexservicerev_e8794dc635fe426e82527c869c76fbe9`를
  public lifecycle로 ACTIVE40→DISABLED41로 바꿨다. 실제 시작은
  `LOCAL_INDEXING_FENCE_FORBIDDEN`으로 종료했고 native 실행0/NRestarts0였다.
  같은 revision을 public activate로 ACTIVE42에 복구한 뒤 정상 기동했다.
  실패 journal과 원 lifecycle 결과를 보존했으며 다른 service/권한으로 대체하지 않았다.
- ordinary Graph 출판1건은 제한 Catalog credential에서 `operators FOR SHARE`가 거부됐다.
  원 command 파일을 보존했고 읽기 전용 확인에서 publication row 없음·current Graph가
  원 `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9` 그대로임을 확인했다. 다른 key나
  elevated credential로 재제출하지 않았다. 설치된 Identity fence를 주입하고 불변 leaf의
  불필요한 잠금만 제거하는 수정이 필요하다. mutable source/producer와 최종 CAS는 보존한다.
- 같은 단원의 실제 기출13개 중 새 문항의 독립 REVIEW가 참고했던 genuine V10 기출
  `itemrev_72ab539bd96c4ba6993bc1f5dc678989`를 공식 읽기 계약으로 확인했다.
  이것은 owner metadata 준비이며 새 사용자 인증/새 Graph/검색 성공 증거가 아니다.
- 수정은 별도 cold SDK에만 설치할 수 있다. DB·daemon/provider/control20을 다시 선택할
  필요가 없는 administrative one-shot 경계다. API66과 후속 SDK의 source/RECORD를
  따로 검증하며, 새 SDK 설치를 운영 전체 release 변경이나 활성화로 보고하지 않는다.

운영 증거는 `/tmp/eom-registered-review-patch.zbfFVg5a/`의 installation/selection,
authority disable/restore, Chat 복구, startup, original publication/outcome 결과다.
최종 HTTP는 exact generated target에 실제 VECTOR observation이 있는지도 확인한다.
Graph-only 후보 반환을 새 문항의 벡터 소비로 확대하지 않는다.

### 제한 출판 역할 수정의 종료 검증

- publisher는 필수 Identity fence를 주입받는다. 최초 owner root와 automatic preliminary
  callback의 새 Session만 명시적으로 시작하고 기존 최종 corpus CAS root는 교체하지 않는다.
- ordinary publisher/기존 fence 관련3개 소스 suite **131 PASS /5.47초**와 strict type,
  Ruff/format을 통과했다. 최종 XML은 `/tmp/eom-ordinary-publisher-identity-fence-final2.xml`이다.
  기존 실패 재현과 중간 성공 실행도 보존하며 합산하지 않는다.
- 별도 disposable DB `20261019174958_c012f45d`의0058 migration cycle·runtime reconcile,
  공식 limited operator-fence profile을 사용했다. 공식 `operator-fence-tests`는 실제 제한
  로그인/설치 SECURITY DEFINER/actor 잠금과 철회, stale Graph·policy 거부를 포함해
  **12 PASS /29.76초**다. Graph member 해석 한 포트는 합성이라 전체 Graph/NAS 출판
  성공으로 확대하지 않는다. 운영 계정·권한·DB는 테스트 대상이 아니다.

## 운영 후속 — 18:13 UTC: 실제 Graph 출판과 Runner 계열 검사

- Identity fence 수정은 `a67fa7847d72be603433de45cb5d624d8ad2f008`로 commit/push했다.
  공식 build-only/RECORD 검증 뒤 cold SDK에만 설치했다. 공용 API/Chat/QUERY/provider와
  normal INDEX20은66으로 유지하며 DB0058/migration과 수치 prefix도 바꾸지 않았다.
- standard API prefix는 기존 설치 계약상 eom:eom writable code 위치다. root-owned SDK
  code 검사와 혼동한 첫 one-shot wrapper는 import/DB 전39ms에 종료했다. 그 attempt
  디렉터리가 없음을 실제 확인하고 기록을 보존했다. 후속 wrapper는 API build-info를
  고정 hash·실제 metadata의 DATA로만 읽고 모든 EOM 코드는 root cold SDK/RECORD로
  제한한다. API prefix 소유권이나 파일 mode를 바꾼 것이 아니다.
- 원 command rawSHA `e0026b50e807b85c799b374f5f00caa7802f32cecbd0849aa66378bb274d27e8`
  그대로 실제 Catalog credential+공개 Identity fence로 출판1회가 **CREATED**를 반환했다.
  새 Graph는 `graphrev_8f3ff9b22d592ecf661fec7116a5cab9`, manifest SHA334a9468…,
  semantic SHA44ed4dc6…, result SHA2c99ecc9…다. 실제 반환은18:07 무렵이며 약5분22초다.
  result에 기록된 published_at18:02:07은 별도 관측한 DB commit 시각으로 확대하지 않는다.
  원 command/key/actor/authorized_at17:46:11·accepted source/REVIEW는 유지했다.
- 최초 승인된 V2 Graph 분석1회 외 추가 Codex/출제/REVIEW/풀이 호출은 없다.
  같은 단원의 REVIEW-referenced genuine V10 anchor로 최종 HTTP plan도 오프라인 검증했다.
  이 plan은 아직 HTTP 제출·사용자 로그인·실제 검색 성공이 아니다.
- 18:08 registry 관측은 신규 target binding0/mixed head3개 NONE이었다. 18:09 FIFO에는
  원 Graphc0e의 mixed CONTENT1건 PROCESSING/attempt1과 미착수5건이 있었다.
  platform_job_id NULL은 native receipt 완료 전 정상이며, 반복 capture 로그만으로
  busyloop나 완료를 판정하지 않았다.
- 별도 source 대조에서 `local_embedding_step_execution`의 execute 후 old-only class
  검사가 독립 output2를 거부함을 확인했다. request2/output2를 authoritative 완료 검증에
  연결하는 집중 회귀·수정과 INDEX-only SDK successor를 준비한다.18:12에 원 INDEX20의
  main에만 SIGTERM을 요청해 current run_once 뒤 정상 종료하게 했다. child kill, SDK hotpatch,
  실패 이력 변경, 원 running workflow 취소나 API/Chat/QUERY 중단은 하지 않았다.
- 요청/완료 계열 수정은 기존 Runner와 checkpoint2 경로를 포함해 **68 PASS /53.91초**,
  최종 소스 바이트 집중 재실행은 **5 PASS /17.10초**다. synthetic owner 회귀이지 실제
  운영 index 완료 증거는 아니다. strict type·Ruff·format·diff 검사도 통과했다.
  18:20 실제 INDEX20은 MainPID0/inactive/dead/Result=success/NRestarts0이었다.
  정상 process 종료와 Workflow/native terminal 완료를 동일시하지 않고 후속 관측한다.

## 운영 후속 — 18:36 UTC: INDEX21 실제 교체·권한 차단/복구

- Runner 수정은 `e013d35013851a8a5a7b50b8bee9c40edd90568c`로 commit/push했고,
  공식 build-only/RECORD 검사와 cold SDK 설치를 통과했다. 실제 설치 code SHA는
  최종 소스86ab1dfc…와 같다. API66/QUERY/Chat과 CPU prefix는 그대로다.
- 원 INDEX20의 command는18:18에 `LOCAL_EMBEDDING_OUTCOME_INVALID`로 FAILED였다.
  native launch Job은 SUCCEEDED이며 ALLOCATION→INDEX_PREPARED→REGISTERED→COMPLETED
  checkpoint4개와 committed index/receipt가 존재했다. WF/step RUNNING은 실행 중인
  작업이 아니라 quiescent nonterminal history로 남긴다. 성공으로 바꾸거나 재시도하지 않았다.
  root READ ONLY 관측 결과는 `original-index20-execution.json`이다.
- 원Graphc0e를 대상으로 미착수였던5건만 같은 공개 cancellation owner로 CANCELLED했다.
  attempt0/lease generation0/step0를 fresh 재검증하고5건을 한 transaction으로 처리했다.
  원870 실행과 Artifact, encoding, 과거 receipt는 수정하지 않았다.
- 기존 공개 Identity·grant·Orchestrator Artifact owner를 사용해 INDEX21을 등록/활성화했다.
  revision은 `localindexservicerev_7819ddd0edc6412dac90393f30ae82ad`, identity SHA는
  `sha256:3e50db350624f99b464de3ae99a387a1e78b1e5e1f1a1e9821fb96f98528dd67`다.
  기존 namespace와 허용 범위를 유지한 legacy/mixed grant2개와 native policy Artifact2개를
  새 immutable service/runtime에 결합했다. IAM/schema/수치 모델 변경은 없다.
- INDEX가 terminal/native0인 상태에서 runtime·owner·unit·prepare entry의4파일을
  exclusive backup/순차 CAS로 선택했고 최종 owner4를 선택했다. API/QUERY/Catalog/Chat의
  기존 control hash·epoch를 보존했다. 전체 service 중단/공용 prefix 재설치는 없었다.
- 같은21을 ACTIVE44→DISABLED45로 바꾸고 실제 시작을 시도했다. invocation
  `9af38de3150d498792b70d24e0c9d5cf`는 `LOCAL_INDEXING_FENCE_FORBIDDEN`으로
  종료했고 native 실행0/NRestarts0였다. 실패 journal을 보존한 뒤 public activate로
  ACTIVE46에 복구했다.21 자체의 실제 차단 증거이지 사용자별 source ACL 철회 증거는 아니다.
- 복구 뒤 positive invocation `8a7c747a65af4169988f3e6cf27abb74`/MainPID19308의
  active/running/Result=success/NRestarts0를 확인했다. 시작 성공을 자동 delta·query 완료로
  확대하지 않는다. 최종 mixed/primary/historical HTTP는 아직 제출하지 않았다.

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
