# 문항 내부 Graph 노드 식별 범위

2026-10-29 UTC. 등록 10331의 검증된 accepted proposal에서 `item.1.statement.giyeok`이
기존 문항에서는 ITEM_ELEMENT, 새 문항에서는 CLAIM이었다. `item.1`도 여러 문항이 공유했다.
이는 공통 과학 개념의 유형 충돌이 아니라 문항 내부 이름을 전역 식별자로 사용한 결함이다.

## 경계와 정본

수정 책임은 Catalog의 순수 Graph projection이다. accepted proposal, 풀이보고서, 원본,
source/accepted Artifact revision/hash는 수정하지 않는다. publish command/manifest의 기존
`publisher_version`으로 투영 알고리즘을 고정한다. 새 publisher **1.10.0**만 새 식별 규칙을
선택하고 이전 버전은 이전 계산을 유지한다. 새 schema, DB 테이블, queue, worker 실행은 없다.

## 식별 규칙과 자료구조

- APPROVED_ITEM source의 ITEM_REVISION/ITEM_ELEMENT 및 역사적 `item.` 이름 공간의 노드는
  해당 immutable Item Revision에 속한다. `item.`은 기존 proposal의 문항 내부 키 문법이며,
  type-qualified proposal의 `<node_type>:` 접두사를 제거한 뒤에도 동일하게 판정한다.
- 투영 키는 `item-source:<item_revision_id>:<원래 stable_key canonical JSON의 SHA-256>`이다. node ID는 기존처럼
  node type과 투영 키로 계산한다. 같은 문항의 같은 키에서 유형이 충돌하면 여전히 거부한다.
- 공통 CONCEPT/FORMULA/PROCESS 등의 키는 그대로 공유한다. 다른 이름만 보고 의미가 같다고
  추정하거나 새로운 과학적 관계를 만들지 않는다. 기존 edges와 source pointer를 정확한
  proposal-local node ID → projected node ID map으로 연결한다.
- PAST_EXAM·TEXTBOOK 및 다른 source는 재키잉하지 않는다. 520 기출과 교과서의 node/edge
  식별을 유지한다. 이전 immutable Graph bytes도 유지한다. 기존 창작 내부 노드는 새 successor
  snapshot에서만 올바르게 분리되며 과거 snapshot을 수정하지 않는다.

접근은 노드별 key lookup/dedup과 edge endpoint lookup이다. 기존 dict/set의 O(N+E) 시간,
O(N+E) 공간을 유지하고 원문을 복제하지 않는다. DB unique/FK와 Graph publication의 기존
CAS·transaction·권한·hash 검사를 사용한다. projection은 DB/파일/서비스를 직접 호출하지 않는다.

## 실패·복구와 검증

공유 키의 실제 유형 충돌, 같은 revision 내부 충돌, stale source/hash/권한 오류는 계속 거부한다.
등록 재개는 기존 accepted analysis와 cohort의 공식 publish replay이며 모델 재실행·직접 row
수정·FAILED 이력 성공 변경을 하지 않는다. publisher version이 요청 hash에 포함되므로 이전
실패 요청을 성공으로 해석하지 않고 수정된 투영의 새 publication identity가 생성된다.

회귀는 문항 간 로컬 키/유형 분리, 동일 revision의 충돌 거부, 공통 개념 병합, 520 기출·교과서
identity 보존, canonical serialization, 구 publisher replay 불변을 확인한다. 모든 등록 owner가
새 버전을 명시하여 이후 publication이 구 규칙으로 되돌아가지 않도록 한다.

단순 재시도는 같은 충돌을 반복한다. 충돌 검사 해제나 node_type 덮어쓰기는 다른 문항의 선지와
근거를 합치므로 부적절하다. proposal 정본 수정/재생성보다 source-aware projection이 작고 안전하다.

## 검증 체크포인트

집중 unit 160개 PASS 후 explicit Item binding/answer-bearing 보존 검사를 추가하여 해당 새 묶음
8개 PASS. disposable PostgreSQL의 기존 Graph/acceptance/동시 생성·replay 6개 PASS, core 7개
파일 mypy PASS, Ruff/format PASS. 첫 임시 DB 실행은 앞선 fixture의 auth binding 잔여로
concurrent-create bootstrap 1건이 거부됐고, 나머지 5건은 통과했다. 기존 supported bootstrap을
사용한 다음 실행은 6개 모두 통과했다. 운영 계정/DB row 수정은 없었다.

