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

## 후속: 새 검색의 반복 manifest 해석

같은 운영 index manifest(5.0, 7,859,685bytes)를 공식 pinned reader로 읽은 후 순수
해석을 비교했다. 실제 파일 읽기는0.081초, 기존 strict decode3회는2.966/2.955/2.937초였다.
exact schema+bytes의 bounded process-local LRU2 후보는 첫 해석2.896초,
별도 복사한 같은 bytes의 다음 두 해석0.00148/0.00135초였다. 계산된 모델의 Python
객체 크기 추정치는30,046,212bytes이며 원본 bytes와 별개다. 최대16MiB 입력2개만
보관하고 초과 입력은 기존 strict 경로를 사용한다. 권한·파일·현재 provenance 검사는
여전히 수행한다. 이는 read-only decoder 측정이지 새 GUI 요청 전체의 개선 증거가 아니다.

- 집중 회귀173 PASS: 새 root의 물리 읽기/provenance 유지, 승인 취소·producer 변경·
  삭제·변조·hash mismatch 거부, schema/bytes 변경, 실패 미보관, size/LRU 경계,
  전체 지원 index의 깊은 불변성 검증.
- Ruff PASS. 기본 mypy가 따라간 기존 다른 두 모듈의 union-type 오류5개는 이번 변경
  파일의 오류가 아니며 범위 밖으로 기록한다. 변경 모듈의 focused type check를 별도 수행한다.
- 변경 모듈 `mypy --follow-imports=silent` PASS. 같은 disposable PostgreSQL에서
  completed ranking·read-set·candidate admission88 PASS(74.36초). 운영 DB에는 테스트하지 않았다.
- 기존 여러 문항 QUERY는 한 finite batch 안에서 모델을 한 번 열고 각 child를 처리한다.
  해당 batch/selection/encoding 회귀46 PASS. 별도 상주 GPU daemon은 추가하지 않는다.
- 동일 요청 재조회는 기존 vector/ranking을 재사용한다. 다른 새 요청까지 QUERY vector를
  재사용하는 ledger는 현재 없다. 그 기능은 새 요청과 원 producer의 증명 계약이 필요하며,
  최초 cold 검색의 병목 해결에 필요하지 않아 이번 최적화에 억지로 추가하지 않는다.

## 후속 운영 적용

2026-11-11 16:12 UTC, 위 순수 decoder 최적화를 다음 호환 릴리스로 반영했다.

| 구성요소 | 설치 source / 변경 |
|---|---|
| Catalog | `568ed89760fc30a1f96d32c6592b5a5233a00ed9`, 기존8be39 대비 decoder 한 모듈만 변경 |
| QUERY owner | `11d826d29587c48a2416fb26825c5748cb737d22`, 기존377b196e에서 decoder만 최소 백포트 |
| API / Web | 기존680fff7296 / 1a617d80 유지, 재시작 없음 |
| GPU controller / numerical | 기존377b196e / c915281e 유지 |
| INDEX / creative / workers | 기존 설치·설정·PID 보존, 이번 배포의 재시작 대상 아님 |

QUERY에 최신 main 전체를 설치하지 않았다. QUERY 백포트의 wheel은 adapter와 RECORD만
변경되고 API contracts 내용은 동일하다. 별도 검증156 PASS, Ruff·mypy·RECORD PASS다.
QUERY owner pin·세 설정 및 private primary hash·두 서비스의 설정 pin만 맞췄으며
controller/source 정책·API provider·수치 runtime·GPU 환경 파일은 보존했다.
Catalog의 같은-root QUERY capture 개선은 Catalog에 적용되어 있으나, 최소 백포트 QUERY
owner에 그 이전 단계의 다른 최적화까지 들어갔다고 주장하지 않는다.

설치 증거는 `/var/lib/eom-similarity-decode-catalog-stage-20261111`, paired activation과
rollback 원본은 `/var/lib/eom-similarity-decode-pair-release-20261111`에 보관한다.
배포 전 유효 QUERY claim·GPU 실행·Catalog 연결이 없음을 확인했다. API ready와 HTTPS
Studio login200은 확인했지만 이것을 새 검색 성공으로 대신하지 않는다.

**아직 남은 것:** 새 GUI 검색의 준비→GPU→첫 결과 목록→문항 열기→같은 요청 재조회
측정. 새 검색은 아직 관측되지 않았다. 이미 확인한 저장 결과 재조회55% 단축과 구분하며
전체 목표는 계속 ACTIVE다. 기존 임베딩·원 결과·실패 이력은 모두 보존했다.
