# KakaoTalk 구현 체크포인트

## 진행 중간 저장 — 저장된 대화·사진에서 학생별 PDF까지

`871e2df3` 뒤에 기존 source/question/packet owner와 renderer/Artifact publisher를 연결했다.
이 단계는 **실제 저장소와 별도 PDF subprocess를 사용하는 합성 입력 검증**이다. Studio의
다운로드 API, 보호된 운영 worker, 실제 카카오 계정 수집의 완료를 뜻하지 않는다.

- `resolve_student`의 exact selection만 local staging 아래 새 전용 입력 디렉터리에
  물질화한다. 원본 사진은 검증된 Artifact FD에서 고유 pointer별 한 번 읽고 bytes를
  바꾸지 않는다. 같은 PNG가 두 메시지에 붙은 경우 binary는 한 번 읽되 사진 occurrence
  두 개와 순서는 실제 PDF에도 남는다. NAS를 worker 입력 폴더로 사용하는 것은 거부한다.
- 임시 PostgreSQL의 CSV·사진 수락 → 질문 저장·확정 → FINAL packet → 실제 PDF 렌더 →
  canonical Artifact 발행·검증된 파일 재조회가 통과했다. 같은 이름의 서로 다른 학생을
  별도 한 페이지 PDF로 출력하고 다른 학생의 문장이 섞이지 않음을 확인했다.
- 같은 완료 attempt의 publication replay는 같은 output pointer를 반환하며 추가 render를
  하지 않는다. 이는 아직 없는 HTTP export 요청의 멱등 검증을 대체하지 않는다.
- 다른 학생 selection, 잘못된 font hash, 파일/디렉터리 링크, NAS 입력 경로, 기존 파일이
  있는 입력 폴더를 거부한다. 물질화 뒤 session이 철회되면 결과를 반환하지 않고 실패한
  staging을 보존한다. PDF subprocess에는 DB URL·인증정보를 상속하지 않는다.
- 공식 guarded PostgreSQL 최종 검사 **135 PASS (42.62초)**, 변경 Python formatter/linter,
  입력 adapter mypy 및 `git diff --check` PASS다. 앞선 동일 경계의 134 PASS 뒤 NAS 경로
  거부 검사를 추가한 결과이며, 겹치는 수를 합산하지 않는다. 기존 source unit 1081 PASS와
  개발 문맥 13 PASS도 참조한다.
- wire schema·DB migration·운영 runtime을 추가 변경하지 않았다. source head는 0086,
  운영은 앞서 기록한 0084 release 그대로다. 다음 연결은 영속 export 접수·완료 pointer와
  현재 권한을 확인하는 API/Studio 조회·다운로드이며, 실제 카카오 한 방/전체 수집도 남는다.

## 진행 중간 저장 — packet owner, 0a812810 이후 소스 작업

사용자가 goal을 다시 등록하면서 검증·커밋·푸시·운영 배포를 명시했다. 전체 범위는
합성 입력의 PDF·Studio 다운로드 완주 후 실제 카카오 한 방, 전체 방 주기 수집까지다.
이 중간 저장은 그 완료를 뜻하지 않으며 추가 로그인은 아직 요청하지 않았다.

- 기존 질문 batch resolver와 packet publisher를 재사용해 선택한 exact question revisions,
  순서, KST 기간, 답변 포함 설정, DRAFT/FINAL을 저장하는 packet owner를 추가했다.
  제목은 작은 불변 DB revision 값이며 원문·사진·큰 선택 목록은 복사하지 않는다.
- 같은 요청 동시 접수, 발행 직후 중단·원래 Artifact 재사용, competing parent/version CAS,
  과거 packet 재조회, 이후 질문 수정 뒤에도 원래 선택 유지가 실제 임시 DB에서 통과했다.
- 합성 학생 2명의 질문을 같은 packet에 저장하고 새 service instance로 다시 열었다.
  `resolve_student`가 해당 학생의 exact question/source만 반환하며 같은 표시 이름으로
  학생을 합치지 않는 것을 확인했다. 잘못된 학생·다른 owner·철회된 session은 거부한다.
- 여러 방 접근은 기존 현재 Identity/binding 확인과 indexed room batch로 연결했다.
  source closure의 현재 권한/metadata를 확인하되 방마다 같은 Identity 조회를 반복하지 않는다.
