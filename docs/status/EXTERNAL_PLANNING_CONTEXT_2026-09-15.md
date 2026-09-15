# EOM 외부 계획 수립용 현재 상태 문서

상태 기준 시각: 2026-09-15 11:23 UTC

대상 저장소: `/home/eom/EOM`

문서 목적: 기존 대화 맥락이 없는 별도 GPT가 EOM의 다음 개발·검증·배포 계획을 독립적으로 수립할 수 있도록 현재 사실, 검증 수준, 불확실성, 제약을 한 문서에 제공한다.

> Update: mutable runtime facts in this planning snapshot were rechecked later on 2026-09-15.
> Use `docs/status/RUNTIME_BASELINE_2026-09-15.md` as the authority for the current corpus
> denominator, solution-report progress, installed HWPX/image bytes, and active runner inventory.
> The architectural description and planning questions below remain applicable.

## 0. 이 문서를 읽는 GPT에게

이 문서는 계획안이 아니라 계획 수립에 필요한 상태 스냅샷이다. 다음 네 종류의 사실을 반드시 구분해야 한다.

| 표기 | 의미 |
| --- | --- |
| `REPOSITORY_VERIFIED` | 현재 Git 저장소의 코드·계약·테스트로 확인된 사실 |
| `LIVE_VERIFIED` | 명시된 UTC 시각에 운영 서비스나 운영 read-only 감사로 확인된 사실 |
| `HISTORICAL_ACCEPTANCE` | 과거 특정 실행에서 실제 완료·승인된 결과 |
| `UNKNOWN_OR_MUTABLE` | 인증된 현재 조회가 없거나 계속 변할 수 있어 재확인이 필요한 사실 |

특히 다음을 동일시하지 말아야 한다.

- GitHub `main`에 구현된 기능과 현재 서버에 배포된 기능
- Workflow가 기술 계약대로 완료된 사실과 문항의 교육적 품질
- RAG ingestion 완료와 모델 weight training
- RAG 근거가 검색·전달된 사실과 실제 근거 사용이 영수증으로 검증된 사실
- 과거 systemd transient unit의 `failed` 기록과 현재 장기 서비스 장애
- RAG Graph의 accepted base 수와 Item Registry 전체 current approved Item 수
- 저장소의 최신 additive 계약과 기존 실행이 고정한 이전 계약

계획을 제안할 때는 기존 검증을 약화하거나 released revision을 재해석하지 말고, 필요한 경우 successor 계약을 추가해야 한다.

## 1. 한 문장 요약

EOM은 기출 PDF를 weight training하지 않고 immutable Graph evidence로 구조화한 뒤, 격리된 역할별 worker가 근거를 인용해 통합과학 문항을 작성·검토하고, 사람 승인 후 immutable Item Revision과 PNG/HWPX를 생산하는 protocol-first 시스템이다. 단일 문항과 실제 25문항 전체 실행은 운영에서 성공한 적이 있으며, 최신 저장소에는 native 표/그림을 정확히 보여 주는 Item Preview V3와 프론트엔드–백엔드 정합성 게이트까지 구현되어 있다. 그러나 현재 운영 API와 Web은 GitHub `main`보다 이전 커밋을 실행 중이므로 최신 기능은 아직 live로 간주할 수 없다.

## 2. 현재 Git과 배포 상태

### 2.1 저장소 상태 — `REPOSITORY_VERIFIED`

| 항목 | 값 |
| --- | --- |
| branch | `main` |
| HEAD | `2e8e5c554b80d443f0754a730ec123ef134eb04d` |
| tree | `e1c88f25c3d7a16bf54547743c9172636ad33b13` |
| `origin/main` | HEAD와 동일 |
| worktree | clean |
| HEAD subject | `feat(web): add contract-checked item preview v3` |

최근 주요 커밋은 다음과 같다.

| UTC 시각 | commit | 의미 |
| --- | --- | --- |
| 2026-09-14 17:38 | `2e8e5c5` | Item Preview V3와 frontend/backend contract alignment |
| 2026-09-14 15:43 | `84613c0` | HWPX package image를 embedded로 명시 |
| 2026-09-14 15:26 | `166d657` | 호환 가능한 시험지 package reference 보존 |
| 2026-09-14 13:10 | `0aa6a8d` | 다음 검증 제품 게이트 문서화 |
| 2026-09-14 13:09 | `c50f978` | live V5 25문항/HWPX acceptance 기록 |
| 2026-09-14 12:43 | `3a5c6e4` | HWPX 수식 출력 의미를 명시적으로 검증 |

### 2.2 현재 설치된 서비스 코드 — `LIVE_VERIFIED`

