# 기존 문항 아카이브 등록·조회 계획

상태: 단계별 구현 중인 설계 기준. 이 문서는 운영 DB 등록, 원본 파일 이동, 문항 승인, Graph 게시를 승인하거나 수행하지 않는다.

작성 기준: 2026-10-27 UTC, `staging/통합과학 DB … all.xlsx`와 `staging/N제.zip`의 읽기 전용 조사. 정확한 원본 식별자는 운영 Intake에서 파일 바이트와 SHA-256을 다시 고정한다. 이 아카이브의 `N제` 폴더명은 내보내기 경로이지 교재·상품의 정본 분류가 아니다.

## 1. 목표와 범위

기존 노션 DB에서 내보낸 엑셀의 **모든 행과 32개 열 A:AF**, 원래 셀 값과 파일 연결을 잃지 않고 EOM에서 검색·열람·엑셀 내보내기까지 제공한다. 파일 링크의 사용자 표시만 `~.hwp`/`~.hwpx` 같은 **파일명**으로 바꾼다. 실제 다운로드는 파일명이나 호스트 경로가 아닌 권한 검사를 거친 불변 Artifact pointer로 수행한다.

원본 `.hwp`/`.hwpx`를 보관·조회하는 것과 EOM의 구조화된 정본 `Item Revision`으로 승격하는 것은 별개의 단계다. 파일 하나가 존재한다는 이유로 본문·정답·해설을 추측하거나, 생성된 문항으로 가장하거나, 승인·출판 가능 상태로 표시하지 않는다. 최초 기능은 **원본과 메타데이터가 온전히 연결된 문항 보관함**이다. 사용자가 추가로 확정한 종료 범위에는 검증된 `창작` 문항의 풀이보고서와 기존 Graph 게시까지 포함한다. 원본 보관과 Graph 게시의 자격 및 결과는 별도로 판정한다.

## 2. 조사 기준선과 격리 대상

- 엑셀: 데이터 행 1,297개, A:AF 32열. `U=고유번호`, `L/M/N=1/2/3교`, `X=반려 여부`; 난이도 B:E/J, 배점 H, 학년 O, 단원 Q/R, 유형·분야 Y/Z, 출제일·출제자 AC/AD 등도 보존한다. U열은 1,297행 모두 비어 있지 않은 5자리 문자열이며 행 간 중복이 없다. U열에는 수식이 없고 이 시트의 별도 hyperlink element도 없다.
- 사용자가 정한 최종본 규칙을 적용하면 3교 894건, 3교가 없는 비반려 2교 173건, 합계 1,067건이 **최종본 후보**다. 반려 5건과 최종본 없는 225건도 엑셀 원본/관리자 이력으로 남기되 정본 Item으로 자동 승격하지 않는다. 1교는 언제나 초안이다.
- ZIP: 2,797,713,785 압축 바이트, 3,854,257,519 압축 해제 바이트, 17,123 entry; 전체 ZIP CRC 검사는 통과했다. SHA-256은 `e22054346d28a829817c2e941ae4cf2dd2daec09b13862c3ee7cd89240c23909`이다. 실제 문서 후보는 HWP 확장자 1,083개, HWPX 4개이며 Mac 메타파일과 symlink가 섞여 있다. 전체 ZIP을 무조건 풀면 안 된다.
- 이 1,087개 HWP/HWPX 파일명은 **모두 확장자 바로 앞에 정확한 5자리 번호**가 있다. 서로 다른 번호는 1,065개이고, 같은 번호가 여러 파일에 붙은 그룹은 17개다. 엑셀 U열은 행 고유 메타데이터로 보존한다. 파일명 번호는 행 대응의 보조 단서일 뿐이고, 중복 파일 그룹은 교정 단계·엑셀 행·파일 hash를 함께 대조할 때까지 단일 파일로 축약하지 않는다.
- 1,067개 최종본 후보를 읽기 전용 대조한 결과 1,042건은 단일 HWP 대응, 1건은 이름은 `.hwp`이지만 내부 HWPX인 단일 대응, 10건은 같은 바이트의 중복 위치, 6건은 해당 고유번호 파일 없음, 7건은 고유번호는 있으나 파일명/내용 맥락이 불일치하고 1건은 링크가 `.ai`다. 따라서 **1,053건은 높은 신뢰도의 연결 후보, 14건은 격리**다. ZIP의 UTF-8 파일명이 CP437로 해석되는 경우를 화면·대응 이름에서 복원하고, 노션 링크의 복사 번호(` 1`, ` (2)`)와 ZIP 파일의 과거 번호 주석은 동일 U 안에서만 정규화한다. 원래 문자열과 멤버명은 보존한다. 파일명 일치는 승인의 증명이 아니며 Intake 시 각 멤버 해시와 문서 내용을 다시 검증한다.
- 한 `.hwp` 확장자 파일의 실제 내용은 HWPX/ZIP이며, 엑셀의 한 최종 링크는 `.ai`이지만 같은 번호의 HWP가 ZIP에 있다. 확장자를 근거로 몰래 교체하거나 `.ai`를 문항 본문으로 간주하지 않는다.
- 일부 `Grade` 값은 학년 숫자 대신 과목처럼 보이고, 일부 메타데이터는 비어 있다. 값이 비어 있거나 모호하다는 사실까지 보존하고, 빈 값을 임의 기본값으로 채우지 않는다.
- 창작 출처 분류는 Y열의 원값이다. 이 파일에서 `기출변형` 1,056행, `자유출제` 241행이며, 반려를 제외하고 3교 또는 허용된 2교가 있는 최종본 후보는 각각 832행·235행이다. 정확히 연결된 후보는 각각 820행·233행, 연결 예외는 각각 12행·2행이다. W열의 `기출변형(0/1)`은 기출변형 행에도 0·빈칸이 있으므로 분류 또는 작업 대상 필터로 대체하지 않는다. Y/W 원값은 모두 보존한다. 이 수치는 원본·ZIP의 읽기 전용 대조이며 운영 등록이나 Graph 게시 수가 아니다.

## 3. 책임·정본·식별자

연결 예외 14건의 행·고유번호·교정본 셀·원본 링크 파일명·동일 번호 후보 SHA와 검수 조건은 [연결 예외 검수 기록](../operations/NOTION_ITEM_LINK_EXCEPTIONS_2026-10-27.md)에 고정한다. 후보는 자동 연결·Item 승격·Graph 게시에서 제외한다.

이 외부 아카이브의 실제 권리자·소유자는 현재 검증되지 않았다. Intake의 내부 기본값인 팀장 소유를 상속하면 출처가 허위로 기록되므로, source-only Intake에서는 `source_owner_type=other`, `source_owner_reference=notion-export-owner-unverified`로 명시한다. 이는 이용 권한의 추가 승인이나 소유자 확정이 아니며, 확인되면 새 출처 결정과 revision으로 남긴다.

```text
원본 XLSX (Content Intake Artifact Revision) + ZIP 해시 고정 운송 봉투
  -> 허용된 HWP/HWPX/관련 자료 멤버만 검증·분할 Intake
  -> 버전 고정 매핑 계약 + 행/파일 대응 제안 (Catalog)
  -> 확정된 원본 문항 기록과 모든 교정본 파일 pointer (Catalog)
  -> 필요 시 문서 변환·구조화 추출 제안 (Orchestrator 경유)
  -> 검증·결정된 AssessmentItemContent + 정본 Item Revision (Item Registry)
  -> 승인된 창작 Item의 기존 Knowledge Analysis + 풀이보고서
  -> APPROVED_ITEM Graph 공통 publisher를 재사용하는 창작 출처 검증 경계
  -> 임베딩·출판
```

