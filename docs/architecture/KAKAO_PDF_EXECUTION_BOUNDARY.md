# Kakao 학생 PDF의 로컬 실행·수락 경계

## 책임과 정본

Catalog가 현재 사용자 권한, binding lifecycle, packet/student/question revision과 승인된
사진 원본을 resolve한다. Orchestrator adapter는 이미 허가된 로컬 원본을 별도 attempt
workspace에 materialize하고 고정 renderer unit을 실행한다. worker는 DB·NAS·인증정보·
네트워크에 접근하지 않는다. 최종 Artifact 발행과 DB 연결은 기존
`CatalogArtifactService.commit_file_set` 및 domain acceptance가 담당한다.

## 식별자·동시성

논리 export와 packet/student/subset은 기존 pure render command에 고정한다. 실행은
`command_id`, `task_id`, `attempt_id`, `attempt_number`, 단조 증가 `fence`를 추가로 고정한다.
동일 export라도 새 attempt는 다른 로컬 디렉터리다. command의 canonical hash가 전체 실행
핀과 입력 manifest·폰트·renderer release를 묶으며 worker result가 실행 identity를 다시
반환한다. 경로는 보관 위치일 뿐 ID가 아니다.

현재 claim/lease/fence를 검증하는 callback은 staging 전·실행 직전·결과 수락 전후에
필수 호출한다. 이 adapter는 lease를 생성하거나 갱신하지 않으며 새 scheduler가 아니다.
늦은 결과는 보존하되 수락하지 않는다. HTTP timeout이나 unit 관측 실패 후 같은 실행을
자동 제출하지 않는다. 중단·부분 출력은 진단/복구용으로 남기고 성공으로 재해석하지 않는다.

`recover_finished`는 owner가 **동일 attempt의 process/cgroup 종료를 확인한 callback**을
필수 전달해야 한다. 원래 request와 execution fence, 입력 manifest/모든 member hash를 다시
검증하고 이미 생성된 결과만 수락한다. render를 재실행하지 않으며 부분 core staging은
기존 파일의 hash가 맞을 때만 남은 파일을 채운다. 기존 파일을 덮어쓰지 않는다. 종료 여부가
UNKNOWN이면 callback이 거부해야 하며, 파일이 있다는 사실만으로 종료를 추정하지 않는다.

## 데이터 구조와 비용

입력은 typed relative member + hash/size/media로 검증한다. ordered question traversal과
member map/set으로 입력 closure·중복을 확인하며 O(질문+member+총 bytes), 메모리는
manifest와 작은 bounded read buffer가 중심이다. 큰 binary를 DB·Job metadata에 복사하지
않는다. 입력 staging과 worker→core staging은 명시적인 물질화 경계다. 둘 다 descriptor
기반 regular-file/단일 link/경로/소유자/크기/hash 검증을 적용한다.

## 실행과 권한

기존 native-exam preparer와 같은 고정 systemd template/StartUnit 방식이다. 사용자는 argv,
Python 경로, unit property, UID 또는 작업 경로를 전달하지 않는다. renderer 전용 UID/private
group, 읽기 전용 입력 bind mount, 출력 한 디렉터리만 writable, private network/tmp/device,
메모리·CPU·파일 크기·시간 한도를 사용한다. worker 설치본과 template/config hash를 실행
전에 확인한다. 실제 privileged sandbox 검증은 별도 운영 gate이며 unit 문자열 테스트나
동일 UID의 합성 process 검사를 그 증거로 표시하지 않는다.

oneshot은 `RemainAfterExit`로 원래 완료 관측을 유지한다. 성공 상태를 확인한 뒤 그 unit의
cgroup을 stop하여 잔여 process가 없어진 다음 출력 수락으로 이동한다. host의 attempt 파일은
삭제하지 않는다. 설치된 wheel provenance는 기존 release owner가 확인하며 adapter는 고정
root-owned Python/template와 release 환경 값의 일치를 검사한다.

동일 renderer UID의 다른 학생 attempt도 보이지 않도록 기존 embedding sandbox와 같은
read-only `TemporaryFileSystem`으로 runtime parent를 가린 뒤 현재 attempt의 input/output만
bind한다. root 설치 후 권한·네트워크·형제 workspace 음성 검사를 별도 수행해야 한다.

### 실제 descriptor 접근과 격리 parent의 호환 — 2026-11-17

