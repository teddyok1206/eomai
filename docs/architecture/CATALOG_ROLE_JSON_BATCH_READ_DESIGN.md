# Catalog 역할 JSON의 일괄 정본 읽기

2026-10-19 UTC. 이 문서는 내부 Catalog adapter의 읽기 경계이며 새 wire protocol,
권한·캐시·DB schema 또는 운영 활성화를 정의하지 않는다.

1. **책임과 경계:** 기존 `CatalogArtifactService`가 정확한 역할 JSON revision을
   일괄 읽는다. source 권한과 Workflow/step/receipt 검증은 호출 application이 소유한다.
2. **정본:** 등록된 Artifact/ArtifactRevision metadata와 해당 NAS revision의
   `result.json` bytes이다. 호출자가 준 metadata는 신뢰하지 않는다. 성공 producer Job,
   최종 역할 occurrence와 source 권한은 기존 호출 application의 provenance 검사다.
3. **Identity:** Artifact ID, revision ID와 content SHA를 각각 pin하는 frozen
   `CatalogJsonRevisionRequest`를 사용한다. 경로나 mutable current revision은 입력하지 않는다.
4. **해석 검사:** own-session joined metadata query로 Artifact/revision 소속·승인,
   manifest canonical SHA·header·primary hash/size를 검증한다. legacy result manifest와
   file-set manifest의 `result.json` primary를 지원한다. single FD의 실제 읽은 bytes를
   SHA 검증하고, open/read 전후 동일 inode·size·mtime·ctime를 확인한다. symlink, traversal,
   비정규파일과 교체된 path는 거부한다.
5. **접근 패턴:** 최대 1,024개 문항의 세 역할, 즉 3,072개의 정확한 revision PK lookup,
   중복 membership과 요청 순서의 bounded iteration이다. 단건도 같은 bulk rule을 쓴다.
6. **자료구조와 인덱스:** frozen request tuple과 revision-ID map, 기존 revision PK 및
   Artifact/Job PK join만 사용한다. 별도 테이블·영속 캐시·새 resolver를 만들지 않는다.
7. **복잡도와 규모:** metadata 조회 한 번과 O(n+b) 읽기/해시/JSON 해석이다. 최대
   3,072개 요청과 합계 256 MiB 실제 payload 예산을 적용한다. 긴 text나 바이너리를
   DB나 다른 Artifact로 복제하지 않는다. 반환 dict는 호출 안에서만 materialize한 값이다.
8. **트랜잭션과 동시성:** 읽기용 own session에서 metadata를 현재 조회한다. FD와
   root-relative directory handles로 NAS 변경 경쟁을 fail-closed 처리한다. caller의 원래
   current source authorization 및 publication 직전 재검증을 대체하지 않는다.
9. **의존 방향:** Catalog infrastructure adapter 안에 내부 typed request와 파일 읽기를
   둔다. contracts/domain에 SQLAlchemy·filesystem·NAS를 역수입하지 않는다.
10. **실패·재시도·멱등:** 누락·승인 철회·hash/size/manifest mismatch·중복 revision·예산
    초과·부분 읽기는 ValueError 또는 기존 파일 I/O의 OSError로 실패한다. latest fallback·
    부분 성공·자동 재시도는 없다.
    동일 요청의 새 호출은 다시 metadata와 실제 파일을 검증한다.
11. **더 단순한 대안:** 단건 반복은 3n metadata query이며, 기존 prehash 후 path 재읽기는
    다른 bytes를 JSON으로 받아들이는 경쟁을 허용한다. 한 owner의 batch query와 same-FD
    read로 두 문제를 함께 해결하며 다른 reader/cache framework는 도입하지 않는다.
