# EOM 생성 문항 정리 경계 (2026-10-28)

## 현재 판정: 운영 적용 완료

2026-10-28 16:40 UTC 정리를 완료하고 원래 active였던 서비스 7개를 재개했다. 이 절이 현재 상태이며, 아래 조사·연습·구현 후보 절의 `미실행` 표현은 각 조사 시점의 기록이다. 과거 관찰이나 실패를 성공으로 덮어쓰지 않는다.

| 항목 | 실제 운영 결과 |
| --- | --- |
| EOM 생성 문항 | 승인된 대상 Item 110개·Revision 111개 삭제, 대표 샘플 1개 보존 |
| 보존 샘플 | `item_f913cf57d96a4fd287381b09eaf7f32e` / `itemrev_2f962f0bb4db4718b6e7af7d6fc8982f`, `APPROVED` |
| 기출·교과서 | Graph 67의 기출 source 520개·교과서 source 10개와 보호 metadata fingerprint 보존 |
| 가져온 창작·legacy | 외부 원천 source 1,297개·legacy Item 757개 보존. 서로 다른 모집단이므로 합산하지 않음 |
| 구 Graph와 파생 이력 | 승인된 Graph 68/69 및 관련 workflow 921개 정리 |
| 공유 producer | 후보 Job 2,134개 중 공유 참조가 있는 1,216개 보존, 전용 918개 삭제 |
| NAS·백업 | 기존 감사 파일과 복구용 백업 보존. 기존 NAS 파일 물리 삭제 0개 |
| 재전송 | 같은 계획으로 `apply` 재전송 시 동일 receipt Job/Artifact/Revision 반환, 새 삭제·새 Job 생성 없음 |
| 가용성 | API readiness와 실제 HTTPS readiness `READY`, 보존 샘플의 Catalog 내용 조회 및 기존 HWPX secure read/hash 확인 |
| 검색 복구 | Graph 67의 `CONTENT_ONLY` current index 520/520 게시 확인. 나머지 view/device는 기존 INDEX owner가 계속 준비하며 전체 짝 완료로 확대 해석하지 않음 |
| runtime | API/Web 및 INDEX/QUERY의 기존 설치 pin·Codex 인증·worker 설정·DB migration head 변경 없음 |

실행 도구 source는 `3a8692641d917f0285b1773bf029588ee9b04b57`, root 소유 설치본은 `/opt/eom/maintenance-releases/3a8692641d917f0285b1773bf029588ee9b04b57/site-packages`다. wheel SHA-256은 `f26dca8ba0f0778f65dddf8fc02521b21fee9fda35490b9e2ba2ce67e0581a6e`, 설치된 RECORD 2,116개 해시를 검증했다. 진행 중이던 다른 문서 변경은 이 릴리스에 포함하지 않았다.

정본 계획은 `artifact_ea7ea7310cb94de48aaa02c687ed4ce8` / `rev_f3b50a188f5e4525ae696f112b3a1f78`, plan SHA-256은 `e16a2149ee01c681766ff1309f13d794288bbdaf5c68d4c724470113303dbde6`이다. 완료 영수증은 `artifact_b6c19da7848243019c17b47d04e5d8f0` / `rev_bc8479c648ff4974a06b8adc19d2f755`, primary `receipt.json`의 SHA-256은 `82ec85a83bc8c9d043b659568e00aa9c0ec3d0342b28196fe82dad18f1276df8`이다. 실제 삭제 수는 이 영수증을 기준으로 보며 아래 오래된 연습 수치를 더하지 않는다.

적용 직전 백업은 `/mnt/nas/eom/backups/postgresql/eom_20261028T162742Z_1edaf9f60765.dump`와 같은 basename의 `.manifest.json`이다. 운영과 분리된 복원 DB에서 interruption rollback·동시성·drift rejection·적용/재전송 6개 검사를 통과했고, 확인 후 disposable DB·전용 role·local state만 공식 cleanup으로 제거했다. NAS 백업은 그대로 보존한다.

후속 INDEX 관찰에서는 `workflow_5c51ee0d1f7440e69a2b18fbebc31faa`가 `COMPLETED`, 명령이 `SUCCEEDED`가 됐다. 별도 native GPU 보조 unit `aef559153f4d40d99bc0c9dc6ab55c63`에는 channel `BlockingIOError` 종료 기록이 있으며 이를 초기화하거나 성공으로 바꾸지 않았다. INDEX owner 자체는 계속 active이고 다음 요청을 준비한다. 따라서 위 `CONTENT_ONLY` 등록 복구와 전체 GPU device/view acceptance를 같은 성공으로 보고하지 않는다. 정리 자체의 source 회귀 최종 재실행은 36개 PASS다. 설치본을 source용 pytest 대상으로 선택한 환경 오류는 개발 source 경로로 바로잡았으며 운영 데이터 오류로 재분류하지 않았다.

