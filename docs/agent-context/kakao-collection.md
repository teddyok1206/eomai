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
`kakao_collection_browser_runtime.py`는 같은 fixed adapter의 실행 관측·exact stop/재관측을
collection metadata에 연결한다. 실제 시작/selector는 아직 제공하지 않는다. 알려진 invocation이
바뀌면 다른 프로세스를 정지하지 않고, reboot와 PRE_READY_FAILED를 성공 flush로 바꾸지 않는다.

## 검증 경계

`scripts/api/testdb_run.sh kakao-tests`의 guarded 임시 DB에서 MANUAL/AUTO 경합·중복
예약·늦은 권한 철회·관측 불일치·종료 실패·terminal 불변·원래 이력/다른 binding 보존을
검사한다. 기존 worker ProfileFence와 hash parity, closed owner metadata와 schema mirror도
검사한다. 실제 UI selector/수집/PDF와 protected 설치 검증은 별도로 기록한다.