| 서비스 | 설치된 source commit | GitHub `main`과의 관계 |
| --- | --- | --- |
| Application API | `3a5c6e44769e02417aa58f102e0d36bd9dc0cb42` | main의 ancestor, 6 commits 뒤처짐 |
| Scientific Studio Web | `a32a124b6cb68e624fc5acda3176216684a527a4` | main의 ancestor, 50 commits 뒤처짐 |

따라서 `2e8e5c5`의 Preview V3, 이후 HWPX image embedding 수정, 최신 cross-layer release gate는 현재 사이트에서 동작한다고 주장할 수 없다. 배포 전에 API·Web·관련 runtime wheel의 호환 배포 단위를 다시 확정해야 한다.

### 2.3 현재 서비스 상태 — `LIVE_VERIFIED`

2026-09-15 11:20–11:23 UTC read-only 확인 결과:

- Application API: systemd `active`, `/api/v1/health/live` = `LIVE`, `/api/v1/health/ready` = `READY`
- Scientific Studio Web: systemd `active`, Studio live = `LIVE`, ready = `READY`
- Web readiness가 보는 Application API와 Observability: 모두 `ACTIVE`
- Catalog application runner: `active`
- HWPX application runner: `active`
- Workflow runner 일반/production/backfill: 모두 `active`
- Workflow maintenance: `active`
- 현재 실행 중인 `eom-worker-*`, HWPX content-team transient unit, image-provider transient unit: 없음
- API와 Web의 현재 systemd `NRestarts=0`

systemd에는 과거 worker/HWPX/image transient unit의 `failed` 기록이 다수 남아 있다. 이것은 현재 장기 서비스가 내려갔다는 뜻은 아니지만, 운영 화면이나 일반적인 `systemctl --failed`만 보면 현재 장애로 오해될 수 있는 관측성 문제다. 성공·실패 receipt 보존과 transient unit 정리는 서로 다른 문제로 다뤄야 한다.

### 2.4 DB migration

- 저장소 Alembic head: `20260912_0035`
- 이 migration은 2026-09-12 배포 기록에서 운영 release migration PASS로 확인됐다.
- 그 이후 현재 HEAD까지 새 migration은 없다.

## 3. 제품 경계

현재 주 제품 경로는 통합과학 문항 제작이다.

```text
사용자 요청
  -> 현재 Workflow / Content Pack / 실행 정책 / Graph Revision 고정
  -> RAG Evidence Bundle 생성 및 검증
  -> Authoring worker
  -> Image worker (IMAGE 또는 MIXED일 때만)
  -> Review worker
  -> Human Approval
  -> Registration worker
  -> immutable Item Revision
  -> 선택적 단일 문항 또는 시험지 HWPX
  -> 인증된 다운로드
```

이 시스템은 “하나의 LLM 프롬프트가 문항 파일을 바로 생성”하는 구조가 아니다. 역할별 결과는 작은 typed contract로 전달되고, Orchestrator와 Catalog가 schema, pointer, revision, hash, lifecycle, evidence usage를 교차검증한다.

## 4. 시스템 구조와 책임

```text
Browser
  -> Scientific Studio BFF
      -> Application API
          -> application services / use cases
              -> Catalog application boundary
              -> PostgreSQL metadata/state
              -> Workflow command queue

PostgreSQL queue
  -> Workflow Runner
      -> Orchestrator
          -> isolated Authoring worker
          -> isolated Image worker
          -> isolated Review worker
          -> isolated Registration worker
      <- local typed results only
      -> validated Artifact commit to NAS

Approved Item Revision
  -> HWPX Manager
      -> isolated HWPX Builder
      <- local typed result
      -> validated HWPX Artifact commit to NAS
```

### 4.1 반드시 유지해야 하는 책임 경계

- Browser는 NAS path, Artifact ID, member path를 임의 입력하지 않는다.
- Worker끼리 직접 통신하지 않는다.
- Worker는 DB와 NAS에 쓰지 않는다.
- Worker는 staged local input을 읽고 local typed result만 제출한다.
- Orchestrator만 검증된 canonical Artifact를 NAS에 커밋한다.
- PostgreSQL에는 binary 전체나 대형 문항 복사본 대신 ID, revision, relation, state, pointer, hash를 저장한다.
- Catalog는 Item registration과 Graph/evidence application boundary를 소유한다.
- HWPX Manager는 delivery projection과 builder output validation을 소유한다.
- CLI와 GUI는 business invariant를 재구현하지 않고 application use case를 호출한다.

## 5. 불변 identity와 pointer 모델

EOM의 핵심 모델은 다음과 같다.

```text
logical entity
  -> immutable revision
      -> typed component pointers
          -> immutable Artifact Revisions
              -> SHA-256 content hashes
```

다음은 서로 다른 개념이며 하나로 합치면 안 된다.

- logical Item ID
- Item Revision ID
- Artifact ID
- Artifact Revision ID
- schema identity/version
- media type
- storage URI/path
- SHA-256 content hash
- mutable current-revision pointer
- immutable pinned revision