이번 사용 사례는 과거 게시 Graph·시험지·검색·실행 이력까지 함께 제거하는 **일회성 prelaunch 물리 정리**다. 앞으로의 일반 삭제 버튼은 기존 Registry lifecycle/retirement application을 사용해 사용 대상에서 제외하고 불변 감사 이력은 보존해야 한다. 일반 삭제에 Graph 전역 되돌리기·공유 producer purge·서비스 점검 창을 묶지 않는다. 이번에 새 범용 GUI hard-delete 기능을 추가한 것은 아니다. 실행 경계와 재전송 절차는 [운영 runbook](../operations/PRELAUNCH_ITEM_RESET_RUNBOOK.md)을 따른다.

## 목적과 정본

시험 운영 전 EOM의 `generic-item-development` 워크플로가 만든 문항 중 대표 샘플 1건만 남기고 나머지 문항 및 문항 메타데이터를 제거한다. 기출 분석, 교과서, 외부에서 가져온 창작 문항은 대상이 아니다. 삭제 집합은 `APPROVED_ITEM`이라는 Graph source class만으로 추정하지 않고, 각 Item Revision에 고정된 `workflow_id`를 `workflow_instances.definition_key`와 대조해 산출한다. 이 집합의 해시와 보존 샘플을 실행 전에 고정해야 한다.

읽기 전용 운영 조사 시점에 `generic-item-development`에서 등록된 문항은 111건, 버전은 112건이다. 이 중 110개 워크플로는 `COMPLETED`, 1개는 `FAILED`이며 등록 문항에 연결된 진행 중 워크플로는 없다. 최초 샘플 후보 `item_07b817a17dce4f4cb13ee60a02014a00`는 삭제할 Graph 69에 고정된 실행 계획을 갖고 있어 보존 대상에서 제외했다. 사용자의 샘플 교체 승인 후 보존 후보는 `item_f913cf57d96a4fd287381b09eaf7f32e` / `itemrev_2f962f0bb4db4718b6e7af7d6fc8982f`로 변경했다. 이 버전은 `APPROVED`, 단일 HWPX 성공 1건, 기출·교과서 Graph 67 실행 계획을 갖고 있고 삭제 Graph 68/69의 source pointer·시험지 placement에 포함되지 않는다.

## 확인된 참조와 위험

111개 문항 전체에 대해 읽기 전용 집계한 현재 참조는 다음과 같다.

| 경계 | 확인된 참조 |
| --- | ---: |
| 단일 HWPX | 22개 문항의 44개 build, 성공 33개 |
| 기존 시험지 placement | 25개 |
| Graph source pointer | 두 published snapshot의 26개 Item Revision, pointer 행 3,308개 |
| 임베딩 source binding | 6개 |
| 풀이/지식 분석 run | 27개 |
| 문항 review record | 25개 |
| 문항 component | 518개 |
| 문항 metadata snapshot | 112개 |
| 문항 event | 113개 |

최초 샘플 후보 기준 집계는 시험지 placement 25개, Graph pointer 행 3,240개(25개 Item Revision), 지식 분석 run 25개, 단일 HWPX build 42개(성공 31개, 21개 문항)였다. 샘플 교체 후에는 삭제 대상에 기존 샘플의 Graph pointer 및 embedding binding 6개가 포함되고 새 샘플은 빠진다. 따라서 위 최초 집계를 운영 삭제 수량으로 사용하지 않는다. 새 기준의 110개 문항·111개 버전과 연관 행은 아래 재검증 수치만 사용한다.

2026-10-28 읽기 전용 재조회에서 삭제 후보 110개 문항은 모두 `ACTIVE`였고, 연결된 111개 버전은 `APPROVED` 105, `IN_REVIEW` 5, `SUPERSEDED` 1이다. 새 보존 샘플 기준 문항 ID를 사전순 정렬한 JSON 배열의 SHA-256은 `fd53d8cae3e79069d3af824fbbbae91932eb3202724ae988a3d418492f5c3b6c`이다. 실제 실행 전 같은 정렬/직렬화로 이 값을 재검증한다. 시험지 placement 25개는 모두 단일 `assemblyrev_f42d6a195e07f21221d24baea250f0c4`에 속하고, 해당 assembly revision의 전체 placement 역시 25개라 비대상 문항과 혼합되지 않았다.

최초 보존 샘플 기준으로 다른 문항으로 향하는 `item_relationships` 11개가 확인됐다. 새 샘플 기준 격리 연습에서는 관계 12개가 대상이었다. 이 관계를 제거하더라도 상대방 문항·기출 노드 자체는 삭제 대상이 아니다. `usage_plans`, `usage_records`/`usage_records_v1`, 교육 품질 검토 plan, legacy editorial compatibility, assessment occurrence reference에서 이 110개를 직접 가리키는 행은 0개였다.

