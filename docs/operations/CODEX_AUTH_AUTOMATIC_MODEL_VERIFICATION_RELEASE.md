# Codex 로그인 변경 후 자동 모델 검증 — 배포 인계

로그인 성공을 모델 권한 미검증 때문에 되돌리던 문제를 분리하고, 새 계정의 실제 모델 검증과 자동 사용 시작을 연결한 소스 후보입니다.

작성일: 2026-10-24 UTC. 최초 인계 후 운영 결과를 이어 기록했습니다.

최신 상태(09:11 UTC): **호환 platform/API/Web f15e66b8 배포·HTTPS READY**.
실제 device 로그인1회와 후속 OBSERVE, host lock 실측은 **사용자 기기 승인 대기**입니다.
아래 최초 인계 상태와 뒤의 운영 기록을 서로 다른 시점의 증거로 구분합니다.

## 최초 인계 시점의 상태 — 보존

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

## 운영 배포 — 2026-10-24 09:11 UTC

```text
SOURCE_IMPLEMENTATION=COMMITTED_AND_PUSHED
INSTALLED_PLATFORM_API_WEB=f15e66b8110900296fc37676502469dee15df741
DISPOSABLE_POSTGRES_CONCURRENCY=60_PASS_AND_CLEANED
INSTALLED_CANDIDATE_IMPORTS=7_PASS_NO_MODEL_NO_DB_WRITES
INSTALLED_API_RECORD_AND_ISOLATION=PASS
INSTALLED_WEB_SERVICE_IDENTITY=48_FILES_PASS
HTTPS_LOGIN_PAGE=200
HTTPS_READINESS=READY
LIVE_DEVICE_LOGIN_CANARY=PENDING_USER_DEVICE_APPROVAL
LIVE_OBSERVE_RETENTION=PENDING
HOST_LOCK_LIVE_DURATION=NOT_YET_MEASURED
```

- source 회귀942 PASS, release inventory/RECORD/deployment111 PASS, 최종 UI9 PASS,
  strict mypy15 modules 및 scoped Ruff/format을 확인했다. 마지막 변경은 관리자 중지 상태를
  모델 검증 실패로 단정하지 않는 안내 문구와 테스트 줄바꿈뿐이다. 새 schema/migration/
  dependency는 없다. 실제 device canary의 성공으로 확대하지 않는다.
- 선행 고정 GPU 실험은 원 CPU1을 보존한 CPU3/CUDA3 실측과 검색 재조회6회, 최종 게시/
  replay까지 완료했다. controller success/status0을 확인한 후에만 shared runtime을 교체했다.
  최종 성능 판단은 KEEP_CPU이며 [실측 기록](EMBEDDING_GPU_MEASURED_2026-10-24.md)에 있다.
- 보호된 context `/var/lib/eom-release-operator-stage.f15e66b8-6qxurhk6/operator-context.json`,
  SHA `82bfa9e975b54c2d3eb6232241b81aea3ca8867d3ce59df8bd6e6c52741062dd`를 기존
  operator로 ADMIT했다. 생산 migration은0058 그대로다. 실제 실행 중 Codex lease,
  활성 일반 대화, 진행 중 로그인 요청이 없는 시점을 확인해 shared consumer를 정상 stop했다.
- 일반적인 전체 Codex maintenance 검사는 과거 native embedding RUNNING metadata 때문에
  BUSY였다. 이를 성공으로 바꾸거나 DB를 보정하지 않았다. shared consumer의 두 workflow
  잔여 row는 실제 부모/단계가 FAILED 또는 CANCELLED이고 실행 가능 command가 없었다.
  실제 INDEX는 별도 고정 runtime에서 계속 active였다. 이력 분류를 release 권한으로
  위장하지 않고 기존 승인된 shared release 절차와 실제 idle 확인을 사용했다.

### 실제 설치 artifact와 호환 구성

사전 검증 후보는 `f15e66b8.gdGPzd`, 실제 standard installer delivery는
`/tmp/eom-api-build/f15e66b8110900296fc37676502469dee15df741.NgQeb3/dist`다.
같은 source라도 build timestamp로 raw wheel SHA가 다르며 동일 ZIP으로 취급하지 않는다.

