# Excel 콘텐츠 편성 구현 체크포인트

승인된 목표는 `docs/architecture/EXCEL_CONTENT_PLACEMENT_DESIGN.md`의 **구현·반복 검증·운영 배포**다.
이 문서는 소스 검증·운영 설치·사용자 경로 증거를 구분한다. 2026-11-09 호환 운영 설치를
완료했으며, 실제 로그인 사용자 경로는 최종 검증 중이다. 마지막 설계 대조에서 발견한
복구·부분 복사·선택 출력 연결·보관 경로 보완은 **아직 별도 운영 반영 전**이다.
기존 문항/벡터/실패 이력은 보존했다.

## 현재 단계

| 단계 | 상태 | 실제 범위 |
| --- | --- | --- |
| I01 계약·순수 규칙 | source PASS | JSON Schema 우선, occurrence/판/인쇄·사용 이력·transport frozen model 구현 |
| I02 저장 구조 | source + disposable PASS | 기존 Product/Form/curated 확장, 새 소속/index/이력, migration 왕복과 저장 primitive 검증 |
| I03 application 저장·복사 | source + disposable PASS | 실제 권한·포인터 재인가, 같은 transaction의 저장/복사/이력/멱등, bounded 읽기 |
| I04 사용 이력·중복 | source + disposable PASS | 같은 current/print projection으로 사용처·교차 중복·연도 USED/UNUSED를 조회. 이전 ledger는 연도를 추정하지 않는 별도 읽기 |
| I05 인쇄 use case | source + disposable PASS | 사용자 기록·동시 최초 기록·재인쇄·정정·취소 및 해당 구간 변경 판정. 출력 이력은 정확한 scope로 별도 보존하며 인쇄 사실을 자동 생성하지 않음 |
| I06 API/BFF/GUI | source/fixture PASS / 운영 설치 PASS | 콘텐츠·판·회차·DB 선택·편성·사용 이력·인쇄·출력 UI. HTTPS 사용자 검증 진행 |
| I07 HWPX 전 경계 확장 | source·설치본 통합 PASS | 새 1,200자리 입력·반복 occurrence·범위 준비/출력 이력/API·기존 제작 UI 연결. 실제 303문항 합본과 독립 검증 PASS. 운영 사용자 출력 별도 확인 |
| I08 운영 배포·실사용 | 호환 배포 PASS / 사용자 경로 PENDING | source 테스트나 READY를 실제 배치·출력 성공으로 확대하지 않음 |

Source baseline: `844a8eec40be1eda9771fb8fe00854007ea660e1`.
별도 세션의 INDEX publication recovery 변경은 이 작업과 구분하고 수정하지 않았다.
`20261109_0076`까지 호환 릴리스로 운영 적용했다. 후속 보완은 현재 DB schema를 재사용하며
임의로 별도 기능의 운영 릴리스에 섞지 않는다.

## 구현한 주요 경계

- V3 curated draft / V2 manifest: 자리 identity와 대상 identity 분리, 빈칸과 반복 Item 허용,
  100,000자리의 방어적 요청 상한. 기존 200개 계약 bytes/의미는 변경하지 않음.
- 판별 head/불변 Product revision/Form 소속. section tree는 adjacency 기반 선형 검증,
  copy는 작은 포인터만 복사하고 새 placement ID·원본 위치를 남김.
- SaveSectionSet은 변경 구간의 최종 배열을 한꺼번에 비교한다. 출발 구간 없는 이동은 거부,
  순서·대상 변경·제거를 구별하고 동일 내용은 NO_CHANGE.
- 인쇄 scope는 선택 leaf의 exact Form/Assembly와 경로/번호 문맥을 pin한다. 2회차 편집은
  이미 인쇄한 1회차 scope를 바꾸지 않으며, 연속 번호의 앞 구간 변경은 반영한다.
- INITIAL print partial unique, command receipt unique, head ownership FK, immutable trigger,
  V1/V2 slot row family 분리. 기존 private 조립의 권한은 아직 변경하지 않음.
- DB에는 metadata/포인터/index만 추가. HWPX/PNG/문항 내용/보고서 bytes 복사 없음.

## 실제 Excel 재확인

입력: staging의 `2026년_문항관리_공유_OneDrive.xlsx` (실제 파일명은 NFD).
SHA-256: `88ae6c7564294ca518c59c3c6d0f9bbd73703b122d54f169adc46c1d6d7d2e50`.

