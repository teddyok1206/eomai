# DB 배치의 편집 가능한 HWPX 출력

2026-11-04 UTC. 구현 계획이며 운영 활성화 증거는 별도 release 기록에 남긴다.

## 목표와 보존 범위

DB의 저장된 조립 순서에서 기출·창작·AI 문항과 원본 HWP/HWPX를 선택한 순서대로
하나의 편집 가능한 HWPX로 내려받는다. 글·표·수식은 native 구조로, 그림은 package
내부 member로 보존한다. 페이지 전체를 PNG/PDF로 바꿔 붙이는 대안은 사용하지 않는다.
가져온 문항의 가변 정본 content를 예전 고정 6-block 틀에 억지로 넣지 않는다.

기존 입력 manifest, 실패 build, 정본 Item, 과거 Artifact는 바꾸지 않는다. 진행 중인
창작 풀이 슬롯·INDEX/QUERY와 고정 numerical runtime을 중단하거나 재설치하지 않는다.

## 책임과 정본

- Web/BFF/API는 인증된 사용자의 저장된 조립 revision으로 제작·조회·다운로드를 요청한다.
- Catalog는 기존 curated assembly application에서 실제 사용자 권한, manifest/placement,
  source·Item·Graph revision과 Artifact member/hash를 다시 확인한다.
- HWPX Manager는 기존 delivery 책임 안에서 영속 build, FIFO claim, 중단 복구,
  검증과 Artifact commit을 조정한다. curated 조립을 기존 시험 Assembly FK에 넣지 않는다.
- 격리 Builder는 검증된 local workspace만 읽어 변환·출력·병합한다. DB·NAS·로그인
  credential을 받지 않는다. 검증 후 NAS commit은 기존 Orchestrator Artifact owner만 한다.

정본 입력은 `curated-document-assembly-manifest/1.0`과 그 안의 immutable pointers다.
원본 파일, 구조화 Item, rendered segment, 합본은 서로 다른 수명과 해시를 갖는다.
변환/segment는 명시적인 materialization 결과이며 원본을 교체하지 않는다.

## 식별자와 계약

논리 assembly ID, assembly revision ID, build ID, source/Item revision, Artifact/Artifact
revision, member SHA-256을 구분한다. build는 입력 manifest SHA, renderer/profile version,
필요한 변환기 identity와 정확한 segment hash를 pin한다. 현재 source/권한이 바뀌면
명시적으로 실패하며 latest 파일로 바꾸지 않는다.

기존 native merge V1은 HWPX 전용이다. HWP 변환이나 가변 canonical Item 전달처럼
새 의미가 필요한 경우 JSON Schema 2020-12와 Pydantic successor를 먼저 추가한다.
browser가 파일 경로·멤버·권한 목록을 제출하는 인터페이스는 만들지 않는다.

## 접근 패턴과 저장 구조

한 조립 최대 200개. 주요 연산은 actor+idempotency key 조회, build ID 조회, immutable
revision의 history 조회, ordered placement 순회, FIFO concurrent claim이다. 작은 metadata와
FK·pointer만 DB에 저장하고 파일 payload는 저장하지 않는다. unique/B-tree/partial FIFO
index를 사용한다. 조회 O(log n), 해석·병합 O(XML 노드+고유 media bytes), 일시 공간은
제한된 staged input/output 크기에 비례한다. resource/object ID relocation은 map, 중복과
target 존재 검사는 set을 사용한다. 반복 파일 hash와 N+1 해석을 피한다.

Manager materialization은 기존 content-team Artifact member resolver의 batch 조회를
공개 경계로 재사용한다. nested member는 root 안의 regular file이고 symlink가 없을 때만
허용한다. canonical Item/1.0의 기존 `MediaArtifactPointer`에는 schema가 없으므로 그
image/png·image/jpeg 포인터에 한해서만 schema를 꾸며내지 않고 기존 media/hash 계약을
따른다. 문서·content·Markdown·복원 증거의 schema 검사는 생략하지 않는다. source/effective
content와 복원 manifest를 검증한 뒤 각 picture use를 확인하고, 검증된 동일 SHA의 local
image 파일만 공유한다. 긴 본문/PNG는 build row가 아니라 단일 workspace에서만 materialize한다.

