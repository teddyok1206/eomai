# 개발 검증과 운영 배포

## 작업 시작

`AGENTS.md`와 관련 주제만 읽고 `git status --short --branch`로 다른 작업을 보존한다.
파일 탐색은 `rg --files`, symbol/호출자는 `rg -n`을 쓴다. source의 존재·테스트 PASS·
설치 wheel·현재 활성 설정·실제 사용자 성공은 구분해 기록한다.

Python은 component에 지정된 Conda interpreter를 명시한다. 기본 API 개발 환경은
`/srv/eom/conda/envs/eom-api/bin/python`이다. 이 환경에 설치된 non-editable package가
현재 수정 source와 다를 수 있으므로 source 검증의 module search path를 명시한다.
`pyproject.toml`의 mypy_path/package 검색 경로와 기존 해당 suite 실행 방법을 확인하고,
설치본 테스트를 source 테스트라고 보고하지 않는다.

## 검증 선택

계약/형식은 schema·Pydantic·resource mirror·canonical serialization을 검사한다.
state/claim/중단/replay 변경은 해당 unit과 disposable PostgreSQL을 함께 쓴다.
filesystem/설치 identity 변경은 실제 격리 설치본 negative 검사도 필요하다.
UI 변경은 실제 route/module/DOM와 session/media/download 경계를 확인한다.

```bash
/srv/eom/conda/envs/eom-api/bin/python -B -m ruff check tests/unit/test_code_context_navigation.py
/srv/eom/conda/envs/eom-api/bin/python -B -m pytest -q tests/unit/test_code_context_navigation.py
```

이 명령은 문맥 파일 검증 예시다. core 코드는 formatter/linter/type checker와 영향받는
focused tests를 별도로 실행한다. live 모델·GPU·Slack·권한 fault 검사는 기존 opt-in 경계를
따른다. 테스트 개수를 늘리는 것이 실제 GUI/문서 acceptance의 대체 증거는 아니다.

DB mutation 검사는 `scripts/api/testdb_prepare.sh` → `testdb_run.sh` →
`testdb_cleanup.sh`의 정확한 disposable identity를 따른다. 운영 URL로 fallback하거나
marker/manifest를 고쳐 통과시키지 않는다. 오류 난 테스트의 invocation/fixture는 수정해
다시 검증하되 실패 로그와 실제 운영 실패 이력은 보존한다.

`scripts/contracts/audit_wire_contracts.py`는 schema 내부의 독립 `$id`/fragment와 runtime
resources의 canonical mirror도 검사한다. 기존 schema bytes를 고쳐 audit만 통과시키지 않는다.
DB 선언 불일치는 released migration의 실제 구조와 비교한다. FK에서 자동 추론한 열 길이,
index 이름/식, 삭제 정책의 선언 차이라면 운영 DDL을 바꾸기 전에 model을 대조한다.
`test_alembic_head_matches_composed_sqlalchemy_metadata`는 새 owner model도 명시적으로 등록한다.

현재 admission과 역사적 실행 재현은 다른 검사다. `tests/workflow_admission_fixtures.py`는
guarded disposable DB에서만 과거의 정확한 policy snapshot을 임시 적용하며 운영 policy,
immutable definition/active flag를 수정하지 않는다. 현재 policy 거부 검사는 이 fixture 없이
실행한다. 구 bootstrap V1/V2처럼 같은 logical key의 다른 frozen profile은 새 임시 DB에서
단독 실행한다. 공유 DB에서 그 history를 덮어써 모든 테스트를 통과시키지 않는다.

## 배포와 백그라운드

자료 학습0074는 기존 protected release operator의 context/admission1.21과 정확한
`MIGRATION_UPGRADE_0074`/`MIGRATION_VERIFY_0074`를 사용한다. 기존 schema/callback을
재해석하지 않는다. API·control 반영과 새 coordinator의 enable/start를 구분하고, 새
Graph10을 모르는 INDEX source는 현재 numerical/preparation 작업을 자연 완료시킨 뒤
호환 인계한다. 운영 사실·부분 canary·남은 경계는
`docs/operations/MATERIAL_LEARNING_RELEASE_2026-11-06.md`와 실제 installed 기록을 확인한다.

