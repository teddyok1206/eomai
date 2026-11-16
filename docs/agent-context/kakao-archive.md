# KakaoTalk 비공개 질문 보관

사용자 메뉴는 **일반 → KakaoTalk**, 내부 feature/route는 `kakao-archive`다.
[설계서](../architecture/KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md)는 원문 보존하며,
후속 사용자 이름 결정과 실제 구현 범위는
[체크포인트](../operations/KAKAO_ARCHIVE_IMPLEMENTATION_CHECKPOINT.md)에 기록한다.
이 문맥은 개발 탐색용이며 카카오 로그인·수집·운영 활성화 증거가 아니다.

## 책임과 원문

기존 Studio/BFF → API → Catalog → Orchestrator 경계를 사용한다. 학생 대화는 비공개
source이며 문항 DB·GraphRAG·자료 학습과 분리한다. AI/OCR/임베딩을 호출하지 않는다.
현재 operator의 권한과 binding owner를 함께 검사하며 ADMIN도 타인 원문에 우회 접근하지 않는다.

`kakao_csv_parser.py`는 strict UTF-8 CSV를 읽고 원문·순서·중복 행을 보존한다. 발신 역할,
시간대와 순서는 실제 관측이 없으면 UNKNOWN이다. `kakao_message_alignment.py`는 제한된
범위만 정합하며 사라진 행을 삭제로 판정하지 않는다. `kakao_question_rules.py`는 원문을
바꾸지 않고 row/attachment occurrence 포인터로 후보를 만든다. 기간 선택은 후보 생성 뒤다.

`kakao_archive_intake.py`는 검증된 로컬 입력을 기존 CatalogArtifactService로 발행한다.
원본 CSV와 snapshot receipt, 정규화 Artifact가 분리되고 exact hash/ID로 연결된다.
Job metadata에는 학생 이름·대화 원문을 넣지 않는다. 호출자의 실제 권한과 fence 재확인
callback은 필수다. 이 adapter 자체가 공개 권한이나 private 다운로드 경계를 완성하지 않는다.

`kakao_media_publication.py`는 PNG/JPEG/WebP의 크기·정적 이미지 여부·실제 decode를 검사하고
원본 bytes·EXIF·SHA를 그대로 발행한다. 같은 binding의 같은 bytes는 기존 Artifact publication을
재사용하며 사진 blob과 메시지별 attachment identity를 구분한다. Pillow는 선택적인
`kakao-runtime` 의존으로 지연 import하며 이 기능을 켜지 않은 Catalog에는 필요하지 않다.

`kakao_source_service.py`는 수락된 방의 원본·정규화·사진과 실제 capture 증거를 하나의 불변
source resolution으로 연결한다. 큰 본문/occurrence map은 Artifact에, DB에는 작은 pointer·
current/version·명령 예약만 둔다. source 수락은 내부 use case이며 실제 수집 권한 callback과
exact attempt/fence 검증이 필수다. 같은 요청은 원래 identity를 재사용하고 새로운 snapshot은
이전 source를 덮지 않는다. 실제 collector 연결 없이 fixture를 운영 수집으로 간주하지 않는다.
`resolve_question_source`는 이 accepted revision을 기존 질문 규칙의 입력으로 해석하며
실제 I/O 이후에도 현재 권한과 같은 Artifact pointer를 재확인한다. 호출자는 고유 source별
한 번 해석한 결과를 해당 요청의 질문들에 재사용한다. source 전용 command를 범용 큐로 쓰지 않는다.
저장 연결의 범위와 후속 질문/출력 책임은
[저장 설계](../architecture/KAKAO_ARCHIVE_DURABLE_CONTENT.md)에 정리한다.

`resolve_question_source_context`는 같은 해석에 accepted source closure를 함께 반환한다.
`validate_question_source_metadata`는 I/O 없는 짧은 transaction에서 원본·resolution·capture
근거의 metadata와 현재 owner 권한을 다시 검사한다. 정규화/사진만 확인하는 것으로 원본
접근 철회 검사를 대신하지 않는다. 이 내부 context는 새로운 실행 권한을 부여하지 않는다.

`kakao_question_service.py`는 accepted source 후보의 최초 저장과 exact revision 조회·검토
수정을 담당한다. 서버 ID/시각/mapping을 작은 command에 예약하고 기존 publisher 밖의 I/O
뒤에 current를 CAS로 채택한다. 다른 key의 같은 origin은 명시적 중복 오류이며 수동 결과를
덮지 않는다. `resolve_questions`는 packet/export의 ordered exact selection을 한 번에 읽고,
고유 source마다 한 번 해석한다. 목록은 작은 metadata만 읽는다. schema는
`kakao_question_store.py`, DB는 `kakao_question_models.py`에 있고 본문은 Artifact다.
이는 source/storage 구현 경계이며 API·GUI 전체 연결이나 운영 migration 완료 증거가 아니다.