Pointer dereference는 최소한 target/revision 존재, permission, lifecycle, expected schema/version, media type, hash와 immutability를 검증해야 한다. missing, stale, deleted, hash mismatch를 “최신 revision”으로 자동 대체하지 않는다.

## 6. 현재 additive 계약 지도 — `REPOSITORY_VERIFIED`

| 경계 | 현재 저장소 family |
| --- | --- |
| 단일 문항 Workflow | `generic-item-development@1.10.0` |
| 역할 protocol | `workflow-role/1.20.0` |
| 역할 결과 | `authoring·image·review·registration-result@10.0` |
| Content Pack | `generated-knowledge-item@1.16.1` |
| 표준 control | `standard-control-bootstrap/13.0` |
| RAG control | `knowledge-item-control-bootstrap/10.0` |
| RAG Evidence | evidence manifest `2.0` |
| RAG 사용 증명 | evidence-usage validation receipt `1.0` |
| Canonical Item | `assessment-item-content/3.0` |
| Item Catalog protocol | `catalog/1.13` |
| 자료 형식 요구 | `content-team-material-requirement/1.0` |
| Item Brief | `4.0` |
| 로컬 이미지 result/provider/policy | result `10`, provider `1.0`, prompt policy `1.4` |
| HWPX | `hwpx-content-team/3.0` |
| 기출 풀이보고서 | `knowledge-analysis@10.0.0`, result `@10.0` |
| 25문항 생산 | production plan/execution `5.0` |
| Item Preview | `item-preview/3.0` |

이 버전들은 additive successor다. released V1–V4 Workflow/production execution/Pack의 의미를 바꾸거나 최신 버전으로 암묵 업그레이드하면 안 된다. 재현 가능한 과거 실행은 당시 revision을 계속 pin해야 한다.

## 7. RAG와 기출 학습 상태

### 7.1 “학습”의 정확한 의미

여기서 학습은 model weight training이 아니다. 기출 PDF를 문항, 페이지, source location, Graph node/edge/anchor, immutable evidence로 구조화하는 RAG ingestion이다.

### 7.2 검증된 기준선 — `HISTORICAL_ACCEPTANCE`

- 기출 source PDF: 50개
- 원래 승인된 기출 Item 분석: 520개
- 이후 승인된 canary Item이 additive lineage에 추가되어 corpus projection accepted base: 521개
- 2026-09-14 Preview 호환 read-only 감사에서 Item Registry의 current approved Item Revision: 558개
  - canonical V1: 4개
  - content-team V2: 3개
  - content-team V3: 31개
  - legacy V1 URI alias: 520개

`521`과 `558`은 서로 다른 projection의 분모다. 전자는 RAG Graph의 accepted analysis base이고, 후자는 Registry의 current approved Item Revision 전체다. 외부 계획이 이를 데이터 중복이나 누락으로 단정하면 안 된다.

### 7.3 근거 사용 검증

현재 trusted RAG path는 단순히 `graph_grounded=true`를 믿지 않는다.

1. Catalog가 pinned Graph Revision에서 bounded Evidence Bundle을 만든다.
2. Orchestrator가 exact manifest/context bytes를 local workspace에 materialize한다.
3. Authoring은 사용한 evidence ID, anchor ID, application 종류와 문항 draft의 RFC 6901 JSON Pointer를 선언한다.
4. Review는 같은 citation과 authoring Artifact를 독립적으로 확인한다.
5. Orchestrator는 cited evidence/anchor가 manifest와 Graph에 존재하고 각 draft pointer가 실제 non-null scalar leaf에 도달하는지 검증한다.
6. Orchestrator가 trusted validation receipt를 생성하고 Artifact success event와 결속한다.
7. 사람 승인 후 Catalog가 registration 전에 receipt, Artifact Revision과 hash를 다시 resolve한다.

따라서 현재 구조가 증명하는 것은 “검색 후보가 있었다”가 아니라 “정확한 immutable 근거가 특정 문항 위치에 적용됐다고 author/reviewer가 선언했고 시스템이 canonical bytes와 대조했다”는 사실이다. 과학적 타당성과 출제 가치는 여전히 reviewer가 평가해야 한다.

### 7.4 풀이보고서 보강 — `UNKNOWN_OR_MUTABLE`

기존 V9 분석은 보존한다. V10 successor가 다음을 additive Artifact로 추가한다.

- 외부 검토 가능한 풀이 단계
- 개념과 출제요소의 연결
- 선택지별 진단
- unresolved issue

이는 hidden chain-of-thought를 요구하거나 저장하는 기능이 아니다.

