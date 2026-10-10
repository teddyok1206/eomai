# 핵심 착상 전이: 제출·결과 조회·보호된 실험 source 연결

상태 시각: 2026-10-10 UTC. **SOURCE_VERIFIED / NOT_LIVE**.
전체 goal은 ACTIVE이며 완료하지 않았다. 실제 corpus 비교·worker canary·사람의 전이 판단을
합성 입력이나 계약 테스트로 대신하지 않는다.

## 이번 구현

- JSON Schema 2020-12 두 standalone family와 frozen 값: actor 없는 작은 pair selection,
  exact Workflow read, 현재 API principal만 넣는 private binding. 기존 snapshot/worker bytes는 불변.
- 현재 authenticated snapshot PREPARE의 exact header/index에서 두 profile을 찾고, 한 개씩 READ해
  closed wrapper를 서버에서 구성한다. 작은 chunk 한도를 임의 확대하거나 latest를 대체하지 않는다.
- 현재 source resolution은 **HTTP idempotency cached replay보다 먼저** 실행한다. 기존 permission
  SHA는 처음의 provenance로 남기고, replay 때 현재 source 권한을 따로 확인한다.
- 같은 기존 transaction에서 Workflow + released exact V21 + START command를 저장한다.
  key-scoped PostgreSQL advisory lock과 기존 unique/savepoint/queue를 재사용한다. 새 queue/DB 없음.
- SQL replay는 초기 public selection·정의·request fingerprint·원래 V21/START 연결을 검증한다.
  historical plan read는 모델의 현재 실행 가능성과 분리해 latest를 찾거나 과거를 다시 실행하지 않는다.
- Catalog own-creator/current-permission result read: Workflow→Step→Job→V21→승인 ArtifactManifest의
  exact lineage 확인, 공식 loader의 canonical outer `result.json` SHA 및 role envelope 검증,
  inner pair의 근거·facet closure 확인, materialization 이후 source/lineage 재확인.
  DB `revision.result` metadata를 정본 결과로 사용하지 않는다.
- 상태는 PENDING / NO_RESULT / POINTER_ONLY / MEMBER_VERIFIED로 분리한다. 원본 결과를 실제
  읽지 않은 STATUS 조회를 내용 검증이나 과학적 정확성 승인으로 확대하지 않는다.
- 기존 socket의 API-peer 전용 분기, API application leaf/router/lifespan, Catalog runner/server를
  연결했다. 일반 chat/worker peer에게 새 권한을 주지 않았다.
- authenticated API snapshot → pure staging adapter → protected local workspace → optional CPU port
  → canonical result/model/execution/hash 검사 → 전체 모집단 현재 재인가 → 기존 file-set owner commit
  composition을 구현했다. CPU/publisher가 없으면 실행을 명시적으로 거부한다.
- 실행 관측이 불확실하면 모델을 재호출하지 않는다. 완료 출력 replay는 모델 호출 0회이며
  현재 source 재인가는 다시 수행한다. 기존 offline CLI의 선택적 execution ID만 추가했다.
- 실행 계획 projection 검증과 comparison fingerprint는 기존 소유 모듈의 공개 함수로 공유한다.
  결과 조회와 제출에 같은 DB rule을 복사해 두지 않았다.

## 검증과 실제 실행의 구분

| Gate | 결과 | 범위 |
|---|---|---|
| 통합 source suite | 1,550 PASS / 75.66 s | 기존 56 + 새 7개 파일, 총 63개 파일. 이후 추가 API 부정 조건 4개는 아래 focused suite에서 확인 |
| 최종 API/client/staging focused | 76 PASS | 실제 principal은 synthetic fixture. 실제 HTTPS/session PASS가 아님 |
| release/control 별도 회귀 | 166 PASS / 5.18 s | source suite와 별도 파일 집합 |
| OpenAPI/release inventory/dependency | 20 PASS / 12.95 s | 일부 통합 suite와 겹치므로 전체 합산하지 않음 |
| 변경 production strict mypy | 22 files PASS | follow-imports=silent, 변경하지 않은 전체 codebase type check가 아님 |
| Ruff lint/format | 35 files PASS | 변경 Python 전체 |
| guarded PostgreSQL | 65 PASS / 12.47 s | 기존 52 + 새 submission persistence 13; source 권한·모델 availability는 명시적인 합성 fixtures |
| migration | PASS | 같은 disposable DB의 `0051 → 0050 → 0051`, 운영 DB 적용 아님 |
| disposable DB cleanup | PASS | `/tmp/eom-api-testdb-20261010110233_a3999a68`의 임시 DB·role·보호된 환경 파일을 지원 cleanup으로 제거하고 경로 부재 확인. 운영 DB는 변경하지 않음 |
| 원문 SHA | PASS | `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a` 유지 |
| installed authenticated corpus/worker | NOT_RUN | 실제 운영 승인·인증·compatible release 필요 |
| human transfer review | NOT_EVALUATED | 사람 label로 검증하지 않음 |