`kakao_packet_service.py`는 선택한 exact question revision·기간·출력 모드의 불변 묶음을
저장한다. 새 선택은 새 packet revision이며 기존 묶음을 최신 질문으로 다시 구성하지 않는다.
원본/사진은 복제하지 않고 기존 question batch resolver와 packet publisher를 사용한다.
`resolve_student`는 선택 학생의 source만 해석해 출력 입력으로 넘기며 이름으로 합치지 않는다.
metadata 목록은 본문을 읽지 않는다. 저장 DTO와 모델은 각각 `kakao_packet_store.py`,
`kakao_packet_models.py`다. 이 저장 경계를 실제 PDF 실행·private download 연결과 구별한다.

`kakao_pdf_inputs.py`는 그 학생의 exact selection을 기존 render projection에 연결하는
로컬 materialization adapter다. 원본 사진은 검증된 Artifact FD에서 pointer별 한 번 읽고
occurrence 수와 순서는 유지한다. 파일·font의 hash와 source 권한을 확인하고 기존 파일을
덮지 않는다. worker command에는 로컬 member만 들어가며 NAS/DB/인증정보를 넘기지 않는다.
이 단계의 입력 생성·실제 합성 렌더·Artifact 조회 시험은 export 상태 owner나 HTTP
다운로드·운영 sandbox 활성화의 대체 증거가 아니다.

`kakao_archive_service.py`는 DRAFT 연결과 불변 정책 revision/명령 receipt의 소유자다.
현재 session·permission·ADMIN 역할은 Identity repository에서 다시 확인하며 다른 owner의
binding은 존재하지 않는 것과 같은 오류다. `kakao_archive_rpc.py`는 기존 Catalog API-peer
socket의 별도 closed operation family이고, 실제 actor/session만 전달하며 caller 역할 주장을
받지 않는다. HTTP/BFF는 기존 인증·CSRF·If-Match와 같은 replay key를 유지한다.
설정 생성은 채널 검증·수집·원격 로그인을 수행하지 않는다.

`kakao_student_service.py`는 owner 범위 학생 identity와 immutable display revision을
관리한다. 이름으로 학생을 합치지 않으며 rename/retirement 뒤에도 이전 exact revision과
원래 명령 replay를 보존한다. `kakao_archive_commands.py`의 짧은 intent 잠금·정규 request
hash만 binding과 공유한다. 학생 정보는 Item/Graph로 등록하지 않는다.

`kakao_room_service.py`는 수락된 방 identity와 불변 학생 연결을 관리한다. 방 생성은
검증된 관측 Artifact와 현재 owner 권한을 요구하는 내부 admission이고 공개 create API는
없다. worker의 room ID·닉네임은 정본 식별자가 아니다. public 읽기/연결/해제는 실제
binding·owner 범위에서 수행하며 이전 mapping과 정확한 학생 표시 revision을 보존한다.
공통 intent 잠금과 짧은 CAS를 재사용하며, 방에는 현재 mapping pointer/version만 UPDATE한다.

`kakao_question_editing.py`는 질문의 exact source span/사진·분할/병합·검토와 packet
선택을 담당한다. `kakao_question_publication.py`는 결과 manifest만 기존 Artifact owner로
발행하고 CSV/사진은 다시 복사하지 않는다. 발행 후 DB 수락·현재 mapping/source 권한은
호출 use case 책임이며 이 함수 자체가 private 원문 조회 권한은 아니다.
`kakao_render_projection.py`는 packet 안의 요청한 학생 subset만 골라 exact source를
로컬 렌더 manifest로 바꾼다. source binding·질문 revision·학생 표시·사진 포인터를
대조하며 다른 학생의 입력을 함께 넘기지 않는다.

## PDF와 화면

별도 `eom_kakao_archive_contracts`와 `eom_kakao_archive_worker` wheel은 격리 렌더링 경계다.
worker 구현은 staged local members만 읽고 DB·NAS·브라우저 profile·네트워크를 사용하지 않는다.
`kakao_pdf_execution.py`는 exact attempt/fence·로컬 input/output·중단 후 동일 결과
수락을 연결한다. unit/template 소스는 있어도 실제 전용 UID·sandbox 설치 검증은
별도 운영 gate이며 아직 PASS로 기록하지 않는다.
`kakao_pdf_publication.py`는 이 완료 결과를 기존 Artifact 발행에 연결한다. 별도 NAS
writer나 재렌더 없이 export+attempt의 같은 publication을 재조회하고, 원래 JSON bytes의
hash와 PDF/PNG/layout member 집합을 유지한다. 발행 후 현재 export pointer 수락과
권한별 다운로드는 별도 use case이며 아직 운영 완료로 표시하지 않는다.
질문 한 개가 한 페이지이며 사진은 자르지 않는다. glyph/배치/필수 사진 조건이 실패하면
명시적으로 검토 필요이고 성공 PDF로 발행하지 않는다. 검증된 원본과 EXIF 적용 derivative를
구분하며 원본을 덮지 않는다. Pillow는 이 worker와 선택적으로 활성화한 사진 수락에서 사용한다.
날짜가 확인되지 않은 DRAFT는 `날짜 확인 필요`로 표시한다. 날짜를 추정하지 않으며,
같은 미확정 입력의 FINAL은 계약과 순수 규칙에서 거부한다.