엑셀과 선별된 각 문서 바이트의 정본은 Content Intake의 불변 Artifact Revision이다. 현재 일반 Intake는 파일당 100 MiB, 한 묶음 500파일·2 GiB를 제한한다. 이 ZIP 자체는 2.8 GB라 일반 Intake의 파일이 될 수 없고, 문서 1,087개도 한 묶음으로는 초과한다. ZIP은 정확한 SHA-256으로 고정한 **운송 봉투**로 취급하고 허용된 멤버를 안전하게 스트리밍하여 여러 정상 Intake 묶음으로 넘긴다. 조사한 HWP/HWPX 1,087개는 합계 약 445 MB이고 가장 큰 파일이 약 46 MB이므로 개별 파일 한도 안에 있다. `.ai` 등 보조 원본은 실제 엑셀 연결과 용량을 따로 검증해 추가 묶음으로 다룬다. 원본 ZIP 자체를 NAS에 보존하려면 일반 Intake의 상한을 몰래 늘리지 말고 별도 대용량 봉투 Artifact commit·용량·복구 게이트를 통과해야 한다. 봉투 보존 전에는 그 바이트가 정본 NAS Artifact라고 주장하지 않는다.

원본 파일명·ZIP 내부 경로·엑셀의 URL 인코딩 링크는 **출처 관찰값**이고 ID가 아니다. 외부 문항 식별자는 `source_namespace + U(고유번호)`이며 EOM `item_id`와 별개다. U는 선행 `0`을 잃지 않도록 숫자형이 아닌 정확한 5자리 문자열 메타데이터로 저장한다. 같은 고유번호의 2교/3교는 하나의 외부 문항에 딸린 원본 교정본이지 EOM의 `item_revision_id`와 동일한 개념이 아니다. 엑셀의 시트·행·셀 좌표와 각 원본 파일의 ZIP 멤버명/해시는 출처 포인터로 남긴다.

등록은 기존 `Content Intake`와 `Catalog` application 경계를 따른다. 기존 `Item Registry`에는 구조화된 문항과 검토 근거가 마련된 뒤 공식 등록 명령으로만 쓴다. 현재 구조화 문항 가져오기는 **기존 승인 문항의 새 버전**을 만드는 기능이고, 기출 승격은 **기출 추출 acceptance**가 전제이므로 둘 중 하나를 이 노션 아카이브에 억지로 재사용하지 않는다. 필요한 최소한의 `external-item-intake` 후속 workflow/contract를 만들되, Registry 테이블을 우회해서 쓰지 않는다.

## 4. 프로토콜과 데이터 모델: 먼저 정의할 것

JSON Schema 2020-12와 동일 의미의 Pydantic 모델을 기존 `catalog_contracts`/해당 application 경계에 추가한다. 기존 released schema의 바이트나 의미는 바꾸지 않는다.

1. `external-item-workbook-mapping/1.0`: 정확한 시트·헤더·A:AF 열, 타입, 상태값 해석, 파일 링크 열, 최종본 선택 규칙, Unicode/URL 정규화 방식, 원본/정규화 값을 모두 담는 규칙. 계약 revision과 hash를 pin한다.
2. `external-item-row-proposal/1.0`: workbook Artifact Revision, 시트/행 번호, 외부 고유번호, A:AF의 원값·셀 타입·공백 여부·원본 셀 참조, 정규화된 검색값, 1/2/3교와 `.ai` 파일 연결 후보, 후보별 해시, 불일치 사유. 행 content hash는 변경 불가다.
3. `external-item-file-binding/1.0`: 정확한 ZIP/source Artifact Revision, 멤버 원래 이름 바이트와 정규화 표시명, 실제 탐지 media type, SHA-256, 크기, 교정 단계, 파일 역할, 검토 결정. 같은 바이트의 복수 위치는 하나의 파일 Artifact를 참조하되 경로 관찰은 모두 남긴다.
4. `external-item-import-decision/1.0`: 행별 `RESOLVED / UNRESOLVED / CONFLICT / REJECTED / DRAFT_ONLY`, 최종본 선택 근거와 결정자/UTC 시각, 사용한 mapping revision/hash. `RESOLVED`만 원본 문항 기록에 반영한다. 14개 예외는 별도 검토 전까지 격리한다.
5. `external-item-source-view/1.0`: 조회 전용 DTO. 외부 고유번호, 상태, 메타데이터 전체, 선택된 최종 교정본, 교정본 목록, 파일명, 내부 불변 포인터, 미리보기/다운로드 가능 상태를 담는다. 일반 사용자 응답에는 NAS·ZIP 내부 경로, 내부 credential, 불필요한 기술 ID를 노출하지 않는다.

DB에는 source/import/row identity, 상태, 제한된 32필드 행 스냅샷, 인덱스 대상 정규화 값, pointer와 hash만 둔다. 원본 엑셀·HWP/HWPX·파생 PDF·긴 추출 결과는 Artifact store에 둔다. 원본 엑셀은 최종 권위자이고, DB의 행 스냅샷은 그 source revision에 고정된 **조회용 불변 파생물**이다. 재매핑은 기존 행을 수정하지 않고 새 mapping revision과 import revision을 만든다.

### 영속 조회 구조의 구체화

- `external_item_sources`: `(namespace, U)`의 유일한 논리 식별자와 현재 revision pointer만 둔다. U는 사용자가 허용한 업무상 5자리 고유번호로 목록·상세·정확 검색에 표시할 수 있다. EOM 내부 source/revision/Artifact ID는 기본 GUI에 노출하지 않는다.
- `external_item_source_revisions`: workbook Artifact Revision·매핑 Revision/hash·원본 시트/행·A:AF 셀 관찰·선택된 원본 파일 pointer·결정 상태의 불변 snapshot이다. `(source_id, revision_number)`, `(import_id, row_number)`, `(import_id, U)`를 고유 제약으로 보호한다. 다른 import의 수정은 successor revision으로만 나타낸다.
- `external_item_imports`: workbook/운송 ZIP/mapping의 고정 hash와 요청·완료 상태를 관리한다. 정확한 조합의 요청은 멱등 replay한다. ZIP 운송 봉투는 Artifact가 아니므로 `archive_sha256`은 원본 파일 pointer를 대신하지 않는다.
- 파일 바이트는 기존 `content_intake_source_files → artifact_revisions`를 사용하고 새 테이블에 복사하지 않는다. 미연결·반려 행은 selected file pointer가 `NULL`인 상태로 남는다.
- 인덱스는 `(namespace, U)` 고유 B-tree, 현재 상태/단원/분야/정렬의 bounded keyset read B-tree, `(import_id, row_number)` 및 `(source_id, revision_number)` 고유 B-tree다. 32칸 전체에 무작정 GIN을 달지 않는다. 예상 1천여 건에서 수십만 건까지 `O(log n + page_size)` key lookup을 목표로 하고, 실제 query plan과 필터 사용량을 보고 보조 인덱스를 추가한다.
- 한 import의 source pointer 해석과 revision insert/current pointer CAS는 Catalog application transaction이 소유한다. 원본 파일 commit은 먼저 기존 Intake/Artifact 경계에서 끝나야 하며, 부분 실패가 있으면 성공한 원본 Artifact를 버리거나 실패 행을 성공으로 바꾸지 않는다. 사람의 불일치 판정은 새로운 decision revision으로 남긴다.

## 5. 파일명 표시와 대응 규칙

