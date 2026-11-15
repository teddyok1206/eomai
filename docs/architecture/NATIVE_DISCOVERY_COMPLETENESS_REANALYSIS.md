# Native 자료의 발견 범위 불완전 판정과 선택 재분석

2026-11-15 UTC. 전체450문항 목표의 실제 두 번째 회차에서 확인한 후속 설계다.
완료된 발견 결과나 실패 run을 제자리에서 수정하지 않는다.

## 확인한 문제

`materialrun_3b66485a97fb5324b136228e0f18b120`은 발견6개를 모두 완료했고 문제25개·상세
해설25개·정답표1개를 찾았다. 원본 Native/Excel의25쌍도 존재한다. 그러나 문제9번과
해설6/11/16/21번의 `continuation=TO_NEXT` 때문에 최종화가 거부됐다. 이들 결과는 실제
다음 페이지 anchor도 포함한다. 적어도 '다음 물리 페이지로 이어짐'과 '제공한 입력 밖의
미관측 부분이 남음'을 모델이 혼동할 수 있는 안내가 있었다. 원문 픽셀을 검토하지 않고
모든 범위가 완전하다고 단정하거나 COMPLETE로 강제 변경할 근거는 아니다.

기존 안내는 'complete unit이 보일 때 COMPLETE'만 설명한다. 입력에는 core 바깥의 context
페이지도 있으므로, 이 페이지들에서 끝까지 읽었으면 물리 페이지를 넘겨도 COMPLETE임을
명시한다. 이는 기존 enum/출력 schema의 의미를 명확히 하는 수정이며 팀장 프롬프트나
원본 내용·bounding box를 하드코딩하지 않는다.

## 구현 경계

1. 책임은 기존 Catalog 자료 학습 retry와 discovery plan, 실제 안내문을 만드는 Workflow
   모듈이다. 새 intake/queue/worker/Graph를 만들지 않는다. Native 완전성 거부 검사는 유지한다.
2. 정본은 원래 intake/prepared/native bundle/Excel과 accepted 발견 Artifact다. 새 모델 결과는
   새 task·Artifact로 남기고 원래 COMPLETED task와 FAILED run을 보존한다.
3. 같은 material revision의 linked run/task successor를 사용한다. 변경하지 않은 PREPARE와
   정상 발견은 그대로 상속하며, 실제 incomplete unit을 만든 발견 task만 PENDING으로 재생성한다.
4. 기존 schema2020-12/Pydantic `RetryMaterialLearningRunCommand`와 `MaterialLearningRetryResult`의
   닫힌 필드를 재사용한다. 이전에 지원하지 않던 Native finalization 실패의 재시도만 추가하고,
   기존 failed-task retry·숫자 해석 finalization-only 복구의 동작은 바꾸지 않는다. 호출자나
   모델이 임의 task/actor/새 권한을 선택하는 필드는 추가하지 않는다.
5. 선택 전 기존 공식 reader로 source/권리·prepared pointer·성공한 발견 결과를 재인가하고
   Native의 정확한 QUESTION/SOLUTION 번호·출처 집합을 확인한다. incomplete flag만으로
   전체 발견을 다시 돌리거나 role/번호/중복/coverage 오류를 이 경로로 숨기지 않는다.
6. 지배적 연산은 run/revision PK, bounded task 목록과 불변 결과 pointer, unit→task lookup이다.
   기존 dict/set과 PK/attempt unique/live-revision partial index를 재사용한다. 선택은 발견
   unit·task 수에 선형이며 새 DB/index/cache나 문항별 전체 원문 재복사는 없다.
7. revision→run 잠금 순서를 지킨다. expected_updated_at, 준비/입력/출력 hash와 task signature,
   child terminal·유효 lease 없음, 동일 native source 관계를 다시 검사한 뒤 하나의 transaction에서
   successor를 생성한다. 현재 처리 중인 다른 회차와 기존 GPU를 중단시키지 않는다.
8. 같은 retry key/selection/source proof는 같은 successor를 반환한다. 다른 최신 attempt,
   stale source·hash·권한·실행 중 claim은 거부한다. 원래 추출/등록 결과나 기존25개는 건드리지 않는다.
9. 새 선택 규칙은 Native discovery 책임 모듈에 두고 기존 retry의 clone/history/동시성 경계를
   재사용한다. SQL/파일 동작을 순수 계약/plan 모델로 옮기거나 worker에 저장 책임을 주지 않는다.
10. 검증은 'core 밖 context에 완전한 다음 페이지가 있음', 실제 미관측 continuation 거부,
    정확한 두 발견만 재분석·나머지 상속, 원본 실패/성공 결과 불변, replay·동시 생성·stale/권한/
    lease 거부를 source 및 disposable PostgreSQL에서 수행한다. 실제 새 모델 결과와25문항
    등록/Graph 성공은 별도 운영 증거다.
11. 단순 대안인 flag 강제 변경은 완전성을 위조하고, 여섯 발견 재실행은 불필요하다. 같은
    source에서 잘못/불완전 판정된 task만 기존 retry로 새로 분석하는 것이 필요한 최소 범위다.

## 현재 범위와 인계

준비 checkpoint는 기존 Native2와 원본 그림 보강 Native3를 모두 지원한다.
새 형식을 추측하거나3을2로 바꾸지 않는다. 기존 `read_material_prepared`가3의 exact2 base를
읽고 관계·hash를 검증하며, retry는3의 원 pointer를 그대로 상속하고 검증한2 base도 최종
Artifact metadata fence에 포함한다. 그림 catalog를 다시 생성하거나 준비 결과를 덮어쓰지 않는다.

안내 명확화 → 선택 재분석 회귀/DB 검증 → Material/Catalog/실제 ROLE executor의 호환 source
반영 → 두 번째 회차의 원래 실패를 보존한 선택 retry → 첫 새 등록의 Native 그림/metadata/
풀이/Graph 확인 순서다. 전체18회차 접수는 완료됐으나450개 등록·임베딩 완료는 아니다.
관측 증거는 `staging/native-region-incomplete-inspection-r2-20261115.json`이며, 이 기록과
안내 후보 자체가 운영 활성화나 복구 성공의 증거는 아니다.