`static/kakao-archive.js`는 기존 api/session/presenter를 주입받는다. private 파일 URL은
검증한 논리 ID와 pinned revision으로 만들고 source payload의 임의 URL을 쓰지 않는다.
실제 API가 없는 화면은 fixture 검증일 뿐 수집 성공으로 표시하거나 운영 연결로 보고하지 않는다.
학생 디렉터리는 `kakao-students.js`가 담당한다. 실제 학생 RPC/API/BFF를 사용하며 연결
선택과 독립된 owner/요청 순서 검사로 늦은 응답을 차단한다. 학생 생성 자체는 방 mapping이 아니다.
`kakao-rooms.js`는 확인된 방 조회와 학생 연결/해제를 같은 경계에서 수행한다. 연결 변경은
방 version·mapping parent·학생 표시 revision을 함께 확인한다. hard reload는 확정된 DB
상태를 다시 읽으며, 아직 응답이 확정되지 않은 변경 intent는 같은 화면 세션에서만 보존한다.
학생·채널 이름과 변경 이유의 길이는 브라우저에서도 schema와 같은 Unicode code point 기준이다.

`kakao_manual_service.py`는 고정 프로필의 owner/binding 배정, MANUAL 의도와 짧은 접근
허가를 저장한다. 새 DB 큐가 아니라 프로필 하나의 indexed gate이며, AUTO도 나중에 같은
gate를 사용해야 한다. DRAFT 연결의 첫 로그인은 허용하되 채널 검증/수집 성공으로 바꾸지
않는다. 시작은 PREPARING 접수이며, 브라우저·gateway 실관측 뒤에만 ACTIVE가 된다.
같은 명령은 원래 응답을 재사용하고 수명을 늘리지 않는다. OS 호출은 DB 잠금 밖에서 한다.
현재 Identity session·ADMIN·remote 권한을 재확인하며 내부 lookup은 실제 접수된 owner/
session pointer를 사용한다. HTTP/RPC의 클라이언트는 profile·fence·READY·TTL을 주장할 수 없다.

`AUTHORIZE_KAKAO_MANUAL`은 기존 history READ와 다르다. 현재 owner/Identity session/
MANUAL fence/TTL을 검증하고, DB 잠금 밖의 실제 runtime 관측 뒤 같은 revision과 권한을
다시 대조한다. GET admission은 실행·갱신·복구를 하지 않는다. API/BFF 성공은 빈 204다.
WebSession에는 작은 lease/binding pointer만 두고 매 접속 때 API를 재조회한다. 세션 삭제·
만료·이전 응답은 generation/CAS로 기존 연결을 되살리지 못한다. 고정 transport 검사는
순수 Kakao contracts를 재사용하며 현재 lease 권한 규칙을 Web에 복제하지 않는다.

Web의 선택 설정 `kakao_remote_transport`는 HTTPS origin과 설치된 정적 파일 경로만
가진다. Secure cookie·허용 host를 확인하며 생략하면 접근이 꺼져 있다. 관리자는
`remote/configuration`에서 boolean 표시 설정만 읽고, 실제 접속은 별도 현재 lease
검사를 거친다. 구성 조회 응답만으로 ACTIVE나 로그인을 만들지 않는다.

`kakao_manual_coordinator.py`는 고정 profile의 현재 intent를 기존 service 전이와 OS
adapter에 연결한다. 별도 bounded thread가 systemd 대기를 담당해 기존 Catalog 업무를
막지 않는다. `kakao_manual_composition.py`는 설치 pin이 없거나 비활성일 때 전용 worker
package/UID를 요구하지 않는다. 정상 history GET이 active라고 보여도 실제 gateway
admission이 보장되는 것은 아니다. 갱신 발행 직전에는 준비 상태가 일시 불일치할 수 있다.

## 실제 브라우저 프로세스 경계

