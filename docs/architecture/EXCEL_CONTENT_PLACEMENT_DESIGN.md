# Excel: 콘텐츠 편성·문항 배치·사용 이력 설계

상태: **DESIGN_REVIEWED — 초안 작성, 원본 재독 2회, 설계 검토·보완 2회 완료**.
작성 기준: 2026-11-09 UTC. 저장소 기준: `844a8eec40be1eda9771fb8fe00854007ea660e1`.
사용자 화면 위치·임시 이름: **데이터 → Excel**.

읽는 순서: §1–5는 사용자 동작과 큰 구조, §15–18은 구현 계약/정본/동시성,
§19는 구현 순서와 검증, §14·17은 두 차례 실제 재독에 따른 설계 변경 기록이다.
부록 A는 최초 제안 보존용이며 본문의 최신 결정과 구별한다.

이 문서는 구현을 위한 설계다. 기능 구현·운영 배포·DB 변경·원본 Excel 가져오기·
Graph/임베딩 재실행을 수행하거나 승인한 기록이 아니다. 기존 코드 존재와 운영 활성화는
구별한다. 이번 작업의 완료 범위는 초안 → 원본 재독 → 검토·보완 → 원본 재독 → 검토·보완이다.

## 1. 사용자와 확정한 의미

| ID | 확정 요구 |
| --- | --- |
| U01 | 콘텐츠 이름과 구성은 사용자가 추가한다. 학교별 맞춤 시험지를 만들고 20회차를 배치할 수 있어야 한다. 고정 상품 목록은 없다. |
| U02 | 대부분 같은 콘텐츠의 연도별 판을 관리한다. 새로운 이름·구성의 콘텐츠를 자유롭게 추가할 수 있어야 한다. |
| U03 | 올해 통합과학은 작년 배치가 없으므로, 기존 DB 문항의 이름으로 찾아 배치할 수 있어야 한다. 과거 사용 이력 입력은 시작 조건이 아니다. |
| U04 | 저장된 배치부터 사용 현황에 포함한다. 인쇄 전까지 계속 수정하고, 인쇄에 들어간 구성을 별도로 체크해 보존한다. |
| U05 | 중복 사용은 차단하지 않는다. 현재 콘텐츠·다른 콘텐츠·다른 연도의 사용 위치를 확실히 표시한다. |
| U06 | 기존 조립의 제한이 새 요구를 가로막으면 해제·확장한다. 기존 구현은 최대한 재사용하되 그 한계를 제품 요구로 강요하지 않는다. |
| U07 | `26_미사용`은 기존 문항 중 26년에 쓰지 않았던 문항이다. 영구 분류가 아니라 연도 범위의 사용 여부다. |
| U08 | 구현 전에 이 문서를 만들고 같은 Excel을 두 번 다시 읽어 설계를 보완한다. 각 검토에서 EOM 전체 설계 원칙도 확인한다. |

