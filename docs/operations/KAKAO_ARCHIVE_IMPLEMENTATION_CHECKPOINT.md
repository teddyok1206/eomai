# KakaoTalk 구현 체크포인트

## 2026-11-16 18:50 UTC MANUAL 다운로드 수신 source·실제 Chromium 합성 검증

- 다운로드 차단 원인을 기존 MANUAL driver에서 수정했다. JSON Schema 2020-12/frozen
  download receipt를 먼저 정의한 뒤, SDK event 수신→로컬 고정 member→완료 byte/hash→별도
  terminal receipt로 연결했다. 시작/실패 기록과 기존 profile/인증정보는 덮지 않는다.
- 실제 설치 Chromium으로 익명 data-URL CSV 2건을 내려받았다. 같은 filename이지만 다른
  capture를 유지하며, context 종료 뒤에도 결과 byte/hash와 파일이 보존되는 것을 검증했다.
  sandbox는 켜져 있고 실제 카카오 profile·대화·외부 네트워크 자료는 사용하지 않았다.
- empty/oversize/timeout/취소/위험 경로/중복 event/즉시 종료와 installer/runtime 검사
  **138 PASS**, source3개 strict mypy·Ruff 및 schema audit1467/mirror1113 PASS다.
  첫 합성 Chromium 검사는 headless-shell 미설치와 test process의 다른 umask 때문에
  실패했다. 기존 설치 Chromium과 운영과 같은0077 umask로 명시해 재검증했으며,
  실제 boundary의 파일 권한 검사·sandbox를 해제하지 않았다.
- root 설치 download directory는 browser UID/control group의2750이고, browser unit에
  그 path만 쓰기를 추가한다. 기존 private profile·NAS/DB 접근 금지는 그대로다. installer는
  layout 위치 변경이 lock owner에 영향을 주지 않도록 path map으로 identity를 조회한다.
- **현재는 source 검증 완료이며 운영 반영은 다음 단계**다. API/Catalog/Web·DB0087,
  INDEX/QUERY pin은 바꾸지 않는다. stopped-profile 경계에서 browser collector와 그 pure
  contract wheel만 같은 release로 설치하고 실제 설치본 합성 수신까지 확인할 예정이다.
  사용자의 실제 CSV 재시도/학생 PDF는 아직 PASS가 아니다. 로그인 요청은 설치 검증 뒤다.

## 2026-11-16 18:36 UTC 실제 내보내기 시도·공개 질문 조합 연결

- 사용자가 번역 팝업을 직접 닫았고, 방 우측 위 메뉴 열기→스크롤과 내보내기 버튼 실행을
  순서대로 추가 허용했다. 화면 확인 후 해당 메뉴만 열고 세로 wheel 3회, `내 PC 저장`
  hover를 실제 cursor 포함 screenshot으로 검증한 뒤, 사용자 승인 아래 내보내기를 1회 눌렀다.
  메시지/키 입력·상담 완료·채팅방 나가기는 0이다. 좌표는 일회성 실증에만 사용했고 실제
  collector selector나 다른 채널/방 identity로 하드코딩하지 않는다.
- **이번 실제 내보내기는 성공하지 않았다.** 정지한 browser의 History 다운로드 metadata를
  read-only로 확인했다. 시도 시각18:31:14 UTC, total5723byte, received0byte, state2,
  interrupt_reason40이다. URI·대화·이름·파일명·인증정보는 진단 출력에서 제외했다.
  설치 MANUAL driver가 `accept_downloads=False`인 것을 확인했다. 다음 우선 작업은
  명시적 다운로드 수락·bounded local staging·hash/receipt 보존 연결이며, 단순 버튼 성공을
  source 수집 성공으로 보고하지 않는다. 파일 수신 전 재접속/반복 클릭은 요청하지 않았다.
- browser/remote는 이후 MainPID0/Result success·종료 code0, profile STOPPED·lease NULL로
  관측됐다. 이전 STOP_UNCONFIRMED 이력은 ENDED 상태로 보존했다. 최대20분 정책은 source에
  있지만 실제 종료 원인이 시간 만료였다고 단정하지 않는다. 실패를 성공으로 바꾸지 않았다.
- 사용자 제안에 따라 다음 display release는 기본80% 축소와 창 크기/창 장식을 함께
  검증할 예정이다. **아직 적용하지 않았고** 기존 profile/비밀번호·배율을 수정하지 않았다.
- source는 atomic composition owner를 실제 Catalog API-peer socket→API→Web BFF에 연결했다.
  새 closed RPC/JSON Schema를 추가했으며 released question-v1 wire bytes는 유지한다.
  사용자/session 권한·CSRF·input별 revision/version CAS·동일 key replay·정확한 출력 연결을
  검사한다. 공개 API의 현재 operation과 OpenAPI snapshot/hash를 함께 갱신했다.
- 새 disposable PostgreSQL의 실제 BFF→HTTP→socket→owner 경로에서 분할→재전송→목록→
  병합→server 재생성→저장 결과 재조회가 통과했다. CSRF 거부·이전 parent412·같은 key의
  다른 body409도 확인했다. 전체 Kakao integration **168 PASS**, RPC/API/BFF·경계 source
  **70 PASS**, 추가 gateway/OpenAPI **29 PASS**, strict mypy6 source PASS다. 테스트 집합은
  중복되므로 합산하지 않는다. schema1466/mirror1112 audit도 통과했다.
