# Codex 로그인 변경 후 자동 모델 검증 — 배포 인계

로그인 성공을 모델 권한 미검증 때문에 되돌리던 문제를 분리하고, 새 계정의 실제 모델 검증과 자동 사용 시작을 연결한 소스 후보입니다.

작성일: 2026-10-24 UTC. 이 문서는 **운영 배포 완료 증거가 아닙니다.**

## 상태

```text
SOURCE_IMPLEMENTATION=COMPLETE_CANDIDATE
FOCUSED_TESTS=942_PASS
RUFF_AND_FORMAT=PASS_ON_TASK_FILES
MYPY=PASS_ON_15_CORE_AND_API_FILES
JS_SYNTAX=PASS
DIFF_WHITESPACE=PASS
SCHEMA_CHANGE=NONE_REUSE_RELEASED_COMPATIBILITY_CONTRACTS
DB_MIGRATION=NONE
NEW_DEPENDENCY=NONE
LIVE_MODEL_CALLS_IN_THIS_TASK=0
DISPOSABLE_POSTGRES_CONCURRENCY=NOT_RUN
INSTALLED_WHEEL_VERIFICATION=NOT_RUN
PRODUCTION_DEPLOYMENT=NOT_PERFORMED
LIVE_DEVICE_LOGIN_CANARY=NOT_RUN
```

기존 Starlette/httpx deprecation warning 1건은 위 테스트 실패가 아닙니다.
SQLite 메모리 DB로 실제 SQL 판정은 검증했지만 PostgreSQL 동시성 PASS로 확대하지 않습니다.
전체 composition type-check는 별도입니다. 선행 실행에서 이 작업과 무관한
`similarity_role_preparation.py`, `similarity_role_catalog_client.py`의 V1/V2 타입 오류
4건이 관찰되어 이 작업에서 수정하지 않았습니다.

## 동작

1. 기기 로그인을 완료하면 새 계정 연결 버전을 먼저 안전하게 저장합니다.
2. 같은 로그인 요청의 `VERIFYING`에서 새 계정 모델 목록을 읽고 후보를 좁힙니다.
   목록에 보이는 것 자체를 검증 통과로 처리하지 않습니다.
3. 기존 합성 PNG + 계산 + strict JSON 진단을 새 계정에서 실제 실행합니다.
4. 통과한 모델/추론 강도만 허용합니다. 출제/검토는 양쪽 현재 계정에서 같은 조합이
   검증되어야 한다는 조건을 유지합니다.
5. 새 인증 확인과 정식 검증 결과가 모두 유효하면 별도 ‘사용 시작’ 없이 READY가 됩니다.
6. 확인된 모델이 없다면 로그인은 보존하되 DRAINING을 유지하고 화면에서 이를 구분합니다.

과거 FAILED 로그인 기록을 성공으로 바꾸지 않았고, 기존 계정의 모델 권한을 새 계정에
복사하지 않았습니다. 인증 파일·토큰 복사, 외부 LLM API, 직접 DB 보정은 없습니다.

재실행은 정식 등록된 검증 결과를 우선 재사용합니다. 로컬 staging이 없어져도 이미 완료한
추론을 반복하지 않습니다. 시작 여부가 불명확한 실행은 자동 재추론하지 않습니다.
새 후보 탐색으로 기존 체크포인트의 모델 목록을 바꾸지 않습니다.

## 함께 반영해야 하는 구성요소

- `eom-platform`: Orchestrator, workflow runner composition, 공통 capability SQL.
- Application API: 계정 목록에서 이전 계정의 snapshot을 숨기는 조회 변경.
- Web: 자동 확인 진행/완료/제한 안내, 확인 중 OBSERVE/ENABLE 버튼 비활성화.

API만 먼저 배포하면 새 platform 모듈이 없어 import 실패할 수 있습니다.
**공유 실행 환경의 wheel/RECORD를 바꾸므로, 메인 GPU 실험의 실행·결과 회수와 겹쳐
임의 pip 설치·설치 파일 덮어쓰기·서비스 재시작을 하지 마세요.**
메인 세션이 runtime pin과 실행 상태를 확인한 뒤 기존 호환 release 절차로 반영해야 합니다.
이 보조 세션은 메인 세션의 embedding 코드, 인증 세션, 서비스 상태를 변경하지 않았습니다.
메인 세션이 같은 저장소에서 작업 중이므로 전체 worktree를 무차별 staging하지 않습니다.

## 핵심 소유권

- `reviewed_capability_policy.py`: 기존 불변 정책 값 모델. 기존 import는 re-export로 유지.
- `auth_enrollment_capability_admission.py`: 정식 Artifact와 정확한 계정/정책의 증거 조회.
- `auth_enrollment_capabilities.py`: 모델 발견, 기존 진단 실행, 용량 fence.
- `auth_enrollment_processor.py`: 같은 enrollment의 인증 → 검증 → READY 수명주기.
- `capability_snapshot_queries.py`: 현재 계정 이후의 snapshot만 허용하는 공통 SQL 조건.
- 기존 `codex_runtime_compatibility.py`와 `codex_compatibility_maintenance.py`: maintenance와
  enrollment가 공유하는 실행/체크포인트/발행 및 host lock 경계.

원 설계 및 제한: [Codex GUI Device Reauthentication V1](../architecture/CODEX_GUI_DEVICE_REAUTHENTICATION_V1.md), §4.1.

## 배포 전에 남은 검증

1. 이 작업의 변경 파일만 검토·커밋하고 설치 wheel에 새 모듈이 포함되는지 확인합니다.
2. 기존 disposable PostgreSQL 경로에서 assignment 불변성, enrollment 유일성/재청구,
   실제 host advisory lock/동시 claim, 현재 snapshot 조회를 검증합니다. 운영 DB pytest 금지.
