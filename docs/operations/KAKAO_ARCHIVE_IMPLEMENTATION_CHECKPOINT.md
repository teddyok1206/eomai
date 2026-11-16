# KakaoTalk 구현 체크포인트

## 최신 체크포인트 — 2026-11-16 MANUAL 연결·설치 전 경계

- 이전 source checkpoint `1e33207c` 이후 수동 로그인 의도/짧은 접근 허가를 저장하는
  Catalog owner와 0083 migration, 실제 API/RPC/BFF 및 화면 controller를 추가했다.
  시작 접수는 PREPARING이며 실제 browser와 gateway 준비 확인 없이 ACTIVE가 되지 않는다.
  현재 사용자·Identity session·ADMIN/remote 권한·binding owner를 다시 확인한다.
- protected 프로필 최초 설치 증거와 실제 flock, browser/gateway의 boot·invocation·cgroup·
  systemd Job 관측을 연결했다. PID 0/비활성이라도 queued Job이 있으면 인계하지 않는다.
  만료·응답 유실·이전 실행 실패를 성공이나 새 실행 권한으로 바꾸지 않는다.
- MANUAL Playwright/Xvnc driver와 별도 UDS gateway supervisor를 구현했다. gateway 종료는
  이미 열린 stream도 닫으며, 같은 grant 재읽기는 TTL을 연장하지 않는다. Catalog에는 raw
  VNC/profile cookie 접근 권한을 주지 않는다. AUTO collector/실제 selector는 후속 범위다.
- 새 Kakao 전용 환경은 `/opt/eom/conda/envs/eom-kakao-*`를 사용한다. 기존 `/srv` 환경의
  소유권을 완화하지 않는다. 고정 installer는 준비된 보호 prefix만 소비하며, 최초 profile
  receipt는 runtime 업그레이드에서도 보존한다. 실제 prefix 준비·설치는 아직 하지 않았다.
- 합동 source/API/BFF/Chromium/계약·의존성 검사 **973 PASS**, 공식 guarded disposable
  PostgreSQL **73 PASS**. 후자는 동시 접수·동일 key 재전송·갱신/종료 경합과 현재 모드
  검사까지 포함한다. 별도 설치·driver/browser/PDF 묶음 **192 PASS**, 프로필/RPC/API
  독립 검토 **47 PASS**. 겹치는 검사는 합산한 고유 테스트 수로 표현하지 않는다.
- 별도 집중 리뷰에서 잔존 gateway `.next` 파일을 최초 실행으로 오인할 수 있는 경계를
  재현해 고쳤다. 같은 파일 관측 규칙을 재사용하며 추가 3개 부정 검사를 포함한 관련
  **176 PASS**를 확인했다. 잔존 파일을 삭제하거나 실행을 강행하지 않는다.
- 전역 import 추적 mypy는 이번에 변경하지 않은 `command_adapter.py`에서 기존
  WorkflowRequest union 접근 오류 6개를 보고했다. Kakao 변경 모듈 검사는 별도로
  수행하며 이 무관한 오류를 감추기 위해 출제/자료 학습 코드를 수정하지 않는다.
- 아직 남은 활성화 경계: Catalog runtime coordinator 조립, 현재 lease의 Caddy admission,
  전용 runtime 실제 설치·UID/sandbox 검사와 호환 migration release. `remoteViewEnabled`는
  기본 꺼짐이며 소스 테스트를 운영 화면·카카오 로그인 성공으로 보고하지 않는다.
- 운영 migration·배포·카카오 로그인·수집은 이 체크포인트에서 실행하지 않았다. 기존 문항,
  GPU 실행·정본·실패 이력 및 인증 자료는 변경하지 않았다.

## 2026-11-16 착수

사용자가 제공한 [설계 정본](../architecture/KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md)을
현재 `6d7fcde708a637aec61a1031042b2b7ae4ba1089` 기준으로 구현한다.
이 문서는 구현 진행 기록이며 운영 활성화·카카오 수집 성공 증거가 아니다.

사용자 확정 변경: 메뉴 위치는 **일반 → KakaoTalk**이다. 설계서의 사용자용
`학생 질문` 명칭보다 이 결정이 우선한다. 내부 feature/route는 `kakao-archive`를
유지하고 작업 설명은 쉬운 한국어로 제공한다. 원본 설계 문서는 보존한다.

## 작은 구현 결정