- 최종 source unit·권한·문맥·이전 계약 **1081 PASS**, 공식 guarded PostgreSQL
  **126 PASS**, 변경 core 5개 mypy·formatter/linter와 schema audit PASS다.
  canonical 1459 / mirror 1106 / reference 12499이며 겹치는 테스트 수는 합산하지 않는다.
- 새 source head `20261116_0086`은 disposable DB에만 적용했다. 실제 운영은 기존
  0084 compatible release 그대로이며 AUTO/MANUAL과 실제 질문 PDF 제공을 활성화하지 않았다.
  공개 API/GUI, atomic 분할/병합, export claim/실제 renderer/private download와
  카카오 관리자 계정의 한 방/전체 방·주기 실증은 계속 남는다.

## 진행 중간 저장 — 질문 owner, 832a4803 이후 소스 작업

외부 검토 기준 뒤에 추가한 **질문 저장 use case의 소스/격리 검증**이다. 다음 사용자
체크포인트의 목표는 계속 CSV·사진 → 편집 → packet → 학생별 PDF·Studio 다운로드이며,
아래 중간 저장을 그 경로의 완료나 운영 활성화로 보고하지 않는다.

- accepted source의 `turn_v1` 후보를 새 논리 질문으로 등록하고, exact revision의 본문
  조회·확정/제외/선택 수정과 metadata 목록을 저장하는 owner를 추가했다. 생성 ID·시각·
  mapping pin을 예약한 뒤 I/O 밖에서 기존 publisher를 사용하고 CAS로 채택한다.
- 동일 intent 동시 접수·다른 intent의 competing edit·발행 직후 중단/재전송을 실제 임시
  PostgreSQL에서 확인했다. 중단 재개는 원래 논리/revision/Artifact pointer를 재사용한다.
  같은 시각·동일 문장인 두 occurrence도 두 개로 유지하며 DB에는 본문/사진을 넣지 않는다.
- packet/export용 exact batch resolver는 입력 순서를 유지하고 고유 source당 한 번 해석한다.
  같은 질문의 서로 다른 두 저장 버전을 읽어도 원본 resolution 해석 호출은 한 번이다.
  현재 binding/room/Identity 권한과 accepted source closure를 I/O 뒤 다시 확인한다.
- 첫 합동 DB 실행은 110 PASS/2 FAIL이었다. 새 head 상수 갱신 누락과, 테스트가 불변
  Artifact approval을 수정하려던 잘못된 fixture였다. source 철회는 실제 binding retirement
  use case로 검증하도록 바로잡았으며 immutable guard를 해제하지 않았다.
- 수정·batch resolver와 재기동 후 표시 교정 보존 확인 뒤 공식 disposable DB 검사 **115 PASS**, Kakao 관련 전체 unit과
  권한/의존성/개발 문맥/이전 release 계약 검사 **1062 PASS**다. unit 전체의 첫 invocation은
  선택적 Pillow가 없는 API interpreter여서 collection 오류였다. 기존 테스트용 Pillow
  11.3.0 materialization을 명시해 재실행했으며 운영 API 의존성은 바꾸지 않았다.
  변경 5개 core 모듈 mypy, formatter/linter, canonical/mirror/reference audit도 PASS다.
- source migration은 `20261116_0085`이며 실제 적용은 guarded disposable DB에만 했다.
  운영은 앞선 0084 compatible set 그대로다. 이후 운영 반영 전 새 head의 compatible
  release/context를 준비해야 하며, 1.26/0084로 새 소스를 배포하지 않는다.
- 아직 미연결: 공개 질문 API/GUI, 분할·병합의 atomic adoption, packet/export owner와
  인증 파일 다운로드, 실제 카카오 로그인·한 방/전체 방 수집·정기 실행.
  실제 카카오 계정 실증은 여전히 NOT_PERFORMED이며 추가 인증 요청은 아직 하지 않았다.

## 운영 부분 배포 결과 — 2026-11-16 10:55 UTC

사용자가 요청한 **미완성 기능의 부분 운영 배포**를 완료했다. 전체 KakaoTalk goal은
계속 진행 중이며, 이번 결과를 카카오 로그인·실제 대화 수집·학생별 PDF 완성으로
해석하지 않는다.