마지막 문서화된 운영 snapshot은 2026-09-14 13:06 UTC이며, 당시 521개 중 212개 완료, 309개 남음, duplicate accepted predecessor 0개였다. 2026-09-15 현재 transient worker 5/6이 실행 중이지는 않지만, 인증된 corpus projection을 이번 문서 작성 시점에 조회하지 못했으므로 최종 완료 수와 중단/완료 여부는 `UNKNOWN_OR_MUTABLE`이다. 다음 계획의 시작 gate에서 Studio 또는 typed API의 batch-free corpus projection으로 반드시 재조회해야 한다.

사용자 화면에는 batch/run/work-unit을 기본 노출하지 않는다. 사용자는 corpus 전체의 시험지·승인 문항·풀이보고서 진행률을 본다. ID 기반 endpoint는 삭제하지 않고 향후 관리자 상세 화면과 운영 감사에 사용한다.

## 8. 문항 자료 형식, 이미지와 HWPX

### 8.1 자료 형식이 이미지 실행을 결정한다

| 학생에게 보이는 자료 형식 | 이미지 step | HWPX 기대 결과 |
| --- | --- | --- |
| `TEXT` | skip | native text, PNG/이미지 placeholder 없음 |
| `DATA` | skip | native data structure, PNG 없음 |
| `INQUIRY` | skip | native inquiry structure, PNG 없음 |
| `TABLE`, 1 panel | skip | editable native table 1개, label/빈 이미지 칸 없음 |
| `TABLE`, 2 panels | skip | 서로 다른 native table 2개, `(가)/(나)`는 editable text |
| `IMAGE`, 1 panel | run | PNG 1개, `(가)/(나)` 없음 |
| `IMAGE`, 2 panels | run | ordered distinct PNG 2개, `(가)/(나)`는 별도 editable text row |
| `MIXED` | IMAGE slot만 run | IMAGE 1개와 TABLE 1개를 authored order로 배치, panel label 없음 |

중요한 제품 요구: 자료가 그림 없이 표 하나인 문항은 정상이다. 이 경우 정확한 결과는 `PNG 0 + native table 1 + panel label 0 + image placeholder 0`이다. 표를 이미지로 바꾸거나 빈 1행 2열짜리 그림 틀을 만들면 계약 위반이다.

### 8.2 GPU와 결정론적 overlay의 책임 분리

```text
변경하지 않는 콘텐츠팀장 source 2개 + KICE 삽화 guide
  -> Image worker가 실제 IMAGE slot별 drawing intent 작성
  -> local GPU가 bounded semantic raster 생성
  + deterministic sanitized SVG가 축, A/B/P/Q, 수치, 과학 label 생성
  -> immutable PNG Artifact Revision
  -> registered Item Revision의 slot을 따라 HWPX에 삽입
```

- 외부 LLM/image API는 사용하지 않는다.
- local GPU의 짧은 text encoder에는 worker가 정리한 bounded semantic subject와 흑백, 흰 배경, 장식 금지 같은 고정 정책을 준다.
- exact geometry와 label을 GPU가 임의로 그리게 하지 않는다.
- `(가)/(나)` panel label은 PNG에 rasterize하지 않고 HWPX editable text로 넣는다.
- IMAGE slot과 TABLE slot의 ordinal과 순서를 보존한다.

### 8.3 HWPX 무결성

현재 저장소의 HWPX 경계는 다음을 검증한다.

- input source를 final symlink follow 없이 open
- regular file, link count, size bound, fd identity before/after
- streaming SHA-256과 pinned hash 일치
- fresh target에만 materialize하고 실패 시 partial 제거
- builder JSON bounded read와 schema/Pydantic 검증
- ZIP path/CRC/core member 검사
- output hash와 committed Artifact primary 재대조
- package 내부 image relationship가 external path가 아니라 embedded member를 가리키는지 검증
- 서로 다른 Item header는 byte-stable append-only superset일 때만 whole-exam merge

## 9. 단일 문항과 25문항의 실제 검증 상태

### 9.1 단일 문항 — `HISTORICAL_ACCEPTANCE`

trusted RAG canary에서 실제로 다음 경계를 통과한 이력이 있다.

- exact PAST_EXAM evidence retrieval
- authoring/review citation equality
- Graph anchor resolution
- scalar leaf application pointer 검증
- human approval
- Catalog registration
- immutable approved Item Revision
- HWPX build와 download

초기 canary 과정에서는 prompt와 leaf-validator의 불일치, idempotency lease owner, Catalog protocol namespace 충돌 등이 실제로 발견됐고 additive/fail-closed 방식으로 수정됐다. 실패 row와 Artifact 이력은 덮어쓰지 않고 보존했다.

### 9.2 25문항 V5 — `HISTORICAL_ACCEPTANCE`

2026-09-14 Pack 1.16.1과 production plan/execution 5.0으로 fresh 25문항을 실제 생성했다.