기존 일반 사용자 API에는 `retire`만 있고 hard purge 사용 사례는 없다. 단순 `items`/`item_revisions` 삭제는 여러 `RESTRICT`/일반 FK에 막히며, FK가 없는 Graph source revision pointer도 dangling이 된다. 이미 게시된 Graph snapshot의 pointer를 제자리 수정하면 snapshot hash와 불변 이력이 달라진다. 기존 HWPX와 Assembly는 별도 정본 Artifact를 참조한다. 따라서 직접 SQL로 순서를 맞춰 삭제하거나 `DELETED_SOFT`만 지정하고 완전 삭제라고 보고해서는 안 된다.

추가 대조 결과, Graph revision 67 (`graphrev_7870b0fb03b7dfb64179e53182bf3999`)은 기출 520 source revision·교과서 10 source revision을 포함하고 `APPROVED_ITEM`은 0이다. revision 68은 기출 520·교과서 10을 그대로 유지하며 `APPROVED_ITEM` 25를 추가했고, 현재 revision 69는 같은 기출·교과서에 `APPROVED_ITEM` 26을 포함한다. 따라서 기출 노드를 보존할 기준 snapshot은 있다. 그러나 revision 68/69에는 교육 검색 request·evidence bundle 각 66건, 임베딩 index revision 697건과 source binding 4,346건, past-exam occurrence reference 1,040건도 고정돼 있다. 이들이 삭제 대상 EOM 문항에서만 파생됐는지, 외부 문항/일반 조회가 참조하는지 분류하지 않고 두 snapshot을 제거해서는 안 된다.

그 66개 교육 검색 request 중 `target_item_revision_id`가 있는 23개는 삭제 대상이 아닌 `legacy-item-extraction` 문항 버전에 연결된다. 나머지 43개는 target 값이 없다. 따라서 revision 68/69 전체를 삭제하면 적어도 23개 기출 계열 조회/근거 영수증의 고정 Graph 참조가 깨진다. `revision 67으로 돌아가면 기출 노드가 남는다`는 사실만으로 `68/69를 물리적으로 지워도 기출 이력이 보존된다`고 결론 내릴 수 없다. 완전 물리 삭제를 하려면 이 23개와 연결된 불변 요청·bundle의 보존/재생성 의미를 별도로 합의해야 한다.

후속 evidence-entry 대조로 이 23개 bundle의 실제 근거 항목 23개는 모두 `legacy-item-extraction` 문항 버전이었다. EOM 생성 AI 문항을 이 23개가 실제 인용했다는 뜻이 **아니다**. 반대로 target 값이 없는 43개 request의 bundle에는 EOM 생성 문항 버전 근거 항목 18개, legacy 문항 버전 1,024개, 문서 버전 133개가 들어 있다. 이 43개 요청의 소유 워크플로는 별도로 매핑해야 한다. Graph snapshot에 AI source가 포함됐다는 사실과 특정 Evidence Bundle이 AI source를 사용했다는 사실을 혼동하지 않는다.

이 23개를 더 세부 대조하면 각 요청의 target Item Revision과 bundle의 source Item Revision이 **모두 동일**하다. 근거 용도는 전부 `REFERENCE_PATTERN`이며 종류는 `ITEM_REVISION` 17개와 `CLAIM` 6개다. 즉 기출 PDF 원문, 520개 승인 분석 또는 풀이보고서가 아니라, 기출 추출 경로 문항을 자기 자신에 연결한 파생 검색/참조 영수증 23개다. 이를 `기출의 정본 근거 23개`라고 표현해서는 안 된다. 제거/재발행 시에도 520개 기출 Graph source와 분석이 유지되는지 별도로 검증한다.

같은 snapshot을 고정한 나머지 검색 request 43개는 target Item Revision이 없다. 요청 source-class 선택은 `APPROVED_ITEM+PAST_EXAM+TEXTBOOK` 36개, `PAST_EXAM` 전용 6개, `CURRICULUM+TEXTBOOK` 1개다. 23개 자기참조 영수증만 삭제해도 이 43개와 그 Evidence Bundle이 snapshot 68을 계속 참조하므로 AI source가 든 과거 snapshot을 물리적으로 제거할 수 없다. 이 43개는 요청 범위상 별도 파생 기록이며, 실제 소유 작업/사용자 결과를 대조하고 제거 승인 범위를 고정해야 한다.

