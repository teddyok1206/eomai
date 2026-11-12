# 공용 슬롯·프리셋별 모델 설정 릴리스

2026-11-12 UTC. 소스 검증부터 운영 발행까지 시점별 기록을 보존한다.
최신 상태(09:25 UTC): **`e03af582` 호환 운영 배포 및 20개 프리셋 공용 슬롯 정책 활성화 완료**.
사용자의 관리자 화면·새 채팅 답변 확인과 서버 COMPLETED 대조도 완료했다.
모델 변경 후 신규 작업 적용 canary는 별도 확인 대상이다.
설계: [공용 슬롯과 모델 설정](../architecture/SHARED_CODEX_SLOTS_AND_PRESET_MODEL_SETTINGS.md).

## 사용자 동작

- `관리자 설정 → 모델·생각하는 깊이`: 현재 프리셋을 고른 뒤 역할별 모델과 추론 깊이를
  편집하고 기존 `검증 → 적용` 절차를 사용한다. 출제·검토뿐 아니라 문의, 자료 검토,
  자료 학습의 support-only 프리셋도 대상이다. 전역 모델 하나로 덮어쓰지 않는다.
- 같은 화면의 `ChatGPT` 카드에서 채팅 모델·깊이를 변경한다. 새 설정은 다음 질문부터
  적용된다. 진행 중 답변과 과거 결과 조회는 원래 설정/실행 ticket을 보존한다.
- ChatGPT는 기존06번을 유지한다. 공용 capacity로 전환한 일반 작업은01–05 중
  사용 가능하고 해당 모델이 검증된 빈 슬롯을 순환 탐색한다. 모델을 몰래 대체하지 않는다.
- 계정 로그인, 상태·사용량 새로고침, 해당 계정 모델 검증은 정확한 대상 슬롯을
  조작하는 관리 작업이다. 이런 작업까지 임의의 빈 슬롯으로 보내지 않는다.

## 설치·활성화 순서

1. 검증된 source commit/tree를 고정하고 platform/API/Web/Catalog/runner/채팅 owner·worker의
   호환 wheel과 롤백 묶음을 준비한다. 같은 package version만으로 같은 빌드라고 판단하지
   않는다. INDEX/QUERY 등 별도 실행의 runtime pin을 바꾸거나 재시작하지 않는다.
2. 변경 대상의 진행 중 claim/lease/채팅 turn을 확인하고 기존 배포 절차로 안전한 시점을
   잡는다. 실행 중 plan/cohort의 capacity/preset/Graph pin을 DB에서 바꾸지 않는다.
3. 기존 migration owner 절차로 `0077 → 0078 → 0079`를 적용한다. release-operator
   context1.24와 `MIGRATION_UPGRADE_0079_FROM_0077` 또는 정확한78 predecessor의
   `MIGRATION_UPGRADE_0079`를 사용한다. 과거 callback을 최신 head로 재해석하지 않는다.
4. 기존 worker runtime 설치·검증 절차로 polkit과 추가 고정 unit11개를 설치한다.
   기존 timeout unit9개를 재사용하므로20개를 중복 신설하지 않는다. root 소유/0644/
   내용 hash와 실제 `systemd-analyze verify`를 확인한다. 공용 capacity를 먼저 발행하지 않는다.
5. API와 채팅 owner의 기존 runtime-role 준비 절차를 각각 실행한다. API는 작은 설정
   revision INSERT/current pointer UPDATE를, 채팅 owner는 설정 SELECT만 갖는다.
   worker에게 DB/NAS 권한을 주지 않는다.
6. 호환 API/backend, 채팅 owner·worker, Web을 기존 릴리스 절차로 배포한다. 채팅 모델
   설정은 selected native runtime과 기존 textbook-RAG protocol4를 전제로 한다.
   이전 설치본에서 설정이 없으면 기존 설치 기본값을 그대로 유지한다.
