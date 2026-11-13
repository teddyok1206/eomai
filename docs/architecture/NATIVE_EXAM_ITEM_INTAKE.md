# 한글 시험지와 해설지의 문항별 등록

2026-11-13 UTC. 기존 자료 학습을 확장하여 시험지·해설지의 편집 가능한 원문과
문항별 Excel 메타데이터를 함께 등록한다. PDF 캡처나 모델의 재작성으로 원문을 대신하지
않는다. 구현·실제 분리 검증·운영 등록·배포 상태는 별도 운영 기록에서 구분한다.

## 입력과 완료 조건

입력은 회차별 시험지, 별도 해설지, 선택적 문항 메타데이터 XLSX다. 압축파일은 이 입력들을
묶는 운반 수단이지 실행 권한이나 문항 identity가 아니다. 확장자보다 실제 container를
판별한다. 원본 문항 번호, 외부 고유번호, 시스템 Item ID는 서로 다르다.

초기 대상은 김병훈 자료 18회 450문항이다. 실제 조사에서 18개 XLSX의 문항은 각각
1–25번이며, 1–10회의 250개 행에는 중복 없는 5자리 번호가 있고 11–18회에는 없다.
운영 DB와의 번호 충돌은 등록 전에 확인한다. 모든 시험지·해설지에서 본문 1–25번의
시작 문단이 발견됐다. 일부 표 내부에도 같은 숫자 접두사가 있으므로 단순 전체 텍스트
정규식으로 분리하지 않는다. 외부 번호가 없는 문항에 번호를 임의로 발명하지 않는다.

사용자는 없는 고유번호를 추후 갱신한 Excel로 제공한다. 그 전에는 null로 보존한다.
문항 identity는 원본 문제·해설 revision과 회차·문항번호로 결정하며 Excel hash나 외부
고유번호에 의존하지 않는다. 후속 Excel은 같은 문항의 metadata successor로 연결하고
이전 원문·metadata revision은 보존한다. 번호 추가만으로 새 Item이나 새 풀이를 만들지 않는다.

완료 조건은 문제·해설 각 450개의 정확한 대응과 편집 가능한 HWPX, 원문 metadata 보존,
기존 Registry/Graph/증분 INDEX 연결, 원본과 등록 문항의 실제 조회다. 단순 ZIP 정상이나
AI 작업 완료만으로 원문 보존을 승인하지 않는다. 원래 해설과 모델의 풀이보고서는 별개다.

## 기존 소유자와 확장 경계

- Catalog의 기존 자료 접수·권한·원본 Artifact·run/task가 학습을 조정한다.
- HWP 변환은 Builder의 고정된 `NativeHwpConverter`와 원문 보존 검사를 재사용한다.
- 문항 분리는 Builder의 native package 읽기·resource 해석을 재사용하는 파일 adapter다.
  원본 문단·표·수식·그림 subtree를 보존한다. 별도 문항 생성기나 출판 엔진을 만들지 않는다.
- Excel decoder는 입력 adapter이고 매핑 결과는 작은 typed contract다. 셀의 원문·좌표·
  중복 헤더·수식과 저장된 값은 원본 XLSX/정규화 manifest에서 추적한다.
- Orchestrator의 기존 staged 실행·검증·Artifact commit 경계만 NAS에 결과를 쓴다.
- Registry·풀이·공통 Graph·증분 INDEX는 기존 owner를 사용한다. worker의 DB/NAS 접근,
  새 queue나 별도 Graph/벡터 검색 엔진을 추가하지 않는다.

기존 자료 학습은 문제·해설 입력을 받아 원본을 보존하지만 등록 component는 문항 JSON,
lineage, review JSON이다. 문항별 native 파일과 Excel 연결을 successor 계약으로 추가한다.
기존 JSON의 필드나 released 계약의 의미를 제자리 변경하지 않는다.

## 정본과 포인터

원본 압축파일/시험지/해설지/XLSX와 불변 source revision이 정본이다. HWP→HWPX 전체 변환,
문항별 HWPX, 검증 영수증은 원본 hash·converter identity·분리 profile에 묶인 파생 Artifact다.
Registry는 이 Artifact를 참조하고 같은 파일을 다른 canonical 폴더에 복제하지 않는다.

분리 계획은 source hash, MAIN/SOLUTIONS 역할, 문항 label, 순서 있는 section/직속 paragraph
범위를 pin한다. 분리 결과는 출력 hash, 입력 범위 hash와 native text/equation/table/picture
보존 증거를 가진다. 출력 파일명·경로는 identity가 아니다. 저장·읽기에는 logical/revision/
Artifact/member/schema/media/hash와 실제 사용자 권한·lifecycle을 검증한다. 최신 원본으로
몰래 바꾸거나 빈 파일을 성공으로 등록하지 않는다.

## 메타데이터와 분류

XLSX header를 읽어 문항번호·단원·원본 출처명·배점·난이도 등을 찾는다. 고정 열/행 번호로
모든 파일을 해석하지 않는다. 같은 이름의 열은 좌표별 원문을 보존하고 의미가 일치하는지
검사한다. 무제목 고유번호 열의 판별 근거를 manifest에 남긴다. 회차+문항번호를 대응 key로
사용하고 제목 유사도나 숫자만으로 기존 Item을 덮어쓰지 않는다.