- generation 완료
- role review 완료
- human approval 완료
- Item registration 완료
- knowledge analysis와 rating 완료
- assessment assembly 완료
- 동일 immutable Item set의 deterministic render 재검증 완료

공식 HWPX acceptance:

| 항목 | 값 |
| --- | --- |
| build ID | `hwpxbuild_f3686d5ca87042e390537464a49f1878` |
| bytes | 258,452 |
| sections | 25 |
| native equations | 81 |
| native tables | 7 |
| visual slots | 13 |
| PNG members | 6 |
| ZIP entries | 40 |
| output SHA-256 | `sha256:8eed5f6961a17df3f65ba62d42690659d9ad85bb9cc267ba6f58f5ecaf7983f8` |
| authenticated download | `https://eomai.duckdns.org/studio/api/v1/mock-exam-hwpx/builds/hwpxbuild_f3686d5ca87042e390537464a49f1878/download` |

이 결과는 “25문항 생산 경로가 기술적으로 실제 완료됐다”는 증거다. 25개 문항 전부의 교육적 품질이 충분하다는 증거는 아니다.

또한 공식 acceptance 기록 뒤에 HWPX compatible package reference와 embedded image 수정 커밋 `166d657`, `84613c0`이 추가됐다. 최신 수정이 포함된 runtime에서 동일 수준의 live whole-exam HWPX acceptance를 다시 수행했다는 문서화된 증거는 아직 없다. 이 차이는 다음 release verification에서 닫아야 한다.

## 10. Item Preview와 frontend/backend 상태

### 10.1 저장소의 Preview V3 — `REPOSITORY_VERIFIED`

최신 저장소에는 다음이 구현되어 있다.

- canonical Item Content V1, content-team V2/V3를 하나의 bounded `item-preview/3.0`으로 projection
- native paragraph/equation/table/image/statement block
- `TABLE_ONLY`를 native table로 표시하고 image 요청/빈 placeholder를 생성하지 않음
- approved Item Revision과 visual ordinal만 browser 입력으로 허용
- Browser same-origin -> Web BFF -> Application API `ITEM_READ` -> private Catalog media operation
- exact Item/revision/current/approved/workflow/Content Pack/ETag provenance 검사
- Artifact pointer의 logical/revision/hash/schema/media/member/ordinal 검사
- 빠른 항목 전환 시 monotonic request sequence로 늦게 온 이전 응답 무시
- preview 시작/실패 시 stale edit revision, ETag, HWPX target 제거
- browser route, BFF route, Application OpenAPI operation, renderer block set, DOM/module graph, Korean status vocabulary, wheel file inventory를 release-blocking test로 연결

Preview V3 설계 문서: `docs/architecture/ITEM_PREVIEW_V3.md`

### 10.2 live gap — `LIVE_VERIFIED`

현재 Web은 `a32a124`, API는 `3a5c6e4`이므로 Preview V3와 최신 media operation은 배포되지 않았다. 현재 사이트의 “미리보기 준비되지 않음”, 목록 새로고침, generic API request invalid 같은 문제를 `2e8e5c5`가 repository 수준에서 해결하더라도, live 배포와 authenticated browser smoke 전에는 사용자 문제가 해결됐다고 볼 수 없다.

이것은 현재 가장 명확한 repository/runtime drift다. API와 Web을 서로 다른 시점으로 부분 배포하면 cross-layer 계약 차이로 다시 오류가 날 수 있으므로 coordinated release가 필요하다.

## 11. 테스트와 release evidence

### 11.1 2026-09-14 최신 repository candidate — `REPOSITORY_VERIFIED`

- API/domain/Catalog/Orchestrator/Studio non-live: 2,924 passed
- HWPX/local-image: 197 passed
- integration collection pure test: 1 passed
- skip:
  - live/database API: 35
  - privileged HWPX: 1
  - explicit PostgreSQL/system: 126
- Ruff format/check: 1,331 files PASS
- strict mypy: 417 source files PASS
- focused Preview/Catalog/API/OpenAPI/browser/pointer/release integrity: PASS
- read-only production projection: current approved Item Revision 558/558 PASS

Skip은 운영 DB로 몰래 우회하지 않은 결과다. live/DB/privileged test는 명시적 opt-in 경계를 가져야 한다.

### 11.2 PostgreSQL persistence — `HISTORICAL_ACCEPTANCE`

- HWPX persistence 6 tests를 disposable PostgreSQL에서 실제 실행
- migration, runtime role reconciliation, release wheel inspection PASS
- disposable database cleanup PASS
- 운영 DB를 test target으로 사용하지 않음

### 11.3 latest release artifacts — `REPOSITORY_VERIFIED`, 배포 아님

`2e8e5c5`에서 build-only로 release wheel을 생성하고 package RECORD/source parity를 확인했다.

