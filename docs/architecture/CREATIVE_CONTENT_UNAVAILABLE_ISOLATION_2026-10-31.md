# 창작 원문 초안 결측의 처리 격리

운영11416과 과거10311은 extract Workflow가 성공했지만 승인된 worker 결과는
`NEEDS_DECISION`, `proposal=null`이다. 이는 이미 허용된 V1/V2 결과이며 실패한 worker를
성공으로 바꾸거나 출제 내용을 만들어서 등록할 근거가 아니다. 원본·관측·풀이/문제 기록은
기존 immutable 결과 Artifact에 남아 있다.11416을 등록하려다 전체 owner가 정지했다.

1. 기존 Catalog 등록 use case가 실제 source/current permission/완료 결과를 resolve한 뒤
   등록 가능한 내용이 없음을 typed local exception으로 알린다. 새 worker protocol은 없다.
2. 정본은 frozen cohort target, original extraction selection, validated result Artifact다.
   오류는 그 target/selection/report pointer만 전달하고 전체 결과를 복사하지 않는다.
3. parallel scheduler는 exact target의 다섯 필드 및 original selection을 대조하고, 이 경우만
   blocked로 분류한다. 권한/해시/다른 target/Graph 오류와 단순 정답 불일치는 격리하지 않는다.
4. 기존 dict window와 blocked source map을 재사용한다. source별 O(1) 분류, O(N) 전체 순회,
   기존 동시성·순서·publication batch·unique command/registration key를 유지한다.
5. 내용이 없는 source는 Item/Graph/embedding을 만들지 않고 verified에 더하지 않는다.
   원본과 canonical worker 결과는 그대로 조회·재검수할 수 있고 재기동해도 원 Workflow를
   읽어 같은 결측을 복구한다. local status는 파생 상태이지 acceptance/권한이 아니다.
6. source별 실패 목록은 기존 상태 파일의 number/code로 관측한다. report는 cohort target의
   원 preparation/Workflow를 통해 exact Artifact revision/hash로 resolve한다. 별도 DB/큐/
   중복 보고서 저장/자동 재추론/FAILED 이력 변경은 없다.
7. 모든 유효 source를 처리해도 blocked가 남으면 COMPLETED가 아니다. 가짜 초안을
   생성하거나 전체 exception을 무시하는 대안은 source 보존·등록 규칙을 위반한다.

검증: V1/V2 nullable 결과, 권한 거부 선행, 등록/학습/Graph side effect 없음, target/selection
교차 오염 거부, 정상 문항 계속 진행·최종 BLOCKED_SOURCES, observer 분류 및 기존 warning
있는 원문 정상 등록 회귀. 운영은 creative owner만 새 설치본으로 선택한다.
