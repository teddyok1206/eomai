# PDF와 한글 자료 통합 학습

2026-11-05 UTC. 설계 D2. 초안 D0 이후 두 차례 코드 대조 설계 검토를 반영했다.
최종 범위는 사용자의 후속 지시에 따라 **운영 배포와 실제 업로드 처리 확인까지**다.
초기 goal 카드에 남은 배포 직전 제한은 이 후속 지시로 대체한다.

## 목표와 사용자 흐름

`데이터 → 자료 학습`에서 PDF/HWP/HWPX 자료를 올리면 설명 부분은 원문에 연결된
지식으로, 문제·정답·해설은 기존 문항 단위로 구조화한다. 문항을 직접 풀어 확인한
공개 풀이보고서·출제 개념·관계·주의사항을 남기고, 기존 공통 Graph와 증분 임베딩에
연결한다. 출처와 사람 승인 여부는 별개다. 배치·내부 key는 기본 화면에서 숨긴다.

사용자는 자료 제목·종류·출처 설명과 처리 권한 확인을 입력한다. 선택적으로 별도
해설 파일과 교과/단원 힌트를 제공한다. 모르는 발행 정보·기출 회차는 만들어 채우지
않는다. 업로드는 빨리 접수하고, 변환·렌더링·AI 분석은 백그라운드에서 진행한다.
큰 책을 HTTP 요청 하나 안에서 전부 처리하지 않는다.

```text
원본 업로드와 권한 확인
  → 실제 형식 검사 및 원본 Artifact 보존
  → PDF 관찰 입력과 한글 본문 개체 준비
  → 작은 페이지 범위별 구성 발견 및 coverage 확인
  ├─ 설명·정의·표·탐구 → 기존 문서 지식 분석 → accepted analysis
  └─ 문제·정답·해설 대응 → 문항 추출·독립 풀이 → 기존 Item Registry
                                                → 공개 풀이·accepted analysis
  → 기존 공통 Graph의 안전한 증분 등록
  → 기존 GPU INDEX owner가 준비된 문항을 증분 반영
  → DB·Map·검색에서 조회
```

한 번에 학습 AI 작업 하나만 실행한다. 기존 Orchestrator의 실제 슬롯 claim/lease를
사용하고, 준비/저장 중에는 슬롯을 쥐고 있지 않는다. 고정된 로그인 계정이나 새 worker
사용자를 만들지 않는다. 실행은 공개된 정확한 preset/definition을 pin한다.

권리 확인은 실제 업로더와 source hash에 묶고, 기존 교과서의 구매·협상 사실을 가정하지
않는다. 원본·분석 PDF·전체 페이지·picture catalog는 자료별로 한 번 보관하며 문항/단원은
같은 포인터를 사용한다. 설명과 문제가 혼재한 페이지가 두 채널의 evidence가 되는 것은
허용하되 같은 문항을 두 번 정본으로 만들지 않는다.

## 현재 코드에서 확인한 재사용 경계

| 책임 | 기존 소유자와 재사용 범위 |
| --- | --- |
| 안전한 원본·Artifact | Catalog Intake와 Orchestrator의 file-set commit |
| PDF/Office 관찰 입력 | `pdf_document_review_intake.py`, `office_document_review_intake.py`, 기존 bounded converter/Poppler |
| 한글 본문 그림 | `office_picture_use_extraction.py`와 publication: 실제 picture use, viewport, 회전, label과 순서 |
| 설명 문서 등록 | `educational_document_service.py`의 immutable document/revision·분석 bundle |
| 지식 분석 | `knowledge_analysis_service.py`, batch service, versioned knowledge-analysis workflow |
| 문항 추출·원본 대조 | legacy extraction과 external-item learning의 원본 anchor/구조 검증 규칙 |
| 일반 문항 구조 | `AssessmentItemContent/1.0`: 객관식과 서답형. 생성 문항의 5지선다/고정 템플릿을 강제하지 않음 |
| 공개 풀이·Graph | 기존 accepted analysis, automatic/shared Graph publication, 공통 개념/출처 연결 |
| 검색 | 기존 증분 INDEX/QUERY와 공통 공개 풀이 projection. 별도 벡터 DB/검색 엔진 없음 |
| 실행·복구 | 기존 Workflow/Job/plan/worker lease와 Artifact commit/replay |

등록 계약은 REFERENCE_BOOK을 표현하지만 실제 문서 서비스는 TEXTBOOK만 허용한다.
external-item 학습은 Notion source/revision/5자리 번호와 2·3교에 결합돼 있다.
legacy extraction은 reviewed exam bundle/occurrence를 전제로 한다. 이 제약을
무시하거나 자료를 가짜 교과서·가짜 기출·가짜 엑셀 행으로 만들지 않는다.
공통 인프라는 재사용하되 혼합 업로드에 필요한 입력·발견 계약을 additive하게 만든다.

## 책임과 정본

1. **시스템 경계:** Web/BFF는 파일 스트리밍·표시, API는 실제 사용자 인증·멱등 접수,
   Catalog application은 자료·단위·자식 Workflow 연결, Orchestrator는 staged 입력,
   worker 실행/결과 검증/Artifact commit을 소유한다. worker끼리 통신하지 않는다.
2. **정본:** 업로드 원본 Artifact와 권리 확인, 불변 자료 revision, 발견/단위 계획,
   기존 Item/Document/accepted analysis가 정본이다. OCR/페이지 PNG/Office 변환은
   원본 revision/hash와 도구 identity를 pin한 파생물이다.
