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

## 배포와 백그라운드

API·Web·Catalog/Runner·INDEX/QUERY·수치 controller는 다른 설치 source일 수 있다.
서로 지원하는 contracts와 wheel/RECORD를 맞춘 release set으로 배포한다. 모든 component를
무조건 같은 HEAD로 재시작하지 않는다. 동작 중인 수치 runtime pin·실행 계획·worker를
바꾸지 않고, 변경된 owner만 기존 graceful handoff로 교체하는 방법을 먼저 검토한다.

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

## 근거

- `docs/operations/API_INTEGRATION_TEST_DATABASE.md`
- `docs/operations/RELEASE_OPERATOR_RUNTIME.md`
- `docs/operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md`
- `docs/operations/LOCAL_FILE_CLEANUP_2026-11-04.md`
- `tests/unit/test_dependency_boundaries.py`
- `tests/unit/test_background_resource_recovery.py`