먼저 제안했던 설명은 [부록 A](#부록-a-이전-대화의-설계-제안-보존)에 보존한다.
사용자 답변 이후에는 위 U01–U08과 본문의 최종 결정이 우선한다.

## 2. 제품의 최소 모델

```text
콘텐츠: 사용자가 정한 교재·시험지 묶음
  └─ 판: 2027 / 2028 / 연도 없는 별도 판
       └─ 구간: 회차, 단원, 주차·일차 등 사용자가 정한 순서
            └─ 배치: 번호가 있는 자리 + 정확한 문항 참조

현재 저장본 ── 수정 ── 다음 저장본
     └─ 인쇄 체크 ── 그때의 정확한 구성 기록 (후속 수정과 분리)

문항 DB ↔ 사용 위치 조회
```

`콘텐츠`, `판`, `구간`, `배치`는 별개 책임이다. 원본 문항의 단원·출처와 교재의 편집상 구간을
섞지 않는다. 학교 이름은 콘텐츠/구간 표시명으로 충분하며 학생별 자료나 수강생 DB를 만들지 않는다.
화면 이름 Excel은 스프레드시트 엔진·수식 실행·Microsoft 계정 연동을 뜻하지 않는다.

### 2.1 초판부터 시작

사용자가 이름을 정해 콘텐츠를 만들고 판을 추가한다. 기존 콘텐츠를 선택할 필요는 없다.
`회차 20개 만들기`는 1–20회의 빈 구간을 만드는 단일 명령이다. 문항 수는 회차별로 정한다.
단일 시험지는 기본 구간 하나로 시작하며 불필요한 폴더 입력을 요구하지 않는다.
콘텐츠 종류는 기존 `MOCK_EXAM/TEXTBOOK/WEEKLY/OTHER`를 표현용으로 재사용하고 배치를 제한하지 않는다.

### 2.2 가져오기와 수정

DB 문항 이름·고유번호·기존 필터로 검색 → 선택 → 대상 구간에 삽입한다.
이전 콘텐츠/판의 전체, 선택 구간, 선택 자리만 복사할 수 있다. 새 판·구간·자리 identity는
새로 만들되 정확한 문항 revision과 원본 포인터는 재사용한다. 복사 출처 revision을 기록한다.
문항/이미지/풀이보고서/벡터를 복제·재생성하지 않는다. 번호·구간·배점 변경은 문항 내용 변경이 아니다.

### 2.3 이력의 두 종류

- 사용 이력: 현재 저장된 위치, 인쇄된 위치, 과거 연도의 위치. 문항 상세와 콘텐츠에서 같은 정본을 조회한다.
- 편집 이력: 누가 어느 저장본에서 삽입·삭제·교체·이동·복사를 했는지. 기본 화면에서는 접어 둔다.
- 배치 제거는 문항 DB 삭제가 아니다. 이미 인쇄된 기록과 과거 저장본도 삭제하지 않는다.
- HWPX 빌드/다운로드는 인쇄 체크가 아니다. 출력 실패가 배치 저장을 취소하지도 않는다.

## 3. 기존 EOM과의 결합: 구현 사실과 확장 구분

| 경계 | 확인한 현재 코드/계약 | 이번 확장 |
| --- | --- | --- |
| 콘텐츠 | `DeliverableRecord`, `DeliverableRevisionRecord`, `UsageLedgerService` | 논리 콘텐츠 identity 재사용, 독립적인 판 head와 typed 구성 detail 추가 |
| 회차 | `AssessmentFormRecord`, `AssessmentFormRevisionRecord` | 구간의 실제 문항 목록을 기존 Form에 연결. 판·구간 소속을 명시 |
| 혼합 조립 | `CuratedDocumentAssemblyService`, draft V1/V2, manifest V1 | 같은 담당 서비스에 빈 자리·반복 사용·큰 목록·저장 revision 경로 추가 |
| 기존 사용 이력 | `usage_plans`, `usage_records`, `usage_records_v1`, `LegacyUsageService` | 과거 의미 유지. 새 배치 현황과 인쇄 체크를 연결하되 거짓 RELEASED/fulfill 금지 |
| HWPX | `curated_application_service`, `curated_mixed_renderer`, native merger | 새 조립 계약을 받아 기존 출력·복구·다운로드를 재사용 |
| 검색/미리보기 | DB 조회·Graph 후보·원본/등록 문항 상세 | 기존 권한·정본 해석을 재사용. Excel 전용 검색 엔진 없음 |
| GUI | DB 조립·배치 표·미리보기·자료 선택 | 데이터 → Excel 작업 공간. DB의 임시 조립은 유지하고 공식 가져오기 명령으로 연결 |

관련 초기 설계: [Product/Form/Assembly/Usage](PRODUCT_FORM_ASSEMBLY_USAGE_V1_DESIGN.md),
[Usage Ledger V0](USAGE_LEDGER_V0.md), [ADR 0039](../adr/0039-product-form-assembly-publication-and-usage.md).
초기 설계 문서의 ‘미구현’ 문구만 믿지 않고 실제 `legacy_usage_models.py`와 서비스도 확인했다.

### 3.1 반드시 해제할 기존 한계

1. 현재 curated draft/manifest/DB row가 `1..200`을 제한한다. 새 편성 경로에서는 이 제품 제한을 제거한다.
2. 같은 source/Item revision의 반복을 거부한다. 새 경로의 유일성은 **자리 identity**이며 문항 중복은 경고다.
3. 현재 조립의 소유자 단독 조회는 여러 조교의 같은 콘텐츠 편집을 대체하지 못한다. 공식 콘텐츠 권한을 추가한다.
4. V0 UsagePlan은 등록 Item을 요구하고 실제 사용 기록은 fulfill 의미다. 원본만 있는 문항의 배치를 막거나
   저장만으로 실제 출판했다고 위장하지 않는다.
5. 현행 Form/Publication V1과 mixed curated assembly는 다른 계약이다. 이름이 비슷하다고 FK를 바꿔 끼우지 않는다.

구버전 저장본과 이미 만든 HWPX는 계속 읽는다. 새 GUI는 확장 계약을 기본으로 쓰며, 구버전 제한에 맞추려고
사용자에게 문항을 쪼개거나 중복 문항을 삭제하도록 요구하지 않는다. 보안상 byte/time/메모리 한도는
제품 문항 수 제한과 구별하고 작은 메타데이터 pagination·파일 streaming으로 다룬다.

## 4. 편성·저장·인쇄의 상태와 규칙

### 4.1 저장

브라우저의 미저장 편집은 사용 현황에 포함하지 않는다. 저장은 새 조립 revision과 현재 구간 head를
원자적으로 확정한다. 응답에 저장본 pointer/ETag, 변경 요약, 중복 경고를 같이 돌려준다.
같은 내용의 재전송은 같은 결과를 반환하고 저장본·이력을 중복 생성하지 않는다.

빈 자리와 목표 문항 수를 허용한다. ‘20회차 만들기’가 각 회차의 20문항 완성을 뜻하지 않는다.
빈 자리는 문항 사용 횟수에서 제외하며, 배치 중인 구간을 승인·Graph·임베딩 완료까지 기다리게 하지 않는다.
문항 읽기 가능 여부와 출력 가능한 원본/문항 계약은 구별해 행에 상태를 표시한다.

### 4.2 인쇄 체크

사용자가 판 전체 또는 선택 구간의 **정확한 저장본**에 인쇄 체크한다. 파일 제작·실물 인쇄를 시스템이
자동으로 증명한 것은 아니므로 `USER_RECORDED` 출처, 작업자, 기록시각, 인쇄 관련 메모를 남긴다.
완료 HWPX가 있으면 exact build/output pointer를 선택적으로 연결한다. 없다고 가짜 Artifact를 만들지 않는다.
출력파일이 다른 revision에서 만들어졌다면 동일 인쇄본으로 연결하지 않는다.

인쇄 체크 뒤의 수정은 새 저장본이다. 기존 인쇄본은 그대로 보며 `현재 배치가 인쇄본과 다름`을 표시한다.
잘못 체크한 경우 공식 취소/정정 이벤트로 남긴다. 이미 인쇄된 사실과 단순 오입력 취소를 구분한다.
과거 인쇄본을 실제 인쇄한 날짜를 알고 기록하면 사용자 입력 날짜와 서버 기록 UTC 시각을 별도로 둔다.

### 4.3 사용·미사용·중복

기본 연도별 사용 현황은 현재 저장된 배치와 유효 인쇄 기록을 합쳐 보여주되 같은 자리/저장본을 중복 세지 않는다.
과거 저장했지만 지금 제거한 미인쇄 문항은 편집 이력에는 남고 현재 배치에서는 빠진다.
기본 `올해 사용`은 **올해 판의 현재 저장 배치 OR 유효 인쇄 기록**이다. 단 한 번 저장했다가
뺀 문항까지 영원히 사용 중으로 남기지 않는다. `과거에 배치했다가 뺀 것 포함`은 별도 이력 필터다.
사용 년도는 인쇄일의 달력 연도가 아니라 사용자가 판에 지정한 학년도다. 연도 없는 판은 `연도 없음`에
따로 집계한다. 기존 DB 이름의 `26_`/`27_`에서 연도를 추정하거나 이름을 고치지 않는다.

원래 문항 모집단에서 해당 사용 집합을 indexed anti-join하면 연도별 미사용 조회가 된다.
다만 옛 사용 이력을 아직 입력하지 않았다면 ‘이 시스템에 사용 기록 없음’으로 표현하고,
외부에서 실제로 쓰지 않았다는 증명으로 확대하지 않는다. 이력 수입의 완전성 정보가 있을 때만
과거 연도의 확정 미사용 상태를 주장한다.

중복은 `같은 구간 / 같은 판의 다른 구간 / 같은 연도 다른 콘텐츠 / 다른 연도`로 나눠 표시한다.
색상만 쓰지 않고 횟수·대상 이름·번호와 이동 링크를 제공한다. 같은 문항의 다른 revision은 같은 논리 문항의
사용으로 묶고, 실제 사용 revision은 펼쳐서 본다. 유사 문항이라는 이유만으로 동일 문항 취급하지 않는다.
원본→등록 Item의 확인된 lineage만 동일성에 사용하며 이름·5자리 번호만으로 합치지 않는다.

## 5. 사용자 화면

```text
데이터
  DB / Excel / 자료 학습 / 운영 데이터 조회 / Map

Excel: [콘텐츠 선택] [판/연도 선택] [새 콘텐츠] [판 복사]
┌────────────────┬──────────────────────────────────┐
│ 회차·구간 목록  │ 구간 제목 / 저장 상태 / 인쇄 상태 │
│ + 구간 추가    │ 번호 │ 문항 이름·고유번호 │ 작업  │
│ + 20회차 생성  │  1   │ 선택한 문항       │ 교체… │
│                │  2   │ 빈 자리           │ 추가  │
└────────────────┴──────────────────────────────────┘
선택 문항 미리보기·사용 이력 / [저장] [HWPX] [인쇄 체크]
```

- 표 중심, 기존 입력창·버튼·여백·색상 토큰 사용. 기술 ID/hash/batch는 기본 숨김.
- 콘텐츠/판/구간 선택이 URL 상태로 복원되며 새로고침에 서버 저장본은 사라지지 않는다.
- 문항 이름은 기존 DB 이름을 우선 표시한다. 과거 연도명을 억지로 새 이름으로 바꾸지 않는다.
- DB에서 여러 문항 선택 → Excel의 대상 판/구간/삽입 위치 선택. 이름·고유번호 찾기와 기존 필터 재사용.
- 기존 DB 배치의 ‘Excel에 가져오기’는 같은 pinned selection을 복사한다. 제목만 바꿔 같은 객체로 오인하지 않는다.
- 변경 전 화면/미리보기에 늦게 온 이전 응답을 적용하지 않는다. 읽기 실패 때 기존 데이터·미저장 편집을 삭제하지 않는다.
- 중복 경고는 항상 확인 가능하되 저장을 막는 확인창을 매번 띄우지 않는다. 자세한 위치는 클릭해서 본다.
- 기술 설명은 안내 모드/상세에 둔다. 기본 화면은 ‘저장됨’, ‘인쇄 기록 있음’, ‘수정됨’ 같은 쉬운 표현을 쓴다.

## 6. 정본과 데이터 구조

아래 이름/계약 version은 **구현 후보**다. 아직 schema·migration·endpoint는 추가하지 않았다.

### 6.1 콘텐츠·판·구간

- 콘텐츠: 기존 `deliverables`의 논리 identity. 자유 제목, 기존 유형, 활성/보관 상태.
- 판: 새 `content_editions`의 안정된 identity. `deliverable_id`, 내부 edition key,
  `current_deliverable_revision_id`, `lock_version`. 표시명과 nullable `academic_year`는 exact 구성 revision의
  metadata다. 같은 연도 복수 판을 허용한다.
- 구성 저장본: 기존 `deliverable_revisions`에 versioned typed metadata를 연결한다. 구판 JSON을 재해석하지 않는다.
  작은 구간 트리와 정확한 Form revision pointer만 포함하고 문항 전체를 넣지 않는다.
- 구간: bounded adjacency tree. 폴더는 자식 구간만, 실제 문항 구간은 Form을 가진다. 한 구간이 동시에 둘을 갖지 않는다.
  안정된 `section_id`, `parent_id`, `ordinal`, `label`, leaf의 Form pointer를 사용한다.
- Form: 기존 논리 회차를 재사용하되 판마다 새 Form identity를 부여한다. 다른 판의 Form을 직접 이동시키지 않는다.
  새 Form composition detail은 curated assembly revision을 명시한다. legacy assessment assembly FK를 오용하지 않는다.

최초 규모 가정은 수천 콘텐츠/판, 수만 구간, 수십만 현재 배치와 더 많은 역사 배치다. 측정 전 달성 성능으로
표시하지 않는다. 구간 구조는 작은 immutable value tree, 문항 순서는 indexed rows/tuple이다.

### 6.2 자리와 문항 참조

자리의 `placement_id`는 UI 행 번호와 다르다. 순서 변경 시 identity를 유지하고 표시 번호는 다시 계산한다.
`position`, optional `display_number`, optional `points_milli`, small `note`, exact typed target을 둔다.
target은 `EMPTY` / `EXTERNAL_SOURCE_DOCUMENT` / `REGISTERED_ITEM_REVISION` / `PAST_EXAM_ITEM_REVISION`이다.
같은 문항을 두 번 넣으면 서로 다른 placement ID가 생긴다. 구간 이동·교체의 before/after 포인터를 남긴다.
원본 문항명/고유번호는 조회 시 공식 DB metadata에서 읽고, 과거 출력 재현에 필요한 표시명만 저장본의 작은 값으로 pin한다.

기존 curated aggregate와 resolver/저장 application을 확장한다. 새 indexed placement row 형식은 반복 문항과
빈 자리, 구간 정보, 안정된 placement ID를 수용한다. 구 V1/V2 bytes와 row는 유지하며 같은 owner가 version dispatch한다.
1차 검토 결정: 새 manifest에는 `curated_document_assembly_slots_v2`라는 **같은 aggregate의
versioned row 저장 형식**을 둔다. 현재 table의 source/Item별 unique index와 200 제한을 새 경로에
적용하지 않는다. legacy row와 새 row를 동시에 정본으로 쓰지 않는다. 부모 revision에 explicit
manifest schema discriminator를 추가하고 version별 단일 row family를 검증한다. 새 row에는
`(assembly_revision_id, placement_id)` PK, `(assembly_revision_id, position)` unique만 적용한다.
동일 문항이 반복되어도 저장된다. 기존 resolver의 typed target/permission/hash 검사를 재사용한다.

UI의 `item-db-draft.js`도 문항 pointer key로 유일성을 강제하고 교체 대상을 찾고 있으므로,
새 기본 편집기는 `placement_id -> entry` map과 ordered ID array를 쓴다. 삭제/교체 대상은 문항이 아니라
자리다. 중복 경고를 위한 `target identity -> set(placement_id)`는 별도 파생 map이며 삽입을 거부하지 않는다.
DB의 기존 임시 배치 UI도 최종적으로 이 편집기/새 계약을 사용한다. legacy 기록은 read adapter로 읽는다.

### 6.3 인쇄와 읽기 projection

인쇄 기록은 `print_record_id`, exact edition revision, 선택한 Form/assembly revisions, 선택 output pointer,
기록자·시간·메모, 취소/정정 연결을 소유한다. 실제 기계 인쇄 성공으로 표시하지 않는다.
사용 이력은 indexed placement + 현재 head + 인쇄 참조에서 조회한다. 사용처 문자열을 문항 메타데이터마다 복사하지 않는다.
Graph는 공식 Catalog 이력의 파생 관계이며 ordering·사용 사실의 두 번째 정본이 아니다. 기존 검색 Graph/RAG는 유지한다.

## 7. Application 계약과 API

모든 상태 변경은 actual actor + permission + `Idempotency-Key` + canonical request hash를 검사한다.
기존 객체 변경은 exact expected revision/ETag를 받는다. 모델/브라우저가 보낸 권한은 사용하지 않는다.

| 유스케이스 | 주요 입력 | 결과 |
| --- | --- | --- |
| CreateContent | 제목, 유형 | 콘텐츠 identity, 초기 표시 정보 |
| CreateEdition | 콘텐츠, 표시명, 선택 연도 | 빈 판, revision, ETag |
| SaveStructure | 판 ETag, ordered section tree | 새 구조 revision, 충돌 또는 결과 |
| CreateSections | 판 ETag, 이름 패턴, 개수 | 원자적 여러 빈 회차 생성 |
| SavePlacement | 판/구간 ETag, ordered slots | 새 조립/Form/판 refs, 사용 현황, 경고 |
| CopyPlacement | exact source revision, 대상 ETag, 전체/선택 범위 | 독립 자리들, 출처 연결, 새 저장본 |
| ReadUsage / ReadDuplicates | typed item/source refs, 연도/콘텐츠 범위, cursor | 현재·인쇄·과거 사용 위치 |
| RecordPrint | exact saved scope, 선택 output refs, 인쇄일/메모 | 불변 인쇄 기록 |
| CorrectPrint | 원기록, 오입력/정정 사유, 권한 | 보상 이벤트, 기존 이력 보존 |
| BuildOutput | exact saved section scope | 기존 HWPX build identity와 상태 |

후보 public path는 `/api/v1/content-planning/...`, BFF는 기존 `/studio/api/v1/...` 대응이다.
UI route는 `excel`; namespace·Python 모듈은 임시 상품명보다 `content_planning` 책임명으로 한다.
목록·읽기 GET은 출력/검색/Graph 실행을 시작하지 않는다. 페이지 조회 중 재계산·재렌더 금지.
오류는 `STALE_REVISION`, `TARGET_UNAVAILABLE`, `PERMISSION_DENIED`, `PRINT_SCOPE_MISMATCH`,
`IDEMPOTENCY_CONFLICT`, `OUTPUT_NOT_SUPPORTED` 등 안정된 code와 한국어 행동 안내를 분리한다.

## 8. 동시성·인덱스·실패 처리

- 저장의 원자 경계: 입력 검증 → 판 head 잠금/ETag 비교 → 새 assembly/Form/구성 revision → 이벤트 → head 전진.
  권한·membership·pointer는 batched 조회한다. NAS bytes 검증은 명시적 입력/출력 경계에서만 수행한다.
- 두 사람이 같은 판을 수정하면 CAS 충돌을 보여주고 자동 덮어쓰기하지 않는다. 다른 판은 서로 잠그지 않는다.
- 복사/인쇄도 exact source와 대상 head를 검사한다. 문항별 transaction으로 절반 저장하지 않는다.
- renderer/HTTP/모델 실행을 DB transaction 안에서 기다리지 않는다. 배치·인쇄 metadata에는 새 worker/queue가 필요 없다.
- key 조회: B-tree. 연도/콘텐츠 역조회: edition-year-product index. 순서: `(revision_id, position)` unique.
  중복 대상은 unique 금지 대신 item/source logical key index. 사건은 aggregate별 append-only sequence.
- 현재 사용·인쇄 사용은 각각 indexed join 후 union/dedup한다. 전체 문항/모든 역사 JSON을 매번 scan하지 않는다.
- 읽기는 `O(log N + K)` 목표, 저장은 바뀐 구간의 `O(P)` 포인터 검증/행 생성. 작은 판 manifest 변경은 구간 수 `O(S)`.
  이미 저장한 다른 구간의 문항을 다시 parse/hash하지 않는다.
- 숨긴/보관한 콘텐츠도 인쇄 이력이 사라지지 않는다. 기본 목록 제외와 미사용 판정 제외는 같은 명령이 아니다.

## 9. 소유 모듈과 구현 순서

1. `catalog_contracts` JSON Schema 2020-12 → frozen Pydantic: edition/structure, expanded composition,
   print record, usage projection와 command/query. 같은 enum·rule을 API와 GUI에 각각 새로 만들지 않는다.
2. Catalog: 기존 deliverable/Form/curated 소유 아래 새 편성 use case, transaction, bounded repositories.
   CLI/API는 command 생성·검증·응답만 담당한다. private SQL/다른 서비스 테이블 우회 금지.
3. persistence: additive migration과 index·FK·immutability/concurrency 검증. 실제 migration 번호는 구현 시 정한다.
4. read/API/BFF: 공식 actor context로 콘텐츠 목록·배치·양방향 이력 조회, 중복 경고.
5. GUI: 데이터 → Excel, 신규 콘텐츠·20회차·DB 문항 선택·편집·복사·저장·이력.
6. HWPX: 확장 placement를 기존 materializer/renderer/merge에 연결. 인쇄 체크는 별도 액션.
7. 운영 rollout: Catalog/API/Web/HWPX의 지원 계약을 맞춘 뒤 노출. 구 GUI·구 조립 read/download 회귀.

이 순서는 후속 **구현 제안**이다. 이번 설계 목표에서 실행하지 않는다.

## 10. 구현 검증·인수 기준

- 신규 ‘학교별 맞춤 시험지’ → 20회차 → DB 이름으로 문항 추가 → 저장 → 새로고침/다른 사용자 조회.
- 300문항/1,200문항 콘텐츠, 반복 문항, 빈 회차를 저장. 200개 제한이나 고정 20/25문항으로 거부하지 않음.
- 작년 판 복사 후 올해만 수정. 작년 배치/인쇄본/문항 revision unchanged, 파일/보고서/벡터 생성 0.
- source-only/등록/기출/AI 문항을 공식 권한으로 선택, 원본과 등록 표현의 중복은 확인된 lineage로 표시.
- 같은 판·다른 콘텐츠·다른 연도의 중복 사용을 명확히 표시하지만 허용.
- 인쇄한 1회차를 보존한 채 2회차 수정, 전체/일부 인쇄, 인쇄 뒤 교체, 기록 정정.
- 같은 요청 replay/HTTP timeout/동시 저장/중간 실패를 disposable PostgreSQL에서 검증.
- 누락·다른 owner·stale·hash mismatch·권한 취소를 fail-closed. 현재 revision으로 몰래 대체하지 않음.
- 과거 저장본 조회와 HWPX 다운로드가 새 build를 만들지 않음. 혼합 입력의 순서·그림·수식·출제의도 회귀.
- DB/BFF/schema/wheel/route/DOM alignment와 실제 browser 편집·복원·미리보기·이력 이동.
- 권한 없는 문항/다른 콘텐츠 이름을 중복 경고에서 누설하지 않음. 생성/권한변경/배치편집 권한 분리.
- synthetic 수십만 placement로 query plan/batching·N+1 검사. 성능 목표치는 측정과 함께 확정.

## 11. EOM 원칙 점검표

| 원칙 | 이번 설계에서 확인할 것 |
| --- | --- |
| OOP/책임 분리 | 콘텐츠 편성, 문항 정본, 출력, Graph를 각각 기존 owner에 둔다. god service 금지 |
| 캡슐화 | API/GUI가 Catalog SQL/private module을 직접 호출하지 않는다 |
| 재사용/단순성 | 기존 Product/Form/curated/renderer를 확장. 별도 Excel DB·수식 엔진·workflow 플랫폼 없음 |
| 포인터 중심 | 문항·파일·풀이·벡터를 복사하지 않고 exact revision 참조 |
| 이력 불변성 | 과거 출력·인쇄 구성을 최신 문항으로 바꾸지 않는다 |
| 접근 패턴 | indexed reverse usage, batched selection, ordered placements, bounded page |
| 동시성 | CAS, atomic save, unique idempotency; 중복 문항과 중복 실행을 혼동하지 않는다 |
| Graph 연계 | 기존 Graph/RAG lookup 재사용, 편성 fact의 owner는 Catalog |
| 권한 | actual actor, 공유 정책, 제한된 중복 경고, secret-safe evidence |
| GUI 원칙 | 표 중심·일관된 토큰·기술 ID 숨김·쉬운 말·설명은 안내 모드 |
| 운영 안정성 | 기존 GPU/slot과 데이터 정본을 건드리지 않는 additive rollout |
| 검증 | 변경 경계에 맞는 source/DB/browser/출력 gate, source PASS와 live PASS 구별 |

## 12. 요청한 설계 절차와 기록

| 단계 | 상태 | 기록 |
| --- | --- | --- |
| 1. 초안 작성 | COMPLETE | 사용자 확정 요구와 현재 source/초기 설계 대조 후 본문 작성 |
| 2. 원본 Excel 재독 | COMPLETE | 2026-11-09 08:49 UTC, ZIP/worksheet를 다시 열어 구조·사용 연결 재계산 |
| 3. 1차 설계 검토·보완 | COMPLETE | §14–16 및 사용 의미·새 자리 저장 형식에 반영 |
| 4. 원본 Excel 재독 | COMPLETE | 2026-11-09 08:54 UTC, 원본을 다시 열어 이동·맞교환·누락·연도별 식별 대조 |
| 5. 2차 설계 검토·보완 | COMPLETE | §17–21. 편집 원자성·부분 인쇄·권한·전체 출력/배포까지 최종 보완 |

## 13. 코드 근거

- [Catalog Product/Usage models](../../services/catalog_service/eom_catalog_service/models.py)
- [Usage service](../../services/catalog_service/eom_catalog_service/usage_service.py)
- [Form/Publication persistence](../../services/catalog_service/eom_catalog_service/legacy_usage_models.py)
- [Legacy usage contracts](../../packages/catalog_contracts/eom_catalog_contracts/legacy_usage.py)
- [Curated draft](../../packages/catalog_contracts/eom_catalog_contracts/curated_document_assembly_draft.py)
- [Curated manifest](../../packages/catalog_contracts/eom_catalog_contracts/curated_document_assembly.py)
- [Curated persistence](../../services/catalog_service/eom_catalog_service/curated_document_assembly_models.py)
- [Curated service](../../services/catalog_service/eom_catalog_service/curated_document_assembly_service.py)
- [DB assembly UI](../../apps/web_gui/eom_web_gui/static/item-db-assembly.js)
- [DB delivery UI](../../apps/web_gui/eom_web_gui/static/item-db-delivery.js)
- [개발 문맥](../agent-context/README.md)

## 14. 1차 재독·설계 검토 기록

원본: staging의 `2026년_문항관리_공유_OneDrive.xlsx`(실제 파일명은 Unicode NFD).
SHA-256: `88ae6c7564294ca518c59c3c6d0f9bbd73703b122d54f169adc46c1d6d7d2e50`.
14개 worksheet를 새로 읽었다. ZIP 내부 OOXML의 값·수식·병합 정보를 확인했으며 Excel 엔진이나
매크로를 실행하지 않았다. cached formula 값과 수식 의미를 구분한다. 아래는 업무 구조의 증거이지
해당 지구과학 문항을 통합과학 DB로 자동 이관하라는 뜻이 아니다.

| R1 | 원본에서 다시 확인한 점 | 초안 검토·보완 |
| --- | --- | --- |
| 01 | `27_모의 정보!A4/P4`, `A5/P5`: 내부 순서와 실제 콘텐츠 회차명이 다름 | 제목/번호를 identity로 사용하지 않음. 순서와 표시 이름 독립 |
| 02 | `27_모의 배치`: 56묶음·1,120자리, 같은 인덱스 71795가 두 위치에 있음 | 자리 identity와 문항 identity 분리, 중복 허용·위치 표시 |
| 03 | `27_엄메!A2:A301`: 300문항, J/K 병합이 주제/부를 표현 | 200 제한 제거, 계층 구간과 연속 번호 지원 |
| 04 | `27_E기적`: 10주×6일×20=1,200자리, 별도 테스트 영역도 존재 | 하나의 판에 여러 유형의 구간 공존, 전체/부분 범위 선택 |
| 05 | `26_미사용!A786/G786/H786`: 이전 미사용 문항이 새 사용처에 연결 | 미사용은 연도 범위의 조회, 이름·분류의 영구 속성이 아님 |
| 06 | `27_모의 정보!S2=F2`, `O2=(G2+H2)/20` | 완성도/신규율이라는 이름을 승인/인쇄 상태로 가져오지 않음 |
| 07 | 기존 코드의 GUI·Catalog·DB·HWPX가 모두 수량/유일성을 제한 | UI만 변경하는 해제는 불충분. §16에 전 경계 변경 목록 |
| 08 | `UsageRecord`는 실제 사용, Publication V1은 출력과 연결 | 새 저장 현황·사용자 인쇄 체크를 기존 실제 출판 성공으로 위장하지 않음 |

EOM 원칙 1차 판정: 기존 Catalog/조립/HWPX를 재사용하는 방향 유지. 별도 Excel 검색/파일저장/
문항 등록 프레임워크는 불필요하다. 구간 전체를 하나의 giant JSON 문항 배열로 저장하거나, 출력할 때마다
문항을 신규 등록하는 대안은 배제했다. 출력용 자료를 단순 복제하는 대신 정확한 조립 참조를 연결한다.

## 15. 저장 모델·읽기·권한 계약 (1차 보완)

### 15.1 논리 identity와 버전의 소유

| 객체 | 핵심 필드/저장 | 정본·가변성 |
| --- | --- | --- |
| Content | 기존 `deliverable_id`, title, type, lifecycle | 논리 상품. 과거 title은 당시 판 metadata가 보존 |
| Edition | `edition_id`, deliverable FK, edition_key, current revision FK, lock_version, lifecycle | 판별 독립 head. 같은 콘텐츠·연도에 여러 판 가능 |
| EditionComposition | 기존 `deliverable_revision_id`, schema `content-edition-composition/1.0`, edition ID, label/academic_year 등 표시 metadata, ordered SectionValue tuple, hash | 불변. 작은 구조/포인터만 포함 |
| SectionValue | section_id, parent_id?, kind GROUP/FORM, ordinal, label, numbering policy, form revision pointer? | 별도 lifecycle 없는 구조 값. 부모/형제/순환/FORM 자식 금지 검증 |
| Form | 기존 Form ID + 새 edition membership | 판의 실제 문항 구간. 이름/순번 변경으로 identity가 바뀌지 않음 |
| FormComposition | 기존 Form revision + `content_form_revision_compositions` detail: edition_id, section_id, curated assembly revision/hash | 기존 assessment assembly FK와 구별. V1 reader에 새 의미를 주입하지 않음 |
| Assembly | 기존 curated logical/revision identity, 새 draft/manifest profile, slots V2 | 구간의 배치 정본. 불변 revision과 단일 current head |
| PrintRecord | print ID, exact edition revision/hash, typed form scope, output refs?, origin=USER_RECORDED, printed_on?, recorded_at/by, note | 불변 사용자 사실 기록. actual render/physical printer 성공과 다름 |
| PrintEvent | event ID, print ID, sequence, kind VOID_RECORD/CORRECT_RECORD, reason, actor/time, replacement print ID? | 오입력 정정 이력. 실물 회수/배포 기능은 이번 범위 아님 |
| EditEvent | edition ID, sequence, command kind, before/after revision refs, affected placement IDs, actor/time | 작은 append-only 변경 기록; 전체 문항/파일/거대한 diff 없음 |

추가 저장은 기존 Catalog DB 안에서 이루어진다. 후보 테이블은 `content_editions`,
`content_edition_revision_forms`, `content_form_memberships`, `content_form_revision_compositions`, `curated_document_assembly_slots_v2`,
`content_print_records`, `content_print_scopes`, `content_print_events`, `content_planning_events`,
`content_planning_command_receipts`다. 새 Product/Item/Artifact registry를 만들지 않는다.
`content_print_scopes`는 인쇄 record의 exact Form/assembly 포인터를 indexed row로 표현하는 것이며
문항별 사용 record를 한 번 더 복제하지 않는다.

`content_edition_revision_forms`는 EditionComposition의 leaf 참조를 정규화한 index rows다.
`(deliverable_revision_id, section_id)` PK, exact Form revision FK, leaf order를 보관한다.
manifest와 같은 transaction에서 작성하고 수정하지 않는다. 이것이 있어야 ‘현재 판의 구간’ 조회가
모든 과거 JSON을 읽거나 current Form head를 잘못 따라가지 않는다. parent tree/전체 문항을 이 테이블에
복제하지 않는다. canonical source는 EditionComposition이며 불일치 시 명시적 integrity error다.

**판과 Product Revision을 혼동하지 않는다.** 하나의 논리 콘텐츠에 여러 판 head가 있고,
각 head는 기존 Product revision을 가리킨다. 기존 `deliverables.edition`은 구 계약의 표시값으로 유지한다.
새 reader는 이 값을 전역 현재 학년도로 읽지 않고 typed Edition을 읽는다. 제목을 임의로 바꾸어 구판을
올해 판으로 덮어쓰지 않는다. 내부 edition key는 콘텐츠 안에서 unique이고 year 단독 unique는 두지 않는다.
같은 연도·표시명의 새 판을 만들면 기존 판을 보여주어 실수를 줄이되, 정당한 별도 판을 이름 때문에 막지 않는다.

Edition의 Product 소속은 정체성으로 고정한다. 매년 새 판을 만드는 기본 동작은 복사이며 원판이 남는다.
표시명·학년도 오입력 수정은 영향 범위를 알리고 새 구성 revision으로 저장할 수 있다. 인쇄 이력은 그때 pin한
revision의 학년도/제목을 읽으므로 현재 표기 변경이 과거 이력을 이동시키지 않는다. 현재 사용의 연도는
current head에서, 인쇄 사용의 연도는 각 인쇄가 pin한 revision에서 읽는다.

**Form V2 소속 규칙:** form revision은 같은 논리 콘텐츠·판에 속해야 한다. 한 구간을 고칠 때 다른 구간의
Form revision을 복제하지 않고 새 EditionComposition이 기존 정확한 Form revisions를 재사용한다.
Form row의 기존 `deliverable_revision_id`는 생성 당시 revision으로 보존하며, 새 detail은 해당 revision이
같은 Edition 소속임을 검증한다. V1의 ‘정확히 같은 Product Revision’ 검증을 완화하여 호출하지 않는다.
V1 legacy import/read와 V2 편성 read는 명시적 schema dispatch로 구분하고, 공개 V1 목록에서도 새 detail을
구 V1로 직렬화하지 않는다. 관계 ID는 사전에 생성해 동일 transaction에서 FK를 만족시킨다.

### 15.2 빈칸·번호·복사

- `SlotTarget`은 discriminator union. EMPTY는 item/source pointer가 없어야 하고, 나머지는 해당 종류의
  필수 identity/revision/hash/schema를 전부 가진다. 원문 전체/bytes는 포함하지 않는다.
- `placement_id`는 논리 자리. 같은 구간의 reorder/교체는 유지한다. 다른 구간으로 이동할 때도 같은 판 안이면
  유지하고 두 구간을 원자적으로 바꾼다. 복사는 새 ID를 만들고 `copied_from`의 exact 위치/저장본을 남긴다.
- `position`은 구간 내 1부터 연속 순서다. 출력 번호는 별도 `RESET_PER_SECTION` 또는
  `CONTINUE_WITHIN_GROUP` 정책으로 계산한다. 선택적 표시 번호 override는 정렬 key가 아니다.
- DB에서 붙여넣기는 기본 INSERT다. 선택 자리를 REPLACE할 때만 정확한 placement ID 목록을 받는다.
  ‘학교 맞춤 시험지’ 같은 새로운 이름도 그대로 저장하고 유형별 개수/단원을 하드코딩하지 않는다.
- 원본 revision을 계속 사용한다. 새로운 문항 버전이 있다는 알림은 가능하지만 자동 교체하지 않는다.
  교체 명령은 선택한 새 revision의 권한과 입력/출력 지원을 재검증한다.

### 15.3 사용 집합의 정확한 정의

`current_placements(edition_head)`와 `effective_print_scopes`를 별도로 읽는다. 한 행을
`배치됨 + 인쇄됨`으로 합쳐 보이게 할 때 key는 `(edition, form, placement_id, exact target)`이다.
인쇄 뒤 같은 자리에 다른 문항을 넣으면 원래 문항은 `인쇄 이력`, 새 문항은 `현재 배치`로 각각 남는다.
여러 인쇄 회차는 하나로 지우지 않고 인쇄 기록 목록에서 본다. 조회의 사용 위치 수와 인쇄 횟수는 다른 수치다.

중복은 논리 Item 또는 확실하게 연결된 원본 source를 기준으로 계산한다. source-only와 그 등록 Item이
같은 문항인지 현재 공식 lineage가 입증하면 묶되 원래 pinned pointer는 수정하지 않는다. 불명확하면
별개의 문항으로 두고 ‘동일성 미확인’으로 표시한다. EOM source 번호 namespace와 구 지구과학 인덱스를
숫자만 보고 조인하지 않는다. 유사도 점수로 동일성 판정을 대신하지 않는다.

올해 판 전체를 읽을 권한이 없는 사용자에게 전사 미사용을 단정하지 않는다. `조회 가능한 범위 기준`을
응답에 명시하고 제한된 콘텐츠 제목·번호·문항 존재 여부는 경고로 누설하지 않는다.

### 15.4 최소 공유 권한

신규 permission 이름 후보는 `CONTENT_PLANNING_READ`, `CONTENT_PLANNING_WRITE`,
`CONTENT_PRINT_RECORD`, `CONTENT_PLANNING_MANAGE`다. 실제 역할 부여는 기존 운영자 RBAC 관리 경로를 따른다.
한 사용자가 만들었다고 자동으로 전 직원에게 문항 접근권이 생기지 않는다. 편성 권한과 각 문항/원본 read,
HWPX build/download 권한의 교집합을 적용한다. 신규 조직/팀/ACL 플랫폼은 만들지 않는다.

기존 private assembly의 creator 체크를 전역 해제하지 않는다. `content_form_memberships`로 연결된
새 편성 조립에 한해 같은 공식 콘텐츠 권한을 검사한다. 다른 조교가 읽거나 출력할 때도 그 사람의 실제
actor로 요청한다. 생성자 impersonation·권한 증명 없는 service 호출은 금지한다.
HWPX 조회/다운로드도 원래 owner-only 경계와 새 content-scoped boundary를 구분해 확장한다.

### 15.5 쓰기 transaction과 replay

현재 `CuratedDocumentAssemblyService.create()`는 자체 transaction을 연다. 새 편성 저장에서 이것을
중첩 호출하고 ‘원자적’이라고 주장하지 않는다. Catalog 내부에서 공유되는 명시적 unit-of-work용
검증/저장 함수를 해당 owner에 추출하고, 편성 use case가 **하나의 transaction**에서 호출한다.
SQLAlchemy Session은 application/infrastructure 내부에서만 사용하고 domain/contract/GUI로 노출하지 않는다.

1. actual actor/요청형식 검증, 현재 권한과 replay receipt 조회.
2. edition row lock → expected revision 비교. 복수 판 변경은 ID 정렬 순서로 잠근다.
3. 변경 구간의 source/Item pointer를 batch 확인, 새 assembly/Form/edition revision을 계산.
4. rows·사건·receipt·head를 동일 transaction에서 commit.
5. 동일 요청 replay는 최초 결과 pointer를 반환하고 현재 head로 대체하지 않는다. 응답의 current head와
   replayed revision은 구별한다. 다른 사용자가 후속 편집했으면 옛 replay가 화면을 덮지 않는다.

`(actor_id, command_kind, idempotency_key)` unique, request SHA mismatch는 충돌이다.
재시도마다 새 key를 발급하지 않는다. PostgreSQL concurrency·timeout-after-commit·crash-before-commit을
disposable DB에서 검증한다. network/파일 render는 transaction 밖에서 진행한다.

## 16. 기존 제한 해제·출력 재사용 상세 (1차 보완)

| 계층 | 확인한 제약 | 필요한 변경 |
| --- | --- | --- |
| GUI draft | 200개, pointer key set으로 중복 거부, pointer로 replace | 자리 ID 기반 편집기, 동일 대상 여러 자리 허용, page/virtual table |
| Catalog draft/manifest | 200개, source/item unique | draft V3·manifest V2 후보, 슬롯과 빈칸·지속 ID, 구 schema 유지 |
| Catalog persistence | 200 check와 unique source/item indexes | 새 versioned slot rows. 새 GUI에서 실제 중복·300/1,200자리 저장 검증 |
| Form bridge | assessment assembly와 curated assembly 타입 불일치 | 명시적 Form composition detail, owner/edition/hash 대조 |
| Build input | `curated_build.py` 200개와 unique Item, byte budget | 새 build input profile. 대상 중복은 허용하고 occurrence 순서를 pin |
| Builder | `curated_document.py`, `curated_mixed.py` 및 renderer 경계 | new handoff/결과 profile을 끝까지 연결. 원본파일 검증·객체 ID 충돌 회귀 |
| Output acceptance | count·position·binary relationship | occurrence 기준 정확한 개수/순서/번호/내장 그림 검증. content 동일하다고 두 자리를 하나로 합치지 않음 |
| 권한/조회 | 개인 owner 전용 | content-scoped 공식 authorization, 기존 private 경로는 유지 |

합본은 폴더/구간 선택 범위를 exact manifest로 고정한 뒤 기존 Manager→Builder→Artifact commit 경계로 간다.
선택 순서는 판의 저장된 순서다. 같은 문항의 bytes는 한 workspace에서 중복 materialization을 줄이되,
출력 occurrence는 모두 남기고 기존 merger의 object/resource ID remap을 적용한다.
전체 1,200문항 편성은 페이지 조회로 열고, 출력은 내부 streaming/순차 segment 처리로 한다.
외부 문항 파일을 이미 변환한 캐시는 exact source/hash/converter pin으로만 재사용한다.

빈 자리 또는 출력 지원이 없는 대상은 **저장은 허용**한다. 출력하려는 범위에 있으면 위치와 이유를
명시하여 제작 시작 전에 안내하며 묵묵히 제외하지 않는다. 빈 자리 없는 다른 회차의 출력은 계속 가능하다.
배점/번호 정책은 실제 새 출력 profile에 전달해 검증한다. 기존 파일 본문의 인쇄 번호를 안전하게 바꿀 수
없는 경우에는 metadata만 바꿔 ‘반영됨’이라 하지 않고 해당 원본의 출력 제약을 표시한다.

별도 200문항 단위 파일로 사용자에게 수동 분할을 강요하지 않는다. 실제 파일 크기/CPU/메모리 한계에
도달하면 저장/조회는 유지하면서 해당 출력의 안전한 한계와 구체적 선택 범위를 안내한다. 기존 runtime의
256MiB 등 안전 한도를 이유 없이 해제하지 않고, 확대 필요 시 실측과 isolated test로 정한다.

## 17. 2차 재독·설계 검토 기록

1차 보완을 저장한 **후** 같은 원본 ZIP을 다시 열었다. 08:54 UTC의 SHA-256이 §14와 일치했다.
원본 파일은 변경하지 않았다. 내용·단원 판단이 아니라 편집 과정과 기록의 의미를 재확인했다.

| R2 | 다시 확인한 원본 증거 | 최종 설계 반영 |
| --- | --- | --- |
| 01 | `27_엄블리버블!C7:F14`: 이동하면서 대상 삭제, 다른 위치 맞교환 | 작업 전 저장본 기준의 최종 상태를 원자 저장. 순차 overwrite로 문항 소실 금지 |
| 02 | 같은 시트 `E32:F36`: 여러 이동 후 최종 위치를 별도로 설명 | 현재 배치와 변경 사건을 구분. before/after로 바뀐 자리를 조회 |
| 03 | `27_테스트!K2`, `K12:L12`: 기록 누락인데 조교최종 | 검토 label은 기록 완전성/인쇄 증거가 아님. 누락을 미사용으로 오판하지 않음 |
| 04 | `27_단원별!H17/H217/H232/H241/H263`은 '-' | 빈 자리와 미연결 기록을 구별. 엑셀 이관은 별도 명시 작업이며 가짜 문항 생성 금지 |
| 05 | 원본 목록 H열 VLOOKUP은 첫 일치만 반환, J열 #REF!를 빈칸 처리 | 다중 사용 위치 전부 pagination 조회. 숨겨진 조회 오류를 ‘없음’으로 변환하지 않음 |
| 06 | `27_엄메!K1`: 실제 300개지만 첫 행 제외로 99.67% | 수기 셀 수식 복제가 아니라 저장된 자리·대상 수에서 상태 계산 |
| 07 | `26_기출변형`: 390개 이름, 양쪽 번호 존재 중 143개는 연도별 번호 다름 | 이름 유사성·연도 문자열로 문항 identity/revision을 연결하지 않음 |
| 08 | 전체 시트에 인쇄/발행/출판을 명시한 값 없음 | 인쇄 체크 의미는 사용자 설명에서 가져옴. 기존 색상/상태로 과거 인쇄를 만들어내지 않음 |

### 17.1 EOM 전체 원칙에 대한 2차 검토

| 점검 | 발견한 위험 | 결정 |
| --- | --- | --- |
| 모듈화/캡슐화 | 기존 create를 호출하면 별도 transaction 때문에 절반 저장 가능 | §15.5의 동일 owner UoW로 원자 저장. UI·domain에 SQL 누출 없음 |
| 단순성 | 모든 과거 사용을 새 UsageRecord로 복제하면 두 번째 정본 발생 | 현재 placement와 print scope join으로 읽음. 같은 사실의 별도 ledger 없음 |
| 역호환 | 구 Publication/Usage 형식이 source-only/사용자 인쇄 체크를 표현 못함 | 가짜 등록/출판 대신 별도 print fact로 명확히 표현, 기존 과거 기록은 그대로 조회 |
| 포인터 | 일부 인쇄 후 다른 회차만 수정해도 전체 revision hash는 바뀜 | 현재 인쇄 범위의 exact composition만 비교. §18.2 |
| 자료구조 | 이름 기반 key와 Item key 교체는 반복 문항에서 틀린 행을 바꿈 | 안정된 placement ID + map/ordered IDs, 순번은 표시/정렬 값 |
| 성능 | 사용 이력 조회가 모든 과거 JSON/파일/Graph를 스캔할 가능성 | indexed slot·head·print-scope joins, 권한 포함 batch, bytes 읽기 0 |
| 권한 | creator-only 해제를 전체 시스템에 적용할 위험 | content-bound scope에만 공식 권한 확장. 기존 private 조립 보호 |
| 전체 흐름 | 200 제한을 화면에서만 해제하고 builder/result가 거부 | input/output/DB/renderer/반환 DTO까지 하나의 호환 릴리스로 검증 |
| 운영 | 새 기능을 이유로 slot/GPU를 재시작할 위험 | 편성 자체는 AI/임베딩 실행 없음. rollout은 활성 작업 runtime pin 보존 |
| 유지보수 | Excel마다 수식·특수 상품 별도 code가 늘어날 위험 | 콘텐츠명/구간/번호 정책은 데이터. 특정 학년도·과목·상품 if 분기 없음 |

## 18. 구현자가 따라야 할 최종 세부 규칙

### 18.1 수정·이동·맞교환의 단일 저장 방식

구간별 임시 UI 변경을 모으고 `SaveSectionSet`에 **변경한 구간들의 최종 slot 배열**을 보낸다.
서버는 expected edition revision과 각 before assembly ref를 확인한 뒤 O(P) map 비교로 변화와 사건을 만든다.
별도의 범용 명령 언어나 event-sourcing 프레임워크는 도입하지 않는다.

- 한 구간의 swap은 최종 배열에서 두 placement의 position만 바뀐다.
- 구간 간 이동은 출발/도착 두 구간이 한 transaction에 포함되어야 한다.
- 대상 문항을 없애고 이동할 때는 제거된 placement와 이동된 placement를 모두 사건에 남긴다.
- 복사는 새 placement ID이므로 원래 위치와 동시에 존재할 수 있다.
- 같은 판의 서로 다른 현재 구간에 동일 placement ID는 존재할 수 없다. 같은 Item ID는 여러 번 존재해도 된다.
- 삭제할 구간에 문항이 있으면 영향 범위를 확인한다. archived/hidden 상태만 바꿔 미사용 판정을 속이지 않는다.
  현재 배치에서 빼는 명령은 명시적이고, 인쇄/역사 revision은 남는다.
- 바뀐 내용이 없으면 `NO_CHANGE`와 기존 revision을 반환한다. 읽기나 같은 내용 저장으로 이력이 불어나지 않는다.

### 18.2 부분 인쇄·후속 변경

`RecordPrint`는 selected leaf Form revision pointers와 그 범위의 표시 경로·출력 순서·번호 정책을 고정한다.
이 작은 값의 canonical `scope_sha256`이 있어야 한다. `edition_revision_id`만 비교해서 인쇄 상태를 판단하지 않는다.
예: 1회차를 인쇄한 뒤 2회차 수정 → 1회차는 그대로 ‘인쇄 기록과 일치’, 2회차는 미인쇄 상태다.
연속 번호를 쓰는 앞 구간의 문항 수가 바뀌어 선택 구간의 표시 번호도 달라졌다면 scope는 달라진다.

인쇄 상태는 가변 boolean을 수작업으로 맞추지 않고 현재 scope와 유효 print records에서 계산한다.
표시는 `인쇄 기록 없음 / 현재 구성 인쇄 기록 있음 / 인쇄 후 변경됨 / 일부 구간만 인쇄`이다.
이는 사용자가 기록한 사실에 대한 상태이며 프린터의 실물 출력 보증이 아니다.
구체적인 파일을 연결했다면 그 파일의 immutable output SHA도 보존한다.

구간 선택은 폴더를 포함할 수 있지만 서버가 그 저장본의 leaf 목록으로 확장한다. 빈 자리/대상 미연결이
있는 구간은 완전한 인쇄 구성으로 체크하지 않고 정확한 위치를 보여준다. 다른 완성 구간만 선택할 수 있다.
이미 외부에서 인쇄한 옛 자료의 배치 누락을 기록하는 기능은 후속 legacy intake 영역이며, 이번 입력 UI에서
없는 문항을 만들어 채우지 않는다. 동시 인쇄 체크는 같은 request key면 같은 record, 다른 key의 같은 scope는
기존 기록을 먼저 보여주고 명시적 `재인쇄 기록` 때만 별도 print ID를 만든다.
VOID는 오입력 기록 취소이고 실물 인쇄를 없던 사실로 지우는 기능이 아니다. 수정은 새 record와 교정 링크로 남긴다.

인쇄 명령의 의도는 `INITIAL / REPRINT / CORRECTION`으로 명시한다. 최초 기록은
`(edition_id, scope_sha256)`에 대한 INITIAL partial unique로 다른 사용자의 동시 중복도 막는다.
재인쇄·정정은 원 print ID를 요구하고 request key로 중복 생성을 막는다. 취소된 최초 기록을 일반
재전송으로 되살리지 않으며, 화면에서 명시적인 정정/재기록 절차로 이어간다.

### 18.3 인덱스·FK·정본 직렬화

| 대상 | 필수 제약/인덱스 |
| --- | --- |
| Edition | Product FK, `(edition_id, deliverable_id)` unique, `(deliverable_id, edition_key)` unique; 표시명·year는 identity key가 아님 |
| Edition head | 같은 edition/product 소속 revision만 허용하는 composite FK. 새 revision의 edition membership을 typed column/detail로 저장 |
| Edition metadata index | 새 typed revision의 academic_year를 indexed column/detail로 함께 저장; canonical metadata와 같은 transaction·불변 값, 과거 print와 현재 head를 각각 조인 |
| Edition leaf index | `(deliverable_revision_id, section_id)` unique, Form revision 역조회 B-tree, leaf order index; head와 join하여 현재 membership 판정 |
| Form membership | Form 1개당 Edition 1개, Form의 Product와 Edition의 Product 일치. 기존 Form은 억지로 편입하지 않음 |
| Form composition detail | 기존 Form revision FK + exact curated revision FK/hash, owner/edition 같은 쌍 검증 |
| Slots V2 | PK `(assembly_revision_id, placement_id)`, UNIQUE `(assembly_revision_id, position)`; item/source FK, 종류별 nullable field CHECK |
| Versioned rows | revision schema와 row family의 composite FK/CHECK 또는 제한된 owner 검증 trigger. V1/V2 rows 혼재 금지 |
| Reverse usage | `(item_id, assembly_revision_id, placement_id)` / `(source_id, assembly_revision_id, placement_id)` partial B-tree; exact revision 별 인덱스 |
| Form current linkage | edition membership→current form composition→assembly 조회 index. 역사 스캔 없이 현재 head에 속하는지 확인 |
| Print records/scopes | INITIAL의 `(edition_id, scope_sha256)` partial unique; `(print_record_id, form_revision_id)` unique, assembly revision 역조회 index; exact 소속 대조 |
| Print events | `(print_record_id, sequence)` unique, 보상 target FK, 중복 VOID 방지. 수정/삭제 금지 |
| Command receipts | `(actor_id, command_kind, idempotency_key)` unique, request hash·결과 pointer·상태 |
| Edit events | `(edition_id, sequence)` unique, before/after revision FK, 조회 pagination index |

계약은 JSON Schema 2020-12와 frozen models를 먼저 정의한다. float 점수 대신 optional 정수
`points_milli`를 사용한다. `null` 배점은 ‘모름/아직 지정 안 함’이고 0점으로 바꾸지 않는다.
식별자는 생성된 ID, 제목은 사용자 문자열이다. hash는 기존 `canonical_json_bytes`/SHA-256 방식으로
identity/revision과 분리한다. JSON/DB row에는 작은 metadata·포인터만 넣고 HWPX/PNG/보고서 bytes는 넣지 않는다.
길어진 구성 manifest는 기존 Artifact owner의 공식 commit 경계로 materialize할 수 있으나,
현재 규모의 포인터 tuple을 이유 없이 파일과 DB에 이중 정본으로 유지하지 않는다.

정본 manifest와 indexed slot rows는 같은 transaction에서 쓰는 한 객체의 두 표현이다. read 검증 시
형식·count·hash/slot 일치를 확인하고, 서로 다른 내용이면 cache처럼 최신 값으로 덮어 고치지 않는다.
불변 저장본의 표준 직렬화와 index 행 일관성은 persistence test로 보호한다.

### 18.4 API와 화면의 구체적인 연결

공통 prefix 후보: `/api/v1/content-planning`. 아래는 구현할 contract inventory이며 지금 활성 endpoint가 아니다.

| Method/path | 계약·행동 |
| --- | --- |
| `POST /contents`, `GET /contents` | 자유 제목 콘텐츠 생성, 권한 범위 목록 |
| `POST /contents/{id}/editions`, `GET /contents/{id}/editions` | 새 판, 선택 연도, 판 목록 |
| `GET /editions/{id}` | 최신 명시 read 또는 지정 revision의 작은 구성, ETag |
| `PUT /editions/{id}/structure` | If-Match + 구간 최종 트리. 회차 일괄 생성도 같은 규칙으로 처리 |
| `GET /editions/{id}/sections/{section_id}/placements` | exact revision·cursor·page size, source metadata와 중복 요약 batch |
| `PUT /editions/{id}/placements` | SaveSectionSet, 변경 구간 최종 배열, If-Match, Idempotency-Key |
| `POST /editions/{id}/copies` | exact source scope, INSERT/REPLACE, 대상 위치/ETag, 복사 결과 |
| `GET /editions/{id}/history` | 변경 event cursor, 지정 before/after 저장본 |
| `POST /usage/query` | read-only typed 대상 목록+연도/콘텐츠 범위. 기존 사용 이력도 adapter로 포함 |
| `POST /editions/{id}/prints`, `GET /editions/{id}/prints` | exact scope의 인쇄 체크/이력 |
| `POST /prints/{id}/corrections` | VOID/CORRECT 명시 선택과 사유. 기존 기록 보존 |
| `POST /editions/{id}/outputs` | exact 선택 범위를 기존 HWPX 제작으로 전달 |

GET/읽기 POST에서 새 조립·출력·사용 기록을 생성하지 않는다. 조회 response는
`schema_version`, pinned revision/ETag, `scope`, 작은 rows, next cursor, warning codes를 반환한다.
cursor는 snapshot·filter digest와 결합하고 현재 head가 바뀌어도 다음 페이지는 원래 snapshot을 읽는다.
무한 page size나 요청 body는 허용하지 않되 서버 pagination 한도를 콘텐츠 문항 수 한도로 오인하지 않는다.
error response에는 사용자 안내와 correlation ID를 포함하고 경로·SQL·traceback은 노출하지 않는다.

새 JSON schema 후보는 `content-edition-composition/1.0`, `content-planning-command/1.0`,
`content-usage-view/1.0`, `content-print-record/1.0`, curated draft/3.0·manifest/2.0이다.
아직 release가 아니며 구현 시 기존 schema inventory와 이름 충돌을 확인한다. API/BFF와 renderer handoff도
같은 candidate set으로 버전 지원을 고정하며 구 schema 파일의 내용을 변경해 새 뜻을 부여하지 않는다.

화면에는 `콘텐츠 / 사용 이력 / 변경 이력`을 작업 맥락 안에 둔다. DB 조회에서 ‘Excel에 배치’를 눌렀을 때
대상 콘텐츠·판·구간·삽입/교체 위치를 고르는 선택창을 열고, 완료하면 해당 위치로 이동한다.
Excel 행을 열면 기존 DB 상세/미리보기를 재사용하며 돌아왔을 때 원래 구간·선택·미저장 편집을 유지한다.
세션 만료 시 읽기 실패를 빈 목록으로 바꾸지 않는다. 인증 후 원래 저장 요청의 상태를 같은 key로 확인한다.
서버 저장본은 보존하고 비밀번호/토큰을 로컬 편집 상태에 저장하지 않는다.

### 18.5 출력과 인쇄 증거의 연결

HWPX 입력은 exact 선택 scope의 각 `(form_revision, placement_id)`를 전역 output position으로 매핑한다.
원래 문항·원본 참조와 display number를 함께 pin한다. 서로 다른 Form에 같은 문항이 있어도 각 occurrence를
출력한다. 다중 구간 build의 derived input manifest는 출력 준비물이며 편성 정본을 새로 쓰지 않는다.

`RecordPrint`에 연결할 output은 scope/hash/profile/완료 artifact가 일치해야 한다. 일부 구간 파일을
전체 콘텐츠의 인쇄 증거로 붙이지 않는다. HWPX가 실패하면 기존 실패 기록을 남기고 supported retry만 한다.
완료된 output 조회/다운로드는 새 renderer 실행을 하지 않는다. 새 편성 GUI의 기능 완료에는 실제
중복 문항·300개 이상 저장 및 합본의 대표 테스트가 포함된다. 수량/중복 해제를 저장에만 적용하고
HWPX에서 다시 거부하는 상태를 완료로 처리하지 않는다.

## 19. 구현 작업 분해와 완료 조건

각 작업은 설계 → schema → domain/application → adapter → focused tests 순서다. 사용자에게는
새 프레임워크를 보여주지 않고 기존 Studio의 데이터 작업으로 제공한다.

| 작업 | 담당 경계·구체 변경 | 완료 증거 |
| --- | --- | --- |
| I01 계약/호환성 | `catalog_contracts`와 API contracts에 위 candidate models/schema. V0/V1 의미 보존. initial ADR 0039에 후속 결정 연결 | schema/Pydantic round-trip, 구 계약 fixtures, 현재 소비 경로 inventory |
| I02 콘텐츠/판/구간 | Catalog의 새 `content_planning_editions.py`, 순수 `content_planning_rules.py`, typed Edition detail, migration | 새 콘텐츠·20회차·같은 연도 여러 판·순환 거부·FK·migration 왕복 |
| I03 배치 저장/제한 해제 | 기존 curated service/resolution에 새 manifest·slots. explicit UoW, revision save, copy/swap | 300/1,200 slots, duplicate·EMPTY·source-only, concurrent save/replay disposable DB PASS |
| I04 사용/중복 조회 | `content_usage_read.py`와 기존 Usage/lineage 공개 read 재사용. batch permission·pagination | 모든 위치 조회·동일 Item revision 변형·source alias·연도 미사용·query plan |
| I05 인쇄/사건 | `content_print_records.py`, scope hash·events·optional output link | 일부 인쇄·후속 수정·반복 클릭·오입력 정정·실패 rollback |
| I06 API/BFF/GUI | 새 `routers/content_planning.py`, typed gateway, `content-planning.js`·shared placement editor. navigation/guide/CSS/RECORD 검사 | 실제 browser 새 콘텐츠→배치→저장→이력→복사. 다른 사용자 충돌/권한 검증 |
| I07 HWPX 끝단 | 기존 `curated_build.py`, `curated_document.py`, `curated_mixed.py`, materializer/renderer/acceptance에 새 profile | 중복·300+ 입력, native 그림·수식·출제의도·순서, 실제 다운로드 SHA |
| I08 운영 전환 | migration→Catalog/Manager/Builder→API→Web 지원 순서, installed wheel/RECORD·권한·호환 smoke | 기존 DB·HWPX·Graph 조회 유지, 새 Excel 사용자 흐름의 live 증거 |

경로명은 기존 파일명 또는 책임별 **추가 후보**이며, 현재 존재/활성화를 주장하지 않는다.
새 JS/CSS를 만들면 Web release-integrity 목록/packaging에 추가한다. 화면만 먼저 배포해 없는 endpoint를
호출하게 하지 않는다. shared placement editor 추출은 DB와 Excel이라는 두 실제 사용처를 위한 것이며,
범용 spreadsheet/component framework로 확대하지 않는다.

### 19.1 필수 검증표

| ID | 상황 | 기대 결과/환경 |
| --- | --- | --- |
| T01 | 올해 과거 판 없음, 문항명으로 검색 | DB 정본을 찾아 신규 콘텐츠에 바로 저장; browser/API |
| T02 | 새 학교 콘텐츠 + 20회차 | 사용자 이름·빈 구간 정확히 생성; 단일 멱등 transaction |
| T03 | 교재 300자리, 주간형 1,200자리 | 저장/조회/목록 복원 성공; 200 제한 없음; DB/browser |
| T04 | 같은 문항을 같은 회차 두 자리 + 다른 콘텐츠 | 두 자리 보존·중복 경고·둘 다 출력; contract/DB/render |
| T05 | 같은 문항의 서로 다른 revision | logical 중복을 알리되 각 exact revision 보존 |
| T06 | source-only와 해당 등록 Item | 공식 lineage에 한해 동일 문항 표시; hash/revision 원본은 유지 |
| T07 | 서로 다른 원본 namespace의 같은 번호/비슷한 이름 | 동일 문항으로 병합하지 않음 |
| T08 | 이동·맞교환·교체 중 저장 실패 | 전체 미반영 또는 전체 반영, 소실/반쪽 사용 이력 없음; disposable DB |
| T09 | 두 조교가 같은 판 동시 저장 | 한 번만 head 전진, 다른 요청은 편집 보존+충돌 안내 |
| T10 | 다른 판 동시 저장 | 불필요한 전역 잠금 없음 |
| T11 | timeout 직후 같은 key replay | 같은 결과, 새 placement/event/build 0 |
| T12 | 실제 내용 변화 없는 저장 | NO_CHANGE, 새 revision 0 |
| T13 | 작년 전체 복사 후 올해 수정 | 작년 불변, 파일/Graph/보고서/임베딩 새 생성 0 |
| T14 | 올해 배치했다 제거, 인쇄 기록 없음 | 현재 사용에서 제외, 변경 이력에는 남음 |
| T15 | 인쇄 후 문항 제거/교체 | 과거 인쇄 사용은 남고 새 문항 현재 사용 구분 |
| T16 | 1회차 인쇄 후 2회차 수정 | 1회차 인쇄 일치 상태 유지 |
| T17 | 연속 번호의 앞 구간 변경 | 영향받는 뒤 구간 scope 차이 표시, 조용한 번호 재해석 없음 |
| T18 | 같은 인쇄 요청 반복/명시 재인쇄 | 전자는 같은 record, 후자는 별도 기록. VOID는 보상 event |
| T19 | HWPX 만들기/다운로드만 실행 | 인쇄 체크/실물출판 성공 자동 생성 0 |
| T20 | 원본 target 권한 취소/누락/stale/hash오류 | 출력/새 사용 중단, 명시 오류, 최신 대상 대체 금지 |
| T21 | 다른 콘텐츠 접근권 없는 사용자 | 중복 경고/미사용 판정에서 제목·문항 존재 누설 없음 |
| T22 | 빈 자리/미지원 출력 대상 | 저장 가능; 해당 범위 출력에만 구체적 안내, 다른 회차 정상 |
| T23 | 구 V1/V2 조립·Publication/Usage 조회 | 기존 semantics/파일/실패 이력 unchanged |
| T24 | 검색/선택/빠른 회차 이동/세션 재로그인 | 늦은 응답 덮기 금지, 원래 저장본·요청 복구; browser |
| T25 | snapshot pagination 중 다른 사용자 수정 | 같은 snapshot 계속 조회, 새 head와 섞이지 않음 |
| T26 | 인쇄한 콘텐츠 보관/삭제 표시 | 이력 숨김/물리 삭제 아님, 사용 여부 보존 |
| T27 | 사용 이력 read를 반복 | rendering/model/GPU 작업 0, 파일 bytes 읽기 0, bounded SQL |
| T28 | 혼합 HWP/HWPX/등록 Item 합본 | 본문 그림·수식·출제의도·반복 occurrence·순서 보존 |
| T29 | pointer payload/DB row 검사 | 큰 바이너리/전체 풀이보고서/Item 복제 없음 |
| T30 | 권한/배포/응답 계층 | schema→API→BFF→GUI 및 wheel/static 포함 검사, 실제 live와 source 결과 분리 |

성능 검증은 합성 10,000개 구간·100,000개 현재 자리와 더 큰 역사 집합을 기준 후보로 한다.
현재 판/선택 문항의 쿼리가 필요한 행만 읽는지 EXPLAIN ANALYZE로 확인한다. 읽기 페이지 100행의
쿼리 수가 행 수에 비례하지 않는지, 반복 문항은 한 번의 bulk metadata resolve로 처리하는지 검증한다.
처음에는 새 cache/queue/index 서버를 도입하지 않는다. 느리면 plan/benchmark 증거를 보고 필요한
DB index/조회 범위만 고친다. 이 수치들은 구현 시험용 제안이지 현재 서비스 SLO/실측값이 아니다.

### 19.2 배포와 되돌리기

이번 문서는 배포를 실행하지 않는다. 후속 구현 때 existing release runner/installed wheel 검증을 사용한다.
먼저 새 계약을 읽을 수 있는 backend/renderer를 준비하고 Web의 Excel 노출은 마지막에 한다.
진행 중 GPU/slot runtime pin을 확인하고 영향을 받는 설치본을 제자리 교체하지 않는다.
첫 live canary는 새 테스트 콘텐츠 하나에서 수행하고 실제 사용자 문항/기출/완료 보고서를 수정하지 않는다.

새 데이터가 기록된 후 schema를 무작정 downgrade하지 않는다. GUI 진입을 끄거나 쓰기를 중지하고
새 데이터를 읽을 수 있는 호환 backend는 유지하는 것이 기본 rollback이다. 원래 DB 조회·개인 조립·
HWPX 다운로드는 유지한다. 파일과 DB 백업/restore는 기존 운영 절차를 쓰며 새 백업 플랫폼을 만들지 않는다.

## 20. 범위와 기본값: 불필요한 확장 방지

이번 구현 설계의 핵심: 자유 콘텐츠 생성 → 실제 편성 → 저장과 이름 검색 → 중복·사용 이력 →
연도/구간 복사 → 인쇄한 구성 보존 → 기존 HWPX 출력 연결이다.

다음은 **현재 필수 아님**: 지구과학 Excel의 자동 수입, Excel 수식 재현, 학교별 학생 관리,
재고/배송/회계, 새 검토 결재 체계, 자동 출제/유사도 기반 자동 교체, 디자인 편집기, Graph 전체 재생성.
기존 문항 DB Excel export는 유지하지만 새 기능 이름 때문에 완전한 Excel 파일 왕복 편집을 요구하지 않는다.

설계가 정한 기본값(사용자가 직접 확정한 사실과 구별):

- 연도 없는 판 허용, 학년도와 실제 인쇄일 분리. 연도/판은 명시 입력하고 문항명에서 추출하지 않는다.
- 최초 판은 빈 기본 구간 하나. 새 회차 생성·연도 복사는 사용자가 명시적으로 선택한다.
- 현재 배치 또는 유효 인쇄 기록을 사용으로 계산. 제거한 미인쇄 배치는 과거 이력에서만 조회한다.
- 중복 경고는 scope별 표시, 중복 차단/팝업 반복 없음.
- 인쇄 체크의 최소 단위는 저장된 leaf 구간. 여러 구간/전체 선택 가능. 학생·배송 단위는 없음.
- 공유는 기존 RBAC에 명시된 편성/인쇄 권한으로 제어하고 자동 계정 권한 확대 없음.

기본값을 이후 사용자와 조정할 수 있지만 현재 설계 완료를 막는 미결 사항은 아니다.
과거 Excel 데이터 이관 시에는 참조 불명·누락·다른 과목 ID를 별도 proposal로 검수해야 한다.
이 사례는 구조 학습 자료이며 현재 통합과학 문항을 지구과학 문항으로 연결할 근거가 아니다.

## 21. 설계 완료 판정과 다음 단계

- 사용자 확정 요구 U01–U08과 기존 답변 보존: 완료.
- 요구한 5단계 순서, 원본 재독 2회, 변경하지 않은 SHA 확인: 완료.
- Product/Form/Usage/curated/HWPX 코드 대조와 EOM 원칙 검토 2회: 완료.
- ownership·identity·revision·pointer·state·DB/index·transaction·API/UI·테스트·rollout 계획: 작성 완료.
- 기능 코드/schema/migration 생성, 운영 배포, 실제 출력/문항 생성, 과거 Excel import: **실행하지 않음**.
- 기존 기출·창작·AI 문항, 완료 풀이/벡터, 실행 중 GPU/slot: 이 설계 작업에서 변경하지 않음.

문서 자체 검증: 로컬 링크 존재, Markdown fence 균형, 요청한 5단계 완료 순서, U01–U08 반영,
I01–I08 구현 단계와 T01–T30 후속 검증 목록, 원본 Excel SHA 불변을 확인했다.
코어 코드/DB/browser/HWPX 검사를 실행한 결과는 아니며, 문서 한 파일만 추가했다.

후속 구현은 I01부터 시작한다. 문서만으로 runtime 기능이 존재하거나 모든 기술 검증이 통과했다고
표시하지 않는다. 설계 검토 결과는 설계의 정합성에 대한 기록이며 T01–T30은 구현 때 실행할 gate다.

## 22. 구현 시 저장 경계 구체화 (2026-11-09, 아직 미배포)

- 공유 편성 권한은 새 RBAC 플랫폼이나 worker permission을 만들지 않고 기존
  `DELIVERABLE_READ`(조회), `DELIVERABLE_CREATE`(콘텐츠/판 생성),
  `DELIVERABLE_UPDATE`(편집/보관), `USAGE_FULFILL_PLAN`(인쇄 사실 기록)을 재사용한다.
  §15.4의 새 permission 이름은 후보였으며 이 명시적 매핑으로 구현한다. 문항/원본 read와
  HWPX 권한은 별도로 교차 검사한다. 기존 개인 조립의 creator 제한은 그대로 둔다.
- 새 편성 저장은 파일 bytes를 읽는 작업이 아니다. exact Graph/Registry/Intake/Artifact
  metadata를 기존 resolver에서 검증하고, HWPX 준비/다운로드에서 실제 bytes의 hash를
  검증한다. 과거 저장본 복사는 pin한 source/Graph revision을 그대로 재인가하며 최신으로
  치환하지 않는다. 구 V1의 current-selection 의미는 바꾸지 않는다.
- 콘텐츠 생성은 제목·종류와 첫 판/빈 구간을 한 transaction에서 생성한다. 전년도 복사는
  exact 구성 저장본을 새 판으로 복사하며 occurrence ID만 새로 발급한다. 편집 receipt에는
  원래 결과 revision만 저장하고, 응답의 현재 head는 별도 필드로 표현한다.

- 기존 Product revision의 `revision_number`는 Product 전체에서 unique지만 새 판마다 편집
  번호가 따로 진행되어야 한다. 기존 열 의미를 바꾸지 않고, 새 편성 Product revision의 저장
  ordinal은 PostgreSQL sequence로 배정한다. 판별 표시 번호·이전 판본 관계는 typed
  `content_edition_revisions` detail에 보존한다. 이것은 새 registry가 아니라 기존 Product
  revision의 소속/index다. 서로 다른 판을 편집할 때 Product 전체 row를 잠그는 대안은 피한다.
  sequence의 gap은 의미가 없으며 GUI·인쇄 이력은 판별 revision을 사용한다. 새 편성은 새로
  만든 콘텐츠에서 시작하며 legacy importer가 기존 revision 번호를 재작성하지 않는다.
- 연속 번호 GROUP은 모든 하위 문항 구간을 하나의 번호 흐름으로 묶는다. 그런 GROUP이
  없다면 FORM의 연속 번호는 같은 부모 아래에서 이어지고 RESET FORM은 1부터 시작한다.
  따라서 부분 출력도 선택 앞 구간의 개수를 반영한다. 표시 번호 override는 정렬에 쓰지 않는다.
- 인쇄 VOID/CORRECTION은 한 원 기록을 두 번 종결하지 않는다. 최초 정정 후 추가 정정은
  새 replacement 기록에 붙인다. 원본/보상 기록을 모두 append-only로 보존한다.
- 현재 구현 검증은 source 단계다. 새 DB schema·API·Web·HWPX의 설치 및 실제 사용 검증 전에는
  Excel 운영 활성화로 간주하지 않는다.

## 부록 A. 이전 대화의 설계 제안 보존

아래는 사용자 답변 전의 제안이다. 기존 DB ‘배치’ 탭 확장이라는 당시 제안은 사용자의 최신 지시인
별도 **데이터 → Excel** 화면으로 구체화했다. 마지막 질문의 답변은 U01–U08에 반영했다.

응. 지금은 개별 단원·난이도·집계 방식보다 **“문항을 콘텐츠에 배치하고, 그 사용 이력을 남기는 구조”**부터 잡는 게 맞아.

그리고 `26_미사용`은 정확히 **“기존 문항 중 26년에 사용하지 않았던 문항”**으로 이해했어. ‘미사용 문항’이라는 영구적인 종류가 아니라, **특정 연도를 기준으로 조회한 결과**인 거지.

### 1. 큰 틀은 이렇게 나누면 좋겠어

```text
문항 DB
   └─ 문항을 선택해서 배치
          ↓
콘텐츠 → 연도별 판 → 회차·단원 등의 구간 → 문항 순서
          ↓
      출력 및 사용 이력
```

여기서 각각의 책임은 간단해.

| 구성 | 담당하는 것 |
| --- | --- |
| 문항 DB | 문항 자체와 원본·해설·메타데이터 |
| 콘텐츠 | 어떤 교재·모의고사인가 |
| 연도별 판 | 그 콘텐츠의 올해 구성과 작년 구성을 구분 |
| 구간과 배치 | 어느 회차·단원·위치에 어떤 문항이 들어가는가 |
| 이력 | 어디에 사용했으며, 배치를 어떻게 바꿨는가 |

회차가 필요 없는 교재는 바로 구간을 만들고, 작은 시험지는 구간 없이 문항을 넣을 수 있도록 하면 돼. 사용자가 복잡한 계층을 반드시 채우게 하지는 않는 방향이야.

### 2. 사용자는 ‘실제 콘텐츠’를 열어서 배치하게 하자

기존 **DB의 ‘배치’ 탭을 확장**하는 방향이 자연스러워 보여.

사용 흐름은 다음과 같아.

1. 콘텐츠와 연도를 선택하거나 새로 만든다.
2. 배치할 회차·구간을 선택한다.
3. DB에서 문항을 찾아 담거나, 기존 배치를 가져온다.
4. 지금처럼 순서 변경·빼기·교체를 한다.
5. 저장하고 필요하면 HWPX로 출력한다.

현재 조립 목록이 “어딘가에 저장된 문항 묶음”이라면, 앞으로는 **“이 콘텐츠의 이 회차에 들어가는 문항 묶음”**이 되는 거야.

기존 코드에도 순서 저장·문항 참조·HWPX 출력 경계가 있으니, 이 기능을 새로 만들기보다는 **조립이 속할 콘텐츠와 사용 이력을 연결**하는 쪽으로 가면 돼. 콘텐츠에 연결하지 않은 임시 조립도 유지할 수 있고.

### 3. 작년 → 올해 복사·붙여넣기는 이렇게

사용자에게는 익숙하게 다음 기능을 제공하면 돼.

- 작년 콘텐츠 전체를 올해 구성으로 복사
- 특정 회차·구간만 가져오기
- 선택한 문항만 현재 위치에 가져오기

내부적으로는 문항 파일이나 풀이보고서를 복제하지 않고, **동일한 문항을 가리키는 새 배치만 만드는 방식**이야.

그래서:

- 올해 순서를 바꿔도 작년 배치는 그대로 남음.
- 올해 한 문항을 빼도 문항 DB에서 삭제되지는 않음.
- 작년과 올해에 썼다는 이력이 모두 남음.
- 단순 재사용 때문에 Graph 등록이나 임베딩을 다시 할 필요가 없음.
- 배치 당시 선택한 문항 버전을 보존해서, 나중에 문항이 수정돼도 과거 출판본이 몰래 바뀌지 않음.

### 4. 이력은 두 종류를 구분하자

**사용 이력**과 **편집 이력**은 다르게 보여주는 게 좋아.

사용 이력은 문항 상세에서:

> 이 문항이 어느 연도의 어떤 콘텐츠, 어느 위치에 들어갔는가?

편집 이력은 콘텐츠 안에서:

> 누가 언제 문항을 넣거나 빼고, 순서를 바꾸거나 교체했는가?

보통은 사용 이력만 간단히 보여주고, 편집 이력은 필요할 때 펼쳐보면 돼. 문항마다 ‘사용 교재명’을 별도로 수동 입력하게 하지 않고, **배치 기록을 양쪽 화면에서 조회**하도록 해야 정보가 어긋나지 않아.

또 HWPX 다운로드와 실제 출판은 구분해야 해. 파일을 시험 삼아 내려받았다고 바로 ‘출판 완료’가 되면 안 되니까.

### 5. 먼저 확인하고 싶은 건 세 가지야

1. **콘텐츠의 연도 관계**
   같은 이름의 교재·모의고사가 매년 이어지는 것으로 관리하면 될까? 예를 들면 ‘엄메이징’이라는 콘텐츠 아래에 2026판·2027판이 있고, 각각의 배치는 독립적으로 보존하는 방식이야.
2. **‘사용했다’의 기준**
   문항을 배치해서 저장하는 순간부터 해당 연도에 사용한 것으로 봤어? 아니면 일단 ‘사용 예정’이고, 최종 확정이나 출판 이후에 ‘사용 완료’로 구분해야 할까? 이 답이 연도별 미사용 조회의 기준이 돼.
3. **같은 연도 내 중복 사용**
   같은 문항을 여러 콘텐츠에 넣는 것은 허용하되 “올해 다른 콘텐츠에도 배치됨”이라고 알려주면 될까? 아니면 특정 콘텐츠끼리는 중복 사용을 막아야 하는 규칙이 있었어?

우선은 이 세 가지를 정하면, 엑셀의 세부 내용을 끌어오지 않고도 **콘텐츠 관리·배치·재사용·이력 조회의 중심 구조**를 잡을 수 있어.
# 구현 보완: 범위 HWPX 출력의 소유 경계 (I07)

## 연도 사용 조회의 연결 (I04)

기존 DB의 창작·기출·외부·AI 목록에 선택적인 `usage_state`와 `usage_year`를
추가한다. 현재 head/유효 인쇄의 동일한 Catalog SQL projection을 사용하고,
페이지를 자르기 **전에** semi/anti-join한다. 기본 조회는 변경하지 않는다.
정본은 기존 occurrence와 인쇄 기록이며, 미사용 flag나 별도 검색 인덱스를 저장하지 않는다.
논리 Item/source의 indexed 관계와 공식 등록 lineage만 사용한다. 필터와 cursor를 함께
pin하고 현재 사용자의 DELIVERABLE_READ도 확인한다. 쓰기·재시도는 없으며 불명확한
포인터/연도는 거부한다. 비용은 해당 연도 사용 위치와 원 모집단 조회에 비례하며,
페이지마다 전체 문항을 조회해 클라이언트에서 빼는 방식은 불완전한 pagination 때문에 쓰지 않는다.
과거 사용은 별도 원본 계약의 이력으로 표시하고, 판/학년도 없는 예전 기록의 연도를
날짜나 파일명에서 추측해 새 편성/인쇄 기록으로 만들지 않는다.

2026-11-09. 아래는 기존 합본을 대체하지 않는 범위 출력 연결이다.

1. **책임**: Catalog가 정확한 판·선택 회차를 출력 입력으로 고정한다. 기존 HWPX
   application/FIFO/recovery/Builder/Artifact owner가 제작·재전송·다운로드를 담당한다.
2. **정본**: 기존 판 revision과 Form/curated Assembly revision이 정본이다. 출력용
   Assembly는 작은 포인터의 파생 snapshot이며 원문·그림·보고서를 복사하지 않는다.
3. **identity**: 판 revision 및 print scope hash를 기존 curated Assembly V2에 연결하는
   작은 `content_delivery_scopes` 관계를 둔다. 출력용 자리도 원래 placement ID를 유지하고
   출력 순서만 선택 회차 순서대로 다시 매긴다. 같은 Item의 두 자리는 서로 다르다.
4. **해석**: 준비와 실행/조회에서 actor, 판/hash, Form/Assembly, source/Item와 Artifact를
   기존 resolution owner로 검사한다. 빈 자리 포함 출력은 명시적으로 거부한다. 현재 판으로
   자동 바꾸지 않는다. native 한글 본문의 번호/배점은 임의 재작성하지 않는다. 편성의 별도
   표시번호·배점·회차 경로는 scope에 보존하며 출력 순서는 canonical placement 순서다.
5. **접근**: 판의 출력 목록, exact Assembly 읽기, 같은 scope 재사용, FIFO 제작, build ID 조회.
6. **구조**: scope→Assembly unique/index와 판 revision FK, 기존 command receipt unique,
   기존 build queue/index를 재사용한다. target metadata 조회는 set/map으로 중복 제거하되
   출력 occurrence 배열을 제거하지 않는다.
7. **규모**: 선택 자리 수에 O(n), metadata는 O(unique targets+n). 기존 200 계약은 보존하고
   V2 build input/V4 render에서 최대 100,000 occurrence를 표현한다. 실제 실행은 input/
   output byte budget·section/package 한도도 함께 적용한다. 1,200자리 저장은 어떤 크기의
   1,200개 원본도 단일 파일로 출력된다는 보장이 아니다.
8. **동시성**: 입력 준비의 짧은 Catalog transaction에서 scope·Assembly·receipt를 함께
   저장한다. 출력 요청은 DB transaction 밖에서 기존 Manager를 호출한다. timeout 후에는
   같은 key/Assembly로 재조회하며 원문 변환·렌더를 transaction 안에 넣지 않는다.
9. **의존성**: presentation→application→계약. 기존 Catalog pin service와 Manager
   materializer/Builder를 확장한다. Builder는 DB/권한/Edition을 알지 않는다.
10. **실패/호환성**: 구 protocol/schema bytes는 보존한다. 새 profile은 새 protocol bundle로
    reserve하며, 실패·중단 결과는 기존 state machine/recovery를 사용한다. 완료 output을
    인쇄 기록에 붙일 때 scope와 Artifact/hash를 대조한다. 인쇄는 여전히 사용자 기록이다.
11. **단순 대안**: 회차별로 구 200개 private assembly를 자동 분할하면 선택 전체 파일,
    반복 자리와 출력 lineage가 깨진다. 별도 queue/renderer 대신 기존 합본에 새 입력 profile과
    scope 관계만 추가한다. 슬롯/GPU 작업과 문항 정본은 변경하지 않는다.
