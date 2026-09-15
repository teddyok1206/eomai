# EOM Scientific Studio

> 기출·교과서 근거를 검색하고, 역할별 검증과 사람 승인을 거쳐 문항을 등록한 뒤 HWPX로
> 전달하는 protocol-first 평가 문항 제작 플랫폼

EOM은 하나의 프롬프트가 문항 파일을 바로 만드는 도구가 아닙니다. 요청 시점의 Workflow,
Content Pack, 실행 정책과 RAG 근거를 불변 Revision으로 고정하고, 격리된 worker의 구조화 결과를
JSON Schema 2020-12와 Pydantic으로 검증합니다. 승인된 결과만 Item Revision으로 등록되며 PNG와
HWPX는 그 정본을 참조하는 별도 Artifact Revision입니다.

```text
logical Item
  -> immutable Item Revision
    -> typed component pointers
      -> immutable Artifact Revisions
        -> SHA-256 content hashes
```

## 지금 할 수 있는 일

- Scientific Studio에서 통합과학 단일 문항을 요청하고 진행 상태 확인
- Authoring → Image(조건부) → Review → Human Approval → Registration 실행
- 검증된 기출 PDF Graph를 검색해 Evidence Bundle을 만들고, 인용한 evidence·anchor·문항 적용
  위치를 authoring/review 영수증으로 다시 검증
- 표, 수식, `<자료>`, `<조건>`, 탐구, `ㄱ/ㄴ/ㄷ`, 5지선다와 해설을 구조화된 Item으로 등록
- 로컬 GPU 이미지와 결정론적 SVG를 합성하되 외부 LLM·이미지 API는 사용하지 않음
- 승인 Item Revision을 단일 문항 또는 시험지 HWPX로 만들고 보안 다운로드
- 승인 문항, HWPX build, RAG 학습 현황과 Codex slot 사용 상태 조회
- 25문항 모의고사 생산 계획·실행·검토·퇴역을 불변 checkpoint와 영수증으로 관리

## 현재 저장소 릴리스 선

아래 값은 기존 실행의 의미를 바꾸지 않고 추가된 최신 계약입니다. 저장소에 존재한다는 사실과
운영 환경에서 현재 활성화되었다는 사실은 구분합니다. 정확한 활성 상태는 Studio와 서비스
readiness가 정본입니다.

| 경계 | 최신 additive 계약 |
| --- | --- |
| 단일 문항 Workflow | `generic-item-development@1.10.0` |
| 역할 protocol / 결과 | `workflow-role/1.20.0` / `authoring·image·review·registration-result@10.0` |
| Content Pack | `generated-knowledge-item@1.16.1` |
| 표준 / RAG 실행 정책 | `standard-control-bootstrap/13.0` / `knowledge-item-control-bootstrap/10.0` |
| Canonical Item | `assessment-item-content/3.0`, Catalog protocol `catalog/1.13` |
| HWPX | `hwpx-content-team/3.0` |
| 로컬 GPU prompt policy | `local-gpu-image-prompt-policy/1.4` |
| 기출 풀이보고서 Workflow | `knowledge-analysis@10.0.0`, result `@10.0` |
| 자료 형식 | `content-team-material-requirement/1.0`, Item Brief `4.0` |
| 25문항 생산 | `mock-exam-production-plan/5.0`, execution `5.0` |

`mock-exam-production-plan/5.0`은 Workflow 1.10, role 1.20, Pack 1.16.1, Item Brief 4.0과
자료 형식 1.0을 함께 고정합니다. V5는 선택된 자료 형식을 authoring의 단일 권위로 사용합니다.
각 문항이 요구하는 `TEXT`, `DATA`, `TABLE`, `IMAGE`, `MIXED`, `INQUIRY`에서 이미지 step과 RAG
검색 요소를 파생하며, V1–V4 계획과 checkpoint는 기존 실행 재현을 위해 그대로 읽을 수 있고
의미를 바꾸지 않습니다.

## RAG 학습의 의미와 현재 기준선

EOM에서 “기출 학습”은 모델 weight training이 아니라 PDF를 검증 가능한 문항·페이지·anchor와
Graph evidence로 구조화하는 RAG ingestion입니다. 현재 typed corpus 기준선은 기출 PDF 50개와
occurrence-backed 승인 기출 문항 분석 520개입니다. 별도로 승인된 trusted-RAG 카나리 문항은
신규 문항의 독립 lineage이며 이 520개 풀이보고서 target에 합산하지 않습니다. 생성 worker는 원
PDF 전체를 복사받지 않고, 권한·Revision·Schema·Hash를 확인한 Evidence Bundle의 bounded
context만 받습니다.