- **이번 변경은 소스만이며 운영 미배포다.** DB0087·기존 compatible set·AUTO 비활성 상태는
  유지한다. 질문 조합 GUI·표시 교정 연결, 다운로드 수신, 실제 source/사진 occurrence·학생 PDF,
  전체 방/주기 수집은 여전히 남아 있다. 다음 행동은 로그인 반복이 아니라 다운로드 수신 구현이다.

## 2026-11-16 18:17 UTC 클릭 없는 스크롤 확인·질문 조합 저장

- 사용자는 실제 카카오 화면에 **마우스 이동·스크롤만 허용하고 클릭은 금지**했다.
  그 범위에서 먼저 스크롤만 검증했다. 이후 **채팅방 열기·닫기와 내보내기 버튼 hover**를
  추가 허용하여 방 하나를 여는 클릭 1회만 실행했다. 키 입력·메시지 전송·내보내기 실행은
  하지 않았다. 번역 팝업이 방 메뉴를 가려, 그 팝업 닫기/방 정보 메뉴 열기는 별도로 확인 중이다.
  아직 내보내기에 hover했다고 주장하지 않는다. 합성 입력 개발은 계속 가능하다.
- 기존 MANUAL은 ENDED/profile STOPPED·실제 프로세스 없음으로 확인했다. 원래
  STOP_UNCONFIRMED 이력은 그대로 두었고, 사용자가 새 연결을 시작한 뒤 ACTIVE를 확인했다.
  연결을 개발자가 임의로 되살리거나 TTL/인증정보를 바꾸지 않았다.
- 실제 화면에서 채팅방 목록의 세로 wheel 3회만 수행했다. 전후 화면에서 목록 내부만
  이동한 것을 확인했고 click/key/message는 0이다. 전체 방 inventory·CSV·사진 수집 검증은
  아니다. screenshot 원문·이름·대화는 Git/Slack에 저장하지 않는다.
- 원격 화면은 1440×960인데 현재 Chromium 창은 그보다 좁다. window manager 부재와
  창 크기를 함께 정리해야 하며, Chromium 100% 기준과 창 장식/크기 고정은 **미구현**이다.
  현재 배율·창 위치·크기와 사용자 프로필은 변경하지 않았다. 좌표를 실제 수집 selector로
  채택하거나 지금 보이는 상담 필터를 전체 방이라고 간주하지 않는다.
- source에는 JSON Schema/frozen 결과 DTO → 질문 조합 저장 owner → DB0088을 추가했다.
  동일 요청은 같은 출력 ID/Artifact를 재사용하고, 분할/병합의 모든 출력과 입력 대체를
  원자적으로 채택한다. 과거 질문 revision·packet·source origin 중복 방지 기록은 보존한다.
  소스 철회·세션 만료·학생 mapping 변경·다른 편집 경합은 수락 직전에 다시 확인한다.
- 새 disposable DB의 전체 migration·0088 되돌리기/재적용과 Kakao 저장/HTTP/PDF/metadata
  **167 PASS**, focused 계약/편집 **137 PASS**, strict mypy4개/Ruff PASS다.
  초기 테스트에서 fixture import 누락과 JSON Schema 예외 분류를 수정했다. 기존 오래된
  disposable DB의 source 완료 시각 CHECK가 현재 source와 달라 한 건 실패한 것은 metadata로
  확인한 뒤 새 DB에서 전체 migration으로 재검증했다. 운영 결함으로 추정해 상태를 고치지 않았다.
- 이번 저장 소스는 **운영 미배포**다. 공개 split/merge API·BFF·GUI와 compatible release는
  후속이며 현재 MANUAL/PDF 운영 설치와 AUTO 비활성 상태는 유지한다. 실제 한 방 수집부터
  학생 PDF까지의 완료와 전체 방 주기 수집도 아직 남아 있다.

## 2026-11-16 17:49 UTC 사용자 채팅방 열림 확인·분할/병합 선택 입력

- 사용자가 원격 화면에서 카카오 채팅방을 열었다고 확인했다. 실제 browser/remote unit도
  17:42:48/49 UTC 이후 ACTIVE이며 PID가 존재한다. 이는 **USER_VERIFIED 로그인·화면**
  증거다. 실제 채널/방 selector·CSV 범위·사진 occurrence 연결은 아직 확인하지 않았고,
  수집 또는 학생 PDF 완료로 확대하지 않는다. 메시지는 보내지 않았다.
- 사용자가 연 연결은 유지한다. 아래 source 작업으로 현재 Catalog/browser를 재시작하거나
  MANUAL 권한·profile/인증 파일·기존 실패 이력을 변경하지 않았다. 실제 화면의 메뉴 위치를
  확인하기 위한 사용자 screenshot을 요청했으며, 로그인 인증정보는 요청하지 않았다.
- JSON Schema 2020-12 `question-compose-v1`과 frozen selection DTO를 추가했다.
  Catalog의 `kakao_question_selections.py`가 exact revision/version과 작은 block/span
  선택을 기존 `split_question`/`merge_questions`에 연결한다. 원문·사진 pointer·authority·
  결과 ID는 browser 입력이 아니다. 같은 서버 예약으로 동일한 manifest를 재구성한다.
- source 검증 **141 PASS**: canonical/mirror/hash, wire 입력 거부, source hash·부모
  version 불일치, 글/사진 coverage, Unicode 경계, display override 보존, 학생 격리,
  미확보 사진의 FINAL 차단, 원문 반복 occurrence 보존 및 기존 API import/route 회귀다.
  초기 테스트의 미확보 사진 기대값은 review reason이 아니라 기존 FINAL blocker를
  확인하도록 고쳤다. 운영 실패/원본을 수정하지 않았다.