7. 전환할 각 논리 프리셋의 **정확한 현재 released revision**을 inventory한다. 설치된
   Orchestrator 소유자 CLI `eomctl control-plane shared-slots release --source-commit <40hex>`에
   `--baseline-revision <execpresetrev_...>`를 반복해 전달한다. 실제 명령 계층은
   `eomctl control-plane --help`로 확인한다. 보호된 기존 owner identity와 실제 관리자 인증이
   필요하며 환경파일/계정 비밀번호를 변경하거나 보관하지 않는다.
8. 이 application use case는 unit 검사 → 현재 predecessor 잠금 → 공용 capacity/draft 준비
   → 기존 Artifact publisher → 평가 기록 → 기존 preset release를 수행한다. 프롬프트·
   모델·retrieval 규칙은 이 전환에서 변경하지 않는다. 모델 호출 수는0이며 출제 품질 PASS를
   뜻하지 않는다. 중단 뒤 동일 predecessor로 재개하면 정확히 발행된 successor를 재사용한다.
   같은 전환 정책의 draft만 재사용한다. 무관한 미발행 draft는 보존하며 현재 발행
   predecessor에서 새 revision을 추가한다. 동일 정책 draft 중복이나 무관한 current는
   충돌로 거부한다.
9. 관리자 화면과 설치 manifest/current 정책을 확인한다. 승인된 bounded canary로
   (a) 일반 작업의 다른 빈 슬롯 배정과 실제 unit/timeout, (b) 프리셋별 모델 변경의 신규 실행 pin,
   (c) 채팅 모델 변경 후 새 질문1회와 COMPLETED를 확인한다. 운영 성공은 이 증거로만 닫는다.

신규 material-learning child workflow는 설치 safety baseline과 호환되는 current 설정만
선택한다. 이미 실행 중인 workflow와 고정된 과거 creative cohort/production plan은 변경되지
않는다. 그 실행의 모델을 바꾸려면 원래 owner의 명시적인 successor/새 cohort 절차를 사용한다.

## 실패와 롤백

- 호환성/설치 unit/권한/포인터 검사가 실패하면 새 공용 작업을 열지 않는다. 과거 FAILED
  기록을 성공으로 바꾸거나 새 identity로 우회하지 않는다.
- 채팅 설정 저장은 예상 버전과 동일 요청 key를 사용한다. 전송 결과가 불명확하면 같은
  key로 replay하며, 새로운 key로 재저장하지 않는다. slot06의 인증은 변경하지 않는다.
- 새 immutable history가 생긴 뒤78/79 migration downgrade는 거부한다. 자동 downgrade나
  history DELETE를 rollback으로 사용하지 않는다. 기존 계약을 지원하는 호환 wheel/정책
  successor를 선택하고 새 claim만 안전하게 제한한다.
- 전체 작업을 임의 재시작하지 않는다. GPU/기존 worker runtime pin과 정본 Artifact는 유지한다.

## 검증과 남은 운영 증거

격리 환경에서 실제 PostgreSQL 동시 claim/동일 요청 replay/설정 CAS/발행 및 재발행,
모든 일반 역할의 슬롯 후보, 채팅06 제외, 잘못된 인증/모델/소진 후보 제외, GPU 역할 한도,
고정 unit timeout20조합, 기존 plan 보존을 검사한다. 모든 DB mutation은 marker가 검증된
disposable DB에 한정하며 운영 DB를 pytest 대상으로 사용하지 않는다.

관리자 두 편집 화면은 실제 Playwright 브라우저에서 합성 응답으로 검사한다. API의 관리자
권한·재인증·ETag·멱등 key·Web CSRF와 source 밖 non-editable wheel import/schema 포함도
별도 검사한다. 이 검사는 실제 운영 모델 실행/화면의 대체 증거가 아니다.

