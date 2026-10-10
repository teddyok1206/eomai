# 문항 핵심 착상 전이 — 인증 자료 조회와 전용 실행 연결

상태 시각: 2026-10-10 10:40 UTC. **소스·격리 검증 기록**이다. 운영 설치, 실제 기출 비교 또는 교육 품질 승인 기록이 아니다. 직전 소스 checkpoint는 `bc2247ab`이며 이번 변경은 그 후속이다.

## 이번에 닫은 소스 경계

- JSON Schema 2020-12와 frozen 모델로 snapshot `PREPARE / READ / AUTHORIZE`, 전용 private binding, 검토된 control bootstrap 입력을 먼저 정의했다. 기존 released retrieval/role/result 계약 bytes는 바꾸지 않았다.
- 인증 API → 기존 private Catalog socket → Catalog owner producer를 연결했다. 실제 principal의 Item·Graph·분석·필요한 intake 권한을 확인하며, public 입력에 actor/ADMIN/permission/path를 받지 않는다. API peer만 새 private operation을 사용할 수 있고 chat/worker peer는 거부한다.
- Catalog는 매 단계 현재 권한과 exact Graph/policy/source/accepted-report pins를 재확인한다. 각 호출은 read-only repeatable-read이며 여러 호출을 하나의 DB transaction이라고 주장하지 않는다. header와 complete-set hash가 호출 사이 동일성을 검증한다.
- 원래 occurrence-backed 집합과 accepted report 누락 수를 보존한다. 현재 수를 520으로 하드코딩하지 않고 canary가 포함되도록 범위를 넓히지 않는다. 표·단위·부정·문제 측 수식을 보존한 answer-free 본문, report 기반 concrete facets, provenance가 확인되는 metadata를 각각 만든다. 그림 pixels를 읽었다고 주장하지 않는다.
- 원본 member는 16 MiB/item, 128 members/128 MiB/batch 한도 내에서 읽고 각 batch를 투영한 뒤 raw bytes를 버린다. Private envelope 4 MiB와 snapshot body 3 MiB는 별도 한도다. 초과하면 내용을 자르지 않고 명시적으로 거부한다.
- 공식 Graph retrieval baseline은 같은 actor/Graph/policy와 기존 ranking을 사용한다. query 자체와 모집단 밖 결과를 제외한 뒤 후보가 적거나 없어도 그대로 기록한다. `result_sha256`은 정규화된 **파생 baseline 값**의 해시이며 raw retrieval response나 Evidence receipt 해시가 아니다.
- pure Orchestrator staging은 ordered chunk/full-index/hash closure, missing-report denominator, 전체 64 MiB 예산을 검사한다. 명시적 read-budget 오류만 같은 chunk의 ordered split으로 처리한다. 현재 최종 재인가 함수는 별도로 제공하며 초기 권한 확인을 영구 권한으로 캐시하지 않는다.
- 전용 V21 resolver는 기존 Runner fenced transaction, exact instruction/rubric, native·reviewed model availability, immutable plan/step 및 기존 unique constraint를 사용한다. Replay는 저장된 plan을 사용하고 latest/current로 바꾸지 않는다.
- Runner composition은 실제 Workflow 생성자와 Catalog pair authorization을 전용 executor에 연결했다. 기존 Orchestrator의 prepare/materialize/run과 replay/prelaunch/commit 재인가, 기존 queue/lease/state machine을 재사용한다. 비교 결과는 Item 등록이 아니다. 최초 permission digest는 audit pin이고 현재 권한은 다시 확인한다.
- bootstrap source는 발행 전에 현재 권한·후보 가용성·capacity·exact reviewed bytes를 확인한다. PREPARE는 DRAFT만 만들며 RELEASE는 별도 명시적 동작이다. 실제 non-live CLI 인자 검사만 평가하고 품질 점수는 없다. 부분 Artifact 발행은 보존하고 exact replay로 복구하며 distributed rollback이라고 부르지 않는다.
- 기존 release 검사에 누락됐던 비교 관련 Catalog schema 4개와 새 module inventory를 추가했다. 과거 support/PDF/출제 의미를 새 비교 목적으로 바꾸거나 별도 queue/search engine/cache/framework를 만들지 않았다.

