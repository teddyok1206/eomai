# 증분 임베딩의 1,024건 초과 자료집 확장 경계

상태: 설계 결정 후보, 운영 미구현 (2026-10-27 UTC). 현재 GPU 우선 배포의
546개 적격 자료집을 재해석하거나 실행 중인 INDEX/QUERY의 pin을 바꾸지 않는다.

첫 source checkpoint: `segmented-embedding-index/1.0` JSON Schema 2020-12와
동일 bytes의 package resource, frozen typed root/segment value, 고정 길이·정렬·
중복·자체 hash 검증을 추가했다. 이것은 **포인터 형식**뿐이다. 실제 segment의
source 수·범위·input hash 및 전체 자료집 완결성은 아직 Catalog가 검증하지
않으므로 새 root를 등록하거나 QUERY에 선택할 수 없다.
계약·기존 device-pair 집중 테스트는 77 PASS, Ruff/strict mypy PASS다. 소스
wheel에는 새 typed module과 schema resource가 포함됨을 확인했다. 이 증거는
Catalog publication, 전체 자료집 인가, 운영 설치 또는 1,025건 처리 성공이 아니다.
후속 pure Catalog content validator는 실제로 다시 연 segment manifest의 장치,
namespace, 정렬 범위, 1,025건 합계, Graph/정책 pin 및 device-independent
source/profile/input hash를 root descriptor와 대조한다. 합성 1,025건을 포함한
집중 테스트는 80 PASS다. 이 검증 함수는 권한·원본 Artifact·전체 모집단을
읽지 않으며, 그 세 경계를 맡을 Catalog application은 아직 구현되지 않았다.
Catalog의 source-first metadata page SQL과 extra-row/중복 검증도 소스에
추가했다. 기존 적격성 predicate를 재사용하며, page마다 최대 1,024개와
경계 확인용 1개만 읽는다. 이 함수는 권한을 부여하거나 현재 정책의
`maximum_sources`를 전체 모집단이 아닌 page 크기로 재해석하지 않는다.
후속 정책·인가·전체 모집단 검증이 없으므로 운영에서 호출하거나 root를
게시하지 않는다. 순수 페이지 검증은 합성 1,025·2,048·10,000건의
순서·중복 없는 연결을 확인했지만, PostgreSQL query plan이나 운영 규모의
전체 출처 검증을 증명하지는 않는다.
후속 `education-retrieval-access-policy/1.3` 후보는 JSON Schema 2020-12와
frozen typed value에서 `maximum_page_sources`(최대 1,024)와
`maximum_population_sources`(1,025~1,048,576)를 분리한다. 전체 상한은
`page × 1,024 segments`보다 클 수 없다. 기존 1.1/1.2 parser의 지원 버전
목록에는 아직 넣지 않았다. 즉 이 값의 검증은 현재 service identity·Graph
인가나 운영 활성화가 아니며, 구버전 `maximum_sources`의 의미를 바꾸지 않는다.
게시 단계는 기존 Catalog owner의 append-only 정책 테이블·실제 service
identity/source/corpus 잠금·동일 revision 재전송을 재사용한다. 새 게시 버전
dispatcher만 1.3을 받아들이며, 기존 **runtime-supported** 1.1/1.2 parser와
조회는 의도적으로 1.3을 거부한다. 1.3의 별도 pinned metadata resolver도
schema/revision/hash를 다시 검증하지만 그 자체는 source 접근 권한이 아니다.
이렇게 게시와 실행 인가를 나누는 것은 단순히 기존 `maximum_sources`를
page cap으로 재해석하는 방식이 이전 release의 의미를 깨뜨리기 때문이다.
격리 PostgreSQL에서는 1.3 append-only 게시·동일 요청 재전송·독립 root
동시 게시와 구형 reader 거부를 확인했다. 그러나 이 게시 검증만으로
Graph 전체 모집단의 profile/input closure나 segmented root publication이
완성되지는 않는다.
후속 Catalog service authority는 동일한 실제 DB/service identity, 원본
access policy, corpus/Graph publication 검사를 1.1/1.2와 공유하되, 1.3에는
`maximum_page_sources`만 적용하는 별도 진입점을 둔다. 구형 진입점은
1.3 값을 받아도 거부한다. 한 active root transaction의 bounded source-first
page는 조회 전후에 같은 1.3 policy를 재검증하고, 전체 순회는 페이지별
`(source revision, accepted analysis run)` 해시와 범위·건수만 유지한다.
이 요약은 최대 1,024개 segment descriptor의 파생값이지 전체 profile,
input-text hash 또는 등록된 Artifact가 아니다. 그러므로 Graph 원천/풀이보고서
프로파일의 실제 검증과 CPU/CUDA 결합 전에는 index 등록에 사용할 수 없다.
페이지별 후속 source capture는 새 worker reader를 만들지 않고 기존 Catalog의
profile·풀이보고서·Artifact 검증 본문을 재사용한다. metadata page의 source/run
ID를 최대 1,024개로 고정한 뒤 같은 root transaction에서 실제 candidate pool과
Artifact 입력을 읽고, 반환된 source/run 쌍이 페이지와 정확히 일치하는지
확인한다. 페이지를 다시 읽어 권한·내용이 바뀌었으면 거부한다. 이 경로는
O(page) 작업 메모리만 쓰며, 아직 전체 root의 모든 page/profile/input-text
closure나 운영 publication을 허용하지 않는다.

## 확인된 제한과 결정