| 실제 설치 wheel | raw SHA-256 |
|---|---|
| API | `d73de300637fbfaacda3e98392c606d7b642ae2f5df0ab37c505b008c8eb1c58` |
| platform | `ab168c436e2b48808589941000c47bcfc85ce6fdd95df07334805e9a8ed58251` |
| API contracts | `6d9109624bf17eae5d0e48af2cee8ea0f4cb86f56190370880591678cd06a07b` |
| Web | `d4d2a53556af0b4f19df6fb2260ba6352c04e1826a4ab80e5e82c0c0922bddab` |

Web wheel은 `f15e66b8.WTvhKd`다. 실제 API metadata/RECORD/isolation과 Web 서비스 계정의
48-file integrity 검사가 PASS했다. rollback 기록은
`/var/lib/eom-api/deployments/f15e66b8110900296fc37676502469dee15df741.json`이며,
이전 b87cc11c API/Web wheel과 이전 설정 bytes는 보존했다. 같은0058 schema를 유지하고,
복구할 때도 서로 맞는 API/provider/consumer 선택을 함께 복구해야 한다.

- 최신 shared source의 `authenticated_session_fence.py`가 QUERY의 이전12-member pin 중
  하나와 달랐다. 원 QUERY SDK `2eef9b20…`를 교체하거나 pin을 무시하지 않았다.
  실제 설치 API/RECORD와 독립 검증 후보 bytes를 대조하고 기존 root provider observation을
  사용해 primary/mixed/private 설정3개와 unit의 파생 hash만 명시적으로 갱신했다.
  pure 정상/거부 검사7 PASS 후 stopped-file CAS를1회 수행했다. namespace·Graph·정책·
  source class·모델·INDEX 설정과 원 검색 결과는 변경하지 않았다.
- QUERY before/after와 선택 intent는 `/var/lib/eom-query-provider-auth-f15e66b8`에 보존했다.
  source-only 일반 대화 release pin은 실제 기존66f387bf를 확인해 f15e66b8로 정렬했고,
  root:root0600과 이전 bytes를 유지했다. b87을 예상한 최초 비교는 변경 전에 거부됐다.
  이미 성공한 QUERY SELECT를 재실행하지 않고 실제 after4개가 일치함을 확인한 뒤 남은
  source-only 선택을 수행했다. 비밀번호·토큰·일반 대화 secret 파일은 변경하지 않았다.
- API PID2362854, Web2365464, QUERY2365463은 active다. QUERY는09:11:45 UTC 실제
  OWNER_READY를 기록했다. INDEX PID130161/invocation053c5ab467ff4e29b4901cfabf037b4b는
  그대로다. 일반 대화 owner/worker와 Codex auth broker도 active로 복구했다.
- HTTPS `/studio/login`은200, 실제 `/studio/api/v1/health/ready`는 READY이고 API,
  API readiness, observability가 ACTIVE다. Web smoke PASS다. 존재하지 않는
  `/studio/health/ready`를 처음 확인한404는 실제 ready 경로의 실패로 취급하지 않는다.

### 실제 사용자 canary 대기

로그인 변경1회는 사용자에게 Studio의 **시스템 → Codex 실행 관리 → 슬롯06**에서 요청했다.
OpenAI 기기 승인은 사용자가 직접 수행해야 한다. terminal에 비밀번호를 새로 보관하거나
다른 슬롯의 인증을 복사하지 않는다. 완료 후 같은 슬롯의 `사용량 새로고침`1회로 OBSERVE의
정확한 assignment/READY 유지와 canonical report를 확인한다.

09:11:45 UTC read-only 관측 시작 시 과거 FAILED enrollment는3개였다. 추가된 마지막 실패도
08:40:59 UTC, 즉 이번 배포 전에 이전 구현에서 발생했다. 이3개를 baseline으로 보존하고
새 canary가 끝날 때 동일 row가 바뀌지 않았는지 확인한다. 슬롯01/02의 이전 사용자 DRAINING은
자동으로 풀지 않았다. 새 사용자 승인·model probe·완료·후속 OBSERVE와 host lock의 실제
유지 시간/관측된 claim 대기는 아직 PENDING이며 source/health PASS로 대신하지 않는다.
