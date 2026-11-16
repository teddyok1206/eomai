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