원본 단원과 검색용 공백 정규화 값을 구분한다. Graph 추론 단원으로 원본 단원을 대체하지
않는다. `검토팀최종 목차`는 사용자가 제공한 분류체계 설명으로 남기며 실제 taxonomy와의
대응은 확인된 값만 기록한다. Excel의 `통합과학 - 창작`과 자료 학습의 `EXTERNAL` 출처는
서로 다른 metadata다. 원본 분류를 손실시키거나 경로에 따라 AI 생성으로 바꾸지 않는다.
폴더의 완/미정산 표시는 출판·과학 검토 승인 상태로 해석하지 않는다.

## 자료구조와 비용

주요 연산은 원본/문항 key 조회, 문단 순서 순회, 중복 검출, resource 참조 해석, append-only
결과와 concurrent claim이다. 문항과 resource는 dict, 번호/사용 member는 set, 범위·결과는
불변 tuple을 사용한다. 전체 source XML은 한 번 읽고 직속 문단을 한 번 순회한다.

N개 XML node와 B바이트 파일에 대해 발견/검증은 O(N+B)다. 각 문항에 필요한 binary만
보존하고 25개 출력마다 전체 시험지 그림을 복제하지 않는다. 공유 header의 작은 style
catalog는 독립 문서 성립에 필요한 값이며 출력 materialization 경계에서만 복사한다.
메모리는 한 회차의 bounded source와 한 문항 출력에 제한한다. 기존 indexed source/task/
registration key를 재사용하며 새 DB/index는 실제 조회 경로 부족이 입증될 때만 추가한다.

## 분리와 검증 규칙

1. 안전한 ZIP inventory와 Unicode 이름 해석을 먼저 한다. traversal·symlink·암호화·중복·
   expansion 한도를 검사하고 macOS 보조파일은 본문 입력에서 제외한다.
2. HWP는 고정 native converter로 변환하고 원문 text/table/equation/binary evidence를 검사한다.
3. 직속 본문 문단의 번호 경계를 발견한다. 표·글상자·해설 내부 숫자를 새 문제로 취급하지
   않는다. 문단을 넘는 문제와 section 연속성을 명시적 범위로 보존한다.
4. 선택 범위의 subtree와 연결 resource만 보존한다. 페이지 장식·정답표와 실제 해설은
   구분하고, 다른 문항의 내용·미리보기 thumbnail이 출력에 섞이지 않게 한다.
5. fragment의 header/spine/manifest/section과 image relationship를 다시 검사한다.
   수식 script·표 셀·그림 viewport/회전/라벨·순서를 원본 범위와 대조한다.
6. 문제와 원래 해설은 회차+번호로 연결한다. AI 내용 해석과 풀이보고서는 검증된 원문
   포인터를 받아 기존 학습 경로에서 진행한다. PDF는 필요할 때 관찰용으로만 쓰며 출력
   한글 파일을 PDF 캡처로 대신하지 않는다.

17회 원본의 `Scripts/headerScripts`와 `Scripts/sourceScripts`는 검토한 한글 기본
editor template의 정확한 두 바이트열인 경우에만 `NATIVE_SPLIT_V1`에서 읽고 파생
fragment에서는 제외한다. JavaScript를 실행·파싱·문자 정규화하지 않고 member의 SHA와
길이(150/80바이트)를 확인하며, 분리 영수증의 `excluded_source_parts`에 그 값과 제외
이유를 기록한다. OPF manifest/spine에서 해당 참조도 제거한다. 원본 package는 완전한
상태로 보존하고 문항 본문·표·수식·그림은 기존 subtree 검사를 그대로 통과해야 한다.
다른 script part, 내용·주석·BOM·인코딩·Unicode의 변경은 거절한다. 일반 macro 제거
fallback이 아니며 기존 STRICT parser/merge는 이 template도 계속 거절한다.

## 트랜잭션과 복구

파일 변환·분리 중 DB lock을 잡지 않는다. Artifact는 기존 commit owner가 멱등 key와
expected hash로 저장한다. 접수/문항/등록 identity는 source revision·범위·profile·actor에
묶는다. timeout 뒤 같은 요청의 commit/registration을 조회하고 새 key로 우회하지 않는다.
파일 성공 뒤 중단하면 검증된 파일을 재사용하고 모델 풀이·Graph를 중복 생성하지 않는다.
기존 FAILED는 보존하며 supported successor/reconcile만 사용한다. 독립 문항의 예외는
명시적으로 보류하고 원문을 고쳐 성공 처리하지 않는다.

## 구현 순서와 gate

1. native 분리 및 Excel 연결의 JSON Schema 2020-12와 frozen model을 먼저 정의한다.
2. synthetic fixture에서 범위·resource·동일 replay·잘못된 참조·보안 회귀를 검사한다.
3. 실제 HWP/HWPX 대표 회차에서 문제·해설 분리와 원문 구조 보존을 검증한다.
4. 전체 18회에서 450쌍 coverage와 metadata/고유번호 충돌을 검증한다.
5. 기존 자료 학습 입력·등록을 확장하고 임시 PostgreSQL에서 권한·동시성·중단·재전송을
   검증한 뒤 호환 release로 운영에 반영한다.
6. 대표 문항의 원본 다운로드·DB 열람·Graph·embedding 입력을 확인하고 전체 처리를 이어간다.
   이 작업에서 검증된 분리/metadata 연결을 자료 학습의 지원 기능으로 정리한다.

단순 대안인 전체 PDF crop은 편집성을 잃고, 모델 재작성은 원문을 바꿀 수 있다. 전체 HWPX를
450개 Item에 그대로 붙이는 방식은 문항별 조회·배치 의미를 충족하지 않는다. 따라서 기존
native package adapter에 작은 범위 분리기를 추가하는 것이 필요한 최소 확장이다.
