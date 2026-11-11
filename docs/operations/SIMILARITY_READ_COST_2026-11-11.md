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

## 운영 및 남은 검증

운영 적용 전 기록이다. 기존 compatible Catalog-only 설치/rollback 경계를 사용하며,
실행 중인 QUERY/INDEX/GPU pin은 교체하지 않는다. 실제 같은 검색 재조회 속도, 동일 ranking SHA,
문항 열기, 새 첫 결과의 비용은 운영 적용 후 별도 확인한다. 이어서 QUERY encoding 재사용과
GPU 연속 처리의 기존 지원 범위를 조사하고, 실제 병목과 부합하는 최소 변경만 추진한다.
