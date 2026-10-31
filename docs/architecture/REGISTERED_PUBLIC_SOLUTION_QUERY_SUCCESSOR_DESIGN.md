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