실제 application 연결에서 최초 input pin은 Catalog 소유의 metadata batch 연산으로 한다.
저장한 조립을 재인가한 뒤 exact Item component와 source-bound visual publication의
Job/Artifact/revision·member descriptor로 source/effective/recovery/Markdown pointer를
고정한다. 이 때문에 API에 NAS 권한을 주거나 status poll마다 `load_item_content`·
전체 그림 복원을 호출하지 않는다. 실제 원본/복원 manifest의 내용과 derivation·PNG 검사는
Manager materialization과 commit 직전 재인가에서 수행한다. exact SUPERSEDED revision을
implicit latest나 현재 Preview의 APPROVED-only 규칙으로 바꾸지 않는다.

합본 결과는 Builder의 성공 플래그만으로 commit하지 않는다. Manager는 기존 bounded
publication ZIP/XML reader를 재사용하고 원본/segment와 합본의 순서·XML 내용·geometry·
binary bytes를 독립 대조한다. resource/object reference 종류만 작은 불변 contract로
공유하며 Builder의 ID 할당 코드나 lxml을 Manager에 들여오지 않는다. native section은
관측한 ordered catalog 구간으로 역대조하고 canonical/CTI 의미 검증도 유지한다.

## 트랜잭션과 실패

actor+key+정확한 요청 해시는 동시 요청을 단일 build로 묶는다. claim은 기존 Manager의
transaction/row lock 원칙을 사용하고 외부 실행 전 commit한다. 중단 후에는 같은 build와
검증된 result/Artifact receipt로 복구한다. 처리 여부 불명인 빌드를 새 key로 우회하지 않는다.
FAILED는 FAILED로 남기며 지원된 별도 재시도만 허용한다. 완료 조회·다운로드는 계산을
다시 실행하지 않는다. 권한은 요청 시와 output 접근 시 다시 확인한다.

curated delivery는 `hwpx_curated_builds`에 actor+key unique, REQUESTED partial FIFO,
RUNNING/VALIDATING partial recovery index와 exact assembly revision FK를 둔다. source body가
아닌 `curated-hwpx-build-input/1.0` pointer snapshot과 hash를 저장하며 Job·Artifact·Artifact
revision 예정 identity는 dispatch 전에 pin한다. 실제 output FK는 commit 이후에만 채운다.
저장된 실제 initiator의 request/session **식별 metadata**만 durable command에 보존하며
비밀번호·cookie·access/refresh token은 저장하지 않는다. background 실행은 그 사용자의
현재 ACTIVE 상태와 권한을 다시 조회한다. 저장된 permissions는 실행 권한으로 사용하지
않고 비워 둔다. 이 metadata는 로그인 세션을 연장하거나 다른 사용자를 가장하는 수단이 아니다.

같은 build의 dispatch·recovery는 전용 DB 연결의 nonblocking advisory lock으로 직렬화하고
finally에서 해제한다. FIFO row claim transaction은 외부 실행 전에 commit한다. lock 소유자나
고정 Builder unit이 살아 있으면 같은 실행을 기다리며, 관찰 timeout을 새 실행 사유로 삼지
않는다. 입력 snapshot/예정 identity와 terminal 상태는 DB에서도 불변으로 보호한다.
published Graph head가 앞으로 이동하는 것은 저장된 snapshot의 폐기가 아니므로 기존
선택 admission은 current-head로 유지하고, delivery reauthorization만 exact published pin을
읽는다. status/replay 권한 검사는 한 번의 source join과 batched Item/Graph 조회로 수행하며
원본 전체를 매 poll마다 다시 hash하지 않는다. bytes는 명시적인 staging/검증 경계에서 읽는다.

변환 손실은 원인별로 분류한다. 구조상 ID 재배정과 실제 본문/도형 손실을 같은 경고로
취급하지 않는다. HWP source-proven picture placement 복원은 재사용하지만 그것만으로
다른 control 손실이나 전체 레이아웃을 승인하지 않는다. 미지원 문서의 위치와 이유를
알려주고, 그림 없는 성공 합본이나 raster fallback을 발행하지 않는다.

