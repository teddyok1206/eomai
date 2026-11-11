# 유사도 검색 조회 비용 개선 — 2026-11-11

설계: [조회 비용](../architecture/SIMILARITY_SEARCH_READ_COST.md).

## 보존할 기준선

사용자가 결과 목록과 문항 열기를 확인한 기존 완료 검색을 비교 대상으로 유지한다.
실패 이력·원 QUERY·ranking Artifact·벡터를 덮어쓰거나 다시 계산하지 않는다.
기존 첫 결과 HTTP는 185.82초, 후속 결과 HTTP는 22.73초였다. 전체 최초 검색 준비부터
READY까지 8분14초였으며, 이 전체 시간을 GPU 순수 추론으로 해석하지 않는다.

## 확인된 변경과 개발 검증

- 1,556-source, 142,986-pointer 실제 SQL closure를 read-only로 비교했다.
  dependency SHA 동일, 관측 1회 11.326초 → 4.977초. 운영 HTTP 전체의 단축 증거는 아니다.
- 전체 membership은 전/후 각1회만 읽고 기존256개 source 검증 페이지를 유지한다.
- 공개 QUERY의 같은 root 안에서는 풀이 해석을 한 번만 수행하고 매번 fresh SQL closure와
  실제 권한/provenance를 확인한다. INDEX savepoint 지원은 유지한다.
- 완료 ranking hit는 publication lock을 잡지 않는다. miss는 기존 lock 안에서 다시 find하여
  concurrent 최초 조회가 중복 compose/commit하지 않는다.
- GPU/모델/벡터/점수/정렬/상위 결과 수·Graph/source 정책·API/GUI 형식은 변경하지 않는다.
- 1차 source tests212 PASS, 이후 lock hit 수정 focused13 PASS.
  disposable PostgreSQL88 PASS, 최종 lock 변경 후 같은88개 재실행도 PASS.
  Ruff·focused mypy·diff 검사 PASS.

## 운영 적용 및 실제 재조회 확인

2026-11-11 15:48 UTC, `8be39bc0426d0a902a3b3fd1112c70380810a428`의 Catalog-only
릴리스를 반영했다. 기존 설치/rollback 경계를 사용했고 API·Web·QUERY owner·수치 runtime은
재시작하거나 pin을 바꾸지 않았다. migration 변경은 없다. 설치/배포 증거는
`/var/lib/eom-similarity-read-cost-20261111`에 남긴다.

15:50 UTC 사용자가 같은 완료 기록의 `결과 불러오기`를 실행하고
“확실히 빨라졌어”라고 확인했다. 서버의 해당 결과 HTTP는 **10.241초**였다.
이전 저장 결과 재조회 **22.735초** 대비 약55% 감소이며, 첫 결과 생성185.82초와
비교해 재조회 개선율을 부풀리지 않는다. 최근 목록21.7ms·검색 상태10.9ms와도 구분한다.

- 실제 결과 요청: `req_446651c0418b46d57cf65912f14fa86b`.
- 같은 검색: `dbsearch_21addb9b2d0d15522a2b804388995c5c`.
- Catalog 저장 결과 읽기9.960초, 전후 dependency observation4.858/4.913초.
- 기존 QUERY native launch는1회 그대로이며 새 계산은 없다.
- ranking revision `rev_51a45074e05f469384e586092905eb5e`, content SHA
  `sha256:27d0a0674f642e034fc5641d73bdf8e65c9bea6129dacae15b7d569f8b122237`
  그대로다. 원래 selection·순서·실패 이력·벡터도 보존했다.
- 문항 열기는 기존 사용자 확인을 보존한다. 이번 확인은 같은 저장 결과 재조회이며,
  새 검색 최초 결과가 빨라졌다는 증거로 확대하지 않는다.

## 남은 검증

완료 결과 재조회에서도 현재 약10초 대부분은 전후 SQL dependency 확인이다. 검증을
삭제하거나 TTL 권한 cache로 바꾸지 않는다. 새 첫 결과의 비용과 QUERY 준비·수치 실행을
분리해 확인하고, 동일 QUERY encoding 재사용과 GPU 연속 처리의 기존 지원 범위를 조사한다.
실제 병목과 부합하는 최소 변경만 추진하며 전체 목표는 아직 완료가 아니다.
