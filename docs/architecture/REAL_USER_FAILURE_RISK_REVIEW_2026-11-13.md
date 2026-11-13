# 실제 사용자 오류 위험 검토 — 2026-11-13

상태: 검토·격리 재현·기록 완료. 구현·운영 변경을 승인하는 문서가 아니다.

후속 사용자 승인에 따라 U01–U06 소스 수정·검증을 수행했다.
[후속 수정 결과](../operations/REAL_USER_RISK_REMEDIATION_2026-11-13.md)를 함께 본다.
아래 위험 관측과 최초 판정은 조사 당시의 근거로 보존한다.

결론: 최초 EOM의 계층·계약·정본·Orchestrator 중심 구조를 다시 만들 필요는 없다.
먼저 고칠 부분은 자료 검토 화면의 응답 소유권, 업로드 재개, 다운로드 자원 예산,
Excel 준비 판정이다. **재현 결함 2종, 정적 위험 3종, 입력 계약 차이 1종**을 아래에 구분했다.
전체 시스템의 무결함이나 모든 사용 시나리오의 운영 검증을 뜻하지 않는다.

## 목적과 판정 기준

여러 사용자가 정상적인 화면 조작과 허용된 파일 입력을 했을 때 실패하거나 잘못된
결과를 볼 수 있는 경계를 찾는다. 특정 오류에 임시 분기를 더하는 대신 기존 책임
모듈에서 가장 작게 해결할 방향을 기록한다. 위험 후보의 수를 늘리는 것이 목적은 아니다.

- **재현 결함:** 현재 소스의 실제 함수 또는 typed 계약으로 격리 재현했다.
- **정적 위험:** 현재 실행 경로와 발생 조건은 확인했지만 실제 운영 장애를 유발하지 않았다.
- **운영 관측:** 읽기 전용으로 수치·설정·서비스 상태를 관찰했다. 원인 확정과는 다르다.
- **제한/확인 필요:** 의도된 계약, 환경 의존 또는 추가 확인이 필요한 사항이다.
- P1은 사용자의 결과 정확성·업무 연속성에 먼저 대응할 항목, P2는 특정 입력·규모에서
  대응할 항목이다. 이번 조사에서 P0 사고가 확인됐다는 뜻은 아니다.

기존 정본·실패 이력·슬롯/GPU 실행·비밀번호·설정을 변경하지 않았다. 운영 DB에
pytest를 실행하거나 실제 사용자에게 고의로 로그인 실패를 일으키지 않았다.
모델 호출, 신규 검색·출제·변환·등록도 실행하지 않았다.

## 기준선

| 대상 | 확인한 기준 | 해석 |
| --- | --- | --- |
| 저장소 | `efa6cc48` / 조사 시작 시 clean | 과거 리뷰와 대조할 source 기준 |
| API/공유 platform | `a7fc195d607bdca917cce0d48a4897b1db313c9b` | 해당 이후 apps/application_api·services·packages·config·content diff 없음 |
| Web | `858680cfaaa3e091b6e98b220e50ccb8d70e3735` | 해당 이후 apps/web_gui diff 없음 |
| INDEX | 수치 설치본 `47fc5366161a6179f9b282b823e86319bc3d9340` | controller 위임 a7fc 전환과 별개. 이번에는 변경하지 않음 |
| Web 세션/자원 | 5,400초 TTL, 최대 256세션, 메모리 512MiB | 읽을 수 있는 운영 설정/unit만 확인 |
| API 보호 설정 | 일반 개발 계정으로 파일 읽기 거부 | 실제 API rate/auth 값은 UNKNOWN. 소스 기본값을 운영값으로 주장하지 않음 |

현재 API/Web/Catalog 및 INDEX·QUERY·등록 owner가 실행 중인 것을 관찰했다. active나
READY만으로 모든 제품 경로가 정상이라고 판정하지 않는다. 스냅샷 이후 상태는 바뀔 수 있다.