추가 FK 확인: 과거 AI Graph snapshot은 `knowledge_snapshot_analyses`를 통해 AI `knowledge_analysis_runs`를 참조한다. 해당 run은 AI `item_revisions`를 `RESTRICT` FK로 참조한다. 동시에 기출 23개 request/bundle은 같은 Graph snapshot을 `RESTRICT` FK로 참조한다. 따라서 23개 기출 근거 기록을 원형 보존하면서 AI Item Revision·그 분석 run·Graph snapshot의 모든 영속 metadata를 물리적으로 삭제하는 것은 현행 스키마/불변 계약에서 동시에 성립하지 않는다. 가능한 범위는 (a) 현재 조회·검색·등록 뷰에서 AI 문항을 제외하고 과거 감사 참조를 제한 보존하거나, (b) 기출 23개를 새 Graph에서 재발행한 뒤 과거 영수증 원본까지 제거하는 별도 파괴적 migration이다. 어느 쪽도 단순 `retire`나 직접 SQL로 대체하지 않는다.

## 구현 경계

### 승인 후 구현 결정: 한 번의 정리와 평소 삭제 분리

사용자가 소유 모듈을 통한 관리자 정리 기능 구현을 승인했다. 평소 삭제는 기존 Item lifecycle/application을 확장해 등록 문항을 사용 대상에서 제외하는 흐름으로 유지하고, 이미 게시된 Graph·풀이·시험지의 불변 이력을 연쇄 물리 삭제하지 않는다. 이번 요청만 별도로 고정한 prelaunch reset scope를 처리한다. 임의 Item ID 목록을 받아 전체 Graph를 삭제하는 범용 purge API는 만들지 않는다.

이번 구현은 Orchestrator application이 공통 transaction·정본 계획·원자적 rollback을 소유하고, Catalog/Workflow/HWPX/Artifact 소유 application 포트를 조합한다. 각 adapter는 자기 component의 행·명명된 불변 트리거만 변경한다. CLI는 계획 생성·확인·적용을 호출할 뿐 SQL/업무 규칙을 구현하지 않는다. 실행 권한은 실제 local maintenance principal·DB owner metadata·서비스 정지 확인에서 나온다. 요청 DTO의 권한 문자열은 근거가 아니다.

속도와 호환성을 위해 영구 schema/migration 증가는 피한다. Catalog 소유자가 **동일 transaction 안에서만** 고정 이름의 보조 FK lookup 인덱스 두 개를 만들고, 정리와 무결성 검증 후 같은 transaction에서 제거한다. 성공·실패 어느 경우에도 운영 schema에 새 index가 남지 않는다. 이는 평소 삭제 경로가 아닌 일회성 reset의 실행 최적화다. 새 migration head나 INDEX/QUERY 실행 pin을 바꾸지 않는다. 기존 동명 index가 있거나 다른 정의면 자동 재사용/삭제하지 않고 중단한다.

지배적 연산은 indexed identity lookup, bounded ordered IDs, 참조 membership, 공유 producer dependency closure다. 계획은 frozen typed model과 JSON Schema 2020-12로 검증하며 target ID set·원래 revision/hash·보호 집합 fingerprint를 고정한다. 각 소유자의 public application 경계를 설치 wheel에서 호출하고 root transaction에서 actual snapshot을 재대조한다. 기존 source script를 운영용으로 우회 활성화하지 않는다.

2026-10-28 후속 승인: 사용자는 짧은 검색 점검 창과 삭제 대상에만 쓰인 Artifact/Job DB 기록의 정리도 허용했다. 공유 기록·NAS 감사 파일·복구용 백업은 보존한다. 계정 관리 요청은 별도 공식 Identity recovery 사용 사례로 처리하며 이 데이터 정리 범위에 넣지 않는다.

### 관리자 정리 사용 사례의 짧은 설계 결정

| 항목 | 결정 |
| --- | --- |
| 책임/경계 | Orchestrator가 점검 창·고정 계획·중단/재개를 조정한다. Catalog는 Item·Graph·검색·임베딩 관계를, Workflow runner는 실행 상태/명령을, HWPX 소유자는 build 관계를 자신의 application 경계에서 정리한다. Worker에 DB/NAS 쓰기 권한을 주지 않는다. |
| 정본/버전 | 삭제 전 정본은 등록된 Item Revision·Graph Snapshot Revision·Artifact Revision이다. 보존 샘플과 기출·교과서·창작 source revision은 정확한 ID/hash로 고정한다. NAS 감사 파일·백업은 보존한다. Artifact/Job DB 행은 공유 참조와 전용 감사 범위를 확인한 뒤 결정한다. |
| 조회 패턴 | Item/workflow/revision/key 직접 조회, 고정 Graph의 source·index 역참조, exact target 집합 membership 검사, index head의 compare-and-swap이다. |
| 자료구조/인덱스 | 110개 목표 ID는 정렬된 immutable tuple + SHA-256, 중복 검사는 set, 관계 검색은 기존 FK/B-tree/unique 제약을 사용한다. 전체 운영 corpus를 Python 리스트로 반복 스캔하지 않는다. |
| 규모/복잡도 | 이번 정리는 110 Item·111 Revision과 두 Graph snapshot의 파생 관계에 한정된다. 계획 생성은 관련 행 수에 선형이며, index revision 역순 제거는 revision 수에 선형이다. 새 범용 purge framework는 만들지 않는다. |
| 트랜잭션/경합 | 서비스 owner fencing과 실제 current head·target hash를 재확인한다. 실제 host 실행·claim이 quiescent임을 확인하고 최신 백업과 동일 입력을 고정한다. 각 소유 adapter의 DB 관계 변경은 하나의 root transaction·advisory/table lock 안에서 수행한다. |
| 실패/재전송 | 계획 hash 또는 참조 수가 변하면 쓰기 전에 중단한다. transaction 내 실패는 전체 rollback하고, commit 이후 receipt 게시 전 중단은 같은 계획의 사후 조건 검증 후 receipt만 복구한다. 이미 게시된 receipt는 그대로 반환한다. 기존 실패 이력을 성공으로 바꾸지 않는다. |
| 간단한 대안 | 기존 `retire`는 일반 목록에서 숨길 뿐 Item/Graph metadata를 남겨 사용자 요구를 충족하지 못한다. 단일 raw SQL은 component 소유권·불변 이력·동시 실행 fencing을 우회하므로 운영 경로가 될 수 없다. |