읽기 전용 opt-in suite `test_content_planning_workbook_reference.py`로 반복 확인한다.
원본 Excel은 Git에 포함하지 않는다. ZIP 크기/경로·XML entity 경계를 검사하며 수식·링크·매크로를
실행하지 않는다. 업무 내용을 자동 import하거나 통합과학 문항에 숫자만으로 연결하지 않는다.

- 실제 `27_모의 배치`: 1,120자리 / 1,112개 index. 같은 index의 두 사용 위치가 보존됨.
- `27_엄메` 본문 300자리, `27_E기적` 1,200자리 / 1,195개 index.
- `27_단원별`의 page 기반 미연결 5자리는 가짜 Item으로 만들지 않고 빈 자리로 표현.
- 주간 부속 시험 80개, 테스트 기록 100개: 비어 있는 회차를 완료로 만들지 않음.
- 전년도 미사용에 속한 문항의 차년도 사용을 대조: 미사용을 영구 분류로 저장하지 않음.
- 리뷰 완료 색/문구는 인쇄 증거가 아님을 확인.

## 실행 증거 (소스·임시 DB)

2026-11-09 UTC:

- 계약/순수 배치 + 기존 V1 조립 회귀: 62 PASS.
- 실제 Excel opt-in: 9 PASS.
- 저장 모델/FK/index/frozen DDL: 16 PASS.
- Catalog schema source/package resource equality: PASS.
- 임시 DB migration `0074 → 0075 → 0074 → 0075`: PASS.
- 임시 DB 저장 primitive 8 PASS: 동시 저장의 한 head만 전진, 서로 다른 판의 독립 저장,
  rollback 후 동일 key replay, metadata mismatch 거부, 1,200자리, profile 혼용 거부,
  INITIAL print 중복 방지, history 있는 downgrade 거부.
- 초기 시험에서 test-only FK model import 누락과 새 head 상수 누락을 확인·수정하여 재실행함.
  실패 이력을 숨기지 않으며 source/test 환경 수정이지 운영 장애나 사용자 데이터 수정이 아님.

현재 disposable DB state: `/tmp/eom-api-testdb-20261109100556_4b9a96dc`.
운영 DB가 아니다. 준비·검사에 기존 `testdb_prepare.sh` / `testdb_run.sh` guard를 사용했다.
credential 파일은 이 기록/로그에 복사하지 않는다. 후속 application 검증에 재사용 후 공식 cleanup한다.
이미 합성 이력이 있으므로 다시 migration 왕복하려면 새 disposable DB를 준비해야 한다.

재현 명령:

```bash
scripts/api/testdb_run.sh content-planning-tests /tmp/eom-api-testdb-20261109100556_4b9a96dc
```

단위 검증은 explicit `/srv/eom/conda/envs/eom-api/bin/python -B`와 source PYTHONPATH를 사용한다.
출판/교육적 품질/실제 GUI·HWPX 성공 증거는 아직 없다.

## 바로 다음 구현

1. HWPX successor와 API/Web/Catalog의 installed wheel·RECORD 검사를 닫는다.
2. 검증된 migration 0075/0076 및 runtime 역할·protected release operator를 호환 묶음에 반영한다.
3. 실제 HTTPS 선택·저장·복사·이력·인쇄·HWPX 다운로드를 확인한다. 운영 활성화 전 완료 금지.

## Application 검증 추가 (2026-11-09 UTC)

배포 직전 추가 검증: 제한된 runtime role의 실제 생성·저장·인쇄·이력·출력 준비까지
포함한 disposable PostgreSQL suite **39 PASS**. snapshot DELETE 거부와 검사 후 권한 복원도
확인했다. 임시 역할 준비 누락, fixture가 빈 회차를 출력으로 선택했던 초기 실패는
공식 testdb reconcile과 정확한 범위 선택으로 수정·재검증했다. 운영 DB 테스트는 없다.

변경된 계약/API/Web/HWPX/운영 도구 집중 회귀 **276 PASS**(실제 workbook opt-in 및 Chromium 포함),
core Python83개 type check PASS, wire audit schema1,344/mirror1,002 PASS다. 이는 설치본·운영 PASS가 아니다.

`content_usage_projection.py` 하나를 페이지·집계·반복 표시·연도 USED/UNUSED 검색이 공유한다.
필터는 pagination 이전에 적용하고 원본과 등록 Item의 관계는 실제 등록 lineage로만 확장한다.
이전 ledger는 학년도/Graph 버전을 추정하지 않는 별도 read adapter로 읽으며 새 print log로 복제하지 않는다.

