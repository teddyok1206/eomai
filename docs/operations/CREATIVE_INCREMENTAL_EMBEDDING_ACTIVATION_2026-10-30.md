# 창작 풀이보고서 자동 증분 임베딩 활성화

2026-10-30 UTC. 목표는 **보고서·Graph 검증 → 실제 벡터 등록 → 공식 검색 반영**이다.
기존 [공통 풀이 설계](../architecture/SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md)와
[구현 체크포인트](PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md)를 이어간다.

## 착수 기준선

- source `39fb4de67e15d83bb20300294c760c367a8f1a39`, clean main/origin.
- 기출 원래 목표 520개를 활성 CPU/CUDA 인덱스 12개에서 각각 대조했다. 원래 목표의
  누락·추가·등록 encoding 참조 누락 모두 0. 1,563 encoding 행은 문항 수가 아니다.
- 08:24 UTC 창작 77/1,053 Graph/report 검증 완료, 다음 원문 10394 분석 중.
- 기존 창작 순차 등록, INDEX, QUERY 서비스는 active. active는 새 창작 벡터 등록 증거가 아니다.
- public recipe2/source-plan3/index3/native3 및 numerical QUERY2는 구현 후보다.
  public source의 GPU 일괄 selection·installed owner·공식 similarity 소비 연결은 미완료다.

## 변경 경계와 짧은 설계 결정

1. 책임: Catalog가 실제 source/보고서/Graph 접근을 검증한다. 기존 Orchestrator INDEX/QUERY
   owner가 수치 실행과 등록을 맡는다. 원문 등록 transaction의 필수 후속 단계로 묶지 않는다.
2. 정본: accepted V10 또는 등록 창작 보고서와 원문/Graph 계보다. 공통 텍스트와 벡터는
   파생물이며 보고서·원문·과거 Graph를 수정하지 않는다.
3. identity: Item/revision, base analysis, report/lineage Artifact revision/hash, Graph/policy,
   recipe/space/partition을 각각 핀한다. 같은 text hash는 권한 또는 source identity가 아니다.
4. pointer: 기존 source capture·pinned artifact resolver·registry의 존재/권한/schema/media/
   hash/lifecycle 검사를 재사용한다. public source를 legacy accepted/review anchor로 위장하지 않는다.
5. 접근: bounded Graph source 순회, indexed report lookup, encoding key dedup, ordered batch,
   원래 queue의 atomic claim, index head CAS. 별도 스캐너·queue·검색 저장소를 만들지 않는다.
6. 구조: public source는 기존 typed entry/evidence를 쓰고, batch에는 text 없는 source/profile/
   evidence pointer만 둔다. 기존 native numeric input/result/shard와 물리 자원 lease를 재사용한다.
7. 비용: public metadata head 16,384, 페이지·수치 batch 1,024, 선택 메타데이터 4 MiB,
   report 캡처 64 MiB 한도 유지. 단일 batch pointer 검사는 O(n), map/set 공간 O(n)이다.
8. 동시성: 원문 등록과 분리된 기존 증분 owner가 누락을 발견한다. 완료 encoding은 재사용하고
   같은 binding은 CAS/unique 제약으로 등록한다. 실행 중 native/runtime pin을 교체하지 않는다.
9. 의존성: schemas/contracts → 순수 값 → Catalog admission → Orchestrator adapter.
   CLI/UI에 근거 검증이나 SQL/NAS 검색을 새로 구현하지 않는다.
10. 실패: canonical mismatch는 명시적 오류, missing report는 대기다. historical FAILED 보존.
    같은 요청의 replay·중단 복구는 기존 identity를 유지하고 완료된 수치를 재계산하지 않는다.
11. 단순 대안: 기존 anchor에 창작 데이터를 끼우면 계보·recipe를 오인하고, 별도 임베딩
    스크립트는 자원·등록·검색 경계를 우회한다. 필요한 successor만 기존 owner에 연결한다.

## 실행 순서와 완료 기준