현재 `EmbeddingRegistryLookup.maximum_sources`, 자료 접근 정책, Catalog의
`population_membership_statement`, `prepare_missing_embedding_bindings`,
`EmbeddingIndexManifest`/`MixedEmbeddingIndexManifest`가 각각 최대 1,024건을
가정한다. 원천 집합이 이보다 크면 `EMBEDDING_REGISTRY_SCOPE_LIMIT`로 닫는 것이
정상이다. 단순히 `maximum_sources`만 늘리거나 처음 1,024건을 전체 집합인 것처럼
게시하지 않는다. 후속 버전은 **한 번에 다루는 행 수**와 **전체 자료집 크기**를
분리하고, 작은 고정 크기 segment와 그 순서를 고정한 root manifest로 확장한다.

## 필수 설계 경계

1. **책임:** Catalog는 실제 operator/service 권한으로 Graph snapshot의 적격
   source 집합을 읽고 segment를 게시한다. Orchestrator는 기존 Workflow와 원자적
   claim/lease를 사용한다. worker는 staged 입력만 읽고 결과를 반환한다.
2. **정본:** 게시된 Graph snapshot, 접근 정책, accepted source/profile, 등록된
   Artifact revision과 SHA-256이 정본이다. cursor나 로컬 캐시는 권한이 아니다.
3. **ID·revision:** 새 root index revision은 동일 namespace/view/device의 ordered
   segment manifest pointer들을 고정한다. 각 segment revision은 최대 1,024개
   binding을 가진다. 기존 V1/V2 단일 manifest는 변경하지 않는다.
4. **포인터:** segment마다 schema/media/lifecycle/hash와 정확한 source/profile/
   input-text hash를 검증한다. root는 segment hash·범위·순서·중복 없음·전체 집합
   fingerprint를 검증한다. CPU/CUDA 동등성은 같은 source/profile/input hash 집합을
   각 device의 실제 binding에 대조하며 단순 건수 일치로 인정하지 않는다.
5. **접근:** 자주 하는 작업은 `(Graph revision, source revision)` 순서의 bounded
   keyset scan, source별 binding 조회, 변경된 segment 교체, root별 ordered iteration,
   장치별 같은 source의 exact pair 조회다. 현재
   `candidate_pool_analysis_statement`는 `analysis_run_id`로 정렬해 제한하므로,
   그 조회에 단순 cursor만 붙이면 source 범위가 page 사이에서 겹칠 수 있다.
   후속 조회는 승인 source revision과 analysis run ID를 함께 정렬·고정한 뒤
   LIMIT를 적용해야 한다. 한 source revision에 여러 accepted analysis가 매칭되면
   현재 정본 선택 규칙으로 정확히 하나를 고정하고, 모호하면 fail-closed한다.
   offset 기반 전수 재검색을 피한다.
6. **구조·인덱스:** Catalog의 기존 Graph membership 관계와 source/binding 고유키를
   재사용한다. keyset 정렬 키에 맞는 B-tree 인덱스가 실제 query plan에 없을 때만
   새 인덱스를 추가한다. 현재 `knowledge_snapshot_analyses`에는
   `(graph_snapshot_revision_id, analysis_run_id)` 고유키와
   `(source_kind, source_revision_id)` 인덱스가 있지만, 계획한 source-first
   keyset을 하나로 뒷받침하는지는 확인되지 않았다. 후속 disposable DB의
   `EXPLAIN`으로 입증한 뒤 필요할 때만 composite index migration을 낸다.
   root에는 payload가 아닌 segment pointer만 둔다.
7. **규모·복잡도:** page·segment당 최대 1,024개, numerical batch는 현재 작은
   유한 묶음을 유지한다. 전체 N건의 최초 순회는 O(N)이다. 전체 segment 수 S,
   변경 segment 수 k일 때 root 재게시에는 O(S) pointer 순회와 변경분 O(k)의
   segment 검증이 필요하다. O(N²) 중복 검사 대신 정렬 범위와 고유키를 사용한다.
   root pointer 수에는 별도 상한을 둔다.
8. **동시성:** 한 Graph snapshot/policy pin에서만 segment 집합을 만든다. 권한·
   source·revision이 순회 중 바뀌면 root 게시를 거부하고 같은 request identity로
   재검증한다. root 교체는 기존 Registry의 transaction/idempotency 경계를 따른다.
9. **의존성:** JSON Schema 2020-12 successor → frozen typed values → Catalog
   application → PostgreSQL/NAS adapter 순서다. 새 queue, 별도 vector DB, worker의
   DB/NAS 직접 접근은 도입하지 않는다.
10. **오류·재시도:** 누락 page, 중복 source, stale cursor, 권한 철회, hash 불일치,
    불완전한 CPU/CUDA pair는 명시적 실패다. 재전송은 동일 snapshot·policy·
    request를 재사용하며 `latest`로 바꾸지 않는다. 이전 성공 root는 보존한다.
11. **단순 대안의 한계:** 1,024 상한을 크게 올리는 방식은 정책·조회·manifest·
    응답 크기와 원자적 검증 시간을 함께 키워 현재 계약을 깨뜨린다. 전체 집합을
    여러 page로 읽되 V2 manifest 하나에 다시 합치는 방식도 같은 한계다.

## 구현·검증 순서

후속 source 작업은 (1) segment/root Schema와 typed model, (2) 권한이 고정된
keyset source read, (3) 증분 segment publication과 원자적 root 교체,
(4) query-side segment iterator와 CPU/CUDA exact pair, (5) 재전송/동시성/
중단을 disposable PostgreSQL에서 검증하는 순서다. 1,025·2,048·10,000개
합성 자료의 누락/중복/경계값과 실제 query plan·메모리 상한을 검사한다. 읽기
성능과 full-index 재게시 비용을 실측하기 전 운영 활성화하지 않는다.

이 설계는 현재 546건 catch-up의 완료 증거가 아니며, GPU default/fallback/
rollback의 남은 live gate를 대체하지 않는다.