검증 중 확인한 invocation 문제도 숨기지 않는다. 서로 다른 시각을 사용하는 기존 DB
fixture를 한 DB에 이어 붙이면 만료된 합성 auth snapshot이 남아 모델 admission이 실패한다.
기존 preset 검사는 별도의 fresh disposable DB에서, 역사적 시각의 shared/creative 검사는
해당 suite의 독립 DB에서 실행한다. 이미지 모델 전용 테스트는 API 환경의 선택적 PIL
dependency 부재 때문에 무차별 glob에 포함하지 않고 해당 환경에서 별도로 실행한다.

변경 파일의 scoped mypy와 formatter/linter를 실행한다. 전체 import closure의 기존
WorkflowRequest/MaterialLearningWorkflowRequest union narrowing 문제는 별도 유지보수
항목이며, 범위를 넓혀 이 릴리스에서 무관한 authoring/similarity 로직을 바꾸지 않는다.

실제 운영 activation, root-owned 설치 unit 검증, HTTPS 관리자 화면 및 live model canary는
**PENDING**이다. 이 문서를 근거로 이미 운영 전환됐다고 보고하지 않는다.

운영 준비에서 `/etc/polkit-1/rules.d`는 실행 owner에게 읽기 권한이 없음을 확인했다.
root 배포 검사는 `require_shared_worker_deployment`로 polkit와11개 unit를 확인하고,
일반 owner의 발행 검사는 `require_shared_worker_units`로 고정 unit를 확인한다.
디렉터리 권한/그룹을 넓히지 않으며 설치 시 polkit hash 검증을 생략하지 않는다.
최초 발행 시도는 로그인/DB mutation 전 PermissionError로 종료됐고 기록을 보존한다.

### 배포 전 GUI 원칙 검토

기존 Scientific Workbench 디자인 시스템과 GUI 원칙 재점검 문서를 대조했다.
공통 입력/버튼/카드, 한국어 역할명, native details와 키보드 포커스를 유지한다.
변경 불가능한 revision·capacity·protocol·설명은 접힌 ‘변경하지 않는 설정 정보’로
옮겼다. 편집 대상은 모델·생각하는 깊이뿐이며 비활성 metadata를 편집 가능하게 만들지
않는다. ChatGPT를 포함하므로 상위 제목은 ‘모델·생각하는 깊이’로 정리했다.
실제 Chromium 1440/390/320px 화면·동일 요청 재전송·중복 클릭·로그아웃 후 늦은 응답
검사를 사용하고 합성 screenshot도 육안 검토했다. 새 프레임워크/스타일 계층은 없다.

### 이번 소스 검증 결과

| 범위 | 결과 |
| --- | --- |
| 슬롯·채팅·프리셋·자료 학습·기존 실행·release-operator 통합 회귀 | 2,354 PASS |
| 검토 모델 successor의 dispatch/교과서 근거 commit 및 이전 검토 계약 | 41 PASS |
| API·Web 계약/관리자 권한/실제 브라우저 편집 화면 | 169 PASS |
| fresh disposable DB 공용 claim/동시 준비·발행·재발행/채팅 설정 CAS | 34 PASS |
| 별도 fresh DB의 기존 프리셋 모델 검증 저장·재전송 | 12 PASS |
| 별도 fresh DB의 기존 채팅 저장·06 예약·지원 라우팅 | 78 PASS |
| 변경 Python 소스51개 scoped mypy, formatter/linter, shell syntax, diff whitespace | PASS |

각 행은 범위가 겹칠 수 있어 단순 합산하지 않는다. non-editable 플랫폼 wheel의 실제
설치/import와 schema 포함 검사는 통합 회귀에 포함된다. 브라우저 검사는 별도 합성 응답이며
운영 모델을 사용하지 않았다. disposable DB4개는 검사 후 공식 cleanup으로 제거했고,
검증 결과 로그만 ignored staging에 보존했다. 운영 DB·인증·과거 실패·기존 실행은
변경하지 않았다. 소스 기준선은 작업 시작 HEAD `3da07096`이며 아직 commit/deploy 전이다.

## 운영 배포 체크포인트 — 2026-11-12 07:10 UTC