API·Web·Catalog/Runner·INDEX/QUERY·수치 controller는 다른 설치 source일 수 있다.
서로 지원하는 contracts와 wheel/RECORD를 맞춘 release set으로 배포한다. 모든 component를
무조건 같은 HEAD로 재시작하지 않는다. 동작 중인 수치 runtime pin·실행 계획·worker를
바꾸지 않고, 변경된 owner만 기존 graceful handoff로 교체하는 방법을 먼저 검토한다.

API 업데이트에서는 QUERY unit의 기존 `Requires=eom-api.service`와 provider의
API commit/wheel/code-member hash pin을 함께 본다. API/Web만 교체하는 것으로
독립 배포가 된다고 추정하지 않는다. public/private wrapper hash와 Catalog/chat/runtime
연결은 기존 compatible-set 절차로 갱신하되 frozen INDEX/GPU는 보존한다.
원래 creative producer의 지원된 SIGINT drain으로 workers와 Graph publication이
자연 완료한 뒤 교체·재개한다. current-provider의 파일 epoch 검증 때문에 코드 교체 후
API 시작까지 기존 1.1초 guard를 유지하며, rollback도 프로세스를 먼저 멈춘 다음
파일을 복구하고 시작한다. 실패한 배포 기록을 지우지 않는다.

정상 입력 뒤의 저장·Graph·검색 실패는 담당 deterministic 코드에서 재현한다. 디스크/DB
자원 장애, 잘못된 AI 결과, 권한/hash 위반을 분리한다. 안전한 원래 요청 재개와 모든 오류
무시하기는 다르다. timeout만으로 미실행을 가정하지 않는다.

`background_storage.py`, `database.py`의 resource 분류, `host_package_maintenance.py`와
creative/INDEX driver가 최근 자원 복구의 시작점이다. source-level guard가 모든 미래
환경 race를 없앴다고 주장하지 않는다. 살아 있는 서비스뿐 아니라 실제 완료/저장과 다음
처리를 확인한다. 기존 정기 관측이 있으면 중복된 빠른 monitor를 추가하지 않는다.

개발 reporter의 활성 슬롯은 Job 상태뿐 아니라 같은 Job/slot의 유효 lease로 확인한다.
producer 기록 시각과 observer 점검 시각도 구분한다. 중단된 producer의 오래된 기록이
신선한 Graph/GPU 관측 전체를 가리게 하지 않는다. optional query/표현의 소유자는
`tools/dev_reporter/eom_dev_reporter/background_monitor.py`이며 운영 상세는
`docs/operations/DEVELOPMENT_BACKGROUND_MONITOR_2026-11-04.md`를 본다.

## 파일 정리

cache와 완료된 build source/설치 시뮬레이션은 실제 실행 참조·정확한 target identity·
복구용 wheel/archive/Git을 확인해 정리한다. 이름이 오래됐다는 이유로 released schema,
staging 원본·실패 로그·인증·설치 runtime·구형 벡터를 지우지 않는다. 소켓과 symlink,
mount는 일반 임시 파일과 구분한다. 큰 산출물과 정리 감사 manifest는 NAS의 기존
Orchestrator Artifact commit 경계로 보관하며 Git에는 넣지 않는다.

사용자의 명시적 EOMIS 퇴역 작업에서는 source/data와 보안 차단용 빈 경로를 구분한다.
`InaccessiblePaths=/home/eom/EOMIS`가 해당 경로의 존재를 요구하므로 옛 repository가
없다는 이유로 빈 guard까지 지우지 않는다. 초기 legacy Git-root/baseline 검사는 퇴역
후 그대로 적용할 수 없다. 범위·암호화 백업·검증은
`docs/operations/LEGACY_MODEL_CACHE_RETIREMENT_2026-11-06.md`를 확인한다. HuggingFace의
home cache와 현재 protected model payload도 별개이며 cache root에는 인증 파일이 있다.

## 근거

- `docs/operations/API_INTEGRATION_TEST_DATABASE.md`
- `docs/operations/RELEASE_OPERATOR_RUNTIME.md`
- `docs/operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md`
- `docs/operations/LOCAL_FILE_CLEANUP_2026-11-04.md`
- `tests/unit/test_dependency_boundaries.py`
- `tests/unit/test_background_resource_recovery.py`
