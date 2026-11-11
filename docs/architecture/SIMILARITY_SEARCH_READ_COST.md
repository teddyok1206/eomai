# 유사도 검색·완료 결과 조회 비용 개선

2026-11-11. 범위는 기존 DB 유사도 검색의 준비·실행·결과 조회다. 새 검색 엔진이나
Graph/권한 우회 경로를 만들지 않는다. 운영 결과와 source 검증은 별도 기록한다.

## 근거와 순서

- 완료 결과의 실제 HTTP 재조회는 약 23초, 최초 결과 생성은 약 186초였다.
- 같은 완료 요청의 SQL 의존관계 관측만 읽기 전용으로 측정하니 11.35초였다.
  1,556개 source를 7페이지로 나누며 142,986개 Graph pointer를 확인했다.
  그룹별 digest 작업은 약 4초이고 나머지 대부분은 반복 membership 페이지 조회다.
- 순수 1,024차원 후보 1,128개 cosine/정렬은 합성 입력에서 약 46ms였다.
  이는 전체 검색 시간이나 GPU 추론 시간의 측정이 아니다.

우선 전체 membership 반복 조회를 없애고, 최초 조회의 동일 root 내 공개 풀이 capture
중복을 줄인다. 그다음 정확히 같은 QUERY encoding 재사용과 GPU 준비 비용을 실제 경로에서
확인한다. timeout 증가, 검증 생략, DOCUMENT 벡터의 QUERY 대용은 해결책으로 삼지 않는다.

## 1차 변경: 전체 membership 한 번 조회, 세부 자료는 기존 페이지 유지

1. **책임**: Catalog의 기존 `local_indexing_source_paging`이 metadata 목록을 읽는다.
   `public_solution_population_dependencies`와 `public_solution_source_capture`가 사용한다.
2. **정본**: 고정 Graph의 association·pointer/node, 현재 Item/analysis lifecycle과 실제
   사용자/INDEX 권한이다. metadata 목록은 admission이나 권한 cache가 아니다.
3. **identity**: 기존 source revision/base analysis 쌍과 순서를 유지한다. 새로운 entity,
   schema, Artifact, DB table, revision은 만들지 않는다.
4. **검증**: 기존 공식 eligibility SQL 그대로, 전체 최대값+1로 초과 감지, ID 형식·중복·정렬
   검증, 작업 후 fresh membership 일치와 기존 전체 provenance/권한 확인을 유지한다.
5. **접근**: 전체 후보의 정렬 순회 2회(전/후), 페이지별 bounded lookup. 각 페이지마다 같은
   전체 Graph eligibility를 새로 계산할 필요가 없다.
6. **구조**: 최대 16,384개 작은 identity tuple을 한 번 읽고 기존 256개 페이지로 나눈다.
   source 본문·보고서·벡터는 여전히 기존 페이지별 reader/budget을 따른다. DB/index 추가 없음.
7. **복잡도**: 한 번의 eligibility 비용 E, source 수 N, 페이지 수 P일 때 membership
   비용을 O(P×E)에서 O(E+N)로 줄인다. metadata 공간 O(N); 큰 payload는 복사하지 않는다.
8. **동시성**: 기존 caller root transaction·READ COMMITTED·before/after 관측을 유지한다.
   사이의 membership 변경은 명시적 실패다. frozen 결과를 latest로 바꾸지 않는다.
9. **의존성**: application owner → Catalog SQL adapter → 기존 모델. UI/worker로 규칙을 옮기지 않는다.
10. **실패/재전송**: 기존 오류·원 요청·저장 ranking identity를 보존한다. membership/hash가 바뀌면
    재계산으로 숨기지 않는다. 성공한 완료 결과 재조회는 새 QUERY를 만들지 않는다.
11. **대안**: 페이지마다 keyset 조회는 코드가 이미 있지만 매번 전체 Graph CTE를 재평가한다.
    작은 제한된 identity 목록을 한 번 읽는 것이 더 단순하며, 전체 Artifact materialization과 다르다.

검증: 기존/새 페이지 및 dependency SHA 동일, 0/경계/초과/중복/순서 오류, 중간 변경 거부,
큰 합성 모집단의 SQL 횟수·시간, 실제 동일 요청 재조회 전후 지연과 ranking SHA 비교.
운영 반영은 관련 실행의 고정 runtime을 보존하는 호환 Catalog 릴리스로 한다.

## 2차 변경: 같은 조회 transaction의 풀이 해석 재사용

기존 INDEX의 `public_solution_index_read_set`을 실제 두 번째 사용 사례인 공개 QUERY
최종 재검증에도 적용한다. 정본·schema·DB·GPU 실행은 그대로다. 첫 읽기는 전체 파일,
보고서, 관계를 엄격히 확인하고, 같은 DB root/thread/settings/실제 scope/recipe/최대값에서만
그 immutable 해석을 재사용한다. 매번 fresh SQL closure와 현재 권한/provenance는 확인한다.
첫 before/after가 다르거나 후속 closure가 달라지면 실패하며 다시 해석해 숨기지 않는다.