## 사용자 오류 후보

| ID | 우선순위 | 판정 | 사용자가 겪을 문제 | 책임 경계 |
| --- | --- | --- | --- | --- |
| U01 | P1 | 재현 결함 | 자료 A의 늦은 주석/수정 결과가 선택한 자료 B 아래 표시됨 | Web 자료 검토 비동기 상태 |
| U02 | P2 | 재현 결함 | 유효한 Excel이 미리보기에서는 준비 완료인데 저장 단계에서 구조 상한으로 거절됨 | workbook import → 편성 command |
| U03 | P1 | 정적 위험 + 운영 설정 | 큰 다운로드 동시 실행으로 Web 메모리 상한 초과 가능 | BFF 다운로드 adapter |
| U04 | P1 | 정적 위험 | 오래 걸리는 정상 업로드/변환이 화면에서 먼저 실패함 | Web → API → intake deadline |
| U05 | P1 | 정적 위험 | 업로드 처리 여부가 불명확한 채 재로그인/새로고침하면 원래 요청 복구가 어려움 | Web upload intent 복구 |
| U06 | P2 | 계약 차이 | 내용은 HWPX이고 확장자만 hwp인 파일이 자료 검토에서 거절됨 | 검토 원본 format 결정 |

### U01. 자료 검토 변경 요청에 선택 문서 일치 검사가 없다

증거: `apps/web_gui/eom_web_gui/static/app.js`의
`applyDocumentReviewCorrection`, `createDocumentReviewAnnotation`,
`selectPdfDocumentReview`, `renderDocumentReviewCorrection`, `renderDocumentReviewAnnotation`.

두 변경 함수는 시작 시 자료 A를 잡고 `await api(...)` 뒤 현재 선택과 무관하게 전역
correction/annotation 상태를 덮어쓴다. 선택 함수는 B의 상태를 초기화하지만 진행 중인
A 변경 응답을 무효화하지 않는다. 결과 renderer도 선택 문서와 결과 workflow ID를 비교하지 않는다.

격리 재현: 실제 두 함수 코드를 Node VM에서 실행했다. A 요청 → B 선택·상태 초기화 →
A 응답 순서에서 두 함수 모두 `selected=B`, `stored_result=A`가 됐다. 네트워크·모델·DB는 없다.
동일 사용자 안에서 잘못된 파일을 내려받을 위험이며, 타 사용자 자료 유출을 입증한 것은 아니다.

권장: 기존 선택 sequence와 workflow ID로 성공·실패·finally의 소유를 검사한다. renderer도
선택과 결과 identity가 다르면 링크를 만들지 않는다. 이전 요청 자체나 idempotency key를
새 identity로 바꾸지 않는다. 별도 전역 상태 framework는 불필요하다.

수정 승인 조건: A→B, A→B→A, 늦은 성공·오류·finally, 중복 클릭, 원래 A 요청 재조회.
선택 B의 결과·버튼·오류를 A callback이 바꾸지 않아야 한다.

### U02. Excel 행 수와 생성되는 편성 section 수가 다른 상한을 사용한다

증거: `packages/catalog_contracts/eom_catalog_contracts/content_workbook_import.py`,
`content_planning_commands.py`, Catalog `content_workbook_layout.py`,
`content_workbook_import_service.py`의 `read`/`commit`.

입력은 최대 10,000행을 허용하지만 각 새 group에는 GROUP과 FORM이 별도로 생성된다.
5,001개의 서로 다른 비어 있지 않은 group/form 행은 유효한 document/proposal이면서
10,002 section을 만든다. `_NewEdition.sections`는 최대 10,000이므로 commit이 거절된다.
현재 `can_commit`은 문항 매칭 여부만으로 계산한다.

격리 재현: 유효한 typed document/proposal 생성 성공 후 실제 layout 함수에서
`ValidationError(too_long, loc=sections)`가 발생했다. dispatch는 ValueError를 안정된
요청 오류로 변환하므로 이 증거로 HTTP 500을 주장하지 않는다.