- API/platform/Catalog/QUERY와 기존 runner의 설치 source는
  `e355e7de8c7ffa1c3534717d754ed58d08b3e1d6`, Web은
  `8d8823a6da47c714f82015bb2a64b7dbb835e7df`인 호환 묶음이다. 마지막 source 변경은
  백엔드 권한 검사이므로 동일 UI를 다시 빌드하지 않았다. 실제 DB head는 `20261116_0084`다.
- `일반 → KakaoTalk`의 연결 준비·학생/방 화면과 해당 API/BFF를 반영했다. 새 화면 JS의
  HTTPS 응답 SHA는 source와 일치하고, 비로그인 source-binding 조회는 HTTP 401이다.
  실제 사용자 세션으로 설정/학생 CRUD를 수행한 live acceptance는 아직 별도 미확인이다.
  이후 사용자가 운영 GUI를 직접 확인하고 화면이 좋다고 응답했다. 이는 화면 확인 결과이며
  아직 실행하지 않은 카카오 수집·질문 저장·PDF 출력의 성공으로 확대하지 않는다.
- API 직접 ready와 HTTPS BFF ready, HTTPS 로그인 페이지는 정상이다. Catalog·QUERY·
  채팅 owner/worker·HWPX·네 개 Workflow runner와 creative owner의 active 상태를 확인했다.
  active/ready는 새 카카오 업무의 전체 성공이나 모델 작업 완료를 뜻하지 않는다.
- AUTO 수집과 MANUAL 원격 로그인은 비활성이다. 기존 브라우저 인증·비밀번호·채팅 모델을
  변경하지 않았다. 아직 준비본인 전용 runtime을 활성 release로 표시하거나 게시하지 않았다.
  질문/packet/export의 영속 owner와 실제 PDF 제공은 다음 구현으로 남는다.
- 최초 `8d8823a6` 반영 뒤 Catalog 시작이 기존 Identity fence와 충돌했다. 원인은 Kakao
  권한 확인에 필요한 세션 metadata 5열 읽기와, 이전 fence의 모든 세션 열 읽기 금지가
  양립하지 않는 것이었다. `e355e7de`에서 Identity가 정확한 5열 목록을 소유하고 Catalog
  grant와 fence가 함께 사용하도록 수정했다. 전체 세션 조회·추가 열·token/credential 읽기·
  IAM 쓰기 금지는 유지하며 actor/업무 권한을 넓히지 않았다. 최초 실패 기록은 보존했다.
- 이 수정은 SQL/설치/grant 집중 검사 60 PASS, 관련 fence 검사 93 PASS와 별도 disposable
  PostgreSQL 16 PASS를 통과했다. 실제 DB 검사는 허용된 metadata와 추가 열·전체 SELECT·
  UPDATE 거부를 함께 확인한다. 겹치는 테스트 수를 합산하지 않는다.
- 최종 배포의 `activated.json`, 설치 member 검사와 변경 전후 설정 hash는 protected release
  기록에 보존했다. 최초 migration/admission 기록과 수정 release의 기록은 별개다.
  수정 source 자체의 `ADMIT`와 배포 후 `API_ISOLATION_VERIFY`도 PASS다. 이것을 최초
  migration을 다시 실행한 증거로 해석하지 않는다. 새 schema에 옛 exact-head API를
  다시 올리는 rollback은 하지 않는다.
- INDEX와 자료 학습 owner는 이번 배포 **이전부터 FAILED**였으며 같은 Invocation을
  보존했다. numerical runtime/INDEX 설정은 바꾸지 않았고 이번 배포로 복구했다고
  보고하지 않는다. 기존 정본·풀이·벡터·실패 이력도 수정하지 않았다.

## 운영 부분 배포 요청 — 2026-11-16

사용자가 전체 기능 완성 전에 운영 배포를 요청했다. 소스의 0084와 호환되는
release context 1.26을 추가하고 기존 배포 경계를 재사용한다. 수집/질문/packet/export
후속 owner 완료를 기다리는 것이 이번 부분 배포의 선행조건은 아니다.
단, 브라우저 MANUAL runtime·remote transport·자동 수집은 비활성 상태로 유지한다.
현재 가능한 연결 준비·학생/방 조회 화면과 실제 미완성 기능을 구별한다.
팀원의 미사용 약속을 권한·기능 차단의 대체물로 사용하지 않는다.
기존 운영 0079에서 0084로 전환하며, 적용 후 구형 exact-head API를 그대로 복구하지 않는다.
운영 완료 여부·설치 commit·실제 health는 배포 후 별도 기록한다.

