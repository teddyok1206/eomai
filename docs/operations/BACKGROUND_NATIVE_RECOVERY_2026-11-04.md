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
