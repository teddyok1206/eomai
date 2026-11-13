# Excel 표준 양식 가져오기

2026-11-12 설계·구현 작업 문서. 운영 활성화나 실제 사용자 자료 등록을 뜻하지 않는다.
사용자가 확인한 빈 양식 1.0을 입력으로 사용한다. 임의 과거 Excel 레이아웃을 추측하는
변환기나 새 문항 등록 파이프라인을 만들지 않는다.

## 책임과 사용자 흐름

`데이터 → Excel → 양식 받기 → 작성한 파일 업로드 → 연결 결과 확인 → 새 교재로 저장`.
한 파일은 콘텐츠 한 개의 한 판이다. 기존 콘텐츠를 덮어쓰지 않는다. 번호가 연결되지 않으면
원래 행과 오류를 미리보기에 보존하고 저장을 막는다. 사용자가 파일을 고쳐 다시 올릴 수 있다.
같은 문항의 반복 배치는 정상이며 중복 사용 안내만 한다.

Web은 파일 선택·결과 표·명시적 저장만 담당한다. API는 실제 로그인 권한과 크기를 검증하고
기존 private Catalog socket으로 전송한다. Catalog가 양식 읽기, 고유번호 해석, 계획 확정과
편성 저장을 소유한다. 공개된 기존 콘텐츠/원본 해석 경계를 유지한다.

## 정본과 포인터

- 원본 XLSX와 검수용 proposal JSON은 기존 `CatalogArtifactService` → Orchestrator
  file-set commit에 보관한다. 원본 바이트·전체 행은 DB에 넣지 않는다.
- proposal은 업로더, 원본 hash/크기, 양식 버전, 해석한 행, 연결한 exact source revision과
  observation hash를 갖는다. 5자리 고유번호는 사용자 입력 키이며 내부 ID나 revision이 아니다.
- 번호는 현재 등록된 source namespace별 고유키로 일괄 대조한다. namespace가 다른 같은
  번호는 `AMBIGUOUS`로 남긴다. 제목 유사도·Graph 유사도·모델 추론으로 연결하지 않는다.
  동일 source의 2교·3교가 같은 선택 파일을 참조하는 경우는 하나의 문항이며 최종 교차인
  3교를 사용한다. 서로 다른 source를 합치는 것은 아니다.
- 출판 당시 사용 사실과 현재 DB 원본의 동일 버전 여부는 다르다. 파일에서 버전을 확인할 수
  없으므로 현재 연결한 원본 revision을 명시적으로 pin하며 과거 파일을 확보했다고 주장하지 않는다.
- 편성·문항 사용 이력은 기존 Deliverable/Edition/Form/curated slot 정본에 저장한다.
  Graph·Item·풀이보고서·임베딩을 재생성하지 않는다.

## 양식 해석과 확장

양식 판별/셀 읽기 → typed `ContentWorkbookDocument` → 번호 연결을 분리한다. 작은 열 이름
변경은 명시적 reader 버전/별칭에서 처리하며 저장 계층을 수정하지 않는다. 모르는 열을 조용히
버리거나 의미를 추측하지 않는다. 단순 열 순서 변경은 제목 기반으로 처리한다.

묶음 공란은 최상위, 회차·단원 공란은 본문이다. 빈칸을 앞 행에서 자동 채우지 않는다.
같은 구간은 연속해야 하며 A→B→A는 자동 재정렬하지 않는다. 문항 번호 공란은 구간별 순서,
고유번호는 정확한 ASCII 숫자 다섯 자리다. 숫자로 이미 손실된 앞자리 0을 임의 복원하지 않는다.
배점은 기존 milli-point 정수로 변환한다. 인쇄일 공란은 공란이며 오늘 날짜를 대신 넣지 않는다.

매크로·외부 링크·셀 수식은 실행/허용하지 않는다. 드롭다운의 validation formula는 셀 수식과
구분한다. 초기 처리 한도는 압축 8MiB, 해제 64MiB, 배치 10,000행이며 worksheet/XML/string
각 한도도 검사한다. 이것은 자원 한도이며 편성 자체의 역사적 200문항 제한을 되살리는 것이 아니다.

## 접근 패턴과 성능