- Ruff·formatter·strict mypy 두 source PASS, wire audit1464개 canonical/1110개 mirror
  참조 검사 PASS. **다중 질문 원자적 저장·SUPERSEDED 전환·공개 split/merge API/GUI는
  후속이며 아직 활성 기능이 아니다.** 운영 release는 위 로그인 수정 compatible set 그대로다.

## 2026-11-16 17:36 UTC X11 수정 운영 반영·installed empty canary 완료

- collector `41bbbaa9d4f31971ab1a3ecb4e489494c167f874` wheel
  `sha256:58bc7286d3723d93f570aba346cce10020abe9ddc5cf15b07c3e42e67578fe23`을
  stopped profile 경계에서 설치했다. wheel member bytes/RECORD와 전체 prefix fingerprint,
  기존 installer stage/verify를 통과하고 Catalog를 재기동했다. 설치 receipt는
  `/var/lib/eom-kakao-x11-release-41bbbaa9/installed.json`이다.
- 실제 설치본의 `run_manual`·X11 directory 준비·Xvnc argv·readiness·Chromium launch/close를
  그대로 사용한 네 번째 empty canary가 두 번 모두 PASS다. 배포 이후 launch/readiness를
  test stub으로 바꾸지 않았다. 새 합성 profile 경로와 전용 canary cgroup/동일 flock 검사만
  재배정했다. 실제 profile은 mask하고 PrivateNetwork를 켜므로 실제 카카오 인증정보와
  대화를 읽지 않는다. 이 검증은 production lease/현재 사용자 권한 실증의 대체물이 아니다.
- canary의 두 반복에서 actual headed Chromium의 정상 시작·정상 close, Xvnc의 정상
  종료, 죽은 VNC endpoint 정리와 X11 endpoint 부재를 확인했다. 새 설치 unit에도
  browser/remote `ExecStopPost`가 반영돼 있다. 과거 unit FAILED/lease 이력은 보존한다.
- 현재 component map은 API/Catalog8e2e11eb, Web636e39fa, browser41bbbaa9,
  gateway/unit01e04fff, DB0087이다. 전체 component가 같은 SHA라고 보고하지 않는다.
  Catalog active와 실제 HTTPS `/studio/login`200을 확인했고 기존 INDEX/QUERY 설치 pin을
  변경하지 않았다. MANUAL/PDF ENABLED·AUTO collection DISABLED 상태는 유지한다.
- source focused219개 및 관련 후속110개 PASS, strict mypy2개/Ruff PASS다. 중복된
  테스트 집합을 더해 독립 검증 수라고 보고하지 않는다.
- 사용자에게 기존 배정 연결에서 새 MANUAL 시작·로그인만 요청했다. **실제 카카오 로그인,
  한 방 CSV/사진 수집, 실제 학생 PDF, 전체 주기 수집은 아직 NOT_VERIFIED**다.
  메시지 전송은0이며 비밀번호·프로필·계정·실패 기록을 변경하지 않았다.

## 2026-11-16 실제 empty headed runtime에서 확인한 X11 시작 실패

- endpoint cleanup `01e04fff`를 두 전용 role에 반영하고 stage/verify·Catalog 재기동을
  완료했다. receipt는 `/var/lib/eom-kakao-endpoint-release-01e04fff/installed.json`이다.
  API/Web/pure contracts·기존 GPU 환경은 변경하지 않았고 profile/인증/실패 이력은 보존했다.
- 사용자에게 재시도를 요청하기 전에 실제 설치 Playwright/Xvnc를 같은 UID·PrivateTmp·
  PrivateDevices·NoNewPrivileges로 빈 프로필에서 실행했다. 실제 profile은 mask하고
  PrivateNetwork를 켰다. 초기2개 canary는 실패했으며 원래 기술 기록을 보존한다.
- RFB가 listen한 직후 Xvnc가 host NVIDIA EGL/GLX 초기화에서 SIGSEGV로 종료되는 것을
  synthetic-only stderr에서 확인했다. 사설 `/tmp/.X11-unix` 부재도 함께 확인했다.
  이는 계정 비밀번호나 카카오 권한 문제의 증거가 아니다.
- 사설 X11 directory 준비와 Xvnc의 GLX 비활성화만 적용한 세 번째 격리 canary에서는
  **authenticated X11 접속·headed Chromium 시작·정상 종료·소켓 정리 2회 PASS**다.
  Chromium sandbox는 켜진 상태이며 `--no-sandbox`·GPU driver 수정·외부 접속은 없다.
- source는 이 설정을 driver owner에 두고 RFB 뒤의 실제 X11 접속을 확인하도록 한다.
  기존 host `x11-utils 7.7+6build2`의 `xdpyinfo`를 재사용하는 이유는 socket 존재와 정상
  인증된 display 준비를 구별하기 위해서다. 새 Python 의존이나 상시 daemon은 없다.
  짧은 probe의 stdout/stderr는 버리고 취소 시 kill/reap한다.
- 위 canary는 아직 새 source wheel의 설치 완료나 실제 카카오 로그인 PASS가 아니다.
  후속 installed wheel의 launch/readiness를 override하지 않은 같은 canary를 확인한 뒤
  사용자에게 재시도를 요청한다.

## 2026-11-16 MANUAL 반복 시작·종료 경계 — 소스 후속

