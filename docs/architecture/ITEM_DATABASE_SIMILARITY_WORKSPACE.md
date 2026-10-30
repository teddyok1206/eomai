# DB 조회·유사도·배치 연결

2026-10-30 UTC. 창작 보고서 증분 임베딩 목표에 추가된 사용자 화면 요구다.
기존 [공통 풀이 임베딩 설계](SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md)와
[운영 연결 기록](../operations/CREATIVE_INCREMENTAL_EMBEDDING_ACTIVATION_2026-10-30.md)을 따른다.

## 사용자 동선

`DB` 안에 `조회 / 배치 / 유사도` 세 탭을 둔다. 기존 `문항 DB` 탭은 `조회`로 바꾼다.
조회에서 문항 하나를 선택하고 `유사도 검색`을 누르면 유사도 탭으로 이동해 진행 상태와
결과를 본다. 결과의 문항을 선택하면 조회 탭의 기존 상세 열람을 사용한다. 그곳에서 원본/
미리보기 열기, 변형, 배치 목록 담기를 기존 조건에 따라 할 수 있다.

탭 이동은 기존 검색 필터·조회 목록·조립 초안·저장된 배치·진행 중 검색을 초기화하지 않는다.
유사도 탭을 눌렀다는 이유만으로 새 수치 계산이나 재제출을 하지 않는다.
요청 중과 서버가 확인한 PENDING 동안 작은 회전 표시와 ‘요청 후 경과시간’을 보여준다.
다른 탭을 보고 있어도 유사도 탭의 작은 표시로 작업 중임을 알 수 있다. 서버가 확인해 준
경우에만 준비/자원 대기/계산/결과 읽기를 구분한다. 경과시간은 전체 요청의 클라이언트
관측값이며 GPU 계산 시간이나 완료 예상 시간이 아니다. 임의의 퍼센트는 만들지 않는다.
관찰 timeout은 실패 확정으로 바꾸지 않고 원래 key로 재확인하게 안내한다.
서버가 PENDING으로 접수를 확인한 경우에만 같은 요청을 2.5초 이후 다시 관찰한다.
동시에 하나만 관찰하고 결과·오류·다른 검색 시작 시 이전 타이머를 중지한다. timeout이나
terminal FAILED를 자동 재실행하지 않는다. 경과시간 표시는 별도의 가벼운 로컬 시계다.

## 책임과 데이터 경계

1. UI는 탭·선택·표시만 맡는다. 실제 검색은 기존 Catalog/Orchestrator의 공식 QUERY와
   pinned similarity read를 사용한다. 브라우저의 로컬 cosine, Graph 키워드 검색으로 대체,
   별도 queue/벡터 DB는 만들지 않는다.
2. 정본은 기존 Item/외부 원본 revision, 등록 보고서, Graph, embedding index다. 화면의 결과와
   선택 상태는 일시적인 read projection이며 별도 문항·보고서·원본 복사본을 저장하지 않는다.
3. 선택은 `GRAPH_ITEM`과 `EXTERNAL_SOURCE`를 구분한다. Graph 문항은 Item/revision/manifest와
   Graph revision/hash, 외부 원본은 source/revision/observation hash를 유지한다. 외부 원본의
   등록 Item 연결은 서버의 기존 공식 등록 계보에서만 해석한다.
4. 원문·보고서·index·QUERY proof와 actual operator 권한은 서버에서 재검증한다. 결과에서
   열람하는 외부 원본도 원래 source revision을 대조하며 최신본으로 조용히 바꾸지 않는다.
5. 주요 접근은 탭의 O(1) 선택, bounded 결과의 순서 순회, request sequence/key의 O(1)
   대조다. DOM에는 제한된 결과와 작은 metadata/pointer만 보관한다. DB schema/index나
   새로운 persistent cache는 필요 없다.
6. 계산·등록 transaction, claim/lease, index CAS와 멱등성은 기존 owner가 유지한다.
   UI의 중복 클릭은 같은 진행 요청을 중복 제출하지 않으며 명시적 재확인은 원래 key와
   pin을 유지한다. 관찰 timeout은 서버 실패나 미처리를 의미하지 않는다.
7. UI → 기존 BFF/API application → Catalog/Orchestrator 방향을 유지한다. 결과의 표시용
   metadata는 공식 조회 projection에서 얻는다. model-supplied path/HTML/권한을 받지 않는다.
8. `PENDING`, `READY`, `UNAVAILABLE`, `FAILED`를 구분한다. 보고서/벡터 미준비는 빈 검색
   성공으로 표시하지 않는다. 점수는 검색 관측값이지 동일 풀이 비율이나 교육 품질 승인이 아니다.
9. 느린 A 응답이 새 B 검색을 덮지 않게 sequence로 구분한다. 결과가 도착해도 사용자가
   다른 탭으로 이동했으면 강제로 탭을 바꾸지 않는다. 선택 해제·문항 변경 후 오래된 상세
   응답과 원래 문항의 배치 대상을 남기지 않는다.
10. 기존 조회 상세와 조립 draft를 재사용한다. 유사도 탭 안에 별도 미리보기/배치/승인
    시스템을 복제하면 pointer 검증과 사용자 동선이 이중화되므로 하지 않는다.
11. 새 UI adapter는 실제 owner/HTTP consumer 연결 뒤 활성화한다. 화면 단위 테스트나
    합성 응답만으로 운영 검색 완료를 선언하지 않는다. 기존 GPU runtime pin은 유지한다.

## 검증

- 세 탭의 mouse/keyboard/ARIA 이동 및 모바일 배치.
- 조회→유사도→조회, 원래 필터·배치 보존, 다른 종류의 결과를 정확한 상세로 열기.
- 빠른 A/B 검색, 탭 이동 중 완료, 이중 클릭, timeout 후 동일 key 재확인, 무권한·stale 거부.
- 실제 official QUERY/index read에 연결한 뒤 source revision/hash 일치, 후보의 기존 상세
  열람과 배치 저장을 인증된 운영 경로에서 검증한다. UI canary로 새 문항을 생성하지 않는다.

현재는 기존 증분 임베딩 목표와 함께 구현 중이다. public QUERY 실행/공식 consumer의 운영
연결이 끝나기 전까지 이 화면만 별도로 검색 가능 상태로 배포하지 않는다.