## 최신 후속 — 2026-11-16 원본 수락과 질문 입력 연결

이번 변경은 `4d190c32` 이후의 **소스/임시 DB 검증 단계**다. 실제 카카오 로그인,
collector activation, 운영 DB migration 및 사용자 PDF 다운로드 성공을 뜻하지 않는다.

- 원본 CSV·정규화·사진과 실제 capture command/result/capability/attempt/fence를 연결하는
  source 수락 owner를 추가했다. occurrence는 같은 문장이라도 별개로 보존하며, 새 snapshot은
  이전 revision을 덮지 않는다. 검증되지 않은 발신 역할·provider ID·문맥 완전성의 과대 주장을 거부한다.
- 사진은 PNG/JPEG/WebP의 실제 decode·크기·정적 이미지 여부를 검사하고 원본 bytes·EXIF·SHA를
  보존한다. 같은 blob의 여러 첨부 occurrence는 유지하되 해당 요청에서 검증용 원본/receipt를
  한 번씩만 읽는다. 원본/긴 본문은 Artifact, DB에는 작은 identity·pointer·상태만 저장한다.
- `resolve_question_source`가 수락된 exact revision을 기존 질문 후보 규칙에 연결한다.
  현재 owner 권한·원본 lifecycle을 I/O 이후에도 확인한다. 질문/packet의 durable 편집·발행 owner와
  공개 API/GUI 연결은 아직 후속이며, 이 resolver 자체를 전체 기능 완료로 표시하지 않는다.
- 초기 설치에는 Catalog의 필요한 sandbox 경로/control group과 Caddy proxy group을 명시한다.
  최초 profile receipt의 설치 SHA는 후속 manifest로 바꾸지 않고 stage/verify 때 다시 대조한다.
  MANUAL driver는 실제 supervisor/profile lock 아래에서 매 실행 Xauthority를 준비한다.
  기존 VNC/Kakao 인증을 복사하거나 수정한 것이 아니다.
- 미확정 날짜 DRAFT는 실제 한 페이지 PDF에서 `날짜 확인 필요`를 표시하며 사진·본문을 유지한다.
  FINAL의 미확정 날짜 차단은 유지한다. 이 미출시 render 계약 변경으로 이전 준비본의
  pure contracts/PDF worker/관련 collector wheel은 활성화 전 새 source로 재빌드해야 한다.
- 최초 DB 합동 검사는 9 FAIL/69 PASS였다. 새 owner metadata 등록 누락 1개와
  batch pointer 조회로 변경된 테스트 주입 형식 8개를 수정했다. 다음 실행의 3 FAIL/90 PASS는
  병렬 개발 중 render schema/hash 교체와 겹친 검사였으며 해당 결과를 최종 PASS로 사용하지 않는다.
- 최종 0084는 새 disposable DB `/tmp/eom-api-testdb-20261116102051_6b2f2fd4`에서
  fresh upgrade → downgrade 0083 → upgrade 0084를 통과했다. 앞선 임시 DB 기록은 보존했다.
  운영 DB·기존 문항·임베딩 결과와 서비스 실행에는 변경이 없다.
- 동결 후 재검증: Kakao unit/API·설치 wheel·개발 문맥 **1100 PASS**, 공식 disposable
  PostgreSQL **98 PASS**(신규 source 20개 포함), schema audit 1456 canonical / 1104 mirror /
  12462 reference PASS. source 6개 모듈과 media 2개 모듈 mypy, 변경 경계 Ruff/format PASS.
  기존 Starlette/httpx deprecation warning 1개는 남아 있다. 겹치는 집중 검사를 합산하지 않는다.
- 이 체크포인트의 소스를 현재 release context 1.25/0083로 운영 배포하면 안 된다.
  source 0084와 후속 owner를 포함한 최종 compatible release/context 및 전용 runtime wheel을
  확정한 뒤 설치·migration·활성화를 진행한다. 기존 4d190c32 준비본의 fingerprint를 새 소스의
  검증 결과로 사용하지 않는다.

