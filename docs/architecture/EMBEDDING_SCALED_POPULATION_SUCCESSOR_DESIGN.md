# 증분 임베딩의 1,024건 초과 자료집 확장 경계

상태: 설계 결정 후보, 운영 미구현 (2026-10-27 UTC). 현재 GPU 우선 배포의
546개 적격 자료집을 재해석하거나 실행 중인 INDEX/QUERY의 pin을 바꾸지 않는다.

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
   장치별 같은 source의 exact pair 조회다. offset 기반 전수 재검색을 피한다.
6. **구조·인덱스:** Catalog의 기존 Graph membership 관계와 source/binding 고유키를
   재사용한다. keyset 정렬 키에 맞는 B-tree 인덱스가 실제 query plan에 없을 때만
   새 인덱스를 추가한다. root에는 payload가 아닌 segment pointer만 둔다.
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
