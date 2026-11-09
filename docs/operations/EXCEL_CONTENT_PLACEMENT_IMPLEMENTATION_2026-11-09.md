# Excel 콘텐츠 편성 구현 체크포인트

승인된 목표는 `docs/architecture/EXCEL_CONTENT_PLACEMENT_DESIGN.md`의 **구현·반복 검증·운영 배포**다.
이 문서는 개발 기록이며 운영 활성화 증거가 아니다. 기존 슬롯/GPU/문항/벡터/실패 이력은 변경하지 않았다.

## 현재 단계

| 단계 | 상태 | 실제 범위 |
| --- | --- | --- |
| I01 계약·순수 규칙 | source PASS | JSON Schema 우선, occurrence/판/인쇄·사용 이력·transport frozen model 구현 |
| I02 저장 구조 | source + disposable PASS | 기존 Product/Form/curated 확장, 새 소속/index/이력, migration 왕복과 저장 primitive 검증 |
| I03 application 저장·복사 | source + disposable PASS | 실제 권한·포인터 재인가, 같은 transaction의 저장/복사/이력/멱등, bounded 읽기 |
| I04 사용 이력·중복 | source + disposable PASS | 같은 current/print projection으로 사용처·교차 중복·연도 USED/UNUSED를 조회. 이전 ledger는 연도를 추정하지 않는 별도 읽기 |
| I05 인쇄 use case | source + disposable PASS | 사용자 기록·동시 최초 기록·재인쇄·정정·취소 및 해당 구간 변경 판정. 출력 이력은 정확한 scope로 별도 보존하며 인쇄 사실을 자동 생성하지 않음 |
| I06 API/BFF/GUI | source/fixture PASS | 콘텐츠·판·회차·DB 선택·편성·사용 이력·인쇄·출력 UI. 운영 미노출 |
| I07 HWPX 전 경계 확장 | source 통합 PASS / 설치본 대기 | 새 1,200자리 입력·반복 occurrence·범위 준비/출력 이력/API·기존 제작 UI 연결. 실제 303문항 합본과 독립 검증 PASS |
| I08 운영 배포·실사용 | 미실행 | source 테스트나 임시 DB를 운영 PASS로 확대하지 않음 |

Source baseline: `844a8eec40be1eda9771fb8fe00854007ea660e1`.
별도 세션의 INDEX publication recovery 변경은 이 작업과 구분하고 수정하지 않았다.
새 migration 및 runtime migration-head 변경은 **개발 후보**이므로 호환 릴리스 전체 검증 전
다른 기능의 운영 릴리스에 섞지 않는다.

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