다음 구현은 기존 질문 생성/편집/publisher를 current/revision/CAS owner에 연결하고,
그 후 immutable packet과 학생별 export/download를 연결하는 순서다. source command는
source 전용이며 capture 필드를 nullable로 늘린 범용 질문/출력 큐로 확장하지 않는다.

## 최신 후속 — 2026-11-16 runtime coordinator·현재 접속 승인

기준 source checkpoint는 `7fe0c345d3b5c95c42c72ae67e371be0988bb92c`다.
다음은 소스/격리 검증 결과이며 아직 운영 설치·카카오 인증·실제 수집 결과가 아니다.

- Catalog 현재 MANUAL intent와 고정 browser/gateway를 연결했다. 별도 bounded thread가
  같은 실행의 준비·종료를 관측하며 원래 Catalog 업무 loop를 막지 않는다. 시작 응답 유실은
  원래 staged 실행을 확인하며 새 launch로 우회하지 않는다. 만료는 기존 gateway stop으로
  즉시 닫고 browser 종료를 확인한다. 실패 이력을 성공으로 바꾸지 않는다.
- private `AUTHORIZE_KAKAO_MANUAL`은 단순 history READ와 분리된다. 현재 owner/session/
  fence/TTL → 실제 OS 관측 → 같은 revision과 권한을 다시 검사한다. API/BFF는 성공 때만
  빈 204를 반환한다. noVNC asset과 WebSocket 모두 이 경계를 통과하며 읽기는 갱신하지 않는다.
- 독립 검토에서 병렬 asset·heartbeat의 읽기 lock 충돌을 재현했다. 실제 read observation만
  짧게 직렬화하고 매 요청의 새 관측·현재 권한 검사를 보존했다. 권한 캐시나 503 무시로
  덮지 않았다. coordinator/OS/remote 집중 검사 **304 PASS**, 관련 8개 모듈 mypy PASS.
- 공식 disposable DB 후속 검사 **78 PASS**: 5개 실제 admission/predecessor 검사를 추가했다.
  통합 수정 중 import 누락으로 처음 22 FAIL/56 PASS가 발생했고, `ProfileFence` import를
  복원한 뒤 같은 공식 경로로 78개를 재검증했다. 운영 DB는 사용하지 않았다.
- WebSession은 작은 lease pointer와 응답 generation만 보관한다. 늦은 read·logout·END가
  이전 화면을 되살리지 못한다. Caddy opt-in template의 실제 로컬 proxy 검사도 수행했다.
  HTTPS origin·정적 파일 allowlist 설정은 기본 생략이며 Secure cookie·허용 host를 요구한다.
  화면은 boolean 표시 설정만 읽는다. 실제 ACTIVE lease 없이 원격 iframe이 열리지 않는다.
- Web 설정/현재 admission·실제 Chromium/remote 규칙 **136 PASS** 후, 주입 경로의 동일
  HTTPS 설정 검사를 보강해 설정/admission **49 PASS**를 확인했다. 기존 Starlette/httpx
  deprecation warning은 남아 있으며 이 변경에서 무관한 의존성을 교체하지 않았다.
- API 배포 입력은 새 context 1.25에서만 pure Kakao contracts를 포함한 정확한 4개 wheel과
  migration 0083을 사용한다. historical context 1.0–1.24의 bytes/3-wheel 의미는 보존했다.
  관련 API 배포 검증 **120 PASS**, 실제 별도 설치 wheel/import 검증 PASS다. dirty source의
  임시 build는 테스트용이며 final release로 재사용하지 않는다.
- 합동 검사 첫 실행은 **646 PASS/1 FAIL**이었다. 실패는 개발 문맥 index의 경로 43개가
  자체 40개 상한을 넘은 것으로, 중복 탐색 경로를 줄인 뒤 문맥 검사 **13 PASS**다.
  운영 기능 오류가 아니며 상한을 완화해 통과시키지 않았다.
- 후속 최종 합동 검사 **693 PASS**(API/BFF·현재 접속 승인·Chromium/Caddy·설치 wheel·
  배포/의존성/개발 문맥 포함), 실제 disposable PostgreSQL 78 PASS와 별도다. root의
  Web/pure-contract 4개 모듈 mypy·Ruff/format도 PASS다.