권장: 같은 layout 책임에서 예상 구조 크기를 준비/조회 단계에도 검사하고, 준비 완료를
표시하기 전에 그룹 수·구조 한도를 안내한다. 상한을 무조건 늘리거나 다른 layout 엔진을 만들지 않는다.
검증: 경계 10,000/10,001 section, 빈 group, 동일 group 재사용, 준비와 commit 판정 일치.

### U03. 큰 파일의 전체 buffering과 Web 메모리 예산이 맞지 않을 수 있다

증거: Web `gateways.py`의 `_application_request`, `download_curated_hwpx`,
`external_item_db_preview_download`. `httpx.AsyncClient.request`로 전체 응답을 받은 뒤
길이·해시를 확인한다. 두 다운로드 경로는 각각 최대 256MiB를 허용한다.

운영 Web은 MemoryMax 512MiB이며 조사 시 기본 사용량 약 65MiB다. 허용 상한에 가까운
파일 두 개를 동시에 보유하면 여유를 넘을 수 있다. 현재 실제 파일 크기 분포나 OOM 발생은
확인하지 않았고, 이를 확인하려고 운영 메모리를 소진시키지 않았다.
MockTransport의 1MiB 응답으로도 adapter 반환 전에 4개 chunk 전체가 소비되고
`response.content`에 1,048,576바이트가 유지됨을 확인했다. 이는 buffering 동작의 확인이지
256MiB 동시 다운로드의 peak RSS 측정은 아니다.

권장: 기존 adapter에서 bounded spool/stream과 다운로드 동시성 예산을 검토한다.
권한·해시·길이·중도 취소 cleanup을 유지한다. 단순 메모리 증설은 상한 관계를 해결하지 않는다.
검증: 작은/상한/초과/길이 거짓/해시 오류, 동시 다운로드 peak RSS, 취소 후 FD·임시 파일 회수.

### U04. 화면의 시작 요청 제한이 서버의 정상 처리 시간보다 짧다

증거: Web `settings.UpstreamSettings.workflow_start_timeout_seconds` 기본 150초,
`gateways.py`의 단일/짝 자료 업로드 호출. 읽을 수 있는 운영 Web 설정은 이 값을
별도로 지정하지 않아 기본값을 사용한다. 서버의 Catalog intake 응답 제한은 1,800초,
Office converter의 `systemctl start` 제한은 180초이며 페이지 처리 시간이 추가될 수 있다.

허용된 변환이 150초를 넘으면 브라우저는 먼저 실패할 수 있지만 서버는 진행 중일 수 있다.
장시간 fault injection이나 실제 파일 제출로 재현하지는 않았다. processing lease floor는
이미 서버 제한에 맞게 보강돼 있으므로 예전 300초 lease 결함과 혼동하지 않는다.

권장: 기존 durable intent의 처리 상태를 짧은 시작 응답과 후속 조회로 연결하고, proxy/BFF/API
deadline을 대조한다. timeout 뒤 새 key로 재제출하지 않는다. 모든 timeout을 길게 늘리는
것만으로 해결하거나 새 queue framework를 추가하지 않는다.
검증: 응답 유실·느린 변환·동일 key replay·브라우저 이탈 후 기존 작업 조회·취소 정책.

### U05. 자료 업로드의 복구 identity가 페이지 메모리에만 있다

증거: Web `app.js`의 `submitPdfDocumentReview`, `pdfDocumentReviewPendingSubmission`,
upload helper의 401 로그인 이동. 새 업로드의 intent/content/set/question/solution key는
state에만 보관한다. 페이지 재생성 후에는 새 key가 만들어진다. API workflow key는
`pdf-review-workflow:{upload_intent_id}`로 intent별 identity를 따른다.