## 구현 순서와 종료 증거

1. 보존한 실제 HWP/HWPX와 기존 merger·picture placement 모듈로 미완료 경계를 재현한다.
   실제 손실 원인을 고치고 synthetic 회귀로 고정한다. 기존 실패 이력은 그대로 둔다.
2. 가변 canonical Item의 text/table/equation/image/statement와 해설 출력을 기존 Builder에
   추가한다. Preview와 동일한 effective 그림을 쓰고 고정 예제 이미지 크기를 강제하지 않는다.
3. exact local segments를 기존 native merger로 결합한다. 서로 다른 문서의 글꼴·스타일·
   binary ID를 재배정하고 역매핑으로 내용·geometry·미디어 보존을 확인한다.
4. curated delivery의 schema·영속 build·Manager claim/recovery·검증·commit·secure download를
   연결하고 기존 API/BFF와 DB 배치 탭에 제작 상태·다운로드를 붙인다. 새 queue framework는 없다.
5. pointer/권한/멱등/동시 claim/중단·재전송/실패 회귀를 실행한다. DB 변경 검사는 disposable
   PostgreSQL만 쓰고 installed wheel/RECORD·service identity·sandbox를 검증한다.
6. 진행 중 작업의 pin을 보존하는 호환 release set으로 운영 반영한다. 실제 저장된 조립으로
   build→검증→commit→HTTPS download SHA를 확인한다. native table/equation, 순서,
   package-internal image 참조·bytes를 검사하고 시각 렌더 증거와 Hancom 수동 검수를 구분한다.

성공 여부는 테스트 수가 아니라 사용자의 저장된 배치에서 실제 다운로드 가능한 편집형
합본이 나오는지로 판단한다. 미지원 입력이나 사람 확인이 남으면 정확한 범위를 보고한다.

## 더 짧은 대안을 쓰지 않는 이유

PDF/그림 이어붙이기는 편집 가능 요구에 어긋난다. 기존 Item/시험 Assembly에 가짜 FK를
만드는 것은 정본·Graph 의미를 깨뜨린다. HWP 전체를 비엄격 변환해 경고를 무시하거나
모든 HWPX를 텍스트로 재생성하면 표·수식·그림 geometry가 손실될 수 있다. 따라서 기존
native package merger와 고정 Builder/Manager 경계의 필요한 부분만 확장한다.

## HWP 변환기의 검증된 수정 경계

선택적 후보는 `hwp2hwpx` commit `62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d`,
`hwplib 1.1.10`, `hwpxlib 1.0.9`다. 원본 grouped drawing을 보존하기 위해 추가하며
고정 JAR/source hash와 Java binary hash를 bundle identity에 묶는다. Builder 전용의
read-only 설치 도구이며 API/Catalog/임베딩·Codex 환경의 dependency가 아니다.

후처리는 원문을 재작성하는 것이 아니다. 고정 writer가 생략한 빈 style name을 빈 값으로
명시하고, 원래 크기와 현재 크기가 같을 때 쓰는 `curSz=0` 축을 그 원래 크기로 명시한다.
이 축약을 그대로 두면 현재 독립 미리보기 도구가 중첩 글상자를 납작하게 해석했다.
ZIP mimetype·preview를 정상 포장하고, 변경을 역적용해 다른 XML/그림 bytes가 그대로인지
검사한다. 문서 간 style name·도형 ID·instance/field ID는 충돌 없이 옮기고 역검증한다.

실제 10310·10318 표본을 **동일한 현재 Office sandbox**에서 원본 HWP와 변환 HWPX로
각각 읽었을 때 각 페이지가 pixel-equal이었다. 이전 날짜의 PDF는 렌더러 상태가 달라
현재 비교 기준으로 사용하지 않았다. 이 증거를 모든 HWP 또는 Hancom 수동 검수로
확대하지 않는다. native 합본의 XML 역검증·media hash는 통과했으나 독립 렌더의 2쪽에는
metadata 표의 `해설` 두 글자 위치 차이가 남았다. 본문·그림과 구분해 기록하고,
`전체 합본 pixel-equal`이라고 보고하지 않는다.