3. **논리·버전:** 자료 logical ID와 source revision을 분리한다. 서로 다른 편집본,
   문제집 장별 같은 `1번`, 별도 해설의 번호를 하나의 전역 번호로 합치지 않는다.
   단위 key는 source revision·장/구간·원문 locator를 포함한다.
4. **포인터:** source, rights, page/picture catalog, extraction plan, Workflow/Job,
   accepted result, Item/Document, Graph/index의 ID/revision/hash를 유지한다.
   미디어·schema·권한·lifecycle·실제 hash는 해당 resolver/materialization에서 검증한다.
5. **주요 접근:** 자료 ID 조회, 소유자별 최근 목록, 자료 내 ordered 단위, 상태별
   다음 작업, 중복 key/원본 hash 조회, parent-child provenance, Graph 인접 연결이다.
6. **자료구조·인덱스:** 기존 Artifact/Workflow queue를 재사용한다. 새로운 영속 자료
   진행 기록은 작은 pointer와 indexed 상태/순서만 저장한다. unique source/단위/key,
   B-tree FIFO/claim 및 append-only event sequence를 사용한다. 큰 본문·그림·보고서를
   DB나 다중 서비스 dict에 복제하지 않는다.
7. **규모:** 긴 책도 bounded page window/한 문항 단위로 처리한다. source/group join은
   map/set, dependency는 adjacency, canonical 계획은 ordered immutable manifest다.
   1,000쪽·수천 문항에서 전체 결과를 매 poll마다 읽거나 N+1 조회하지 않는다.
8. **동시성:** 자료 owner는 작업 하나를 원자적으로 claim하고 긴 파일/모델 작업 동안
   row lock을 잡지 않는다. 자식 Workflow는 기존 멱등 submission을 사용한다.
   Graph publication은 기존 공통 writer/CAS를 사용해 현재 창작 등록과 합쳐진다.
9. **의존 방향:** interfaces → application → contracts/domain; 파일/DB/Codex/변환기는
   기존 infrastructure adapter다. 도메인이 API·NAS·SQLAlchemy에 의존하지 않는다.
10. **실패·재개:** 같은 요청의 timeout 후 새 key로 중복 실행하지 않는다. 원본/계획과
    자식 Workflow/Artifact를 조회해 복구한다. 실패 이력과 이전 attempt는 보존하며,
    재시도는 공식 successor/attempt다. 일부 단위의 문제 때문에 독립 단위를 멈추지 않는다.
11. **단순 대안:** 텍스트 전체를 Codex에 한 번에 보내기, 교과서 결과로 모든 문제를
    대체하기, 각 기능에 별도 파일/queue/Graph를 복제하는 방식은 coverage·시각·풀이·
    재개·출처를 잃는다. 자료 조정 use case와 필요한 successor만 기존 엔진에 더한다.

## 내용과 문항의 구분

레이아웃을 고정 규칙으로 추정하는 것이 아니라, 기존 support worker의 `DISCOVER`
프롬프트가 페이지 그림과 보조 텍스트에서 실제 위치·역할·단원/번호·이어짐을 판독한다.
`EXTRACT_ITEM`은 선택된 단위만 원문대로 옮기고, 별도 knowledge-analysis는 선택된 설명만
개념/관계로 분석한다. 원문 입력이므로 콘텐츠팀 출제 문체·5지선다·특정 박스 양식을
강제하지 않는다. 프롬프트와 실제 역할의 연결은 기존 Workflow Runner/실행 plan에 있다.

가변 배치 지침은 2단·혼합 페이지, 설명/예제/연습 혼재, 공통 지문/자료와 소문항,
인접/단원 끝/책 뒤/별도 파일의 해설, 여러 문항을 담은 정답표, 단원별 번호 재시작과
번호 없음까지 구분한다. OCR 순서를 시각적 읽기 순서로 단정하지 않으며, 관측하지 못한
단원이나 번호를 만들어 연결하지 않는다. 단위/페이지 coverage·출처 identity·정답표와
해설의 대응·중복 여부는 기존 deterministic 계약/계획 검증으로 다시 검사한다.
지침 문자열·합성 배치 fixture PASS는 실제 모델이 모든 책의 레이아웃을 정확히 읽었다는
증거가 아니다. 실제 모델의 경계 인식·해설 대응 정확성은 bounded 업로드에서 따로 확인한다.

- 구성 발견은 페이지마다 설명/문제/해설/정답표/비내용 및 이어지는 부분을 명시한다.
  한 페이지의 여러 역할과 페이지를 넘는 문제, 책 끝의 해설, 별도 해설 파일을 허용한다.
- 모든 페이지가 처리·비내용·불명확 중 하나로 집계돼야 하며 문제/해설을 조용히 누락하지
  않는다. 번호만 같다는 이유로 장이 다른 문제와 해설을 연결하지 않는다.
- 원문 오류·정답 충돌은 내용을 고쳐 숨기지 않고 보고서에 남긴다. source-derived와
  model-solved 정답/풀이를 구분하고, 모델 추론을 원문 인용으로 표시하지 않는다.
- 불명확한 문제/해설 대응, 읽을 수 없는 원문, 해결하지 못한 그림은 단위별로 보인다.
  원문을 만들어 채우거나 옆 문항 그림을 가져오지 않는다.
- 한글은 본문 picture use를 가져온다. 우측 참고 기출/해설에만 쓰인 개체를 제외하되,
  본문과 공유한 binary member 전체를 삭제하지 않는다. 표·수식은 native로 보존한다.
- 교과서/참고 내용과 기출/외부 창작/시스템 AI의 provenance를 유지한다. 사설 모의고사를
  교육청/평가원 기출로 분류하지 않는다. 자료명·폴더명은 확인된 기관/회차를 대체하지 않는다.