실제 첫 Chromium 시작의 root-owned HOME에서는 Crashpad `--database is required`와
SIGTRAP이 발생했다. 같은 UID·NoNewPrivileges·PrivateNetwork의 빈 프로필에서 HOME만
private writable profile로 바꾸었을 때 empty HTML 출력이 성공했다. `641d9fde`로 이를
운영 browser role에 반영했으며 sandbox/user namespace를 해제하지 않았다. 이 offline
headless 증거는 카카오 로그인이나 headed 브라우저 전체 경로의 PASS가 아니다.

후속 실제 요청에서는 종료된 gateway의 `KAKAO_GATEWAY_SOCKET_EXISTS`를 확인했다.
profile은 STOPPED·current lease NULL·flock 해제였고, 실패 lease는 ENDED로 보존됐다.
directory 보존과 socket 수명 처리를 분리하는 수정은 다음과 같다.

- 책임/정본: 각 browser/gateway runtime이 자신의 고정 Unix endpoint를 systemd
  `ExecStopPost`에서 정리한다. DB·lease·profile·인증정보·request 감사본은 수정하지 않는다.
- identity/해석: 고정 unit cgroup 또는 정확한 `.control` subgroup, 실행 UID/group,
  socket type·단일 link·mode·inode를 확인한다. 연결이 실제 거절된 socket만 제거하고
  unlink 직전 같은 device/inode/owner/group/link/mode를 대조한다. live endpoint는 거부한다.
- 접근/복잡도: 고정 path 한 개의 O(1) stat/connect/unlink다. 별도 DB/index/cache/queue,
  schema·wire contract·dependency는 추가하지 않는다. browser는 기존 profile flock도 쓴다.
- 동시성/실패: 실제 unit 자식 종료 이후 hook이 수행된다. lock 경합·접속 성공·종류/소유권
  불일치는 명시적 실패이며 타 endpoint를 지우거나 새 lease를 만들어 우회하지 않는다.
  종료 기록을 지우지 않고 기존 owner coordinator가 원래 실패를 관측한다.
- 단순 대안: directory를 무조건 지우면 request 감사본이 사라지고, 시작 때 임의 unlink하면
  아직 살아 있는 runtime을 훼손할 수 있다. 기존 service lifecycle 안의 좁은 hook을 선택했다.

소스 검증은 actual local Unix socket·flock과 synthetic fixed-scope identity를 사용한다.
이는 실제 카카오 계정/CSV/사진 수집 PASS가 아니다. 운영 role 교체 후에는 network와 실제
profile을 격리한 empty headed browser의 반복 시작·종료를 먼저 확인하고 사용자 재시도를 요청한다.

## 2026-11-16 동명 연결 선택·확정 거절 UI 후속

사용자 문의 `webreq_a87c42c7e6651f6705653995`의 PROFILE_UNAVAILABLE를 확인했다.
read-only 기술 metadata에서 같은 owner·같은 표시 이름의 DRAFT binding 두 개와,
primary profile이 그중 하나에만 배정된 것을 확인했다. 원래 profile은 STOPPED,
current lease는 NULL, flock은 해제됐고 이전 실패 lease 두 개는 ENDED 이력을 보존한다.
사용자가 알려준 로그인 ID/채널 이름은 배정된 표시 이름과 같았지만 이름 자체는 ID가 아니다.

- `636e39fa`에서 동명 표시만 `연결 1/2`로 구분했다. 실제 API 요청은 기존 binding ID를
  그대로 사용하며 name/ID를 hardcode하거나 원본/배정을 합치지 않는다. map 집계 O(n)이다.
- START의 명시적 PROFILE_UNAVAILABLE 거절에서만 UI 선택을 다시 열었다. 응답 유실,
  timeout·불확실한 처리 여부는 기존 key/body를 유지한다. 서버의 ownership/fence와
  프로필 배정, 실패 이력은 변경하지 않았다. 다른 채널로의 명시적 전환은 별도 후속이다.
- UI/API presentation·실제 Chromium 검증33개 PASS와 공식 Web offline closure/실제
  설치100 member 검사를 통과했다. Web636e39fa를 설치·재기동했고 HTTPS login200이다.
  API/Catalog8e, gateway codec352, remote unit692b는 이번 Web 배포에서 변경하지 않았다.
- 사용자에게 현재 서버 profile이 배정된 구분 항목으로 다시 시도하도록 요청했다.
  **실제 카카오 로그인·수집·학생 PDF는 아직 검증 대기**다. 특정 채널로 고정한 해결이 아니다.


## 실제 첫 MANUAL 시작에서 확인한 후속 수정 — 진행 중

사용자가 `카카오 로그인 준비`를 눌렀으나 원격 화면의 최초 시작이 ERROR로 끝났다.
아직 카카오 인증에 도달하지 않았으며 기존 실패/lease/fence 기록을 보존한다.

- noVNC1.6.0의 정상 빈 `.gitmodules`가 기존 nonempty grant reader의 공통 조건에
  걸렸다. source tree를 임의 삭제하지 않고 static asset 검사에만 최소0byte를 명시했다.
  grant/revocation·실행 interpreter·필수 HTML/JS는 여전히 nonempty다. wire schema,
  profile/lease/권한, 고정 asset path·hash·size bound는 바꾸지 않는다.
- 설계서의 별도 VncAuth 비밀번호는 installer가 의도적으로 만들지 않는다. 운영 활성화
  전에 이 provisioning 확인이 빠져 있었다. 기존 TigerVNC 도구의 stdin으로만 암호를
  전달하는 일회성 `scripts/kakao/provision_vnc_password.py`를 추가했다. 현재 profile
  lock·실제 중지 확인 아래 고정 경로600의 새 파일만 생성하며 기존 비밀번호는 덮지 않는다.
  계정 로그인/변경이나 브라우저 시작은 하지 않는다. argv/URL/로그/Artifact/Git에 값이 없다.
