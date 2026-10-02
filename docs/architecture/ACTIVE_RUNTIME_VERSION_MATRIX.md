# EOM contract and runtime version matrix

이 문서는 EOM의 버전 번호를 한 줄의 "현재 버전"으로 뭉개지 않기 위한 운영 기준이다. 서로
다른 숫자는 서로 다른 수명주기를 가진다. Workflow definition, worker role protocol, result
schema, Content Pack, control bootstrap, execution plan, Catalog protocol과 HWPX contract의 숫자를
서로 맞추거나 가장 큰 값으로 자동 승격하지 않는다.

## 상태 어휘

| 상태 | 의미 |
| --- | --- |
| Repository selector | 새 설치가 복사하는 저장소의 정의 또는 새 요청이 선택하는 최신 계약 |
| Admitted | 정확한 definition/protocol 조합으로 새 Workflow를 시작할 수 있는 코드 정책 |
| Live activated | 운영 DB의 immutable snapshot/release/preset이 실제로 존재하고 활성 조건을 충족 |
| Repository candidate | schema와 코드가 검증됐지만 운영 bootstrap/activation이 아직 확인되지 않음 |
| Historical replay | 기존 실행·Item·Artifact·receipt를 검증하기 위해 보존하는 불변 predecessor |
| Production pinned | 하나의 생산 계획이 재현성을 위해 의도적으로 고정한 이전 버전 묶음 |

`active=true`로 저장된 과거 Workflow definition 행은 그 자체로 새 요청의 selector가 아니다.
새 작업은 코드 admission, 저장된 exact definition snapshot, preset/Pack activation과 요청 계약을
모두 통과해야 한다. 반대로 historical은 "불필요"나 "삭제 가능"을 뜻하지 않는다.

## 저장소의 새 작업 selector

`scripts/workflow/install_runner_configuration.sh`가 새 설치에 복사하는 정의와 그 정의가 산출하는
result schema를 기준으로 정리한다.

| 제품 경로 | Workflow definition | Role protocol | 결과 계약 | 관련 selector |
| --- | --- | --- | --- | --- |
| 단일 문항 | `generic-item-development@1.16.0` | `workflow-role/1.24.0` | authoring/image/review/registration `@12.0` | Pack `generated-knowledge-item@1.20.14`; Graph plan `19.0`; ungrounded plan `20.0` |
| 풀이보고서 | `knowledge-analysis@10.0.0` | `workflow-role/1.21.0` | proposal `@10.0` | accepted knowledge analysis `10.0` |
| 고객지원 | `customer-support@1.0.0` | `workflow-role/1.22.0` | customer support `@1.0` | customer-support preset |
| 문서 검토 V3 | `pdf-document-review@1.2.0` | `workflow-role/1.27.0` | PDF document review `@3.0` | plan `15.0`, control bootstrap `5.0` |
| Legacy extraction | `legacy-item-extraction@1.0.0` | `workflow-role/1.14.0` | extraction `@1.0` | historical intake compatibility |
| Legacy editorial | `legacy-item-editorial-compatibility@1.0.0` | `workflow-role/1.16.0` | compatibility `@1.0` | historical editorial compatibility |

단일 문항의 plan `19.0`과 `20.0`은 경쟁하는 latest가 아니다. `19.0`은 pinned Graph/Evidence를
소비하고, `20.0`은 근거를 가장하지 않는 ungrounded 검토 경로다. 둘 다 Workflow 1.16과 role
1.24 결과를 검증하며, 검토 뒤 등록·HWPX 확인·사람 승인 순서를 사용한다. Predecessor plan
`17.0`/`18.0`과 Workflow 1.15의 실행 의미는 그대로 보존한다.

## 25문항 생산의 독립 pin

`mock-exam-production-plan/5.0`과 execution `5.0`은 다음 묶음을 불변으로 고정한다.

| 경계 | 고정 값 |
| --- | --- |
| Workflow | `generic-item-development@1.10.0` |
| Role protocol | `workflow-role/1.20.0` |
| Content Pack | `generated-knowledge-item@1.16.1` |
| Item Brief / material requirement | `4.0` / `1.0` |
| Review publication family | production V5가 선언한 exact review decision/publication/eligibility |

단일 문항 selector가 1.16/1.20.14로 올라가도 V5 생산을 묵시적으로 변경하지 않는다. 새 묶음이
필요하면 predecessor bytes를 수정하지 않고 successor production contract를 먼저 추가한다.

## 코드가 허용하는 새 Workflow 조합

정본은 `packages/workflow/eom_workflow/admission.py`의 O(1) identity map이다. 이 표는 2026-10-01
UTC의 사람이 읽는 요약이며 `tests/unit/test_runtime_version_admission.py`가 checked-in YAML과
정확히 대조한다.

| Definition | Admitted versions | 대응 role protocol |
| --- | --- | --- |
| generic-item-development | 1.8, 1.9, 1.10, 1.11–1.12, 1.13–1.16 | 1.17, 1.19, 1.20, 1.23, 1.24 |
| knowledge-analysis | 1, 4, 8, 9, 10 | 1.4, 1.7, 1.11, 1.18, 1.21 |
| customer-support | 1 | 1.22 |
| pdf-document-review | 1, 1.1, 1.2 | 1.25, 1.26, 1.27 |
| legacy-item-extraction | 1 | 1.14 |
| legacy-item-editorial-compatibility | 1 | 1.16 |

이 목록에 없는 checked-in definition은 historical validation 자료일 수 있지만 새 작업 admission은
아니다. admission에 있다고 해서 운영 bootstrap과 activation까지 완료됐다는 뜻도 아니다.

