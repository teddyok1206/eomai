# 기존 문항 아카이브 등록·조회 계획

상태: 단계별 구현 중인 설계 기준. 이 문서는 운영 DB 등록, 원본 파일 이동, 문항 승인, Graph 게시를 승인하거나 수행하지 않는다.

작성 기준: 2026-10-27 UTC, `staging/통합과학 DB … all.xlsx`와 `staging/N제.zip`의 읽기 전용 조사. 정확한 원본 식별자는 운영 Intake에서 파일 바이트와 SHA-256을 다시 고정한다. 이 아카이브의 `N제` 폴더명은 내보내기 경로이지 교재·상품의 정본 분류가 아니다.

## 1. 목표와 범위

기존 노션 DB에서 내보낸 엑셀의 **모든 행과 32개 열 A:AF**, 원래 셀 값과 파일 연결을 잃지 않고 EOM에서 검색·열람·엑셀 내보내기까지 제공한다. 파일 링크의 사용자 표시만 `~.hwp`/`~.hwpx` 같은 **파일명**으로 바꾼다. 실제 다운로드는 파일명이나 호스트 경로가 아닌 권한 검사를 거친 불변 Artifact pointer로 수행한다.

원본 `.hwp`/`.hwpx`를 보관·조회하는 것과 EOM의 구조화된 정본 `Item Revision`으로 승격하는 것은 별개의 단계다. 파일 하나가 존재한다는 이유로 본문·정답·해설을 추측하거나, 생성된 문항으로 가장하거나, 승인·출판 가능 상태로 표시하지 않는다. 사용자가 원한 최초 기능은 **원본과 메타데이터가 온전히 연결된 문항 보관함**이다. 자동 출제·GraphRAG·유사도 편입은 검증된 구조화 문항이 생긴 뒤 별도로 활성화한다.

## 2. 조사 기준선과 격리 대상

- 엑셀: 데이터 행 1,297개, A:AF 32열. `U=고유번호`, `L/M/N=1/2/3교`, `X=반려 여부`; 난이도 B:E/J, 배점 H, 학년 O, 단원 Q/R, 유형·분야 Y/Z, 출제일·출제자 AC/AD 등도 보존한다. U열은 1,297행 모두 비어 있지 않은 5자리 문자열이며 행 간 중복이 없다. U열에는 수식이 없고 이 시트의 별도 hyperlink element도 없다.
- 사용자가 정한 최종본 규칙을 적용하면 3교 894건, 3교가 없는 비반려 2교 173건, 합계 1,067건이 **최종본 후보**다. 반려 5건과 최종본 없는 225건도 엑셀 원본/관리자 이력으로 남기되 정본 Item으로 자동 승격하지 않는다. 1교는 언제나 초안이다.
- ZIP: 2,797,713,785 압축 바이트, 3,854,257,519 압축 해제 바이트, 17,123 entry; 전체 ZIP CRC 검사는 통과했다. SHA-256은 `e22054346d28a829817c2e941ae4cf2dd2daec09b13862c3ee7cd89240c23909`이다. 실제 문서 후보는 HWP 확장자 1,083개, HWPX 4개이며 Mac 메타파일과 symlink가 섞여 있다. 전체 ZIP을 무조건 풀면 안 된다.
- 이 1,087개 HWP/HWPX 파일명은 **모두 확장자 바로 앞에 정확한 5자리 번호**가 있다. 서로 다른 번호는 1,065개이고, 같은 번호가 여러 파일에 붙은 그룹은 17개다. 엑셀 U열은 행 고유 메타데이터로 보존한다. 파일명 번호는 행 대응의 보조 단서일 뿐이고, 중복 파일 그룹은 교정 단계·엑셀 행·파일 hash를 함께 대조할 때까지 단일 파일로 축약하지 않는다.
- 1,067개 최종본 후보 중 `고유번호 + 정규화 파일명`으로 1,043건이 단일 대응, 10건은 같은 바이트의 중복 위치, 6건은 해당 고유번호 파일 없음, 8건은 고유번호는 있으나 파일명/내용 맥락이 불일치한다. 따라서 **1,053건은 높은 신뢰도의 연결 후보, 14건은 격리**다. 파일명 일치는 승인의 증명이 아니며 Intake 시 각 멤버 해시와 문서 내용을 다시 검증한다.
- 한 `.hwp` 확장자 파일의 실제 내용은 HWPX/ZIP이며, 엑셀의 한 최종 링크는 `.ai`이지만 같은 번호의 HWP가 ZIP에 있다. 확장자를 근거로 몰래 교체하거나 `.ai`를 문항 본문으로 간주하지 않는다.
- 일부 `Grade` 값은 학년 숫자 대신 과목처럼 보이고, 일부 메타데이터는 비어 있다. 값이 비어 있거나 모호하다는 사실까지 보존하고, 빈 값을 임의 기본값으로 채우지 않는다.

