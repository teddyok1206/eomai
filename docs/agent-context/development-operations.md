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

Excel 콘텐츠 편성0075/0076은 같은 protected operator의 context/admission1.22를 사용한다.
정확한0074 predecessor부터 `MIGRATION_UPGRADE_0076_FROM_0074`로 이동하며 기존 migration은
재해석하지 않는다. 새 head에서 옛 API의 exact-head readiness는 통과하지 않으므로,
배포 전 fallback도 해당 additive schema와 호환되어야 한다. 새 편성/인쇄 이력이 생긴 뒤
옛 기능으로 후퇴하거나 DDL을 제거하지 않는다. 실제 release와 사용자 경로 증거는
`docs/operations/EXCEL_CONTENT_PLACEMENT_IMPLEMENTATION_2026-11-09.md`를 확인한다.

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

진행 중인 GPU/QUERY와 무관한 개발 timer라도 `disable --no-reload`는 안전한 무간섭
작업으로 가정하지 않는다. systemd255의 manager-global unit-file outdated 상태가 모든
unit의 `NeedDaemonReload`를 바꿔 exact-runtime 종료 검증을 거부시킬 수 있다. 보고만
멈출 때는 우선 timer stop을 사용하고, enable/disable와 daemon reload는 관련 실행이
끝난 시점에 수행한다. 실제 pin/권한 검증을 제거해 회피하지 않는다. 발생 근거는
`docs/operations/UNIFIED_ITEM_EMBEDDING_GPU_CHECKPOINT_2026-10-31.md`의11월11일 기록이다.

API 업데이트에서는 QUERY unit의 기존 `Requires=eom-api.service`와 provider의
API commit/wheel/code-member hash pin을 함께 본다. API/Web만 교체하는 것으로
독립 배포가 된다고 추정하지 않는다. public/private wrapper hash와 Catalog/chat/runtime
연결은 기존 compatible-set 절차로 갱신하되 frozen INDEX/GPU는 보존한다.
원래 creative producer의 지원된 SIGINT drain으로 workers와 Graph publication이
자연 완료한 뒤 교체·재개한다. current-provider의 파일 epoch 검증 때문에 코드 교체 후
API 시작까지 기존 1.1초 guard를 유지하며, rollback도 프로세스를 먼저 멈춘 다음
파일을 복구하고 시작한다. 실패한 배포 기록을 지우지 않는다.

공유 채팅 adapter 배포에는 owner뿐 아니라 `eom-general-chat-worker`도 교체 대상이다.
private chat 검색이 켜진 QUERY는 시작할 때 chat source socket을 검사한다. 따라서
API/Catalog 준비 → 채팅 worker 준비 → 채팅 owner의 일반·private source socket 준비 →
QUERY 준비 → Web 재개 순서를 따른다. QUERY가 뜬 다음 채팅 owner를 시작하려고 기다리면
순환 대기가 생긴다. rollback에도 같은 의존 순서를 적용한다. 한도 초과 자체와 이 배포
순서 오류는 별개의 원인이며, 둘을 새 모델 요청이나 인증 변경으로 우회하지 않는다.

creative 종료 요청은 새 source advance/publication을 멈추고, 이미 실행한 publication의
close가 끝나기 전까지 cohort fence와 `DRAINING` 상태를 유지한다. service template의
30분 한도는 유한 운영 종료 예산이지 모든 NAS/DB 지연의 성공 보장이 아니다. 배포는
먼저 SIGINT drain을 요청하고 실제 작업 종료를 확인한다. 시간 초과·실패는 원래 scope의
멱등 복구 경계를 따르며 성공으로 바꾸지 않는다.

creative 시작 검사는 현재 execution scope의 ACTIVE preset과 이전 scope의 보존된 RELEASED
revision을 구분한다. 과거 logical preset은 RETIRED여도 exact identity/hash/capacity/key를
검증해 읽을 수 있지만, 현재 scope 또는 신규 admission의 ACTIVE 요구는 완화하지 않는다.
새 owner template은 `Type=notify`이며 scope/fence/pin 초기화 뒤에만 `READY=1`을 보낸다.
이 readiness는 모델 완료 증거가 아니다. 새 template은 notification을 구현한 wheel과
함께 인계해야 하며 옛 runtime에 unit만 먼저 적용하지 않는다.

