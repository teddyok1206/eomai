# Registered public solution 검색 확장

## 사용자 우선순위

전체 재임베딩 완료는 검색 경로를 준비·전환하는 선행조건이 아니다. 준비된 binding으로
PARTIAL 결과를 제공하고, 미준비 source/보고서/벡터 수를 원래 population 의미대로 유지한다.
전체520 최종 검증과 구형 벡터 삭제는 별도 후속 gate다.

## 변경할 경계와 유지할 경계

- 현재 운영 public INDEX3/QUERY는 이미 `public-solution-text/1.0`·recipe2·동일 BGE-M3 공간을
  사용한다. 기존 기출과 등록 창작(entry1)은 이 경로로 부분 검색할 수 있다.
- AI의 실제 accepted V11 보고서(entry2), 그 profile2와 binding4/index4를 읽으려면
  source reference·similarity context·Workflow metadata에 closed successor가 필요하다.
  released context3/request3의 의미나 허용 범위를 제자리에서 넓히지 않는다.
- **숫자 QUERY input/result2는 바꾸지 않는다.** 이 계약은 entry/profile/보고서 provenance를
  담지 않고 검증된 text row·encoding·model/query space만 담는다. full public text와 recipe는
  동일하므로 새 QUERY3를 만들 이유가 없다.
- 같은 이유로 QUERY2만 감싸는 `embedding-work-batch-input/result/2.0`과 수치 shard1도
  그대로 재사용한다. metadata 확장 때문에 새 모델·벡터 공간·GPU 이미지·batch queue를
  만들거나 기출 벡터를 다시 계산하지 않는다.
- 기존 public receipt2와 coordinator2도 원본 request/context SHA와 QUERY2 file-set을
  고정하고 report envelope를 내장하지 않는다. 후속 native 연결에서 이 실제 closure를
  검증해 재사용한다. 단지 source provenance가 늘었다는 이유로 receipt/coordinator 버전까지
  일괄 증분하지 않는다. 입력 context를 내장한 native request와 read reply/parent Artifact 등은
  각각 실제 필드를 확인해 필요한 closed successor만 추가한다.

## 짧은 설계 검토

1. 책임: Catalog가 원본·Graph·accepted 보고서·정식 index를 resolve하고, 기존 QUERY owner가
   현재 인증된 사용자의 요청을 받아 검증된 텍스트의 QUERY2만 실행한다.
2. 정본: accepted 원본 Artifact/Graph/report와 등록된 numerical row. 새 source reference와
   similarity response는 정본의 고정 pointer와 관측값이다.
3. revision: entry1/2 및 index3/4를 구분하며 기존 context3는 원래 핀으로 계속 읽는다.
4. pointer: source·base accepted analysis·V11 successor·원문 raw SHA·semantic SHA·profile·Graph·
   policy·index revision/member/hash를 각각 검증한다. missing/latest 대체나 caller-supplied 권한은 없다.
5. 접근: source revision map, encoding hash map, ordered rank, immutable index shard 목록.
6. 구조: 기존 indexed Registry 조회·bulk source resolver·bounded shard read를 재사용한다.
   새 DB 테이블/별도 검색 엔진/새 큐는 필요하지 않다.
7. 비용: source/proof 준비 O(N), vector score O(ND), top-k는 기존 구현과 상한을 유지한다.
   현재 public metadata 최대16,384 source와 bounded byte budget을 존중한다.
8. 동시성: 기존 request identity/idempotency/CAS/lease를 유지한다. partial head 선택 뒤에는
   Graph/policy/index를 핀하고 재전송 때 재권한 확인한다. 뒤늦게 증가한 latest와 합치지 않는다.
9. 의존: frozen contracts → 순수 projection/수치 score → Catalog application/ports → 설치 adapter.
   GUI에는 정본·권한·랭킹 규칙을 재구현하지 않는다.
10. 실패: 미준비/회수/해시 불일치를 구분하고, 다른 source class나 구형 projection으로 조용히
    fallback하지 않는다. 기존 FAILED는 보존한다.
11. 더 단순한 대안: 숫자 포맷까지 모두 새 버전으로 만드는 것은 불필요하다. 필요한 proof
    carrier만 successor로 두고 기존 QUERY2를 유지하는 것이 요구를 만족하는 최소 변경이다.

## 반영 순서

1. 실제 운영 partial 검색을 인증된 사용자로 확인한다. 현재 API/Catalog public 경로는 이미
   source 후보와 동일하므로 의미 없는 서비스 재시작은 하지 않는다.
2. metadata successor의 JSON Schema를 먼저 정의하고 old/new reference·index 조합을 검사한다.
3. QUERY reader가 index3/4를 모두 읽도록 설치 검증한 뒤에만 INDEX4 writer를 활성화한다.
4. AI 정식 Graph/base2/V11 보고서 producer와 증분 등록을 실제 canary로 닫는다.
5. 전체 기출520 검증·검색 범위 확정 후 정확한 구 projection 소비자만 조사·정리한다.

## 실제 native carrier 범위 — 2026-10-31

