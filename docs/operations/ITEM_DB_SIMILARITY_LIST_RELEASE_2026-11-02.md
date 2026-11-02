# DB 유사도 목록·기록·결과 재열람 운영 체크포인트

2026-11-02 13:13 UTC 관측. **호환 배포 완료, 실제 신규 목록 검색 검증은 PENDING**이다.
서비스 READY와 합성 브라우저 검사를 실제 검색 성공의 대체 증거로 쓰지 않는다.

## 범위

사용자가 기존 단일 검색의 결과 문항을 DB 조회에서 열었다고 확인한 상태를 보존하고,
목록1–32개·문항마다 상위1–64개·최근 사용자별 검색·선택 기준 미리보기를 추가했다.
완료 결과 확인은 원 selector의 읽기이며 새 계산을 시작하는 버튼과 분리한다.
검색 기록은 활성화 이후 실제 접수부터 저장한다. 과거 검색을 신규 기록으로 위장하지 않는다.

[설계와 최종 설명 근거](../architecture/ITEM_DB_SIMILARITY_BATCH_HISTORY.md).

## 실제 설치 묶음

| 구성요소 | 고정 source |
| --- | --- |
| API / shared platform / API contracts | `217d28bf8c918f501fcf6396066a2abcf1579e15` |
| Catalog 별도 설치본 | `281692c8b2def44cfae0808d144d1f72fff641e7` |
| Web | `7bd2df330768f379a8c83e149b93b0d544196b6c` |
| QUERY 수치 owner | `7ba7524da3d7fd8dc86892b1654af89031380641`, 코드 변경 없음 |
| INDEX | `aac484339651b53f9bd5e2d29e1215a052754f08`, process `3284474` 유지 |
| DB head | `20261102_0069` |

Catalog는 이미 운영되던 `6589d16d`의 조회 개선을 보존한 successor다. API 소스 기준의 이전
Catalog reader로 되돌리지 않았다. 패키지 비교에서 삭제0, 새 V2 계약/스키마2개와 관련
validation/dispatch/selection만 변경됐다. Catalog의 기존 API 계약 bytes는 동일하다.

API provider code-member pin과 QUERY cohost/private 관계는 새 API 설치본의 정확한 bytes로
갱신했다. QUERY 모델·controller·환경·device routing, INDEX 설정·PID와 기존 실행은 보존했다.
API 서비스 정의와 인증 시간·비밀값도 변경하지 않았다. Web 재시작으로 브라우저 재로그인은 필요하다.

## 검증된 것

- schema-first V2 목록과 순서·중복·범위·실제 actor 검증, 원 V1 계약 보존.
- focused154개, 이후 OpenAPI/header/access-capture 연동45개 PASS. 범위가 겹치므로 합산하지 않는다.
- disposable PostgreSQL6개 PASS: 같은 key 동시4접수, 원 intent 불변, owner 분리, keyset,
  최초 pin 유지와 늦은 PENDING의 완료 역행 방지. 제한 runtime role의 원 input/owner/key UPDATE 거부.
- migration68↔69 임시 DB 왕복, 실제 운영은 독립 보호된 release-operator1.16으로69 적용·확인 PASS.
  공식 API runtime role bootstrap도 통과했다. 운영 DB에는 pytest를 실행하지 않았다.
- changed runtime14모듈 strict mypy, 후속 route/BFF3모듈 mypy·Ruff/format PASS.
- 실제 Chromium에 저장소 화면과 합성 API를 연결한 목록·preview 영역·기록·결과 이동·A/B 경합 PASS.
  이는 실제 로그인·실제 PDF 픽셀 검증이 아니다.
- API/Catalog/Web wheel/RECORD·독립 설치 검증 PASS. API 첫 빌드의 OpenAPI snapshot 미갱신은
  운영 변경 전에 발견·수정했으며 실패 이력을 보존했다. 새 호환 묶음은 다시 빌드해 PASS했다.

## 운영 보존과 현재 미완료

13:13 UTC GPU 공통 입력은356/1003 bindings, CPU는328/1003이다. 장치별 분모를 합산하지 않는다.
GPU가 배포 전348에서356으로 진행했고 INDEX PID·설정은 유지됐다. 구 벡터는 삭제하지 않았다.

창작 풀이보고서 서비스는 이 체크포인트 이전부터 PID0 상태이며, 이번 검색 기능 배포가 이를
재개했다거나 여러 슬롯이 실행 중이라고 보고하지 않는다. 별도 장애 복구를 본 기능 완료로 대체하지 않는다.

다음 실제 검증은 한 로그인 브라우저로 단일 검색, 이미 준비된 결과 문항을 포함한2문항 검색,
top_k3/5, 원문 미리보기, 결과→DB, 최근 기록 재열람과 새로고침 후 복원이다.
같은 완료 요청의 재조회 전후 native/Workflow 개수와 output hash도 대조한다.
GPU 공유 배치·모델 재사용 경로의 실제 장치·호출 수·소요시간을 따로 확인한 뒤 완료 판정한다.

## 증거 위치

- protected release/admission: `/var/lib/eom-db-search-history69-20261102/` 및
  `/var/lib/eom-release-operator-stage.db-search-history69-hi9cf6zk/`.
- build-only logs: `/tmp/eom-db-list-20261102.api-build-v2`, `.catalog-build`, `.web-build-v2`.
- source tests: `/tmp/eom-db-list-final-20261102.tests`,
  `/tmp/eom-db-list-20261102.check-key-tests`, `.mypy-followup`.
- disposable tests: `/tmp/eom-db-search-list-20261102.integration-tests-v4`.
- release metadata: `/tmp/eom-db-list-post-release.metadata` (읽기 전용·mutation0, 내용/인증 미수집).

임시 로그는 장기 보관본이 아니며 Git에 복사하지 않는다. 정본 문항·보고서·기존 실패와 모델
산출물은 원래 저장소/Artifact 경계를 그대로 유지한다. 최종 실제 검증 결과는 이 문서에 후속 기록한다.
