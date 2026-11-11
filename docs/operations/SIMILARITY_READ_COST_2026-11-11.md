# 유사도 검색 조회 비용 개선 — 2026-11-11

설계: [조회 비용](../architecture/SIMILARITY_SEARCH_READ_COST.md).

## 최종 판정

2026-11-11 16:51 UTC, 구현·회귀 검증·호환 운영 배포 및 실제 사용자 경로 확인을 완료했다.
사용자가 새 검색의 **결과5개 표시 → 문항 열기 → 같은 최근 기록 다시 불러오기**를 모두
확인했다. 재조회는10.498초였고 원 ranking revision/hash·선택 목록·native launch1회가
그대로다. 아래 단계별 PENDING/실패 기록은 당시 상태이며, 최종 증거는 문서 끝에 덧붙인다.

같은 기존 기록의 재조회22.735→10.241초(약55% 단축)는 동등 요청 비교다. 새 검색은
READY까지4분10초, 첫 결과 HTTP까지6분2.5초였으므로 최초 검색이 수초로 단축됐다고
주장하지 않는다. 기존 데이터·실패 이력은 보존했으며 별도 신규 요청 사이 QUERY 벡터
재사용은 도입하지 않았다.

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

## 설치본 직접 확인과 완료 감사

같은 pinned manifest를 실제 QUERY owner interpreter
`/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12`와 설치 source11d826d2로
읽기 전용 확인했다. 파일 읽기0.08194초, cold decode3.57093초, 별도 복사한 동일 bytes의
warm decode0.00145/0.00131초였다. 모델 객체 크기 추정30,046,212bytes와 원 hash는
source 검사와 같다. 새 GPU/모델/검색 실행은 없으며, GUI 전체 지연으로 해석하지 않는다.
검증용 disposable DB는 공식 cleanup으로 제거했다. 운영 데이터에는 테스트하지 않았다.

| 목표 요구 | 확인된 근거 | 판정 |
|---|---|---|
| 기존 결과·순서·정본 보존 | 같은 search/selector/ranking revision·SHA 유지, 사용자 목록·열기 확인 | PASS |
| 현재 권한·provenance 보존 | before/after SQL closure, warm cache의 철회·변조 거부, disposable 동시성 회귀 | PASS |
| 완료 기록 재조회 개선·중복 계산 없음 | 실제 HTTP22.735→10.241초, native launch1회 그대로, 사용자 확인 | PASS |
| 최초 검색 반복 해석 개선 | strict decoder 재사용 소스·설치본 측정 및 QUERY/Catalog 배포; 새 검색 단계별 시간과 전체 보고서1회 해석 확인 | PASS; 최초 검색은 여전히 분 단위 |
| 동일 QUERY 재사용·GPU 연속 처리 검토 | 동일 요청 재사용 유지; 다른 요청 reuse는 새 증명 필요; finite batch 모델 load1회/encode N회 회귀 | 검토 완료; 별도 상주 서비스 추가 안 함 |
| 배포 후 새 GUI 검색→목록→문항 열기→동일 요청 재조회 | 새 검색384의 사용자 확인 및 재조회 동일 ranking/hash·native launch1회 유지 | PASS |

다음 행동은 이미 요청한 사용자 GUI 검색1건을 관측하는 것이다. 새 요청 없이 ready 상태나
내부 benchmark만으로 완료 선언하지 않는다. 사용자 세션을 만들어내거나 과거 operator
기록으로 새 실행 권한을 대신하지 않으며, 새 요청이 없다는 이유로 개선 범위를 확장하지 않는다.

## 재개 후 실제 새 검색 — 인증 만료로 미완료

16:33:32 UTC에 새 GUI 요청 `dbsearch_f160e9b17e0095914bc29f37000975f1`을 확인했다.
기준1개·top_k5이며 이전 기준선의 top_k3과 구분한다. CUDA allocation
`c06540d281c74cf29b6ad5d98200bd39`과 Workflow
`workflow_57166fdf65144a0f95b2b999375e4b16`에 연결되었고 native launch는1회다.
입력 준비는16:35:08에 끝났지만 완료 결과는 생성되지 않았다.

확인된 원인은 `fresh_auth_seconds=2700`이다. 사용자의 최초 인증
15:50:24.422160 +2700초 =16:35:24.422160이며, 첫 권한 오류는16:35:24.427163으로
만료5ms 뒤다. 액세스 토큰은16:33:27에 갱신돼17:03까지 유효했지만 이 갱신은
`authenticated_at`을 연장하지 않는다. 이후 driver의 `AUTHENTICATED_SESSION_FORBIDDEN`
→ controller EOF 순서도 일치했다. 검색 row는 FAILED이며 원 실패와 native 실행을 보존한다.
이 결과를 성공이나 새 검색 속도 검증 PASS로 해석하지 않는다.

