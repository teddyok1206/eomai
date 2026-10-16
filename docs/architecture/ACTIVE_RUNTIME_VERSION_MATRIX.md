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
| 단일 문항 | `generic-item-development@1.16.0` | `workflow-role/1.24.0` | authoring/image/review/registration `@12.0` | Pack `generated-knowledge-item@1.20.15`; Graph plan `19.0`; ungrounded plan `20.0` |
| 풀이보고서 | `knowledge-analysis@10.0.0` | `workflow-role/1.21.0` | proposal `@10.0` | accepted knowledge analysis `10.0` |
| 고객지원 | `customer-support@1.0.0` | `workflow-role/1.22.0` | customer support `@1.0` | customer-support preset |
| 문제지·해설지 검토 V3 | `pdf-document-review@1.2.0` | `workflow-role/1.27.0` | PDF document review `@3.0` | plan `15.0`, control bootstrap `6.0` (5.0 historical) |
| 단일 문서 검토 V4 | `pdf-document-review@1.3.0` | `workflow-role/1.28.0` | PDF document review `@4.0` | 기존 plan `13.0`, control bootstrap `6.0` |
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

단일 문항 selector가 1.16/1.20.15로 올라가도 V5 생산을 묵시적으로 변경하지 않는다. 새 묶음이
필요하면 predecessor bytes를 수정하지 않고 successor production contract를 먼저 추가한다.

## 코드가 허용하는 새 Workflow 조합

정본은 `packages/workflow/eom_workflow/admission.py`의 O(1) identity map이다. 이 표는 2026-10-03
UTC의 사람이 읽는 요약이며 `tests/unit/test_runtime_version_admission.py`가 checked-in YAML과
정확히 대조한다.

| Definition | Admitted versions | 대응 role protocol |
| --- | --- | --- |
| generic-item-development | 1.8, 1.9, 1.10, 1.11–1.12, 1.13–1.16 | 1.17, 1.19, 1.20, 1.23, 1.24 |
| knowledge-analysis | 1, 4, 8, 9, 10 | 1.4, 1.7, 1.11, 1.18, 1.21 |
| customer-support | 1 | 1.22 |
| pdf-document-review | 1, 1.1, 1.2, 1.3 | 1.25, 1.26, 1.27, 1.28 |
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

### 문서 검토 후속 운영 확인 — 2026-10-03 09:27 UTC

위 2026-10-01 snapshot은 역사적 조회다. 문서 검토에 한해 compatible release
`f81c55354dc5e65e97215e9430acd466b3829b72` 설치와 supported V6 bootstrap publication을 확인했다.
새 단일 문서 요청은 definition 1.3 / role 1.28 / result 4.0 / plan 13.0을 선택한다.
current preset revision 12는 1.25–1.28과 호환되며 paired V3의 Graph policy를 유지한다.
단일·paired predecessor는 원래 계약으로 조회/replay한다. 설치 테스트와 incident-source
read-only plan/schema preflight는 PASS이나, 이번 release의 신규 모델 실행·인증 browser canary는
미실행이다. 전체 제품 경로를 새로 acceptance했다고 해석하지 않는다.
정확한 pins와 rollback은 [ADR 0179](../adr/0179-single-document-review-target-aware-status.md)에
기록했다.

### 단일 문항 제시 형식 후속 운영 확인 — 2026-10-09 14:35 UTC

앞선 날짜의 snapshot은 보존한다. API/Catalog/Orchestrator 공용 설치 source는
`578ddd9a8f23a1a3aa9be3ee6e256344230d98aa`이며, 새 단일 문항 요청은 development activation
`activation_88c2e332a784425fa17d3c7702756839`의 `generated-knowledge-item@1.20.15`를 사용한다.
Release는 `packrel_8dde7e96f50542e4932f55c8e76b8083`, bundle은
`sha256:63785945ceaa226dcb63a278cb08cbc82f8dcf35b0a9e7df9b65dde5810f6f6c`이다.
Workflow/role/control/preset/Graph/25문항 production pins는 이번 배포로 변경하지 않았다.
기존 1.20.14와 다른 predecessor는 historical replay/진행 중 실행의 불변 pin으로 유지한다.

