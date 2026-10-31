# DB 조립 → 편집 가능한 HWPX

## 제품 범위

저장된 DB 조립 revision의 최대 200개 문항을 지정 순서대로 한 HWPX로
출력한다. 창작 원본, 기출 Item, 창작 등록 Item, EOM AI Item을 지원하는 입력
경계를 유지한다. 25문항 모의고사의 Form/배점/개수 정책을 적용하지 않는다.
페이지 전체를 그림으로 대체하지 않는다. 승인 상태 변경/문항 재생성도 하지 않는다.

단순 파일 바이트 연결은 ZIP 중앙 디렉터리와 전역 글꼴/문단/스타일/그림
참조를 합치지 못한다. 이전 10991+11436 표본은 이미지 bytes를 보존하고도
다른 문항의 그림을 참조했다. 기존 source/실패/조립 manifest는 수정하지 않는다.

## 책임과 정본

- API/Web: 저장된 조립 선택, 제작 요청, 진행/실패, 검증된 다운로드.
- Catalog 공개 application: 현재 operator 권한 및 exact Assembly/Item/Graph/
  source revision/hash 해석과 입력 파일 자격. Manager는 이 경계를 재사용한다.
- HWPX Manager: 영속 요청/claim/recovery, 검증된 로컬 materialization,
  격리 Builder 실행, 결과 재검증, 기존 Orchestrator artifact commit 호출.
- Builder: 로컬 입력만 읽어 변환/병합 후보와 보존 검사 결과를 반환한다.
  DB/NAS/사용자 인증/네트워크에는 접근하지 않는다.

정본 입력은 `curated-document-assembly-manifest/1.0`이다. 조립 ID와 revision,
manifest hash, source Artifact/revision/member/hash는 분리한다. 출력은 새 build
ID와 Artifact/revision/hash를 갖는다. 기존 원본을 다시 정본 파일로 복사하지 않는다.

## 영속성과 접근 패턴

기존 HWPX application runner 안에 curated profile을 추가한다. 새 범용 queue나
worker orchestration framework를 만들지 않는다. 전용 build row는 기존 시험지
build와 달리 curated assembly FK를 사용하며, source-only 원본을 가짜 Item에
연결하지 않는다. DB에는 작은 pointer/state/hash/actor만 저장한다.

주 연산은 `(operator,idempotency key)` unique lookup, build ID lookup,
REQUESTED FIFO claim, assembly revision별 결과 목록이다. B-tree/partial FIFO
index와 `FOR UPDATE SKIP LOCKED`를 사용한다. 정렬한 불변 placement tuple,
resource/reference map과 visited-pair set으로 병합 검증을 O(입력 XML+media bytes)
수준으로 수행한다. 최대 200개/총 입력 bytes/압축 해제/출력 bytes 상한을 별도로
고정한다. 사용자 지정 절대 경로와 arbitrary subprocess 인자는 받지 않는다.

동일 key+동일 조립/renderer/config 입력은 기존 build를 반환하고 다른 입력은
409다. claim 후 중단 시 기존 fixed-unit 실행 상태와 검증된 output receipt를
확인한다. 살아 있는 renderer와 경합하지 않으며 terminal FAILED를 성공으로
바꾸지 않는다. 새 실행은 새 identity로 원인과 predecessor를 남긴다.

## 변환·병합·검증

1. 파일명 확장자가 아니라 탐지된 내용 형식과 pinned media/hash를 확인한다.
2. 등록 Item은 검증된 기존 editable HWPX segment를 사용하거나 기존 단일
   문항 renderer로 segment를 만든다. EOM 템플릿 계약은 변경하지 않는다.
3. 원본 HWPX는 보존형 package merge 후보로 처리한다. HWP는 별도 변환
   보존 검증을 먼저 통과해야 한다. HWP 5.0 손실/손상은 HWPX 성공으로 숨기지 않는다.