303문항 합본 acceptance에서 큰 header를 문항마다 복사하던 비용을 제거했다.
동일 fixture renderer27.11초 + Manager acceptance8.06초, 총38.63초이며 기존 약267초/3.7GiB와
같은 native 표·수식·그림·출제의도 검증을 유지한다. 허용 최대100,000자리는 방어적 상한일 뿐
무제한 파일 보장이 아니다. 새 metadata16MiB, private transport4MiB 등 독립 예산 초과 시
회차를 나누어 출력한다. 정상 원본 XML 한도는 유지하고 생성 합본만 기존 총256MiB 예산 내에서 허용한다.

protected operator1.22/정확한0076 callback·API read권한·Catalog write권한·독립 sequence USAGE는
소스/임시 환경에서 확인했다. **운영 적용은 아직 미실행**이다.

- API/transport/계약 집중 검사: **63 PASS**. 실제 HTTP의 1,200자리 전달, 실제 operator 전달,
  authority 필드 주입 거부, 다른 요청 응답 거부, print endpoint 포함.
- disposable application/storage/print/usage: **29 PASS**. 실제 workbook 구조의 1,120/1,200자리,
  동시 편집, 정확한 replay, rollback 재시도, partial print, 동시 최초 인쇄 기록 하나,
  취소/정정 append-only, current+print 중복 집계 방지, 삭제한 인쇄 위치 보존,
  연도별 사용·보관 콘텐츠 이력, 1,200자리의 bounded query 수를 확인했다.
- 사용 조회는 repeatable-read snapshot 내 고정 개수 SQL로 page/count/대표 위치를 계산한다.
  원본과 등록 Item의 동등성은 기존 creative registration lineage만 사용하며 번호/이름으로 추정하지 않는다.
- Catalog application RPC와 API의 `commands`, `query`, `prints` 세 transport를 사용한다.
  DB/권한/해시/정합성 규칙은 Catalog가 소유하고 BFF에는 복제하지 않는다.
- print 결과와 목록에 4 MiB transport 예산을 적용하며 목록은 DB에서 크기를 먼저 확인해
  bounded page만 materialize한다. 목록의 실제 대형 record 경계 fixture는 후속 검증 대상이다.
- focused type check PASS. 전체 타입 검사의 기존 Workflow request union 오류는 별도 세션 변경과
  구분하며 이 변경을 이유로 임의 수정하지 않았다.
- 이번 단계에서 운영 DB/서비스/worker/GPU 재시작은 없었다. 실제 UI·HWPX·운영 검증은 PENDING.

목표는 계속 ACTIVE다. 현재 checkpoint를 전체 기능 완료로 표시하지 않는다.

## 범위 출력 및 화면 검증 추가 (2026-11-09 UTC)

- 실제 workbook을 읽는 두 application 사례를 포함한 disposable suite **35 PASS**.
  1,200자리의 준비·HWPX queue admission·같은 요청 replay, 두 편집자의 동일 범위 준비,
  중간 예외 전체 rollback, 새 편집 후 옛 출력 유지, 출력 history pagination·권한을 검사했다.
- migration `0075 → 0076 → 0075 → 0076`은 신규 scope history 입력 전에 PASS.
  history가 있는 현재 DB에서는 downgrade를 반복하지 않는다.
- 실제 Chromium fixture의 20회차/1,200자리/반복 사용/응답 지연/사용자 전환 및 출력 history
  재조회에서 제작 요청 추가 0을 확인했다. 외부 입력 내용은 textContent로 렌더한다.
- 실제 **303문항 로컬 HWPX 합본**: 300 native 반복 원본 + canonical Item 2 + editorial 1.
  그림·수식·표·순서 및 Manager 독립 보존검사 PASS. 이 검사는 운영 출력/한컴 육안 PASS가 아니다.
- 합본 검증 중 최종 header를 occurrence마다 deep-copy하는 O(n²) 경로를 확인했다.
  non-resource options를 bytes 복제 없이 한 번만 계산하도록 수정; 후속 성능/보존 회귀 진행 중.
- 신규 occurrence build-input V2 / render V4 / native-item V2 / public build-view V2 사용.
  기존 V1/V3 bytes 및 개인 조립 creator 정책 유지. 공유 범위는 실제 콘텐츠/문항 권한 재검사.
- Catalog delivery V2 transport는 exact profile family·revision/hash·실제 actor를 검증한다.
  출력 prepared scope는 별도 queue가 아니라 기존 curated Assembly/빌드 queue의 typed 입력이다.
- 추가 API `POST /content-planning/deliveries` 및 query `DELIVERIES`; 준비·상태·다운로드는
  인쇄 기록을 자동 생성하지 않는다. 현재 print record의 optional output field는 비워 두며,
  별도 출력 history에서 exact edition/scope를 조회한다.