TestClient의 기존 httpx deprecation warning 1건은 남아 있으며 새 dependency는 추가하지 않았다.
OpenAPI/resource/inventory도 함께 갱신했다. 이전 3종 wheel build PASS를 이번 변경의 build PASS로
옮겨 적지 않는다. 이번 source 후보의 실제 build-only 결과는 아래 별도 evidence다.

독립 read-only 검토에서도 제출 전 현재 권한 확인, 최초 permission provenance 보존,
Workflow/V21/START 원자적 기록, historical plan closure 및 정본 결과 조회에 재현 가능한
추가 결함은 발견하지 못했다. 이것은 실제 인증·운영 실행·교육 품질 승인 증거가 아니다.

### 이번 후보의 실제 build-only

2026-10-10 11:12 UTC에 기존 `scripts/api/deploy_release.sh --build-only`를 실행해 성공했다.
운영 설치·서비스 restart·control activation·운영 migration은 실행하지 않았다.

- source commit: `992df006cb2b4a1f49d1a1fed904ce8c5f72ff3f`
- source tree: `f607b255cd84fc04863f64a03f2c4d2dd4f20558`
- wheel directory: `/tmp/eom-api-build/992df006cb2b4a1f49d1a1fed904ce8c5f72ff3f.D4c8fj/dist`
- installed-layout inspection 및 wheel RECORD 검증: PASS

| Wheel | SHA-256 |
|---|---|
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `730fa41629c50e9c54f53226372340b8c10dc83fdf4ab7e8793c60ba4d099b7b` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `3b87b58bbd9940d7ef694b1f06b46e00b39b6e2150340ecc5d5c8195dc4fd115` |
| `eom_platform-0.1.0-py3-none-any.whl` | `f00e4283ae999fc868aded7e27c45a9c527e806fbacbc184063bae49344b4312` |

이 기록을 추가한 후속 문서 commit과 위 build source commit은 다른 identity다. 임시 build
경로는 정본 runtime 설치나 NAS Artifact를 뜻하지 않는다.

### 실제 설치 상태의 read-only preflight

2026-10-10 11:24–11:25 UTC에 실제 서비스 상태, `python -I`의 설치 metadata 및 선택된
package 파일/RECORD를 확인했다. 저장소 import/PYTHONPATH, 자격 증명·환경 파일·DB·NAS·사용자
문서 접근이나 모델 실행·설치·서비스 변경은 하지 않았다.

| 확인 | 실제 결과 | 해석 |
|---|---|---|
| API·Catalog·Runner | `active/running`, `NeedDaemonReload=no` | 기존 서비스 process 정상; 신규 기능 PASS가 아님 |
| 설치 API build source | `83884224651d8b9516a7a54370077757138c518c`, tree `0731b36ab54ea89c4126cb8b94b6c422a534810f` | 후보 `992df006…`는 미설치 |
| 신규 purpose 파일·schema | 필수 18개가 설치 파일과 RECORD 양쪽에 없음 | `INSTALLED_PURPOSE_SUPPORT=UNAVAILABLE_NOT_INSTALLED` |
| 기존 owner 파일 | 선택 7개 존재 및 RECORD SHA 일치 | 전체 wheel 무결성이나 기능 검증으로 확대하지 않음 |
| API health smoke | PASS | 인증·Graph·신규 pair 실행 검증이 아님 |
| 고정 CPU 환경·libexec·unit | 없음; unit `LoadState=not-found` | 격리 CPU launcher 사용 불가 |
| 이전 임시 CPU 환경 | `/tmp/eom-inference-transfer-runtime.T3lA5o/env` 존재; Python `3.12.13`, torch `2.7.1+cpu`, transformers `4.56.2`, safetensors `0.6.2`, tokenizers `0.22.2`; UID/GID `1000/1000` | 개발용 수치 환경일 뿐 보호된 운영 설치가 아님 |
| 관련 worker/image/HWPX transient unit | 관측 시각의 active/activating/deactivating 목록 없음 | DB queue·claim·lease quiescence는 UNKNOWN; 재제출/배포 근거로 대체하지 않음 |
| active controls·Graph·policy·actual operator corpus | UNKNOWN / NOT_READ | 인증 및 운영 승인 경계 유지 |