- 책임: 기존 Studio/BFF → API → Catalog 업무 소유자 → Orchestrator 격리 실행·발행.
  학생 질문은 Item/Graph/자료 학습과 다른 비공개 업무이며 그 실행 경로를 호출하지 않는다.
- 정본: 원본 CSV/사진과 긴 본문·질문/발행 manifest는 기존 Artifact. DB는 소유자,
  논리 identity, immutable revision, 상태·색인·exact pointer만 저장한다.
- 새 binding은 DRAFT, 자동 수집은 꺼짐. 실제 채널 관측 전 ACTIVE를 만들지 않는다.
  모든 접근은 현재 operator 권한과 owner를 확인하며 ADMIN에도 타인 원문을 공개하지 않는다.
- 초기 구현은 CSV 정규화·질문 후보, offline PDF, 화면 controller를 독립 검증한다.
  미구현 route를 화면에 활성화하거나 fixture 성공을 카카오 실증으로 보고하지 않는다.
- snapshot ordinal은 occurrence 정체성이며 같은 시각·같은 내용도 지우지 않는다.
  안정 ID가 없으면 bounded alignment/snapshot-only로 남기고 이름으로 역할을 추측하지 않는다.
- 조회는 owner/binding을 먼저 제한한 keyset/index 조회. 원문 순회는 O(N), 동일 bytes 조회는
  binding+SHA unique lookup, 장기 전체 O(N²) 비교를 만들지 않는다.
- 변경은 owner별 멱등 key와 request SHA, 짧은 transaction/CAS, 명시적 transition으로 처리.
  브라우저·파일 변환 동안 DB 잠금을 유지하지 않는다. worker 결과와 publication Job은 분리한다.
- 작은 불변 정책 값은 frozen DTO로 충분하다. 별도 queue/framework/DB/AI 서비스를 추가하지 않는다.
- 새 worker pure-contract wheel은 isolated PDF/browser가 Catalog·DB 의존 없이 실행하기 위한
  실제 배포 경계다. PyMuPDF는 기존 의존성을 재사용하고 browser 의존은 후속 전용 runtime에 한정한다.
- 카카오 selector·계정 capability는 아직 UNKNOWN. 인증 없이 구현할 수 있는 부분을 먼저
  완료하고, 수동 로그인은 실제 private runtime과 한 방 실증 준비 후 요청한다.

## 단계

1. P1 계약·CSV/정합/질문 규칙·offline PDF와 익명 fixture 검증 — 소스 검증 PASS.
   별도 설치 worker의 PDF 출력은 확인했지만 운영 sandbox·Artifact 발행 연결은 아직 미완료다.
2. P2 Catalog 저장·권한·UI/API 연결 — DRAFT binding 경계 소스 구현·검증 완료,
   binding·학생 disposable DB 검증 PASS. 학생 화면 연결과 대화/질문/묶음 영속 연결 진행 중.
3. P3 private browser·원격 lease·수동 인증 안전 경계 — pure 계약/종료·복구 규칙 검증,
   실제 browser/gateway 설치·영속 owner 연결은 대기.
4. P4 실제 한 방의 CSV·복수 사진 실증 — 인증 요청은 여기 직전에.
5. P5 전체 방·주기 수집·복구, P6 학생별 최종 PDF, P7 호환 설치·live 검증 — 대기.

기존 김병훈 문항 작업과 GPU INDEX는 마지막 조회에서 오류 종료 상태다. 완료된 정본·
풀이·벡터·실패 이력은 보존하며 정상 모니터링 중이라고 표현하지 않는다. 이번 새 기능의
소스 구현은 그 복구를 기다릴 필요가 없고, 공유 설치본 변경은 실제 실행 상태와 조율한다.

## P2 제한된 binding 저장 경계

- Catalog가 owner별 연결 설정만 저장한다. 현재 구현 범위는 DRAFT 생성/조회,
  정책 successor와 RETIRE이며 실제 채널 검증·수집·schedule 활성화는 포함하지 않는다.
  브라우저의 채널 확인 주장을 ACTIVE 근거로 받아들이는 명령은 만들지 않는다.
- 정본은 binding의 owner/lifecycle/current pointer, 작은 immutable 정책 revision,
  immutable command receipt 세 테이블이다. 대화·학생·파일·인증정보는 여기에 없다.
  논리 ID와 정책 revision ID 및 canonical 정책 SHA를 분리한다.