- GUI 링크 텍스트는 선택된 파일의 정규화된 **basename**과 실제 형식 배지만 표시한다. 링크 목적지는 EOM의 인증된 source-file download API이며, 브라우저가 파일 경로나 Artifact ID를 임의로 선택할 수 없다.
- 내부 매칭은 `source namespace + U + 검토된 교정 단계 + 정확한 member hash`를 사용한다. 파일명만 같거나 `U`만 같으면 자동 결정하지 않는다. 경로 문자열은 설명 자료이지 권위가 아니다.
- 엑셀의 원래 하이퍼링크/텍스트, URL 인코딩 값, 원래 파일명, Unicode 정규화 전후 값, ZIP 멤버 관찰, 중복 위치를 모두 보존한다. 표시명 변경은 이 출처 정보를 덮어쓰지 않는다.
- 3교가 있으면 3교가 우선이다. **3교가 있는데 파일 대응이 실패하면 2교로 조용히 대체하지 않는다.** 3교가 없고 반려되지 않은 경우에만 2교를 선택한다. 1교는 조회 가능한 초안 이력일 수 있지만 최종본이 아니다. `반려 여부`가 모호하면 자동 승인하지 않는다.
- 파일 확장자와 magic byte가 다르면 원래 파일명과 실제 탐지 형식을 모두 기록한다. 특히 `.hwp`라는 이름이지만 실제 HWPX package인 문서는 **HWPX로 처리**한다. 이때 확장자를 이유로 격리하지 않지만, 실제 HWPX ZIP 구조·필수 멤버·외부 참조는 사용 전에 검증한다. 잘못 표기된 확장자를 원본 Artifact에서 바꾸지 않는다. 알 수 없는 형식이나 역방향 불일치는 격리한다. `.ai`는 별도 보조 자료로만 연결하고 최종 문항 파일 대체는 명시적 결정이 필요하다.

## 6. 조회·미리보기·승격 UX

초기 운영 미리보기는 교정본의 정확한 source revision·교차검증된 Intake Artifact를
입력으로 고정한 뒤, 사용자가 `PDF 미리보기 준비`를 누를 때 Catalog가 PDF 파생물만
커밋한다. `GET preview.pdf`는 파일을 만들지 않고 원본 source를 다시 인가한 다음
manifest·SHA가 일치하는 PDF만 스트리밍한다. 준비 명령은 source revision·교정 차수
기반의 멱등키를 사용하며, 원본 HWP/HWPX를 새 Artifact로 복사하지 않는다. 이 PDF는
내용 추출·정본 문항 승인·Graph 게시의 증거를 자동으로 부여하지 않는다. 준비되지
않거나 원본이 바뀐 경우에는 명시적 오류로 끝나며 암묵적 최신 버전 대체는 금지한다.

기존 문항 보관함의 Catalog read model을 확장해 `SOURCE_ONLY`와 `REGISTERED_ITEM`을 구분하는 판별 DTO를 사용한다. `SOURCE_ONLY`에도 목록 검색, 전체 32필드 상세, 최종/이전 교정본 파일명, 인증된 원본 다운로드, 변환 상태를 제공한다. 기존 `Item` 조회의 의미나 Graph 기반 기출 occurrence 조회를 바꾸지 않는다. 정본 승격 후에는 같은 외부 고유번호 source 기록에서 정확한 `item_id + item_revision_id`를 따라간다. 사용자에게 batch를 기본 노출하지 않는다.

검색: 외부 고유번호 exact lookup, 등록 상태, 단원·분야·분류·학년·출제자·날짜·난이도 필터, 생성일/고유번호 순서의 keyset pagination. 인덱스는 실제 query plan을 보고 `namespace + U` unique, 상태/단원/분야/날짜/정렬용 B-tree를 최소로 추가한다. 한 페이지의 source/file pointer를 bulk resolve해 N+1을 피한다. 예상 규모는 우선 1,297행, 이후 수십만 문항까지 확장 가능하게 bounded page와 인덱스를 사용한다. 조회 자체는 원본 파일을 매번 복사하거나 변환하지 않는다. **5자리 U 고유번호는 사용자가 허용한 업무 메타데이터로 GUI 목록·상세·정확 검색에 표시한다. EOM 내부 source/revision/Artifact ID와 경로는 숨긴다.** 원본 메타데이터 보존을 위해 XLSX export의 원본 시트에도 U를 남긴다.

노션식 상세 필터는 원본 A:AF의 열과 연결 상태를 조건 대상으로 삼되, UI에서는 열 이름을 업무 용어로 표시한다. 첫 계약은 최대 8조건의 `ALL`/`ANY` 조합이며 `일치`, `불일치`, `포함`, `비어 있음`, `비어 있지 않음`을 제공한다. 같은 조건 계약을 목록과 Excel export에 사용하고 필터·정렬·권한·커서를 함께 고정한다. 입력값은 255자로 제한하고 와일드카드 문자는 리터럴로 이스케이프한다. API가 허용한 고정 열만 SQL 표현식으로 매핑하며 사용자 문자열을 SQL 식별자나 경로로 해석하지 않는다. 현재 1,297행에서는 `(namespace,U)` keyset과 기존 자주 쓰는 열의 B-tree를 우선 쓰고, 임의 열 `포함`의 실제 query plan/지연을 측정한다. 수십만 행에서 반복되는 임의 열 검색이 병목으로 관측되면 불변 source revision에서 파생된 별도 인덱스/검색 projection을 추가한다. 원본 JSONB를 대신하지 않으며 새 revision이 발행되면 파생 인덱스도 같은 트랜잭션 경계에서 갱신한다. 검색용 병렬 DB는 만들지 않는다.

유사도 검색은 별도 벡터 DB나 파일명·태그만의 유사도를 만들지 않고, **현재 설치된 로컬 임베딩 인덱스와 공식 Similarity Query application**을 DB 읽기 경계에 연결한다. 사용자가 한 문항을 기준으로 유사 문항을 찾으면 그 문항의 정확한 등록 revision과 source-class/Graph/policy/index revision을 pin하고, 기존 similarity 결과 pointer를 Catalog DB 보관함의 가시 권한·현재 revision과 교차 검증한다. 점수는 풀이의 동일성 확률이 아니라 후보 정렬 신호로 표시하고, 근거 부족 판정과 source별 coverage를 함께 보여준다. 아직 구조화·임베딩되지 않은 legacy 원본 HWP에는 점수를 계산한 것처럼 표시하지 않는다. 해당 문항은 `유사도 준비 전`으로 두고, 검증된 추출·승격 후 기존 incremental embedding publication 경계로 편입한다. GPU INDEX/QUERY의 현재 pin을 변경하지 않고, GPU 부재 시 기존 CPU fallback 정책만 적용한다.

Scientific Studio에는 일반 사용자가 이해할 수 있는 **`DB`** 메뉴를 별도로 둔다. 기존 `Graph 문항은행`의 기출 occurrence 조회와 섞지 않고, `DB` 목록에서 제목·단원·출처·교정 상태와 5자리 고유번호로 찾고 여러 문항을 선택해 순서를 지정할 수 있게 한다. 선택 목록은 브라우저의 임시 ID 문자열 배열이 아니라 서버가 검증한 `(source namespace, external U, exact source revision/해시)` 또는 승격된 `(item_id, item_revision_id, manifest hash)`의 ordered snapshot이다. 다른 사람의 선택과 섞이지 않게 사용자/권한과 idempotency를 고정한다. 기본 화면에는 내부 ID나 batch 정보를 표시하지 않는다.

최종 검색 경험은 현재 별도 화면의 **기출 검색도 DB 안으로 통합**한다. 첫 source-only 배포가 곧 통합 완료는 아니다. `EXTERNAL_SOURCE`, `PAST_EXAM`, `CREATED` 판별형을 동일한 사용자 검색 계약으로 묶되, 각 source class의 정본·승인·Graph occurrence·원본 페이지·풀이보고서·유사도 coverage를 지우거나 서로 다른 의미의 점수를 하나로 가장하지 않는다. 공통 필터는 교육과정·영역·자료형·난이도 등 실제 교집합에서 시작하고, source별 고유 필드는 명시적 네임스페이스/능력으로 확장한다. **기출·창작의 교육과정/개념/근거 검색은 반드시 현행 고정 Graph Snapshot의 기존 Catalog read/retrieval application을 통과한다.** SQL 원본 메타데이터 필터와 U 고유번호 exact lookup은 Graph를 대체하는 별도 의미 검색이 아니라, 후보를 정확한 원본 revision으로 제한·검증하는 보조 조회다. 기존 Graph 검색 구현과 검증된 retrieval/read contract를 내부 어댑터로 재사용하며 병렬 검색 DB를 만들지 않는다. 한 화면의 결과를 섞기 전에 권한·고정 revision·정렬 안정성·중복 문항 식별·N+1/지연을 테스트하고, 기존 기출 검색 화면은 전환 기간 동안 유지한다. 개선된 DB 검색이 기능·품질 모두를 대체한다는 운영 증거가 생기기 전에는 기존 경로를 제거하지 않는다.