위 ‘commit/deploy 전’은 소스 검증 당시 기록이다. 후속 운영 상태는 다음과 같다.

- 기능 commit `20c767b2c4114ddafa1ae2d89fbacfe429b16b88`, 권한 분리 후속
  `41efd26efd06fece9aa470ceb14e514696cc90f6`.
- 최종 API/platform/Web/Catalog/runner/채팅 설치 source는 `41efd26e`.
  자료 학습 coordinator도 이 설치본으로 자연 종료 후 교체했다. 기존 요청·child·cohort의
  preset/Graph pin은 변경하지 않았다.
- DB `0077 → 0078 → 0079`: 보호된 release operator의 정확한 callback으로 적용하고
  verify, API/Catalog/HWPX 역할 조정 PASS. 후속41 배포에서는 migration 재실행 없음.
- polkit와11개 신규 고정 unit의 소유권·mode·hash 및 systemd 검증 PASS.
  실제 `eom-workflow-runner` OS identity에서 새 설치본의 unit preflight PASS.
  정책 파일 접근 권한/그룹, worker 인증, 기본 모델은 변경하지 않았다.
- 전체 Web517 PASS(실제 합성 Chromium 포함), 권한 후속 회귀295 PASS, scoped mypy와
  formatter/linter PASS. 처음 전체 Web 검사에서 옛 제목을 기대한2개 assertion을
  변경된 UI 제목으로 고친 후 전체 재실행했다.
- HTTPS 로그인200, API READY, 배포된 HTML/JS/CSS5개가 최종 wheel bytes와 일치.
  채팅 설정·프리셋 관리자 endpoint의 anonymous 조회는401.
  API/Web/채팅 owner·worker/QUERY/runner/자료 학습·창작 coordinator active 확인.
- QUERY 설치 source `11d826d2`와 수치 runtime은 유지하면서 API provider pin만 정식
  호환 묶음으로 갱신했다. INDEX는 작업 전부터 failed/PID0였으며 동일 InvocationID와
  설정을 보존했다. 이번 릴리스를 GPU 복구 성공으로 보고하지 않는다.
- 보호된 실행/이전 wheel·설정 기록:
  `/var/lib/eom-shared-settings-release-20261112`,
  `/var/lib/eom-shared-settings-release-r2-20261112`.

**정책 활성화는 아직 PENDING**이다. 최초 시도는 일반 owner가 root-only polkit 경로를
읽으려다 로그인·DB 변경 전에 종료됐다. 책임 분리 후속 설치/실제 identity 검증 후
`EOM → 2번 model-settings-release`에서 실제 guiadmin 로그인을 기다리고 있다.
동일20개 exact baseline을 official shared-slots release use case로 발행하며,
인증 입력 전에는 공용 capacity/프리셋 successor를 발행했다고 주장하지 않는다.
실제 인증 관리자 화면, 새 채팅 응답 및 선택 설정 적용 canary도 별도 확인 대상이다.

## 활성화 사전 점검 후속 — 2026-11-12

실제 관리자 인증은 성공했으나 `CONTROL_SHARED_DRAFT_CONFLICT`로 전환 준비 transaction이
rollback됐다. 운영 조회에서 `knowledge-grounded-item`의 10월10일 미발행 모델 초안1개가
확인됐고, 새 shared capacity/후속 preset은 아직 없다. 이 초안을 삭제하거나 발행하지 않는다.
전환 owner가 정확한 현재 predecessor의 정책과 일치하는 전환 초안만 재사용하도록 수정했다.
과거 초안 보존·동시4회 준비·같은 요청 재개·일치 초안 중복 거부를 fresh disposable DB에서
검증했다(관련 suite36 PASS). 슬롯/모델/unit focused340 PASS, scoped mypy/ruff PASS.

모델 사전 조회에서는 binding이 READY여도 최근 native catalog가 만료된 경우를 확인했다.
새 인증을 요청하기 전에 기존 상태·사용량 OBSERVE로 갱신하며, 만료 기록을 유효하다고
꾸미거나 모델을 자동 대체하지 않는다. 이 후속 source도 운영 적용/정책 발행과 구분한다.