- owner+binding key 조회와 owner+binding ID keyset 목록은 B-tree를 사용해
  O(log B + page size), 명령 재전송은 owner+scope+key unique 조회를 사용한다.
  정책 previous/current pointer는 같은 binding의 revision만 composite FK로 연결한다.
- 한 명령은 짧은 transaction에서 현재 Identity permission/ADMIN 역할/세션과 owner를
  확인하고 멱등 request SHA, resource_version/parent CAS, 정책·receipt를 함께 확정한다.
  동일 intent advisory lock과 unique 제약으로 concurrent replay를 합친다. DB 잠금 중
  browser/NAS/worker 작업은 없다. 권한 조회는 Identity의 기존 repository를 재사용한다.
- 같은 key의 다른 내용은 conflict, stale parent/version은 precondition failure다.
  replay는 현재 권한을 재확인하고 원래 result revision을 반환한다. RETIRE는 삭제가
  아니며 정책·receipt UPDATE/DELETE는 기존 immutable trigger로 금지한다.
- 현재 DB 인증과 짧은 application transaction을 사용하며 별도 ACL framework,
  scheduling queue, auth store 또는 generic event-sourcing을 추가하지 않는다.
  하나의 가변 정책 행만 두는 대안은 재전송·기존 실행 pin을 보존할 수 없어 제외한다.
- migration은 새 0080과 ADMIN 전용 5개 permission seed로 한정한다. source/DDL 검사와
  실제 disposable PostgreSQL 동시성 PASS를 구분하며 운영 migration은 별도 단계다.

P2 초기 소스 검증: binding 계약·파서/질문·Catalog 최소 권한·기존 bootstrap 회귀 80개 PASS,
새 owner 소스 5개 mypy PASS, Ruff/format PASS. 당시 PostgreSQL 13개는 임시 DB 준비 전
SKIPPED였다. 아래 후속 실제 검증이 이 미실행 경계를 닫으며 초기 결과를 소급 변경하지 않는다.
Catalog 설치 권한은 새 테이블 3개 SELECT/INSERT 및 binding만 UPDATE다. 현재 세션
확인은 `api_sessions`의 ID·owner·철회·만료 5개 열 SELECT만 추가하며 token/credential
조회, Identity 변경, API/worker의 archive DB 권한은 추가하지 않는다.

## 일반 → KakaoTalk 화면과 HTTP 경계

- 기존 Studio 메뉴·안내 모드·권한·뒤로가기 경로에 `일반 → KakaoTalk`을 연결했다.
  기존 세션 owner가 바뀌거나 종료되면 선택과 원문 화면을 비운다.
- 현재 공개 API는 연결 초안 생성/조회/정책 변경/종료뿐이다. BFF는 실제 공개된
  DRAFT/RETIRED DTO를 사용하며, NOT_VERIFIED에서는 방 조회·수집·원격 로그인·PDF
  요청을 호출하지 않는다. 후속 화면 fixture는 그 API가 운영에 존재한다는 증거가 아니다.
- API → private Catalog RPC → Catalog owner를 기존 경계에 추가했다. 실제 세션,
  권한·owner, 멱등 key, If-Match/CAS, reply identity·policy pin을 검증한다.
- 합동 검증 200개 PASS: CSV·질문 규칙·Artifact intake·binding/RPC·offline PDF·
  실제 API/BFF HTTP·Chromium 화면·개발 문맥·의존성 경계. HTTP 항목은 실제
  TestClient/gateway와 가짜 Catalog owner를 결합한 것이며 운영 DB 검증이 아니다.
- 별도 기존 shell/안내 모드/어휘/route/배포 파일 목록 회귀 54개 PASS.
- 소스 OpenAPI와 schema mirror를 갱신했다. 운영 설치본·migration·카카오 인증은
  변경하지 않았으며, 실제 수집/학생별 발행/live PASS는 아직 선언하지 않는다.
- 다음 설치 전 필수: 0081까지 지원하는 release context,
  호환 platform/API/Web 및 private runtime 검증. 현재 0079 배포 절차를 그대로
  사용해 새 migration을 설치하지 않는다.

## 2026-11-16 학생 디렉터리·실제 PostgreSQL 후속

- `kakao_students.py`와 Catalog 학생 서비스·0081 migration을 추가했다. 이름은 key가
  아니며 동명이인, 표시 이름 successor, 소속 owner 확인, retirement, exact revision
  조회를 지원한다. large content/사진/credential을 DB에 넣지 않는다.