`kakao_browser_runtime.py`는 하나의 고정 systemd unit에 AUTO/MANUAL을 함께 연결한다.
별도 `eom_kakao_archive_collector` supervisor는 실제 profile flock을 child lifetime 동안
잡으며, root-installed 고정 driver만 실행한다. Catalog owner의 권한·현재 fence 검사는
필수 callback이고, DB lease 만료만으로 profile을 넘기지 않는다. 종료는 실제 invocation,
boot, cgroup 비어 있음과 exit status로 판정한다. 같은 실행의 시작 응답이 사라졌으면
다시 launch하지 않고 원래 run을 관측한다.

MANUAL driver는 별도 collector 환경에서 Playwright와 Xvnc를 실행한다. 원격 gateway의
기존 lifetime은 PDF worker에서 `eom_kakao_archive_gateway/lifetime.py`로 이동했으며,
고정 UDS→UDS 통로와 짧은 grant 감시를 담당한다. `kakao_gateway_runtime.py`는 실제 VNC
준비와 exact lease/epoch 실행을 확인한다. 공용 `kakao_runtime_os.py`는 두 고정 unit의
보호 파일·boot·systemd·cgroup 관측만 담당하며 scheduler/권한 규칙을 갖지 않는다.

READY 이전 실패와 reboot는 원래 staged intent/hash를 보존한 채 관측한다. PID가 없어도
systemd Job이 남아 있으면 종료 완료가 아니다. 정확한 실제 종료가 확인되기 전 입력을
갈아끼우거나 marker를 지우지 않는다. 종료 관측은 성공/flush 증거나 신규 권한이 아니다.

이 단계는 소스/local subprocess/임시 DB 검증이며, actual selector·Caddy와 원격 admission·
전용 UID/systemd 설치·실제 카카오 로그인/수집은 별도 gate다. `scripts/kakao/install_runtime.py`
역시 준비된 보호 runtime만 설치하는 경계이며, 코드 존재를 설치 완료로 해석하지 않는다.
`scripts/kakao/publish_runtime.py`는 초기 설치의 3개 prefix·2개 asset만 보호하며 기존
install manifest와 정확한 dependency lock을 검사한다. Conda는 최종 전용 prefix에서
준비하고 새 root inode로 게시한다. tmp 환경 복사·다른 환경 업그레이드·서비스 시작은 하지
않는다. 일부 게시 후 실패하면 기록/준비본을 보존하고 별도 확인 없이 재설치하지 않는다.
`config/caddy/kakao-remote.caddy`는 검증용 opt-in template이다. 운영 Caddyfile에는
자동 import하지 않는다. forward metadata는 Caddy가 덮어쓰고, 허용된 private UDS로
보내기 전에 cookie/authorization을 제거한다. 허가 실패를 200으로 반환하지 않는다.

## 먼저 볼 코드·검사

- `packages/catalog_contracts/eom_catalog_contracts/kakao_archive.py`
- `packages/catalog_contracts/eom_catalog_contracts/kakao_snapshot.py`
- `services/catalog_service/eom_catalog_service/kakao_archive_intake.py`
- `services/catalog_service/eom_catalog_service/kakao_archive_service.py`
- `services/catalog_service/eom_catalog_service/kakao_student_service.py`
- `services/catalog_service/eom_catalog_service/kakao_room_service.py`
- `services/catalog_service/eom_catalog_service/kakao_manual_service.py`
- `packages/catalog_contracts/eom_catalog_contracts/kakao_manual_rpc.py`
- `apps/application_api/eom_api/routers/kakao_manual.py`
- `services/orchestrator/eom_orchestrator/kakao_browser_runtime.py`
- `services/orchestrator/eom_orchestrator/kakao_gateway_runtime.py`
- `services/kakao_archive_collector/eom_kakao_archive_collector/manual_driver.py`
- `services/kakao_archive_gateway/eom_kakao_archive_gateway/supervisor.py`
- `packages/catalog_contracts/eom_catalog_contracts/kakao_students.py`
- `services/catalog_service/eom_catalog_service/kakao_archive_authorization.py`
- `packages/catalog_contracts/eom_catalog_contracts/kakao_archive_rpc.py`
- `apps/application_api/eom_api/routers/kakao_archive.py`
- `apps/web_gui/eom_web_gui/kakao_archive_routes.py`
- `packages/kakao_archive_contracts/eom_kakao_archive_contracts/`
- `services/kakao_archive_worker/eom_kakao_archive_worker/`
- `tests/unit/test_kakao_archive_rules.py`
- `tests/unit/test_kakao_archive_intake.py`
- `tests/unit/test_kakao_question_render.py`
- `tests/web_gui/test_kakao_archive_browser.py`

실제 카카오 selector·채널 export 범위·사진 capability는 별도 실증 대상이다. 임시 합성
CSV/브라우저/worker PASS를 실사나 설치된 활성 계약과 동일시하지 않는다.