접근은 한 transaction의 단일 typed read-set key 조회 O(1)과 기존 SQL closure O(N+관계 수)다.
큰 보고서 사본을 추가하지 않고 기존 frozen capture를 참조한다. 새 root/rollback/다른 scope나
recipe에서 재사용하지 않는다. QUERY는 clean root에서만, 기존 INDEX는 정확한 clean savepoint도
허용한다. dirty context는 기존 strict capture를 사용한다. session 종료 후 남는 권한/TTL cache는 없다.
기존 INDEX 구현을 재사용하므로 별도 프레임워크나 공통 서비스가 필요 없다.

전체를 매번 해석하는 대안은 현재 첫 결과의 긴 지연 원인이다. 캐시만 믿는 대안은 revocation을
놓친다. 따라서 해석만 재사용하고 권한/관계 재관측을 남긴다. 회귀 검사는 source/report/producer
변경, 다른 사용자·recipe·thread·root·nested frame, 중간 실패/rollback, canonical bytes 불변을 포함한다.

완료 ranking의 동시 읽기는 배타 publication lock 없이 처리한다. 저장본이 없을 때만 기존
원 QUERY advisory lock을 얻고 `find`를 다시 실행한다. 두 최초 요청이 경합해도 한 번만
compose/commit하고, 이미 저장한 immutable 결과의 재조회는 서로를 기다리지 않는다.
양쪽 경로 모두 기존 before/after source/권한 검증을 수행한다.

## 3차 변경: 동일 index 파일의 순수 해석 결과 재사용

실제 고정 index5 파일7,859,685bytes의 official pinned read는0.081초였지만,
같은 파일의 schema/Pydantic/자기hash 검증은2.966/2.955/2.937초였다. QUERY 준비와
관측은 새 DB root마다 같은 manifest를 다시 해석한다. 권한 확인을 없애지 않고 이
순수 계산만 줄인다. 단일 검색의429회 source 관측 기록은 다른 관측이 섞일 수 있고
해당 수를 모두 manifest parse 횟수나 독립 GPU 실행 횟수로 해석하지 않는다.

1. 책임/정본: 기존 Catalog `embedding_registry_catalog_adapter`의 index decoder만
   확장한다. 정본은 원래 Artifact bytes이며 registry·source·권한의 소유자는 그대로다.
2. identity/pointer: 해석 cache key는 schema와 **완전히 같은 bytes**다. 경로·latest·사용자·
   승인 여부를 key/결과로 쓰지 않으며 기존 logical/revision/Artifact/hash 검사를 바꾸지 않는다.
3. resolution: `_read_index_member`의 매 root 파일 읽기·SHA·producer·schema/media·file set과
   각 caller의 실제 권한/registry/pin 검사는 그대로다. 그 뒤 순수 decoder만 재사용한다.
4. 구조/복잡도: 표준 bounded LRU2개, entry raw 최대16MiB로 제한한다. raw key 최대32MiB와
   그에 선형인 frozen model만 남는다. 첫 해석O(B+bindings), hit는새 bytes hash/equalityO(B),
   retained raw/model 공간O(제한한 B). 큰 파일은 기존 strict decoder로 처리하며 거부하지 않는다.
5. 불변성: index1–5의 도달 가능한 모든 계약 모델은 frozen이고 collection은 tuple이다.
   사전/Session/ORM/authority/열린 파일을 cache에 넣지 않는다. 결과는 정본 조회 권한이 아니다.
6. 동시성: `functools.lru_cache`의 thread-safe metadata를 사용한다. 동시에 첫 miss가 난 경우
   같은 순수 해석이 중복될 수 있으나 새 Job·GPU·publication을 만들지 않는다.
7. 실패/무효화: 실패는 저장하지 않는다. schema/bytes 변경은 miss, eviction은 재해석이다.
   설치 code가 바뀔 때 owner 프로세스 교체로 cache도 사라진다. cross-root 권한 cache나 TTL은 없다.
8. 의존방향/범위: 기존 Catalog adapter 안의 private 함수다. Worker·API·DB schema·모델·
   numerical space·released JSON Schema 변경은 없다. INDEX/진행 중 실행은 배포 대상이 아니다.
9. 대안: 매 root strict parse는 확인된3초 비용을 반복한다. 거대한 상주 모델 서비스나 QUERY
   벡터 재사용 계약보다 작고, 이미 읽어 검증한 같은 bytes의 해석 재사용으로 충분하다.
10. 검증: same bytes/schema decode1회, 변경·invalid·oversize·eviction, 중첩 불변성, 매 root의
    파일/provenance 확인, 실제 파일의 cold/warm 시간과 메모리, 최초 검색 전후를 확인한다.
11. 배포: QUERY owner와 Catalog의 기존 호환 릴리스에서만 활성화한다. 수치 runtime/INDEX
    pin을 바꾸지 않으며 실제 첫 결과 확인 전에는 전체 목표 완료로 표시하지 않는다.

별도 새 검색 사이 QUERY 벡터 재사용은 현재 없고, 같은 요청 replay는 원 결과를 사용한다.
다문항 한 요청은 이미 한 backend lifetime을 공유한다(최대32개). 따라서 이 단계에서
새 GPU 상주 서비스나 QUERY reservation을 만들지 않는다. 별도 요청의 벡터 재사용을
추가하려면 현재 context와 원 numerical producer를 연결하는 additive reuse receipt가
필요하며, 이전 native 실행을 새 실행인 것처럼 기록해서는 안 된다.
