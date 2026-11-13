# 실제 사용자 위험 수정 결과

기준은 [11월 13일 위험 검토](../architecture/REAL_USER_FAILURE_RISK_REVIEW_2026-11-13.md)의
U01–U06이다. 사용자 수정 요청 후 기존 담당 모듈에서 고쳤고, 후속 운영 배포도 완료했다.
출발 source는 `ab930a52`이며 정본·실패 이력·현재 슬롯/GPU·인증 설정은 변경하지 않았다.

위 상태는 소스 검증 시점의 기록이다. 이후 사용자의 운영 배포 승인에 따른 결과는
아래 **운영 반영** 절에 구분해 기록했다.

## 수정 결과

| 항목 | 수정 | 보존한 경계 |
| --- | --- | --- |
| U01 자료 선택과 늦은 응답 | workflow/선택 sequence/owner를 POST 전·응답·오류·finally에서 확인하고 다른 문서의 결과 링크를 만들지 않음 | 원래 요청 key·결과, 32개 bounded mutation 참조 |
| U02 Excel 구조 상한 | 공통 layout iterator가 준비/조회/저장에서 동일한 10,000 section 한도를 검사, 원본 연결 전에 명확히 거절 | released V1 의미·행 한도·기존 Artifact/receipt |
| U03 다운로드 메모리 | chunk 수신·SHA/길이/prefix 검사 후 bounded spool, 큰 응답 최대 2개, 송신·취소 시 정리 | 기존 권한·해시 검증, 작은 bytes 응답 호환 |
| U04 긴 변환 응답 | timeout 뒤 같은 intent/set GET을 한 번 확인하고 실제 PROCESSING/STARTED 등일 때만 진행 상태 반환 | 기존 API claim/threadpool 처리 소유권, 자동 PUT 재전송 없음 |
| U05 새로고침·재로그인 복구 | owner별 tab storage에 작은 ID/key/fingerprint만 보관, 재진입은 같은 상태 GET/필요 파일 전송 | 파일 bytes·자연어 지시·credential 저장 없음, domain 실패 보존 |
| U06 hwp 확장자의 HWPX | 새 intent 전에 header를 확인해 제출명에 `.hwpx` 추가, 두 이름을 화면에 안내 | 원본 File bytes/이름·SHA, strict Catalog HWPX 검사 |

U06 예시는 `교재.hwp` → 제출명 `교재.hwp.hwpx`다. 저장된 `original_filename`은 제출명이다.
별도의 원래 파일명 필드가 추가된 것은 아니며 원래 이름 전체는 제출명에 남긴다.
동결된 계약의 확장자 조건을 고치거나 임의 ZIP을 HWPX로 승인하지 않는다.

업로드 polling은 최대 60회이며, 그 뒤 자동 조회만 멈추고 원래 요청은 보존한다.
사용자는 같은 요청을 수동 재확인할 수 있다. terminal 실패의 로컬 재개 참조를 버릴 때도
서버 상태를 다시 읽고 명시적으로 확인한다. 과거 FAILED를 성공으로 바꾸지 않는다.

## 단순성과 설계 원칙

새 DB·queue·registry·worker protocol·released schema 변경은 없다. 브라우저의 결과 소유권,
기존 intent의 조회, Catalog layout, Web download adapter에서 책임을 닫았다.
AnyIO는 기존 Web lock에 이미 설치된 `4.14.2`를 직접 의존성으로 명시했다. 취소된 ASGI
scope에서도 socket close를 shield하고 별도 미추적 cleanup task를 만들지 않기 위해서다.
새 라이브러리를 설치하거나 다른 runtime pin을 바꾸지는 않았다.

독립 재검토에서 추가로 발견한 두 문제도 회귀로 고쳤다.

- 예전 GET이 pending을 지우는 동안 새 제출의 비동기 fingerprint 계산이 끝나 새 요청을
  만들 수 있었다. 제출 시작 시 기존 조회 epoch를 먼저 무효화한다.
- AnyIO 취소 scope에서 upstream close가 중단될 수 있었다. 5초 제한의 shielded cleanup과
  receiving/capacity-wait/downstream 취소 검증을 추가했다.

## 운영 관측 항목의 처리