## 3. 책임·정본·식별자

```text
원본 XLSX (Content Intake Artifact Revision) + ZIP 해시 고정 운송 봉투
  -> 허용된 HWP/HWPX/관련 자료 멤버만 검증·분할 Intake
  -> 버전 고정 매핑 계약 + 행/파일 대응 제안 (Catalog)
  -> 확정된 원본 문항 기록과 모든 교정본 파일 pointer (Catalog)
  -> 필요 시 문서 변환·구조화 추출 제안 (Orchestrator 경유)
  -> 검증·결정된 AssessmentItemContent + 정본 Item Revision (Item Registry)
  -> 선택적 Graph 게시·임베딩·출판
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

## 5. 파일명 표시와 대응 규칙

- GUI 링크 텍스트는 선택된 파일의 정규화된 **basename**과 실제 형식 배지만 표시한다. 링크 목적지는 EOM의 인증된 source-file download API이며, 브라우저가 파일 경로나 Artifact ID를 임의로 선택할 수 없다.
- 내부 매칭은 `source namespace + U + 검토된 교정 단계 + 정확한 member hash`를 사용한다. 파일명만 같거나 `U`만 같으면 자동 결정하지 않는다. 경로 문자열은 설명 자료이지 권위가 아니다.
- 엑셀의 원래 하이퍼링크/텍스트, URL 인코딩 값, 원래 파일명, Unicode 정규화 전후 값, ZIP 멤버 관찰, 중복 위치를 모두 보존한다. 표시명 변경은 이 출처 정보를 덮어쓰지 않는다.
- 3교가 있으면 3교가 우선이다. **3교가 있는데 파일 대응이 실패하면 2교로 조용히 대체하지 않는다.** 3교가 없고 반려되지 않은 경우에만 2교를 선택한다. 1교는 조회 가능한 초안 이력일 수 있지만 최종본이 아니다. `반려 여부`가 모호하면 자동 승인하지 않는다.
- 파일 확장자와 magic byte가 다르면 실제 media type을 기록하고 `FORMAT_MISMATCH`로 검토한다. 잘못 표기된 확장자를 원본 Artifact에서 바꾸지 않는다. `.ai`는 별도 보조 자료로만 연결하고 최종 문항 파일 대체는 명시적 결정이 필요하다.

## 6. 조회·미리보기·승격 UX

기존 문항 보관함의 Catalog read model을 확장해 `SOURCE_ONLY`와 `REGISTERED_ITEM`을 구분하는 판별 DTO를 사용한다. `SOURCE_ONLY`에도 목록 검색, 전체 32필드 상세, 최종/이전 교정본 파일명, 인증된 원본 다운로드, 변환 상태를 제공한다. 기존 `Item` 조회의 의미나 Graph 기반 기출 occurrence 조회를 바꾸지 않는다. 정본 승격 후에는 같은 외부 고유번호 source 기록에서 정확한 `item_id + item_revision_id`를 따라간다. 사용자에게 batch를 기본 노출하지 않는다.

검색: 외부 고유번호 exact lookup, 등록 상태, 단원·분야·분류·학년·출제자·날짜·난이도 필터, 생성일/고유번호 순서의 keyset pagination. 인덱스는 실제 query plan을 보고 `namespace + U` unique, 상태/단원/분야/날짜/정렬용 B-tree를 최소로 추가한다. 한 페이지의 source/file pointer를 bulk resolve해 N+1을 피한다. 예상 규모는 우선 1,297행, 이후 수십만 문항까지 확장 가능하게 bounded page와 인덱스를 사용한다. 조회 자체는 원본 파일을 매번 복사하거나 변환하지 않는다.

Scientific Studio에는 일반 사용자가 이해할 수 있는 **`DB`** 메뉴를 별도로 둔다. 기존 `Graph 문항은행`의 기출 occurrence 조회와 섞지 않고, `DB` 목록에서 고유번호·메타데이터·교정 상태로 찾고 여러 문항을 선택해 순서를 지정할 수 있게 한다. 선택 목록은 브라우저의 임시 ID 문자열 배열이 아니라 서버가 검증한 `(source namespace, external U, exact source revision/해시)` 또는 승격된 `(item_id, item_revision_id, manifest hash)`의 ordered snapshot이다. 다른 사람의 선택과 섞이지 않게 사용자/권한과 idempotency를 고정한다. 기본 화면에는 내부 ID나 batch 정보를 표시하지 않는다.

`DB → 엑셀 내보내기`는 현재 필터 결과 전체 또는 선택한 문항의 **권한 검증된 고정 조회 스냅샷**을 XLSX로 만든다. 첫 시트는 출처 종류·표시 고유번호·제목·단원·교정/승인 상태·원본 파일명·정확한 revision 등 공통 목록이다. legacy 행은 별도 `원본 메타데이터` 시트에 A:AF 32열의 원값(공백 포함)과 엑셀 출처 행을 보존한다. 기출·생성 문항의 메타데이터는 각 source class와 provenance를 구분하고 legacy 열에 억지로 채우지 않는다. 엑셀 수식으로 해석될 수 있는 외부 텍스트는 수식이 아닌 문자열로 내보내고, NAS 경로·내부 다운로드 토큰·비밀값을 넣지 않는다. 단일 HTTP 응답으로 무제한 행을 조립하지 않고 기존 Artifact delivery 경계에서 제한된 비동기 export를 생성하며, 동일 필터·정렬·권한·스냅샷·요청 키는 멱등 재전송한다. 생성된 XLSX의 manifest/hash와 인증 다운로드를 검증한다.

사용자가 확정한 배치의 출력은 **선택한 기출·생성·기존 등록 문항의 한글 파일을 지정 순서대로 이어 붙인 HWPX 한 개**다. 따라서 `DB` 선택은 source-only 원본까지 포함하는 버전 고정 ordered selection을 만들고, 이 선택을 실제 합본 HWPX delivery로 연결해야 한다. 원본 HWP/HWPX를 정본 `Item Revision`에 억지로 끼워 넣지 않으며, 기존 25문항 모의고사 정책을 임의 개수의 DB 선택에 적용하지 않는다. 대신 기존 Catalog의 원본/Item pointer 검증, Assessment Assembly의 불변 ordered placement·멱등·권한 원칙, HWPX Manager/Builder의 검증·NAS commit 경계를 재사용하는 **curated-document-assembly successor**를 정의한다. 각 placement는 `REGISTERED_ITEM_REVISION`, `PAST_EXAM_ITEM_REVISION`, `EXTERNAL_SOURCE_DOCUMENT`의 판별형과 정확한 Artifact Revision/해시·입력 형식을 고정한다. 그 source class는 정본 Item 여부를 속이지 않는다.

출력 단계는 각 placement의 한글 원본을 검증된 HWPX segment로 정규화한 뒤 순서대로 하나의 HWPX package로 합친다. 기존 `content_team_exam_renderer._merge_item_packages`는 같은 EOM 템플릿에서 만든 package의 공유 header 구조를 전제로 하므로 임의 HWPX 파일에 그대로 쓰면 안 된다. 그 안의 ZIP/section/media/reference 검증·자원 ID 재매핑 소유권은 재사용하되, 서로 다른 header/style/page setting을 가진 package를 안전하게 합치는 후속 renderer contract와 격리 Builder를 둔다. 합본은 모든 내부 이미지 relationship, 수식·표·section 순서, 실제 압축 멤버와 다운로드 hash를 검증한다.

대부분의 기존 파일은 바이너리 `.hwp`다. 이 서버에는 LibreOffice는 있으나 별도의 HWP→HWPX 변환 실행 파일은 현재 확인되지 않았다. [한컴의 공식 변환기 설명](https://help.hancom.com/hoffice120/ko-KR/HwpxConverter/convert/convert.htm)은 HWP→HWPX를 지원하지만 Windows 실행 파일 예시다. 따라서 Linux에서 편집 가능한 HWPX 변환이 가능하다고 가정하지 않는다. 격리된 실제 표본 변환과 한글 열기·레이아웃 비교에서 검증된 변환 경계만 사용한다. **사용자는 편집 가능한 합본만 허용했다.** HWP 페이지를 그림으로 넣거나 PDF 이미지로 우회하는 출력 profile은 현재 범위에서 금지한다. 변환 실패한 placement가 있으면 성공 합본 pointer를 만들지 않는다.

HWP/HWPX 화면 미리보기는 기존 Catalog의 격리된 Office→PDF 변환 경계를 재사용하고, 파생 PDF를 별도 Artifact Revision으로 연결한다. 변환 실패는 `미리보기 불가`로 표시하되 원본 다운로드와 메타데이터 조회를 계속 허용한다. 원본을 변환 PDF로 대체하거나 변환만으로 내용이 정확하다고 승인하지 않는다. 구조화된 본문·정답·해설 추출은 별도 제안/검토를 거쳐 기존 `AssessmentItemContent` 계약과 Registry 등록·승인 상태기계를 통과한다. source-only 문항을 HWPX 빌드·GraphRAG·유사도·출판 대상으로 자동 포함하지 않는다.

## 7. 트랜잭션·보안·재시도

ZIP은 전체 압축해제를 금지한다. 경로 탈출, symlink, Mac 메타파일, 중복 entry, 압축 폭탄, 확장자·magic 불일치, Office 외부 링크/매크로를 검증한다. 허용된 멤버만 bounded streaming으로 로컬 staging에 materialize하고, worker에게 ZIP/NAS 마운트를 주지 않는다. 검증된 Artifact commit은 기존 Orchestrator/Catalog owner만 수행한다.

Import Run은 workbook revision + archive revision + mapping revision + namespace의 고정 조합으로 멱등화한다. 행은 `(import revision, sheet, row)`로, 채택된 외부 문항은 `(namespace, U)`로 uniqueness를 보장한다. 같은 입력의 replay는 같은 결과를 반환하고 hash 충돌/수정 입력은 새 revision 또는 conflict다. 파일 commit 중단 시 정확한 immutable receipt를 조회해 복구하고, 처리 여부가 불명확하면 새 identity로 재제출하지 않는다. 행 제안과 결정은 append-only로 보존한다. canonical source pointer/hash/권한 검증이 실패하면 해당 행만 격리하고 다른 행의 완료를 성공으로 꾸미지 않는다.

원본 파일과 출제자 등 개인정보성 메타데이터는 실제 로그인 권한에 따라 조회한다. 다운로드는 인증·권한·sha256/size/member 검증 후 같은 origin의 임시 응답으로 제공한다. 공개 URL이나 NAS 경로 노출은 금지한다.

## 8. 구현 순서와 종료 게이트

1. **고정·대조**: 엑셀을 immutable Intake로, ZIP을 해시 고정 운송 봉투로, 허용된 문서 멤버를 제한 크기의 여러 Intake로 나눌 설계·권한·용량을 확인한다. 원본 hash/manifest, 1,297행/32열, 1,067 최종본 후보와 14 예외의 read-only inventory를 재현한다. 운영 commit 전에는 계획과 fixture만 다룬다.
2. **계약·어댑터**: schema-first로 매핑/행/파일/결정 DTO를 정의한다. 기존 안전한 XLSX 파서와 Artifact/Office 경계를 재사용하고 ZIP 멤버 선택 어댑터를 더한다. Unicode/URL/확장자/magic 문제와 모든 셀 원값 보존을 테스트한다.
3. **제안·결정 저장**: Catalog application의 import proposal/decision/read use case와 필요한 additive DB migration을 작성한다. raw row 스냅샷 하나와 pointer만 저장한다. 14 예외는 UI에서 해결 전까지 `CONFLICT/UNRESOLVED`로 유지한다.
4. **조회·내보내기 화면**: 기존 보관함에 source-only 목록·상세·필터·파일명 링크·원본 다운로드·미리보기 상태를 붙인다. 검색 결과/선택 문항의 XLSX 내보내기를 권한·행 상한·고정 스냅샷과 함께 제공한다. 사용자 화면에는 내부 ID/경로를 기본 노출하지 않는다. 정본 Item이 없음을 명확히 보인다.
5. **다종 문항 합본 경계**: 세 source class의 exact pointer를 받는 ordered Assembly successor와 Builder handoff를 정의한다. HWP→HWPX 및 이질적인 HWPX package 병합을 각각 격리 표본으로 검증하고, 실제로 지원되는 경로만 운영에 연다. 정본 구조화 추출·승격은 별도의 목적이며 합본 다운로드를 위해 가짜 정본 Item을 만들지 않는다.
6. **정본 승격 경계**: 원본 교정본 내용에서 구조화 문항이 검증된 건에만 공식 import workflow와 Registry registration/승인 명령을 연결한다. 기존 생성 문항, 기출 Item, 상품 Usage를 섞거나 가짜 workflow/Graph occurrence를 만들지 않는다.
7. **검증·운영 rollout**: source parser·pointer·RBAC·멱등·동시성·중단/재개·마이그레이션을 unit 및 disposable PostgreSQL에서 검증한다. 실제 파일은 소수 표본(정상 HWP/HWPX, 동일 바이트 중복, 형식 불일치, 누락, 2교 최종)을 먼저 등록·조회·다운로드/미리보기 검증하고, 그다음 1,053 연결 후보를 bounded chunk로 진행한다. 14 예외와 230 비최종/반려 행의 보존·격리 결과도 reconciliation에 포함한다. 이후 기출·생성·기존 등록 문항을 섞은 순서 고정 합본 HWPX의 원본 media embedding, package reference, 실제 한글 열기와 download SHA를 검증한다. 백업/rollback은 source activation과 새 조회 경로만 되돌리고 이미 생성된 불변 Artifact/감사 기록은 삭제하지 않는다.

완료 증거: 원본 workbook/ZIP hash, 모든 1,297행과 A:AF 값의 원본 대비 hash 일치, 각 교정본의 정확한 파일 Artifact pointer, `1,053 resolved candidate / 14 unresolved`의 실제 검토 후 재집계, 중복 Item 0, 원본/파생 파일 다운로드 hash 일치, XLSX export의 동일 행/원값/권한/해시 검증, 조회 성능 query plan, 기존 Item/Graph/HWPX 경로 회귀 PASS. 실제 교육적 정확성·구조화 추출 품질은 별도 검토 결과로 기록한다.

## 9. 더 단순한 안을 채택하지 않는 이유

엑셀 행을 곧장 `items.metadata_json`에 넣고 ZIP 경로를 URL로 쓰면 구현은 짧지만, 문서가 없어도 Item이 만들어지고 교정본·원본 바이트·충돌·권한·재전송의 의미가 사라진다. 모든 HWP를 즉시 JSON으로 변환하는 방식도 표·수식·그림 손실을 정본으로 오인할 수 있다. 원본 source 기록 → 검토된 파일 대응 → 정확한 ordered document assembly → 필요한 건만 정본 승격의 경계가 기존 EOM 규칙을 가장 적게 바꾸면서 메타데이터·조회성·합본 출력을 함께 보장한다.