비교를 위한 disposable 스크립트는 FK 순서를 실험할 뿐, 이 관리자 application 사용 사례를 대체하지 않는다.

사용자는 2026-10-28 대화에서 샘플 1개 보존, 기출 520개 노드 보존을 전제로 AI 문항의 정리를 승인했고, Graph 68/69에 묶인 파생 검색 request/bundle 66개 및 과거 임베딩 인덱스의 제거 범위도 승인했다. 이 승인은 운영 DB에 즉시 직접 SQL을 실행하거나 기출·교과서·외부 창작 정본을 삭제한다는 뜻이 아니다.

1. 삭제 승인 범위는 문항·메타데이터, 전용 시험지/단일 HWPX 관계, Graph·풀이 이력의 운영 DB 관계 정리까지다. 사용자는 NAS 감사 파일과 복구용 백업을 보존하기로 결정했다. Artifact/Job 감사 행 가운데 공유 참조가 있는 것은 보존하고, 전용 행은 감사 정책을 확정한 뒤 정리한다. NAS bytes는 삭제하지 않는다. 삭제 대상에 보존해야 할 다른 문항 또는 공유 artifact가 있으면 중단한다.
2. Catalog/Orchestrator의 관리자용 application maintenance use case를 설계한다. 보존 샘플과 삭제 대상 ID 집합, 각 고정 revision/hash, 참조 수, 현재 활성 Graph/임베딩 상태를 typed plan에 담는다. 프리플라이트와 실행은 같은 plan hash를 사용하고 예상 참조 수가 바뀌면 fail closed한다.
3. 현재 Graph/검색에서 삭제 대상이 보이지 않도록 successor activation을 먼저 준비한다. 기존 published snapshot을 제자리 수정하지 않는다. 과거 snapshot 및 build의 물리적 제거 여부는 별도의 명시된 제품·감사 결정에 따른다.
4. 작업 중인 GPU index owner와 겹치지 않는 실행 창에서 인덱싱을 멈추고 대상 source binding·index head를 재계산한다. CPU fallback/QUERY의 pinned release는 유지한다.
5. 운영 DB 관계 정리는 각 소유 application의 관리자 경계에서 수행한다. 항목·metadata·component·review·analysis·assembly/HWPX와 artifact 참조를 먼저 검증한다. NAS 감사 파일과 복구용 백업은 보존한다. Artifact/Job DB 행은 공유 참조를 판정하고 감사 manifest로 재식별 가능한지 검증한 뒤 범위에 따라 처리한다. 각 단계는 멱등이며 중간 실패 시 남은 참조와 재개 위치가 명확해야 한다. SQL이나 NAS 경로를 worker에 제공하지 않는다.
6. disposable PostgreSQL에서 대상 110개와 보존 1개, 공유 artifact, historical snapshot, concurrent 조회, 재전송, 중단/재개를 검증한다. 운영에서는 삭제 전/후 개수와 샘플 read, 기출·교과서·창작 read, Graph/임베딩 조회를 대조한다. 제거된 내용·비밀·파일 경로를 Slack에 보내지 않는다.

### 검증·실행 순서 초안

운영 DB와 동일 시점의 백업을 먼저 만들고 disposable DB에 복원해 실제 FK·데이터 형태로 삭제 순서를 검증한다. 현재 백업을 만들었다는 사실만으로 삭제 준비가 완료된 것은 아니다. 승인된 범위는 110개 Item, 그 111개 Revision, 25개 전용 Assembly placement/Assembly, 42개 단일 HWPX build, Graph revision 68/69, 이 버전에 고정된 파생 검색 request/bundle 66개와 임베딩 인덱스다. 520개 기출·10개 교과서 source revision, 외부 창작 import, 샘플 Item은 불변 검증 대상으로 둔다.

