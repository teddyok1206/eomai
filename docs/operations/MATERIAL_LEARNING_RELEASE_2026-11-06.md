# 자료 학습 운영 반영 — 단계별 증거

기준: 2026-11-06 06:12 UTC. **전체 목표의 완료 보고서가 아니다.**
사용자 지정 순서는 자료 학습의 운영 반영·실제 처리 확인을 완료한 뒤 Map의 Layer
표시 개선에 착수하는 것이다. Map은 아직 시작하지 않았다.

## 최신 인계·실제 결과 확인

기존 INDEX는 지원된 main stop Event로 현재 묶음을 자연 종료했다(`Result=success`).
현재 service revision의 non-terminal 요청과 native lifetime이 비어 있음을 기존 owner가
검증한 뒤 unchanged-scope 후속 identity/config를 선택했다.06:08 UTC 새 e1df5c8f INDEX가
enabled/active로 기동했다. 수치 controller/model·CPU/GPU 환경과 과거 기록은 불변이다.
아래 ‘INDEX 인계 대기’ 설명은 배포 순서와 그 당시 상태이며, 인계 자체는 완료했다.

첫 DISCOVER Workflow/Job은 실제로COMPLETED/SUCCEEDED였다. 그러나 coordinator의
완료 결과 읽기에서 file-set 전용 `read_member`를 사용해, 실제 Orchestrator가 저장한
single-primary `ArtifactManifest`에 존재하지 않는 `files` 배열을 요구하는 결함을 발견했다.
모델 실패가 아니다. 같은 결과를 보존하고 기존 `load_json_revision` owner로 읽도록
수정했다. 이 owner는 두 실제 JSON 저장 형식의 identity·lifecycle·manifest·size·hash·
bounded nofollow FD를 이미 검증하며, material reader는 기존 Job/Workflow/plan/source
closure와 정확한 role schema/receipt를 그대로 검증한다. 새 wire format이나 file 변환,
DB/NAS 덮어쓰기·예외 무시는 없다.

실제 Orchestrator writer→Catalog verified JSON reader 회귀를 추가했다(권한/DB port는
명시적 synthetic). 집중70 PASS·material 임시 PostgreSQL41 PASS·mypy/format/lint PASS.
수정 후보는 **material owner에만** 호환 prefix로 반영하며 API/Web/QUERY/실행 중 INDEX를
다시 바꾸지 않는다. 새 모델 요청 없이 이미 성공한 DISCOVER 결과부터 이어서 확인한다.

## 실제 운영에 반영한 범위

- 설치 source `e1df5c8f9925d977028c66e2b99ad056a1ada583`: API·Web·Catalog·
  global Workflow Runner·채팅 연결 설정·창작 producer/관측 owner.
- production head `20261105_0074`. 공식 protected release operator context/admission
  1.21로 정확한0073→0074 upgrade와 verify, API/Catalog 기존 role bootstrap을 수행했다.
  테스트를 운영 DB에 실행하거나 row를 직접 수정하지 않았다.
- API/Web 설치 wheel·RECORD, API provider의 정확한 source/wheel/member hash,
  QUERY public/mixed/private wrapper와 Catalog read pin을 호환 set으로 정렬했다.
  QUERY의 수치 owner7f0566c4와 HWPX intent-box 수정본은 바꾸지 않았다.
- 자연 quiescence를 확인한 뒤 worker helper와 영향을 받는 driver/runner를 함께
  교체했다. 실행 중 worker를 강제 종료하거나 인증 파일을 교체하지 않았다.
- 새 material control의 capacity·instruction·네 preset·정확한 Workflow definition과
  `uploaded-material-item@1.0.0` Pack은 기존 owner로 release했다. 실제 권한을 확인한
  운영자와 기존 source policy를 사용했고, 기존 policy의 허용 범위를 넓히지 않았다.
- 새 coordinator unit은 설치·검증됐으나 **INDEX source 인계 전에는 disabled/inactive**다.
  현재 API에 접수된 요청은 영속 보관되며, 서비스 READY를 자동 처리 완료로 간주하지 않는다.

## 설치물 identity

| 구성 | SHA-256 |
| --- | --- |
| API contracts wheel | `b1db6b1e0e08aadcbcc82d94104aa857e3420f89041f6594c8baf7719f516b32` |
| Application API wheel | `759403fd7e32af8be1fc5a0ab2491d0ad2000fd411b90bf18198bc127efce412` |
| Platform wheel | `9b245c55a57228367d6e1ae93fbbafcbac95e28b8f8710123dccc35a978bebee` |
| Web wheel | `a393a58b6990f4460c2fd9910e62acc93b4e7590fb55ed4c0d1d367a222331aa` |