3. 검증된 호환 platform/API/Web release를 설치합니다. 새 DB migration이나 보호된
   `/etc/eom/codex-capabilities.yaml` 직접 수정은 필요하지 않습니다.
4. 승인된 관리자 계정으로 슬롯 한 개만 실제 로그인 변경합니다. OpenAI 기기 승인 자체는
   사용자가 해야 하며 이를 생략하거나 다른 슬롯의 인증을 복사하지 않습니다.
5. 같은 enrollment가 VERIFYING → SUCCEEDED로 이동하는지, 같은 assignment를 유지하는지,
   actual probe report/Artifact/hash, READY 또는 명확한 DRAINING을 확인합니다.
6. OBSERVE 후에도 새 증거가 유지되는지, 오래된 snapshot으로 미검증 모델이 배정되지
   않는지 확인합니다. 검증 중 중지한 슬롯을 자동 READY로 되돌리면 안 됩니다.
7. 실제 로그인 및 진단 시간을 기록합니다. 현재 구현은 희귀한 로그인 변경 동안 기존
   host capacity lock을 잡아 새 worker claim을 대기시킵니다. 이미 실행 중인 작업은
   중단하지 않지만 **새 작업 접수에 영향이 전혀 없다는 뜻은 아닙니다.**

진단은 기존 released report의 규칙대로 첫 실패/불명확 실행에서 멈추며 이전 PASS 조합만
사용 가능합니다. 미실행 모델까지 전부 통과했다고 보고하지 마세요. 남은 enrollment 시간
안에 검증이 충분히 끝나는지도 실제 canary에서 확인해야 합니다.

## 로컬 검증 명령

명시적 Conda Python:

```bash
PYTHONPATH=services/orchestrator:apps/web_gui:apps/application_api \
/srv/eom/conda/envs/eom-api/bin/python -m pytest \
  tests/unit/test_codex* tests/unit/test_control* \
  tests/unit/test_current_assignment_capability_snapshots.py \
  tests/unit/test_preset_model_selection.py tests/unit/test_worker_auth_capability.py \
  tests/unit/test_dependency_boundaries.py \
  tests/web_gui/test_codex_account_auth_refresh.py \
  tests/web_gui/test_frontend_backend_alignment.py \
  tests/web_gui/test_studio_boot_navigation.py \
  tests/api/test_control_plane_adapter.py \
  tests/api/test_preset_model_selection_contracts.py -q
```

이 테스트는 source/fixture 검증이며 live 모델 호출·사용자 인증·배포를 하지 않습니다.

## 메인 세션 인수 검토 — 2026-10-24 08:32 UTC

- 인계 diff와 설계 §4.1을 검토했다. 새 assignment별 canonical report 조회,
  current-assignment/latest-snapshot SQL, 관리자 DRAIN/DISABLE 보존, 같은 enrollment의
  checkpoint replay를 확인했다. 인증 파일 복사나 정책 파일 갱신은 수행하지 않았다.
- 인계의 source 회귀 942개를 다시 실행해 PASS했다. strict mypy15개 모듈과 scoped
  Ruff/format, ES-module 방식 JS syntax도 PASS했다. 처음 CommonJS 방식의 node syntax
  호출은 invocation 오류였으며 ES-module 검사로 재실행했다.
- marker-guarded disposable PostgreSQL에서 60 PASS: enrollment 동시 생성/claim의
  단일 소유자, polling TTL 이후의 연장 claim 보존/만료 후 회수, 실제 current-account /
  latest-model SQL와 assignment immutable trigger, 기존 host advisory lock/전역 동시
  worker claim/기존 V3 persistence를 포함한다. 모델·systemd worker 실행은 없었다.
- 추가한 fixture의 종료 상태와 고정 과거 시각 때문에 최초 두 검증은 실패했다.
  production 규칙을 완화하지 않고 fixture를 유효한 FAILED(reason 포함) 종료와 현재
  clock으로 수정했다. 실패 DB2개와 최종 PASS DB
  `/tmp/eom-api-testdb-20261024083057_245ed03c` 모두 공식 cleanup으로 제거했다.
  운영 DB를 pytest 대상으로 사용하지 않았다.
- 기존 release wheel inventory에 새 자동 검증/공통 SQL/정책 모듈을 추가하고 누락 거부
  회귀를 추가했다. release contract/RECORD/deployment boundary 111 PASS다. 첫 core
  invocation의 source PYTHONPATH 누락은 바로잡고 전체 source 경로로 재실행했다.
- 설치 wheel 검사, 운영 배포, 실제 device 로그인1회와 후속 OBSERVE는 아직 미실행이다.
  고정 GPU 비교가 실제 실행 중이므로 public platform/API/Web 교체는 그 결과 회수 후다.
  희귀 로그인 진단 중 host-capacity fence가 새 claim을 막는 기존 동작은 PG에서 검증했고,
  실제 lock 유지 시간·신규 claim 대기 영향은 운영 canary에서 별도로 측정한다.

공식 Codex 안내에서도 device 인증은 사용자가 브라우저에서 승인하며 모델 사용 가능 여부는
로그인 방식·계정·클라이언트에 의존한다. 따라서 목록 노출만 PASS로 취급하지 않고 실제 CLI
probe를 유지한다. [인증 안내](https://developers.openai.com/codex/auth),
[모델 안내](https://developers.openai.com/codex/models). 이 문서는 EOM의 외부 LLM API
금지 원칙을 변경하지 않는다.