기존 public request3는 context3를 내장하므로 그대로 넓히지 않는다. 독립적인
`reference-query-workflow-request/4.0`은 context4와 index3/4의 정확한 source proof를
담는다. Workflow definition2/result2/receipt2/step-output2/launch1/coordinator2 및
수치 QUERY2/shard1은 같은 의미이므로 재사용한다. native Job의 protocol pin은 새 request
schema SHA에 고정한 별도 metadata family로 구분한다. 원 request3/native protocol2의
역사적 hash는 변하지 않는다.

동일한 공개 풀이 text/hash와 수치 공간이면 context3/4에서 QUERY2의 row/encoding 및
input_set_sha256은 같아야 한다. 출처·base/result/report/Graph/policy/index identity가
다르면 context와 외부 request hash는 달라야 한다. QUERY2에도 context_request_sha256과
원 Job ID가 있으므로 전체 native request SHA까지 같다고 주장하지 않는다. 수치 동등성과
출처 envelope의 동일성을 혼동하지 않는다. 새 native Job metadata pin은
`reference-query/3.0`과 request4의 exact schema SHA를 사용한다.
새 schema·parser·native read/submit/prepare/registration을 먼저 연결·검증하며 receiver가
설치되기 전 INDEX4 writer 또는 현재 GPU numerical runtime은 활성화·교체하지 않는다.

Completed-read RPC는 result에 context를 내장하므로 `system-rag-similarity-read/4.0`을
추가한다. request4/reply4는 기존 exact Workflow/hash selector로 context3 또는4를 읽는다.
read3의 bytes/허용 결과는 그대로 유지하고 context4를 read3으로 위장하지 않는다. 새 API
client 선택은 read4 receiver 설치와 함께만 활성화한다. 새 queue/DB/수치 작업은 없다.

### Routed parent의 실제 closure

실제 source의 public QUERY parent는 `embedding-batch-plan/1.4`이며 INDEX parent1.3과
다르다. parent1.4 selection의 anchor/view는 context3 proof에 고정되고 preparation2는
그 parent request를 내장한다. registered entry2/index4를 넣기 위해 이 기존 schema를
넓히지 않는다. 필요한 successor는 이 두 metadata carrier로 제한하며 기존 allocation/
route/bound/finite numerical batch/checkpoint 형식과 indexed publication key는 재사용한다.
재전송 시 저장된 preparation과 selection의 원래 schema family를 먼저 확인하고 그대로
읽는다. 새 family 이름을 옛 Artifact pointer에 붙여 재해석하지 않는다. CPU/GPU의 부분
coverage와 전환 중 index3/4의 차이는 source별 exact proof로 확인하며, 전체 target-set을
같다고 가정하거나 구형 private/accepted projection으로 fallback하지 않는다.

이 successor는 QUERY parent1.5/preparation3로 명시한다. 원래 file-set commit owner가
고유 publication key로 찾은 정식 primary member의 typed pointer를 제공하도록 확장한다.
같은 조회에서 이미 검증한 원 request의 member schema/media/hash를 사용하며, payload를
다시 복사하거나 다른 서비스의 private DB를 읽지 않는다. 기존 find API의 결과와 성능
경계는 유지한다. preparation과 selection replay의 두 호출자가 이를 사용해 원래 family를
고정한다. indexed key lookup·최대1,024개의 작은 member metadata 검사이며 새 테이블/
index/queue는 없다. Artifact의 실제 byte/lifecycle/권한 재검증은 기존 독립 owner가 유지한다.

## INDEX4 producer 연결

새 설치본의 public discovery는 기존 Catalog의 authorized capture에서 plan4/request4를
발행한다. 기존 request3를 replay하거나 반대 장치에 match할 때는 원래 plan3를 보존한다.
정본은 accepted report/Graph/기존 수치 row이며 새로운 profile/encoding을 발명하지 않는다.
INDEX parent1.3은 entry1 anchor에 고정돼 있으므로 INDEX-only parent1.6을 추가한다.
이는 QUERY-only1.5와 별개이며 최대1,024 source, child view1개, allocation/route/bound1,
기존 DOCUMENT input 및 수치 batch1과 parent Job/lease/transaction을 그대로 쓴다.
기존 schema bytes는 불변이다.
source request4일 때만 parent1.6을 선택하고, 원 request3는 parent1.3을 유지한다.

현재 index3→4 전환 중 membership 비교는 원래 pointer의 실제 family/hash를 확인한다.
새 helper는 binding3/4와 index3/4를 명시적으로 받고, 기존 public3 helper는 입력 범위를
넓히지 않는다. revision→entry map과 binding hash의 정렬 비교 O(N log N)/O(N), 기존
indexed capture와 publication key를 사용한다. 새 테이블/큐/index/권한 캐시는 없다.
source·권한은 준비 전후 같은 transaction에서 재확인하고 원 publication/START idempotency,
CAS와 실패 이력을 보존한다. 누락/해시/철회는 명시적으로 거부하며 latest로 치환하지 않는다.
옛 anchor를 재사용하면 V11 proof가 손실되고 새 수치 wire까지 만드는 것은 불필요하므로
source metadata만 successor로 둔다. reader4 설치와 migration 검증 전 writer를 활성화하지 않는다.