- 사용자에게 전용 비밀번호 입력을 요청했다. 이는 Linux·Studio·카카오 비밀번호가 아니며
  실제 noVNC 화면에서도 수동 입력한다. 코드가 암호를 조회해 대신 로그인하지 않는다.
- gateway/OS adapter/coordinator/암호 helper **112 PASS**, source3개 mypy와 Ruff PASS다.
  source 수정 후 새 gateway wheel과 별도 설치 successor 검증을 진행한다. 이 단락은
  아직 실제 카카오 로그인 또는 source 수정 운영 완료의 선언이 아니다.

후속 운영 반영:

- `c352037e`의 gateway wheel `sha256:c2ddb3d6789bc65b90c354433f1bfd6b017a32dedbbf6724f0085a758af74e36`을
  실제 미실행/중지 상태에서 설치하고 Supervisor source pin을 갱신했다. API/Web/pure
  contracts는 바꾸지 않았다. VNC 비밀번호는 worker 소유600·8byte·단일 link의 metadata만
  확인했으며 값을 조회하지 않았다.
- 첫 후속 설치 verify는 실패한 systemd gateway 종료 시 `/run/eom-kakao-remote`가
  삭제된 것을 확인했다. 실제 runtime lifecycle 문제이며, root가 DB 상태를 수정해
  성공으로 표시하지 않았다. `692b3bfd`에서 gateway도 browser와 같이
  `RuntimeDirectoryPreserve=yes`로 정렬했다. 빈 실행 폴더만 유지하며 socket/process
  종료·fence 검사는 그대로다. gateway/installer87개 검사 PASS다.
- 현재 worker source는 c352, remote unit source는692b다. 새 successor manifest와
  source pin을 명시적으로 적용해 stage/verify 후 Catalog를 재기동했다. 운영 evidence는
  `/var/lib/eom-kakao-gateway-release-c352037e/installed.json`, 현재 설치 검증 입력은 같은
  폴더의 `install-manifest-runtime-dir.json`과 `payload`다. 최초 publication/manifest는
  역사적 predecessor로 보존하며, 최초 hash를 현재 successor의 검증값으로 사용하지 않는다.
- Catalog/API/Web/Caddy 및 HTTPS login은 정상이다. 실패한 MANUAL intent는 여전히
  원래 기록이며 사용자가 `로그인 연결 종료 → 카카오 로그인 준비`로 새 연결을 여는
  supported 경로를 안내했다. 실제 카카오 로그인/한 방/CSV·사진/PDF는 아직 NOT_VERIFIED다.


## 2026-11-16 보호 runtime 설치·MANUAL/PDF 활성화

- API/Web/Catalog/QUERY 운영 source는 `8e2e11eb`, DB0087이다. build gate는
  `0b1b3c2c`, 설치 owner-group 수정은 `157d7c7e`로 각각 커밋·푸시했다. 각 component의
  source를 같은 SHA라고 단정하지 않는다. 전용 runtime package 코드는 eb9→8e 사이
  변경 없음을 Git diff로 확인하고 eb9에서 만든 새 4-wheel을 실제 전용 prefix에 설치했다.
- browser/remote/pdf의 `pip check`, 5개 runtime/asset tree fingerprint, root inode
  publication과 별도 installer stage/verify, 실제 전용 UID·group·systemd template
  검증을 완료했다. 원래 builder tree는 `/opt/eom/.kakao-runtime-publish-3jjj0s70`에
  복구/감사를 위해 보존했다. source 원본·인증정보를 worker에게 복사하지 않았다.
- 최초 stage는 Catalog owner를 render group에 추가한 뒤 동일 owner를 금지하던 installer
  allowlist 불일치에서 중단됐다. worker 권한을 넓히지 않고 owner의 좁은 I/O group만
  허용하도록 수정했다. renderer/타 worker/임의 계정 분리 포함 installer **47 PASS** 후
  동일 manifest의 stage/verify를 완료했다. 실패 기록은 보존했다.
- 설치 manifest SHA는 `sha256:fad5939db96ddab355607e13a4ea0170d94b346d7340ae69d1df1654bcdb32c7`,
  publication plan SHA는 `sha256:8d40ce61453790e29b3c3ad108c34d4381da5aaef470ca86483324620e61237e`다.
  installer source157d의 별도 SHA는 `sha256:5aaf7dfea16f8a58ebbd1cfd109e0ef7ee638a3cc38e7358739c70259c44d504`다.
- 실제 설치 noVNC inventory에서 Web의 exact static path allowlist를 구성하고, 기존
  Caddy route에 현재 owner/session/lease 검사를 통과하는 private UDS 경로만 연결했다.
  Catalog MANUAL/PDF만 ENABLED이며 **AUTO collection은 여전히 비활성**이다.
  Catalog/Web/Caddy 재기동 후 공개 HTTPS login200, API READY, 무인증 remote401을 확인했다.
- 운영 기록은 `/var/lib/eom-kakao-runtime-activation-157d7c7e/activated.json`이다.
  기존 Caddy/Web 설정은 같은 private directory에 복구용으로 보존했다. 개인 인증정보나
  실제 대화·사진을 개발 Git/Slack에 넣지 않았다.
- 사용자에게 `일반 → KakaoTalk → 카카오 로그인 준비`의 실제 로그인 요청을 보냈다.
  **실제 카카오 로그인/한 방/CSV/사진/학생 PDF는 아직 NOT_VERIFIED**다. 실제 로그인과
  2단계 인증을 관측하지 않은 상태를 전체 업무 성공으로 보고하지 않는다. 메시지 전송은 금지다.