- 소스 기반 cross-boundary HWPX tests는 API interpreter에 필요한 Builder source와 설치된
  HWPX dependency 경로를 명시했다. 순수 Builder의 non-editable 설치 검증과 혼동하지 않는다.
- 실패한 초회 검사는 test fixture constructor/empty-section 기대값/필수 revision 누락 등과
  생성 합본 header byte budget을 분리해 수정했다. 운영 데이터/실패 기록 변경 없음.

## 운영 설치 체크포인트 — 2026-11-09 13:14 UTC

- 구현 commit `91a14bb695d1aad8a102306b74329cda135cd83d`와 Web 패키지 목록 보완
  `8677b4ef346bff936b90f767ff045c04fb3c0225`를 main에 push했다.
- API/platform/Catalog/Manager source `91a14bb6`, Web `8677b4ef`, Builder `91a14bb6`.
  수치 INDEX/QUERY의 독립 설치본은 교체하지 않았다. QUERY의 API provider hash만
  해당 API 설치본과 맞춘 기존 호환 설정으로 갱신했다.
- protected operator1.22: ADMIT, 정확한 `0074 → 0076`, VERIFY, API/Catalog/HWPX 역할
  reconcile PASS. 운영 DB에서 pytest를 실행하거나 application row를 직접 고치지 않았다.
- 설치 wheel/RECORD 및 서비스 identity PASS. HTTPS `/studio/api/v1/health/ready` READY.
  완료 작업/유효 lease/비동기 출력이 비어 있음을 확인한 뒤 원래 creative producer를
  지원된 SIGINT로 drain하고, 호환 설치 뒤 원래 서비스로 재개했다.
- 설치된 Builder/contract와 API/Manager를 사용하는 합본·native 회귀 **31 PASS**
  (46.51초, 303 occurrence 합본 포함). source package 경로를 주입하지 않고 설치된
  non-editable packages를 사용했다. Pydantic2.11의 기존 `exclude_if` 경고 6개와
  pytest JUnit property 경고 1개는 오류 없이 기록됐으며 dependency 변경은 하지 않았다.
  공개 HTTPS의 새 Web asset 5개 SHA도 wheel bytes와 일치했다.
- INDEX PID와 InvocationID가 배포 전후 동일하며 material coordinator/config,
  native-intent-cell 코드, 원본 converter, Codex 인증 및 GPU configuration hash를 보존했다.
- root-owned 복구/설치 기록:
  `/var/lib/eom-excel-compatible-release-20261109`,
  `/var/lib/eom-excel-compatible-rollback-20261109`,
  `/var/lib/eom-excel-builder-release-20261109`,
  `/var/lib/eom-release-operator-stage.excel76-p2rbra27`.
- 롤백 후보 `6b3c77d75f7ee7e9f4eb342b0e1f6686d1bdb8e9`는 b900의 기존 기능과
  새 schema76 head를 호환시키는 **노출 전 전용** 별도 branch다. 실제 rollback은 없었다.
  새 편성 이력이 생성된 뒤 이 후보로 기능을 숨기거나 DB를 downgrade하지 않는다.
- 최종 임시 DB 대조에서 독립 model import가 누락된 global metadata fixture를 보강했다.
  실제 migration와 전체 composed metadata 일치 및 기존 저장 primitive **6 PASS**,
  복구 후보의 기존 저장 primitive **5 PASS**. DB DDL 차이가 아니라 fixture 등록 누락이었다.
- 빌드 준비 중 Web의 신규 4개 asset/module이 inventory에 없어 거부된 것을 명시적 목록에
  추가·재검증했다. Builder 복구용 contract는 초기836이 아닌 실제 설치 bytes와 일치하는
  ad761dc5 wheel로 고정했다. 이 사전 실패는 운영 설치 전에 발생했다.

남은 gate는 실제 HTTPS 브라우저의 콘텐츠 생성→DB 문항 선택→반복 배치 저장→복사→
이력 조회→선택 회차 HWPX 제작→다운로드 및 동일 요청 재조회다. READY/소스 PASS만으로
이 gate를 닫지 않으며, 원본 지구과학 Excel 자체를 운영 통합과학 DB로 import하지 않는다.

## 최종 설계 대조 보완 — 2026-11-09 13:38 UTC

운영 설치 후 원설계를 다시 항목별로 대조했다. 위 설치본을 전체 목표 완료로 처리하지 않는다.

