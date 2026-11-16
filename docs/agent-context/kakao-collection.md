# KakaoTalk 수집 실행과 프로필 공유

개발 탐색용이며 로그인/수집/운영 활성화 증거가 아니다. 질문·학생 PDF는
[KakaoTalk 보관](kakao-archive.md), 정본 설계는
[수집 실행 경계](../architecture/KAKAO_COLLECTION_EXECUTION_BOUNDARY.md)를 먼저 본다.

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

MANUAL history의 profile FK와 binding FK는 분리한다. 같은 owner가 실제 STOPPED·lock
해제를 확인한 뒤 현재 binding만 바꿀 수 있고 과거 lease/수신 proof는 수정하지 않는다.
다른 owner로의 profile 이전은 허용하지 않는다. 실제 channel identity 검사는 별도다.

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