## 2026-11-16 후속 운영 release — 학생별 PDF 연결 소스 반영

1. 실제 사용 경로: `eb9e7e1f`에 질문 선택/packet/PDF API·BFF·Studio 연결을 커밋·푸시했다.
   설치 기동 import 결함을 `8e2e11eb95d618cfcd7ee8f7ae810297d96b674e`에서 수정·푸시했으며,
   **현재 API·Web·Catalog/QUERY 호환 release는 8e2e11eb, 운영 DB는0087**이다.
   Web은 공식 offline closure 설치 후 명시적으로 재기동했다. 공개 HTTPS login200과
   API READY를 확인했다. 이것은 아직 실제 학생 자료 PDF 생성의 증거가 아니다.
2. 합성 검증: 아래152개 PostgreSQL 검증을 보존한다. 전체 Kakao source/API/BFF·브라우저·
   의존성/개발 문맥·배포 검사는 재실행 **1426 PASS / 132.25초**였다. 이후 실제 기동에서
   드러난 optional renderer annotation import를 수정했고 disabled composition 직접 생성
   등21개, 배포/기동 경계69개 및 mypy를 통과했다. 겹치는 검사를 합산하지 않는다.
3. 실제 카카오 계정 검증: **NOT_PERFORMED**. 사용자 계정에 접속하거나 대화를 전송하지 않았다.
4. 운영 활성 범위: API/GUI와 저장 schema만 반영했다. AUTO 수집·MANUAL 원격 화면·PDF
   보호 실행은 아직 비활성이다. 전용 browser/remote/pdf의 새 wheel과 dependency 검사를
   마쳤고 별도 보호 runtime publication/설치를 진행한다. 기출·창작·벡터 정본을 변경하지 않았다.
5. 다음: 보호 runtime·현재 권한 Caddy 경로 → 사용자의 실제 카카오 로그인 → 관리자 권한으로
   한 방의 조회/CSV/사진 occurrence → 저장 질문/학생 PDF의 실제 재조회·다운로드를 검증한다.
   atomic 분할/병합 저장 및 전체 방 주기 수집도 남아 있다. 부분 배포로 goal을 완료하지 않는다.
6. 실패/복구: 최초 eb9 배포는 Catalog의 TYPE_CHECKING 전용 class를 postponed annotation
   없이 참조해 중단됐다. 실패 로그/시작 marker는 보존했다. source0087을 되돌리지 않고
   successor 설치본의 실제 Catalog runner import를 확인한 뒤8e 호환 set으로 복구했다.
   successor 첫 실행의 admission receipt 누락도 원래 기록과 config-before SHA/head를
   확인하고 같은 배포의 명시적 복구로 처리했다. 이미 적용한 migration을 재실행하지 않았다.
   공식 API wheel/실제 설치 검사에도 Catalog runner import를 추가해 재발을 차단한다.

운영 evidence 위치는 `/var/lib/eom-kakao-delivery-release-8e2e11eb/api`와
`/var/lib/eom-api/deployments/8e2e11eb95d618cfcd7ee8f7ae810297d96b674e.json`이다.
이전 eb9 실패 및 원래 source/설정 백업도 별도 control directory에 보존했다.
INDEX/자료학습은 배포 전 FAILED였던 상태/설치 pin을 그대로 보존했으며 이번 작업에서
복구·재개했다고 주장하지 않는다. creative producer는 지원된 drain 후 새 호환 source로 재개했다.


## 진행 중간 저장 — 학생별 PDF의 실제 API·저장·Studio 다운로드 연결

기준 commit은 `4ba17415`다. 새 delivery wire schema를 먼저 정의하고 기존
packet/export owner, PDF executor/publisher와 Studio BFF를 연결했다. 새 migration이나
AI 호출, 별도 저장소·큐 framework는 추가하지 않았다. **아래는 합성 검증이며 실제 카카오
수집 또는 운영 활성화의 증거가 아니다.**

- 수락된 CSV/사진 → 질문 확인 저장 → exact 질문·기간 packet 저장 → 학생 PDF 요청 →
  별도 PDF subprocess → 기존 Artifact owner → 권한 검사된 HTTP/BFF 다운로드까지 연결했다.
  같은 사진 byte가 여러 메시지에 쓰인 경우 occurrence 수와 학생별 구성을 유지한다.
- Studio는 저장한 자료와 PDF 기록을 다시 읽는다. POST 응답 유실은 동일 body/key로
  확인하고, GET 상태 조회·완료 기록 재열기는 새 계산을 시작하지 않는다. 원래 publication
  이후 DB 채택 중단은 동일 attempt/command의 저장만 복구하며 재렌더하지 않는다.
- process-local bounded deque/set은 DB 작업을 깨우는 hint다. 영속 정본은 기존 export
  record이고, 재시작 뒤 명시적 원 요청 replay가 PENDING/RUNNING 복구를 깨운다.
- Catalog의 private staging parent는 기존 primary GID를 유지하고 per-attempt에만 좁은
  render group을 적용했다. 실제 cgroup 종료 확인과 종료된 원 unit의 명시적 close를
  구분한다. worker에는 DB/NAS 권한을 주지 않는다. 이 소스 검증은 운영 sandbox PASS가 아니다.
- guarded disposable PostgreSQL 최종 실행 **152 PASS / 76.81초**. 실제 API/UDS/PG와
  Studio BFF 경로, 분리 PDF process, 다운로드 동일 SHA, session 철회 후 거부,
  publication 중단/replay 무재렌더를 포함한다. 인증은 합성 fixture다.
