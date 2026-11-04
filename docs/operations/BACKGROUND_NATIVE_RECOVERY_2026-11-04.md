# 창작 등록·공통 임베딩 중단 복구

2026-11-04 UTC. 사용자 승인: 중단 원인을 수정하고 같은 작업을 재개하는 것을 새 목표로 설정.
기존 1,053개 모집단·완료 풀이·정본·Graph·벡터·실패 이력을 유지한다. 새 교재 ingestion,
HWPX renderer, 별도 queue/검색 engine은 범위 밖이다.

## 실제 중단

- creative owner: 2026-11-03 22:45:18 UTC, `KNOWLEDGE_GRAPH_STALE_CURRENT`, exit78.
  마지막 단독 HWPX canary의 Graph append 이후 정상 4문항 publication이 이전 Graph에
  기반해 실패했다. 앞선 완료 보고 시점(22:42 UTC)은 실행 중이었으나, 그 뒤 중단됐다.
- INDEX owner: 2026-11-04 01:26:02 UTC, `LOCAL_EMBEDDING_SOURCE_PLAN_STALE`가
  service unavailable로 감싸져 종료됐다. 30분 관측 timer는 실행 중이나 owner 재개는 하지 않았다.
- 04:45 UTC 실제 유효 worker lease·수치 실행 unit은 0이었다. 서비스 ACTIVE를 실제
  진행의 대체 증거로 사용하지 않는다.

## 최소 수정 설계

1. **책임/경계:** 기존 creative Graph application의 publication 재시도와 기존 public
   source-plan builder/admission의 버전 결정만 보완한다. worker 동작·wire schema는 바꾸지 않는다.
2. **정본:** accepted analysis/source revision·공개 풀이 Artifact, 기존 encoding ledger와
   committed index. observer cache는 현재 진행 표시이며 완료 판정의 원본이 아니다.
3. **식별:** 동일 Item/분석 ID·보고서·수치 encoding ID를 유지한다. 충돌 뒤 publication은
   현재 Graph를 명시적으로 다시 읽고 새 expected-current로 append하며 과거 요청은 수정하지 않는다.
4. **포인터:** 매 publication 재시도에서 동일 원본/분석과 실제 operator 권한을 재검증한다.
   source-plan 재검증은 원래 request의 family와 source/Graph/policy/hash를 유지한다.
5. **접근 패턴:** 고정 source tuple 순회, source-ID map/set, Graph CAS 및 멱등 publication,
   기존 unique encoding/binding 조회다.
6. **구조/인덱스:** 기존 map/set·unique key·Graph CAS·ledger 인덱스를 재사용한다.
   새 DB/schema migration·persistent queue·파생 상태는 없다.
7. **복잡도:** plan 검증은 선택된 source/entry 수에 선형이다. publication 충돌만 최대 3회
   재검증하며, 모델 추론/문항 등록을 다시 시작하지 않는다.
8. **동시성:** `KNOWLEDGE_GRAPH_STALE_CURRENT`만 같은 accepted tuple로 제한 재시도한다.
   다른 권한/hash/source/publication 오류는 그대로 실패한다. 다른 writer가 이미 넣은
   분석은 기존 membership 검증 후 재사용하며 중복 Graph/Item을 만들지 않는다.
9. **의존 방향:** Catalog application → 기존 publication/registry 인터페이스와 순수 plan
   builder → 기존 DB/NAS adapters. CLI/systemd에 새로운 business rule을 넣지 않는다.
10. **실패/복구:** 실패·중단 증거를 먼저 보존한다. 같은 완료 Workflow/분석/벡터를
    기존 owner가 읽어 재개한다. source/policy/hash의 실제 변화는 계속 stale 오류다.
11. **단순 대안:** restart만 하면 다시 같은 경계에서 멈춘다. 모든 stale 검사를 끄거나
    이전 request를 latest로 덮어쓰는 방법 대신 정확한 version pin·CAS 재시도만 정렬한다.