실제 호출 경로도 확인했다. 원본/정책/index 검증과 native 입력 구성 및 실행 후 재검증은
QUERY11d826d2가 맡는다. 보존된 controller377b196e는 물리 프로세스·소켓·GRANT를 관리하며
원본 index를 구형 decoder로 직접 읽는 것이 아니다. numericalc915와 Catalog568ed 경계는
그대로다. 따라서 controller를 추가 교체하거나 권한 검사를 약화하지 않는다.

다음 정상 검증은 사용자가 다시 로그인한 직후의 새 검색1건이다. 기존 실패의 자동 재실행,
비밀번호 변경, session 가장, policy 완화, timeout 증가는 수행하지 않았다.

## 새 로그인 후 실제 검색 완료

16:40:33 UTC의 새 로그인에서 요청한
`dbsearch_38467229986385300e92e40fff5ff3ad`는 오류 없이 완료됐다. 기준1개·top_k5,
CUDA이며 원 QUERY native launch는1회다. 이전 기준선과 selection SHA가 다르므로
아래 최초 검색 시간은 동등 workload의 인과적 개선율이 아닌 운영 참고 비교다.
동일 기록 재조회22.735→10.241초의55% 단축은 별도의 같은 요청 비교로 유지한다.

| 실제 경계 | 시각 UTC / 소요 |
|---|---|
| 새 검색 생성 | 16:40:43.575227 |
| GPU READY 관측 | 16:41:29.525649 |
| 입력 구성·GRANT | 16:42:15.758669 |
| numerical result/vector 파일 완성 | 16:43:53.789743 |
| native 실행 검증 / publish / 완료 | 16:44:25.904659 / 16:44:29.043840 / 16:44:31.393819 |
| Workflow COMPLETED | 16:44:43.075211 |
| 검색 READY | 16:44:53.347477, 생성 후249.772초(4분10초) |
| 첫 결과 HTTP 완료 | 16:46:46.069791, 결과 조회112.702초 |
| 생성부터 첫 결과 HTTP까지 | 362.495초(6분2.5초) |

기존 참고 측정은 검색 READY까지8분14초·첫 결과 HTTP185.82초였다. 이번도 아직
처음부터 수초에 끝나는 검색은 아니며, GPU 순수 연산과 준비·현재 source/권한 검증·
모델 초기화·최초 ranking 생성을 같은 시간으로 설명하지 않는다.

- Workflow `workflow_190434a1944946ad9749479f9b5ae40a` COMPLETED,
  native Job `job_22b2fca74a4e45c68fbcfbd6d55baf22` SUCCEEDED.
- 저장 ranking `rev_9fdbbf81f56f41f3b34e9bb9c707fb40`, content SHA
  `sha256:fc09d332512005202b4a618561589e2571f8718f60e3acd8f059e3f1c3166a39`,
  56,825bytes. 첫 결과 요청 `req_c9a6c563dbb6c3b664371513eaee3c19`.
- 실제 첫 결과 로그에서 전체 보고서 읽기는7페이지 한 묶음만 있었다. 같은 root의
  마지막 재검증에서 전체 보고서를 다시 읽지 않았다. SQL 모집단/저장 의존성 전후 검사는
  유지하며 이것을 보고서 재해석과 혼동하지 않는다.
- 첫 조회 중 Catalog1GiB cgroup 한도에서 file cache 회수가 관측됐지만 OOM/kill/restart는0.
  권한·정본·벡터·점수·정렬 코드를 완화하지 않았다.

사용자에게 새 결과5개 표시·문항 열기·같은 최근 기록 다시 불러오기를 요청했다.
해당 수동 확인과 재조회 동일 hash/launch 검증 전까지 전체 목표 완료는 PENDING이다.

## 최종 사용자 확인과 동일 요청 재조회

사용자 확인: **“5개 보이고, 문항 열기·다시 불러오기 모두 돼”**.
실제 HTTPS GUI에서 요청한 새 검색의 결과 열람부터 DB 문항 조회와 최근 기록 재열람까지
확인한 것이며, health나 테스트 통과로 이를 대신하지 않았다.

- 재조회 HTTP `req_a0033a97b611eed5917c24c2f1fc211f`는16:49:40.389722 UTC에
  **10,497.721ms**로 완료됐다. Catalog 저장 결과 읽기는10,139ms이며 전후 SQL
  dependency 확인5,199/4,766ms를 포함한다. 결과를 새로 구성한112.702초와 구분한다.
- 16:51:16 UTC read-only 대조에서 같은 search384·selection SHA·Workflow COMPLETED와
  ranking revision `rev_9fdbbf81f56f41f3b34e9bb9c707fb40`가 유지됐다.
  content SHA `sha256:fc09d332512005202b4a618561589e2571f8718f60e3acd8f059e3f1c3166a39`,
  manifest SHA `sha256:c7a7b759b84b749a3ae28884aab9ee7119f6553b63eb282c0d8be10d7e2d4e25`,
  saved Job·Artifact 생성 시각·크기도 최초 결과와 동일하다.