## 실제 검증 결과

| 검사 | 결과 | 확인 범위 |
|---|---:|---|
| 통합 source suite | 1,241 PASS / 56.80 s | 56개 파일의 계약·projection·embedding adapter·staging·bootstrap·resolver·Runner·API/OpenAPI·기존 제출/검색·의존성·임시 installed wheel 검사 |
| 추가 release/control 회귀 | 166 PASS / 5.22 s | 별도 7개 파일: 배포/RECORD/build metadata/Catalog deployment와 기존 model validation/release |
| 변경된 production Python strict mypy | 30개 PASS | 명시한 소스 파일을 검사; `follow-imports=silent`로 변경하지 않은 의존 모듈의 전체 재검사를 주장하지 않음 |
| Ruff lint / format | PASS / 54 files | 변경된 production 및 테스트 Python |
| 임시 PostgreSQL suite | 52 PASS / 11.44 s | 기존 guarded 검색·권한·membership/stage/제출과 snapshot SQL 2개, 새 plan persistence 8개 |
| 실제 plan persistence | PASS | Workflow FK, exact replay, plan/step UPDATE·DELETE 차단, concurrent unique conflict, 실제 Runner lease fence |
| migration cycle | PASS | 같은 disposable DB에서 `0051 → 0050 → 0051`; 운영 DB에는 적용하지 않음 |
| 임시 DB cleanup | PASS | `/tmp/eom-api-testdb-20261010102812_112f843e`의 DB·roles·보호된 임시 환경만 지원 cleanup으로 제거; 경로 부재 확인 |
| 원문·predecessor bytes | PASS | 최초 답변 원문 SHA와 기존 29개 workflow-role bundle hashes 유지 |
| shell syntax / diff whitespace | PASS | 변경된 release/testdb scripts와 diff |

Suite 파일 목록과 작은 결과는 별도로 재현 가능하다. Source suite와 추가 suite는 서로 다른 파일 집합이며, 중간의 겹치는 실행을 합산하지 않는다. 기존 Starlette TestClient의 httpx deprecation warning 한 건은 남아 있다. 이 작업에서 dependency를 임의로 업그레이드하지 않았다.

Installed-wheel unit 검사는 checkout 밖의 임시 설치에서 새 package imports와 resources를 확인한다. 전체 supported `--build-only` release 검사는 이 기록 작성 시 별도 후속 검사이며, installed production identity·역할별 권한 격리·authenticated live smoke와 동일하지 않다.

### 발견한 실패와 수정

1. Source API pytest 최초 invocation이 source `PYTHONPATH` 없이 installed predecessor를 사용해 collection에 실패했다. 명시한 환경·source roots로 다시 실행했다.
2. Release schema inventory가 비교 관련 Catalog family 4개 누락을 실제로 발견했다. 정본 inventory를 완화하지 않고 release 검사 목록을 보완했다.
3. Snapshot SQL fixture의 부분 생성 서비스에 실제 Artifact adapter가 없었다. 테스트 fixture에 정식 adapter를 구성했다. 운영 생성자는 이미 구성하고 있었으며 production 동작을 우회하지 않았다.
4. PostgreSQL immutable trigger 4분기 테스트가 `IntegrityError`를 기대했으나 실제 보호는 `ProgrammingError → RaiseException / P0001`로 작동했다. 정확한 SQLSTATE·메시지와 실패 후 row/hash 보존을 검사하도록 테스트만 보정했다. Trigger/schema를 바꾸지 않았다.
5. 실행 뒤 Identity 권한 철회 오류가 owner callback 밖으로 새어 job을 실행 중으로 남길 수 있는 경계를 보강했다. 해당 Identity 오류만 기존 owner 실패 경계로 정규화한다. 임의 programming exception을 권한 오류로 삼키지 않는다.
6. 후속 실제 3종 wheel `--build-only` 검사에서 새 comparison definition이 검증용 staged 정의 목록에 빠져 admission equality가 실패했다. Equality를 약화하지 않고 exact comparison YAML/인자를 포함하고, 기존 PDF-only inventory 회귀를 모든 fixed support family에 적용하도록 보강했다. RECORD는 최초 실행에서도 PASS였으며 운영 설치 전 실패였다. 수정 후 전체 build 재실행 결과는 별도 release evidence로 남긴다.

