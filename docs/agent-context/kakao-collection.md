# KakaoTalk 수집 실행과 프로필 공유

개발 탐색용이며 로그인/수집/운영 활성화 증거가 아니다. 질문·학생 PDF는
[KakaoTalk 보관](kakao-archive.md), 정본 설계는
[수집 실행 경계](../architecture/KAKAO_COLLECTION_EXECUTION_BOUNDARY.md)를 먼저 본다.

## 설치 준비 경계

source head0093의 기존 release operator successor는 context/admission1.28과
`MIGRATION_UPGRADE_0093_FROM_0087`/`MIGRATION_VERIFY_0093`다.1.27의 의미를 넓히지 않는다.
source 준비·임시 DB 왕복은 운영 설치 증거가 아니며 현재 설치 기록을 먼저 확인한다.
학생/질문/PDF와 AUTO 수집의 활성화 범위도 별도로 확인한다.

## Studio 수신물 확인

`kakao_capture_intake_service.py`는 기존 room intake owner를 최근 수신물 선택에 연결한다.
`kakao_download_inputs.py`의 metadata-only reader/list와 실제 payload materialization을
분리한다. 목록은 최근 MANUAL8개/최대50건이고 complete inventory가 아니다. 공개 DTO에는
provider key·경로·DOM·파일명·본문·인증정보를 넣지 않는다. `manual-capture-intake-v1`의
preview hash와 사용자 확인은 원래 입력을 pin할 뿐 권한 token이 아니다.

`kakao_capture_rpc.py`/dispatch → 기존 API-peer socket → API `kakao_captures.py` →
Web `kakao_capture_routes.py`/gateway → `static/kakao-captures.js` 순이다. 현재 owner/admin/
COLLECT와 원래 lease/fence를 파일 I/O 뒤에도 검사한다. 확인 POST만 payload를 읽으며
기존 room proof·admission을 재사용한다. 완료 replay는 canonical proof를 읽어 local 파일
삭제와 분리한다. 새 학생/질문/source 수락·capability 승격·AUTO 시작은 수행하지 않는다.
화면은 불확실한 응답의 key/body를 유지하고 다른 owner/binding의 늦은 목록을 표시하지 않는다.

CSV popup successor는 같은 공개 요청의 독립 방 근거다. 기존 사진 proof/version에는
손대지 않는다. preview는 보호된 관측만 읽고, 확인 POST에서 CSV/hash를 확인해 새
proof를 발행한다. 고정 artifact manifest에서 원래 schema를 해석하고, capability
소비자가 같은 태그의 저장 근거를 다시 검사한다. 사진 파일과 말풍선의 연결, 전체 범위,
발신 역할·시각대는 이 방 근거로 인정하지 않는다.

## 담당 코드

`kakao_room_intake.py`와 `kakao_capability_service.py`가 실제 MANUAL 수신 관측을 기존
Room/Artifact owner에 수락한다. 이름이나 파일명은 identity가 아니다. 이 수락만으로
DRAFT를 활성화하거나 사진 occurrence/전체 목록을 검증했다고 표시하지 않는다.

`kakao_collection_service.py`는 현재 실제 API actor의 수집 의도를 run/ordered task로
저장한다. 원래 policy/capability/adapter를 pin하고 same-key replay·active binding 중복을
보호한다. `kakao_collection_authorization.py`가 이 owner와 browser owner의 현재 계정/
권한·정확한 pin 판정을 공유한다. 내부 준비 read는 API session이나 source authority가 아니다.

`kakao_collection_browser_service.py`는 PREPARING/RUNNING/STOPPING/CLOSED process
lifetime과 원래 실행 pin을 저장한다. 기존 `kakao_profile_runtime`을 MANUAL과 공유하며
별도 AUTO mutex/queue를 만들지 않는다. 실제 관측 callback은 DB lock 밖에서 수행하고
현재 fence/version을 다시 대조한다. timeout만으로 종료/재실행을 허용하지 않는다.
현재 slice는 원래 epoch를 재사용하며 CLOSED replay도 새 browser로 바꾸지 않는다.
worker command/task·source admission·상위 run 완료는 별도 경계다.