최초 실제 호출의 선행조건은 **호환 release 설치 승인 + 실제 operator 인증**이다. 로그인 ID
만으로 현 미설치 runtime에서 실험할 수 있다고 해석하지 않는다. Bootstrap PREPARE/별도 RELEASE,
격리 CPU 설치·handoff·실행 및 human review는 이후에도 각각 별도 gate로 남는다. 이번 점검은
새로운 권한·서비스를 승인하거나 old controls/Workflow를 최신 후보로 대체하지 않는다.

### 실패 이력과 수정

1. 유효한 max_entries=1 selection에 두 profile READ를 한 번에 만들면 constructor가 실패하는
   부분을 실제 발견했다. 한 개씩 READ하고, 단독 request도 예산을 넘기면 안전한 422 budget
   error를 반환한다. source/policy 한도를 늘리지 않았다.
2. SQL replay에서 V21 연결 검사가 빠진 경계를 독립 리뷰로 찾아 보강했다. 기존 owner의
   exact historical plan validator를 재사용하고 현재 runnable candidate admission과 분리했다.
3. API test의 foreign revision fixture prefix가 계약과 달라 409 대신 올바른 422가 나왔다.
   fixture만 정확한 prefix로 고쳤다. 입력 검증을 완화하지 않았다.
4. 추가 PostgreSQL 변조 tests 세 건이 불변 snapshot 필드를 수정할 수 있다고 잘못 가정했다.
   DB는 실제 `ProgrammingError / RaiseException / P0001`로 수정 자체를 차단했다.
   정확한 거부·nested rollback·원래 hash·원래 replay·Workflow/V21/START 각 1건 보존을
   검사하도록 tests만 고쳤다. mutable runtime pin 세 건은 application replay 거부를 검증한다.
5. 일부 최초 개발 invocation의 source path/파일명 오타와 Ruff/static typing 오류는 로컬에서
   보정·재실행했다. 이를 운영 장애나 권한 완화 사유로 분류하지 않았다.

## 남은 경계

1. 실제 인증 operator의 installed snapshot API 호출과 권한 범위 확정.
2. 검토된 bootstrap bytes를 실제 control authorizer/publisher로 PREPARE하고, 별도 NON_LIVE
   RELEASE를 통과시키는 운영 composition. 기존 support/PDF/출제 preset은 바꾸지 않는다.
3. pinned protected model과 명시적인 설치·격리 CPU launcher. 소스의 CPU port는 unsandboxed
   subprocess나 ambient Python으로 자동 대체하지 않는다.
4. 실제 target의 길이·token overflow·resolution 비용과 동일 집합의 lexical/Graph/세 표현 비교.
5. 기존 Orchestrator를 통한 제한된 pair canary와 사람 검토 묶음.

Workspace sentinel은 임시 실행 관측이며 durable exactly-once registry가 아니다. 완료/uncertain
workspace를 임의 정리한 뒤 같은 execution ID로 recovery하는 것은 지원하지 않는다.
지원 owner reconciliation 전에는 관련 자료를 보존한다. source 재인가와 NAS commit 사이를
분산 원자성이나 영구 권한 cache라고 주장하지 않는다. 공식 결과 loader 위의 반환 bytes
hash를 재검증했지만, 기존 loader 전체에 새로운 protected FD 보증이 생겼다고 주장하지 않는다.

관련: [보존 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md),
[구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md),
[owner 호출부 설계](ITEM_INFERENCE_TRANSFER_OWNER_INVOCATION_DESIGN.md),
[protected staging 설계](ITEM_INFERENCE_TRANSFER_SNAPSHOT_STAGING.md).