### Graph 검색과 창작 게시의 정확한 경계

현재 운영 Graph ontology는 `APPROVED_ITEM_REVISION`의 승인된 분석을 `APPROVED_ITEM` 또는 `PAST_EXAM` source class로 게시한다. 후자는 실제 기출 occurrence pointer가 있어야 하고, 전자는 occurrence를 만들지 않는다. 따라서 `창작`은 사용자에게 보이는 출처 분류로 먼저 정의한다. 원본의 기출변형/자유출제 메타데이터와 검증된 `ItemOriginProfile`의 제작 방식·원본 관계를 연결하되, Graph에서는 기존 `APPROVED_ITEM` layer를 사용한다. 새 `창작` Graph enum이나 기출 occurrence를 임의로 만들지 않는다. `APPROVED_ITEM`만으로 사용자 분류를 정확히 표현하지 못한다는 실제 사례가 확인될 때에만 정책·ontology successor를 제안한다.

오늘 업로드한 XLSX/ZIP은 아직 **source-only 원본**이다. 각 행의 2/3교 파일은 내용을 읽고 풀어 검증하기 전까지 `APPROVED_ITEM_REVISION`도 `accepted Knowledge Analysis`도 아니다. 그러므로 원본 행은 Catalog의 exact metadata 검색에서 `Graph 미게시`로 표시하고, Graph 교육과정/개념 검색 결과 또는 검증된 근거로 위장하지 않는다. 검색 계약은 source type과 `graph_state=NOT_PUBLISHED|PUBLISHED`를 분리해 표현한다. Graph 후보가 필요한 질의는 Graph가 없으면 명시적으로 coverage 없음으로 끝나야 한다. 해당 조건을 SQL 태그 유사도나 파일명 매치로 몰래 대체하지 않는다.

승격 경로는 행/파일의 고정 revision·hash 확인 → HWP/HWPX의 신뢰할 수 있는 문항 단위 추출 → 실제 풀이와 정답/해설 검증을 포함한 Codex 제안 → 사람 또는 이미 승인된 정책에 의한 Item acceptance → 정본 Item Revision/Origin profile 등록 → 기존 `APPROVED_ITEM_REVISION` Knowledge Analysis → 출처를 검증한 Catalog 경계에서 `APPROVED_ITEM` Graph 공통 publisher 재사용 및 창작 source에 맞는 additive 풀이보고서 successor다. 기존 기출 학습처럼 Graph 게시는 accepted base analysis가 있으면 풀이보고서보다 먼저 가능하되, 이번 창작 학습 전체의 완료에는 두 결과가 모두 필요하다. 풀이보고서는 검증 가능한 풀이 단계·출처·출제요소 연결을 담는 결과 Artifact이며 내부 사고 과정의 원문을 요구하지 않는다. 정확한 Item Revision, accepted base analysis, solution-report Artifact, Graph publication을 각각 pin한다. 보고서가 아직 없으면 `GRAPH_PUBLISHED`와 `SOLUTION_REPORT_PENDING`을 혼동하지 않는다. 중복/실패는 기존 accepted successor uniqueness·멱등·immutable history를 따른다.

기술적으로 현재 `knowledge-analysis-request/10.0`은 기출의 `knowledge-analysis-request/9.0` 시각 분석, 문제지/해설지 페이지 anchor와 `PAST_EXAM` source를 요구한다. 창작 문항의 기존 base analysis는 `APPROVED_ITEM`이고 이 시각 기출 pointer가 없다. 따라서 V10의 schema bytes나 저장 결과를 바꾸지 않는다. 창작 풀이보고서 successor는 동일한 풀이 단계·선지 진단·개념 출제 연결·해설 비교 의미를 재사용하되, anchor authority를 승인 Item Content, 원본 HWP/HWPX의 검증된 위치, 등록/검토 solution receipt로 교체한다. `답지 없음`이나 출처 미확인 항목은 명시적 상태로 기록하고, 없는 기출 페이지를 만들지 않는다. JSON Schema 2020-12를 먼저 정의하고 Pydantic/worker proposal/accepted-result/unique successor/조회 계약을 같은 의미로 확장한 뒤에만 실행한다.

현행 `ordinary_item_graph_publication_service`는 EOM authoring/review/registration Workflow의 성공한 role result와 검토 receipt를 요구한다. 이번 HWP/HWPX 원본에서 승격한 Item에는 그 이력이 존재하지 않으므로 이를 가짜로 만들거나 검사를 우회하지 않는다. 새 **창작 출처 검증 application 경계**가 원본 외부 U·source revision·파일 Artifact·구조화 추출/승인·Item Origin profile·accepted 분석을 reauthorize한 뒤, 내부에서는 기존 `AutomaticItemGraphPublicationService`와 Graph snapshot CAS/idempotency를 재사용한다. 풀이보고서는 그 exact accepted 분석의 additive successor로 따로 검증한다. 기존 ordinary/기출/25문항 publisher의 계약은 그대로 유지한다.

주 조회는 Graph Snapshot→승인 분석/Item node/교육과정 edge의 인덱스 탐색과, external `(namespace,U)`/current revision의 B-tree lookup이다. 공통 결과는 bounded page와 typed pointer만 materialize한다. 원본 1,297행부터 수십만 행까지도 Graph snapshot pin·권한 검증·keyset pagination을 유지하고, 임의 A:AF 문자열 포함 필터는 별도 비용을 측정한다. Publication은 Catalog application/Orchestrator의 기존 CAS·receipt 경계를 사용하며 worker는 NAS/DB에 직접 쓰지 않는다. 직접 Graph 테이블 INSERT나 원본 행을 근거 node로 복사하는 단순안은 현재 source-class/acceptance/anchor 규칙을 깨므로 배제한다.

`DB → 엑셀 내보내기`는 현재 필터 결과의 **권한 검증된 단일 SQL 조회 스냅샷**을 XLSX로 만든다. 첫 시트는 출처 종류·표시 고유번호·제목·단원·교정/승인 상태·원본 파일명 등 공통 목록이다. legacy 행은 별도 `원본 메타데이터` 시트에 A:AF 32열의 원값(공백 포함)과 원본 시트·행 번호를 보존한다. 기출·생성 문항의 메타데이터는 각 source class와 provenance를 구분하고 legacy 열에 억지로 채우지 않는다. 엑셀 수식으로 해석될 수 있는 외부 텍스트는 수식이 아닌 문자열로 내보내고, NAS 경로·내부 다운로드 토큰·비밀값을 넣지 않는다. 첫 단계는 현재 1,297행에 맞춰 2,000행·원문 텍스트 24 MiB·출력 16 MiB 상한의 **비정본 일회성 HTTP 다운로드**로 제한한다. 원본은 여전히 Intake Artifact이며, 파생 XLSX는 DB나 NAS의 새 정본으로 보관하지 않는다. 단일 SQL statement가 필터와 A:AF를 함께 읽고 결과 해시를 응답과 BFF에서 검증한다. 이 상한을 넘는 규모에서만 비동기 Artifact delivery successor를 별도로 도입한다. 현재 구현은 legacy 원본 행의 필터 결과 내보내기이며, 기출·생성·사용자 선택 집합을 함께 내보내는 기능은 공통 DB read model 이후로 분리한다.