`kakao_collection_attempt_service.py`는 실제 RUNNING epoch와 기존 room task에 최초
attempt/command/snapshot identity를 한 번 예약한다. 기존 Artifact의 command/inventory와
canonical capability를 읽고 late 권한/fence를 재검사해 고정한다. 결과 proof를 수락해도
원본 성공은 아니며, 기존 source owner가 실제 revision을 채택한 뒤 task가 LOCAL_ACCEPTED다.
`authorize_source` callback이 실제 수락한 exact command/capability/result/report만 허용하고
worker가 선언한 attempt/fence만 믿지 않는다. FAILED와 같은 요청의 재조회는 새 실행이 아니다.
최초 attempt 저장 구현은 실제 AUTO 시작/selector/주기 실행을 활성화하지 않는다.
inventory는 command Artifact에 복사하지 않고 별도 exact Artifact pointer로 저장·재인가한다.

`admit_capture_source`는 실제 accepted capture의 기존 source admission→원 task 채택을
하나의 application 입구로 연결한다. 원본 commit 직후 중단돼도 같은 입력/key는 저장된
source revision을 재조회한 다음 task만 채택한다. Artifact·원본 bytes·attempt를 다시 만들지
않는다. 기존 source callback·현재 사용자·CAS 검사는 유지하며, 이 source 연결 자체는
collector 실행/실제 카카오 검증이나 운영 source admission 활성화가 아니다.

`publish_and_admit_capture_source`는 같은 owner의 실제 RESULT_ACCEPTED 결과를 읽고
`kakao_capture_publication.py`에서 기존 CSV/정규화/사진 발행기를 호출한 뒤 위 입구로 잇는다.
로컬 member reader는 trusted Orchestrator composition이 제공하며 public path 입력이 아니다.
원래 source precondition/key는 고정 입력이다. `KakaoSourceService.completed_capture_source`가
unique(binding,capture_attempt)의 exact 완료 revision을 읽어, 완료/채택 직후 중단 복구에서는
workspace·parser·decoder를 다시 요구하지 않는다. 실제 actor·현재 source 권한과 원래
capability/result/report pins는 계속 검사한다. 사진 binary는 재사용해도 attachment occurrence는
각각 남기며 검증되지 않은 화질/발신 방향을 승격하지 않는다. 실제 collector 실행·수락은
여전히 별도이며 이 source 연결로 AUTO나 로컬 샘플을 운영 등록하지 않는다.

`kakao_collection_source_access.py`는 이 경로의 trusted controller가 실제 RESULT_ACCEPTED
attempt에서만 얻는 내부 권한 adapter다. `kakao_source_access.py`의 API adapter와 같은
SourceService를 사용하지만, HTTP session을 생성/연장하지 않고 현재 DB owner·ADMIN/
READ/COLLECT·binding/room·원 pin과 실제 accepted result를 재검사한다. 정상 logout/HTTP
만료 후에도 정확한 원본 발행/채택은 이어지며, 공개 source 조회·PDF 다운로드는 여전히
현재 API 로그인을 요구한다. background source read도 해당 capture의 admission에 한정한다.
terminal run에서는 완료 source의 exact replay만 허용하고 새 publication을 시작하지 않는다.
`test_kakao_collection_source_access.py`는 임시 DB에서 이 경계와 중단·경합을 검사한다.
이 adapter는 worker/public DTO가 아니고, AUTO/collector 운영 활성화 자체도 아니다.

`kakao_capture_inputs.py`는 configured local root의 exact attempt/`outputs/` member를 기존
OS guard로 읽는다. `kakao_collection_source_composition.admit_staged_kakao_capture_source`가
실제 accepted access와 이 lazy reader를 기존 publication/adoption에 주입한다. directory/file
UID/GID/mode·link·변경·byte 크기/SHA를 검사한다. 완료 replay는 파일이 없어도 원 source를
읽고, adapter는 worker/공개 요청에서 root나 authority를 받지 않는다. 일반 server import는
optional collector/OS 구현을 eager load하지 않는다. 실제 browser dispatch/관측·운영 배치는
별도이며, 이 소스 연결만으로 수집이 실행 중이라고 판단하지 않는다.

