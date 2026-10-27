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
전체 순회는 PostgreSQL `REPEATABLE READ` 또는 `SERIALIZABLE` root에서만
허용한다. 기본 `READ COMMITTED`에서는 페이지마다 snapshot이 바뀌어 동시
삽입을 cursor가 건너뛸 수 있으므로 시작 전에 거부한다.
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

### 페이지별 Artifact 검증기의 수명

현재 `PinnedArtifactReadContext.for_session`은 한 root transaction에서 같은
검증기를 재사용하며 revision 4,096개, member 8,192개와 보유·디코딩 bytes의
별도 상한을 둔다. 1,024건짜리 페이지들을 그대로 같은 검증기에 계속 넣으면
10,000건 순회 전에 이 상한에 걸릴 수 있다. 따라서 후속 전체 모집단 처리기는
**DB의 동일한 REPEATABLE READ root는 유지하되**, Artifact 검증기는 한
page 또는 더 작은 명시적 chunk마다 새로 열어야 한다. 각 chunk의 실제
member/lifecycle/hash와 `revalidate_provenance`가 끝나기 전에는 그 chunk의
source/profile/input fingerprint를 root 요약에 편입하지 않는다. 이전
검증기를 지운 뒤 그 권한을 캐시하거나 다음 page의 권한으로 재사용하지 않는다.

정책의 `maximum_page_sources`는 source 행 수 상한일 뿐 Artifact 수·bytes
상한을 대체하지 않는다. 한 page가 검증기 예산을 넘으면 부분 성공으로
게시하거나 같은 request를 몰래 더 작은 page로 재해석하지 않고 명시적으로
실패한다. 필요한 경우 새 정책 revision에서 더 작은 page 크기를 고정하고
전체 segment 상한과 함께 다시 계획한다. 1,048,576건은 schema의 이론적
상한이지 모든 자료형에서 달성했다고 주장할 수 있는 처리량이 아니다.
10,000건 이상을 대상으로 page/chunk 사이 최대 보유 revision·bytes가
bounded인지, 누락·중복 없는 요약과 마지막 권한 재확인이 성립하는지를
격리 PostgreSQL에서 검증한 뒤에만 root publication을 연결한다.

현재 페이지 capture는 비어 있지 않은 이전 페이지의 Artifact 검증기를
재사용하려는 호출을 거부하고, 정확한 페이지 재조회 후 사용한 검증기의
provenance를 마지막으로 재확인한다. 집중 테스트 29개가 통과했다. 새
검증기를 페이지마다 공급하고 전체 profile/input-text closure를 만들
상위 처리기와 10,000건 실제 Artifact 예산 검증은 아직 남아 있다.

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
   2026-10-27의 운영 DB **읽기 전용** `EXPLAIN (FORMAT JSON)`은 현재
   Graph의 source-first keyset 형태에 `ix_knowledge_snapshot_source_revision`과
   `uq_knowledge_snapshot_analysis`를 BitmapAnd로 결합한 후
   `(source_revision_id, analysis_run_id)` Sort를 적용했다. 이는 546건
   작업의 장애 증거가 아니라 대규모 페이지 순회에서 재정렬 비용을
   검증해야 한다는 근거다. disposable PostgreSQL의 실제 eligibility SQL을
   합성 10,000건에 적용한 source-first 10페이지 순회는 누락·중복 없이
   완료됐다. 같은 임시 DB에서 기존 인덱스 0.360초, 후보 복합 인덱스
   `(graph_snapshot_revision_id, source_kind, source_revision_id, analysis_run_id)`
   0.253초였다(한 환경의 진단값이며 운영 SLO가 아님). 약 0.1초의 절대
   차이만으로 운영 migration을 추가하지 않는다. 더 큰 실제 규모와 쓰기
   비용을 함께 확인한 뒤 인덱스 도입을 결정한다.
   root에는 payload가 아닌 segment pointer만 둔다.
7. **규모·복잡도:** page·segment당 최대 1,024개, numerical batch는 현재 작은
   유한 묶음을 유지한다. 전체 N건의 최초 순회는 O(N)이다. 전체 segment 수 S,
   변경 segment 수 k일 때 root 재게시에는 O(S) pointer 순회와 변경분 O(k)의
   segment 검증이 필요하다. O(N²) 중복 검사 대신 정렬 범위와 고유키를 사용한다.
   root pointer 수에는 별도 상한을 둔다.
8. **동시성:** 한 Graph snapshot/policy pin에서만 segment 집합을 만든다. 권한·
   source·revision이 순회 중 바뀌면 root 게시를 거부하고 같은 request identity로
   재검증한다. 모든 page·profile·Artifact 읽기는 동일한 `REPEATABLE READ` 이상
   root에서 수행한다. root 교체는 기존 Registry의 transaction/idempotency 경계를
   따른다.
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