인증 API smoke, installed wheel/RECORD, 권한 격리, 서비스 readiness와 배포 후 verify는 PASS다.
실제 등록된 Pack Artifact를 읽기 전용으로 resolve해 Brief V5 binding 및 출제·검토 profile
`12.2.1` 렌더링에 동일한 V2 지침·원문 SHA가 포함됨을 확인했다. 이미지 policy와 SVG 라벨
검증 정책은 변경하지 않았으며, 새 bundle의 정확한 hash에도 기존 label-clearance gate가
적용된다. 새 모델/문항/GPU/HWPX 실행은 0건이므로 교육·편집 품질 평가를 새로 PASS한 것은 아니다.

Web 설치 source `67fafe99fec99e1f9bcd2293fe970c9ed18d8449`는 변경하지 않았다.
독립 일반 채팅 서비스의 release pin은 `d32f3ba75bc7a0b34305204d3dba43a009e99617`로
유지했다. 이 기능의 코드는 이번 diff에서 변경되지 않았으며, 채팅을 새 release로 재활성화했다고
보고하지 않는다. 공용 환경의 설치 wheel source와 개별 서비스의 activation pin은 구분한다.
Rollback과 검증 범위는 [ADR 0160](../adr/0160-natural-stimulus-presentation.md)에 기록했다.

## 검토 판정값 교정 운영 후속 — 2026-10-09 15:29 UTC

공유 API/Catalog/Orchestrator의 최신 설치 source는
`2bf5dd75b1356384f5748d4c396c0af4926816ee`이다. 앞선 14:35 배포의 Pack
`generated-knowledge-item@1.20.15` release/bundle/activation과 Workflow/role/Graph/control/
production pins는 그대로 유지한다. 추가 계약 `workflow-review-correction-directive/1.0`은
검토자가 제출한 복잡도·상위 검토 사유·판정값 오류만 고정된 출제/그림 입력으로 최대 3교까지
교정하며, 기존 내용 재작업·강화 검토 및 무결성 보호는 변경하지 않는다.

Source gate 175 PASS, disposable PostgreSQL gate 66 PASS, 실제 wheel/RECORD·권한 격리·인증 API
smoke·배포 후 verify PASS. Installed read-only incident-source proof는 2교 수정 지시 및 원본
실패 이력 보존을 확인했다. 새 worker 실행으로 검토 3교를 live canary한 것은 아니다.
DB head는 `20261008_0049`, Web과 독립 chat activation은 변경 없음.
상세 증거/rollback은 [ADR 0160](../adr/0160-natural-stimulus-presentation.md)에 기록했다.

## 주요 독립 계약 namespace

### 핵심 착상 전이 source 후보 — 2026-10-10 UTC

이 후보는 위 새 작업 selector/admission 또는 live activation 목록에 추가된 제품 경로가 아니다.
기존 Item/accepted V10/Graph/Evidence·Pack·production pins와 29개 predecessor role bundle hash는
유지한다. 새 지원은 opt-in source implementation이며 compatible exact-purpose release 없이는
실행을 거부한다. 실제 corpus 품질·worker canary·운영 설치는 미검증이다.

| 경계 | 별도 후보 | 상태 |
| --- | --- | --- |
| 비교 값 | `item-inference-transfer/1.0` schema family: profile, pair request/result, human evaluation, model spec | JSON Schema/Pydantic/source reference 검증 |
| Support worker | `workflow-role/1.29.0`, `item-inference-transfer-pair-result@1.0` | source-only binding; 이전 support purpose에 적용하지 않음 |
| 실행 계획 | `resolved-execution-plan/21.0`, definition `item-inference-transfer-comparison@1.0.0`, stage `INFERENCE_TRANSFER` | source wrapper/resolver/materializer/Runner 연결 검증; dedicated instruction/preset의 owner publication·운영 연결 대기. authoring Content Pack을 요구하지 않음 |
| 모집단·인가 | `OCCURRENCE_BACKED_PAST_EXAM` opt-in scope와 exact 두 profile 재생성 검증 | default 기존 scope 유지; 실제 operator/policy/Graph/report admission만 사용 |
| CPU 실험 | `item-inference-transfer-experiment/1.0` standalone family | source 및 실제 모델 합성 입력 3-view smoke; 실제 corpus·human gate 미실행 |
| 인증 snapshot | `item-inference-transfer-snapshot/1.0` standalone family | authenticated API/private Catalog owner source 연결; staged 호출·installed/live 검증 대기 |
| Private snapshot transport | `item-inference-transfer-snapshot-binding/1.0` standalone family | API peer 전용, 기존 private socket 재사용; worker/chat peer 거부 |
| Public pair submit/read | `item-inference-transfer-invocation/1.0` standalone family | source selected-pair·atomic V21/START·cached replay 이전 current-source 재인가 검증; installed/live 미실행 |
| Private canonical result read | `item-inference-transfer-workflow-binding/1.0` standalone family | API-peer own-creator/current-source/Workflow·Step·Job·V21·outer member hash closure source 검증 |
| Control bootstrap | `inference-transfer-control-bootstrap/1.0` | reviewed bytes/capacity/model pins; PREPARE DRAFT와 명시적 NON_LIVE RELEASE source 구현, 실제 publisher 호출·activation 미실행 |
| 로컬 모델 | pinned `multilingual-e5-small`, CPU toy probe | 개발 임시 환경; protected production 모델 설치 아님 |

