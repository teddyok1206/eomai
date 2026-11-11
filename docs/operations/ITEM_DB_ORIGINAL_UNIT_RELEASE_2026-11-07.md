# 문항 정보의 원본 소속 단원 표시

## 변경 범위

사용자의 요청에 따라 문항 정보에는 원본 소속 단원만 표시한다. 가져온 원본의
대단원·소단원을 `소속 단원`으로 묶고, Graph가 연결한 교육과정 단원은 이 패널에서
표시하지 않는다. Graph 분류, 검색 필터, 풀이보고서와 임베딩 자료는 변경하지 않는다.

등록 문항을 검색 결과에서 여는 경우에도 Item Revision과 manifest hash에 고정된
원본 등록 관계로 소속 단원을 읽는다. 원본의 current revision이나 Graph 추정값으로
대체하지 않는다. 없음·조회 권한 없음·조회 실패를 구분한다.

구현과 경계: [등록 원본 동등 조회](../architecture/ITEM_DB_REGISTERED_SOURCE_PARITY.md).

## 검증한 후보

- 코드 commit: `9810efd6a153683f143707c4c3cd818cc2de650d`.
- API/Web/Catalog 및 OpenAPI·정렬 검사: 집중 테스트 134개 PASS.
- 별도 disposable PostgreSQL: current source가 이동해도 등록 당시 원본 단원을
  읽는 실제 DB 검사 1개 PASS. 운영 DB에 pytest를 실행하지 않았다.
- 실제 Chromium synthetic fixture: 원본·등록·Graph 상세, A→B 응답 역전,
  권한 거부, 조회 실패, 기존 조립·유사도 흐름 PASS.
- Ruff·focused mypy·diff 검사 PASS.
- API wheel RECORD, Web 실제 runtime import·installed simulation(62 files) PASS.

## 운영 반영

호환 release set의 기존 준비·drain·설치·rollback 절차를 재사용한다.
API/Web/platform/Catalog와 API provider 참조를 함께 갱신하며 QUERY 실행 owner는
기존 `c915281ea3acda63ea066ba9de397f7bbc335295`를 유지한다.
DB migration은 없고 기존 head `20261105_0074`를 유지한다.

보호된 설치·복구 증거 위치: `/var/lib/eom-original-unit-release-20261107`.
기존 원본, 문항, Graph, 검색 이력, 임베딩 벡터를 변경하거나 삭제하지 않는다.
별도 INDEX·자료 학습의 설정/실행 identity는 보존한다.

배포 전 INDEX는 이미 `failed`였다. 이번 변경의 범위는 단원 조회와 화면 표시이며,
이를 GPU 복구 또는 임베딩 정상 실행으로 보고하지 않는다.

## 배포 후 검증 — 2026-11-07 16:33 UTC

- API/Web/platform/Catalog 설치 source: `9810efd6`. 설치 wheel member 검증 PASS.
- 기존 QUERY owner `c915281e` 유지, API provider hash/관련 wrapper를 호환 갱신.
- API·Web·Catalog·QUERY·workflow·HWPX·채팅 서비스 active, creative producer 재개.
- 실제 HTTPS API/Web ready PASS. 배포된 `item-db.js`·`styles.css`가 후보 파일과
  byte-for-byte 일치. 비인증 원본 조회는 HTTP 401로 거부.
- 실제 등록 문항 5개(12099, 10693, 11823, 12299, 11908)에서 설치된 Catalog
  조회 함수와 API DTO로 고정 원본 revision·소속 단원 연결 PASS.
  이 검사는 읽기 전용이며 사용자 인증 브라우저 확인을 대체하지 않는다.
- 배포 전후 INDEX/자료 학습 runtime identity 및 보호 대상 설정 hash 동일.
- DB write·migration·새 모델 요청·새 검색 요청은 0.

운영 증거는 위 보호 경로의 `activated.json`, `prepared.json`, `rollback.json`,
`source-unit-read-verification.json`에 보존한다. API/Web 사용자는 새로고침 후
`데이터 → DB → 조회 → 문항 정보`에서 소속 단원을 확인할 수 있다.

## 유사도 결과 목록 적용 — 2026-11-11 UTC

- 코드/운영 API·platform·Catalog: `680fff7296a8b1028692bcc8f7be620d93e29dcb`.
  Web `1a617d80`, QUERY owner/controller `377b196e`는 유지하고 API provider 및
  그에 종속된 설정 hash만 호환 갱신했다. migration `20261110_0077` 변경 없음.
- 결과 목록의 `unit_label`을 Graph 연결 단원 대신 등록 당시 원본 Q/R의
  `대단원 → 소단원`으로 표시한다. 원본 단원이 없는 경우 빈 값(`—`)이며
  원본 조회 오류는 추정값으로 숨기지 않는다. 단건 상세와 동일한 Catalog resolver다.
- 최대64개 결과를 두 번의 indexed batch SQL + O(k) map으로 결합한다.
  결과마다 별도 HTTP/SQL 조회를 추가하지 않았다. 순위·점수·벡터·완료 기록 불변.
- source 단위/검색 application/문맥 87개, API 권한·조회 24개,
  disposable PostgreSQL source/등록/출력 34개 PASS. Ruff·focused mypy·wheel RECORD PASS.
  단건 SQL 기대값을 batch 형태에 맞춘 과정의 실패는 개발 로그에 남겨 두었고 최종 재실행 통과.
- 운영의 실제 API DB 역할로 설치된 batch 조회와 상세 원본 조회를 3문항 대조:
  모두 동일, 원본 단원 있음, batch SQL 2회. 읽기 전용이며 사용자 세션을 만들지 않았다.
- API·Web·Catalog·QUERY·채팅·runner active, creative producer 재개.
  INDEX/자료 학습의 실행 identity와 고정 설정, GPU/CPU 수치 runtime 보존.
  새 검색·모델 실행·업무 DB write·벡터 재생성 없음.
- 보호된 준비/rollback/설치 증거:
  `/var/lib/eom-similarity-original-unit-20261111`.
  실제 GUI에서 변경된 단원 열은 사용자가 이후 “확인했어”로 확인했다.

사용자가 이번 수정 전에 실제 유사도 결과 목록 표시를 확인했다. 해당 검색의
첫 계산/조회 지연은 이번 단원 표시 변경으로 해결했다고 주장하지 않는다.