2026-11-13 소스 보강: 준비·기존 proposal 조회·저장은 `content_workbook_layout.py`의 같은 ordered group/form
iterator로 실제 생성할 section 한도를 확인한다. 한도는 기존 Edition 계약의 10,000개로
유지하며, 행 10,000개와 동일한 뜻은 아니다. 빈 묶음은 GROUP을 만들지 않는다. membership은
set이므로 시간 O(행 수), 공간 O(고유 구간 수)이며, 미리보기 검사는 새 ID나 slot을 생성하지
않는다. 초과하면 `CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE`로 준비 전에 거절한다.
이미 보관한 과대 proposal도 같은 오류로 조회/저장을 거절하지만 Artifact·receipt는 보존한다.
V1 preview의 `can_commit == 미연결 행 없음` 의미와 schema bytes는 바꾸지 않는다.
새 저장소·cache·DB index·transaction·queue가 필요하지 않으며, 정본 source/revision/hash와
기존 권한/멱등 경계도 그대로다. preview에서 별도 수식으로 개수를 세거나 실제 전체 layout을
생성하는 대안보다, 실제 layout과 작은 키 iterator를 공유하는 방법이 단순하고 일치성이 높다.

주 작업은 순서대로 행 읽기, 고유번호 membership/dedup, indexed source 조회, 불변 계획 조회와
원자적 편성 생성이다. 행은 tuple, 번호별 후보는 dict/set, 순서는 입력 occurrence로 유지한다.
전체 시간은 파일 크기+행 수에 선형이고, DB는 namespace+번호 기존 unique index를 사용한 bounded
batch 조회다. source/파일 해시는 실제 입력·Artifact 해석 경계에서만 검사한다. 조회마다 원본
문항 파일을 모두 읽지 않는다. 미리보기는 최대100행씩 반환하며 큰 proposal은 Artifact에 남긴다.

## 동시성·재전송·실패

준비본은 원본+업로더+양식 버전에 대해 멱등이다. 재전송은 확정된 proposal을 반환하며 새 현재
revision으로 조용히 바꾸지 않는다. 파일 확인 이후 등록 시에도 실제 권한·source 상태·exact
pointer를 재검증한다. 미해결 행을 빈 배치로 성공 처리하지 않는다.

동일 파일의 중복 콘텐츠 생성은 기존 Deliverable unique key와 content receipt로 막는다.
첫 저장은 완성된 전체 구간/배치를 기존 edition snapshot owner로 한 트랜잭션 안에서 생성한다.
양식에서 인쇄 완료라고 명시한 경우에만 기존 인쇄 담당의 transaction 진입점을 재사용하여
같은 트랜잭션으로 인쇄 사실을 기록한다. 인쇄 상태 UNKNOWN은 인쇄 완료로 만들지 않는다.
권한 부족·검증 실패·중단은 전체 저장을 rollback한다. 출력 제작은 이 요청에서 실행하지 않는다.

구형 release/schema bytes·실패 기록은 바꾸지 않는다. 새 RPC/schema는 additive다. 새 queue나
DB table은 만들지 않고 작은 receipt에는 proposal/output pointer만 둔다. 조회/등록 때 source가
없어졌으면 명시적 오류이며 다른 최신 문항으로 대체하지 않는다.

저장 응답이 불명확하면 브라우저는 같은 proposal/key로만 재확인한다. 원본 접근 거절 등
명시적 거절일 때만 사용자가 기존 Excel 목록을 확인한 뒤 로컬 확인 내역을 닫을 수 있다.
이때도 과거 저장이 없었다고 단정하지 않고 서버의 배치·receipt를 지우지 않는다. 재로그인 시
owner별 작은 포인터만 복구하며 원본 XLSX·전체 행·인증 정보는 브라우저 저장소에 넣지 않는다.

## 단순한 대안과 선택

브라우저가 번호를 한 개씩 조회해 기존 생성·저장·인쇄 HTTP 요청을 순서대로 호출하는 방법은
N+1 조회와 부분 성공·중복 저장 위험이 있어 선택하지 않는다. 반대로 범용 Excel 매핑 엔진,
별도 registry/queue도 필요 없다. 고정 양식 adapter와 기존 편성 owner의 단일 저장이면 충분하다.

## 검증

원래 빈 양식·열 순서 변경·텍스트/숫자 고유번호·날짜/배점·빈칸·반복·누락·구간 순서 및 공격성
ZIP/XML/수식을 검사한다. private 전송 길이/hash·현재 actor·reply correlation과 Web 업로드/확인/
저장/재조회 동선을 검사한다. 실제 동시 저장·동일 파일 재전송·실패 rollback·권한 회수·정확한
원본/사용 이력 연결은 disposable PostgreSQL에서 검증한다. 운영 DB를 테스트에 쓰지 않는다.
이 문서의 검증 계획을 실행 PASS로 미리 기재하지 않는다.

## 구현 확인 — 2026-11-12 UTC

- `GET template / PUT imports / POST query / POST commit`와 Web 업로드 화면을 연결했다.
  원래 Excel 편성/인쇄 담당을 재사용하며 DB migration·worker 실행·임베딩은 필요 없다.