- 학생·binding의 멱등 잠금/정규 직렬화만 좁은 공통 함수로 재사용했다. 현재 권한 확인과
  domain별 state/CAS는 담당 서비스에 남겼다. 별도 generic repository/queue는 없다.
- Linux 인증 후 공식 guarded prepare로 생성한 임시 DB:
  `/tmp/eom-api-testdb-20261116044952_78727a2c`.
  운영 DB에는 연결하거나 migration을 적용하지 않았다.
- 처음 실제 실행: 18 PASS / 3 FAIL. 변경 차단 자체는 작동했지만 테스트가 PostgreSQL
  드라이버의 `ProgrammingError`를 `InternalError`로 예상했고, 좁은 metadata 검사가
  무관한 미등록 ORM의 FK까지 정렬했다. 예외의 실제 immutable 메시지를 검증하도록
  고치고 이 owner의 직접 metadata 비교와 별도 전체 composition 검사를 분리했다.
- 재실행 21 PASS, 이어 전체 Alembic/ORM composition 포함 **22 PASS**. 4개 동시 생성은
  한 identity/receipt, 같은 부모의 동시 이름 변경은 한 successor, exact replay와
  이전 표시 revision 보존, 타인 ADMIN·철회된 세션 거부, immutable trigger·composite FK,
  keyset 3페이지의 일정한 join 조회까지 실제 PostgreSQL에서 확인했다.
- 학생 소스/계약·기존 binding 회귀 81 PASS, owner 관련 5개 소스 mypy PASS.
- 임시 DB는 다음 같은 기능의 영속 검증에 사용할 수 있게 아직 보존 중이다. cleanup은
  실행 완료 후 별도로 기록한다. 이 PASS가 카카오 수집·원격 인증·운영 배포를 뜻하지 않는다.
- 학생 public RPC/API/BFF/UI, private remote lease와 PDF 실행 adapter를 연결 중이다.
  카카오 실제 계정 로그인은 아직 요청하지 않았다.

## 2026-11-16 P2 화면·질문/PDF 연결 체크포인트

- 학생 생성/목록/정확한 revision 조회/이름 변경/사용 중지를 기존 Catalog socket,
  API/BFF, `일반 → KakaoTalk`에 연결했다. 방 mapping을 이름으로 추측하지 않는다.
  현재 READ/EDIT 권한과 owner를 검사하며 표시 이름이 같은 학생도 별개 identity다.
- 학생 controller는 채널 선택과 독립된 owner/응답 순서 검사를 사용한다. 계정 변경,
  권한 철회·늦은 응답, 이전 revision에 대한 변경, 같은 intent 재조회가 검증됐다.
  미확정 intent는 같은 페이지 이동에서는 유지하지만 hard reload/login reset 이후
  복구는 아직 영속 owner/조회 UX 연결이 필요하다. browser에 개인 원문/세션을 저장하지 않았다.
- 순수 질문 편집·분할/병합·packet 선택과 기존 Artifact 발행 adapter를 연결했다.
  원문·사진을 packet마다 복사하지 않으며 source span/hash와 사진 occurrence/revision,
  학생·mapping pin, FINAL blockers를 exact 질문에서 재검증한다.
- 학생 subset → local render projection → 실제 한글·사진 PDF/PNG까지 익명 fixture로
  통과했다. 문장→사진→문장 순서, 명시적 회전/crop, 원본 불변, 파생 hash를 보존한다.
  같은 요청의 worker 재실행이 아니라 동일한 종료 attempt 결과 수락 복구를 구현했다.
- 통합에서 발견해 수정한 두 문제: PDF 하단 float 누적 `790.0000000000001`은
  조판 좌표를 1e-6 pt로 고정해 실제 790 pt 경계를 유지했다. 또한 packet의 binding만
  다른 값으로 바꿀 수 있던 projection 검사를 추가했다. 각각 실제 PDF와 부정 fixture로 확인했다.
- 수집 command/result·capability·inventory의 순수 계약도 추가했다. worker 결과가
  미확인 capability를 full-history/원본 화질/확인된 방향으로 승격할 수 없으며,
  unsupported 사진도 실패 사유와 함께 남긴다. 실제 selector·수집 실행은 아직 없다.
- 최종 합동 소스 검증 **582 PASS**: Kakao 계약·파서·권한·RPC/API/BFF, 실제 Chromium,
  질문/packet·local PDF·중단 후 수락·remote/capture 규칙, 설치 platform wheel import,
  OpenAPI·개발 문맥·의존성 경계. 앞의 disposable PostgreSQL **22 PASS**와 별도다.