- 참고서는 현행 source-class mapping과 권리·retrieval policy를 확인한다. Graph 등록을
  특정 worker의 근거 사용 권한이나 사람의 교육 품질 승인과 동일시하지 않는다.

## 구현 및 완료 순서

| 단계 | 산출물과 종료 조건 | 상태 |
| --- | --- | --- |
| D0 | 현행 경계와 초안 | 작성 |
| R1 | 입력/내용·문항 분리/시각·해설 대응/권리·출처 설계 검토 | D1 반영 |
| R2 | 재사용 경계/상태·동시성/복구·확장/실제 배포·검증 설계 검토 | D2 반영 |
| P1 | JSON Schema 2020-12·Pydantic·pointer·상태/단위 계획 | 입력·준비·발견·문항·출처·진행 및 일반 문서 분석 successor 후보 구현 |
| P2 | 안전한 업로드/준비와 기존 converter·원본 그림 연결 | 후보 구현. 원본 재사용·page chunk·Office 준비 복구·공식 문서 등록은 임시 DB에서 확인. 실제 운영 업로드는 P6 |
| P3 | 1슬롯 발견/문항/내용 분석·등록·Graph·증분 INDEX 연결 | 발견/추출 V33와 일반 설명 V34의 실행·source 재인가·기존 Graph projection 연결 후보 구현. 문항 등록/소비 경로·coordinator·control release·실제 실행은 진행 중 |
| P4 | 자료 학습 GUI와 최근 작업·진행·예외·재개/조회 | 업로드·최근 목록·상세 진행 후보 구현, 브라우저 fixture 확인. 운영 및 재개/재시도 조작은 후속 |
| P5 | unit/schema/security·disposable DB 동시성/중단·browser·wheel 검사 | 변경 경계별 진행 중. 통과한 fixture/임시 DB와 미실행한 실제 학습을 구분해 checkpoint에 기록 |
| P6 | 호환 배포·bounded 실제 업로드·Item/Graph/검색 연결·재조회 | 미착수 |

R1과 R2 완료 전에 실행 계약/worker behavior/DB 변경 구현을 시작하지 않는다.
설계 검토의 발견·변경·잔여 조건은 별도 review 기록에 남긴다. 운영 배포는 기존 API
provider pin과 QUERY/Catalog/runtime 호환 절차를 따르며 INDEX 수치 환경은 보존한다.
현재 4슬롯 원래 작업을 강제 종료하지 않는다. 새 자료 학습은 한 번에 한 AI 작업만
진행하며 기존 전체 동시 실행 상한을 공유한다. 6개 슬롯이 구성돼 있어도 현재 정책의
전체 동시 실행 상한은 4다. 별도 근거 없이 4+1 실행을 약속하거나 상한을 늘리지 않는다.
용량 대기는 정상 상태이며 기존 작업이 자연스럽게 자리를 비우면 실행한다.

## D2 구현 경계와 복구 결정

### 장시간 Graph 저장의 기존 claim 유지

실제 공유 Graph 저장이 짧은 coordinator lease보다 길어질 수 있으므로, 문항/설명
publication 두 호출에 동일한 `material_claim_renewal` 범위를 사용한다. 정본은 기존
run의 owner/token/expiry이며 새 queue·schema·identity·권한은 만들지 않는다.
15분 lease를 30초마다 동일 run PK/정확한 token으로만 갱신하고, 긴 원문/Graph 작업 중
DB row lock을 유지하지 않는다. 갱신 transaction의 lock/query 대기는 유한하다.
범위 종료 시 갱신 thread를 먼저 끝내고 기존 claim을 다시 확인한 뒤 task를 갱신한다.
만료·교체된 token은 부활시키지 않으며, 갱신 실패는 완료로 바꾸지 않는다. 원래 작업
오류를 heartbeat 오류로 덮어쓰지 않는다. 호출마다 O(1) 상태/PK 조회, 단일 thread와
상수 공간이며 별도 영속 자료가 없다. 단순 TTL 상향만으로 긴 문서의 유효성을
보장할 수 없어 기존 claim 갱신을 사용한다. 실제 PostgreSQL의 경쟁 claim/만료·재소유와
source 단위 중단 회귀로 검증한다. 이미 실행 중인 옛 owner에는 코드 주입/직접 lease
수정을 하지 않고, 자연 종료 후 호환 owner successor로 원래 checkpoint를 이어간다.

### 공개 풀이의 내부 전용 preset 선택

외부에 공개된 `CreateKnowledgeSolutionAnalysisCommand`는 기존 `knowledge-analysis`
literal을 그대로 유지한다. material owner는 같은 등록 문항 풀이 엔진의 명시적인 내부
`create_material_solution_with_pinned_preset`을 사용해 `material-item-solution` logical key와
정확한 released ID/revision을 대조한다. 새 RPC/worker schema·권한·queue가 아니며 원래
source/operator, accepted base, protocol/hash/idempotency 검증을 공유한다. 기출 V9 base를
이 경로로 채택하지 않는다. 공개 command의 literal을 넓히거나 다른 purpose의 preset으로
대체하지 않는다. 일반/자료 전용 preset 양쪽을 실제 임시 DB의 V11 보고서와 공통 텍스트
projection까지 실행해 경계 조합을 검증한다. 모델 결과 fixture만 쓰는 테스트가 실제
material preset 연결을 대체하지 않도록 한다.

- **계약:** `material-learning/1.0` 계열에 업로드 의도, 원본/분석 입력 포인터,
  권리 확인, 페이지별 발견 계획, 단위별 추출 입력/결과와 공개 진행 상태를 정의한다.
  발견과 문항 추출은 서로 다른 task kind다. 기존 Notion·기출 요청은 변경하지 않는다.