### 후속 운영 반영

- commit/설치 source `e03af582f129c0bd5ad2b300cd600c8edca1d685`.
  API/platform/Web와 관련 owner를 같은 호환 절차로 반영했다. migration79는 그대로다.
- HTTPS 정적 파일5개와 배포 wheel 일치, 익명 관리자 endpoint401,
  API/Web/채팅 owner·worker/QUERY/runner/자료 학습 서비스 active 확인.
  ChatGPT06 예약·기본 모델·인증은 유지했다.
- 새 테스트용 disposable DB는 공식 cleanup으로 제거했다. 실패한 최초 invocation과
  실제 초안 충돌 기록은 보존한다. 운영 DB/Artifact를 테스트 정리 대상으로 쓰지 않았다.
- 정책 current는 아직 기존20개이며 shared capacity는0개다. 실제 로그인은 통과했으나
  초안 충돌 뒤 실행 세션이 종료됐다. 이번 수정본은 설치됐지만 정책 발행 완료는 아니다.
- 현재 binding은 READY지만 native 모델 목록의 OBSERVE가 오래되어 모델 선택용
  후보가 비어 있다. 1번과6번의 공식 상태·사용량 새로고침을 요청했다. 갱신 확인 후
  실제 관리자 인증으로 동일20개 baseline의 전환을 이어간다. 새 모델 호출은 아직0회다.
- 보호된 배포 기록: `/var/lib/eom-shared-settings-release-r3-20261112`.
  최신 읽기 검증: ignored `staging/shared-settings-live-smoke-r3-20261112.json`.
  INDEX는 이전과 같은 failed 상태/InvocationID를 보존했으며 이번 작업 범위 밖이다.

## 공용 모델 준비 완료 — 2026-11-12 후속

1~6번의 실제 OBSERVE 뒤 일반 슬롯에 남은 누락은 `gpt-5.6-terra/medium`이었다.
18개 프리셋은 준비됐지만 customer-support와 item-inference-transfer-comparison-axes는
이 조합을 요구했다. 설정을 임의로 high로 바꾸거나 채팅06의 모델 검증을 빌려 쓰지 않았다.

- 기존 scoped compatibility owner로 슬롯05의 medium·xhigh를 실제 각1회 실행했다.
  2/2 PASS, 모델 호출2회. 기존 xhigh를 포함한 이유는 tested-slot 정책 교체 때 기존
  허용 조합을 보존하기 위해서다. 기출/문항 내용은 사용하지 않은 합성 진단이다.
- 정식 committed 보고서:
  `artifact_1dd460fff10d4a3dae790babdd3b11b4` /
  `rev_529668c1911a41618a0cf1fff8bd39be` / `report.json`,
  SHA `sha256:7ff6fe03290e97528de31e8f873940e7705aec35442444da0a061c4c2b1e42d7`.
- 기존 정책 installer로 exact predecessor를 검증해 설치했다. 기존 모든 pair 보존과
  추가값이 `(05, gpt-5.6-terra, medium)` 하나뿐임을 설치 전에 확인했다.
  현재 정책 SHA `sha256:a7be9176870007c7020914bdeaf405d885f0020c5f3b87482139538cb947e171`.
  이전 정책은 installer의 hash별 복구 사본으로 보존한다. Codex 바이너리·계정 인증·
  프리셋 모델·채팅06 모델·GPU runtime은 바꾸지 않았다.
- 슬롯05의 새 snapshot은 기존 공식 기록 함수를 통해 추가했다. 이후 실제 조회에서
  20개 baseline 모두 missing model/effort=0을 확인했다.
- 근거 경로: `/var/lib/eom-shared-settings-medium-proof-20261112` 및 ignored
  `staging/shared-settings-model-preflight-ready-20261112.json`.