- 기존 shell/GUI 회귀 25 PASS/1 environment SKIP 후, 같은 opt-in Playwright 환경으로
  해당 파일을 다시 실행해 **4 PASS**. 전체 582 검사에는 Kakao 실제 Chromium이 포함된다.
  FastAPI TestClient의 기존 Starlette/httpx deprecation warning 하나는 남으며 새 의존 설치로 우회하지 않았다.
- schema audit: canonical 1441 / mirror 1092 / reference 12326 PASS. Ruff 64개 파일·format PASS.
  별도 non-editable pure-contract/worker wheel에서도 실제 한글·사진 PDF 생성 PASS.
  이는 같은 사용자 권한의 로컬 설치 검증이며 전용 UID/systemd sandbox PASS가 아니다.
- 설치 worker의 collection schema는 소스와 같은
  `sha256:9c9cd7cc4438a194acd157775261b4ac846e0b7ab12ee2aa05e79560777746ce`다.
  render/layout은 각 package-owned hash로 검증한다. 사진 원본이나 실제 학생 자료는 사용하지 않았다.
- 남은 핵심: Catalog room·불변 학생 mapping/원본 수락, 저장된 owner intent 기반 주기
  실행·fence, private 파일 전달과 question/packet/export 영속 연결, 브라우저/원격 runtime,
  실제 capability/CSV·사진 실증, 호환 운영 배포. 현재 학생/API 소스 PASS를 전체 완료로 보지 않는다.
- 다음 한 가지는 room·학생 mapping 저장 경계다. 검증된 binding별 source identity만
  canonical room으로 연결하고 worker가 제안한 room ID나 닉네임을 정본으로 믿지 않는다.
  자세한 최소 순서는 `KAKAO_COLLECTION_EXECUTION_BOUNDARY.md`에 기록했다.
- 운영 API/Web/Catalog·카카오 계정·기존 문항/벡터에는 변경이 없다. 새 로그인 요청도 없다.

## 2026-11-16 P2 방 연결·PDF 발행 및 P3 프로세스 경계

기준은 로컬 구현 체크포인트 `d37dc7dd` 이후 변경이다. **운영 배포·실제 카카오 수집은
아직 하지 않았다.** 이번 검증에는 합성 이름/대화/그림만 사용했다.

- 확인된 방의 canonical identity와 학생 mapping을 0082에 저장한다. 최초 원본·관측
  Artifact를 현재 owner 권한으로 재확인하며, 공개 임의 방 생성 API는 없다. 이름으로
  학생/방을 합치지 않는다. 연결·해제는 version/parent CAS, exact 학생 표시 revision,
  같은 요청 재확인과 불변 이력을 유지한다. 목록은 기존 unique B-tree와 한 bounded join을
  사용하며 같은 열의 중복 index는 만들지 않았다.
- Studio 방 목록·학생 연결·해제까지 기존 RPC/API/BFF에 연결했다. 새로고침 후 확정된
  DB 상태를 읽고 늦은 응답·다른 owner 응답을 차단한다. 미확정 변경의 intent 복구는 같은
  페이지 세션 범위이며, 새로고침을 넘는 미확정 intent 복구까지 구현했다고 주장하지 않는다.
  학생·방 이름과 사유의 길이는 UTF-16 길이가 아닌 schema의 Unicode code point 기준으로
  맞췄고, 이모지·ZWJ 조합을 실제 Chromium에서 확인했다.
- `kakao_pdf_publication.py`가 core에 수락된 PDF/PNG/layout을 기존 Artifact owner로
  발행한다. export+attempt의 원래 발행을 재사용하며 재렌더하거나 PDF를 다른 정본으로
  복사하지 않는다. DB/Job에는 ID·hash·count만 저장한다. 실제 export DB 수락과 비공개
  다운로드 use case는 다음 단계이며 이 helper의 PASS와 구분한다.
- 최초 PDF 소스 검사에서 5 FAIL/13 PASS를 확인했다. 유효한 원본 render JSON의 생략된
  optional field가 Pydantic 직렬화에서 추가되어 hash가 달라지는 문제였다. 원래 입력
  bytes를 검증하도록 수정했으며, whitespace/생략 필드도 보존하는 18개 focused 검사가
  통과했다. 입력 hash 검사를 제거하거나 옛 결과를 변경하지 않았다.