사용자가 확정한 배치의 출력은 **선택한 기출·생성·기존 등록 문항의 한글 파일을 지정 순서대로 이어 붙인 HWPX 한 개**다. 따라서 `DB` 선택은 source-only 원본까지 포함하는 버전 고정 ordered selection을 만들고, 이 선택을 실제 합본 HWPX delivery로 연결해야 한다. 원본 HWP/HWPX를 정본 `Item Revision`에 억지로 끼워 넣지 않으며, 기존 25문항 모의고사 정책을 임의 개수의 DB 선택에 적용하지 않는다. 대신 기존 Catalog의 원본/Item pointer 검증, Assessment Assembly의 불변 ordered placement·멱등·권한 원칙, HWPX Manager/Builder의 검증·NAS commit 경계를 재사용하는 **curated-document-assembly successor**를 정의한다. 각 placement는 `REGISTERED_ITEM_REVISION`, `PAST_EXAM_ITEM_REVISION`, `EXTERNAL_SOURCE_DOCUMENT`의 판별형과 정확한 Artifact Revision/해시·입력 형식을 고정한다. 그 source class는 정본 Item 여부를 속이지 않는다.

출력 단계는 각 placement의 한글 원본을 검증된 HWPX segment로 정규화한 뒤 순서대로 하나의 HWPX package로 합친다. 기존 `content_team_exam_renderer._merge_item_packages`는 같은 EOM 템플릿에서 만든 package의 공유 header 구조를 전제로 하므로 임의 HWPX 파일에 그대로 쓰면 안 된다. 그 안의 ZIP/section/media/reference 검증·자원 ID 재매핑 소유권은 재사용하되, 서로 다른 header/style/page setting을 가진 package를 안전하게 합치는 후속 renderer contract와 격리 Builder를 둔다. 합본은 모든 내부 이미지 relationship, 수식·표·section 순서, 실제 압축 멤버와 다운로드 hash를 검증한다.

2026-10-27 격리 임시 폴더에서 N제 원본 HWPX 네 개를 실제로 열어 합본기에 대입한 결과, `10991`(`sha256:736a722f9f1dda7f8cc05c862745e67c69cdaaf6d4717ffa25995d15ac251e99`)과 `11436`(`sha256:abad699d2ea599d5612561094cdb5c46cddd328543d54310471ed7d742d56f9b`)은 header skeleton이 같아도 교차 style ID 재매핑이 필요해 현행 합본기가 거부했다. `11763`(`sha256:d204fc709292fddf2c0d8873f5af3693f0d65d05ceb4821556c9b63e38b23468`)과 `10513`(`sha256:7a7208eb33281209c8cb6f11ff040bb7a161bfd805fb945e5775ea9654b861ef`)은 header skeleton부터 다르다. 네 파일의 `version.xml`·`settings.xml` 해시도 서로 달랐다. 이는 renderer의 고장으로 분류하지 않는다. 기존 25문항 경로의 동질 패키지 계약을 유지하면서, 이질 패키지에서 style graph, section/page setting, 공용 part, 이미지·수식 relationship을 검증·정규화하는 독립 successor가 필요하다는 실제 입력 증거다. 이 표본의 실패를 무시하거나 한 package의 header/settings를 다른 문항에 강제로 적용하는 합본은 금지한다.

`curated-document-assembly-draft/1.0`은 이 다종 조립의 첫 입력 계약이다. 위치가 연속된 최대 200개의 판별형 placement를 갖고, `EXTERNAL_SOURCE_DOCUMENT`는 고정 source revision·행 관찰 해시·선택된 2/3교·탐지 형식을, `REGISTERED_ITEM_REVISION`과 `PAST_EXAM_ITEM_REVISION`은 고정 Item revision·manifest 해시·Graph snapshot revision/해시를 갖는다. 동일 외부 source 또는 Item revision은 초안에 중복 담지 않는다. 화면 초안은 브라우저 메모리에만 머물며 서버 정본·승인·HWPX 출력이 아니다. 따라서 초안을 받은 후속 application은 실행 직전 각 포인터의 현재 자격·권한·Artifact Revision/해시·media type을 다시 해석하고, 그 결과를 불변 조립 manifest에 pin해야 한다. 화면에 임의 내부 ID 입력란을 추가하지 않는다. 이 입력 계약과 화면 선택만으로 합본 기능을 완료했다고 판정하지 않는다.

`curated-document-assembly-manifest/1.0`은 초안 다음의 **입력 고정** 계약으로 추가됐다. source-only placement는 원본 U·source revision·관찰 해시 외에 실제 Content Intake source-file의 Artifact ID·Revision·멤버·media type·크기·SHA를 pin한다. 기출/창작 정본 placement는 기존 Item Revision manifest와 Graph Snapshot의 정확한 hash를 pin한다. 연속된 순서와 중복 금지, HWP/HWPX 탐지 형식↔media 일치, 전체 manifest hash를 JSON Schema 2020-12와 Pydantic으로 검증한다. 이 manifest는 source 현재성·사용자 권한·실제 Artifact 멤버를 Catalog application이 다시 확인한 뒤에만 작성할 수 있다. manifest가 유효해도 변환·이질 package 합본·Hancom 편집 품질·HWPX 출력이 성공했다고 표시하지 않는다. 조립 실행 및 불변 출력 receipt는 별도 후속 경계다.

저장된 조립 입력의 목록·재열기는 Catalog의 같은 application 경계에서 제공한다. 정본은 새 파일이나 브라우저 저장소가 아닌 `curated_document_assemblies`의 current pointer와 immutable revision manifest다. 읽기는 현재 로그인한 operator를 DB에서 재확인하고 해당 operator가 만든 조립만 공개하며, 상세는 manifest schema/hash와 placement 인덱스를 재검증한다. 목록은 `(created_by, created_at DESC, assembly_id DESC)` 인덱스와 keyset cursor로 작은 페이지를 조회하고, 상세는 assembly ID/current revision의 키 조회를 사용한다. 최대 200 placement의 manifest 검증은 O(k), 목록 페이지는 O(log n + page size)다. 읽기는 부작용·새 Artifact가 없으며 삭제·수정되지 않은 historical revision을 latest로 치환하지 않는다. 단순 브라우저 localStorage만 쓰는 방법은 다른 기기와 재전송 복구가 안 되고 서버의 고정 입력 정본이 될 수 없어 배제한다. 목록/상세가 준비되기 전에는 GUI의 임시 선택을 영속 저장 완료로 표시하지 않는다.

현재 Catalog의 정본 Item 입력 해석은 정확한 Item revision/manifest hash와 활성 Graph snapshot revision/hash/ontology를 확인하고, `APPROVED_ITEM`과 `PAST_EXAM`의 source pointer를 혼동하지 않는다. 기출은 동일 analysis run의 typed examination occurrence가 있어야 하며, 일반 등록 Item에 occurrence가 붙어 있으면 거부한다. 최대 200개 Item 입력은 Item·Graph source·occurrence를 각각 배치 조회하고 기존 `(snapshot, stable_key)` 등 인덱스 키를 사용한다. 200개 합성 입력에서도 DB 조회 횟수가 입력 수에 비례하지 않는 소스 테스트를 추가했다. 실제 운영 query plan·동시성은 배포 전 disposable PostgreSQL에서 별도 확인한다. 이 검증은 아직 조립 요청 저장이나 HWPX 빌드의 운영 활성화를 뜻하지 않는다. 최종 실행 시에는 같은 권한·포인터를 다시 확인한다.

조립 초안→입력 manifest의 Catalog 합성 함수는 실제 operator의 문항 읽기·출판물 생성 권한, 원본이 포함되면 Intake 읽기 권한을 먼저 확인한다. 이어 Graph 정본 문항은 묶어서, 원본 파일은 source ID 순서로 포인터와 바이트 해시를 확인한 뒤 사용자가 지정한 배치 순서를 복원한다. 이 함수의 출력은 아직 **commit 전 값**이며, 공식 Assembly Revision/Artifact·멱등 저장과 HWPX 조립은 다음 application 경계에서 연결한다. 화면 초안을 곧바로 결과물로 표시하지 않는다.

### 혼합 조립 저장 경계의 선행 설계

기존 `assessment_assemblies`는 시험 `AssessmentForm`에 1:1로 연결되고 `assessment_item_placements`의 모든 배치가 정본 `Item Revision` FK를 요구한다. 원본 Office 파일만 있는 배치를 이 테이블에 넣으면 가짜 Item을 만들어야 하므로 사용하지 않는다. Catalog 소유의 `curated_document_assemblies`/불변 revision/typed placement successor를 같은 Assembly 개념의 별도 profile로 둔다. 기존 시험 Assembly의 행·manifest·의미는 바꾸지 않는다.