- **문서:** 기존 EducationalDocument owner에 일반 자료 등록을 additive하게 추가한다.
  기존 TEXTBOOK 전용 bundle/rights bytes를 새 의미로 쓰지 않는다. 일반 page bundle과
  업로더 권리 확인을 참조하는 source successor만 추가한다. 모르는 출판사·판·교육과정
  권수는 null/미확인 값이며 구매·협상 사실을 만들어 넣지 않는다.
- **작업:** 기존 Workflow/Orchestrator의 KNOWLEDGE_ANALYSIS workload와 support role을
  사용한다. 새 task 요청은 자료 revision, 입력 Artifact와 정확한 원문 범위를 pin한다.
  새 결과를 받으면 같은 자료 owner가 기존 문서 지식 분석 또는 Item 등록·공개 풀이
  use case를 호출한다. 새 queue framework, worker role, 로그인 복제는 만들지 않는다.
- **영속성:** 자료 접수/불변 revision, ordered 단위와 child 실행 포인터, append-only
  상태 이벤트만 저장한다. 파일과 긴 결과는 Artifact다. 원본 hash만 같은 다른 사용자의
  자료를 권한 확인 없이 재사용하지 않으며 멱등 key는 실제 actor와 요청 hash에 묶는다.
  구체적으로 logical 자료, 불변 revision, 처리 run, 순서 있는 task, append-only event의
  다섯 작은 테이블이다. revision에는 접수 manifest 포인터만, run/task에는 진행과
  child 포인터만 둔다. 일반 원문/발견 결과/본문/풀이/페이지는 JSONB에 넣지 않는다.
  actor+idempotency key, revision+run attempt, run+unit+task attempt를 unique로 하고
  owner recent/상태별 next ordinal/event sequence를 B-tree로 조회한다. 모델 실행 중인
  자료 task의 partial unique 실행 lane으로 자료 전체에서 AI 작업 한 개만 허용한다.
  만료된 coordinator lease만으로 살아 있는 child를 재제출하지 않는다.
- **부분 완료:** `PREPARING → DISCOVERING → PROCESSING → COMPLETED`를 전체 경로로,
  단위는 준비/실행/등록/Graph/임베딩의 별도 상태로 기록한다. 명시적 예외가 남으면
  `COMPLETED_WITH_EXCEPTIONS`다. 학습 슬롯 대기와 임베딩 대기를 실패로 취급하지 않는다.
- **재시도:** child 제출 전 안정된 key를 저장하고 timeout 뒤 같은 identity를 조회한다.
  실패 실행은 그대로 두고 retry attempt만 새로 만든다. Registry 성공 직후 중단돼도
  같은 registration key와 정확한 원본/결과 hash를 대조해 기존 Item을 이어받는다.
  Graph CAS 충돌은 publication만 다시 시도하며 Codex 풀이를 재생성하지 않는다.
- **출처:** ItemOrigin의 DOCUMENT_REVISION derivation을 재사용할 수 있다. 자료-단위
  포인터 관계는 새 학습 owner가 보관하되 출처 조직·기출 회차를 추정해 발급하지 않는다.
  새 내부 권리 정책은 실제 권리 확인에서 만든다. imported provenance와 원문 anchor를
  유지하며 모델 풀이·경고는 원문 정답과 구분한다.
- **조회:** 현행 창작 DB 목록은 Notion 행을 전제로 하므로 그 행을 위조하지 않는다.
  자료에서 등록한 Item을 보여주는 additive 조회 projection을 기존 DB의 외부 목록에
  연결한다. 기존 원본의 메타데이터/선택형 필터는 유지하고, 새 자료명·단위·원문 위치와
  풀이/Graph/검색 준비 상태를 추가한다. AI 생성 분류로 섞지 않는다.

### 2026-11-06 사용자 분류 확정

이번 통합 업로드로 가져온 문항의 명칭과 `source_kind`는 **외부 / EXTERNAL**이다.
원래 가져온 Notion 창작 / CREATIVE, 기출 / PAST_EXAM, 시스템 생성 / AI를 변경하지 않는다.
이하 설계 검토 당시의 ‘새 자료 창작’ 표현은 이 후속 결정으로 대체한다. 과학 개념과
관계를 연결하는 shared Graph, 공식 APPROVED_ITEM source family와 공통 public solution
임베딩 형식은 동일하며, 출처 표시를 바꾸기 위해 독립 Graph/벡터를 만들지 않는다.

### 2026-11-06 완료 후에도 유지할 배경 작업

목표를 완료 처리해도 기존 창작 풀이·Graph 등록과 GPU 증분 임베딩 서비스는 계속 실행한다.
최종 배포 후 실제 producer/INDEX 프로세스와 새 checkpoint 진행을 확인한다. 단순
`enabled`, health 또는 오래된 상태 파일만으로 실행 중이라고 판정하지 않는다. 사용량과
전역 동시4·자료 학습 단일 AI lane을 준수하며, 기존 요청/실패 이력·수치 runtime pin을
보존한다. 진행 중이던 요청을 새 identity로 중복 생성해 속도를 맞추지 않는다. 배포 전부터
멈춘 작업은 확인된 원인과 공식 recovery 경계로 복구한 뒤 종료 상태를 보고한다.

### 실패 단위 재처리와 예외 열람

- 소유 경계는 기존 material Catalog application이다. 새 queue/worker/Artifact 저장소는
  만들지 않는다. 원본, 준비 결과와 이미 수락한 Item/분석이 정본이며 실패 run/task도
  그대로 보존한다. 실제 업로더의 현재 권한과 current material revision을 다시 확인한다.