근거를 실제로 사용했는지는 `graph_grounded=true` 같은 boolean 하나로 판정하지 않습니다.
Authoring과 Review가 동일한 evidence와 anchor, 문항 JSON Pointer를 선언하고 Orchestrator가
Graph snapshot 및 Artifact bytes에 대해 이를 재검증한 영수증을 남깁니다. 기출 풀이 논리와
개념→출제요소 연결은 기존 분석을 바꾸지 않는 additive 풀이보고서 Artifact로 축적합니다.

사용자 화면은 시험지 수, 승인 문항 수, 풀이보고서 완료 수처럼 corpus 전체 기준으로 보여 줍니다.
내부 batch는 실행·복구 구현 세부사항이므로 노출하지 않습니다. ID와 hash 기반 조회 기능은 운영과
관리자 감사를 위해 유지하되 기본 화면에서는 숨기고 필요한 상세 화면에서만 제공합니다.

Scientific Studio의 완성 문항 미리보기는 Item Preview 3.0으로 V1/V2/V3 정본을 하나의 bounded
표현 계약에 투영합니다. 표만 있는 자료는 native 표로, 그림은 승인된 Item Revision의 같은-origin
visual URL로 표시합니다. 조회 실패나 빠른 문항 전환이 발생하면 이전 편집·HWPX 대상은 즉시
해제되고 늦게 도착한 이전 응답은 무시됩니다. 브라우저 route, BFF route, Application OpenAPI,
상태 어휘, DOM/module, wheel 파일 목록은 자동 정합성 검사로 함께 변경되어야 합니다. 자세한
경계는 [Item Preview V3](docs/architecture/ITEM_PREVIEW_V3.md)에 정리했습니다.

## 한 문항이 만들어지는 과정

```mermaid
flowchart LR
  R[Request] --> P[Pinned Workflow<br/>Pack · Policy · Graph]
  P --> A[Authoring]
  A --> I{Required material}
  I -->|TEXT · DATA · TABLE · INQUIRY| V[Review]
  I -->|IMAGE · MIXED| G[Local GPU + SVG]
  G --> V
  V --> H{Human approval}
  H -->|rework| A
  H -->|approve| C[Registration]
  C --> IR[Approved Item Revision]
  IR --> X[HWPX projection]
  X --> D[Secure download]
```

1. 작은 typed request를 검증하고 현재 Workflow·Pack·실행 정책 Revision을 고정합니다.
2. Catalog가 pinned Graph에서 bounded Evidence Bundle을 만들고 Orchestrator가 local workspace에
   materialize합니다.
3. Worker는 서로 통신하지 않고 staged input을 읽어 typed local result만 제출합니다.
4. Orchestrator는 schema, pointer, hash, RAG citation과 state transition을 검증한 뒤에만 NAS에
   canonical Artifact를 커밋합니다.
5. 사람 승인 후 Catalog가 Item Revision을 등록합니다.
6. HWPX Manager는 Item Revision과 HwpQuestionEditor handoff를 고정해 전달 Artifact를 만듭니다.

## 이미지와 HWPX 배치 계약

콘텐츠팀장 원문 두 개와 KICE 삽화 가이드는 원본 bytes와 SHA-256을 그대로 보존합니다. Image
worker는 세 파일을 순서대로 모두 읽고 authoring 결과의 실제 `visuals` 배열에서 IMAGE slot만
투영합니다.

| 학생에게 보이는 자료 구조 | PNG | HWPX 배치 |
| --- | --- | --- |
| TEXT / DATA / INQUIRY | 생성하지 않음 | 각 native 본문·자료·탐구 구조만 배치 |
| TABLE 1개 | 생성하지 않음 | 편집 가능한 native 표 1개, panel label·빈 이미지 칸 없음 |
| TABLE 2개 | 생성하지 않음 | 서로 다른 표 칸에 native 표 2개, `(가)/(나)`는 편집 가능한 텍스트 |
| IMAGE 1개 | PNG 1개 | `(가)/(나)` 없이 단일 영역 |
| IMAGE 2개 | 서로 다른 PNG 2개 | 서로 다른 표 칸에 배치하고 `(가)/(나)`는 편집 가능한 텍스트 행 |
| IMAGE + TABLE | IMAGE slot에만 PNG 1개 | 실제 요소 순서를 유지하고 두 요소 모두 panel label 없음 |