기존 INDEX는 같은 PID/invocation으로 실행 중이었다. 재관측에서 anon 사용량은 약
1.60GB로 감소했고 OOM/OOM-kill은 0, 당시 pressure 평균은 0이었다. file cache는 회수
가능하다. 이 증거만으로 누수라고 단정하거나 cache/runtime을 바꾸지 않았다.
Catalog 동시 intake도 실제 정상 사용자 부하에서 장애 한계를 재현한 것이 아니므로 새
global queue/gate를 추가하지 않았다. 고정 Web TTL·pre-auth burst·readiness 의미,
검토된 ORM composition cycle은 정책/기존 부채로 유지한다.

이 항목들은 소프트웨어 결함으로 확인된 U01–U06과 다르다. 임의로 설정을 바꾸는 대신
기존 관측 근거와 한계를 남겼다.

## 검증

- 전체 Web + 관련 workbook/layout/Office intake/의존성/API 집중 묶음: **709 PASS**,
  기존 실제 Playwright opt-in 15 SKIP. 동일 묶음의 반복 실행 수를 합산하지 않았다.
- mypy: 변경 핵심 9개 source files PASS. Ruff lint/format·diff PASS.
  wire audit는 정본 1,375개·참조 11,789개·mirror 1,026개 PASS.
- 실제 모델·GPU·운영 DB 쓰기·사용자 실패 로그인·서비스 재시작: 0.
- 실제 Playwright/Hancom와 disposable PostgreSQL opt-in은 소스 검증과 구분한다.
  DB 구조/transaction/lease 변경은 없으며 기존 application의 권한·멱등성 owner를 유지한다.

합성 동시 다운로드 2개의 파일 크기를 각각 4MiB → 16MiB로 늘려 비교했다.
`tracemalloc` peak는 각각 3,227,717바이트 / 2,806,016바이트였고 전달 byte 수는 모두
일치했다. Python heap이 전체 파일 크기에 비례해 증가하지 않는 것을 확인한 것이며,
프로세스 전체 RSS나 운영 처리량의 측정값은 아니다. source/HTTP stream은 합성이고
실제 NAS 파일·모델·GPU를 사용하지 않았다.

수정 commit `a9dbdf3a2551739b4b5d1a792bbb1f2466534190`의 clean tree에서 공식
`scripts/web_gui/build_release.sh`도 실행했다. package inventory/RECORD와 실제 Web
interpreter의 isolated import, 별도 venv 설치 시뮬레이션 **82 files PASS**다.
운영 환경에는 설치하지 않았다.

Web wheel SHA-256:
`7b67011d2e78b6874b603d40b2940fde24c1c1c99d6a985d5ca7a962b1c3869e`.
API/platform과의 호환 배포는 별도로 필요하며 Web wheel 성공만으로 운영 반영을 선언하지 않는다.

설계와 세부 검증 위치:

- [다운로드 자원 경계](../architecture/WEB_DOWNLOAD_RESOURCE_BOUNDARY.md)
- [업로드 이어가기](../architecture/DOCUMENT_REVIEW_UPLOAD_CONTINUATION.md)
- [브라우저 복구](../architecture/DOCUMENT_REVIEW_BROWSER_RECOVERY.md)
- [Excel 표준 가져오기](../architecture/EXCEL_STANDARD_WORKBOOK_IMPORT.md)

이후 운영 반영은 호환 API/platform/Web release로 진행하며 현재 GPU 수치 설치본·owner
실행 pin과 기존 작업을 보존한다. 이번 소스 검증을 운영 사용자 acceptance로 대신하지 않는다.

## 운영 반영

2026-11-13 사용자 배포 승인 후 실제 설치 source를
`c8a851fef5075db071577bb208d80425b693898c`로 전환했다. 이는 a9dbdf3a 수정과
검증 문서가 포함된 clean commit이다. 운영 DB head는 `20261112_0079`로 유지하며
DDL·비밀번호·모델 선택·슬롯 인증·기존 실패/문항/Graph/벡터를 변경하지 않았다.

| 구성요소 | 실제 반영 |
| --- | --- |
| API·API contracts·공유 platform/Catalog/Runner | c8a851fe의 세 wheel |
| Web | c8a851fe, 실제 eom-web identity의 RECORD 82 files 검증 PASS |
| Catalog·Workflow·채팅 release source | 실제 코드 source에 맞춰 c8a851fe, 기존 unit/model/native/auth는 보존 |
| QUERY | 기존 owner 11d826d2 보존; API provider commit/wheel/member hash와 config pin만 호환 갱신 |
| 창작 등록 owner | 기존 a7fc195d unit/env 유지, SIGINT 정상 drain 후 같은 설정으로 재개 |
| INDEX·controller | 47fc5366 / a7fc195d 유지, 기존 PID 203375 및 invocation ae8aa922… 보존 |
| 자료 학습 | 기존 PID 3392845 및 invocation ddd00986…·설정 보존 |