- Web wheel SHA-256: `343b133b3ceec552fbe03e50086f6ba3942ee1db8b17cd27362b8d5a38b93f14`
- API release wheel directory가 생성되고 세 wheel의 RECORD가 검증됨
- 이 wheel 생성은 배포나 서비스 재시작을 의미하지 않는다.

## 12. 현재 확인된 강점

1. Protocol-first JSON Schema 2020-12와 Pydantic의 이중 검증이 광범위하다.
2. immutable revision과 exact hash가 Workflow, RAG, Item, image, HWPX에 일관되게 적용된다.
3. Worker 격리와 Orchestrator-only NAS commit 경계가 명확하다.
4. RAG evidence usage가 boolean이 아니라 citation/anchor/draft location/receipt로 검증된다.
5. human approval과 immutable history를 우회하지 않는다.
6. table-only, image-only, mixed material을 하나의 모호한 “visual”로 합치지 않는다.
7. HWPX를 단순 파일 생성이 아니라 package/reference/hash/persistence 계약으로 다룬다.
8. production data를 건드리지 않는 read-only 감사와 disposable DB persistence test 경계가 있다.
9. 사용자 UI에서는 batch와 내부 key를 숨기되 관리자용 ID endpoint는 보존한다.
10. frontend/backend drift를 정적 route·schema·DOM·wheel inventory gate로 줄이기 시작했다.

## 13. 객관적으로 남은 불확실성·위험·누락 후보

아래 항목은 곧바로 버그라고 단정하는 목록이 아니라, 다음 GPT가 우선순위와 증거 수집 방법을 결정해야 하는 planning input이다.

### A. Repository와 live runtime의 명확한 불일치

- API는 main보다 6 commits, Web은 50 commits 이전 코드다.
- Preview V3와 최신 embedded-image 경계는 live 확인이 없다.
- API/Web/runner/HWPX wheel을 하나의 호환 release set으로 고정하고 배포해야 한다.
- 배포 후 source commit, tree/archive, installed wheel RECORD, migration, health, authenticated UI/API smoke를 함께 검증해야 한다.

### B. 최신 HWPX image embedding 수정의 live end-to-end 재검증 부족

- 과거 공식 25문항 HWPX는 유효한 acceptance 증거다.
- 그러나 그 기록 이후 image package relationship 수정이 추가됐다.
- 최신 source로 단일 IMAGE 1, IMAGE 2, MIXED와 전체 시험지에서 PNG가 package 안에 실제 embedded되고 외부 filesystem path를 참조하지 않는지 검증이 필요하다.
- 이미 생성된 binary를 Git에 넣지 말고 NAS Artifact/manifest로 보존해야 한다.

### C. 풀이보고서 521건 backfill의 현재 완료 상태 불명

- 마지막 확정 수치는 212/521이다.
- 현재 worker 5/6은 실행 중이지 않다.
- 완료, 정상 중단, 실패 중 무엇인지는 authenticated batch-free corpus projection 재조회 없이는 알 수 없다.
- 재개한다면 accepted V9 base당 accepted V10 successor 최대 1개 unique constraint, active/failed/retry classification, idempotent replay를 먼저 확인해야 한다.

### D. 사용자 품질 지표 부족

- 25문항 생성과 HWPX 성공은 기술 transport/contract 성공을 증명한다.
- 과학적 정확성, 근거 적절성, 기출 표현의 단순 변형 여부, 정답 유일성, 시각 정확성, 해설 품질, HWPX 수정 시간은 별도 측정이 필요하다.
- released prompt/Pack을 직접 수정하지 말고 측정 결과가 successor Pack을 정당화해야 한다.

### E. Historical transient failure의 관측성

- 현재 core 서비스는 healthy하지만 systemd failed transient unit 기록이 남아 있다.
- 사용자/관리자 화면은 현재 active failure와 immutable historical failure를 분리해야 한다.
- 정리 작업은 DB/Artifact/audit receipt를 삭제하면 안 된다. systemd unit state 정리도 증거 보존과 독립된 운영 절차여야 한다.

### F. Frontend/backend 정합성은 구현됐지만 live 운영 게이트가 아직 부족

- repository의 route/OpenAPI/schema/DOM/wheel gate는 강하다.
- 실제 reverse proxy, cookie/session, BFF timeout, same-origin media, authenticated download, stale browser cache까지 포함한 post-deploy smoke가 필요하다.
- generic `API request invalid`가 다시 생겼을 때 technical code와 correlation ID는 관리자에게 보이되, 기본 사용자 메시지는 행동 가능한 한국어여야 한다.

### G. Material matrix의 독립 회귀 유지

- heterogeneous 25문항 aggregate 성공만으로 모든 분기를 보장할 수 없다.
- TEXT, DATA, TABLE 1/2, IMAGE 1/2, MIXED, INQUIRY를 각각 독립 Item/manifest/Preview/HWPX까지 검증해야 한다.
- 특히 TABLE 1은 image 0·placeholder 0, IMAGE 1은 panel label 0, IMAGE 2는 distinct PNG 2·editable label 2를 exact count로 고정해야 한다.