U04 같은 불명확한 응답 뒤 새로고침·재로그인하고 같은 파일을 다시 올리면 원래 intent를
복구하지 못하고 별도 요청으로 갈 수 있다. 실제 중복 workflow를 만들지는 않았다.
서버의 동일 key idempotency가 없다는 뜻은 아니다. Web이 그 key를 잃는 경계다.

권장: 기존 Excel import의 복구 접근처럼 작고 사용자에 귀속된 intent/set ID와 key만
보존하고, 재진입 때 동일 권한으로 상태를 확인한다. 파일 bytes·비밀번호·세션·본문은
브라우저 복구 저장소에 넣지 않는다. 실패 이력을 성공으로 바꾸지 않는다.
검증: 각 업로드 단계에서 새로고침/401/timeout, 다른 계정 재로그인, 원래 결과 재개,
동일 파일의 의도된 새 검토와 복구 요청 구분.

### U06. 실제 HWPX 파일의 잘못된 확장자를 처리하는 범위가 다르다

증거: Web `documentReviewSource`는 확장자 hwp를 HWP로 선언한다. API `PdfUploadStager.stage`
는 선언된 HWP에 OLE signature를 요구한다. `stage_detected`는 실제 container 판별을
지원하지만 자료 학습 입력에서 쓰이며 검토 업로드는 strict `stage`를 사용한다.

DB/학습에서 받아들인 파일이 검토에서는 signature 오류가 될 수 있다. 엄격한 선언 검증
자체는 보안 경계이므로 무조건 제거할 결함이 아니다. 공통 제품 기대와 계약 차이로 기록한다.

signature helper의 합성 ZIP header 검사는 strict HWP=False, 자동 판별=HWPX였다.
이 작은 검사는 완전한 HWPX 유효성·실제 변환 성공을 입증하지 않는다.

권장: 확장자 오기를 허용하는 제품 범위를 먼저 확정하고, 필요하면 새 검토 intent를
고정하기 전에 실제 container를 판별하는 기존 모듈을 재사용한다.
원래 파일명은 보존하고, ZIP이라는 이유만으로 모든 파일을 HWPX로 허용하지 않는다.
고정된 기존 intent의 format/hash를 사후에 바꾸지 않는다.

## 운영·용량 관측과 의도된 제한

이 절은 자동 수정 목록이 아니다. U01–U05와 달리 추가 장애 재현이나 원인 계측 전에
새 queue·cache·설정 framework를 만들 근거가 없다.

### INDEX의 여유 메모리와 실제 완료 지연

동일 시점 cgroup에서 2GiB 상한에 약 2.13–2.15GB가 사용 중이었다. anon 약 1.81GB,
file cache 약 318MB였고 `memory.events.max=51037`, `oom=0`, `oom_kill=0`, swap=0이었다.
일부 file cache는 회수 가능하며 당시 pressure 평균은 0이었다. 현재 OOM 또는 특정
cache의 누수를 확정하지 않는다. 반복 reclaim의 존재와 작은 여유만 확인했다.

[직전 GPU 저장 검증](../operations/GPU_INDEX_BATCH_STORAGE_ACCEPTANCE_2026-11-13.md)은
실제 4개 vector·binding·shard·최종 index commit을 확인했지만 owner 처리 구간은 약
34분 34초였다. 이는 순수 GPU encoder 시간이나 전체 대상 완료 증거가 아니다.
source scan·pointer 검증·publication·hash·I/O의 별도 계측 후 병목을 판단해야 한다.
진행 중 INDEX를 재시작하거나 정본 검증을 생략하지 않는다.

### 세션과 상태 표시

Web의 90분 TTL은 현재 코드상 고정 수명이며 활동마다 연장되는 idle timeout이 아니다.
작은 TTL의 합성 시계로 이를 확인했다. 세션은 프로세스 메모리이므로 Web 재시작과
최대 256세션의 LRU eviction도 재로그인 원인이 될 수 있다. 구현된 정책과 사용자 기대를
구분해 안내해야 하며, 이를 로그인 성공 횟수 제한의 재발이라고 단정하지 않는다.