- `RETRY_MATERIAL_LEARNING_RUN`은 준비가 완료된 terminal FAILED 또는 일부 확인 필요
  run에서 새 processing run을 만든다. 기존 run의 상태를 성공으로 바꾸지 않는다.
  동일 revision의 다음 attempt와 정확한 predecessor를 pin한다. CANCELLED와 원본/구조
  확인이 필요한 EXCEPTION을 자동 재실행하거나 가짜 성공으로 바꾸지 않는다.
- 새 run은 완료 task의 작은 checkpoint와 predecessor 참조만 이어받는다. 파일/본문을
  복제하지 않으며 기존 child Workflow/analysis의 전역 unique owner는 옛 task에 둔다.
  실패 QUESTION의 추출/등록이 이미 성공했으면 그 결과와 accepted base를 재사용하고,
  실제 실패한 분석/풀이만 기존 application 명령으로 새 시도한다. 실패 DISCOVER 또는
  설명 분석은 해당 단위만 다시 실행한다. 재시도 뒤에도 살아 있는 child를 중복 제출하지 않는다.
- 주 접근은 run PK, revision별 attempt, run별 ordinal, bounded predecessor 조회다.
  기존 PK/unique/B-tree 인덱스를 사용한다. predecessor 읽기는 최대32단계의 한 번의
  recursive indexed query로 묶고 cycle/다른 자료·업로더·단위 연결은 명시적으로 거부한다.
  N개 작은 checkpoint를 선형으로 생성하며 실패 단위 lineage만 추가로 확인한다.
- transaction은 revision→run 순서로 잠가 같은 자료의 동시 재시도를 직렬화하고 기존
  live-revision unique 제약으로 보강한다. observed run timestamp로 만든 고정 key와
  deterministic successor ID를 재사용해 timeout/동시 재전송이 두 run을 만들지 않게 한다.
- `GET_MATERIAL_LEARNING_TASK`는 사용자가 선택한 한 단위의 실제 파일 역할·페이지·
  번호·확인 코드를 읽는다. status poll마다 전체 책/풀이/그림을 읽지 않으며, 원본 위치를
  알 수 없는 단계는 모른다고 표시한다. 임의 filesystem path나 다른 사용자의 Artifact를
  브라우저 입력으로 받지 않는다. UI는 같은 재처리 명령과 source detail read만 호출한다.
- 단순 대안인 기존 FAILED row 재개·책 전체 재업로드·완료 child ID 복사는 실패 이력이나
  중복 방지 경계를 잃는다. 이 변경은 기존 predecessor/attempt 컬럼을 사용하며 새 DB
  테이블·binary 값·별도 registry를 도입하지 않는다. 기술적 복구와 원문 품질 판정은 분리한다.
- 준비 단계의 암호화·쪽 수·렌더링 예산 초과는 그 자료의 명시적 실패로 기록해 다음
  자료가 처리될 수 있게 한다. 일반 예외·profile 불일치·포인터/권한 오류를 이 부류로
  뭉개지 않는다. 중단된 준비는 원래 checkpoint를 재조회하며, 원본을 고쳐야 하는 실패는
  같은 실패 파일을 무한 재실행하는 버튼으로 숨기지 않는다.
goal 카드 종료는 이 운영 서비스들의 stop/disable 사유가 아니다.

### 운영 parser와 한글 변환의 실제 소유 경계

지배적 접근은 고정 도구 실행과 단일 private workspace 조회다. Root 자료 coordinator는
기존 Orchestrator Artifact publisher/Registry/Workflow를 조합하지만 외부 PDF를 root로
파싱하지 않는다. 기존 Poppler/Tesseract extractor의 command port에 PDF 격리 adapter를
주입하고, eom-image sandbox에 정확한 원본 파일 하나를 read-only bind한다. 페이지마다
원본 전체를 복사하지 않으며 O(원본 보관1개 + chunk 출력) 공간이다. PNG 출력은 해당
extractor가 방금 만든 임시 디렉터리 하나만 writable이다. NAS/DB/auth/network는 없다.

한글 변환은 기존 Catalog-manager 소유의 고정 office-conversion workspace와 기존
office-converter systemd unit을 그대로 쓴다. Root staging의 UID 검사를 완화하거나 기존
폴더를 root로 chown하지 않는다. 작은 schema-first 로컬 command는 instance/format/hash와
CREATE/CONVERT/READ만 포함하고 arbitrary path/actor/DB 권한을 받지 않는다. 실제
Catalog-manager helper가 기존 converter를 호출하며 root는 정확한 입력 임시 파일만
넘기고 기존 완료 결과를 검증해 재사용한다. canonical source/Artifact는 기존 revision이다.
프로세스 실패는 명시적 오류로 남기고 이미 완료한 변환은 READ로 재조회한다. 새 queue나
변환 엔진을 만드는 대안보다 기존 보안·권한·변환 의미를 유지하는 이 adapter가 작다.

중단/재개 command는 기존 run row의 key lookup과 짧은 FOR UPDATE를 사용한다. 실제
업로더·현재 자료 revision을 재인가하고 화면이 읽은 updated_at으로 optimistic fence를
건다. PAUSED에서도 이미 실행 중인 자식의 완료는 회수하지만 새 모델 작업은 시작하지
않는다. 같은 중단/재개 재전송은 부작용 없는 현재 상태를 반환한다. 상태가 바뀐 뒤의
오래된 다른 action은 STALE로 거부한다. 기존 append-only event와 phase_before_wait를
재사용하며 새 queue/테이블/lease 취소나 실패 성공 재해석은 하지 않는다.