보호된 합성 실행에서0711 private parent는 경로 통과는 허용하지만, 기존 descriptor walk의
`O_RDONLY|O_DIRECTORY|O_NOFOLLOW` parent open을 거부하는 것을 확인했다. 파일을 임의
경로로 열도록 우회하거나 descriptor 구현 전체를 바꾸지 않고 private read-only tmpfs의
parent만0755로 맞춘다. 이 namespace에는 현재 attempt bind만 있으므로 host의 다른 학생
attempt는 여전히 보이지 않는다. input read-only/output 한 곳 write, private network,
NAS/인증정보/소스/host Catalog 상태 차단과 worker의 private group은 유지한다.

기존0711 template의 실제 FAILED 기록은 보존한다. 수정은 새 template hash와 Catalog의
기대 pin을 함께 반영하며 새 합성 attempt로 실제 실행·재수락을 검증한다. unit 문자열 검사나
template hash 일치만으로 정상 PDF 실행을 선언하지 않는다. 결과는 운영 체크포인트에 따로 둔다.

사진 수락은 Catalog의 선택적 `kakao-runtime` 의존인 Pillow11.3.0을 사용한다. 실제 API/
Catalog 환경 lock에도 같은 pin을 포함한다. `--no-deps` EOM wheel 설치와 일반 `pip check`만
통과해도 optional dependency가 없을 수 있으므로, 실제 `-I` 설치본의 PNG/JPEG/WebP
검사를 함께 수행한다. feature-off import를 강제 의존으로 바꾸거나 worker의 decoder를
API에서 임의로 원격 호출하지 않는다.

설치된 Noto CJK는 여러 Unicode 문자를 같은 glyph로 매핑하며 MuPDF의 ToUnicode 역매핑은
그중 하나를 선택한다. 합성 날짜에서 hyphen, 실제 질문에서 ellipsis와 compatibility Jamo가
이 차이로 거부되는 것을 재현했다. 문자별 예외 목록을 늘리거나 원문/출력 문자열을 치환하지
않고, readback의 같은 위치에서 **사용한 exact font의 glyph ID가 같고0이 아닐 때만**
동일한 출력 글리프로 인정한다. NFKC·모양 추정·다른 폰트의 fallback을 사용하지 않는다.
실제 폰트에서 glyph가 다른 수학 minus·다른 본문·누락·중복은 계속 거부한다. 원문 codepoint의
정본은 immutable manifest와 coverage receipt이며 PDF 역추출 문자열을 원문으로 사용하지
않는다. glyph map은 고유 문자마다 한 번 계산해 O(문자 수+고유 문자 수)다.

## 결과·발행

원래 command와 정확히 맞는 실행 핀·학생 subset, canonical layout receipt, 기대한 PDF·PNG
개수/이름/media/hash를 검증한다. 원본과 실패 workspace는 수정하지 않고 검증된 출력만
core 소유 디렉터리에 복사하고 hash를 재확인한다. 반환 DTO는 출력 member와 작은 receipt만
외부에 노출하며 로컬 절대 경로는 내부 adapter 값이다. Catalog가 source 권한·lifecycle을
다시 확인한 뒤 canonical 발행하고 exact Artifact pointer를 DB에 연결한다.

NAS publish 후 DB accept 전 중단은 기존 publication identity를 조회해 이어야 한다. 이
adapter 자체에서 NAS/DB를 함께 commit하거나 임의 row를 성공으로 바꾸지 않는다.

## 대안

API 안에서 직접 render하면 신뢰하지 않는 사진 decode와 긴 작업이 API 권한·수명에
합쳐진다. 범용 worker/scheduler를 새로 만드는 것은 기존 owner·claim·unit 경계를 중복한다.
따라서 고정 PDF adapter와 제한된 materialization/validation 함수만 추가한다.

## 명시적 사진 편집과 질문 내부 순서

spec §§8.6, 9.5–9.8에 따라 문장/사진 payload와 별도로 작은 typed `ordered_blocks`
reference tuple을 고정한다. 모든 text span/attachment occurrence는 정확히 한 번 나타나며
각 payload tuple의 상대 순서를 보존한다. 레이아웃은 이 순서를 따라 흐르고, 인접 사진
묶음에 한해서만 1열/2열 후보를 쓴다. 후보는 글자 크기 11/10 × 사진 열 1/2의 네 개로
고정하며 범용 layout engine을 추가하지 않는다.

