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
구분하며 원본을 덮지 않는다. 새 의존 Pillow는 이 worker에서만 사용한다.

`static/kakao-archive.js`는 기존 api/session/presenter를 주입받는다. private 파일 URL은
검증한 논리 ID와 pinned revision으로 만들고 source payload의 임의 URL을 쓰지 않는다.
실제 API가 없는 화면은 fixture 검증일 뿐 수집 성공으로 표시하거나 운영 연결로 보고하지 않는다.
학생 디렉터리는 `kakao-students.js`가 담당한다. 실제 학생 RPC/API/BFF를 사용하며 연결
선택과 독립된 owner/요청 순서 검사로 늦은 응답을 차단한다. 학생 생성 자체는 방 mapping이 아니다.
`kakao-rooms.js`는 확인된 방 조회와 학생 연결/해제를 같은 경계에서 수행한다. 연결 변경은
방 version·mapping parent·학생 표시 revision을 함께 확인한다. hard reload는 확정된 DB
상태를 다시 읽으며, 아직 응답이 확정되지 않은 변경 intent는 같은 화면 세션에서만 보존한다.
학생 이름과 변경 이유의 길이는 브라우저에서도 schema와 같은 Unicode code point 기준이다.

## 실제 브라우저 프로세스 경계

`kakao_browser_runtime.py`는 하나의 고정 systemd unit에 AUTO/MANUAL을 함께 연결한다.
별도 `eom_kakao_archive_collector` supervisor는 실제 profile flock을 child lifetime 동안
잡으며, root-installed 고정 driver만 실행한다. Catalog owner의 권한·현재 fence 검사는
필수 callback이고, DB lease 만료만으로 profile을 넘기지 않는다. 종료는 실제 invocation,
boot, cgroup 비어 있음과 exit status로 판정한다. 같은 실행의 시작 응답이 사라졌으면
다시 launch하지 않고 원래 run을 관측한다.

이 단계는 OS adapter 소스와 local subprocess 검증이다. driver, 카카오 selector, 원격
gateway·영속 lease와 실제 전용 UID/systemd 설치는 아직 없다. READY 이전 시작 실패의
staged intent도 보존하며, 후속 owner reconciliation 없이 marker를 삭제하거나 처음 실행으로
위장해 재시작하지 않는다. 설치/권한/실사 미완료를 수집 성공으로 표시하지 않는다.

## 먼저 볼 코드·검사

- `packages/catalog_contracts/eom_catalog_contracts/kakao_archive.py`
- `packages/catalog_contracts/eom_catalog_contracts/kakao_snapshot.py`
- `services/catalog_service/eom_catalog_service/kakao_archive_intake.py`
- `services/catalog_service/eom_catalog_service/kakao_archive_service.py`
- `services/catalog_service/eom_catalog_service/kakao_student_service.py`
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