실제 배포 wheel SHA-256:

- platform: `fe7dd8cc4255f64412dba6c31e066cc961cef077bd521e9508d92ff8699a88ce`
- API: `d9e84c12e93e8e14a0fab9b8a5ea52e912b4e6c31e8cd6d3dde8582deadc0ab3`
- API contracts: `b72e0bf4f484670f2c228ef429d3139fd2c4525a8212ca7007ba43137401dec6`
- Web: `99dc459fa05adb0b11e403a5b5fc8a8bd2f771c7f267c93e781d8e0e5179f11a`

배포 당시 GPU controller가 실행 중이어서 종료를 기다렸다. 기존 worker lease·실행/대기
command·HWPX·채팅·native transient와 Catalog RPC를 확인한 뒤 전환했다. shared wheel과
Web 설치를 먼저 끝내고 native-idle을 다시 검사한 다음 config/unit 파일 교체와
daemon-reload를 인접 실행했다. INDEX를 위한 가짜 작업·GPU mutex pause·재핀은 사용하지 않았다.
관측 창의 idle 확인을 전역 원자적 admission lock이 있었다는 뜻으로 확대하지 않는다.

Catalog/API → 채팅 worker → 채팅 owner/private socket → QUERY → HWPX/Web →
broker/runner → 원래 창작 등록 owner 순서로 시작했다. 배포 후 관련 서비스 14개 active,
Web/API/INDEX/material의 `NeedDaemonReload=no`를 확인했다. Web 재시작으로 기존
브라우저 세션이 종료될 수 있으며, 실제 사용자 재로그인 검증과 별개다.

### 배포 중 오류와 복구

첫 활성화에서 API/platform 설치·파일 검증 후 Web 설치 helper에 Path 대신 str을 넘겨
`AttributeError`가 발생했다. 이 실패 로그·첫 operator bytes·시작/정지 기록을 보존했다.
설치된 API bytes와 c8a851fe source, 아직 변경되지 않은 config와 서비스 정지를 다시
확인한 뒤 `resume-api-installed` 단계로 **API 재설치 없이** Web 설치부터 이어갔다.
기존 실패를 성공으로 덮거나 자동 rollback하지 않았다.

pip는 이전 uninstall 임시 폴더 일부를 제거하지 못했다는 경고를 냈다. 실행 대상 package
bytes·RECORD와 두 환경의 `pip check`는 정상이다. 배포 중 이를 임의 삭제하지 않았다.

### 배포 후 확인

- 실제 API health smoke / Web smoke PASS, API READY.
- 실제 HTTPS 로그인 화면과 app.js·신규 document-review-pending.js·Excel import JS·
  한국어 vocabulary가 새 wheel bytes와 일치했다.
- 익명 session 및 신규 단일 intent/paired set GET 접근은 401이다. 없는 route나 502로
  인증 차단을 대신하지 않는다.
- 실제 설치된 격리 Web interpreter에서 2MiB 합성 download를 검증된 spool로 받아
  ASGI 송신·종료·permit 회수 PASS. 실제 네트워크/모델/DB 사용이 없는 검사다.
- API/Web 환경 모두 `No broken requirements found`.
- INDEX/자료 학습 PID·invocation·관련 파일 hash는 전환 전후 같았다. 배포 후 INDEX의
  source-read 단계 이벤트와 창작 owner의 VERIFIED/PROCESSING 진행을 관찰했다.
  관측한 창작 verified_count 증가를 새 문항/새 모델 호출 수로 해석하지 않는다.
- 이번 배포가 새 GPU shard/전체 corpus 완료 또는 실제 사용자 파일/Hancom 품질을
  검증한 것은 아니다. 인증된 사용자 화면 확인은 `PENDING_REAL_USER_LOGIN`으로 남긴다.

정본 배포·복구 기록: `/var/lib/eom-real-user-risk-release-20261113/`의 prepared.json,
actual-rollback.json, activation-started.json, stopped.json, activation-resume-requested.json,
installed.json, activated.json, postdeploy.json 및 before/after config. 보호된 operator는
`/usr/local/libexec/eom-real-user-risk-release-20261113/`에 버전별로 보존한다.
기존0079 DB를 유지한 채 exact 이전 wheel/config로 복구할 수 있으며, 기록 삭제나 DB
다운그레이드를 복구 절차로 사용하지 않는다.