동일 composition은 `KakaoCaptureOutputReader.read_result`의 고정32KiB proposal을 기존
attempt의 `publish_and_accept_result`에 먼저 넘긴다. 실제 command/capability와 C1 schema/
canonical bytes·report4MiB/hash를 검증한 뒤 `kakao_capture_result_publication.py`가 기존
`ControlFileSetPublisher`에 result/report만 발행한다. 원본 CSV/사진은 이 Artifact에 복사하지
않는다. 발행 후 row 채택 전 중단은 exact key의 completed publication을 읽어 `accept_result`
만 복구한다. FAILED/PAUSED/CANCELLED는 기록하지만 source로 진행하지 않는다. 이미 수락한
내부 metadata read는 source 권한이 아니며 그 다음 현재 accepted-source 권한 검사를 유지한다.
설치 release commit은 trusted controller에서 전달하고 ambient Git을 사용하지 않는다.

`kakao_capture_proposal.py`는 exact C1 command/capability/inventory를 먼저 확인하고, 실제
수집 owner가 넘길 CSV·행 관측·사진 member로 기존 normalization/report/result를 조립한다.
발신/시간대/순서를 자동 추정하지 않고 같은 사진 bytes의 별도 행을 유지한다. 일부 room
결과만 조립하고 브라우저를 실행하거나 권한·완전성·등록을 부여하지 않는다. 기존
`admit_staged_kakao_capture_source`의 합성 파일·DB 테스트로 이 연결을 검증한다.

원본 채택 다음의 `KakaoQuestionService.create_source_candidates`는 같은 accepted access로
최대100개 후보를 기존 질문 owner에 저장한다. API 세션을 꾸미지 않으며 현재 EDIT도 확인한다.
source는 한 번 해석하고 origin을 bounded IN lookup해 이미 편집/제외/분할/병합된 원본은
보존한다. 고정 source/candidate key로 중단 후 같은 Artifact를 채택하고, 미해석 row ordinal을
반환한다. 아직 실제 AUTO dispatcher 호출/운영 활성화는 아니며 unknown source order를
승격하지 않는다. 저장/수동 편집·PDF 접근은 [보관 문맥](kakao-archive.md)을 함께 본다.

`build_configured_kakao_collection_attempts`는 명시적인 collection adapter SHA와 기존 profile
ID가 있을 때만 실제 owner를 만든다. `application_runner`가 이를 질문 composition에 넣어
질문/읽기/편집/개념이 같은 source·Artifact owner를 사용한다. 설정 미지정은 기존 admission
거부이며 명시한 잘못된 설정은 오류다. browser driver hash를 대신 쓰거나 source를 임의
수락하지 않는다. 같은 owner의 public `sources` property는 trusted composition용이고
새 권한/HTTP session을 만들지 않는다. 이 구성만으로 AUTO나 collector를 시작하지 않는다.

MANUAL history의 profile FK와 binding FK는 분리한다. 같은 owner가 실제 STOPPED·lock
해제를 확인한 뒤 현재 binding만 바꿀 수 있고 과거 lease/수신 proof는 수정하지 않는다.
다른 owner로의 profile 이전은 허용하지 않는다. 실제 channel identity 검사는 별도다.

`browser_first_observed_at`는 DB0097의 nullable 최초 browser 관측이고,
`browser_observed_at`은 계속 최신 관측이다. `prepare_gateway`가 실제 첫 관측을 한 번
채택하며 DB trigger는 변경·삭제와 역사적 row의 추측 backfill을 거부한다.
`OwnedManualCaptureRun.validate_transfer_interval`은 최초 시각이 있으면 이를 하한으로
사용해 RENEW 이후에도 원래 정상 수신물을 읽는다. 과거 NULL은 최신 관측의 보수적 하한을
유지한다. lease 생성 시각·CSV 시각으로 대신하지 않는다. 새 wire/queue/index는 없으며
source 권한·fence·만료·종료와 Artifact 검증은 그대로다. context1.32의 정확한0096→0097
전환과 임시 DB 검증은 운영 적용 증거가 아니므로 installed release를 따로 확인한다.