source-plan 재현 원인: 전체 capture에 native entry3가 있으면 선택한 4문항이 모두
legacy여도 plan5가 만들어질 수 있으나, admission의 선택-only capture는 plan4를
만든다. 테스트와 실제 저장 plan 비교로 확인한다. 신규 discovery의 자동 family 결정은
기존 mixed/index5 경로를 위해 유지하고, 재검증 때는 original request가 선택한 family를
명시적으로 전달한다. 새로운 schema/plan tag로 과거 문서를 바꾸지 않는다.

실제 중단 시각의 committed preparation Artifact도 확인했다. `job_be01ea53a61a423e9f83bba0e6b7b602`의
CUDA plan5는 source/demand가 각각 4개이며 native demand는 0개다. manifest/member hash
검증을 통과했고 plan SHA는 `79a5e5d9adad8c2df5384f717f4ec214acf78f8e7790eb9b1a3d9d9479d351cc`다.
직전 완료 수치 Workflow 8건은 CPU/CUDA 각 4개 native demand로 정상 완료했다. 따라서
수치 모델 실패가 아니라 다음 legacy-only membership preparation의 false-stale다.

## 소스 수정 검증 체크포인트

- 원래 요청 family5인 legacy-only subset의 실제 admission 오류를 단위 테스트에서 재현했다.
  family를 보존하는 재검증은 source/hash/보고서 누락 변화까지 무시하지 않는다.
- Graph 충돌 뒤 같은 accepted 분석을 새 expected-current로 최대 3회 반영한다.
  이미 다른 writer가 등록한 같은 분석은 재사용하며, 권한 취소·source hash 오류·다른
  publication 오류는 재시도하지 않는다. 모델/분석 생성은 반복하지 않는다.
- 집중 회귀 115 PASS, 변경 production 3개 파일 mypy PASS, ruff/format PASS.
- 새 disposable PostgreSQL의 기존 Graph 동시 publication/CAS·멱등 재전송을 포함한
  6 PASS. 뒤이어 같은 테스트 DB에서 다른 fixture 계열을 실행했을 때 synthetic binding
  STALE 충돌이 있었으므로 production 오류로 해석하거나 상태를 고치지 않고 별도 fresh
  disposable DB로 분리했다. fresh DB의 인덱스 동시 등록·중단 rollback 후 동일 요청
  재전송·stale CAS 거부 3 PASS였다. 두 DB 모두 head71이며 production에는 pytest를
  실행하지 않았다.
- creative owner는 04:53 UTC 원래 source `31073cb4`·동일 cohort로 우선 재개했다.
  원래 중단 cache를 보존했으며, 완료 풀이를 다시 생성하지 않고 기존 Graph 등록부터
  이어갔다. 이는 아직 수정본 배포 완료나 실제 4슬롯/CUDA 완료를 뜻하지 않는다.

## 완료 기준

두 원인의 재현/부정 회귀, 필요한 disposable DB의 충돌·재전송 검증, 설치 wheel/RECORD,
기존 실행·권한·history 보존을 확인하고 담당 owner만 호환 설치한다. 실제 4슬롯 진행과
새 Graph 반영, 실제 CUDA의 증분 처리/저장·동일 완료 요청 재조회 무중복을 확인한다.
전체 1,053개 처리나 전수 임베딩 완료는 배경 작업으로 유지한다. 복구 이후 실제 결과를
이 문서에 추가하며 과거 완료 기록은 그 시점의 역사로 보존한다.

## 호환 운영 배포와 실제 재개

운영 수정 commit은 `38d1f5c34bb415dd9ed3568dd1ea534c6b738b32`이며 main에 커밋·푸시했다.
새 wheel의 RECORD, 격리 설치 import, source 일치를 검증한 뒤 두 metadata owner만
설치·활성화했다. 공유 API·QUERY·Web이나 물리 CUDA 실행환경을 함께 재시작하지 않았다.