- 새 source·브라우저 focused **26 PASS**는 FINAL 거절 뒤 수정 가능, 응답 유실 시 동일
  요청 유지, 새로고침 후 PDF 기록 재열기까지 검사한다. focused mypy 11개 PASS다.
  전체 source 회귀 첫 실행은 **1425 PASS / 1 FAIL**였으며 실패는 배포 검사의 옛0084
  기대값이었다. 현재 source0087과 기존 공식 installer callback을 대조해 정렬했다.
  수정 후 release/context/delivery 집중 검사는 **45 PASS**, schema audit는
  canonical1463 / mirror1109 / reference12550 PASS다. 개발 index의 경로 상한을 넘긴
  첫 문맥 수정은 경로를 중복 나열하지 않도록 정리했으며 runtime 계약은 바꾸지 않았다.
- 질문 분할/병합의 영속 API 연결, 실제 수집 source admission, 실제 한 방과 전체 방 주기
  수집은 남아 있다. 이 체크포인트로 전체 goal을 완료 처리하지 않는다.
- 사용자 운영 지시: 실제 카카오는 **조회·CSV/사진 다운로드만** 수행한다. 메시지 전송,
  답장, 담당자·상태 변경, 차단/삭제/나가기는 금지다. 로그인/2단계 인증은 사용자가 한다.
  방 열기의 불가피한 읽음 효과는 관측 후 알리며 되돌리기 mutation을 하지 않는다.


## 진행 중간 저장 — 실제 질문 API·Studio 열람/확인 저장 연결

`b84952fa` 이후 기존 source/question owner를 API-only Catalog socket과 실제 API/BFF에
연결했다. 새 queue·DB migration·파일 서버·AI 호출은 없다. 이번 단계는 **합성 자료의
저장→Studio HTTP 열람/검토 저장** 완료이며 실제 카카오 수집·PDF 다운로드의 완료가 아니다.

- 질문 목록은 작은 metadata만 읽고, 상세는 exact question revision에서 원문 span과 사진
  occurrence를 해석한다. 두 개의 동일 메시지와 같은 PNG의 두 첨부 identity를 보존한다.
  deep link에 room hint가 없어도 실제 room을 다시 인가하며 잘못된 room은 거부한다.
- 사진 URL은 질문/revision/attachment ID만 받고 임의 Artifact/member/path를 받지 않는다.
  현재 owner/session/source를 FD 열기 전후 다시 확인하고, 기존 bounded length/SHA proxy를
  거친 same-origin 원본 bytes만 화면에 내보낸다. 다른 학생/owner의 사진은 보이지 않는다.
- 일반 확인/제외는 기존 parent·If-Match·멱등 key를 사용한다. 브라우저는 응답 유실 시
  동일 body/key로 다시 확인하며 다른 내용으로 바꾸지 않는다. 저장한 revision과 상태는
  새로고침·새 service instance 뒤에도 유지된다. 원문·사진은 바꾸지 않는다.
  공개 리뷰로 클라이언트가 만든 actor/시각/사진 품질 수용 stamp를 받지 않는다.
- 기존 채널의 현재 수집 불가와 수락된 질문의 읽기 불가를 구분했다. DRAFT history 열람은
  현재 backend 권한을 확인하지만 collection/export capability를 활성화하지 않는다.
- 공식 guarded disposable PostgreSQL **149 PASS (64.81초)**. 그중 새 합성 검사는 실제
  Studio BFF→HTTP gateway→API→API-peer UDS→Catalog owner→PG/Artifact를 통과해
  생성/replay·원문/사진·확인 저장/replay·목록 재조회를 수행한다. HTTP 인증은 합성 fixture이고
  Catalog는 실제 임시 Identity session/권한을 재검사한다. HTTPS/live 인증 증거는 아니다.
- Kakao source/API/BFF·브라우저·권한/의존성/문맥/배포/표시 검사 **1347 PASS**.
  이어 추가한 다섯 API-peer 거부 분기를 포함한 질문 HTTP 집중 검사 **13 PASS**다.
  겹치는 수를 합산하지 않는다. 변경 core 9개 focused mypy, Ruff/format, shell와 schema
  audit(1462 canonical / 1108 mirror / 12537 reference) PASS다.
- 최초 브라우저 실행은 ambient Node18과 headless shell이 없는 새 runtime을 잘못 선택해
  실행 전 실패했다. 기존 설치된 Playwright/Chromium test 환경으로 재실행했다. 첫 신규
  BFF fixture의 중복 Host와 publisher filename 추정도 수정해 실제 계약과 대조했다.
  통합 검사의 Web source 경로 누락은 해당 guarded purpose 안에서만 보완했다.
  기존 Starlette/httpx deprecation warning은 유지하며 운영 의존성은 바꾸지 않았다.
- 운영 DB는 여전히 **0084**, source head는 **0087**이다. 이번 API/Web/Catalog 소스는
  아직 배포하지 않았다. 앞선 83203f88 wheel 준비본에는 이번 연결이 없으므로 새 후보로
  다시 빌드해야 한다. 실제 카카오 계정 검증은 **NOT_PERFORMED**, AUTO/MANUAL 비활성이다.
- 다음은 packet/export의 API·실행 coordinator·Studio PDF 다운로드를 이어 붙여 합성 입력의
  첫 사용자 경로를 닫는 것이다. source 후보 수락 연결과 atomic 분할/병합도 남아 있다.
  그 뒤 호환 release/보호 runtime 배포와 실제 한 방→전체 주기 수집 검증을 진행한다.