### 출제의도 글상자의 제한된 호환성 수정 — 2026-11-05 UTC

사용자가 해설 위 출제의도 상자의 본문이 Hancom에서 비어 보인다고 보고했다. 같은
합본의 텍스트와 독립 Office PDF에는 내용이 남아 있으므로 데이터 누락과 구분한다.
관측한 상자는 제목/본문 두 글상자와 빈 가장자리 도형을 가진 중첩 container이며 HWP에서 넘어온
본문 줄 폭 캐시가 변환된 rectangle의 유효 폭보다 컸다. Hancom 재현 완료와 동일시하지 않는다.

기존 HWP→HWPX package 정규화 owner에서 이 구조와 정확한 `출제의도` 제목을 식별해
본문 문단의 파생 `linesegarray`만 무효화한다. 글·상자 위치/크기·제목·그림·수식·본문의
다른 표/캐시는 그대로 둔다. 제거한 캐시를 역삽입했을 때 원래 XML과 일치해야 한다.
신규 DB/프로토콜/변환 bundle과 별도 출력기는 추가하지 않는다. paragraph→ordinal map과
직접 자식 조회로 시간·일시 공간 O(XML 노드), 동일 입력의 정규화는 결정적이고 멱등이다.
이 수정의 실제 Hancom 표시 여부는 새 파일의 사용자 검수로 별도 확인한다.

실제 3문항 합본의 확인용 사본에서는 본문 캐시 3곳만 제거됐고, 이를 역삽입한 XML과
원래 XML이 일치했다. 다른 ZIP member는 byte-equal이며 독립 Office PDF의 세 페이지도
수정 전후 pixel-equal이다. 집중 회귀와 HWPX 전체 검사 431개가 통과했고 기존 root-only
검사 1개는 opt-in으로 남겼다. formatter·ruff·mypy도 통과했다. 최초 전체 검사 invocation은
격리 Builder 환경에 Manager package가 없어 collection에서 종료됐고, 개발 검사에서만
설치 API package 경로를 명시해 다시 실행했다. 운영 Python 환경은 바꾸지 않았다.
현재 이 증거는 Hancom 표시 복구 또는 운영 활성화 완료를 의미하지 않는다.

변환 input/output hash, native 문단 텍스트 fingerprint, 표 구조, 수식 script, binary
fingerprint와 도형 개수는 로컬 schema-valid evidence로 다시 대조한다. 문단 fingerprint는
공백 차이를 제외한 **multiset**이며 자체로 reading order를 증명하지 않는다. 문서/section
순서와 실제 합본 배치는 별도 검증한다. 지원하지 않는 source control과 active/linked
binary는 손실을 숨기는 성공 경로가 아니라 위치를 가진 명시적 실패다.

## 가변 정본 문항 전달

혼합 local 실행은 `curated-hwpx-render-request/3.0`의 ordered discriminated segments를
사용한다. 원본 HWP/HWPX, canonical Item/1.0 blueprint, 콘텐츠팀 Item/2.0·3.0을 구분하며
가짜 시험 Assembly/placement identity를 만들지 않는다. 원본 content hash, local blueprint
hash와 rendered segment hash는 각각 다른 값이다. 같은 request의 정확한 source/segment
chain과 section별 원래 position을 결과에 기록한다. 기존 local V1/V2 schema 의미는 유지한다.

공통 handoff archive/runtime/template은 한 번만 검증·준비한다. generated 이미지의 기존
binding은 유지하되 실제 staged file은 content-addressed `images/`로 한 번만 materialize한다.
중간 segment는 검증·복구용 workspace 결과이며 별도 per-item delivery나 NAS 정본으로
자동 등록하지 않는다. 파일·XML·총 입력/output byte budget과 local path를 제한한다.
canonical 문항은 선택 순서로 번호를 표시하고 원본 native 문서의 번호·내용은 바꾸지 않는다.

가변 canonical `assessment-item-content/1.0`은 Manager의 `project_native_item`에서
`native-item-render-request/1.0`으로 투영한다. 이는 기존 정본을 교체하는 모델이 아니라
격리 Builder의 명시적 local materialization 입력이다. 원래 content SHA와 Preview의
effective content SHA를 구분하고 body 순서·그림 use·해설을 고정한다. 본문 JSON을 DB에
추가 저장하거나 Catalog/Graph 검색을 Builder로 옮기지 않는다.