release operator의 context/schema hash/migration/receipt 형식은 기존 adapter의
`_CONTEXT_FORMATS` 한 표에서 고정한다. schema bytes와 실제 callback 권한은 그대로이며
새 버전을 inferred latest나 문자열 범위로 허용하지 않는다. 운영 helper hash 승인과
소스 정리는 별개다. 역사적 설치 기록·staging wrapper를 정리 대상으로 오인하지 않는다.

INDEX readiness의 `LOCAL_EMBEDDING_READINESS_FAILED reason=...`은 제한된 원인 코드만
남긴다. timeout·파일 변경·control 불일치를 구분하되 원문 stderr나 환경값을 출력하지
않는다. 사용자 오류 코드와 실패 판정은 유지하며 이 진단 자체가 자동 retry 권한은 아니다.

INDEX 인계에서는 exit 0 이후에도 완료 중인 CUDA가 생성한 미실행 CPU standby가 남을 수
있다. 원 요청의 성공·남은 queue를 따로 확인한다. 정확한 무시도·무lease·무step 요청만
기존 `local_indexing_unstarted_cancellation` 배포-owner 계약으로 정리할 수 있으며,
실행 중/실패한 요청을 일괄 취소하거나 DB row를 직접 고치지 않는다. 관련 절차·증거는
`docs/operations/ARCHITECTURE_REMEDIATION_RELEASE_2026-11-08.md`를 참고한다.

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

초기 합성 CPU probe `run_local_embedding_probe.py`와 EOMIS Git 저장소 존재를 요구하던
`check_repository_boundaries.sh`는 호출자 없는 퇴역 도구로 소스에서 제거했다. 과거 보고와
Git 이력은 보존한다. 현행 실험 CLI·설치/복구·schema 생성기나 EOMIS의 빈 sandbox guard를
같은 이유로 지우지 않는다. QUERY는 routed/batch 경로의 공통 START를 유지하며, 현재
모델 선택 UI는 모델·추론 강도의 개별 입력을 사용한다. 이전의 호출 없는 중복 wrapper나
결합 문자열 역변환 함수를 다시 추가하지 않는다.

시스템 전반의 미사용 코드 검토에서는 symbol 참조뿐 아니라 entrypoint·decorator·동적
callback·설치 스크립트·역사적 조회를 함께 확인한다. 테스트만 호출하는 옛 wrapper를
제거할 때는 해당 검증을 실제 실행 owner로 옮긴다. 현재 슬롯 관측은
`ControlPlaneAdapter._observation_views`, worker 시작 명령은 `worker_systemd`, Graph 자동
정렬 요청은 `automatic_item_graph_publication_service`, 인프라 진단은
`InfrastructureDoctor`가 담당한다. 이 경로와 별도로 남아 있던 usage-only/argv/retrieval/
진단 요약 wrapper, 미사용 QUERY reader와 이미지 비교 hash helper는 제거했다.

초기 미설치 초안 `eom-orchestrator.service.example`과 `eom-worker@.service`도 제거했다.
현재 고정 slot별 unit·설치 절차와 구 generic worker의 실행 중 여부를 확인하는 안전장치는
보존한다. public parser·serializer·복구 메서드는 정적 호출자가 적다는 이유만으로 삭제하지
않는다. Git source 정리와 운영 설치본·실행 pin 교체는 별개이며, 삭제한 source는 Git 이력으로
복원한다. 이 검토가 모든 동적 호출의 부재나 전체 dead code 제거를 증명하는 것은 아니다.

과학 기출 웹 수집의 신규 manifest 작성은 `science_assessment_web_corpus_service`의
V2 경로가 담당한다. 호출이 끊긴 V1 private writer는 제거했지만, 과거 manifest의
schema·공개 모델·조회 검증기는 보존한다. 신규 작성 검사는 V2를, historical 읽기 검사는
V1 fixture를 직접 검증한다. 버전 이름이 오래됐다는 이유만으로 reader를 삭제하지 않는다.

README는 제품 소개와 핵심 흐름만 유지한다. 기능별 설계·운영 탐색은 `docs/README.md`,
이전 상세 상태표는 날짜가 붙은 `docs/status/README_CHECKPOINT_2026-11-10.md`로 분리했다.
각 배포 수치와 진행 상황을 다시 README에 누적하지 않는다.

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