후속 설치 패키지 검사에서 c081dd76의 committed OpenAPI가 신규 질문 routes보다 이전인 것을
확인했다. 공식 source exporter로 명세/hash를 갱신한다. 또한 공식 installer의 migration
verify callback이 source head0087이 아닌0084를 가리키던 것을0087로 정렬하고, 기존0083까지
고정돼 있던 배포 회귀 검사의 기대값/closed callback 집합을 실제 지원된0084/0087과 대조한다.
이 수정은 추가 migration 실행이나 운영 변경이 아니며 새 wheel 검증 뒤 후속 release에 포함한다.

위 정렬은 `36174ceb7f2e9e70f41165effe222e9d9788e589`로 커밋·푸시했고 OpenAPI/배포
회귀 **56 PASS**를 확인했다. 같은 commit의 공식 API four-wheel build/RECORD/격리 import·
OpenAPI 검사는 PASS다. UI는 `c081dd76e0f1a56b91d48209689f3cc9c5f2a5ae`의 공식 Web wheel
closure/빈 환경 offline 설치/97 runtime member 검증이 PASS다. API build 위치는
`/tmp/eom-api-build/36174ceb7f2e9e70f41165effe222e9d9788e589.CzFLjX/dist`, Web은
`/tmp/eom-web-gui-build/c081dd76e0f1a56b91d48209689f3cc9c5f2a5ae.W5MlXf/dist`다.
이 패키지 검증은 아직 운영 migration·서비스 교체·실제 질문 PDF 제공의 증거가 아니다.

## 진행 중간 저장 — 영속 출력 요청·claim·현재 권한 파일 열기

`99f97a65` 뒤에 기존 PDF executor/publisher를 바꾸지 않고 export 저장 owner를 연결했다.
이번 완료 범위는 **저장 use case와 실제 PDF 파일 adapter의 합성 입력 검증**이다.
API/BFF/GUI 출력 경로와 보호 worker 활성화, 실제 카카오 수집은 여전히 미연결이다.

- 한 학생의 exact packet revision/subset와 renderer/font/layout pin으로 build를 고정한다.
  같은 요청은 원래 ID를 재사용하고 같은 build의 다른 key도 작은 receipt만 추가한다.
  배포 뒤 renderer profile이 달라져도 이전 key는 이전 요청·출력과 연결된다.
- 실제 동시 접수와 claim에서 한 export·한 실행 승자만 생성된다. 조회/접수 replay는
  렌더를 시작하지 않는다. 긴 파일 I/O 중에는 DB row lock을 잡지 않는다.
- 실제 PDF 발행 뒤 새 service instance가 DB 채택만 이어서 수행했다. 완료 목록·상세와
  같은 PDF 파일을 두 번 다시 열어도 render 호출은 1회였다. 현재 session/source 검사를
  파일 FD를 열기 전후에 수행하며, 열기 중 권한 철회 시 FD도 닫는 것을 확인했다.
- 실제 프로세스 정지 callback이 거부하면 RUNNING을 보존한다. 명시적인 exact 실패
  attempt retry만 새 attempt/fence를 만들며 기존 FAILED 기록을 수정하지 않는다.
  다른 학생/바뀐 command/다른 hash의 출력은 채택하지 않는다.
- 최초 query-plan 추가 검사만 143 PASS/1 FAIL이었다. 작은 fixture에서 optimizer가
  동등하게 유효한 owner index를 고른 것을 잘못 실패로 판정한 경우였다. 실제 indexed
  lookup과 정확한 unique build B-tree 정의를 함께 검사하도록 고쳤다. 목록용 index는
  기존 unique(owner,binding,export)가 같은 연산을 지원하므로 중복 생성하지 않는다.
- 변경된 미출시 migration을 **새로운** 공식 guarded disposable DB에 처음부터 적용했다.
  최종 PostgreSQL **144 PASS (55.37초)**, 합동 소스/권한/배포 경계 **1186 PASS**, mypy
  4개 core와 formatter/linter/shell 검사 PASS다. schema audit는 canonical 1461 /
  mirror 1107 / reference 12525 PASS다. 기존 테스트 결과와 수를 합산하지 않는다.
- source head는 `20261116_0087`이다. 운영 반영용 context/admission 1.27과 exact
  0084→0087/0087 read-only callback을 기존 operator에 추가했다. 1.26 bytes/의미는
  보존했다. **아직 운영 적용하지 않았고** 실제 운영은 앞선 0084 release 그대로다.
  새 source를 옛 exact-head context로 설치하지 않는다.
- 다음은 이 owner를 실제 API·Studio와 실행 coordinator에 연결하고 같은 합성 입력의
  인증 다운로드를 완주하는 것이다. 그 뒤 호환 운영 release/보호 renderer를 적용하고,
  원격 화면에서 사용자 카카오 관리자 로그인 → 실제 한 방 수집/PDF → 전체 주기 수집으로 간다.

소스 변경은 `83203f881f8e6f4cbf27a6bfb109cb717db62dc2`로 커밋·푸시했다. 이 정확한
commit의 공식 API four-wheel build/RECORD 검증을 통과했고 protected operator source/wheel
staging도 준비했다. 이 준비는 ADMIT/DDL 적용/서비스 교체가 아니다. 현재 운영 DB 0084와
API/Web은 변경하지 않았다. 후속 API·Studio 연결 전 준비본을 전체 기능 운영 완료로 보고하지 않는다.

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
