# 공용 슬롯·프리셋별 모델 설정 릴리스

2026-11-12 UTC. 소스 구현/격리 검증 기록이며 운영 반영 증거가 아니다.
설계: [공용 슬롯과 모델 설정](../architecture/SHARED_CODEX_SLOTS_AND_PRESET_MODEL_SETTINGS.md).

## 사용자 동작

- `관리자 설정 → 모델·추론 설정`: 현재 프리셋을 고른 뒤 역할별 모델과 추론 깊이를
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
   다른 draft 또는 무관한 current가 있으면 충돌을 보고하고 덮어쓰지 않는다.
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