자료 coordinator는 별도 WorkflowRuntime/model executor를 만들지 않는다. 기존 application
create가 만든 Workflow command를 이미 운영 중인 global Workflow Runner가 실행한다.
coordinator는 짧은 claim으로 원래 자식 상태를 읽고 다음 checkpoint를 연결할 뿐이며,
모델이 응답하는 동안 자료 run lease나 HTTP 요청을 붙들지 않는다. 이로써 pause와 여러
자료의 파일 준비도 긴 모델 호출에 종속되지 않는다. 기존 단일 AI lane/전역 동시4가
각자의 DB·host lock에서 그대로 강제된다.

### 통합 검사에서 확인한 설명 append 계약 보정

실제 임시 DB에서 교과서의 reviewed structure V2→일반 자료 설명 source V5를 append하자
자료 owner가 publication V6/structure V6를 고정해 거부했다. V6에는 실제 기출 placement와
origin-scoped Item alignment가 필요하므로 교과서-only Graph를 그 형태로 위장하지 않는다.
정본은 원래 reviewed structure와 accepted source이며, 새 설명은 기존 구조의 실제
schema/version에 대응하는 공식 publication V2–V6로 제출한다. 신규 snapshot V10만
structured pointer V2–V6를 명시적으로 지원한다. released publication/structure/snapshot
V1–V9의 bytes와 과거 요청 해석은 바꾸지 않는다. 새 source가 없는 기존 publication은
동일한 구 snapshot 계열을 사용한다. 새 source가 있으면 그 exact 구조를 pin한 V10을
반환한다. 타입 선택은 작은 immutable map(O(1)), 발행·재조회는 기존 writer/CAS와
Artifact resolver가 소유한다. 새 Graph나 DB schema·권한 확대는 없다. 임의 최신 구조로
교체하거나 가짜 기출/Item을 넣는 대안은 출처와 검토 의미를 깨므로 허용하지 않는다.
- **Graph/INDEX:** 문서 accepted analysis는 기존 공통 Graph publication, Item은 기존
  automatic Item publication을 사용한다. 출처 정책은 별도 적용한다. Graph 등록 후
  기존 공통 풀이 projection으로 증분 INDEX에 넘긴다. 전체 기출 INDEX 완료를 기다리지
  않으며 `GRAPH_READY`와 `EMBEDDING_PENDING/READY`를 구분해 표시한다.
- **인증/업로드:** 현재 자료 학습 권한을 유지하고 실제 호출자를 검증한다. 짧은 파일
  접수 이후 변환/모델은 background owner가 담당한다. 브라우저 세션 만료가 접수된
  작업을 지우지 않는다. 재접속 조회는 현재 권한을 다시 확인하며 관리자 사칭이나
  worker 권한 부여로 해결하지 않는다.
- **검증/배포:** 먼저 schema/model, deterministic 계획·포인터·매칭, 격리 worker,
  disposable PostgreSQL 경합/중단/재전송, 브라우저와 wheel을 검증한다. 이후 실제
  호환 API/platform/Catalog/QUERY/Web release set을 배포하고 작은 혼합 자료로
  업로드→Item/내용→Graph→증분 임베딩 handoff와 같은 요청 재조회를 확인한다.
  현행 INDEX 수치 runtime과 실행 identity는 유지한다. 실제 새 자료 모델 실행은
  이번 사용자가 승인한 운영 완료 범위 안에서 제한된 검증 자료로 수행한다.

## 필요한 검증

같은 파일·요청 재전송, 이름/확장자와 실제 형식 차이, PDF/HWP/HWPX, native 그림·표·수식,
한 페이지 복수 문항/다중 페이지 문항, 장별 중복 번호, 별도/책 끝 해설, 설명 전용/문항 전용/
혼합 자료, 해설 없는 문제, 읽기 불가/원문 오류, 권한 철회·hash 변경, claim 충돌·만료,
업로드/모델/Artifact/Item/Graph 경계별 중단, 구형 Workflow/계약 회귀를 검사한다.
운영 DB에 mutating pytest를 실행하지 않는다. 실제 canary는 제한된 검증 자료와 공식
사용자 권한으로 실행하고, 전체 책 재처리나 기존 정본/실패 이력 삭제로 검증하지 않는다.

## 일반 자료 설명 지식의 successor 범위

일반 자료는 기존 `knowledge-analysis` application·risk policy·proposal 정규화·accepted
result·shared Graph writer를 그대로 사용한다. 새 분석 엔진을 따로 만들지 않는다.
기존 source V4를 완화하지 않고 명시적인 uploaded-material source V5, request/result
V12, proposal receipt V11, Workflow `12.0.0`/role `1.38.0`, resolved plan V34를 추가한다.
worker의 안정된 node identity/typed edge/anchor/page 관찰 구조는 기존 proposal V6를
재사용한다. 새 버전은 아직 후보이며 운영에서 허용됐다는 뜻이 아니다.

- 정본은 이미 등록한 EducationalDocument revision과 실제 업로더의 권리 확인이다.
  source V5는 일반 자료 revision manifest와 원본 native/PDF 포인터, bounded 선택 영역,
  정확한 page-chunk 멤버를 함께 pin한다. 텍스트를 기존 교과서 charset/schema로
  위장하거나 같은 Artifact에 넣기 위해 페이지를 다시 복사하지 않는다.
- 접근은 document revision key lookup, 선택 페이지 범위 조회와 chunk membership이다.
  source당 chunk 끝 페이지 tuple을 만들고 이분 탐색하며 같은 chunk는 한 번만 읽는다.
  complexity는 chunk header 수 + 선택 페이지 수 × log(chunk 수), 공간은 선택 chunk와
  최대 32페이지의 작은 metadata다. DB index와 기존 분석 queue는 그대로 사용한다.