`kakao_browser_runtime.py`·`kakao_profile_observation.py`·`kakao_manual_runtime.py`는 기존
Orchestrator OS adapter다. profile flock·systemd boot/invocation/cgroup 실제 상태를
관측하며 core/worker가 타 component의 DB/NAS를 직접 쓰지 않는다. source existence나
임시 DB의 합성 관측 PASS를 실제 Kakao/AUTO 활성화로 간주하지 않는다.
`kakao_collection_browser_runtime.py`는 같은 fixed adapter의 exact start·관측·종료를
collection metadata에 연결한다. 이미 staged된 epoch는 관측만 한다. 알려진 invocation이
바뀌면 다른 프로세스를 정지하지 않고, reboot와 PRE_READY_FAILED를 성공 flush로 바꾸지 않는다.
`kakao_browser_history.py`는 실제 보호된 입력의 MANUAL/AUTO fence와 일치하는 닫힌 기록만
반환한다. 두 모드 전환에 같은 브라우저를 동시 실행하지 않는다.

`kakao_one_room_collection.py`는 수락된 run→browser→원 attempt, 고정 command dispatch,
receipt→동일 browser의 종료→원본 수락·단일 run 종료를 기존 owner로 호출한다. receipt가
없을 때 실행 중이라는 증거는 OS 관측이다. 끝난 프로세스는 receipt 없이 성공하지 않으며
닫힌 socket/epoch를 재시작하지 않는다. `start_registered_room`은
`kakao_collection_input_publication.py`와 기존 capability owner를 사용해 등록된 한 방의
증거에서 C1 command/선택 범위 inventory를 한번 발행·pin하고 실행에 넘긴다.
카카오 route 키는 exact manual proof가 pin한 page observation에서만 추출한다. 원본 증거와
capability를 복제하지 않으며, 발행 뒤 pin 중단은 동일 member revision을 재사용한다.
검증한 CSV popup proof에서만 현재 세 키의 AUTO v2 직접 주소를 사용한다. 다른 증거는 v1
목록 경로를 유지하고 v2는 주소/DOM이 맞지 않으면 목록으로 우회하지 않는다.
기존 Catalog runner의 `ONE_ROOM` 설정이 맞으면 `kakao_collection_continuation.py`가
durable pending run을 선택한다. 원래 browser/attempt 및 source command의 CAS를 재사용하고
수신물이 없거나 고정 수신물의 내용이 확정적으로 잘못된 한 방은 실제 종료 확인 뒤 `FAILED`로
남긴다. 일반 I/O·인가·발행 오류를 수신물 오류로 바꾸지 않는다. 사용자의 상태 조회는 `get_status`만
호출한다. HTTP→보호된 API-peer의 collection 요청은 `kakao_collection_dispatch.py`에서
검증하고, 기능이 꺼져 있으면 작업을 접수하지 않는다. Studio의 `kakao_collection_routes.py`
및 `kakao-room-collection.js`는 admin/CSRF로 등록된 방 수집을 접수하고, 같은 탭에서
같은 owner/binding/room의 미확정 키 또는 수집 ID를 되찾는다. 접수 뒤는 GET만 쓴다.
운영 활성화와 전체 방 주기 수집은 별도다.

계정 화면으로 이동한 방과 목록이 모두 확인되면 collector는 기존 C1 `FAILED/AUTH_REQUIRED`
제안을 단일 `auth-refusal.json`으로 쓴다. `KakaoOneRoomCollection.finish`가 실제 브라우저
종료 뒤 기존 result publisher와 attempt owner에 넘긴다. source나 새 수집을 만들지 않으며,
원래 결과가 먼저 채택됐으면 작업 파일 없이 같은 단일 run을 종료한다.

## 검증 경계