API readiness의 DB revision/role/permission 검사는 전체 Catalog 작업·GPU 처리·파일 변환의
성공 증거가 아니다. 기존 feature별 capability/운영 조회를 함께 봐야 한다.

로그인의 pre-auth 전역 burst 제한도 정상 성공을 포함한다. 사용자별 실패 누적 버그와는
다른 정책이다. `routers/auth.py`와 소스 기본값은 확인했지만 보호된 API 운영 설정은
읽지 않았으므로, 동시 접속 인원에 비해 실제 설정이 낮은지는 운영 담당 조회가 필요하다.
의도적인 사용자 로그인 실패를 반복하는 방식으로 검증하지 않는다.

### 여러 파일을 동시에 변환할 때의 처리량 제한

Catalog `application_server.py`는 `ThreadingMixIn`으로 요청을 처리한다. 확인한 진입부에는
변환 종류별 동시 처리 admission이 없으며, 요청 header를 읽은 뒤 일부 작업에 timeout을
설정한다. 운영 Catalog의 cgroup은 1GiB/128 tasks로 제한돼 있어 완전히 무제한인 것은 아니다.
변환 subprocess는 별도 systemd 격리 경계를 쓴다.

여러 정상 업로드가 겹칠 때 조회까지 지연될 가능성은 있으나, 이번에는 부하·고갈을 재현하지
않았다. 먼저 동시 변환 수, 대기 시간, Catalog thread/RSS, 호스트 여유를 측정한다.
병목이 확인되면 기존 intake adapter에서 작은 동시성 예산과 명시적인 대기/거절을 검토한다.
범용 분산 queue를 먼저 만들거나 모든 DB timeout을 일괄 변경하지 않는다.

## 최초 EOM 설계 원칙과의 대조

평가 기준은 클래스 수·파일 길이가 아니라 책임 소유권과 실제 데이터 흐름이다.

| 최초 원칙 | 현재 확인 | 판단과 최소 대응 |
| --- | --- | --- |
| 계약을 먼저 정하고 명시적으로 통신 | JSON Schema 정본 1,375개·참조 11,789개·mirror 1,026개 감사 통과 | 구조적 drift는 찾지 못함. U02처럼 서로 다른 계약 사이 의미·상한까지 같다는 뜻은 아님 |
| 상위 계층 → application → domain/contract | 현재 AST 의존성 검사 통과. contract/domain의 runtime 역참조 및 service→app 위반을 차단 | 유지. 기존 검토된 runtime composition cycle은 아래와 같이 별도 취급 |
| 캡슐화와 공개 경계 | apps/services/packages의 직접적인 다른 first-party package private-symbol import는 AST 검사에서 0 | 동적 import·행위 전체의 증명은 아님. 불필요한 wrapper를 추가하지 않음 |
| Worker는 실행 결과만, Orchestrator가 조정 | 현재 Runner의 command lease/fence, typed rework/correction, 채팅 예약과 일반 슬롯 분리 확인 | worker DB/NAS 직통 경로를 새로 만들지 않음. 이번에는 실제 worker 실행 없음 |
| 정본과 revision·hash는 분리 | Artifact pointer 검증과 immutable 결과 재조회 경계의 집중 검사 통과 | 구 벡터 삭제·과거 contract 재해석·이력 덮어쓰기는 필요 없음 |
| 상태의 소유자를 명확히 | HWPX/문항 미리보기/Map/Chat에는 선택 epoch·identity guard가 있으나 자료 검토 변경 callback에 빠짐 | U01. 기존 guard 패턴을 해당 화면에 적용; UI 전체 framework 교체 불필요 |
| 같은 규칙은 한 소유자에서 검증 | Excel의 매칭 완료와 실제 편성 생성 가능 판정이 분리됨 | U02. layout 책임에서 구조 가능성을 공유; 서로 다른 곳에 수식 복사 금지 |
| 부작용·재시도 경계를 명확히 | 서버의 intent/idempotency는 있으나 화면의 재진입 복구 연결이 끊김 | U04/U05를 함께 수정. 새 작업을 만드는 것과 기존 작업을 조회하는 것을 구분 |
| 큰 bytes는 명시적 materialization 경계에서만 | Web 다운로드에 경계는 있지만 허용 크기와 동시 메모리 예산이 맞지 않을 수 있음 | U03. 해당 adapter만 bounded 처리; binary를 DB로 옮기지 않음 |
| 가장 단순한 충분한 구현 | 기존 수평 슬롯·서비스·receipt·revision·adapter 재사용 가능 | 새 검색 엔진·registry·queue·DI framework·microservice 분리 불필요 |