즉 `<자료>`가 그림 없이 표 하나인 문항은 정상적인 독립 형식입니다. `TABLE_ONLY`는 정확히
`PNG 0개 + native 표 1개 + panel label 0개 + 이미지 placeholder 0개`이며 Image worker를
실행하지 않습니다. 표를 이미지로 바꾸거나 빈 1행 2열 이미지 틀을 만드는 것은 계약 위반입니다.

`A`, `B`, `P`, `Q`, 축, 수치 같은 과학적 표시는 panel label과 다릅니다. 이 값은 GPU 픽셀이
아니라 sanitizer를 통과한 결정론적 SVG overlay가 담당합니다. 로컬 GPU에는 worker가 작성한 짧은
의미 설명과 흑백·흰 배경·장식 금지 정책만 전달하고, 전체 팀장 원문과 정확한 기하·label은
Artifact provenance와 검증 단계에 남깁니다. HWPX staging은 symlink를 따르지 않는 file descriptor,
bounded read, SHA-256, identity 재확인과 fresh-target copy를 사용합니다.

서로 다른 자료 형식을 한 시험지로 합칠 때 per-Item HWPX header가 완전히 같은 bytes가 아닐 수
있습니다. Whole-exam renderer는 기존 정의가 정확한 prefix인 append-only header superset만
선택하고, 같은 ID의 의미가 바뀌거나 두 header가 비교 불가능하면 실패합니다. 일반적인 XML 합성이나
style ID 재번호 매기기는 하지 않습니다.

자세한 경계와 실패 규칙은
[Content-team prompt to HWPX preflight](docs/adr/0076-content-team-prompt-to-hwpx-preflight.md)에
정리되어 있습니다.

## 시스템 구조

```mermaid
flowchart TB
  Browser[Browser] -->|HTTPS| Studio[Scientific Studio BFF]
  Studio -->|loopback| API[Application API]
  Studio -. read-only .-> Observe[Observability]

  API --> Catalog[Catalog application]
  API --> DB[(PostgreSQL metadata)]
  DB --> Runner[Workflow Runner]
  Runner --> Orch[Orchestrator]
  Orch --> A[Authoring worker]
  Orch --> I[Image worker]
  Orch --> R[Review worker]
  Orch --> M[Registration worker]
  A & I & R & M -->|local typed result| Orch
  Orch -->|validated commit only| Store[(Immutable Artifact Store)]
  Catalog --> Registry[Item Registry]
  Registry --> DB

  DB --> HM[HWPX Manager]
  HM --> HB[Isolated HWPX Builder]
  HB -->|local result| HM
  HM --> Store
```

Browser가 접근하는 공개 경계는 Scientific Studio뿐입니다. Worker와 HWPX Builder는 DB·NAS·다른
worker에 직접 접근하지 않습니다. PostgreSQL에는 binary나 전체 문항 복사본 대신 identity,
Revision, 관계, 상태, pointer와 hash만 저장합니다.

## 설계 원칙

- **Protocol first:** JSON Schema 2020-12를 먼저 추가하고 Pydantic과 동작을 뒤따르게 합니다.
- **Pinned provenance:** logical ID, revision ID, Artifact ID, Artifact Revision ID와 content hash를
  서로 다른 불변 개념으로 유지합니다.
- **Fail closed:** missing, stale, lifecycle, schema/media, permission, hash 불일치를 최신값으로
  대체하지 않습니다.
- **One canonical artifact:** workspace는 임시 materialization이며 정본은 등록된 Revision입니다.
- **Orchestrated isolation:** worker 간 직접 통신과 NAS 쓰기를 금지합니다.
- **Explicit state machines:** Workflow, job, approval, build와 lease는 전이표와 append-only event로
  관리합니다.
- **Idempotent boundaries:** HTTP command, Workflow step, registration과 build는 입력 identity로
  exact replay와 conflict를 구분합니다.
- **Human authority:** 자동 검토는 증거이고 최종 승인은 사람의 결정입니다.

## 현재 검증 상태

2026-09-15 로드맵 상태는 다음과 같습니다. Preview V3와 인증 HWPX 다운로드는 사용자가 실제
브라우저에서 확인했고, Hancom 내부 레이아웃·편집성은 최종 수동 확인 목록에 남아 있습니다.
기존 25문항은 개별 HWPX 25개가 아니라 하나의 승인 Assembly와 whole-exam HWPX로 제공되는 것이
현재 제품 계약입니다.