- 아직 공용 capacity 활성화 PASS는 아니다. 모델 준비 완료 후
  `EOM → 2번 model-settings-release`에서 실제 관리자 발행 인증을 기다리는 단계다.

## 운영 정책 활성화 완료 — 2026-11-12 09:21 UTC

위 인증 대기·미활성 상태는 각 시점의 기록이다. 실제 guiadmin 인증 후 설치된 official
shared-slots use case가 성공했고, 별도 읽기 검증으로 current pointers를 다시 확인했다.

- 20/20 논리 프리셋의 current는 새 `worker-capacity-policy/1.7`에 연결됐다.
  capacity revision: `capacityrev_f145d972c88c4c74a1c698af873e3bcc`.
- 7개 실행 pool 모두 슬롯01–05를 후보로 갖는다. 모델/추론 깊이·인증·사용량과
  점유 조건을 통과하는 빈 슬롯을 고르며 host4, 슬롯당1, GPU1 제한은 그대로다.
  ChatGPT 전용06은 일반 pool에 포함되지 않는다.
- 각 exact predecessor와 successor를 canonical executable policy hash로 대조했다.
  capacity 외의 모델·후보 순서·프롬프트/Bundle·retrieval·timeout은 동일하다.
  10월10일의 무관한 미발행 초안도 DRAFT 상태로 보존됐다.
- 과거 plan/cohort pin과 실패 이력은 수정하지 않았다. 신규 실행부터 current 공용
  프리셋을 선택하며 이미 고정된 과거 실행을 암묵적으로 전환하지 않는다.
- 공용 설정 발행 자체의 모델 호출은0회다. 앞 절의 compatibility 실제 진단2회와 구분한다.
- HTTPS asset5개와 운영 wheel 일치, 익명 관리자 읽기401, API/Web/채팅 owner·worker/
  QUERY/runner/자료 학습 서비스 active를 다시 확인했다. INDEX의 기존 failed 상태는
  그대로이며 이 릴리스의 성공 범위에 포함하지 않는다.
- 보호된 최종 발행 증거:
  `/var/lib/eom-shared-settings-release-r3-20261112/controls-activated.json`.
  기존 `activated.json`의 당시 controls=PENDING은 덮어쓰지 않았다.
  ignored 읽기 증거는 `staging/shared-settings-activated-smoke-20261112.json` 및
  `staging/shared-settings-activation-evidence-20261112.log`다.

GUI 원칙 검토·합성 Chromium 검사·배포 assets 확인은 완료다. 실제 사용자의 관리자 화면
확인과 새 채팅 COMPLETED, 모델 변경 후 신규 turn/일반 작업 pin canary는 아직 기록되지
않았으며, 위 자동 검증을 이 수동/실행 확인의 대체 증거로 쓰지 않는다.

## 사용자 화면·실제 채팅 확인 — 2026-11-12 09:25 UTC

- 사용자가 관리자 화면의 프리셋별 설정·ChatGPT 카드가 잘 보이고 새 채팅 답변도
  도착했다고 확인했다. 관리자 화면과 실제 답변 확인은 PASS로 기록한다.
- 같은 시점의 새 turn `chatturn_20b7e859a60d6cbe450dc803f396b18d`는
  09:25:15.630891 UTC에 시작해 09:25:26.718771 UTC에 `COMPLETED`로 종료했다.
  failure code는 없으며 서버 처리 시간은 약11.1초다. 과거 실패 대화는 재실행하지 않았다.
- 읽기 전용 후속 검증에서 채팅06 예약, 배포 HTTPS asset5개, 익명 관리자 접근 거부,
  서비스 상태를 재확인했다. 증거는 ignored
  `staging/shared-settings-user-canary-smoke-20261112.json`이다.
- 모델 설정을 실제 변경한 뒤 신규 작업/turn에 적용하는 운영 canary는 별도로
  실행하지 않았다. 현재 설정 유지 상태의 실제 채팅 성공과 구분한다.