`MODULE_BOUNDARIES.md`의 네 package(Catalog/Identity/Orchestrator/Workflow Runner)는
공유 ORM/transaction composition으로 검토된 순환 cluster다. 최초의 순환 금지 목표를
완전히 충족한 상태라고 쓰지는 않는다. 현재 의존성 검사는 이 예외가 확대되지 않도록 한다.
이를 한 번에 분리하면 atomicity와 복구를 해칠 수 있으며, 이번 사용자 오류와 직접 연결되는
새 위반은 찾지 못했다. **기존 부채 보존 항목이지 이번 우선 수정 항목은 아니다.**

`query_adapter.py`, `workflow_catalog.py`, `app.js`의 크기도 후속 변경 시 책임 경계를
살필 이유는 되지만, 크기 자체가 결함의 증거는 아니다. 이번에는 U01 등 실제 문제의
소유권만 좁혀 고치면 된다. 파일을 잘게 나누기 위한 클래스·상속·mixin을 만들지 않는다.

## 사용 흐름별 검토 범위

| 흐름 | 확인한 코드·방어 | 남은 범위 |
| --- | --- | --- |
| 로그인·계정 관리 | 성공/실패 rate-limit 회귀, 관리자 CAS·receipt 단일 transaction, session→token 잠금 순서, Web refresh 공유 lock | 실제 보호 설정·여러 사람의 동시 로그인 부하 미검증 |
| 슬롯·모델 설정 | 01–05 안정적 탐색, 06 채팅 예약, model-only successor, exact pin, command fencing | 실제 계정 교체·quota·모델 호출은 실행하지 않음 |
| 출제·문항 검토 | 현재 교과서 admission, Pack 경계, exact-source rework·correction 상한과 lease 검사 | 모든 worker 오류가 3교로 복구되는 것은 계약이 아님. 과학 품질은 별도 |
| 자료 검토 | 단일/짝 업로드 replay, lease floor, 주석/수정 use case, 늦은 UI 변경 응답 | U01/U04/U05/U06 |
| 자료 학습·등록 | claim heartbeat, 원래 claim token 재검사, 최대 32 retry 이력의 명시적 제한 | 실제 대형 교재·형식별 의미 분해 품질 및 DB 경합 미검증 |
| DB·Excel·Map | workbook reader의 ZIP/XML/수식 방어, layout·dispatch, Map 선택 sequence, 기존 typed pointer 조회 | U02. 실제 사용 자료 전체의 metadata 정확성을 감사하지 않음 |
| 미리보기·HWPX·PDF | 선택 sequence, 결과 pointer, 원래 renderer job 중단 복구, 변환/주석 모듈의 집중 검사 | U03. 실제 Hancom 렌더링·폰트 조합 전체 미검증 |
| 유사도·INDEX | 완료 결과 읽기는 prepare/dispatch와 분리, 현재 owner 자료와 메타데이터 해석 경계 확인 | 메모리·publication 지연 관측. 새 live 검색이나 GPU 실행 없음 |
| API·릴리스 | source와 설치 source 대조, body 크기·contract mirror·의존 방향 검사 | 재배포·crash injection·복구 훈련은 이번 조사 범위 밖 |