`CANONICAL_ITEM_NATIVE_V1`은 고정 template hash에서 글꼴을 가져오되 free-flow 문단
속성을 별도로 할당한다. 그림은 content-addressed file로 한 번만 stage하고 모든 use의
pointer는 먼저 검사한다. native picture 생성과 native package merger는 기존 구현을
재사용한다. 순서·텍스트·표 cell·수식 script·실제 picture bytes/viewport는 순수 계약
검증기로 출력 XML에서 독립적으로 읽어 대조한다. 임의 크기 그림과 표-only에 고정 PNG나
빈 visual frame을 만들지 않고 내부 alt description도 학생용 글자로 출력하지 않는다.
지원하지 않는 LaTeX는 기존 검증된 수식 grammar에서 명시적으로 실패한다.

`version.xml`의 제작 OS·응용프로그램 차이는 새 native merge V2에서 producer metadata로
구분한다. version 5.1, XML 1.4/1.5, 실제 layout compatibility와 section/resource 검증은
유지한다. OS 필드의 upstream 정의는
[VersionXMLFile](https://github.com/neolord0/hwpxlib/blob/main/src/main/java/kr/dogfoot/hwpxlib/object/root/VersionXMLFile.java)에
있다. 구 native merge V1의 의미와 schema bytes는 바꾸지 않는다.

## 저장·상태·화면의 연결

API는 request-only `CuratedHwpxApplicationService`와 Catalog delivery gateway를 사용한다.
기존 private Catalog 소켓에 `RESOLVE_CURATED_DOCUMENT_DELIVERY`만 추가하고 실제 operator
식별·고정 assembly revision/hash를 전달한다. BUILD/READ 재확인은 release를 다시 선택하지
않는다. 최초 PIN_INPUTS에서만 보호된 설정의 handoff/converter를 선택하며 Catalog가 실제
권한·Item/Graph·Artifact metadata를 재확인한다. 파일/worker 내용은 이 RPC에 없다.

Runner는 기존 Catalog application과 Registry를 직접 조합해 같은 권한 검사를 수행하고,
기존 Artifact `commit_file_set` owner로만 NAS를 발행한다. 추가 DB 권한은 큐 상태 변경과
현재 operator/source의 SELECT다. credentials·worker 권한은 추가하지 않는다. 한 Job의
예정 identity, 기존 file-set commit intent와 local result를 재사용하며 새 영속 큐나
Artifact 출판 framework를 만들지 않는다.

단일 문항·시험지·DB 조립 큐는 세 순서를 순환한다. `render-curated`만 고정 unit/900초
한도를 쓰며 기존 renderer timeout은 그대로다. 큰 합본은 별도 download/2.0에서 최대
256MiB로 제한한다. 기존 download/1.0의 64MiB와 schema bytes는 변경하지 않는다.

DB 배치의 저장본 행에 제작·상태 확인·다운로드를 연결한다. 최신 제작의 조회, 진행 중
제작의 반복 조회와 완료 결과 확인은 모두 read-only이며 새 제작을 제출하지 않는다.
응답을 잃은 생성 요청은 같은 idempotency key를 유지한다. 실패 뒤 다시 제작은 사용자
버튼으로만 새 요청을 만들고 기존 FAILED를 보존한다. UI의 내부 ID는 표시하지 않는다.

## 관련 근거

- [혼합 문항 입력·조립 설계](NOTION_ITEM_ARCHIVE_IMPORT_PLAN_2026-10-27.md)
- [native 합본 구현 체크포인트](../operations/CURATED_NATIVE_HWPX_CHECKPOINT_2026-10-31.md)
- [HWP 그림 배치 복원과 남은 차이](../operations/HWP_PICTURE_PLACEMENT_FIX_2026-10-31.md)
- [가변 문항 출력의 이전 보류 범위](../operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md)
- [Manager·Builder application 경계](HWPX_APPLICATION_API_V0.md)