실패 이력을 성공으로 다시 표시하거나 운영 DB 행을 수정하지 않았다. 임시 fixture의 availability/control metadata는 합성값이고 actual published control admission 증거가 아니다.

## 연결 상태와 남은 일

| 경계 | 소스 상태 | 운영/실험 상태 |
|---|---|---|
| 실제 operator 인증 snapshot API → private Catalog owner | 연결됨 | compatible installed release/authenticated read 미검증 |
| Runner 전용 executor → Identity/Catalog 재인가 → Orchestrator | 연결됨 | dedicated definition/control publication 및 bounded worker 미실행 |
| snapshot read → pure staging port | pure port/function 구현 | 실제 authenticated client adapter·오류 매핑 호출부 대기 |
| staging → protected local request → offline experiment → 최종 재인가·Artifact commit | 기존 harness와 재인가 함수 구현 | owner materialization/launch/commit 호출부 대기 |
| 선택 pair → 실제 principal Workflow 제출·공개 결과 조회 | 내부 wrapper/admission/Runner 구현 | 공개 제출/결과 계약 및 actual-principal 호출부 대기 |
| bootstrap → actual control authorizer/publisher | prepare/release source 구현 | 실제 owner 호출부·publication/release 미실행 |

Snapshot read 자체는 새 DB migration을 요구하지 않는다. `20261010_0051`은 비교 Workflow 실행 경로의 별도 gate다. API read가 설치되어도 CPU harness나 worker가 DB/NAS 권한을 얻는 것이 아니다.

후속은 위 얇은 호출부를 기존 owner 경계 안에서 닫고, 호환 release와 실제 인증된 operator의 정확한 Graph/policy scope를 확인하는 것이다. 로그인 ID는 인증이 아니며 username만으로 내부 자료를 내보내지 않는다. 이후 complete authorized corpus의 token overflow·resolution 비용·본문/facets/metadata 비교와 공식 Graph baseline, 소수 pair의 Orchestrator canary를 실행한다. 인간 평가에 필요한 항목은 한 묶음으로 남긴다.

이번 checkpoint에서 신규 CPU/GPU/model/worker inference, 실제 corpus export, 운영 migration/publication/release/activation, 외부 Git push는 **0건**이다. 이전 CPU 합성 smoke는 별도 역사적 증거다.

```text
GOAL=ACTIVE
SOURCE_INTEGRATION=PASS
DISPOSABLE_POSTGRESQL=PASS
ACTUAL_CORPUS_EXPERIMENT=NOT_PERFORMED
BOUNDED_CODEX_PAIR_CANARY=NOT_PERFORMED
HUMAN_TRANSFER_REVIEW=NOT_EVALUATED
PRODUCTION_ACTIVATION=NOT_PERFORMED
```

## 관련 문서

- [변경하지 않은 답변 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)
- [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md)
- [인증 snapshot owner·transport 설계](ITEM_INFERENCE_TRANSFER_AUTHORIZED_SNAPSHOT.md)
- [pure snapshot staging](ITEM_INFERENCE_TRANSFER_SNAPSHOT_STAGING.md)
- [전용 Runner·resolver·bootstrap 설계](ITEM_INFERENCE_TRANSFER_RUNNER_COMPOSITION.md)
- [직전 제출·준비·실행 검증](ITEM_INFERENCE_TRANSFER_THIRD_CHECKPOINT.md)

Git/Slack에는 원문 문제·worker prompt/result·모델 파일·긴 로그·자격 증명을 넣지 않는다.