- S01–S04 자동화 경계: PASS; Gate A browser/download: PASS;
- M02: 기존 25문항의 사람 품질평가 worksheet 준비 완료, 평가는 진행 전;
- M03 자동 UX 기반과 M04 관리자 관측성: PASS;
- L01 제한 교과서 evidence 기술 파일럿: PASS, 교육적 개선 효과는 미평가;
- L02 반복 생산 기술 경계: PASS, M02 결과 전 새 25문항 생성은 시작하지 않음;
- L03 두 support slot 측정: 33.5분 동안 17개 승인, 백업 manifest source hardening PASS;
- M01 풀이보고서: 362/520 완료 지점의 worker 결과 중복 ID 1건을 validator가 차단했고,
  exact deterministic retry 1건으로 16:21 UTC에 안전 재개.

M01의 실패는 Artifact commit 전에 차단됐으며 이력은 보존됩니다. 16:21 UTC 재개 직후 typed
projection은 362 완료, active 2, pending 156, failed 0, 중복 승인 0이었습니다. 최신 mutable 값은
[M01 기록](docs/status/M01_SOLUTION_REPORT_BACKFILL_2026-09-15.md),
[L03 기준선](docs/status/L03_SOLUTION_REPORT_CAPACITY_BASELINE_2026-09-15.md), 그리고 Studio typed
projection을 확인해야 합니다.

2026-09-13 저장소 후보는 runtime별 명시적 환경에서 non-live 테스트 2,916개를 통과했고, 158개
live·DB·privileged opt-in 테스트는 조건 미설정으로 skip했습니다.

- API·domain·Catalog·Orchestrator·GUI: 2,755 passed / 35 skipped
- HWPX 전체 + local image adapter: 160 passed / 1 skipped
- PostgreSQL integration collection: 1 passed / 122 skipped
- Ruff format/check 전체 1,301개 파일, strict mypy 414개 source 파일
- V4 schema 재생성, JSON Schema 2020-12, canonical/package byte parity, shell syntax와 Git whitespace

세 release wheel을 실제로 만들고 V4 plan/execution schema와 HWPX renderer가 저장소 원본과
byte-for-byte 같은지도 확인했습니다.

이후 2026-09-14에는 현재 release 선에서 API suite 511개가 통과하고 14개 opt-in이 skip됐으며,
HWPX 전체 및 관련 Application 경계 225개가 통과하고 privileged 1개가 skip됐습니다. HWPX
persistence 6개는 운영 DB가 아닌 명시적 disposable PostgreSQL에서 실행됐고, migration·runtime
role·release wheel 검증까지 통과한 뒤 그 DB를 제거했습니다.

Item Preview 3.0과 프론트엔드–백엔드 정합성 게이트를 포함한 최신 저장소 후보는 표준 non-live
진입점에서 API/domain/Catalog/Orchestrator/Studio 2,924개, HWPX/local-image 197개, integration
collection 순수 테스트 1개를 통과했습니다. live·DB·privileged opt-in 162개는 운영 환경으로
우회하지 않고 명시적으로 skip했습니다. Ruff는 1,331개 파일, strict mypy는 417개 source를
통과했습니다.