`manual_observation.py`는 leaf element뿐 아니라 direct text/BR 조각도 관측한다. 원문 CSV가
canonical text이며 DOM 조각을 전체 문장/전체 이력으로 간주하지 않는다. 편집·인증 subtree,
페이지 이동과 전체 text/element/direct-node 상한은 유지한다. `download_origins.py`는 같은
페이지의 실제 GET image endpoint→허용된 CDN redirect→download를 일회성으로 연결한다.
출처 연결 실패 수신에는 `manual_download.py`가 같은 보호 폴더에 운영 진단 한 줄만 보관한다.
주소·식별자·예외 문자열은 저장하지 않으며 진단으로 정합 조건을 완화하지 않는다.
`photo_dom_diagnostic.py`는 직접 전송 형태의 수신에서 같은 방의 사진 링크·표시 주소가 최종
전송 주소와 일치하는지 검사한다. 브라우저를 벗어나는 값은 고정 분류뿐이며, 일치 결과도
말풍선/CSV 행 연결 권한이 아니다.
마지막 request leg의60초·64건·8redirect 상한과 SDK request identity를 확인하며 URL query/
header/cookie는 저장하지 않는다. URL hash index를 사용하고 다른 방·모호함·범위 없는 event는
소비 후 거부한다. direct CDN URL 자체는 여전히 UNAVAILABLE이고 source 권한이 아니다.
MANUAL의16건 상한은 AUTO의 전체 수집 상한과 다르며, loaded DOM 수만으로 CSV 전체를
수집/연결했다고 표시하지 않는다. 실제 redirect와 direct-text fixture는 별도 임시 Chromium/
loopback TLS proxy를 사용하며 개인 profile·실제 provider 접속/운영 인증은 사용하지 않는다.

`room_read_actions.py`는 열린 방과 보호된 room pin 위에서 세 가지 고정 동작만 제공한다.
실제 관측한 popup/menu/내보내기 구역과 같은 방의 단일 사진 링크를 확인하며 좌표나
외부 selector를 받지 않는다. 모호하거나 가려진 버튼은 누르지 않으며 timeout은 자동
재클릭 권한이 아니다. 테스트는 격리 browser의 실제 download event와 로컬 TLS302를
검사한다. 아직 AUTO 실행에 연결하지 않았고, 클릭 요청은 원본 수신/수락 증거가 아니다.
`room_read_transfer.py`는 그 동작 전에 exact page listener와 attempt 로컬 시작 표시를
준비한다. 같은-origin blob 또는 exact image GET/redirect 및 실제 SDK 파일이 확인되면
`manual_capture_files.py`의 보호된 복사·hash 경계를 사용한다. 원래 GET 연결이 없는
직접 CDN 전송은 AUTO가 클릭한 단일 사진의 유일한 표시 주소와 same-page CDN GET·
최종 전송 주소가 정확히 일치할 때만 연결한다. 비교값은 메모리에서만 쓰고 MANUAL의
사후 관측을 출처 판정으로 승격하지 않는다. 다른 event, 중복·timeout은
다시 누르지 않는다. 기존 `manual_download.py`도 같은 file copy를 사용하지만 이전
MANUAL receipt/경로/범위는 유지한다. 자동 dispatcher는 아직 여기에 연결하지 않았다.
`open_room_capture.py`는 이미 열린 한 room의 bounded DOM에서 일반 사진 최대6개를
고른 뒤 사진→메뉴→CSV를 한 번씩 연결한다. 앨범/중복/상한 밖은 미확정 수치를 남긴다.
같은 페이지의 CDN 직접 GET이 단일 파일로 끝났으나 원래 사진 요청에 연결되지 않은 경우,
나머지 사진 동작을 건너뛰고 해당 부분을 미확정으로 올린다. 기존 CSV 내보내기를 한 번
시도하며, 성공하면 확인된 CSV·사진만 기존 부분 수집 receipt에 넣는다. 그 외의 전송
불확실 상태는 이미 받은 파일만 유지하고 중단한다. 시작 표시가 있는 방은 재수집하지 않는다.
미로드 이력·channel 전체·실제 운영 collector start/C1 저장은 이 함수가 보증하지 않는다.
`kakao_capture_proposal.py`의 `build_open_room_proposal`은 좁은 내부 다운로드 증거를
받아 exact CSV/사진 member·scope·텍스트 앵커를 확인한다. 유일하지 않은 행은 미연결로
남기고, 실제 이미지 bytes만 기존 C1 제안에 넣는다. worker wire나 수락 권한은 추가하지
않는다. 실제 local 파일→기존 source owner의 PostgreSQL 통합 검사는 합성 입력으로 한다.
`capture_open_room_attempt`는 수신 뒤 같은 attempt에 고정 `open-room.json`을 한 번만 쓴다.
`KakaoCaptureOutputReader`가 보호된 member를 열면 `admit_staged_kakao_open_room`이 해당
command SHA와 실제 등록 방의 scope를 확인한 후 C1 문서를 기존 발행기에 넘긴다. 결과가
이미 수락된 재조회는 영수증을 다시 요구하지 않는다. 이 경로는 실제 AUTO 브라우저를
시작하거나 방을 여는 launcher가 아니다.
영수증 bytes가 수신 계약 자체를 위반하는 경우 `KakaoOneRoomCollection.finish`는 먼저
exact browser 종료를 확인하고, continuation은 기존 browser owner의 단일 방 실패
전이를 호출한다. 경로 보호·설치 schema 오류는 malformed bytes와 구별한다. 상태 재조회가
새 attempt나 브라우저를 시작하지 않으며 원본·영수증에는 쓰지 않는다.

