# 창작 풀이 처리의 원본 변환 실패 격리

## 범위와 근거

2026-10-31 운영 확인에서 창작 처리 owner는 PDF 변환 산출물이 없는 원본 HWP 한 건 때문에
전체 창을 중단했다. 원본의 OLE 서명·고정 SHA는 정상이며, 같은 Catalog 변환 경로로 두 번
재현했다. 원본 내용이나 기존 FAILED 이력을 고쳐 우회하지 않는다.

1. 책임: 기존 Catalog preview owner가 변환하고, 기존 병렬 cohort driver가 준비 실패를 격리한다.
   Orchestrator의 3슬롯 claim/lease/model 정책과 Graph commit 책임은 바꾸지 않는다.
2. 정본: admitted cohort의 원본 revision/edition과 기존 Artifact. PDF는 파생물이다.
3. 참조: 자식 owner의 제한된 결과는 원래 요청의 source ID/revision/edition을 다시 확인한다.
4. 접근/구조: 기존 최대 6개 source window와 기존 순서, source ID keyed map을 사용한다.
   변환 산출물 없음만 source-local deferred 항목으로 보관한다. 권한·해시·protocol·Graph 실패는
   여전히 전체 중단이다. 새로운 큐/DB 테이블/상태 보정은 없다.
5. 복잡도: N개 source를 회차당 최대 한 번 준비, O(N) 시간/O(N) bounded 실패 메타데이터.
   긴 원본/풀이/로그는 상태 파일에 넣지 않는다.
6. 동시성/재개: 기존 cohort process fence와 source별 공식 idempotency를 유지한다.
   실패 source를 완료로 세지 않으며 다음 owner 재개 때 원래 identity로 다시 준비한다.
7. 관측: deferred source 번호와 안정된 오류 코드, 정상 처리 수를 구분한다. 모든 정상 항목
   처리 후 deferred가 남으면 `BLOCKED_SOURCES`로 종료하고 전체 완료를 선언하지 않는다.
8. 대안: 단순 재시작은 같은 원본에서 나머지 슬롯을 다시 멈춘다. 무조건 skip/COMPLETED 보정은
   누락을 숨긴다. 원본 변환 실패만 격리하고 명시적으로 남기는 것이 필요한 최소 변경이다.

새 local-owner 결과는 JSON Schema 2020-12와 frozen Pydantic 모델로 먼저 정의한다.
선택된 오류 외 예외, 잘못된 identity, 알 수 없는 출력은 재시도·skip 권한이 아니다.