4. 원본별 section/paragraph/table/equation, 페이지 설정과 실제 사용된 header
   resource를 순서대로 비교한다. Resource ID는 값 자체가 아니라 해결된
   정의를 비교한다. style cycle은 visited pair로 처리하고 누락/상충은 거부한다.
5. 이미지 reference마다 원본 media SHA+type의 lineage를 검증/재매핑한다.
   ZIP 안에 이미지가 존재한다는 검사만으로 PASS하지 않는다.
6. package/core/internal relationship 및 결과 hash를 독립 검증하고, 다운로드
   bytes가 committed Artifact hash와 같은지 확인한다.

변환기의 단순 손실 코드 allow-list는 acceptance가 아니다. 문서 단위 metadata
정책과 실제 문항 보존 증거를 구분한다. 구조/픽셀 자동검사와 Hancom에서의
육안 편집 품질은 별도 상태로 기록한다. 못 보존한 입력은 문항 위치와 짧은
원인을 표시하며, 일부 문항을 빼고 성공 파일을 제공하지 않는다.

## 의존성과 더 단순한 대안

HWPX 병합은 기존 lxml/ZIP 기반의 native package relocation을 사용한다.
별도 변환기로 XML을 재생성하지 않고, 원본마다 자원 ID를 먼저 배정한 다음
정의와 참조를 함께 옮긴다. 역매핑한 section/resource XML과 원본을 비교한다.
새 라이브러리·변환기 생산 의존성은 추가하지 않는다.

기존 감사 도구 hwp-cli 1.3.1은 HWP 변환 **후보 생성기**로만 검토한다.
런타임 다운로드/자동 업데이트는 금지하고 binary/version/SHA를 pin한다.
원본 HWP의 실제 그림 보존을 입증하지 못하면 해당 형식은 명시적으로 차단한다.

공식 도구 설명: https://github.com/STAIxBWLB/hwp-cli/blob/v1.3.1/docs/manual/cli-reference.md

기존 content-team exam merger는 동질 템플릿용 계약이므로 임의 원본에 강제로
적용하지 않는다. 비엄격 변환, PDF/PNG 삽입, HTTP 응답 안에서 장시간 합치기,
큰 bytes의 DB 저장, 별도 사용자 파일 저장소/queue는 대안에서 제외한다.

## 구현 순서와 exit gate

1. 로컬 Builder request/result schema와 독립 보존 검증기; synthetic 및 실제
   10991/11436 충돌 회귀. 손상된 10310/10318 변환은 음성 fixture로 유지한다.
2. 보존형 병합 adapter와 제한된 변환 profile, bounded fixed-unit 실행.
3. 기존 Catalog/Manager의 입력·권한·artifact 경계, 요청 저장/claim/복구/다운로드.
4. API/BFF와 DB 배치 탭 연결, 임시 DB 동시성/재전송/중단 검사, 설치 wheel 검증.
5. 승인된 소수 실제 조립의 download SHA와 시각 비교. GPU와 창작 슬롯의
   실행/pin은 보존한다. 끝나지 않은 단계를 완료했다고 표시하지 않는다.

## 2026-10-31 구현 체크포인트

- Builder native 병합, request/result JSON Schema·Pydantic, `render-curated`
  로컬 workspace 명령을 구현했다. 파일 확장자는 ZIP 내용 형식의 증거가 아니다.
- 실제 10991/11436 HWPX 두 문항 합본을 기존 격리 Office 변환기로 PDF로 열었다.
  각 원본 1쪽과 합본의 대응 1·2쪽을 동일 설정의 PNG로 변환한 결과가 각각
  바이트 동일했다. Hancom 자체 편집/저장 검토와는 별도 자동 증거다.
- DB build queue, 공식 Manager 실행/commit/download 및 GUI 연결은 **아직 미구현**이다.
  로컬 명령의 성공을 운영 조립 기능 완료로 표시하지 않는다.
- 원래 HWP의 그림 누락은 native HWPX 병합과 다른 입력 변환 경계의 문제다.
  변환기를 단순 비엄격 모드로 바꾸거나 PDF 페이지를 그림으로 넣어 우회하지 않는다.