- 실제 호출자의 현재 권한과 source-class policy, material/문서 lifecycle, 원본/문서/권리/
  chunk/member hash를 기존 소유자가 검증한다. 새 source는 TEXTBOOK 또는 INTERNAL_GUIDE로
  구분하되 구매·협상 사실이나 공식 기출을 만들지 않는다. Graph 등록과 retrieval의
  허용은 별도이며 기존 released policy를 조용히 넓히지 않는다.
- 분석 접수·replay·정규화·승인은 기존 transaction/idempotency/risk-policy owner가
  담당한다. 한 자료 task가 자식 analysis run을 pin하고, 전체 학습 AI lane은 한 개다.

자식 실행은 task의 optional Workflow/analysis ID를 partial unique B-tree로 조회한다.
Catalog의 runner 전용 재인가 RPC는 저장된 역할에서 실제 업로더를 복원하며,
발견/문항 추출(V33)뿐 아니라 일반 설명 분석(V34)의 exact source도 검증한다.
RPC 입력에는 actor/권한을 추가하지 않는다. 실행 직전·결과 commit 직전에 같은
원본과 권리를 다시 확인하고, 같은 child가 서로 다른 task에 연결되는 것은 DB에서도
거부한다. 큰 보고서를 매 상태 조회에 읽는 구조는 추가하지 않는다.

새 설명 분석은 기존 구조·projection·공유 writer를 사용하되 uploaded source를 보존하는
snapshot V10을 발행한다. 구 snapshot bytes는 바꾸지 않는다. 새 원본을 구 교과서
구매/권리 bundle로 변환하지 않으며, retrieval consumer가 지원하는 source-family와
access policy도 별도로 확인한 뒤 운영 활성화한다.

## 혼합 자료 문항의 등록·공개 풀이 연결

등록은 기존 Registry와 새 `uploaded-material-item` 등록 Pack을 사용한다. Notion 행,
5자리 고유번호, 시험 occurrence는 만들지 않는다. 안정된 등록 key는 material revision과
발견 계획의 source-local unit key에 묶는다. 작은 lineage Artifact는 exact task·실행
selection·work/role-result 포인터·원문/정규화 content hash·경고·실제 업로더만 pin한다.
본문은 기존 canonical Item content, 출처는 SOURCE_REFERENCE, 독립 풀이/주의사항은
원래 REVIEW_REPORT 컴포넌트에 둔다. 본문 그림은 공통 native picture-use resolver를
사용하고, PDF만 기존 crop renderer의 명시적 derived-image 경계를 사용한다.

원문 내용과 독립 풀이의 정답이 다르면 원문을 고쳐 숨기지 않는다. 등록은 원문 수록
의미이지 과학적 무오류 인증이 아니다. 이후 기존 registered-Item V2 지식 분석과 V11
공개 풀이 Workflow를 순차 실행한다. 이렇게 하면 기존 공통 embedding projection과
현재 numeric INDEX가 지원하는 accepted registered-solution 형식을 재사용할 수 있다.
추출 단계의 공개 풀이 원본도 보존하며, 이를 가짜 V10/V11 worker 실행으로 포장하지 않는다.
추가 분석의 비용은 실제 호출로 집계한다. 실행은 여전히 자료 전체 한 AI lane과 기존
물리 host 상한 안에서 순차다. 기존 GPU INDEX에 새 evidence variant를 억지로 넣거나
돌고 있는 runtime을 바꾸지 않는다.

원자 경계는 각 기존 application이다. Registry 성공 후 중단되면 같은 key와 content/
lineage hash를 확인해 재사용하며, accepted analysis/public report의 identity도 저장된
child 포인터로 복구한다. Graph CAS 재시도는 publication만 반복한다. task의 별도
solution-analysis pointer는 기존 base analysis와 다른 실행을 명확히 구별한다.
  실패 이력은 유지하며 Graph 경합으로 모델 분석을 다시 실행하지 않는다.
- 대안인 TEXTBOOK source V4로 변환/새 파일 복제는 권리와 chunk identity를 잃는다.
  별도 지식 분석/Graph framework도 불필요하다. 필요한 입력/source successor만 추가해
  동일 risk·proposal·Graph 경계를 재사용한다.

## 구현 체크포인트 2026-11-05

- 설계/검토와 기본 계약·순수 계획: `679e48c1`; 패키지 발견 및 새 schema 설치 경계:
  `bdfb23e7`. 후자는 subproject의 옛 `build/`를 Python package로 잘못 포함하는 문제와
  새 자료 schema resource의 wheel 포함을 검증한 수정이다.
- `material-learning@1.0.0`, `workflow-role/1.37.0`, plan `33.0`은 현재 **후보**다.
  정의/입력·출력 schema와 실제 Codex strict-output 형식을 검증했으며, 아직 운영에
  활성화한 preset이나 실제 새 자료 모델 실행은 없다. 후속 일반 문서 source/공개 진행
  계약이 완료되기 전 운영 가능하다고 표시하지 않는다.
- migration `20261105_0074`는 현재 새 다섯 테이블과 보호 trigger의 **개발 후보**다.
  guarded disposable PostgreSQL에서 upgrade/downgrade/upgrade와 metadata 일치,
  동시 접수/단일 AI lane/lease 만료/기록 불변성 및 Workflow 재전송/권한 철회를 확인했다.
  운영 DB head와 설치 서비스는 변경하지 않았다. 최종 배포 전 release-operator의
  successor context/정확한 head와 API/Catalog/QUERY 호환 set을 함께 준비해야 한다.
