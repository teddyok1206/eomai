# DB 조회와 공개 풀이 유사도 연결

2026-10-30 UTC. 기존 공통 풀이/INDEX/QUERY 설계의 UI application 연결이며 별도 검색 엔진이 아니다.

1. 책임: Catalog가 DB 선택 포인터를 등록 Item과 검색 scope로 해석한다. API application은
   기존 QUERY prepare4와 completed read3를 호출한다. Web은 진행 상태·결과·조회/배치 이동만 맡는다.
2. 정본: 외부 문항의 원본 observation/Registry registration, 원래 선택한 Graph membership,
   Registry의 canonical public index와 고정 Graph/policy/report가 정본이다. GUI 문구·경로는 식별자가 아니다.
3. identity: 외부 source/revision/observation hash 또는 Item/revision/manifest hash와 선택 Graph
   revision/snapshot hash를 보존한다. 검색은 별도의 명시적 indexed Graph scope를 가진다.
4. 해석: Graph 선택은 원래 snapshot/Item membership을 먼저 검증한다. 외부 선택은 exact
   observation과 기존 unique creative registration key를 검증한다. 검색 scope에서도 같은
   immutable Item/report가 해석돼야 한다. 삭제·불일치·없는 보고서를 다른 revision으로 바꾸지 않는다.
5. 접근: 단일 PK/unique-key lookup, Graph/source indexed membership, 장치별 index head,
   최대 64개 결과의 기존 Graph metadata batch projection을 쓴다. full list 검색이나 N+1을 추가하지 않는다.
6. 구조: 작은 discriminated selection 값과 기존 prepare4/completed context3, ordered tuple,
   revision-keyed projection map을 사용한다. DB 테이블·큐·auth cache·벡터 복사본은 추가하지 않는다.
   initial selection은 O(1) indexed metadata + 해당 source 검증, 결과는 O(K), K≤64다.
7. 원래 선택 Graph와 검색 Graph: UI 목록이 더 새로울 수 있다. initial selection에서만
   canonical index의 Graph/policy를 검색 범위로 명시적으로 선택하고 결과에 반환한다. 원래 선택한
   source Graph/hash도 검증하므로 missing/stale pointer를 latest로 대체하는 동작이 아니다.
   선택 문항이 indexed scope에 아직 없으면 준비 필요로 표시한다.
8. transaction: Catalog 선택은 현재 operator fence 아래 read-only root에서 수행한다.
   기존 QUERY owner가 별도 root에서 원문·권한·index·resource를 다시 검증하고 원래 queue/CAS로 실행한다.
   결과의 ranking은 고정 검색 Graph/report/벡터를 유지한다. 탐색용 metadata는 같은 immutable
   Item/revision/content pointer를 현재 Graph에서 일괄 재검증해 반환한다. 검색 Graph와 탐색 Graph를
   혼동하지 않고, 현재 Graph에서 없는 문항은 다른 버전으로 대체하지 않는다. 이 구분으로 기존
   배치의 current-Graph admission을 유지한다. 원문 등록을 이 검색 경로에 종속시키지 않는다.
9. dependency: contracts → Catalog selection / 기존 QUERY applications → API use case → Web.
   실제 actor/capture는 인증된 API만 공급한다. Catalog가 QUERY의 DB 권한·provider·launcher를 빌리지 않는다.
10. replay: 브라우저는 반환된 작은 prepare4를 같은 검색 key와 함께 보낸다. Catalog는 매번
    선택 포인터와 해당 exact request를 재검증하며 pinned replay에서는 새 index head를 고르지 않는다.
    PENDING은 원래 작업 조회이고 새 key/계산 생성이나 실패 기록 수정이 아니다. 새 세션을 만들지 않는다.
11. 단순 대안: browser에서 직접 DB/encoder를 호출하거나 API에 다른 ranking을 만들면 권한·
    Graph/report 출처·GPU lease·중단 복구 경계를 잃는다. 기존 metadata query에 고정 Graph+revision
    batch 선택을 추가하고 기존 native owner를 이용하는 것이 더 작고 일관된 변경이다.

HTTP에는 source selection과 optional original prepare4만 허용한다. actor/role/permission,
runtime/model/path/벡터는 받지 않는다. 같은 key로 다른 source/intent를 보내면 명시적 충돌이다.
완료 결과는 score를 풀이 동일성·과학적 정확성의 확률로 표시하지 않는다. 원래 UI의 작은 진행
표시와 `조회 → 유사도 → 조회/배치` 이동을 유지한다. 원래 legacy contracts/역사는 수정하지 않는다.
