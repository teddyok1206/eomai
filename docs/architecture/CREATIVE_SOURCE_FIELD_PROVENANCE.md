# 창작 원문 필드와 근거 영역의 연결 규칙

2026-10-29 UTC. U10317 재실행은 `solution.authoring_intent`가 실제 `OTHER` 영역을
인용하여 거부됐다. `solution`이라는 저장 위치만 보고 출제의도를 정답·해설과 같은
증거로 분류한 것이 원인이다. 입력의 region 분류나 출제의도 문장을 고쳐 통과시키지 않는다.

## 책임과 정본

Catalog 계약 계층의 순수 규칙이 **이미 존재하는 content path**에 허용할 region role을
결정한다. Worker 출력·원문 페이지·공개 풀이·주의사항은 기존 immutable Artifact가 정본이다.
필드 이름/role 정책은 작고 고정된 값이며 별도의 DB·캐시·registry가 아니다. JSON Schema의
기존 필드·문법·released bytes는 유지하고 Pydantic과 생성용 schema 설명을 같은 규칙에 맞춘다.

| 필드 | 허용하는 원문 영역 |
| --- | --- |
| 발문, 자료·그림·표, 선지와 그 하위 값 | TARGET_ITEM |
| 정답, 해설, ㄱㄴㄷ별 해설 | TARGET_ITEM / EDITORIAL_SOLUTION |
| 출제의도 | TARGET_ITEM / EDITORIAL_SOLUTION / OTHER |
| 배점과 인쇄 여부 | TARGET_ITEM / EDITORIAL_SOLUTION / OTHER |
| `solution` 전체를 가리키는 묶음 참조 | TARGET_ITEM / EDITORIAL_SOLUTION |

REFERENCE_ORIGINAL은 어느 필드에도 허용하지 않는다. 출제의도에 OTHER를 허용한다고
독립 풀이 단계의 과학적 근거나 정답·본문에도 허용하는 것은 아니다. 관찰한 해설 위치와
정답 일치 판정의 구분은 별도 기존 규칙으로 유지한다. 미확정 풀이·불일치는 보존한다.
원문 편집 답안이라고 선언한 EDITORIAL_SOURCE에는 여전히 최소 한 개의 실제 editorial
정답 근거가 필요하다. 필드별 허용 role 표가 이 추가 조건을 대체하지 않는다.

U10317의 같은 실패 body를 끝까지 재검증하자, 독립 답안의 `answer_labels`에 실제 선택지
기호가 아닌 “제시된 선택지 없음” 문장이 들어간 것도 확인됐다. 이를 유효한 선택지로
허용하거나 이전 모델 판단을 자동 수정하지 않는다. 유일한 제시 선택지를 확정할 수 없으면
UNDETERMINED/NOT_DETERMINED·빈 답안 배열로 표현하고, 계산한 결론·선택지 부재·불일치는
공개 풀이와 conflict에 보존하도록 같은 지침을 생성 schema와 core prompt에 전달한다.
원문 답안은 그대로 둔다. 해당 잘못된 라벨은 계속 거부하며 새 실행이 올바른 표현을 제출해야 한다.

## 값·포인터 해석과 데이터 구조

1. 기존 JSON Schema/Pydantic이 source/role/region ID, 중복, bounded 배열과 문장을 검사한다.
   원문/source/revision/hash·권한·lifecycle 검사는 기존 Catalog/Orchestrator 소유자가 담당한다.
2. content path는 실제 native/source draft 값에 해석되어야 한다. 없는 필드·배열 범위 밖·잘못된
   문법은 거부한다. `body[0].rows[0][1]`처럼 실제 표 셀의 연속 배열 인덱스도 해석한다.
3. 고정 lookup map은 root 필드와 개별 solution 필드를 명시적으로 구분한다. 문자열 접두사가
   비슷하다는 이유로 새 필드를 묵시적으로 허용하지 않는다. `solution` 묶음에 OTHER를 허용해
   answer 근거 검사를 우회할 수 없다. 모델 필드 목록과 정책 표의 coverage를 테스트한다.
4. 실제 content mapping의 모든 region ID는 관찰 영역 map에 존재하고 허용 role이어야 한다.
   그림의 포함 관계·첨부 기출/해설 overlap·media/hash 검사도 그대로 적용한다.
5. 지배적 접근은 작은 고정 key lookup과 path/참조 순회다. lookup은 O(1), 전체 검증은
   O(path 길이 + 참조 수), 공간은 bounded 필드/참조 수에 비례한다. 큰 파일은 복사하지 않는다.

## 소유권·중단·호환성

순수 계약 → Workflow 생성 schema 설명 → 기존 Orchestrator 검증/commit 방향을 유지한다.
도메인 규칙은 IO·SQL·worker 실행을 하지 않는다. 새 table/index/migration·의존성은 없다.
기존 원문·정본·Artifact·Graph·실패 기록을 덮어쓰지 않고 ID/revision/hash를 분리한다.

실패한 실행은 그대로 보존하며 기존 supported invalid-result recovery로 별도 successor를
준비한다. 같은 요청은 같은 successor로 돌아가고, 원래 operator/source/preset/cohort를
재인가한다. 원문이나 근거를 자동 재분류하거나 실패를 성공으로 바꾸는 대안은 쓰지 않는다.
V1의 과거 region 정책은 바꾸지 않고 현재 V2 정책을 정리한다. 공통 path resolver의 수정은
기존 schema가 허용하는 실제 nested 배열 경로를 처리하는 버그 수정이며, 기존 유효 path의
결과·canonical serialization/hash는 바꾸지 않는다.

검증은 필드×role 행렬, 알 수 없는 필드/region·첨부 원본·메타데이터의 answer 유입 거부,
표 셀 path 및 범위·문법 거부, 생성 설명과 검증의 동일 정책, 공개 보고서/원문 보존과 실제
실패 body의 변경 없는 재검증을 포함한다. 운영은 호환 릴리스 후 같은 1,053개 대상·slot 05
동시 1개로 재개하며, 재시작할 때 이미 등록한 원문을 재생성하지 않는다.