- 큰 원본을 문항마다 복제하지 않는다. 현행 file-set의 member/byte 상한이 있으므로
  긴 자료의 페이지 리소스는 bounded chunk Artifact로 나누고, 일반 문서 manifest와
  source successor가 정확한 chunk/member/hash를 pin하도록 구현한다. 기존 교과서
  source V4의 한 Artifact 가정을 조용히 완화하지 않는다.
- 19:23 UTC read-only 점검: 기존 유효 슬롯 lease 4개, 원래 creative producer와
  GPU INDEX의 PID/invocation 유지. 현재 목표의 새 학습 모델 실행·운영 변경은 0이다.
- 원본 접수·권리 확인·실제 형식 감지·멱등 자료 생성·bounded 진행 조회 및 Web/BFF 화면을
  연결했다. `PUT /material-learning/sources`, `POST /material-learning`, 최근 목록과 실행
  상세는 공식 API→Catalog 경로만 사용한다. 원본 Artifact는 한 번 보관하고 intake에는
  pointer만 둔다. 일반 사용자에게 새 관리자 권한을 부여하지 않는다.
- 최신 guarded 임시 DB에서 migration 왕복/metadata 일치와 저장·Workflow·원본
  publication/실제 동시 접수/재조회 **21개 PASS**. 파일 보관의 Pydantic UTC 직렬화
  (`Z`)와 self-hash 생성의 시간 표기 차이는 이 실제 검사에서 발견해 고쳤다.
  실패한 첫 검증 기록은 보존했다. 원본에 새 `request`를 붙여 실패 이력을 덮지 않았다.
- 실제 Chromium에서 본문+별도 해설 입력, 접수 실패 후 **같은 key 재전송·파일 재복사 없음**,
  진행 표시와 계정 전환 후 늦은 응답 폐기 PASS. 합성 자료/응답을 사용했으므로 이 결과는
  운영 업로드 또는 Codex·Graph 완료 증거가 아니다.
- 아직 구현 중: bounded 페이지/일반 문서 source, 실제 Orchestrator 실행/결과 처리,
  문항·문서·Graph·증분 INDEX와 DB 소비 경로, 운영 호환 배포와 실제 canary.
  지금의 업로드 접수 성공만으로 학습 완료나 전체 goal 완료를 선언하지 않는다.
- 페이지 준비 후보는 긴 자료를 bounded chunk로 저장하고, PDF 원본을 중복 등록하지
  않는다. HWP/HWPX는 기존 변환기와 본문 picture-use 추출을 사용하며, 성공한 변환의
  private workspace와 이미 committed된 page chunk를 중단 후 그대로 이어받는다.
  일반 문서는 기존 EducationalDocument owner에 등록하되 별도의 새 manifest로
  업로더 권리 확인을 pin한다. 기존 구매·협상 교과서 source 의미는 바꾸지 않는다.
- 최신 임시 DB에서 준비 중단→재개→일반 문서 등록과 원본 pointer 재사용을 포함한
  22개 검사가 통과했고, 같은 DB에서 동일 suite를 다시 실행해도 22개가 통과했다.
  합성 extractor를 사용한 복구/저장 검사이므로 실제 Codex 분석 또는 운영 Graph
  등록 완료의 증거는 아니다. 기존 API/GUI/문서 계약 회귀는 87개 PASS이며 browser
  opt-in 한 건은 별도의 기존 Chromium fixture PASS와 구분한다.
- 20:13 UTC read-only: 기존 creative 실행은 publication 단계이며 당시 active slot lease는
  0이었다. 기존 producer PID `4175073`/invocation과 GPU INDEX PID `4045657`/invocation은
  그대로였다. cursor `25`는 재개 구간의 진행값이지 전체 Graph 누적 수가 아니다.
- 실행 연결 후보: 새 자료의 `learn` step은 기존 Orchestrator의 Job·capacity lease·
  local worker workspace·result validation·Artifact commit을 사용한다. 전용 source
  권한 RPC는 저장된 Workflow/step에서 실제 actor를 복원하며 모델이나 브라우저가
  actor를 지정하지 못한다. 같은 task 입력의 canonical bytes 및 권리·문서·chunk·
  선택 페이지 소속을 대조한다. 발견은 페이지별 coverage, 문항은 독립 공개 풀이와
  native picture-use binding을 기존 공통 검증기로 확인한 뒤에만 commit한다.
- 자료 image manifest V5는 원본 `source_role/physical_page`와 전달 `input_index`를
  분리한다. 문제지와 해설지의 같은 페이지 번호, 비연속 선택을 원래 위치대로 전달한다.
  기존 V1–V4의 의미와 파서는 유지한다. worker helper 변경을 포함하므로 최종 배포는
  진행 중 Codex 프로세스가 자연 종료한 창에서 helper와 관련 Codex driver/runner의
  설치 wheel/hash를 호환 조합으로 바꿔야 한다. 기존 child의 입력·모델·plan pin은
  보존하고 numeric GPU INDEX 환경은 변경하지 않는다. 이전 driver의 hash pin과
  새 helper를 섞어 먼저 활성화하지 않는다.
- 이 연결의 격리 회귀 196개, 기존 Catalog/Office 경계와 실제 파일 materialization
  47개 PASS. 임시 DB에서는 실제 업로드/문서/페이지 소속 대조와 단일 READY/command,
  동시 재전송·늦은 권한 철회의 원자성을 포함해 25개 PASS. command 검사 일부는
  명시적인 synthetic plan port를 사용하므로 운영 control release/capacity 승인 증거가
  아니다. 실제 자료 coordinator·일반 설명 지식/문항 등록·Graph·증분 INDEX와 운영
  canary는 계속 구현 중이다.