- Web은 기존 API 환경에 기대지 않는 빈 Web interpreter venv에서 30개 exact wheel을
  오프라인 설치하고 `pip check`, 실제 app/contract import, 95개 RECORD 검사를 통과했다.
  기존 third-party 버전은 유지하며 jsonschema의 빠진 의존성만 완전한 잠금 목록에 포함했다.
  운영 installer는 root 보호 source snapshot의 helper/lock을 독립 SHA로 검증한다.
- 고정 초기 publisher는 3개 전용 Conda prefix와 Playwright/noVNC 두 경로만 준비·검증·
  새 root inode로 게시한다. 기존 install manifest를 참조하며 기존 prefix 업그레이드나
  서비스 활성화는 하지 않는다. 관련 installer/publisher **62 PASS**, 독립 검토에서 실제
  임시 3환경의 isolated dependency 검사와 5개 tree fingerprint도 PASS다. 실제 `/opt`
  게시·apt 설치·계정 생성은 아직 실행하지 않았다. 중간 실패는 검증되지 않은 설치 상태로
  보존하고 성공 receipt를 만들지 않으며, 이를 자동 배포 성공으로 취급하지 않는다.
- 아직 남은 경계: 전용 prefix의 root 보호 설치·실제 UID/systemd/VNC·Caddy 연결, 최종
  clean-commit 호환 release 및 운영 migration, 카카오 실제 로그인/selector/한 방 수집,
  원본 수락·질문/packet/export 영속 owner 연결과 실제 PDF 제공. 구현·시험 성공을 전체
  운영 완료로 표시하지 않는다. 기존 문항/임베딩/인증 자료에는 변경이 없다.

### 다음 영속 연결의 최소 순서

0080–0083은 binding/student/room/manual owner까지만 제공한다. 공개된 질문·packet
화면 fixture와 Artifact 발행 helper가 DB 수락까지 구현했다는 뜻은 아니다.

1. source 수락 owner가 actual attempt/fence 또는 명시 수동입력 provenance, 현재 owner/
   binding/room을 검사하고 snapshot/normalization/occurrence ID를 먼저 예약한다.
   기존 parser·capture publisher를 사용하고 사진 blob은 binding+SHA로만 dedup한다.
2. 정규화·alignment·원문·사진은 Artifact, DB에는 exact pointer와 occurrence 관계만 둔다.
   기존 `ResolvedKakaoQuestionSource`를 영속 resolver에서 구성해 source 권한을 재검사한다.
3. 기존 질문 생성/편집/분할/병합·publisher를 수락 owner에 연결한다. split/merge의 입력
   supersede와 결과 current pointer는 한 transaction이며 수동 편집을 재수집으로 덮지 않는다.
4. packet은 선택한 exact question/student/mapping/기간/mode를 고정한다. export는 이 pin과
   renderer/font/layout을 예약한 뒤 기존 PDF executor·publisher로 처리한다.
5. same intent는 예약 ID·기존 publication key/완료 attempt를 재조회한다. Job metadata에는
   ID/hash/count만 남기고 새 queue/framework나 원문 JSONB를 만들지 않는다. CAS 실패는
   원래 current를 보존한다. source ACL을 확인한 private download만 기존 media transport에 잇는다.

이 후속 단계의 schema/DDL은 아직 추가하지 않았다. 먼저 합성 CSV·사진 2개 → 질문 편집 →
학생별 packet/PDF·PNG → 재조회 추가 render 0을 disposable DB와 실제 local PDF로 닫는다.
날짜가 확인되지 않은 DRAFT는 날짜 추측 대신 명시적 미확인 표시가 필요하다. 현재 render
projection의 DATE_UNVERIFIED 거부가 이 설계와 다르므로 해당 경계를 구현할 때 정합시킨다.
실제 카카오 selector·완전성·사진 연결 capability는 로그인 전 UNKNOWN을 유지한다.

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

## 2026-11-16 06:41 UTC 전용 환경 준비

- source `4d190c32a01de55a4f19fc1c3697ec48762615d4`의 공식 API 4-wheel 빌드와
  Web offline wheel closure 빌드를 완료했다. 설치·운영 활성화는 아직 수행하지 않았다.