| 구성 요소 | 실제 설치 source / 보존 경계 |
| --- | --- |
| 창작 등록 담당·관측 실행기 | `38d1f5c3`, 2026-11-04 05:17:54 UTC 재개. 기존 담당은 SIGTERM을 받고 현재 작업을 마친 뒤 정상 종료했으며 실행 중 모델 작업을 죽이지 않았다. |
| INDEX metadata 담당 | `38d1f5c3`, 05:18:31 UTC 기동. 기존 service logical identity와 같은 corpus·Graph·정책 범위를 새 revision으로 활성화했다. |
| 공유 API·Catalog/runner·QUERY | `31073cb4`, 기존 프로세스 보존 |
| Web | `e22ca6e0`, 기존 프로세스 보존 |
| 물리 수치 controller | `a70cd434`, CPU/CUDA model·space·profile·환경 파일 bytes 보존 |
| DB | `20261103_0071` 유지, 이 복구에 migration 없음 |

배포 전 상태와 rollback 입력은 각각 `/var/lib/eom-creative-recovery-38d1f5c3-20261104`,
`/var/lib/eom-index-native-recovery-38d1f5c3-20261104`에 보호 보관한다. 환경 비밀값은
감사 Artifact나 Git/Slack에 복사하지 않는다. 설치물은
`/opt/eom/embedding-owner-releases/38d1f5c34bb415dd9ed3568dd1ea534c6b738b32/site-packages`다.

05:19:46 UTC에 **03·04·05·06 네 슬롯의 실제 유효 ACTIVE lease**를 동시에 확인했다.
그 후 새 풀이 Workflow들이 완료됐으며, 05:29:35 UTC에는 수정본 owner가
**11795·11796·11797·11798의 Graph 등록·공식 풀이 조회를 모두 VERIFIED**로 기록했다.
Graph revision은 `graphrev_d0bc430dde16224174eaba97739080a7`이다. VERIFIED는 단순 등록
row 생성이 아니라 실제 요청자 권한으로 공개 풀이 pointer와 경고 기록까지 읽은 뒤의 상태다.
다음 원본들의 추출·풀이도 이어졌다. 재시작 후 `verified_count=4`는 이번 순회의 진행이며
전체 corpus 완료 수를 4로 초기화했다는 뜻이 아니다.

새 CUDA Workflow `workflow_2209e33c70ba42d68e3f7adb0e69ae10`의 수치 job 4건은
05:22:13 UTC 시작, **05:26:22 UTC 전부 SUCCEEDED**였다. 이는 과거 CUDA 성공을
재인용한 것이 아니라 수정본 재개 후의 새로운 실제 실행이다. 수치 성공과 committed
index 저장·재조회 검증은 분리하며, 아래 최종 증거가 저장 완료를 명시한다.

두 disposable PostgreSQL DB는 공식 guarded cleanup으로 제거했다. 테스트 결과·혼합
fixture 실패 이력은 남겼고 운영 DB·원본·기존 벡터는 삭제하지 않았다. 기존 30분 관측
timer 두 개를 유지한다. 이 복구 때문에 새 비밀번호 입력·계정 변경을 요청하지 않았다.

## 실제 CUDA 저장·재사용 확인

새 CUDA 인덱스는 05:30:05 UTC에 기존 등록 담당을 통해 committed 상태로 저장됐다.
05:42 UTC 설치된 Catalog reader로 실제 member를 두 번 읽어 같은 bytes·해시를 확인했고,
기존 membership planner도 같은 입력 두 번 모두 추가 갱신 불필요로 판정했다.
이 조회 검증이 새 수치 실행을 제출하거나 source claim을 만들지는 않는다.

- Index revision: `embeddingindexrev_e6eff420b2503f88d9ba6693287975f4`
- Member SHA: `sha256:ccdca94d83d1d4d7c059e867f548bc18b7d4ae271c9889d8502c3790ce2be87c`
- CUDA 해당 view의 binding 552개 중 native role3 기반 binding 26개를 확인했다.
  이 수는 전체 등록 문항 수나 1,053개 완료 분모가 아니다.