기존 자동 curriculum test의 기대값에 누락된 `inherited_binding` callback을 반영하면서 두
binding family가 동일한 callable을 공유하는지도 단정한다. 운영 membership 검증을 제거한
수정이 아니다. 배포 완료와 실제 10331 Graph publication은 별도 증거로 남긴다.

## 등록과 GPU source reader의 동시 실행

수정본 owner의 재개에서 PostgreSQL이 원인을 추가 확인했다. 이미 존재하는 분석의 `_create`
idempotent replay가 `SELECT FOR UPDATE`를 요구하여, 동일 row를 보호하는 GPU population
reader의 SHARE lock 뒤에서 기다렸다. replay 분기는 제출 hash를 대조하고 DTO를 반환할 뿐
row/state를 변경하지 않는다. 이 read-only lookup에서만 배타 잠금을 제거한다. 새 생성의
unique idempotency constraint, source/preset 검증, 상태 변경의 기존 잠금은 그대로다.
실제 disposable DB에서 다른 connection이 SHARE lock을 유지한 동안 동일 요청의 replay가
완료되는지, run ID/상태/lock version과 중복 1개 제한이 유지되는지 검사한다.

## 실제 운영 복구 — 2026-10-29 15:45 UTC

`abcc6eda`의 문항 내부 식별 수정과 `007e3f44`의 read-only replay 수정을 기존 isolated
creative owner에 배포했다. 최종 설치는 `/opt/eom/maintenance-releases/007e3f44bcc22afe699a0a452b093c2065a43649`.
wheel raw SHA/RECORD, Catalog identity import와 기존 cohort/limit 검증 PASS다. API/Web,
QUERY PID 1708497·07ec 설치본과 numeric GPU runtime/bundle은 교체하지 않았다. production
migration·권한 변경·로그인/비밀번호 변경·기출 재생성은 없다.

이전 owner는 GPU SHARE lock 뒤의 read-only replay에서 대기하여 정상 stop을 요청했고,
기존 systemd의 180초 종료 한도 후 종료됐다. 새 invocation은 같은 cohort의 기존 완료
21건을 다시 확인했다. 이를 새 모델 실행 21회나 완료 데이터 손실로 계산하지 않는다.

기존 실패 지점 **10331**은 원래 `analysisrun_70662984ce8e4962be7b011cd87bf976`와
`itemrev_6b15a706134b464b858c9447a6ab88bd`를 그대로 사용하여 새 Graph
`graphrev_86889bbff51b960b7733f5fc0a168376`에 게시됐고, cohort의 공식 SOLUTION_REPORT
조회까지 **VERIFIED** 됐다. 모델 재생성 없이 **22/1,053**으로 진행했으며 다음 10332는
새 추출·등록을 마친 뒤 ANALYZING 상태로 이어졌다. 전체 자동 순차처리와 기존 :00/:30
read-only observer를 유지한다. 전체 1,053건 완료 판정은 아니다.

read-only identity 대조 결과:

- 이전 accepted source 1,036개 모두 동일 revision/source SHA/accepted SHA 유지, 새 source 1개 추가.
- 기출·교과서 source pointer를 가진 node 17,000개와 edge 40,652개의 ID/type/key/endpoint 보존.
- missing/changed source·protected node·protected edge 각각 **0**.
- source unit/경계 집중 **167 PASS**, 실제 disposable DB 동시 생성·SHARE lock 중 replay 등
  **6 PASS**, 수정 core mypy/Ruff/format PASS. build-only/설치본 검사와 실제 운영 게시를 구분한다.

보존 검사의 첫 correlated EXISTS 조회는 read-only 30초 timeout으로 중단됐다. 같은 metadata를
각각 indexed 읽기 후 ID set으로 비교하여 완료했으며 운영 row·source·정책은 바꾸지 않았다.

공개 풀이 원문과 report Artifact/hash는 변경하지 않았으므로 공통 풀이 텍스트 투영의 입력도
그대로다. 새 Graph revision의 source proof/index binding은 새 revision에 정확히 귀속해야 한다.
node key 변경을 풀이 텍스트에 섞거나 구 index의 Graph pin을 바꾸지 않는다. 같은 text/space의
수치 row 재사용과 새 Graph의 source membership 갱신은 서로 다른 검증이며 운영 검색 연결은
별도 미완료 상태다.