정본 설계·단계별 상태는 [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md),
첫 CPU 실행은 [첫 checkpoint](ITEM_INFERENCE_TRANSFER_FIRST_CHECKPOINT.md),
최신 source 연결 검증과 남은 운영 경계는
[네 번째 checkpoint](ITEM_INFERENCE_TRANSFER_FOURTH_CHECKPOINT.md) 및
[후속 호출부 checkpoint](ITEM_INFERENCE_TRANSFER_FIFTH_CHECKPOINT.md)에 기록한다.
벡터 점수·구조 대응 가설·사람의 풀이 전이 판단은 서로 다른 값이며 어느 것도 Item 승인이나
과학적 정확성의 자동 증명이 아니다.
source migration head는 additive `20261010_0051`이며, disposable DB에서 실제
upgrade/downgrade/upgrade와 stage CHECK/downgrade 거부를 검증했다. 이 후보 작업으로
운영 migration 또는 서비스 release를 적용하지 않았다. 설치 runtime의 head와 혼동하지 않는다.

| 책임 | 현재 저장소의 latest/additive 계약 | 주의사항 |
| --- | --- | --- |
| Canonical Item | `assessment-item-content/3.0`, Catalog `catalog/1.13` | logical Item과 immutable revision/hash 분리 |
| HWPX | `hwpx-content-team/3.0` | Item/Assembly pointer를 projection하며 원본을 수정하지 않음 |
| 실행 정책 | standard bootstrap `17.0`, knowledge bootstrap `14.0` | preset revision은 별도 immutable identity |
| Evidence usage | Graph plan `19.0`, ungrounded plan `20.0` | boolean이 아닌 pointer/hash/receipt로 검증; predecessor `17.0`/`18.0` replay 보존 |
| 검토 결과 교정 | `workflow-review-correction-directive/1.0` | 같은 출제 revision·검토 tier에서 최초 포함 최대 3교; 통신 재시도로 횟수 초기화 금지, 내용 재작업과 구분 |
| GPU prompt policy | `local-gpu-image-prompt-policy/1.6` | predecessor `1.4` replay 보존 |
| 자료 형식 | material requirement `2.0`, Item Brief `5.0` | TABLE과 IMAGE를 같은 것으로 취급하지 않음; production V5의 `1.0`/`4.0` pin 보존 |
| PDF annotation | paired request `3.0` / `catalog/1.22`; single V4 request `4.0` / `catalog/1.23` | 원본 보존, 기존 native-panel output 재사용 |
| HWPX correction | single V4 request·plan `2.0` / `catalog/1.24` | 기존 correction output 재사용; predecessor 의미 보존 |
| Human quality workbench | command/workbench `1.0` | released Assembly와 immutable Item Revision pointer만 평가; runtime migration/activation 별도 |
| Recovery evidence | Artifact snapshot/receipt `1.0` | full metadata inventory는 항상 비교; sampled/full byte verification 구분 |
| 일반 채팅 근거 | turn input/result·owner/worker/dispatch `3.0`, agent-search `1.0`, grounding/citation `1.0` | released `1.0`/`2.0` history 보존; 대화형 검색·조회와 첨부 Item/Graph/report를 revision/hash로 고정 |