- **정본·식별자·포인터:** 사용자의 확정 요청은 `(actor, idempotency key, draft hash)`에 묶는다. 논리 `assembly_id`와 불변 `assembly_revision_id`는 따로 발급하며, 정본 입력은 검증된 `curated-document-assembly-manifest/1.0`이다. 큰 문서 파일은 기존 Intake/Item Artifact에 한 번만 남는다. DB의 typed placement 행은 조회·FK·중복 방지용 파생 인덱스이며 manifest와 반드시 대조한다.
- **주 접근과 규모:** actor+key의 멱등 조회, assembly revision의 순서 조회, source 또는 Item revision의 역추적이 중심이다. 한 조립은 최대 200배치이고 초기 약 1천 원본에서 장기 수십만 source를 가정한다. unique/B-tree key lookup은 O(log n), 배치 조회·manifest 직렬화는 O(배치 수), 저장 공간도 O(배치 수)다. 원본 바이트를 DB나 새 조립 폴더에 복사하지 않는다.
- **트랜잭션·권한·실패:** 실제 로그인 actor의 `ITEM_READ + DELIVERABLE_CREATE`, 원본 포함 시 `CONTENT_INTAKE_READ`를 요구한다. Catalog transaction에서 현재 Graph/Item/source를 일정한 lock 순서로 재인가·해시 검증하고, 하나의 assembly revision과 placement를 원자적으로 기록한다. 동일 key+동일 draft는 기존 revision을 돌려주고 key+다른 draft는 충돌한다. commit 후 HWPX 변환·합본은 **별도** idempotent build/Artifact 경계이며 변환 실패를 저장된 조립의 성공 HWPX로 표시하지 않는다. 읽기·빌드 때 권한과 pin된 Artifact member/hash를 다시 확인한다.
- **의존·대안:** Web/API는 typed 명령, Catalog application은 결정과 영속화, HWPX Manager/격리 Builder는 변환·합본, Orchestrator/Artifact owner는 검증 결과 commit을 담당한다. 기존 시험 Assembly를 느슨하게 만들어 source-only를 끼우는 더 짧은 안은 Item FK·시험 Form·25문항 정책을 깨므로 배제한다. JSON manifest만 파일로 저장하고 별도 DB identity/unique key를 두지 않는 안은 중복 제출·권한 철회·조회 및 중단 복구를 보장하지 못한다.

private Catalog 생성 명령은 API가 이미 인증한 `operator_id + session_id + request_id + authentication_time`과 draft, idempotency key만 전달한다. 브라우저나 worker가 권한 목록을 제시하지 못하며, Catalog는 해당 운영자의 현재 활성 상태·비밀번호 변경 요구·DB의 실제 권한을 같은 저장 트랜잭션에서 다시 조회한다. 명령·응답은 각각 JSON Schema 2020-12와 Pydantic으로 검증하고, 응답의 성공값은 HWPX가 아닌 고정 입력 manifest다. 더 단순한 actor ID 단독 명령은 원래 API 인증 세션/요청을 감사 기록에 연결하기 어렵고, 반대로 클라이언트가 보낸 permissions를 믿는 방식은 역할 변경 후 권한을 넓힐 수 있어 배제한다.

Catalog의 `resolve_curated_external_document`는 source-only 배치 항목에 대해 현재 source 행을 공유 잠금으로 확인하고 정확한 2/3교 연결·관찰 해시·탐지 media type을 대조한다. 이어 기존 verified Artifact-member reader가 멤버 해시를 검증한 결과만 위 manifest의 외부 문서 placement로 만든다. 정본 Item·Graph 포인터는 별도로 재인가하고 세 종류 placement를 입력 순서대로 합성한다. `20261027_0061`은 이 입력 manifest의 논리 Assembly·불변 revision·typed placement와 actor별 idempotency key를 저장하는 후보 migration이며, 배포 운영 계약은 기존 `release-operator-context/1.9`를 변경하지 않고 `1.10`으로 확장한다. 이후 저장본을 계정별로 조회하는 인덱스는 기존 migration 바이트를 바꾸지 않고 `20261027_0062` 및 `release-operator-context/1.11`에 추가한다. Catalog private 생성·목록·상세와 API/Web 저장 경계 및 GUI 저장·재열기는 소스에서 연결됐다. 실제 Builder/출력 receipt는 아직 연결되지 않았으므로, 이 단계는 HWPX 합본 완료가 아니라 고정 입력 저장 후보다. 읽기/빌드 단계에서는 저장된 manifest와 indexed placement의 일치, 현재 권한, pin된 Artifact member/hash를 다시 확인해야 한다.

이 후보의 소스/임시 DB 게이트는 혼합 입력 resolver·영속 모델·릴리스 계약 집중 회귀 323건, disposable PostgreSQL 외부 문항/조립 검사 9건, `0061` upgrade→`0060` downgrade→`0061` upgrade 왕복을 통과했다. 임시 DB에서 revision UPDATE/DELETE 차단, source/Item 판별형 포인터 shape, actor+key 유일성 및 동시 삽입의 단일 승자를 확인했다. 운영 DB와 GPU 작업의 설치본은 이 검증으로 바뀌지 않았다.