### H. 관리자 관측성

- 기본 사용자 UI는 ID/key/batch/lease를 숨기는 현재 방향이 맞다.
- 관리자에게는 immutable IDs, revisions, hashes, state/event history, idempotency/retry, failure receipt, active lease와 installed source commit을 drill-down으로 제공할 필요가 있다.
- default user projection과 admin audit projection을 하나의 과도한 DTO로 합치지 않는 것이 바람직하다.

### I. Skipped integration/privileged tests의 지속 관리

- skip 자체는 안전 설계의 일부지만, 변경 경계와 실제 실행 gate가 명확해야 한다.
- DB schema/state-machine 변경은 disposable DB suite를 요구한다.
- filesystem privilege/runtime isolation 변경은 명시적 protected test environment가 필요하다.
- “모든 unit test PASS”를 “live integration PASS”로 표현하면 안 된다.

## 14. 기술적으로 변경하면 안 되는 원칙

다음은 계획의 제약이지 최적화 대상이 아니다.

1. `/home/eom/EOMIS`를 수정하지 않는다.
2. `/home/eom/EOM`의 별도 Git history를 유지한다.
3. cross-service/worker 변경은 JSON Schema 2020-12를 먼저 정의한다.
4. 향후 Pydantic model과 schema의 required/discriminator/hash 의미를 일치시킨다.
5. Worker 간 직접 통신, Worker의 DB/NAS 쓰기를 허용하지 않는다.
6. 외부 LLM API와 외부 image API를 사용하지 않는다.
7. root Codex auth나 운영 secret을 worker에 복사하지 않는다.
8. logical ID, revision, Artifact ID/revision, hash를 하나의 문자열이나 path로 축약하지 않는다.
9. external file은 untrusted로 취급한다.
10. ambient Python을 사용하지 않고 명시적 Conda runtime을 사용한다.
11. HWPX, PNG, PDF, long log와 generated artifact를 Git에 넣지 않는다.
12. released contract/Pack/revision을 수정하거나 과거 실행의 의미를 바꾸지 않는다.
13. missing/stale/hash mismatch를 암묵적 latest fallback으로 복구하지 않는다.
14. batch 정보를 기본 사용자 화면에 노출하지 않는다.
15. ID 기반 기능은 삭제하지 않고 관리자용으로 유지한다.
16. core protocol/storage/state-machine/worker 변경은 focused tests 없이 merge하지 않는다.
17. Slack 개발 보고 실패가 개발/runtime을 막아서는 안 되며 secret, full log, worker prompt/result, Item content를 보내지 않는다.

## 15. 데이터 구조와 성능 관점의 요구

다음 계획에서 새 DB/query/cache/queue/registry가 필요하면 먼저 access pattern을 명시해야 한다.

- identity lookup: dict/map 또는 indexed DB key
- membership/dedup: set/hash/unique constraint
- command processing: indexed queue와 explicit claim
- Workflow dependency: DAG/adjacency representation
- state/event history: append-only monotonic sequence
- revision: immutable linked relation
- component assembly: typed manifest와 keyed lookup
- Graph relationship: adjacency/indexed relation

반복 list scan, list membership 기반 dedup, N+1 query, immutable file의 반복 parse/hash, DB에 large binary 저장을 피한다. 성능 개선은 query plan, benchmark, profiler 또는 명백한 complexity 개선으로 근거를 남긴다.

## 16. 다음 계획이 반드시 답해야 할 질문

1. GitHub `main`과 현재 API/Web 배포의 차이를 어떤 atomic 또는 staged release 단위로 닫을 것인가?
2. 부분 배포 중 frontend/backend contract mismatch를 어떻게 fail-closed하고 rollback할 것인가?
3. Preview V3를 live로 승인하기 위한 최소 authenticated browser/API/media/HWPX smoke matrix는 무엇인가?
4. latest embedded-image 수정으로 single Item과 25-Item HWPX를 다시 검증해야 하는가? 그렇다면 기존 Item/assembly를 재사용할지 fresh successor를 만들지 어떻게 결정할 것인가?
5. solution-report progress를 batch-free typed projection으로 재확인하고 521개를 안전하게 완료하기 위한 idempotency/uniqueness/quiescence gate는 무엇인가?
6. material matrix 각 분기를 어떤 fixture와 실제 Artifact로 독립 검증할 것인가?
7. 기술 성공과 교육 품질을 분리해 reviewer scorecard와 acceptance threshold를 어떻게 수집할 것인가?
8. historical transient failure를 지우지 않으면서 현재 장애와 구분하는 admin observability를 어떻게 설계할 것인가?
9. repository 정적 alignment gate를 reverse proxy/session/cache/runtime까지 확장할 때 최소한의 유지보수 구조는 무엇인가?
10. 각 단계의 rollback, retry, idempotency, immutable receipt, STOP 조건은 무엇인가?