실행은 단일 관리자 명령이 target-set hash·현재 Graph/Assembly/인덱스 head·예상 참조 수를 잠근 뒤, 인덱싱 신규 작업을 정지하고 owner별 삭제 순서를 수행해야 한다. Graph 현행 포인터는 67의 정확한 revision/hash로 전환하고, 68/69에 고정된 파생 의존성을 정리한 후 두 snapshot과 해당 corpus revision을 제거한다. 구 index namespace의 current/previous chain을 끊는 과정은 각 revision을 역순으로 제거해야 하며, encodings가 공유되는 경우 삭제하지 않는다. 그다음 AI 분석 run, 전용 Assembly/HWPX, Item 부속 metadata와 본체를 정리한다. 중간 단계가 실패하면 새 쓰기를 시작하지 않고 남은 참조를 재조회한다. NAS bytes는 제한된 감사 보관으로 남기며, DB 행 삭제 여부와 별개로 사용자에게 전체 물리 삭제라고 보고하지 않는다.

정본 문항 → 불변 버전 → component/artifact pointer와 Graph snapshot → source pointer 관계를 보존해야 한다. 사용자에게 숨기는 것과 모든 영속 metadata 및 파일을 물리적으로 제거하는 것은 서로 다른 작업이며, 결과 보고에서 구분한다.

## 2026-10-28 실행 준비 결과

- 운영 데이터를 읽기 전용으로 재확인했다. 삭제 대상 110개 Item의 정렬된 ID 집합 해시는 위 값과 동일했고, 보존 샘플 1개는 별도로 고정했다.
- 운영 백업 `/mnt/nas/eom/backups/postgresql/eom_20261028T105705Z_e13d65090d66.dump`를 생성했다. 백업은 복구용이므로 과거 데이터를 포함한다. 백업 생성은 운영 삭제가 아니다.
- 이 백업을 disposable PostgreSQL에 복원해 `scripts/catalog/prelaunch_ai_item_reset.py`의 **초기 FK 범위** 두 단계로 관계 삭제를 연습했다. Graph 68/69와 고정 검색 66건, 해당 인덱스 700개 revision/4,354개 binding, Item 110건·Revision 111건을 제거하는 FK 경로와 트리거 복구는 PASS였다. 그러나 후속 read-only 감사에서 Graph 68/69를 고정한 `resolved_execution_plans` 60개가 별도로 발견됐다. 초기 PASS는 이 의미상 dangling pointer를 검사하지 않았으므로 완전한 삭제 PASS가 아니다. 새 가드는 계획 미처리 시 `AI_ITEM_RESET_PINNED_PLANS_UNRESOLVED`로 fail-closed한다. 모든 검사는 격리 DB에서만 수행했고 운영 DB를 변경하지 않았다.
- 사후 검증에서 기출 Graph source 520개, 교과서 source 10개, 외부 창작 source 1,297개, legacy-extraction Item 757개 및 샘플 1개가 보존됐다. 이 수치는 해당 백업 시점의 복제 DB 기준이다.
- 새 샘플 기준 읽기 전용 감사에서 삭제 대상 Item에 직접 연결된 Artifact와 Graph/검색/임베딩/대상 workflow의 산출물을 넓게 합친 참조 후보는 Artifact Revision 1,577개, 기록된 payload 합계 약 1.77GB다. **이 수치는 파일 삭제 승인 집합이 아니다.** 공유 파일·재사용 가능한 기출 인코딩·다른 작업의 소유 여부를 판정하기 위한 감사 목록이며, 실제 파일 삭제 0건이다. 대상 Item workflow 110개와 Graph 68/69 고정 계획 60개의 합집합은 143개 terminal workflow다. 60개 계획의 구성은 등록 대상 AI 문항 workflow 27개, 등록 문항이 없는 출제 계획 28개, 비교 실험 4개, 자료 검토 1개이며 보존 샘플은 0개다. 사용자는 그 과거 기록의 삭제와 샘플 교체를 명시적으로 승인했다.
- `resolved_execution_plans` 외에도 Graph 68/69에 고정된 `assessment_item_occurrence_references` 1,040개, `knowledge_snapshot_analyses` 2,081개 등 snapshot 파생 행이 있다. 기출 정본 520개와 교과서 10개의 현행 Graph 67 사후 검증이 필요하다. 정확한 전용 children을 검증하지 않은 채 참조 행 수를 `삭제할 기출` 수로 읽지 않는다.
- 따라서 관계 삭제 연습 PASS를 전체 물리 삭제 PASS로 승격하지 않는다. Orchestrator 소유 Artifact의 공유 참조/경로/해시, workflow history 보존 범위, 백업 보존 정책을 별도 검증해야 한다. 실제 `eom-embedding-index-owner.service`가 active/running이므로 인덱스 head를 정리할 때는 소유 작업을 quiesce하고 정확한 고정 입력을 다시 확인해야 한다.