- DB 임시 배치의 여러 pinned 문항을 한 번에 Excel에 가져오기, exact URL 위치 복원,
  제출 후 세션 만료 시 같은 요청 key/body 복구를 추가했다. 다른 owner의 요청은 표시·
  실행하지 않는다. timeout과 확정된 편집 충돌을 구별하고 편집은 사용자가 버리기 전 보존한다.
- 전체 판 복사 외에 저장 구간/선택 자리의 삽입·교체 복사를 기존 SAVE_SECTIONS에 연결했다.
  새 endpoint/DB 없이 provenance와 새 placement ID를 보존한다.
- 완료 HWPX를 인쇄 기록에 선택적으로 연결하는 successor와 공식 보관/복원 경로는
  별도 보완 중이다. 기존 인쇄·사용 기록이 있다는 사실로 이 선택 기능까지 완료라 하지 않는다.
- 실제 workbook을 다시 읽은 순수 구조 검증 **9 PASS**. 동일 workbook opt-in을 켠
  guarded disposable DB 저장·동시성·선택 복사·인쇄·이력 **47 PASS**, 운영 DB 사용 없음.
- Web/API focused **32 PASS**, 실제 Chromium DB 목록 handoff와 Excel
  1,200자리/재인증 replay/선택 복사·삽입·교체/충돌 편집 보존/owner race/mobile PASS.
- INDEX는 기존 PID·InvocationID 그대로 active, creative coordinator도 active다.
  실제 HTTPS 사용자 canary는 준비된 로그인 입력을 기다리고 있다. 새 입력창을 만들거나
  기존 계정·비밀번호를 변경하지 않았다.

이 후속 소스는 아직 미커밋·미배포이며, 모듈별 증거를 합친 뒤 같은 호환 릴리스로 반영한다.

## 후속 통합 검증 — 2026-11-09 13:56 UTC

- 위 보완의 구현을 마쳤다. 새 lifecycle/인쇄 출력 연결은 명시적 successor 계약이며
  기존 V1 schema bytes와 schema76은 변경하지 않았다. Catalog 역할에는 기존
  `deliverable_events`의 SELECT/INSERT만 추가한다. sequence 권한은 기존 reconciler가 관리한다.
- 실제 Excel을 다시 참조한 guarded PostgreSQL 검사 **62 PASS**: 편집과 보관의 잠금 순서,
  같은 요청의 동시 재전송, 별도 판의 병렬 편집, 선택 복사와 출력 연결을 포함한다.
  이어서 같은 임시 DB에서 HWPX persistence/복구 검사 **31 PASS, 1 SKIP**.
  SKIP은 opt-in 설치 Builder 실제 렌더이며 위 13:14의 설치본 렌더 증거와 구분한다.
- Web/API/계약/원본 Excel/OpenAPI 및 실제 Chromium 통합 **201 PASS, 0 SKIP**.
  DB에서 반복 문항 301개 선택, 100행 표시, 한 번에 전달, 기존 개인 초안 보존을 확인했다.
  요청 복구는 계정 A의 충돌 판정이 계정 B의 요청에 남지 않으며, 보관 충돌은 실제 거부된
  대상의 상태를 다시 읽는다. 현재 선택한 다른 판을 대신 읽지 않는다.
- 한글을 문자 수로 세어 4MiB 전송 한도를 넘던 요청은 UTF-8 바이트 기준으로 제출 전에
  거부한다. 미확인 요청이 아닌 로컬 입력 오류이므로 초안을 유지하고 수정 후 저장할 수 있다.
- 기존 OpenAPI 읽기 전용 POST 테스트 목록의 새 query 두 항목 누락은 fixture에 추가했다.
  초회 실패 로그를 보존했고 런타임 장애로 분류하지 않았다.
- wire audit: canonical schemas 1,350 / mirrors 1,008 / references 11,573 PASS.
  변경 core Python 24개 type check와 개발 문맥 13건 PASS.
- 다음 배포는 현재 91a API/platform + 8677 Web에서 후속 호환 묶음으로 갱신한다.
  DB migration·Builder 설치·INDEX 재시작·인증 변경은 하지 않는다. 현재 설치본을 복구
  기준으로 사용하며 노출 전용 구 6b3c77d7 fallback은 사용하지 않는다.

실제 HTTPS 검증은 기존 `EOM → 4번 excel-check`의 Studio 로그인 입력을 기다린다.
Linux sudo 입력 성공과 Studio 로그인 성공을 혼동하지 않는다. 테스트 PASS만으로
실제 사용자 경로 또는 전체 goal을 완료 처리하지 않는다.