- native 26개 모두 profile3·원래 role result3와 encoding ledger의 text hash·space·row가
  일치했다. 기존 공통 풀이 텍스트·벡터 행 계약을 바꾸지 않았다.
- 창작 owner는 그동안 11799–11802도 다음 Graph
  `graphrev_ba3abefbb66d2c51a839370694d17467`에 반영하고 공식 조회 검증을 끝내,
  이번 수정본 순회의 VERIFIED가 8개로 증가했다. 이후 원본 처리를 계속했다.

수치 계산 성공, 인덱스 저장, Workflow 최종 완료는 별도 상태다. 05:42 관측은 인덱스
저장·무계산 재사용까지의 증거이며 당시 Workflow는 `complete` 단계였다. 최종 완료와
감사 Artifact는 아래 완료 기록의 시각·포인터를 기준으로 판단한다.

## 복구 목표 완료 기록

2026-11-04 **05:44:20 UTC** 원래 재개한 CUDA Workflow가 `COMPLETED`로 종료됐고
오류 코드는 없다. 05:45:25 UTC에는 동일 완료 Workflow·수치 job 4건을 두 번 읽어
동일한 결과임을 검증했다. 인덱스 member도 두 번 같은 bytes였고 membership 갱신은
두 번 모두 불필요였다. **재조회 검증의 모델·수치 실행 수는 0**이다. 다른 새 문항의
정상 증분 계산까지 금지하거나 이번 재조회에 포함한 것은 아니다.

05:46:59 UTC 최종 관측에서는 03·04·05·06 네 슬롯에 다시 새 실제 ACTIVE lease가
동시에 있었고, 11803·11804·11806·11808의 다음 Graph publication과 그 뒤 원본의
추출·풀이가 진행 중이었다. 두 owner·기존 API/Web/QUERY는 정상이며 HTTPS 200,
API READY다. 30분 관측기는 05:30 UTC 정상 종료했고 두 timer는 계속 active다.

이 복구의 구현·검증·배포·실제 실행 목표는 완료다. **전체 1,053개 완료는 아니다.**
기존 변환/읽기/추출 예외 16건과 실패 이력은 성공으로 바꾸지 않고 보존한다. 기존
background owner의 순차 등록·증분 임베딩을 그대로 계속하며, 가변 정본 HWPX 재출력은
사용자가 선택한 후속 범위로 남긴다.

검증 기록은 기존 Orchestrator `ControlFileSetPublisher`로 commit하고 Catalog의
검증된 member read로 다시 읽어 원래 보고서와 byte equality를 확인했다. 기존 내부
운영 감사 schema를 재사용했으며 새 worker protocol/schema/queue는 추가하지 않았다.

- Artifact: `artifact_70a41880061342799803fca44a974d43`
- Revision: `rev_9cc8d8f33dc14eb2b0887daaff23bc74`
- Member: `report.json`
- Report SHA: `sha256:f608cd7048a40b650d118cef4dc139ee1b93ec0170a81138b2959f1ce14e806b`
- Manifest SHA: `sha256:c3b3c67b497b45af167a37a7374c557845468c20e3912c4758f86725e801c983`
- [검증 보고서](/mnt/nas/eom/artifacts/artifact_70a41880061342799803fca44a974d43/rev_9cc8d8f33dc14eb2b0887daaff23bc74/report.json)

보고서는 15개 점검과 11개 증거 파일을 포함한다. 실제 Graph/CUDA/멱등 재조회,
115개 회귀, disposable Graph 6개·별도 fresh index 3개, 설치 검증과 cleanup뿐 아니라
앞선 synthetic fixture 실패 로그도 보존했다. 환경 파일·비밀번호·인증 토큰은 포함하지 않는다.