일반 채팅의 2026-10-08 19:02 UTC 운영 후속은 API/Catalog/chat `7fb311fb`와 Web `6c765820`의
호환 조합이다. `CHAT-READTOOLS-1`은 native SEARCH/READ를 기존 Orchestrator/Catalog 경계에서 실행하며
새 DB schema/migration·queue·worker privilege·외부 LLM API를 추가하지 않는다.
Workflow/Pack selector와 별도 수명주기를 가지며 기존 6개 작업 슬롯을 변경하지 않는다.
[대화형 검색 실제 검증](../status/GENERAL_CHAT_AGENT_SEARCH_ACCEPTANCE_2026-10-08.md)에 기록했다.
같은 날짜의 이전 API/Catalog/chat `276f31ea` 수동 첨부 acceptance는
[역사적 검증](../status/GENERAL_CHAT_REPRESENTATIVE_ACCEPTANCE_2026-10-08.md)으로 보존한다.

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

## 임베딩 QUERY 입력의 호환 후보 —2026-10-16 UTC

기출변형의 `reference-query-workflow-request/1.0`과 엄격한 parser는 그대로 보존한다.
신규 출제·검토의 **승인 참고 문항** 조회에는 additive 입력 `1.1`을 추가했다.
동일 definition `local-embedding-reference-query@1.0.0`, protocol `reference-query/1.0`,
policy/launch/receipt/result 및 numerical input은 유지하며 새 입력의 purpose/hash를
구분한다. 새 버전 번호는 새 Workflow topology·실행 권한·private 초안 검색을 뜻하지 않는다.

현재 상태는 repository/source + disposable PostgreSQL PASS이며 운영 미설치·미활성이다.
실제 QUERY owner `8c411041`, INDEX `2a4843c3`/Identity13, API/Web/Pack 선택은 바뀌지 않았다.
상세한 입력 의미·보존 검사·남은 소비 연결은
[authoring-reference 구현 경계](SYSTEM_RAG_AUTHORING_REFERENCE_CONTEXT.md)를 따른다.

일반 출제의 참고 근거 전달에는 추가 후보 `resolved-execution-plan/24.0`을 구현했다.
기존 educational retrieval1.0과 Evidence5를 유지하고 정확한 참고 기출 anchor와 보조 자료를
별도 pin으로 묶는다. 기존 기출변형 plan23과 QUERY 입력1.0의 의미는 바꾸지 않는다.
원래 ITEM_AUTHORING 참고 근거를 출제와 모든 검토 회차가 재사용하며 새 초안의 vector 비교로
가장하지 않는다. 소스 회귀1632/임시 DB139 PASS인 미설치·미활성 후보이며 위 운영 선택을
변경하지 않는다. strict type15, Ruff/format 및 이전 plan23 bytes 보존을 검증했다.

동일 HTTP/native 준비 경로의 입력 전용 successor1.1도 구현했다. ITEM_AUTHORING/
ITEM_REVIEW 목적을 명시하며, 기존1.0의 암시적 기출변형 의미·reply1.0·실제 사용자와
원래 key로 결정되는 native identity는 유지한다. purpose를 바꿔 같은 key를 보내면 기존
작업을 재해석하거나 새 작업을 생성하지 않고 거부한다. 관련 회귀1729/임시 DB152 PASS,
최종 HTTP·실소켓 subset110 및 strict type9 PASS. 소스 검증일 뿐 운영 미설치·미활성이며,
공식 Evidence의 자동 참고 선택·일반 문항 시작과 실제 사용자 활성화 검증은 아직 남아 있다.

## 보존·정리 규칙

- immutable row, manifest, receipt, release, Workflow, Item Revision 또는 rebuild/validation 경로가
  pin한 계약은 보존한다.
- filesystem path는 identity가 아니다. 정리는 logical/revision/artifact/hash 참조를 먼저 확인한다.
- cache, wheel staging, `__pycache__`, test output처럼 재생성 가능한 파일만 canonical pointer가
  아님을 확인한 뒤 삭제한다.
- historical ID나 hash를 최신 숫자로 다시 쓰지 않는다.
- 계약 파일 삭제는 immutable reference 0건과 validation/rebuild use 0건을 별도 감사에서 증명한
  후 독립된 reviewed deletion으로 수행한다.