대부분의 기존 파일은 바이너리 `.hwp`다. 이 서버에는 LibreOffice의 HWP 읽기 필터는 있으나 HWPX 출력 필터나 별도 HWP→HWPX 변환 실행 파일은 현재 확인되지 않았다. [한컴의 공식 변환기 설명](https://help.hancom.com/hoffice120/ko-KR/HwpxConverter/convert/convert.htm)은 HWP→HWPX를 지원하지만 Windows 실행 파일 예시다. [한컴 개발자 답변](https://forum.developer.hancom.com/t/hwp-hwpx-api/2980)은 서버 변환 API 지원이 보유 라이선스에 따라 다를 수 있음을 밝힌다. 현재 호스트에 한컴 변환기 또는 DocsConverter 설치·라이선스가 확인되지 않았으므로 Linux에서 편집 가능한 HWPX 변환이 가능하다고 가정하지 않는다. 격리된 실제 표본 변환과 한글 열기·레이아웃 비교에서 검증된 변환 경계만 사용한다. **사용자는 편집 가능한 합본만 허용했다.** HWP 페이지를 그림으로 넣거나 PDF 이미지로 우회하는 출력 profile은 현재 범위에서 금지한다. 변환 실패한 placement가 있으면 성공 합본 pointer를 만들지 않는다.

HWP/HWPX 화면 미리보기는 기존 Catalog의 격리된 Office→PDF 변환 경계를 재사용하고, 파생 PDF를 별도 Artifact Revision으로 연결한다. 변환 실패는 `미리보기 불가`로 표시하되 원본 다운로드와 메타데이터 조회를 계속 허용한다. 원본을 변환 PDF로 대체하거나 변환만으로 내용이 정확하다고 승인하지 않는다. 구조화된 본문·정답·해설 추출은 별도 제안/검토를 거쳐 기존 `AssessmentItemContent` 계약과 Registry 등록·승인 상태기계를 통과한다. source-only 문항을 HWPX 빌드·GraphRAG·유사도·출판 대상으로 자동 포함하지 않는다.

### 원본 문서 미리보기의 파생 Artifact 결정

- **책임·정본:** Catalog application만 현재 `(source_id, source_revision_id, edition)`을 재확인하고 해당 Content Intake source-file의 정확한 Artifact Revision/member/media/size/hash를 연다. 정본 원본은 Intake에 한 개만 남긴다. 변환용 로컬 복사는 임시 workspace이며, `external-item-preview-manifest/1.0`과 PDF만 새 Artifact에 commit한다. 원본 HWP/HWPX 바이트를 파생 Artifact에 다시 넣지 않는다.
- **식별자·해석:** manifest는 원본 source/file/Artifact의 고정 포인터, 입력 hash, 실제 탐지 형식, PDF member/hash/size, 변환기 종류·버전·실행 파일 hash를 담는다. 현재 source revision이 달라졌거나 원본 member가 stale/누락/변조되면 PDF가 이미 있어도 fail-closed한다. 파생 PDF는 정본 Item Revision이나 교육적 승인 증거가 아니다.
- **접근·자료구조:** 자주 쓰는 경로는 키 조회 `(source_id, current_revision_id)`와 `(source_revision_id, edition)`, 이어서 파생물의 idempotency key 조회다. 기존 B-tree/unique key와 immutable Artifact manifest를 재사용한다. 사용자는 한 번에 한 문항의 bounded PDF를 읽으며, 목록 조회는 원본/파생 바이트를 열지 않는다. 파생물 조회는 O(log n), 실제 스트리밍은 O(PDF 크기), 동시 빌드의 임시 공간은 요청당 원본+PDF 상한 안이다. 수십만 문항까지 늘어도 전체 파일 스캔으로 조회하지 않는다.
- **트랜잭션·재시도:** 변환은 현재 Catalog application의 별도 bounded 작업으로 실행하고, 원본 포인터와 변환기 profile이 같은 정확한 요청에 기존 Catalog idempotency/unique job 경계를 적용한다. `CREATED` 상태의 동일 요청만 지원된 재시도로 복구하며, 성공 파생물을 덮어쓰지 않는다. 실패하면 원본 조회·다운로드는 그대로 되고, 실패 이력은 보존한다. 병렬 요청이 서로 다른 PDF를 같은 revision으로 승격하지 못하게 한다.
- **의존 방향·대안:** API/Web은 인증된 사용자의 `ITEM_READ`·`CONTENT_INTAKE_READ`를 확인한 뒤 source/revision/edition만 넘기고 PDF를 같은 origin에서 제공한다. 변환·NAS·DB 해석은 Catalog adapter에만 둔다. 기존 자료 검토 `OfficeDocumentReviewIntakeService.ingest()`를 그대로 호출하는 간단한 방법은 동일 원본을 다시 commit하고 문서 검토용 source schema에 묶이므로 채택하지 않는다. 임의 HWP/HWPX의 브라우저 직접 렌더링도 신뢰할 수 있는 편집/표시 경계가 아니다.

## 7. 트랜잭션·보안·재시도

ZIP은 전체 압축해제를 금지한다. 경로 탈출, symlink, Mac 메타파일, 중복 entry, 압축 폭탄, 확장자·magic 불일치, Office 외부 링크/매크로를 검증한다. 허용된 멤버만 bounded streaming으로 로컬 staging에 materialize하고, worker에게 ZIP/NAS 마운트를 주지 않는다. 검증된 Artifact commit은 기존 Orchestrator/Catalog owner만 수행한다.

Import Run은 workbook revision + archive revision + mapping revision + namespace의 고정 조합으로 멱등화한다. 행은 `(import revision, sheet, row)`로, 채택된 외부 문항은 `(namespace, U)`로 uniqueness를 보장한다. 같은 입력의 replay는 같은 결과를 반환하고 hash 충돌/수정 입력은 새 revision 또는 conflict다. 파일 commit 중단 시 정확한 immutable receipt를 조회해 복구하고, 처리 여부가 불명확하면 새 identity로 재제출하지 않는다. 행 제안과 결정은 append-only로 보존한다. canonical source pointer/hash/권한 검증이 실패하면 해당 행만 격리하고 다른 행의 완료를 성공으로 꾸미지 않는다.

원본 파일과 출제자 등 개인정보성 메타데이터는 실제 로그인 권한에 따라 조회한다. 다운로드는 인증·권한·sha256/size/member 검증 후 같은 origin의 임시 응답으로 제공한다. 공개 URL이나 NAS 경로 노출은 금지한다.

### 원본 다운로드의 교차 서비스 계약 결정

`Application API`는 실제 로그인 사용자의 `ITEM_READ`와 `CONTENT_INTAKE_READ`를 확인하고, `source_id + 고정 source_revision_id + 교정 단계`만 Catalog의 기존 private application socket으로 넘긴다. 임의 파일 경로·Artifact ID·멤버명은 브라우저 입력으로 받지 않는다. Catalog는 현재 source pointer와 완료된 import, 해당 교정본의 source-file/Artifact Revision/manifest member/크기/hash/media type을 다시 확인하고 100 MiB 이하의 검증된 파일 descriptor만 스트리밍한다. `.hwp` 이름의 HWPX는 원래 이름을 출처 메타데이터에 남기되 다운로드 이름과 Content-Type은 탐지한 HWPX 형식으로 지정한다. 대상이 바뀌었거나 source-file 권한·lifecycle이 유효하지 않으면 `latest`로 대체하지 않고 안정된 오류를 돌려준다. 이 경계는 기존 Item image media를 HWP 다운로드인 척 재사용하지 않고, `external-item-document-media/1.0`의 별도 요청/응답 계약으로 추가한다. 주 접근은 `(source_id, current_revision_id)`와 `(source_revision_id, edition)`의 indexed lookup이고 O(log n)이며, 본문 바이트는 디스크→socket→HTTP의 bounded streaming 외에는 복제하지 않는다. 더 단순한 API 직통 NAS 읽기는 API 격리와 pointer 검증 소유권을 깨므로 채택하지 않는다.

## 8. 구현 순서와 종료 게이트

1. **고정·대조**: 엑셀을 immutable Intake로, ZIP을 해시 고정 운송 봉투로, 허용된 문서 멤버를 제한 크기의 여러 Intake로 나눌 설계·권한·용량을 확인한다. 원본 hash/manifest, 1,297행/32열, 1,067 최종본 후보와 14 예외의 read-only inventory를 재현한다. 운영 commit 전에는 계획과 fixture만 다룬다.
2. **계약·어댑터**: schema-first로 매핑/행/파일/결정 DTO를 정의한다. 기존 안전한 XLSX 파서와 Artifact/Office 경계를 재사용하고 ZIP 멤버 선택 어댑터를 더한다. Unicode/URL/확장자/magic 문제와 모든 셀 원값 보존을 테스트한다.
3. **제안·결정 저장**: Catalog application의 import proposal/decision/read use case와 필요한 additive DB migration을 작성한다. raw row 스냅샷 하나와 pointer만 저장한다. 14 예외는 UI에서 해결 전까지 `CONFLICT/UNRESOLVED`로 유지한다.
4. **조회·내보내기·유사도 화면**: 기존 보관함에 source-only 목록·상세·필터·파일명 링크·원본 다운로드·미리보기 상태를 붙인다. 검색 결과/선택 문항의 XLSX 내보내기를 권한·행 상한·고정 스냅샷과 함께 제공한다. 기존 similarity query 경계에서 지원되는 등록 revision은 유사 문항 검색을 제공하고, 미지원 source-only 문항은 이유를 표시한다. 사용자 화면에는 내부 ID/경로를 기본 노출하지 않는다. 정본 Item이 없음을 명확히 보인다.
5. **다종 문항 합본 경계**: 세 source class의 exact pointer를 받는 ordered Assembly successor와 Builder handoff를 정의한다. HWP→HWPX 및 이질적인 HWPX package 병합을 각각 격리 표본으로 검증하고, 실제로 지원되는 경로만 운영에 연다. 정본 구조화 추출·승격은 별도의 목적이며 합본 다운로드를 위해 가짜 정본 Item을 만들지 않는다.
6. **정본 승격·창작 Graph 경계**: 원본 교정본 내용에서 구조화 문항이 검증된 건에만 공식 import workflow와 Registry registration/승인 명령을 연결한다. `창작` provenance를 고정한 승인 Item에는 기존 분석과 창작용 풀이보고서 successor를 수행하고 출처 검증 successor에서 기존 Graph 공통 publisher로 게시한다. 기존 V10이나 ordinary-item workflow receipt를 창작에 재해석하지 않는다. 기존 생성 문항, 기출 Item, 상품 Usage를 섞거나 가짜 workflow/Graph occurrence를 만들지 않는다. 게시 전·후 같은 DB 질의에서 Graph coverage와 정확한 source/Item revision이 일치하는지 검증한다.
7. **검증·운영 rollout**: source parser·pointer·RBAC·멱등·동시성·중단/재개·마이그레이션을 unit 및 disposable PostgreSQL에서 검증한다. 실제 파일은 소수 표본(정상 HWP/HWPX, 동일 바이트 중복, 형식 불일치, 누락, 2교 최종)을 먼저 등록·조회·다운로드/미리보기 검증하고, 그다음 1,053 연결 후보를 bounded chunk로 진행한다. 14 예외와 230 비최종/반려 행의 보존·격리 결과도 reconciliation에 포함한다. 기존 유사도 경로에서 등록 문항의 정확한 revision·권한·coverage·점수 표현과 source-only 미지원 표시를 검증한다. 이어 기출·창작 검색이 기존 Graph 조회를 통과하고 원본 전용 행이 Graph 결과에 섞이지 않음을 확인한다. 승인·풀이보고서·Graph 게시가 끝난 창작 표본은 정확한 revision/hash/Graph snapshot 및 재전송 멱등성을 검증한다. 이후 기출·생성·기존 등록 문항을 섞은 순서 고정 합본 HWPX의 원본 media embedding, package reference, 실제 한글 열기와 download SHA를 검증한다. 호환 릴리스로 운영 DB migration → API/Catalog/HWPX/Web을 순서대로 반영하고 실제 HTTPS 브라우저·인증 다운로드·엑셀/합본 hash를 확인한다. 백업/rollback은 source activation과 새 조회 경로만 되돌리고 이미 생성된 불변 Artifact/감사 기록은 삭제하지 않는다.

완료 증거: 원본 workbook/ZIP hash, 모든 1,297행과 A:AF 값의 원본 대비 hash 일치, 각 교정본의 정확한 파일 Artifact pointer, `1,053 resolved candidate / 14 unresolved`의 실제 검토 후 재집계, 중복 Item 0, 원본/파생 파일 다운로드 hash 일치, XLSX export의 동일 행/원값/권한/해시 검증, 조회 성능 query plan, 기존 Item/Graph/HWPX 경로 회귀 PASS. 실제 교육적 정확성·구조화 추출 품질은 별도 검토 결과로 기록한다.

### 가져오기 사후 감사 경계

Catalog의 읽기 전용 `external-items verify --import-id`는 **로컬 staging 파일이 아니라** import가 pin한 NAS workbook Artifact Revision을 검증해 다시 해독한다. 그 A:AF 행·행 번호·U·관찰 해시·검색 facet을 같은 import의 불변 source revision과 순서대로 대조하고, L/M/N에 원래 링크가 있던 교정 단계와 등록된 edition 관찰 수, 선택 문서와 Intake source-file 해시 관계를 확인한다. `import_id` 및 `(import_id,row_number)` 인덱스 조회와 정렬된 일대일 순회가 중심이며 시간 O(행+교정 링크), 메모리 O(행+링크)다. 현재 최대 1,297행에서는 원본 XLSX 파서의 bounded 메모리 모델을 재사용한다. 이것은 새로운 권위 데이터나 저장 테이블을 만들지 않고, 원본 바이트가 달라졌거나 DB 관찰이 달라지면 실패한다. 원본 문서 1,087개의 실제 바이트를 모두 다시 읽는 전수 NAS 무결성 검사나 교육적 품질 검토를 대신하지 않는다.

## 9. 창작 Graph 적합성·게시 게이트

### 격리된 창작 풀이 입력의 단계적 활성화 경계

`external-item-learning` V27은 승인 Item이나 Graph 게시가 아니라, 원본의 고정된 페이지를 코덱스가 독립적으로 풀어 보는 **제안 단계**다. 정본은 Catalog의 source revision과 Orchestrator가 발행한 page-set Artifact revision이며, 실행 계획은 이 둘의 ID·revision·hash 및 정확한 페이지 순서를 pin한다. Worker에게 원본 HWP/PDF나 NAS 경로를 주지 않고, Orchestrator가 발행된 PNG·manifest만 로컬 작업공간에 검증 후 적재한다. 원본 사용 권한 재확인은 Catalog application의 책임이며, Orchestrator의 파일 검증은 그 권한 판정을 대체하지 않는다.

주 접근은 source revision의 키 조회, 발행 Artifact의 immutable revision 조회, 순서 고정 페이지 반복이다. 기존 ID 인덱스와 typed manifest를 재사용하며 페이지 수에 선형 시간·입력 크기만큼의 일시 공간이 든다. 새 검색 DB나 worker의 직접 NAS 접근은 필요 없다. 발행·plan·claim은 기존 트랜잭션/멱등 경계를 사용하고, 실패한 실행은 이력 그대로 보존한다. 재시도도 동일 pin을 재검증하며 현재 버전으로 바꾸지 않는다. 단순히 원본 PDF를 worker에게 복사하는 방법은 원본 권한·페이지 선택·해시 경계를 우회하므로 사용하지 않는다. V27 materializer의 지원만으로 실행을 열지 않으며, source 재인가·정확한 page Artifact allowlist·결과 검증·승격 경계가 이어지기 전에는 `CONTROL_CREATIVE_LEARNING_NOT_ACTIVATED`를 유지한다.

구체적인 출처·풀이보고서 successor·게시 경계는 [창작 문항 풀이보고서·Graph 게시 후속 계약](CREATED_ITEM_GRAPH_AND_SOLUTION_REPORT_SUCCESSOR.md)에 고정한다.

사용자가 이번 작업의 종료 범위로 지정한 검토와 게시다. 기존 시스템에서 기출변형 및 자유출제로 **생성·등록된 정본 문항**의 사용자 명칭을 `창작`으로 둔다. 이번 N제 ZIP에서 가져온 **원본 파일만 있는 source-only 행**도 메타데이터상 창작 후보이지만, 내용·승인·근거가 검증되기 전까지 `창작` 정본 Item으로 간주하지 않는다. 현행 계약상 승인된 창작은 기존 `APPROVED_ITEM` Graph source class에 origin profile로 구분하여 게시한다. source-only 상태에서 새 Graph node/edge나 색인을 게시하지 않는다.

검토 시 정확한 Item Revision, 승인 상태, 생성/변형 원본 관계, 교육과정 태그, 풀이보고서, 근거 receipt, embedding publication pin, 접근 정책을 기존 기출 layer 계약과 대조한다. 기존 Graph·정본 Item·유사도/출제 경계를 재사용할 수 있는지, 별도 successor 계약이 필요한지, 기출과 창작을 조회·인용·학습 근거로 사용할 때 오인 위험이 없는지 판단한다. 첫 검증은 승인 창작 표본과 source-only 부정 표본을 함께 사용한다. 결과는 호환성 표, 필요한 최소 schema/policy 변경, migration·rollback·회귀 게이트와 함께 기록한다. 새 ontology는 기존 `APPROVED_ITEM`과 origin profile로 표현되지 않는 실제 사례가 입증될 때에만 검토한다.

## 10. 더 단순한 안을 채택하지 않는 이유

엑셀 행을 곧장 `items.metadata_json`에 넣고 ZIP 경로를 URL로 쓰면 구현은 짧지만, 문서가 없어도 Item이 만들어지고 교정본·원본 바이트·충돌·권한·재전송의 의미가 사라진다. 모든 HWP를 즉시 JSON으로 변환하는 방식도 표·수식·그림 손실을 정본으로 오인할 수 있다. 원본 source 기록 → 검토된 파일 대응 → 정확한 ordered document assembly → 필요한 건만 정본 승격의 경계가 기존 EOM 규칙을 가장 적게 바꾸면서 메타데이터·조회성·합본 출력을 함께 보장한다.