- 원 native Job `job_22b2fca74a4e45c68fbcfbd6d55baf22`의 launch는1회다.
  재조회 때문에 GPU 재실행·새 ranking 저장·원 요청 변경이 발생하지 않았다.
- 완료 시점의 설치는 Catalog568ed897 / QUERY11d826d2다. API·Web·controller·수치
  runtime의 기존 pin을 보존했고, 마지막 증거 기록을 위해 runtime을 다시 배포하지 않았다.
- 이전 인증 만료 검색f160의 FAILED 기록은 그대로다. 별도 INDEX 서비스의 기존 failed
  상태를 이번 QUERY 성공으로 정상화됐다고 주장하지 않으며 재시작·수정하지 않았다.

현재 범위의 완료 판정은 **PASS**다. 남은 지연은 최초 source/권한 검증·모델 초기화·
최초 ranking 구성과 재조회 SQL 확인이다. 별도 신규 요청 사이 QUERY 벡터 재사용이나
상주 GPU 서비스는 이번 필수 범위가 아니며, 측정 없이 새 계층을 추가하지 않는다.

## 후속: 경과시간 표시 충돌

위 검색 완료 확인 이후 사용자가 `요청 후5분25초` 등의 시간이 오가는 현상을 보고했다.
운영 HTTPS가 제공하는 두 JS의 SHA가 source와 같음을 확인하고, 실제 presentation module에
합성 시계·지연 결과 응답을 연결해 재현했다. 목록 controller는 서버 `created_at`부터,
내부 결과 view는 결과 읽기를 시작한 `startedAt`부터 같은 DOM을 갱신했다. 두1초 timer를
실행하면 같은 시각에 `요청 후5분26초`와 `요청 후1초`가 차례로 표시됐다. 실제 검색이나
GPU를 추가 실행하지 않고 재현한 프론트엔드 소유권 충돌이다.

수정은 기존 두 presentation module에 한정한다. 목록 controller가 진행 표시·timer를
단독 소유하고, 하위 view는 `onProgress`로 조회 중 상태만 알린다. 단독 view의 기존 진행
표시는 유지한다. 결과 조회 중에도 원 검색 시각을 쓰며 종료·초기화 때 timer를 제거한다.
API·검색 identity·벡터·권한·DB schema·결과 순서는 바꾸지 않는다. 운영 반영은 Web만
대상이며 GPU/QUERY/INDEX와 API·Catalog의 설치 pin을 보존한다.

검증·운영 반영 결과는 아래에 기록한다. 이 후속은 앞선 속도 개선 목표를 다시 여는 것이
아니라 사용자에게 확인된 별도 표시 오류 수정이다.

- 기존 Web suite483 PASS / 기존 opt-in browser13 SKIP. 추가한 타이머 회귀와 인접
  binding/context 검사는18 PASS. 같은 회귀를 이전 source63895a9b에 메모리로 연결하면
  READY→지연 결과 단계에서 timer2개로 실패하고, 수정본은1개로 통과한다.
- 새 회귀는 PENDING→READY/지연 결과·최근 기록 열기·기준 변경·완료 후 중복 요청 없음·
  계정 초기화·이전 계정의 늦은 응답에서 단일 시계와 timer 정리를 확인한다.
  기존 단독 view 검사는 보존했다. 운영 검색·GPU 실행은0회다.
- 변경 테스트의 Ruff/format/mypy, JS syntax, diff 검사와 독립 코드 리뷰를 완료했다.
- 16:58:10 UTC Web source `4fc1c11a1712d0d2f8ddc6b59bb1e0234ab4d15a`를 운영 반영했다.
  wheel/RECORD·격리 설치본·실제 service identity 검증73파일 PASS. 이전 wheel 대비
  변경은 위 두JS와 build-info/RECORD뿐이다. rollback·배포 기록은
  `/var/lib/eom-web-similarity-elapsed-20261111`에 보존한다.
- Web 재시작 직후 HTTPS 확인 첫 시도는502였고 기존 bounded 확인의 다음 시도에서
  정상화됐다. 후속 HTTPS login200·Web smoke PASS. API/Catalog/QUERY/INDEX/creative의
  PID는 모두 배포 전후 같으며 인증·DB·GPU 실행을 변경하지 않았다.
- 운영 HTTPS가 제공한 두JS bytes가 수정 source와 일치하며, 그 실제 응답 bytes를
  메모리에서 로드한 동일 timer 회귀도 PASS다. 이는 fake-clock/DOM의 결정적 검증이며
  실제 사용자 브라우저 수동 확인으로 과장하지 않는다. 이미 열려 있는 화면에는 새로고침이
  필요하고, 기존 최근 기록을 열면 되므로 검증을 위해 새 GPU 검색을 만들 필요는 없다.
