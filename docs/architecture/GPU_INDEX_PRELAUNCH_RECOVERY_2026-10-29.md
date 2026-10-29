# GPU INDEX 실행 전 중단 복구

2026-10-29 UTC. 현재 작업 범위는 GPU 계산 재개와 실제 index binding 증가다.
공개 풀이 recipe/새 검색 기능 활성화는 이 복구의 선행조건으로 확대하지 않는다.

## 실제 원인과 경계

새 parent `job_be1fed35ea2b47b18873941ac029b711`은 15:43:25 생성, CUDA ROUTED 15:44:40,
Workflow `workflow_fbd6f8991ff9447e8782bb9bd3318db6` 생성 15:45:30, encode 시작 15:49:29,
executor context 거부 15:50:17이었다. allocation은 만료됐고 BOUND/native launch Job/수치
completion이 없다. 이전 `workflow_db74b6d4242443dca07867e29ebbcb88`도 별개로 같은 실행 전
중단 상태다. 둘을 하나의 실행으로 혼동하지 않는다.

source SQL의 generic plan이 각 source 검사를 수분씩 지연시키고, 유한 GPU allocation 시간은
계산 전에도 흐른다. 먼저 검증된 materialized eligible-key SQL 개선을 owner에 반영한다.
deadline·권한·pidfd 검사를 끄거나 시간을 무제한 늘리는 방식은 사용하지 않는다.

## 책임·정본·식별

- 기존 Workflow maintenance application은 원 Workflow/START command/encode step의 실패를
  기록한다. 실제 root UID와 schema owner, 원 service/revision과 제출 hash를 재검사한다.
- 정본은 기존 Workflow/Job/event/Artifact와 보호된 runtime 선택이다. 작은 command/receipt는
  원 workflow ID·request SHA·command ID·lease generation·service pointer·successor commit을 고정한다.
- 기존 preallocation retirement/1.0의 reason은 encoding protocol unavailable로 고정돼 있어 이번
  오류에 재사용하면 사실과 다르다. schema-first successor **1.1**에 closed reason
  `EMBEDDING_EXECUTION_CONTEXT_UNAVAILABLE`을 추가하고 v1 bytes/hash/parser는 보존한다.
- 기존 guards를 공유한다: 만료된 PROCESSING lease, RUNNING/encode, 플랫폼 Job 없음,
  native launch key 없음, output 없음, exact source plan/definition/service. 살아 있는 claim,
  이미 시작된 native Job/완료 output, 다른 lease/hash는 거부한다. 기존 실패 이력을 성공으로 바꾸지 않는다.

## 데이터 구조·transaction·동시성

접근은 정확한 ID/unique key lookup, source-specific native Job 존재 검사와 단조 event append다.
기존 B-tree/unique/FK, NOWAIT row locks, 짧은 owner transaction을 사용한다. 작업당 O(log N)
indexed lookup과 작은 고정 event 집합이며 원문·벡터를 DB에 넣지 않는다. 새 DB/index/queue/cache는 없다.
같은 command replay는 동일 receipt, 다른 command/hash는 conflict다. 늦은 claim/launch·rollback을
disposable PostgreSQL에서 확인한다. application은 공개 domain transition/Identity owner를 재사용하고
계약은 infrastructure를 import하지 않는다.

## 운영 재개

수정된 metadata owner를 기존 protected owner installer와 stopped PREPARE/PUBLISH/SELECT 경계로
새 immutable prefix에 설치한다. 실제 service identity/runtime config/grants/native service policy를
정확히 새 owner에 귀속한다. scope·6 namespaces·device profiles·numeric CPU/CUDA bundle·controller
24555547·QUERY 설치본/공유 root-owner env는 보존한다. Studio 로그인 재요청은 이 schema-owner
maintenance 작업 자체의 필수조건이 아니다.

기존 중단 child는 공식 retirement로 FAILED 이력을 남긴다. 기존 parent의 RUNNING/BOUND 없음
planning history를 성공으로 고치거나 새 physical dispatch로 재사용하지 않는다. 새 owner/서비스의
정상 missing-binding discovery가 실제 새 요청을 만들며, 기존 registered encoding은 재사용한다.
과거 parent history의 별도 정리는 이번 GPU 복구를 이유로 범위를 넓히지 않는다.

## 검증·실패·단순 대안

ready PID만으로 성공하지 않는다. 실제 CUDA 수치 완료 receipt, registry binding 증가, committed
index revision, 기존 rows 재사용과 zero duplicate를 확인한다. dtype/space/recipe/Graph의 pin을 바꾸지
않고 fault를 CPU fallback으로 숨기지 않는다. 부분 staging/실패는 보존하며 같은 배포 phase와
command identity로만 재확인한다. 미확인 처리에 새 key를 발급해 중복 실행하지 않는다.

단순 restart는 expired physical context와 generic SQL을 반복했다. 직접 row UPDATE와 임의 key
변경은 owner/감사 경계를 깨므로 제외한다. 기존 maintenance의 좁은 successor와 기존 배포 경계가
새 복구 프레임워크보다 작고 충분하다.

## 새 Graph의 통계 공백에서도 선택 검색을 한 번만 스캔

2026-10-29 UTC 추가 결정. Catalog의 기존 `candidate_pool_analysis_statement`에서 pointer
eligibility를 Graph당 `MATERIALIZED DISTINCT analysis_run_id` 집합으로 한 번 만든다.
`source_revision_ids`는 정본 `knowledge_snapshot_analyses`의 바깥 exact-revision 조건으로만
적용한다. Graph/분석/문항 revision pin, 출처 class·node 존재·정답 권한·명시한 analysis ID·accepted
상태·문항 lifecycle·exact occurrence·정렬·LIMIT은 유지한다. pointer의 source revision을 직접
필터링하지 않아 기존 FK와 원본 불일치/orphan 검증의 의미도 바뀌지 않는다.

이 경계는 source 승인이나 Artifact를 대체하는 검색 엔진이 아니라 기존 metadata SQL builder다.
기존 인덱스와 caller-owned Session/현 권한/원본 공유 잠금을 그대로 사용한다. 새 DDL·cache·권한·
worker protocol·runtime pin 변경과 cross-transaction proof 재사용은 없다. 결과·실패·retry·멱등성도
변경하지 않는다. 접근은 eligible analysis ID 집합과 exact revision membership이며, fresh Graph를
1행으로 과소추정하는 custom plan에서도 pointer 읽기는 O(P), 선택 수 k에 따른 O(kP)가 아니다.

근거는 disposable `pg_temp`의 520개 source/73,840개 pointer를 ANALYZE한 뒤 새 Graph로 복제하고
재분석하지 않는 검사다. 기존 내부 selected-analysis 서브쿼리는 selected8 custom 실행이 20초
guard에 걸렸다. 수정 후 custom/generic에서 전체·선택8 결과와 pointer scan 1회를 검증한다.
매 Graph 발행마다 수동 ANALYZE하는 대안은 당장 통계를 복구하지만 발행 직후의 나쁜 계획을
제거하지 못한다. 통계 갱신을 권한·수명 검사를 우회하는 근거로 사용하지 않는다.