## 17. 별도 GPT에 요청할 권장 출력 형식

이 문서만 읽고 다음 형식으로 계획을 작성하라.

1. **사실 검증:** 문서에서 확정된 사실, mutable 재확인 필요 사항, 추론을 분리한다.
2. **문제 목록:** P0/P1/P2로 분류하고 사용자 영향, 데이터/보안/재현성 위험을 설명한다.
3. **권장 순서:** dependency DAG 또는 numbered milestones로 제시한다.
4. **각 milestone:**
   - 목표와 비목표
   - 책임 모듈과 dependency direction
   - protocol/schema/model 변경 여부
   - canonical source와 pointer model
   - DB/index/migration 여부
   - transaction/concurrency/idempotency
   - unit/integration/live test matrix
   - deploy/rollback/STOP 조건
   - 완료 증거
5. **호환성:** released V1–V5와 기존 Artifact/receipt를 어떻게 보존하는지 설명한다.
6. **운영 확인:** repository candidate와 installed runtime을 혼동하지 않는 검증 절차를 작성한다.
7. **제품 확인:** 기술 게이트와 reviewer 품질 게이트를 별도 트랙으로 작성한다.
8. **최소화:** 새 framework보다 기존 경계 확장을 우선하고, 각 abstraction/dependency의 필요성을 설명한다.

계획은 검증을 완화하거나 “일단 latest로 바꾸기”, “DB row 직접 수정”, “failed history를 성공으로 재해석”, “worker에 NAS 권한 부여”, “테스트를 운영 DB로 우회”하는 방법을 제안하면 안 된다.

## 18. 주요 근거 문서와 코드 위치

| 경로 | 용도 |
| --- | --- |
| `README.md` | 제품 경계와 additive version map |
| `docs/status/CURRENT_SYSTEM_STATUS.md` | 2026-09-14 repository/operational status |
| `docs/architecture/ITEM_PREVIEW_V3.md` | native preview와 frontend/backend alignment |
| `docs/architecture/KNOWLEDGE_BACKED_ITEM_EXECUTION_V3.md` | trusted evidence materialization |
| `docs/architecture/TRUSTED_EVIDENCE_REGISTRATION_GATE.md` | registration receipt re-resolution |
| `docs/architecture/MOCK_EXAM_TRUSTED_RAG_PRODUCTION_V3.md` | pinned 25-Item RAG family의 기반 |
| `docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md` | local raster/compositor 책임 |
| `docs/adr/0073-additive-past-exam-solution-reports.md` | additive 풀이보고서 |
| `docs/adr/0076-content-team-prompt-to-hwpx-preflight.md` | visual intent와 HWPX preflight |
| `docs/adr/0077-material-first-item-and-independent-hwpx-acceptance.md` | material-first contract |
| `docs/adr/0078-hwpx-exam-header-superset-merge.md` | whole-exam HWPX resource merge |
| `docs/adr/0090-content-team-explicit-equation-and-output-acceptance.md` | 수식/output acceptance |
| `docs/operations/API_INTEGRATION_TEST_DATABASE.md` | disposable PostgreSQL test boundary |
| `schemas/` | canonical JSON Schema 2020-12 |
| `packages/` | typed domain/API/pointer contracts |
| `services/` | Orchestrator, Catalog, runners, HWPX boundaries |
| `apps/` | API, Web, observability, CLI interfaces |
| `content/packs/` | immutable Content Pack successors |
| `config/workflows/` | immutable Workflow definitions |
| `config/control-plane/` | versioned execution/knowledge controls |

## 19. 현재 시점의 가장 중요한 결론

EOM은 더 이상 “RAG나 HWPX가 가능한지 모르는 초기 설계” 상태가 아니다. 실제 단일 문항과 25문항, evidence receipt, 사람 승인, Item registration, whole-exam HWPX까지 운영 acceptance가 존재한다. 현재 핵심 과제는 새 기능을 무작정 늘리는 것이 아니라 다음 세 층을 일치시키는 것이다.

```text
GitHub repository의 최신 검증 후보
  == 실제 설치된 API/Web/runner/HWPX release set
  == 사용자가 브라우저에서 경험하는 Preview/다운로드/오류 의미
```

그 다음에야 solution-report corpus 완결, material별 독립 회귀, reviewer 품질 측정과 관리자 관측성을 순차적으로 진전시키는 것이 안전하다. 이 우선순위 자체는 외부 GPT가 다시 검토할 수 있지만, repository와 live runtime의 현재 불일치는 반드시 계획의 명시적 선행 조건으로 다뤄야 한다.