- 원본 XLSX는 실행하지 않고 파일 구조/크기/수식/외부 연결을 검사한다. 번호 대조 결과를
  최대100행씩 보여주고 저장 전 사용자 확인을 요구한다.
- disposable PostgreSQL: 새 가져오기 검사16개를 포함해 편성·인쇄·사용 이력 회귀
  **77 PASS / 2 SKIP**. SKIP은 기존 사설 원본 workbook을 지정해야 하는 별도 읽기 검사다.
  동일/다른 사용자 동시 제출, 재전송, 저장 후 수정 보존, 인쇄 후 예외의 전체 rollback,
  권한/원본 사용 불가, 같은 파일의 2교·3교 연결을 검증했다.
- 401행 번호 해석은 두 고유번호 반복 시 SQL3회, 서로 다른 미등록 고유번호401개 시
  SQL4회였다. 문항별 반복 조회나 원본 한글 파일 전체 읽기는 하지 않는다.
- Web의 실제 Chromium 검사에서 업로드→미리보기→명시적 저장→기존 Excel 문항 목록 열기,
  페이지 이동, 계정 전환, 같은 키 복구, 오류 후 연결 내역 닫기를 검증했다.
- API/소켓/입력 검사·OpenAPI·주변 회귀145개, Web 관련74개, parser/기존 편성 unit123개
  검사 묶음이 통과했다. 검사 묶음 사이에는 중복이 있으므로 합산하지 않는다.
  Ruff·mypy와 개발 문맥 검사를 통과했다.
- **소스 구현·비운영 검증 단계이며 운영 배포는 하지 않았다.** 운영 활성화 시 기존
  platform/Catalog/API/Web 호환 release 절차를 사용한다. 실제 사용자 자료 업로드나
  교재 배치 변경은 이번 개발 검증에서 실행하지 않았다.

## 운영 배포 — 2026-11-12 UTC

후속 사용자 승인으로 구현 commit `7b1fa87813af7ae8a77c8ca22915eb1517afd792`를 운영에
반영했다. 앞 절의 미배포 표시는 소스 검증 완료 당시의 기록이다.

- API/contracts/shared platform·Catalog·runner 및 Web을 같은 후보로 설치했다.
  기존 공식 installer와 no-migration 호환 release 절차를 사용했다.
- QUERY owner `11d826d2`와 기존 numerical/controller는 유지하고 API provider의 정확한
  source/wheel/member hash만 호환 갱신했다. 채팅은 기존 06번 슬롯과 인증을 유지한다.
- DB head `20261110_0077` 그대로이며 migration·권한 확대·문항/Graph/임베딩 재생성은 없다.
  INDEX·자료 학습 설정 및 실행 identity, Pack1.20.19와 기존 출제 경로를 보존했다.
- 처리 중 worker/command/HWPX/chat/native query가 없음을 확인한 뒤 기존 creative
  producer를 SIGINT drain하고 교체했다. Catalog/API→채팅 worker→채팅 owner→QUERY→Web
  순서로 재개했으며 기존 네 runner·maintenance·producer도 다시 active임을 확인했다.
- 설치 API/platform/contracts 실제 member2,887개를 원 wheel과 대조했다. Web 설치 검증은
  76개 파일 PASS. HTTPS의 HTML/app/import-controller/편성 JS/CSS가 wheel과 일치한다.
  API READY·HTTPS 로그인 화면200·Catalog 신규 Workbook branch와 미인증 경로401 확인 PASS.
- INDEX는 배포 전 이미 failed/PID0이었다. 그 상태와 identity를 그대로 보존했으며, 이번
  업로드 배포를 임베딩 복구/실행 성공으로 해석하지 않는다. 자료 학습 PID/identity는 동일하다.
- 실제 사용자 인증으로 workbook 업로드·교재 저장은 실행하지 않았다. 비운영 통합/실제
  Chromium 검사와 위 운영 설치 smoke를 구분하며, 사용자 양식 다운로드 확인은 별도다.
  운영 테스트 교재·문항/배치·실패 이력 변경·신규 모델 실행은 모두0건이다.

보호된 release/rollback wheel·설정·설치·smoke 근거는
`/var/lib/eom-excel-workbook-release-20261112`에 보관한다. 이전 API/Catalog `c0dafbe3`,
Web `d1328814`의 호환 복구 포인터를 보존하며 데이터 삭제나 DDL 후퇴로 복구하지 않는다.
최초 진단 smoke의 정적 자산 URL 오기(`/studio/static`,404)는 진단 스크립트만
`/studio/assets`로 고친 뒤 재검증했다. 운영 구현 수정이나 재배포는 없었으며 이전 로그는 보존했다.