사진 편집은 불변 transform revision + EXIF→명시적 90도 단위 회전→ppm crop의 순서다.
crop은 회전 후 크기의 정수 millionths 좌표이며 왼쪽/위는 floor, 오른쪽/아래는 ceil로
픽셀 범위를 정한다. 원본 파일은 수정하지 않고 worker 내부 PNG 표시 파생물의 hash·크기·
픽셀 크기를 receipt에 기록한다. 자동 crop이나 overflow를 숨기는 축소는 하지 않는다.
원본과 transform은 command manifest hash로 고정되고, 결과를 읽을 때 같은 transform과
source hash, 블록 순서·비겹침·최소 크기를 재검증한다. 알려지지 않은 날짜는 임의의 생성
날짜로 바꾸지 않고 owner의 명시적 unsupported 상태로 남긴다.
## 검증된 PDF의 정본 발행 연결

`kakao_pdf_publication.py`는 Orchestrator가 정지한 worker 결과를 검증해 만든
`AcceptedKakaoPdf`를 기존 Catalog Artifact 발행에 연결한다. 별도 NAS writer,
worker의 DB 접근, 새로운 파일 복제 계층은 만들지 않는다. 이 함수는 공개 API가 아니며
실제 export owner가 현재 권한·binding·packet/student·attempt/fence를 확인하는 callback을
발행 전과 직전 및 직후에 제공해야 한다.

- 정본은 한 발행의 PDF, layout receipt, 순서 있는 page PNG다. 기존 core-only accepted
  staging을 `commit_file_set`의 입력 경계로 그대로 넘기며, DB에는 이들의 exact Artifact
  member pointer만 채택한다. 학생 이름·질문 본문은 일반 Job request/result에 넣지 않는다.
- logical export/attempt와 publication Job, Artifact/revision, 각 member hash는 별개다.
  `export + attempt`를 멱등 발행 key로 사용한다. 같은 attempt 재전송은 같은 파일 집합을
  반환하고, 동일 key의 다른 내용은 conflict다. 새 attempt는 기존 실패 이력을 덮지 않는다.
- request/manifest/layout/result의 exact pins, PDF/PNG media와 페이지 순서, 전체 member
  집합을 확인한다. Artifact owner가 staged bytes를 expected hashes와 대조한다. worker의
  임의 경로나 출처 이름은 발행 파일 이름으로 사용하지 않는다.
- manifest는 검증된 원래 JSON bytes를 받는다. 선택 필드의 생략·명시적 null 또는 공백이
  다를 수 있으므로 Pydantic 기본값을 채운 재직렬화 결과를 원본 hash로 사용하지 않는다.
- 접근은 단일 export/attempt 조회와 최대 202개 member의 순서 있는 집합 검사다.
  map/set으로 O(페이지 수), 실제 저장/검증은 O(출력 bytes), 추가 binary 복제는 없다.
  domain lock은 발행 동안 유지하지 않는다. callback은 발행 권한을 대체하지 않는다.
- 발행 뒤 DB CAS나 권한 확인이 실패하면 미채택 Artifact를 보존한다. 같은 완료 attempt의
  발행·수락을 다시 시도하지 worker를 다시 실행하지 않는다. FAILED를 성공으로 바꾸지 않는다.
- 단순 PDF 경로 저장은 파일 교체·다른 학생의 결과·중복 재렌더를 구별하지 못하므로
  기존 immutable Artifact 발행을 재사용한다. 새 DB/schema는 이 연결 함수에 필요 없다.

PDF/PNG binary pointer 형식 식별자는 각각
`eom://schemas/kakao-archive/question-pdf/1.0`,
`eom://schemas/kakao-archive/question-preview-png/1.0`이다. JSON Schema는 binary에
적용하지 않으며 실제 media/bytes 검증은 격리 renderer와 core acceptance가 수행한다.
layout은 기존 `eom://schemas/kakao-archive/worker-question-layout/1.0`을 사용한다.
이 연결의 소스/합성 검증은 실제 DB export 수락·권한별 다운로드·운영 활성화 증거가 아니다.

## 저장된 학생 묶음의 실제 입력 물질화

`kakao_pdf_inputs.py`는 Catalog가 `resolve_student`로 해석한 exact 학생 selection을 받아
기존 render projection에 연결한다. 책임은 이 한 입력 경계뿐이며 export 예약·claim·worker
실행·DB 수락을 겸하지 않는다. 실제 학생 원본과 packet이 정본이고 로컬 입력은 일시 materialization이다.

선택한 source의 가용 사진은 ArtifactMemberPointer의 전체 identity를 map key로 사용해 한 번씩
검증된 FD로 읽는다. attachment occurrence는 줄이지 않는다. 본문·사진 순서, 누락 표시와 명시적
transform은 기존 projection이 담당한다. 원본 사진·font를 packet마다 NAS에 재발행하지 않는다.
사진 하나 32MiB, 고유 사진 합계 256MiB와 기존 manifest bound를 지키며 비용은 고유 입력 bytes에
선형이다. 이미지를 decode하거나 줄이거나 캡처하지 않는다.