후속 전체 **관계/FK 연습**은 복원한 disposable DB에서 통과했다. Graph 68/69 고정 실행 계획 60개를 포함한 관계를 추적했고, 대상 Item workflow·지식 분석 workflow와의 합집합인 terminal workflow 170개를 정리했다. 대상 Item 110개·Revision 111개, 전용 Assembly와 Graph 68/69, 검색 request 66개 및 백업 시점 index revision 700개/source binding 4,354개를 정리한 뒤, 샘플 1개·기출 Graph source 520개·교과서 source 10개·외부 창작 source 1,297개·legacy Item 757개가 남았고, 트리거를 복구했다. 이 연습은 Artifact/Job 감사 행의 개별 소유 여부를 판정하거나 NAS 파일을 삭제하지 않았다.

2026-10-28 12:08 UTC 운영 재조회에서는 구 Graph index revision이 704개/source binding 4,370개로 증가했다. GPU index owner가 계속 실행 중이므로 백업·연습 수치를 운영 삭제의 고정 예상 수량으로 재사용할 수 없다. 구 Graph를 고정한 `local-embedding-index` workflow는 12:08 UTC에 `RUNNING` 5건, 후속 재조회에서는 새 요청이 시작돼 6건이었다. 일부는 오래된 실행이지만, 단순히 오래됐다고 실패/완료로 재해석하거나 DB 행을 직접 바꾸지 않는다. 관계 연습의 최초 사후 점검은 이 비종결 요청을 검사하지 않았기 때문에 전체 PASS가 아니다. 사후 검증에 이 가드를 추가하자 복제 DB에서도 `AI_ITEM_RESET_ACTIVE_INDEXING_PINNED_TO_OLD_GRAPH`로 정확히 차단됐다. 또한 보존 대상 Graph 67에는 index revision과 current head가 모두 0개다. 운영 Graph를 67로 전환할 때 공식 owner가 기존 520개 인코딩을 재사용해 대체 index를 준비할 수 있는지, 구 Graph의 비종결 작업을 공식 취소/종료할 수 있는지와 검색 가용성 전환을 먼저 검증해야 한다.

현재 운영 변경 상태: **삭제 미실행**. 테스트 스크립트에는 disposable DB 식별·소유자·marker를 확인하는 가드가 있으며 운영 DB 실행 경로가 없다. 운영 전환에는 소유 application의 계획·중단·재개 경계, 비종결 작업 정리, Graph 67 검색 인덱스 확보, 최신 백업·대조가 필요하다. NAS 감사 파일과 복구용 백업은 보존한다.

### 확인된 공식 경로의 공백

현재 API의 일반 `CANCEL_WORKFLOW`는 사람 관리자의 취소 명령을 저장할 수 있으나, 설치된 INDEX owner runner는 `local_indexing_service` actor의 native 명령만 claim한다. 일반 역할 runner는 native workflow를 claim하지 않는다. 따라서 이 6건을 단순히 API에서 취소 요청한 뒤 완료됐다고 간주할 수 없다. 기존 owner의 unstarted-only 취소 절차도 이미 `RUNNING`인 실행에는 적용되지 않는다. 비종결 INDEX 실행의 안전한 종료/정리 경계를 소유 runner에 추가하고, 실제 command·job·lease가 quiescent임을 확인해야 한다.

또한 INDEX reconciliation은 새 요청을 현재 게시된 Graph head에서만 선택한다. Graph 67은 게시돼 있지만 현재 head가 아니며 대체 index가 없다. 현행 owner가 Graph 67의 기존 encoding을 재사용할 수는 있어도, 활성화 전 비현행 Graph를 자동으로 prewarm하지는 않는다. 일시적 검색 중단을 허용하는 점검 창에서 head 전환 후 재인덱싱하거나, 명시적으로 승인된 prewarm 경로를 먼저 구현해야 한다. 어느 경우든 `0개 index`를 가용한 검색으로 보고해서는 안 된다.

후속 JSON pointer 감사에서는 구 Graph를 고정한 INDEX 이력 외에 native reference QUERY 9건(완료 8·비종결 1)도 확인됐다. 이들은 기출 정본이 아니라 구 Graph 파생 검색 실행이며, 명시적인 비현행 Graph pointer를 포함한다. disposable 연습에 이 native INDEX/QUERY 집합과 전용 producer metadata 정리 경로를 추가했다. 공유 FK·JSON pointer에서 보호 집합을 만들고 candidate producer의 의존 관계를 따라 보존 집합을 확장한다. NAS bytes에는 손대지 않는다. 입력/가드 unit test 8개는 통과했으나, 이 보강 경로의 전체 DB 회귀 결과는 아직 미확정이다. 운영 DB 경로는 계속 차단돼 있다.