- 실제 임시 DB에서 0082 적용·되돌리기·재적용을 확인했다. 첫 migration 검사에서 source의
  예상 head가 0079였던 차이를 발견하여 `CURRENT_MIGRATION_REVISION`을 0082로 맞췄다.
  현재 운영 release operator의 0079 지원을 몰래 넓히지는 않았으며, 운영 설치에는 별도
  compatible release/context successor가 필요하다.
- 첫 통합 DB 검사: 40 PASS/8 FAIL. 하나는 좁은 metadata 테스트에 신규 Artifact FK의
  dependency가 빠진 경우였고, 일곱은 negative fixture가 이미 승인된 Artifact를 직접
  UPDATE해 기존 immutable trigger가 차단한 경우였다. metadata 검사는 FK closure를
  포함하고, replay fault는 read boundary에서만 주입하도록 고쳤다. trigger/FK를 끄거나
  approved 정본을 수정하지 않았다. fault 제거 뒤 원래 정본의 replay도 확인한다.
- 후속 공식 guarded DB 검사 **48 PASS**: 기존 binding/학생, 신규 room 23개, PDF 발행
  3개, 전체 Alembic/ORM composition. 같은 키의 동시 admission·mapping, 경쟁 CAS·학생
  rename 경합, 권한·source 검증, publication 중단/응답 유실·재조회와 원본 불변을 확인했다.
  disposable DB는 후속 검증을 위해 보존하며 운영 DB 테스트는 하지 않았다.
- 합동 소스 검사 **733 PASS**: 계약·RPC/API/BFF·Chromium·PDF·설치 platform wheel·
  OpenAPI·의존성/개발 문맥. 이후 browser/room/context의 최종 변경 검사는 **93 PASS**.
  새 핵심 소스 14개 strict mypy PASS, Ruff/format와 shell syntax PASS.
  기존 Starlette TestClient deprecation warning 한 건은 별도 의존 교체 없이 유지했다.
  schema audit는 canonical 1445 / mirror 1096 / reference 12390 PASS다.

### 별도 브라우저 실행 경계

- AUTO/MANUAL은 하나의 고정 unit과 실제 profile flock을 공유한다. fixed driver만
  실행하고, 현재 owner/fence 확인과 실제 invocation/boot/cgroup 종료를 요구한다.
  초기화 marker·per-run 입력을 보존하여 불확실한 시작을 새 실행으로 위장하지 않는다.
- 실제 subprocess 검사에서 SIGTERM 처리 중 driver가 7로 종료한 것을 supervisor가 0으로
  덮던 결함을 발견해 수정했다. 정상 close/flush, 실패 종료, 강제 timeout을 구별한다.
  supervisor/OS adapter 61개 검사와 별도 non-editable wheel 검증을 통과했다.
  이는 현재 사용자 권한의 local 검증이지 전용 UID/systemd sandbox의 live PASS가 아니다.
- collector wheel SHA:
  `sha256:4a07a87776bb547b3f7e7a1e65697a34318e67ee525cf9f52dbd8a124268ab29`.
  검증 설치 위치는 `/tmp/eom-kakao-browser-verified.FckefOrG`다.
- actual driver·Playwright/Xvnc/gateway·전용 계정은 아직 없다. `systemd-analyze verify`도
  미설치 전용 interpreter를 지적하므로 전체 unit 설치 PASS로 기록하지 않는다.
  READY 이전 시작 실패의 staged intent는 후속 owner reconcile이 필요하다.

### 다음 실제 경로

1. MANUAL browser driver와 private gateway/현재 사용자 lease를 연결해 안전한 로그인
   화면을 준비한다. 실제 설치·권한/종료 검증 전 원격 화면을 공개하지 않는다.
2. accepted collection run/capability에서 snapshot·occurrence·첨부 연결을 수락하는
   owner를 구현한다. `ResolvedKakaoQuestionSource`를 만들었다는 것만으로 원문 권한을
   얻지 않으며, worker의 source identity 주장을 바로 canonical source로 받지 않는다.
3. 고정된 질문 intent/revision → 기존 pure 편집/Artifact 발행 → 짧은 재검증 CAS →
   packet → 한 학생 PDF로 연결한다. 이 수직 경로를 확인한 뒤 전체/주기 수집으로 확장한다.

추가 비밀번호 요청 없이 가능한 부분을 계속 구현한다. 기존 문항·GPU 완료 데이터·실패
이력은 보존하며, 이 체크포인트를 전체 goal 완료 또는 운영 활성화로 보고하지 않는다.