- browser/remote/pdf 전용 Conda 환경을 각각 최종 prefix에 직접 생성하고, 검증된
  오프라인 wheel만 설치했다. 세 환경의 `pip check`가 통과했다. 임시 venv를 운영
  경로로 복사하거나 기존 API/GPU 환경을 업그레이드하지 않았다.
- 원격 화면용 TigerVNC 1.13.1+dfsg-2build2와 해당 의존 4개 패키지만 설치했다.
  기존 패키지 업그레이드·삭제는 0이며 unrelated service restart는 하지 않았다.
- 최초 fingerprint는 Conda archive의 group-writable 파일 때문에 거부됐다. 이번에
  만든 eom 소유 준비본에 한해서 group/other write 및 set-id bit를 제거했고,
  5개 runtime/asset tree fingerprint가 통과했다. byte 변경이나 기존 서비스 변경은 없다.
- 아직 root-protected runtime 게시, 전용 service 활성화, DB migration, 카카오 로그인·
  수집은 미실행이다. 실제 실행 전에 발견한 Catalog sandbox write-path와 일회성
  Xauthority 준비 누락을 기존 installer/driver에서 보완한다.
- 자세한 준비 기록은 `staging/kakao-runtime-4d190c32/preparation-receipt.json`,
  wheel/RECORD/별도 PDF 출력 검사는 `/tmp/eom-kakao-release-4d190c32.93KcwwE4`다.
  이 경로들은 개발 증거이며 runtime authority 또는 활성화 선언이 아니다.

### 사진 blob 발행의 짧은 설계

1. 책임은 Catalog의 기존 Artifact 발행 adapter다. 사진 byte 검증·원본 보관만 맡고,
   방/메시지 연결·권한·DB 채택은 콘텐츠 owner에 남긴다.
2. 정본은 변경하지 않은 원본 이미지와 byte 고유 속성만 담은 작은 receipt다.
3. binding 범위 blob 논리 identity는 DB owner가 맡는다. Artifact/revision/hash와
   attachment occurrence/revision을 분리한다. 같은 사진의 새 관측은 별도 association이다.
4. SHA·크기·실제 MIME·decode 크기를 대조하고 고정 member명으로 exact pointer를 반환한다.
   호출 전/발행 직전/반환 전의 현재 source 권한 검사는 필수 callback이다.
5. 주요 연산은 binding+SHA 중복 확인, 처음 byte hash/decode, exact member 조회다.
6. 기존 Artifact publication 멱등 key와 후속 owner의 unique(binding,SHA)를 사용한다.
7. 사진 하나당 O(bytes+pixels), 명시적 byte/pixel 상한, 요청별 한 번의 검증이다.
   공개 조회마다 다시 decode하지 않는다. 원본 이름을 검색 key로 사용하지 않는다.
8. 대용량 검증·Artifact 발행 중 DB row lock은 잡지 않는다. 발행 후 owner가 재검증하고
   짧은 transaction으로 pointer를 채택한다. byte를 DB에 저장하지 않는다.
9. 순수 receipt 계약은 Catalog contracts, 이미지 decode/발행은 Catalog adapter다.
   실제 PyMuPDF 1.26.7의 `image_profile(bytes)`가 정상 PNG/JPEG에도 native binding
   TypeError를 내는 것을 재현했다. private C API 우회나 별도 이미지 파서를 만들지 않고
   PDF worker와 같은 Pillow 11.3.0을 선택적 `kakao-runtime` 의존으로 재사용한다.
   운영 활성화 전 이 의존 설치를 검증해야 하며, feature-off import는 요구하지 않는다.
   worker→NAS, domain→filesystem 의존을 추가하지 않는다.
10. 같은 binding+SHA의 재전송은 같은 발행을 재사용한다. 손상·형식·크기·권한·hash 오류는
    명시적으로 실패한다. 실패 이력을 성공으로 바꾸거나 byte를 보정하지 않는다.
11. 방·시간·파일명을 blob receipt에 넣는 더 단순한 대안은 같은 사진 재수집 때 request
    hash를 바꾸고 중복 보관을 유발하므로 제외한다. 별도 blob 저장소/framework는 불필요하다.