## 운영 적용 요청 후 추가 프리플라이트

사용자는 전용 Artifact/Job metadata 정리와 짧은 점검 창을 승인한 뒤 운영 적용을 요청했다. 기존 disposable 전용 가드를 제거해 운영 명령으로 전용하지 않는다. 현재 도구는 소유 application 경계가 없는 관계/FK 연습 도구이며, 이것을 운영에서 그대로 실행하면 AGENTS의 component 소유권 원칙을 우회하게 된다.

복원한 DB에서 확장 연습은 Item 110개·Graph 68/69·과거 실행 902건까지 관계 정리를 수행한 뒤, 후보 Job 2,096개 중 공유 참조가 있는 1,197개를 보존 대상으로 분리했다. 전용 Artifact Revision 624개를 삭제하는 경로를 검사했다. 최초 실행은 승인 Artifact 불변 트리거에 차단돼 전체 롤백됐고, 정확한 두 트리거의 복구 검증을 disposable 도구에 추가했다. 후속 실행은 `artifacts` 삭제 단계가 1분 이상 진행돼 중단·전체 롤백했다. 운영에는 어떤 삭제도 적용하지 않았다.

원인은 실제 FK/index 대조로 확인했다. `knowledge_node_source_pointers.source_artifact_id`와 `knowledge_edge_source_pointers.source_artifact_id` FK에는 선행 인덱스가 없었다. 운영 시점 테이블 전체 크기는 각각 약 2,961MB·3,878MB였다. Artifact 삭제마다 이 테이블을 반복 검사할 수 있어, 현행 경로를 짧은 점검 창으로 승인해서는 안 된다. disposable DB에서만 해당 두 lookup 인덱스를 추가해 비교 검증한다. 운영 인덱스 변경은 정식 migration/release 경계를 사용해야 하며 이 테스트 index를 운영에 직접 복제하지 않는다.

남은 순서: (1) Catalog·Workflow·HWPX·Orchestrator 소유 관리자 정리 경계 구현, (2) FK lookup index 정식 migration과 호환성 검증, (3) 전용 metadata·공유 producer·quiescent native 실행을 포함한 rollback/replay 전체 검사, (4) 승인된 점검 창의 최신 백업·실행 정지·적용·Graph 검색 재구성. 현재 운영 상태는 여전히 **삭제 미실행**이다.

후속 복제 DB 검사에서 두 FK lookup 인덱스를 보강한 후 `disposable_full_relational_exercise=PASS` 및 별도 `disposable_postconditions=PASS`를 확인했다. 삭제 결과는 Item 110개/Revision 111개, 관련 실행 902개, 전용 Artifact/Revision 각 624개, 전용 Job 899개 및 Job event 7,073개다. 후보 Job 2,096개 가운데 공유 참조가 있는 1,197개는 보존했다. 기출 Graph source 520개·교과서 source 10개·외부 창작 source 1,297개·legacy Item 757개·보존 샘플 1개와 불변 트리거 복구를 확인했다. 운영 INDEX/QUERY 서비스는 여전히 active이며 변경하지 않았다. 이 PASS는 복제 DB의 정리 순서/선별 검증이며 운영 실행 경계를 승인하거나 설치한 증거가 아니다.

## 소유 application 구현 후보

기존 disposable 전용 SQL 도구는 검증 뒤 제거하고 소유 adapter로 통합했다. `eom_orchestrator.prelaunch_item_reset_service`는 Catalog/Workflow/HWPX 구현을 import하지 않고 typed application port를 조합한다. 각 소유 module의 `prelaunch_item_cleanup`과 Orchestrator의 `prelaunch_artifact_cleanup`만 자기 component의 행을 정리한다. 분석 run/lease/Artifact는 Orchestrator가 소유한다. API upload intent는 존재 시 거부하며 다른 component가 삭제하지 않는다.

`eomctl prelaunch-reset plan/apply`가 설치 wheel에서만 실제 host/DB owner를 확인해 실행한다. 원래 SQL 연습 스크립트를 운영용으로 전용하지 않았다. JSON Schema 2020-12와 frozen plan/receipt, 정본 계획/영수증의 Orchestrator NAS commit, plan hash·fingerprint·동시성·interruption/replay guard를 구현했다. 설치/운영 절차는 `docs/operations/PRELAUNCH_ITEM_RESET_RUNBOOK.md`다.

Application 경계를 사용한 disposable snapshot 통합 검사 6개가 73.04초에 PASS했다. 별도 source/contract/owner 및 Identity recovery 회귀 54개도 PASS했다. 이 문단 시점에는 운영 실행은 아직 전이다. PostgreSQL head와 API/Web/INDEX/QUERY runtime pin은 변경하지 않는다. 성능 인덱스는 영구 migration 대신 transaction 내부 보조 인덱스로 결정했다.