root-owned release/rollback 자료:

- `/var/lib/eom-material-compatible-release-20261106`
- `/var/lib/eom-material-compatible74-rollback-20261106`
- `/var/lib/eom-material-controls-release-20261106`
- `/var/lib/eom-api/deployments/e1df5c8f9925d977028c66e2b99ad056a1ada583.json`

0074 적용 후에는 head73용 platform으로 되돌리거나 새 자료 history를 drop하지 않는다.
배포 실패 시 사용할 **이미 검사한 compatible74 8b4632d8 전체 set**과 해당 provider/
runner/helper 설정을 별도로 준비했다. 이번 배포는 rollback 없이 성공했다.

## 실제 확인과 남은 확인

1. API readiness PASS. 실제 HTTPS 로그인 화면200·새 자료 API의 anonymous401 PASS.
   이것은 인증된 사용자 화면 acceptance의 대체가 아니다.
2. 실제 HTTPS `/studio/assets/material-learning.js` bytes와 설치 파일 SHA 동일 PASS.
   API/Web installed build metadata도 위 source와 일치한다.
3. 직접 작성한 작은 PDF2쪽을 실제 source/intake owner로 접수하고 같은 명령 재전송에서
   동일 run을 재사용했다. 실제 parser sandbox→Document/page Artifact 준비와 typed
   progress read PASS. 별도 Graph/예제용 fake worker 결과는 사용하지 않았다.
4. 이 검증은 **권한을 확인한 owner application 호출**이며 HTTPS 로그인 canary라고
   부르지 않는다. 첫 실제 DISCOVER child가 기존 global Runner에서03번 slot의 실제
   lease/Job을 얻고 RUNNING인 것을06:02 UTC에 확인했다. 아직 모델 결과·등록·공유
   Graph·공통 INDEX 완료의 증거는 아니다.
5. 이어갈 것: 기존 INDEX의 현재 묶음 자연 완료→source consumer 인계→coordinator
   enable/start→동일 canary의 설명/문항·공개 풀이·공유 Graph/INDEX handoff·RAG 읽기·
   DB 조회 및 동일 요청 재조회. 새로운 acceptance identity로 원래 실패를 우회하지 않는다.

## background 보존 및 인계

API/Web 배포 동안 INDEX PID/invocation·설정·수치 runtime/model은 불변이었다. 새 자료
Graph10을 읽을 후속 INDEX source와 unchanged-scope control은 보호 저장소에 준비했다.
05:57 UTC에 기존 INDEX **main에만 SIGINT**를 보내 지원된 stop Event를 설정했다.
이는 현재 preparation/numerical 작업을 끝까지 수행한 뒤 새 묶음을 잡지 않는 graceful
인계 요청이다. `systemctl stop`의4분 강제 종료를 사용하지 않았고 numerical child를
신호로 중단하지 않았다. 실제 unit/원래 Workflow/CPU standby 상태를 대조한 뒤에만
후속 identity/config를 활성화한다. 같은 요청을 새 identity로 복제하지 않는다.

창작 owner는 같은1053 source scope를 유지해 새 prefix로 재기동했다. 마지막 종료 당시
처리 가능한1013개 완료·원본 보류40개였으며 이 숫자는 현재 다시 조회할 대상이다.
보류를 성공으로 바꾸거나4개 슬롯이 바쁜 것처럼 꾸미지 않는다. 기존10분 observer timer는
enabled/active로 보존했다. 목표 종료 뒤에도 background 서비스를 유지한다.

## 증거 파일

상세 로그는 Git에 포함하지 않는다. 이들은 개발·운영 증거 경로이며 runtime authority가 아니다.

- `/tmp/material-learning-compatible-activate-20261106-1.log`
- `/tmp/material-learning-controls-release-20261106-2.log`
- `/tmp/material-learning-live-canary-submit-20261106-1.log`
- `/tmp/material-learning-live-canary-advance-20261106-1.log`부터`-3.log`
- `/tmp/material-learning-postdeploy-read-20261106-2.log`
- `/tmp/material-learning-release-record-20261106-1.log`

source/격리 검증의 범위는[구현 checkpoint](MATERIAL_LEARNING_IMPLEMENTATION_CHECKPOINT.md)를
참조한다. 자료 임시 디렉터리의 초기0700과 읽기 전용 관측 스크립트의 열 이름 오류는
해당 operator helper에서 바로잡았으며 초기 실패 로그도 보존했다. 모델/원본/운영 history를
오류 처리 편의상 수정하지 않았다.