32회 자료 학습 재시도는 history reader만 임의로 잘라낸 값이 아니다.
`material_learning_recovery.py`도 같은 `MAX_MATERIAL_ATTEMPTS`로 새 retry를 제한한다.
따라서 이번에는 “reader가 정상 이력을 놓친다”는 후보에서 제외했다.

## 이미 해결됐거나 이번 가설이 기각된 항목

과거 [체크포인트 리뷰](/home/eom/EOM_CODE_REVIEW_POST_CHECKPOINT_2026-10-24.md)와
[설계 오류 검토](DESIGN_ERROR_REMEDIATION_REVIEW_2026-11-08.md)를 현재 source 및
[모듈 경계의 11월 5일 수정 기록](MODULE_BOUNDARIES.md#2026-11-05-배치-확장-전-경계-검토),
[11월 12일 정비 기록](../operations/MAINTENANCE_CONSOLIDATION_VERIFICATION_2026-11-12.md)과 대조했다.

| 이전 후보/가설 | 현재 확인 | 이번 판정 |
| --- | --- | --- |
| 단일 HWPX 중단 후 RUNNING 잔류 | `renderer_recovery.recover_item_renderer_job`의 기존 source/job/output 확인 및 중단 처리 | 새 결함으로 재등록하지 않음. 실제 PostgreSQL 중단 검사는 이번 미실행 |
| refresh/계정 변경 잠금 역전·ETag 외부 검사·계정 변경/receipt crash gap | Identity/API의 동일 transaction·잠금 순서·CAS 유지 | 해결된 항목. 부가 잠금 서비스 불필요 |
| Web refresh 경합·무제한 replay cache·관리자 목록 200개 선필터 | 공유 session lock, 64항목/256KiB session replay budget, SQL 필터 확인 | 기존 해결 유지 |
| 문서 lease 300초와 Catalog 1,800초 불일치 | composition의 response/continuation 예산을 포함한 lease floor | 해결 유지. U04는 별도의 Web 응답 대기 경계 |
| API chunked JSON 초과가 400으로 바뀜 | 합성 요청에서 declared/chunked 모두 413 `API_BODY_TOO_LARGE` | 가설 기각 |
| XLSX formula injection·무제한 확장·외부 참조 | export inlineStr, reader 수식/외부 관계 거부, ZIP member/XML/확장 크기 제한 | 해당 방어 존재. U02의 구조 상한은 별도 |
| access 만료 때 소비된 upload stream 재전송 | MockTransport에서 요청 1회 뒤 401, refresh/replay 없음 | 중복 stream 재전송 가설 기각. 재진입 문제는 U05 |
| 자료 검토 page image의 늦은 onload | 기존 선택 guard 존재 | 이미 해결. U01의 annotation/correction callback과 구분 |
| 자료 학습 재시도 32회 이후 묵시적 이력 절단 | retry owner와 reader가 같은 상한 사용 | 가설 기각 |
| `FAILED_FINAL`/retention을 domain 실패·key 재사용으로 해석 | `API_IDEMPOTENCY.md`가 transport receipt와 cleanup 의미를 구분 | 새 상태기계 수정 필요 근거 없음 |

## 검증 증거와 한계

격리 probe는 source를 읽어 실행하며 운영 DB·live HTTP·모델을 사용하지 않았다.

- `staging/real-user-risk-probes-20261113.py/.json`: workbook 상한, 고정 TTL,
  본문 상한과 consumed-stream replay 가설을 검사한 소규모 개발 자료.
- `staging/real-user-review-races-20261113.mjs/.json`: U01의 실제 callback 2개 재현.
- `staging/real-user-safe-runtime-settings-20261113.json`: 비밀값 없는 허용 설정만 추출.

위 staging 파일은 정본 시스템 데이터가 아니며 Git에 넣지 않는다. 이 문서의 압축된
결과를 검토 기록으로 보존한다. 운영 장애를 만들지 않았으므로 최악 조건의 실제 메모리,
네트워크 단절, PostgreSQL 동시성·crash consistency는 별도 격리 검증이 필요하다.

추가 확인 결과:

- 계약 감사: JSON Schema 2020-12 정본 1,375개, 참조 11,789개, mirror 1,026개 PASS.
  의미적 input/output 일치 전체를 보증하는 검사는 아니다.
- 집중 suite A: **427 PASS, 실제 Playwright 환경 필요 1 SKIP**. rework/correction,
  command fence, 슬롯·모델, claim 갱신, 의존 방향, Artifact pointer, workbook,
  로그인 제한, 검색 기록/브라우저 binding을 포함한다.
- 집중 suite B: **152 PASS, 실제 Playwright 환경 필요 1 SKIP, opt-in 1 DESELECT**.
  HWPX Manager/application, Office converter/수식 품질/입력, PDF 주석, upload replay,
  idempotency, 주석·교정 application, 문항 preview·모델 설정을 포함한다.
- 합계 **579 PASS**. fixture는 임시 파일·mock·테스트용 저장소를 사용한다.
  운영 PostgreSQL·live 모델·GPU·실제 파일 변환을 사용한 acceptance는 아니다.
- 두 suite에서 같은 Starlette TestClient deprecation warning이 있었다. 현재 사용자
  장애로 분류하지 않으며, 이번 작업에서 의존성을 임의 추가/갱신하지 않았다.
- `git diff --check` PASS, 이 문서와 문서 안내의 로컬 링크 34개 확인 PASS.

실행 환경은 `/srv/eom/conda/envs/eom-api/bin/python -B`다. source 검사는 root
`pyproject.toml`의 `tool.mypy.mypy_path`와 repository root를 `sys.path` 앞에 넣었고,
pytest cache를 끈 상태로 두 개의 전용 `/tmp/eom-real-user-*-tests-20261113`를 사용했다.
실행한 테스트 파일은 위 영역의 기존 테스트이며 새 production 코드나 회귀 코드를 추가하지 않았다.

## 권장 후속 순서와 범위 제한

1. **U01:** 자료 검토의 늦은 응답 소유권을 기존 선택 guard로 수정한다.
2. **U04/U05:** 업로드를 같은 intent로 이어갈 수 있도록 기존 status/replay를 연결한다.
   화면 timeout과 재로그인 복구를 하나의 사용자 흐름으로 검증한다.
3. **U03:** 다운로드 adapter의 peak memory와 동시성 예산을 정하고 bounded 처리한다.
4. **U02:** Excel 준비 단계가 실제 생성 가능한 구조만 준비 완료로 표시하게 한다.
5. **U06:** 확장자 오기를 허용할 검토 입력 범위를 확정한 경우에만 기존 판별기를 재사용한다.

이것이 이번 조사로 근거가 생긴 수정 범위다. 운영 관측 항목은 실제 병목 계측 후 필요한
것만 추가한다. 과거 contract/설정/실패 기록 삭제, 전면 OOP 재설계, 추가 플랫폼 도입,
코드 줄 수를 줄이기 위한 대규모 파일 이동은 포함하지 않는다.

후속 구현의 공통 승인 조건은 선택/계정이 바뀌어도 결과 소유권 유지, 중복 부작용 0,
정본과 pin 보존, 명확한 오류/대기 상태, 측정 가능한 자원 한도다. DB 상태·lease·receipt가
바뀌는 수정은 disposable PostgreSQL에서 중단·동시성·재전송을 검증하고, Web만 바뀌는
수정에 불필요한 GPU/25문항 생성 acceptance를 붙이지 않는다.

최종 판정: **기록 목표 완료, 수정·배포 미수행**. 발견 항목을 다음 작업의 입력으로 쓰되
이 문서를 모든 기능의 정상 동작 보증이나 자동 운영 변경 권한으로 사용하지 않는다.