`prepare_auto_room`과 `dispatch_staged_kakao_open_room`은 기존 active epoch/등록 room의
typed command를 `FixedKakaoBrowserRuntime.stage_auto_room`의 단일 고정 member에 넣는다.
`manual_driver`의 AUTO 분기는 기존 supervisor/profile lock 아래 같은 Chromium pin을
headless로 사용한다. `auto_room_browser.py`는 지정된 channel route와 안정 ID의 방만 열고
기존 guarded 다운로드를 호출하며 MANUAL/VNC 또는 임의 브라우저 조작을 하지 않는다.
방 선택으로 열린 별도 popup은 그 클릭을 호스팅한 목록의 이벤트에서만 받아 구분한다.
기존 탭을 뒤지지 않고, 새 창의 provider/room 경로와 popup 근거가 모두 맞을 때만 읽는다.
격리 브라우저 fixture의 selector와 실제 카카오 UI 일치 여부는 별도 검증 대상이다.

`kakao_photo_alignment.py`는 같은 MANUAL fence/page와 방, CSV exact hash를 확인한 뒤
단일 사진의 인접 메시지 window가 CSV에서 유일한 경우 row/album ordinal을 제안한다.
기본은 서로 다른 완전 본문 두 개로 사진을 감싸는 방식이다. 연달아 나온 사진이 화면의
끝에 있으면 같은 쪽 두 문장도 사용할 수 있지만, CSV 시점의 말풍선 식별자와 문장이
같은 순서로 보이고 그 구간이 실제 CSV 끝에서도 유일해야 한다. CSV 양쪽 순서를 모두 비교한다.
실방에서 확인한 하나의 자식 span에만 본문이 있는 형태도 exact 앵커 후보로 읽는다.
둘 이상의 본문 조각을 결합하거나, 안정적인 사진 경로 없이 행만 추측하지 않는다.
KMP는 같은 문구·같은 시각의 row를 합치지 않는다. 파일명·닉네임·시간 근접성은 쓰지
않고, 더보기·앨범·잘린 DOM·복수 매치는 미확정이다. 내부 `SEQUENCE_INFERRED` 제안이며
현재 source 권한·정본 첨부·방 전체 coverage를 증명하지 않는다. 공개 경로에는 아직 연결하지 않았다.
수신물 owner의 `inspect_photo_occurrence`는 기존 보호된 reader와 실제 binding/lease 권한을
I/O 전후 확인해 두 exact capture에서 이를 호출한다. CSV parser의 공통 헤더/행 검사를
재사용하고 가짜 normalization revision을 만들지 않는다. 원본/질문/Artifact 쓰기는 없다.
기존 수신물 UI의 '사진 위치 확인'은 별도 추가 wire인 `catalog-kakao-photo-check-v1`을
사용한다. `kakao-captures.js` → 기존 BFF/API `/manual-captures/photo-occurrence` →
기존 socket dispatch 순서이며 exact 선택과 응답을 각 경계에서 대조한다. 같은 로그인
회차의 두 파일을 고른다. 해당 없음과 전송 실패를 구분하고, 선택/owner가 바뀌면 늦은 응답을
버린다. source/API/Chromium 테스트는 실제 카카오나 운영 활성화 증거가 아니다.

`scripts/api/testdb_run.sh kakao-tests`의 guarded 임시 DB에서 MANUAL/AUTO 경합·중복
예약·늦은 권한 철회·관측 불일치·종료 실패·terminal 불변·원래 이력/다른 binding 보존을
검사한다. 기존 worker ProfileFence와 hash parity, closed owner metadata와 schema mirror도
검사한다. 실제 UI selector/수집/PDF와 protected 설치 검증은 별도로 기록한다.