1. public INDEX batch selection/입력 검증을 기존 GPU 자원·실행 경로에 연결한다.
   기존 1.0/1.1/1.2 계약 bytes와 의미는 보존한다. 수치 wire와 queue는 바꾸지 않는다.
2. 명시적인 public owner 설정과 동일 recipe QUERY/공식 similarity 소비 경로를 연결한다.
3. focused/static/schema와 disposable PostgreSQL의 concurrency/replay/중단 회귀를 확인한다.
4. 기존 수치 작업을 안전하게 마친 뒤 compatible wheel/policy/owner를 설치한다.
5. 고정 창작 5건의 실제 수치 계산·등록 binding·공식 검색 결과와 정확한 source identity를
   확인한다. 같은 요청 재전송은 새 수치 실행이 없어야 한다.
6. 기존 backlog와 이후 Graph publication을 기존 owner가 자동 발견하는지 확인하고 활성화한다.
   기존 기출 인덱스/정본/실패 이력과 창작 순차 등록의 보존도 재확인한다.

현재 상태: `IN_PROGRESS`, 운영 public 검색 활성화 `PENDING`.
소스 테스트·PID·캐시 membership 갱신만으로 목표 완료를 선언하지 않는다.

## 첫 구현 체크포인트 — public GPU 실행 준비

- `embedding-batch-plan/1.3`: 기존 INDEX batch owner가 public entry의 source/base analysis/
  profile/evidence **포인터**를 검증한다. 수치 본문·보고서를 selection에 복사하지 않는다.
  기존 allocation/route/bound 이벤트와 numerical input/result/shard는 그대로다.
- `local-indexing-owner-configuration/6.0`: 기존 GPU-first/CPU counterpart composition을
  재사용한다. public namespace 한 개와 명시적으로 핀한 legacy config5를 같은 서비스에서
  순회할 수 있어 기존 6개 view의 갱신을 끊지 않는다. 각각의 recipe/routing/source grant는
  따로 검증하고 물리 runtime·실제 DB owner·controller는 일치해야 한다. 구 config1–5의
  schema bytes와 decoder는 public successor 입력을 계속 거부한다.
- parent 생성은 public source에만 1.3을 선택한다. 기존 기출·review 경로는 1.1을 유지한다.
  같은 request의 parent/selection identity는 보존하고 새 allocation 후보를 새 dispatch로
  취급하지 않는다. CPU matching에도 같은 source·풀이 입력을 유지하되 space는 분리한다.
- 기존 device-index pair 검증에 public manifest3를 명시적으로 추가했다. 같은 원문 번호만
  보고 CPU/CUDA를 짝짓지 않으며 source/보고서/lineage/Graph/policy/input hash가 다르면 거부한다.
- 공개 풀이가 없는 plan3는 기존 coverage-only 경계로 처리한다. 0 벡터를 만들지 않는다.
  legacy similarity context1/2는 public profile을 자체 후보로 재해석하지 않는다.

확인 결과:

- focused unit **313 PASS**: 새 계약/owner/parent/device pair, 기존 batch/submit/similarity 회귀.
- dependency·similarity/native read boundary **119 PASS**.
- guarded disposable PostgreSQL의 parent·plan store·routed/fallback/recovery **83 PASS**.
  이 중 public/legacy parent concurrent creation·allocation 후 중단·release 변경 replay 6개는
  같은 저장 identity와 물리 실행 중복 방지를 확인했다.
- 변경 core 11개 mypy PASS, 변경 Python 20개 Ruff/format PASS, diff whitespace PASS.

DB 검사는 실제 임시 PostgreSQL과 실제 control Artifact IO를 사용하나 IAM/source/runtime
일부는 명시적인 합성 seam이다. **모델·실제 GPU·운영 검색 성공 증거는 아니다.**
운영 API/INDEX/QUERY/창작 owner와 production migration은 이 체크포인트에서 바꾸지 않았다.
다음은 public query/result2의 공식 검색 소비 연결, installed wheel 검증과 호환 활성화,
창작 5건의 실제 벡터·검색 canary다. 목표는 아직 완료되지 않았다.