Pack 1.16.1과 production plan/execution 5.0은 운영에서 실제 25문항 생성·검토·승인·등록까지
완료했습니다. 같은 immutable Item set을 공식 HWPX API로 빌드해 25개 section, native 수식 81개,
native 표 7개, visual 13개와 PNG 6개를 검증했고, 출력의 SHA-256·ZIP entry·CRC·경로 안전성도
재확인했습니다. 로그인한 Studio 사용자는
[검증된 25문항 HWPX를 다운로드](https://eomai.duckdns.org/studio/api/v1/mock-exam-hwpx/builds/hwpxbuild_f3686d5ca87042e390537464a49f1878/download)할 수 있습니다.

기출 풀이보고서 보강의 모집단은 occurrence-backed 원 기출 분석 520개입니다. 별도 trusted-RAG
canary는 의도적으로 제외합니다. 2026-09-15 15:38 UTC에는 362개 완료 후 한 worker 결과가 중복
node identity로 검증 실패하여 refill이 안전 정지했습니다. 실패 이력은 보존했고, DB 수정이나 새
임의 key가 아니라 기존 exact allowlist와 deterministic retry 경계로 16:21 UTC에 재개했습니다.
이 수치는 mutable 운영 상태이므로 최종 정본은 Studio의 batch-free corpus 집계입니다.

더 자세한 구현/운영 구분과 남은 경계는
[Current System Status](docs/status/CURRENT_SYSTEM_STATUS.md)를 참고하십시오.

## 저장소 구조

| 경로 | 책임 |
| --- | --- |
| `schemas/` | canonical JSON Schema 2020-12 |
| `packages/` | domain contracts, typed pointer, identifier, API DTO |
| `services/` | Orchestrator, Workflow Runner, Catalog, HWPX Manager/Builder |
| `apps/` | Application API, Scientific Studio, observability, `eomctl` |
| `config/workflows/` | 불변 Workflow 정의 |
| `config/control-plane/` | 버전 고정 실행·지식 정책 |
| `content/packs/` | Content Pack, role profile과 prompt template |
| `migrations/` | PostgreSQL schema revision |
| `infra/` | 명시적 Conda, systemd와 운영 경계 |
| `scripts/` | schema 생성, 검증, release와 격리 test 도구 |
| `docs/adr/` | 변경 이유와 불변성 결정 |
| `docs/operations/` | 설치·검증·복구 runbook |

## 개발과 검증

```bash
git clone git@github.com:teddyok1206/eomai.git
cd eomai

/srv/eom/conda/envs/eom-api/bin/ruff format --check .
/srv/eom/conda/envs/eom-api/bin/ruff check .
/srv/eom/conda/envs/eom-api/bin/python -m mypy --cache-dir=/tmp/eom-mypy-cache
scripts/infra/test_repository_non_live.sh
scripts/infra/check_repository_boundaries.sh
git diff --check
```

각 runtime은 `infra/conda/`의 명시적 환경을 사용합니다. HWPX test는 `eom-hwpx`, API·Catalog·
Orchestrator test는 `eom-api`, 실제 GPU runtime은 `eom-image` 환경에서 실행합니다. 위 스크립트는
서로 다른 Pydantic runtime을 한 Python process에 섞지 않고 non-live suite를 분리하며, live·DB·
privileged opt-in 변수가 설정돼 있으면 실행을 거부합니다. PostgreSQL integration은 배포 DB가 아니라
[API Integration Test Database](docs/operations/API_INTEGRATION_TEST_DATABASE.md)의 disposable DB를
사용해야 합니다.

## 핵심 문서

- [Current System Status](docs/status/CURRENT_SYSTEM_STATUS.md)
- [M01 Solution-report Backfill Recovery](docs/status/M01_SOLUTION_REPORT_BACKFILL_2026-09-15.md)
- [M02 25-Item Educational Review Baseline](docs/status/M02_25_ITEM_EDUCATIONAL_REVIEW_BASELINE_2026-09-15.md)
- [Repository agent rules](AGENTS.md)
- [Knowledge-backed Item Execution V3](docs/architecture/KNOWLEDGE_BACKED_ITEM_EXECUTION_V3.md)
- [Trusted Evidence Registration Gate](docs/architecture/TRUSTED_EVIDENCE_REGISTRATION_GATE.md)
- [Mock-exam Trusted RAG Production V3](docs/architecture/MOCK_EXAM_TRUSTED_RAG_PRODUCTION_V3.md)
- [Material-first Item and independent HWPX acceptance](docs/adr/0077-material-first-item-and-independent-hwpx-acceptance.md)
- [HWPX whole-exam append-only header merge](docs/adr/0078-hwpx-exam-header-superset-merge.md)
- [HWPX explicit equation and output acceptance](docs/adr/0090-content-team-explicit-equation-and-output-acceptance.md)
- [Education Knowledge and Assessment Item GraphRAG](docs/architecture/EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md)
- [Additive Past-exam Solution Reports](docs/adr/0073-additive-past-exam-solution-reports.md)
- [Batch-independent Solution Scheduling](docs/adr/0074-batch-independent-additive-solution-scheduling.md)
- [Local GPU Image Orchestration](docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md)
- [Local GPU Image Prompt Policy](docs/architecture/LOCAL_GPU_IMAGE_PROMPT_POLICY_V1.md)
- [HWPX Application API](docs/architecture/HWPX_APPLICATION_API_V0.md)
- [Scientific Studio Design System](docs/product/EOM_SCIENTIFIC_WORKBENCH_DESIGN_SYSTEM.md)
- [Application API Troubleshooting](docs/operations/API_TROUBLESHOOTING.md)

## 보안

Secret, token, credential, `.env`, Codex auth, SSH key와 DB URL을 Git에 넣지 않습니다. 외부 파일은
모두 untrusted input으로 취급합니다. HWPX, PNG, AI, PDF, 장기 log와 backup은 Git이나 PostgreSQL이
아니라 manifest가 있는 Artifact storage에 보관합니다. 새 EOM service는 port 8000을 사용하지
않으며 Application API의 예약 bind는 `127.0.0.1:8765`입니다.