입력은 설정된 local staging root 아래의 새 owner-only 0700 디렉터리에 exclusive로 작성한다.
NAS 및 staging root 자체를 입력 폴더로 쓰는 것은 거부한다. 기존 파일·링크를 덮지 않고
실패한 staging도 남긴다. font는 고정 설치 profile이 제공한 LocalMember의 hash/size/media와
실제 regular single-link FD를 검증한다. 이 함수가 임의 폰트·runtime 경로를 공개 API 입력으로
허용하는 것은 아니다. 실제 profile 설치는 별도 runtime admission 책임이다.

필수 `authorize` callback은 물질화 전과 후에 현재 source/packet/session을 재검사한다.
완료한 입력은 기존 `KakaoPdfExecutor` → `publish_kakao_pdf`로 넘어간다. 이 adapter 추가는
새 큐나 DB schema를 요구하지 않으며 입력 helper 시험을 실제 Studio 다운로드 성공으로
간주하지 않는다. 단순 임의 경로 전달은 다른 학생/가변 파일/누락 이미지를 구별하지 못해 사용하지 않는다.

## 영속 export와 현재 권한의 다운로드 연결

1. Catalog export owner가 한 학생의 불변 packet subset, 설치 renderer/font/layout pin,
   접수·실행·완료를 소유한다. 기존 executor/publisher를 호출하는 adapter와 상태 저장은 분리한다.
2. 원문은 기존 source/question/packet Artifact이며, 출력은 한 canonical PDF Artifact다.
   DB에는 ID·hash·state·작은 실행 command와 output pointer만 둔다. 본문·사진을 복사하지 않는다.
3. export ID, 실행 attempt ID, output revision ID와 Artifact revision은 별개다. 같은 build key의
   새 접수 key는 기존 export를 가리키는 작은 receipt만 만든다. 과거 실패는 성공으로 바꾸지 않는다.
4. 현재 actor의 binding/학생 subset/source closure와 정확한 packet·출력 schema/hash/lifecycle을
   확인한다. 결과 조회·다운로드도 매번 현재 권한을 확인하며 임의 Artifact/path 입력은 받지 않는다.
5. 접수 replay는 owner+key, cache는 owner+build hash, 목록은 owner+binding+export ID,
   실행은 export PK의 짧은 row lock을 사용한다. 출력 페이지는 한 Artifact manifest의 member map이다.
6. build hash unique constraint와 command receipt unique key, packet/student/Artifact FK를 사용한다.
   목록은 keyset pagination, source 확인은 기존 ordered batch resolver다. 별도 범용 큐는 없다.
7. 접수/선택은 O(선택 질문+고유 source), 저장본 metadata 조회는 indexed lookup,
   파일 열기는 현재 source 확인 후 O(해당 출력 bytes)다. 200 질문의 기존 상한을 유지한다.
8. claim은 PENDING→RUNNING 한 번만 허용한다. 긴 파일 I/O/렌더/발행 중 DB lock을 잡지 않는다.
   bind된 작은 RenderCommand와 exact attempt를 보존하며 재접수·상태 조회는 실행을 시작하지 않는다.
9. 순수 계약은 Catalog contracts, SQL/파일과 기존 publisher 호출은 Catalog adapter,
   실제 프로세스 실행·중단 확인은 Orchestrator다. HTTP가 worker argv/UID/font 경로를 고르지 않는다.
10. 완료 발행 뒤 DB 채택 전 중단이면 원래 attempt의 발행 pointer로 채택을 이어간다.
    RUNNING 시간이 길다는 이유로 새 attempt를 자동 실행하지 않는다. 중단된 실행의 회수는
    실제 process 종료 확인과 기존 recover_finished를 먼저 사용한다. FAILED는 terminal이다.
11. PDF 경로만 저장하는 대안은 학생/버전/재전송을 구별하지 못한다. 기존 공통 Job를 질문
    내용 저장소나 새 범용 scheduler로 확장하는 대신 작은 export owner와 기존 실행 경계를 연결한다.

실패한 attempt는 terminal 불변 기록으로 남긴다. 명시적 retry는 exact 실패 attempt를
기대값으로 받고 새 attempt·순번·fence를 만든다. RUNNING 또는 결과 불명인 attempt를 retry로
우회할 수 없고 완료 build를 다시 실행하지 않는다. 단순 POST replay/GET은 retry 권한이 아니다.
정기 수집 권한·실제 HTTP/GUI 연결과 보호 runtime 활성화는 별도로 검증한다.