## 운영 snapshot

아래 값은 2026-10-01 UTC에 운영 DB를 read-only로 조회하고 설치 release를 검증한 결과다.
mutable 상태이므로 배포나 canary 직전에는 다시 조회한다.

| 경계 | 운영 상태 |
| --- | --- |
| 단일 문항 definitions | 1.8–1.16 admission 조합의 snapshots 존재; 최신 요청은 1.16 사용 |
| 단일 문항 Pack | development activation `generated-knowledge-item@1.20.14`; release `packrel_752cb927d929471eaefa374a1f581580`; bundle `sha256:72150b33965cbd70465cd13738df41eef66d9a9ed51d7a16b84897227c53a391` |
| 단일 문항 presets | `standard-item` revision 34, `knowledge-grounded-item` revision 28; role 1.24 호환 |
| 풀이보고서 | definition 10.0 snapshot, `knowledge-analysis` preset revision 40; role 1.21 호환 |
| 고객지원 | definition 1.0 snapshot, preset revision 2; role 1.22 호환 |
| 문서 검토 | definitions 1.0/1.1과 preset revision 8(role 1.25/1.26) 활성 |
| 문서 검토 V3 | source 1.2/role 1.27은 repository candidate; 운영 definition/preset activation 미확인 |

단일 문항의 repository selector와 위 2026-10-01 운영 snapshot은 Workflow 1.16 / Pack 1.20.14로
정렬됐다. 이미 시작된 Workflow는 시작 시점에 pin한 predecessor release를 계속 사용한다.

따라서 문서 검토 V3의 source 존재나 admission만 보고 live라고 표시하면 안 된다. bootstrap,
definition import, preset release/current selection과 authenticated canary를 모두 마친 뒤 이 snapshot을
갱신한다. 운영 snapshot의 release ID와 SHA는 배포 증거에 남기되 이 문서를 mutable ID 저장소로
사용하지 않는다.

## 주요 독립 계약 namespace

| 책임 | 현재 저장소의 latest/additive 계약 | 주의사항 |
| --- | --- | --- |
| Canonical Item | `assessment-item-content/3.0`, Catalog `catalog/1.13` | logical Item과 immutable revision/hash 분리 |
| HWPX | `hwpx-content-team/3.0` | Item/Assembly pointer를 projection하며 원본을 수정하지 않음 |
| 실행 정책 | standard bootstrap `17.0`, knowledge bootstrap `14.0` | preset revision은 별도 immutable identity |
| Evidence usage | Graph plan `19.0`, ungrounded plan `20.0` | boolean이 아닌 pointer/hash/receipt로 검증; predecessor `17.0`/`18.0` replay 보존 |
| GPU prompt policy | `local-gpu-image-prompt-policy/1.6` | predecessor `1.4` replay 보존 |
| 자료 형식 | material requirement `1.0`, Item Brief `4.0` | TABLE과 IMAGE를 같은 것으로 취급하지 않음 |
| PDF annotation | request `3.0`, Catalog `catalog/1.22` | 원본 보존, 파생 Artifact만 생성 |
| Human quality workbench | command/workbench `1.0` | released Assembly와 immutable Item Revision pointer만 평가; runtime migration/activation 별도 |
| Recovery evidence | Artifact snapshot/receipt `1.0` | full metadata inventory는 항상 비교; sampled/full byte verification 구분 |

## Catalog application route 숫자

private socket은 하나의 framed protocol이다. operation별 request/response 숫자는 경쟁하는 runtime
버전이 아니며 `CATALOG_APPLICATION_SCHEMA_ROUTES`가 exact projection을 선택한다. route suffix를
서로 같게 만들기 위해 schema를 올리지 않는다.

## 정본 위치와 변경 절차

| 판단 | 코드 정본 |
| --- | --- |
| 새 Workflow admission | `packages/workflow/eom_workflow/admission.py` |
| 새 설치 definition selector | `scripts/workflow/install_runner_configuration.sh` |
| Definition의 단계/result schema | `config/workflows/*.yaml` |
| Result schema↔role protocol | `packages/workflow/eom_workflow/schemas.py` |
| Pack compatibility | 각 `content/packs/*/*/pack.yaml`과 Catalog admission |
| Control bootstrap | `config/control-plane/`과 Orchestrator bootstrap models |
| 25문항 pin | Catalog production plan + API execution contracts |
| Live activation | 운영 DB의 immutable definition/release/preset records |

새 cross-service 의미는 JSON Schema 2020-12를 먼저 추가하고 Pydantic, resolver, admission, 배포,
문서를 그 뒤에 맞춘다. 문서만 보고 runtime을 선택하지 않으며, runtime의 `latest`를 암묵적으로
해석하지 않는다.

## 보존·정리 규칙

- immutable row, manifest, receipt, release, Workflow, Item Revision 또는 rebuild/validation 경로가
  pin한 계약은 보존한다.
- filesystem path는 identity가 아니다. 정리는 logical/revision/artifact/hash 참조를 먼저 확인한다.
- cache, wheel staging, `__pycache__`, test output처럼 재생성 가능한 파일만 canonical pointer가
  아님을 확인한 뒤 삭제한다.
- historical ID나 hash를 최신 숫자로 다시 쓰지 않는다.
- 계약 파일 삭제는 immutable reference 0건과 validation/rebuild use 0건을 별도 감사에서 증명한
  후 독립된 reviewed deletion으로 수행한다.
