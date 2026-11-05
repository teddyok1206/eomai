# 편집 가능한 HWPX 출력 검증

2026-11-04 UTC. DB 조립 출력의 native 변환·병합 단계에 대한 체크포인트다.
운영 GUI의 합본 제작·다운로드 활성화는 아직 완료 전이며 전체 목표는 진행 중이다.

## 실제 입력과 결과

고유번호 10310·10318의 원본 HWP를 격리된 `eom-hwpx` 계정에서 변환하고 합쳤다.
별도 wheel 설치본은 저장소·NAS·인증 파일·네트워크에 접근하지 않았다. 두 wheel의
설치 RECORD 84개 파일을 검증했다.

| 입력 순서 | 결과 | section 순서 | 내부 그림 파일 | 경과 시간 |
| --- | --- | --- | --- | --- |
| HWP 10310 다음 HWP 10318 | 성공 | 1 다음 2 | 4개 | 1.739초 |
| HWPX 10991 다음 HWP 10318 | 성공 | 1 다음 2 | 4개 | 1.080초 |
| 같은 HWP 두 건 재실행 | 성공 | 1 다음 2 | 4개 | 1.681초 |

HWP 두 건 합본과 재실행의 SHA-256은 모두
`7dcfe3398d1fc5dc667dd95739b5fea1e5a0badecb131486faadbe3ea5521c2a`다.
혼합 합본은 `e556c572c354af5f83521081a4d37bac66257b7db76be468560a07f951d72a3b`다.
시간은 이 두 문항의 단회 설치본 검사 값이며 대량 처리 성능으로 일반화하지 않는다.

소스 HWP에서 계산한 문단·표 구조·수식 script·binary fingerprint 및 도형 개수를
변환 후보의 native XML·binary와 대조했다. 10310은 문단 53개·표 5개·수식 4개·binary
2개, 10318은 문단 55개·표 4개·수식 4개·binary 2개가 일치했다. 문단 fingerprint는
공백을 제외한 multiset이며 읽기 순서 자체를 증명하지 않는다. section 순서와 native
병합의 ID·resource 역매핑은 별도로 검사한다.

## 도구와 검증 경계

선택적 HWP 변환 bundle identity는
`sha256:dd88564a9f0c569264eb4b87820b7bdf04dcd9b2990c414f3301ec51be9713fb`다.
고정 upstream commit과 JAR·Java hash를 검증하며 Builder는 입력이 지정한 임의 실행
경로나 ambient Java 옵션을 사용하지 않는다. `/srv/eom/vendor/hwp2hwpx`의 이 bundle만
root 소유 읽기 전용으로 설치했다. 운영 Python·GPU·Codex 설치본은 교체하지 않았다.

Writer가 생략한 빈 style name, 원래 크기와 같은 축의 `curSz=0`, ZIP 포장만 명시적으로
정규화했다. 다른 XML·그림은 역검증한다. 원본 HWP와 각 변환 HWPX를 동일한 현재 Office
sandbox에서 PDF로 읽었을 때 페이지는 pixel-equal이었다. 합본의 두 번째 페이지에는
metadata 표의 `해설` 두 글자 위치 차이가 남아 있다. 본문·그림의 native 보존과 구분하며
전체 합본의 pixel equality 또는 Hancom 수동 검수 완료로 보고하지 않는다.

격리 설치 검사 1·2차는 `pip --target`의 entry-point RECORD 상대 경로를 검증 스크립트가
잘못 해석하여 실행 전에 종료했다. 실패 기록을 보존하고 그 검증 경로만 수정한 3차에서
위 세 결과를 얻었다. 운영 build나 사용자 실패를 성공으로 바꾸지 않았다.

## 검증 기록과 다음 경계

HWPX 전체와 dependency boundary·개발 문맥 검사는 397개 통과했다. 기존 opt-in root
ownership 검사 1개는 기본 실행에서 제외됐으며, 이번 새 변환 경로는 위 실제 격리 계정
설치본 실행으로 별도 확인했다. 변경 Python 16개 파일의 formatter·ruff, 핵심 source
11개 파일의 mypy가 통과했다. 이 native 변환 단계에서는 DB schema와 영속 build를
변경하지 않았다. 이후 영속 제작 단계의 소스·임시 DB 증거는 아래에 별도로 기록한다.

격리 실행 결과는 `/tmp/eom-curated-installed-probe-20261104-03.jsonl`, 결과 파일은
`/tmp/eom-curated-installed-result-20261104-03/`에 있다. 이는 개발 검증용 local 산출물이며
사용자에게 발행한 NAS Artifact가 아니다. 기존 실패 진단은 같은 이름의 01·02 기록이다.

구현한 가변 canonical Item 출력과 native merger를 curated delivery의 영속 build·claim·중단
복구·Artifact commit, API/BFF·DB 배치 화면·인증 다운로드에 연결한다. DB 검사는 임시
PostgreSQL에서 수행하고, 호환 운영 배포 후 저장된 조립으로 실제 다운로드를 검증해야
전체 목표를 종료할 수 있다.

- [전체 설계와 완료 조건](../architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md)
- [기존 native 합본 체크포인트](CURATED_NATIVE_HWPX_CHECKPOINT_2026-10-31.md)

## 가변 정본 문항 출력

실제 고정 EOM template와 합성 canonical Item을 사용해 표-only, 표·그림·수식·보기,
같은 그림의 두 use, JPEG 서답형 네 형식을 생성했다. 모두 기존 Office sandbox에서
PDF로 열렸다. PNG는 321×189, JPEG는 177×301로 예전 800×500 제약을 쓰지 않았다.
실제 PDF picture use는 첫 페이지에 각각 0·1·2·1개, 해설 페이지에는 0개였다.
같은 그림 두 use는 HWPX 내부 binary 하나를 공유한다. 이 합성 입력은 출제 품질 평가나
실제 등록 문항 생성 실행이 아니다.

가변 출력 추가 후 HWPX 전체·의존 경계·개발 문맥·정본 콘텐츠 검사는 422개 통과했고
기존 opt-in root ownership 검사 1개는 기본 실행에서 제외됐다. 이후 추가한 handoff·재실행·
부분 출력 실패 guard까지 포함한 집중 회귀 70개도 통과했다. 두 수는 중복을 포함한다.

첫 시각 렌더에서 marker 문단의 들여쓰기와 고정 cell 높이 때문에 보기 마지막 줄이
잘렸다. 새 출력 profile에 한정한 local paragraph 속성과 글자 높이 기반 cell 여유를
적용한 뒤 네 형식을 다시 열어 세 진술이 모두 표시됨을 확인했다. 기존 template나
content-team released 출력의 문단/그림 크기는 바꾸지 않았다.

격리 wheel 설치본에서 `render-native-item`이 SUCCEEDED였다. RECORD 91개 파일과
소스에서 검증한 결과와의 output SHA 일치를 확인했다. 수식 3개·content table 1개·그림
1개가 native로 남았다. local 결과는 `/tmp/eom-native-item-installed-20261104-01/`,
Office 검사는 `/tmp/eom-native-item-office-20261104-02/`에 있다. Hancom 수동 확인과
운영 DB 배치 화면의 제작·다운로드 완료로 확대 해석하지 않는다.

12:39 UTC 보존 점검에서 창작 네 슬롯의 유효 lease를 확인했다. 별도로 INDEX metadata
owner는 10:33 UTC `EMBEDDING_BENCHMARK_CHANNEL_EOF`로 종료된 상태였다. 실행 중인
native 수치 unit이 없음을 확인한 뒤 같은 설치본의 공식 INDEX owner를 한 번 시작했다.
12:50 관측에서는 해당 owner가 실행 중이었다. 새 벡터 완료 증거는 아직 이 체크포인트에
없으며 이전 FAILED 기록, native runtime/model pin과 네 슬롯 설정은 변경하지 않았다.

## 저장된 조립의 영속 제작 경계

소스에 `curated-hwpx-build-input/1.0`, `HwpxCuratedBuildRecord`,
`CuratedHwpxApplicationService`와 migration `20261104_0072`를 추가했다. 원본-only 조립에
가짜 Item/시험 Assembly FK를 만들지 않는다. ordered pointer snapshot과 hash, 실제 initiator의
credential 없는 식별 metadata, 예정 Job/Artifact/revision identity를 실행 전에 저장한다.
FIFO claim은 외부 실행 전에 commit하며 같은 build의 dispatch/recovery는 autocommit DB
연결의 nonblocking advisory lock으로 직렬화한다. 상태 조회·같은 요청 replay는 제작을
다시 호출하지 않는다. FAILED와 source snapshot은 DB trigger에서도 불변이다.

Catalog의 제작/조회 권한을 분리하고 저장된 exact published Graph를 재확인한다. 새 Graph
head가 나왔다고 이전 조립을 latest로 바꾸지 않는다. 철회·변경된 source는 명시적으로
거부한다. 최대 200개 원본의 재확인은 한 source/edition join으로 처리하며 Item/Graph도
기존 batch 조회를 재사용한다. status poll에서 원본 문서를 다시 열지 않는다.

guarded disposable PostgreSQL에서 migration upgrade/downgrade/upgrade가 통과했고,
기존 HWPX persistence 6개와 새 queue/recovery 11개가 함께 통과했다. 새 검사는 동시 요청
단일 build, SKIP LOCKED claim, render 후 중단·같은 identity 복구, active unit 대기,
advisory 중복 복구 거부, 조회/replay의 재계산 없음, 실행 중 source 철회의 commit 차단,
실패 불변, NULL 성공
증거 거부, binary DB 값 없음과 partial FIFO query plan을 포함한다. renderer port는 이
DB 검사에서 file-free double이며 실제 한글 파일 생성의 대체 증거가 아니다.

기존 persistence fixture 세 건은 빈 binding manifest/가짜 self-hash, 내용과 무관한 출력,
이전 예외 타입을 사용해 현행 검증과 맞지 않았다. fixture를 정확한 self-hash와 선언된
text-only native XML, 현재 stable error로 수정했으며 운영 검증 규칙을 완화하지 않았다.

source/API/BFF/릴리스 경계 집중 검사 228개와 HWPX/정본/문맥 회귀 425개가 통과했다.
후자의 기존 root ownership opt-in 1개는 제외됐다. 별도 source-head 검사 6개는 고정 숫자
문자열을 찾던 오래된 fixture를 현재 archive-data→installed 비교 경계에 맞춰 검증했다.
이 수들은 중복을 포함하므로 합산하지 않는다. 변경 핵심 source 6개의 mypy도 통과했다.

release operator에 `1.19`/`0072` successor를 추가해 `0071→0072`만 업그레이드하고 같은
head에서는 재실행 없이 검증하게 했다. predecessor schema·callback 의미는 보존한다.
이 체크포인트에서는 **운영 migration/서비스 교체를 하지 않았다**. 실제 Builder/Artifact
commit adapter, API/BFF/DB 배치 화면의 제작·복구·다운로드 연결과 호환 배포·인증된 실제
합본 다운로드 검증은 아직 남아 있으므로 전체 목표는 ACTIVE다.

영속 제작 소스는 `fa5e16dd`로 commit/push했다. 해당 commit의 clean Git archive에서
platform wheel을 만들고 기존 RECORD verifier를 통과했다. wheel SHA는
`eaf5b20e23ad8b3f22a8f022899ae0b6f22bfeb70b12a1753872891fbc8605fa`다.
별도 non-editable 설치본은 `python -I`로 저장소 경로 없이 새 공개 use case와 schema,
metadata DDL·head 0072를 읽었고 설치 RECORD 2,386개 파일의 bytes를 확인했다. 이는
운영 service identity·실제 Builder/HTTPS canary의 대체 증거가 아니다.

검사에만 사용한 guarded 임시 DB는 공식 cleanup으로 제거했다. 운영 DB·NAS 정본은
변경하지 않았고, 기존 창작/INDEX owner의 실행 PID도 이 단계에서 바꾸지 않았다.

## 원본·가변 정본·콘텐츠팀 문항의 실제 혼합 출력

local successor `curated-hwpx-render-request/3.0`과 result/3.0은 native 문서,
canonical Item/1.0, content-team Item/2.0·3.0을 순서대로 함께 받는다. JSON Schema를 먼저
추가하고 같은 bytes를 Builder wheel resource에 둔다. source와 rendered segment SHA를
분리하며 input-plan SHA, 표·수식 수, 실패 placement를 보고한다. 기존 V1/V2의 schema와
의미는 그대로다. 새 private application RPC를 활성화한 것은 아니다.

Manager `CuratedInputMaterializer`는 source/effective/recovery·Markdown과 실제 Item Revision
component를 대조하고 원본/JSON과 그림을 두 단계의 batch member 조회로 읽는다.
각 pointer를 확인한 뒤 같은 local PNG만 공유한다. 공개 source/effective derivation을 다시
대조하고, registered schema 2/3을 generic/1로 재해석하지 않는다. source JSON을 build row에
넣지 않는다. 초기 구현의 반복된 포인터 hash는 map으로 한 번만 처리하며 nested member는
root 내부·symlink 없는 경우만 허용한다. schema 없는 옛 canonical image pointer는 기존
media/hash 계약을 유지하고 문서/JSON에서 schema 검사를 생략하지 않는다.

실제 원본 10310·10318 HWP와 합성 canonical 두 형식·content-team 두 형식을 합쳐
6입력/6section HWPX를 생성했다. 입력 순서는 1–6이며 수식 18개·native tbl 25개·binary
8개다. tbl 수에는 layout table이 포함되며 25개 콘텐츠 표라는 뜻이 아니다. 원본 hash는
변경되지 않았다. handoff/runtime과 generic template는 각 합본에서 한 번 준비했다.

첫 혼합 output은 별도 Office sandbox에서 열렸지만 시각 확인에서 고정 template의 `1.`과
새 번호가 겹치고 nested table의 전체 폭·낮은 label cell 때문에 일부 텍스트가 가려졌다.
새 mixed profile의 `curated_editorial_layout.py`에서만 고정 prefix를 제거하고 width를
바깥 cell 안으로 맞추며 shared row-span grid의 높이를 내용·그림에서 계산했다. derived
line cache도 제거했다. 전후 비교는 텍스트·수식·image viewport와 비-layout 속성을
보존한다. 기존 single/exam renderer와 원본 HWP/HWPX의 geometry는 바꾸지 않았다.

수정 후 동일 입력의 HWPX SHA는
`sha256:c3e55322993c6737faf672680e660ce434d817082dd0410cf0135cd13b4544ba`,
size 427,858 bytes다. 현재 Office sandbox에서도 8page로 열렸고 page 6의 3열 header·
전체 데이터, page 7의 별도 두 그림과 편집 가능한 `(가)/(나)`가 보인다. 두 중복 번호도
없다. PDF 확인은 Hancom 수동 검수·교육 품질 승인·HTTPS 다운로드의 대체 증거가 아니다.

local 실행 증거는 `/tmp/eom-curated-mixed-native-20261104-u37o_3wm/`, Office PDF/PNG는
`/tmp/eom-mixed-native-office-20261104-02/`다. 첫 결과와 시각 오류 진단도 각각
`/tmp/eom-curated-mixed-native-20261104-yxq2l2ma/`,
`/tmp/eom-mixed-native-office-20261104-01/`에 남겼다. 이 파일들은 개발 진단이며 정식
사용자 NAS delivery가 아니다. 새 모델 추론·문항 생성·운영 migration/restart는 없었다.

혼합 출력과 materialization 집중 검사 19개가 통과했다. native/canonical/CTI와 Manager,
영속 metadata·의존·문맥을 포함한 회귀 503개도 통과했다. 기존 opt-in root ownership 1개는
기본 실행에서 제외했다. 추가 member-index 변경은 관련 Manager 회귀로 별도 확인한다.
좁은 module graph에서 빠졌던
DDL test의 실제 FK target import를 명시해 test-order 의존을 제거했다. 테스트용 가짜 FK를
만들거나 운영 DDL을 완화하지 않았다. 같은 입력 re-render의 SHA 동일, replay 재실행 거부,
손상된 blueprint·image·Markdown·symlink의 실패 위치와 부분 성공 미발행을 확인했다.

여전히 남은 범위는 durable queue의 실제 Builder dispatch·중단 결과 복구·Artifact commit
adapter, Catalog application/API/BFF·DB 배치 탭의 제작·상태·다운로드 연결, fixed unit·권한·
설치본·호환 운영 배포와 인증된 실제 saved-assembly build/download다. 이 단계의 port와
local 파일 검증을 전체 기능 완료로 간주하지 않으며 목표는 ACTIVE다.

## 영속 제작·발행 adapter와 DB 화면 연결

Manager의 독립 검증은 기존 bounded ZIP/XML reader를 재사용하고 stdlib만 사용한다.
최종 section 순서와 원문 text·equation·표/그림 geometry, 관측된 resource 대응과 실제
embedded media bytes를 대조한다. Builder의 allocator나 성공 flag를 그대로 신뢰하지
않는다. canonical 출판 event와 content-team semantic 검증도 함께 적용한다. 같은
immutable binary를 문항마다 다시 hash하지 않도록 한 번의 lookup map을 만든다.

실행 전 예정 Job/Artifact/revision을 예약하고 고정 unit의 dispatch observation을 남긴다.
단위 실행이 아직 살아 있으면 같은 handle을 기다린다. 완성 local result 또는 기존
file-set commit intent가 있으면 동일 identity로 발행을 복구한다. 결과 없이 종료한
dispatch와 FAILED는 새 실행으로 바꿔 성공 처리하지 않는다. Artifact 발행은 기존
Catalog/Orchestrator `commit_file_set`만 사용하며 segment별 복제 Artifact는 만들지 않는다.

새 private RPC는 Catalog의 실제 operator 권한과 고정 revision/hash를 확인하고 metadata만
반환한다. 최초 pin 이후의 상태/완료 조회는 새 handoff를 고르지 않는다. nullable source
component를 응답에서 일괄 제거하던 직렬화를 집중 테스트에서 발견해 수정했다. API는
request-only service이며 NAS/변환/Builder에 접근하지 않는다. Runner composition에만
실행·발행을 넣고 단일/시험지/조립의 세 큐 순서를 순환한다.

배치의 저장한 조립 순서 행에 제작·상태 확인·다운로드를 추가했다. 요청 응답 손실 때
동일 key를 재사용하고 상태 재조회는 read-only다. 실패 뒤 다시 제작은 사용자 버튼으로만
새 요청을 만든다. 출력/commit hash와 broker FD/download hash를 검증하며, 큰 합본만
download/2.0의 256MiB bound를 사용한다. 구 download/1.0 bytes와 64MiB는 유지했다.

검증: HWPX/Manager·metadata·의존·문맥 회귀 536 PASS, 기존 root ownership opt-in 1 skip.
별도 guarded PostgreSQL migration 왕복과 persistence/publication 25 PASS(기존 6, queue 11,
publication 8). publication 검사는 실제 Job/Artifact owner와 임시 local artifact store를
쓰며 renderer/acceptance는 test port다. 따라서 그 8개가 실제 문서 렌더링을 증명하지는
않는다. 실제 native/mixed 문서 증거와는 앞 절처럼 별도로 유지한다.

집중 Catalog/API/BFF/DB 화면 검사 35 PASS, 후속 contract·context·정합성 검사 29 PASS,
기존 identity/worker 권한 회귀 124 PASS였다. 이 수는 중복이 있어 합산하지 않는다.
별도 실제 Chromium fixture에서 DB 탐색·배치·제작 버튼·완료 다운로드 링크와 완료
상태 재조회 시 추가 POST 없음, 작은 화면 overflow 없음이 PASS였다. 기존 Playwright
모듈의 browser binary가 없어 처음 실행은 사전 단계에서 실패했고, 임시 test cache에
해당 버전 headless binary만 준비해 다시 실행했다. 제품 dependency/운영 browser는
설치하지 않았다. 이 브라우저의 API는 fixture이며 실제 HTTPS release 증거가 아니다.
변경 Python 44개 파일의 format/lint와 핵심 application/contract 31개 source의 mypy,
별도 Builder interpreter 기준 resource-relocation source의 mypy도 PASS였다.

현재 남은 gate는 clean-commit wheel/RECORD·service identity 설치 검증, 새 고정 unit과
권한의 실제 검사, migration 72와 호환 runtime 배포, 인증된 saved-assembly 제작·정식
Artifact commit·실제 다운로드 SHA다. 운영 migration/API/Web/HWPX 교체는 아직 하지
않았고 전체 목표는 ACTIVE다. 기존 슬롯·정본·실패 이력·벡터를 삭제/재생성하지 않았다.

## 호환 운영 배포 체크포인트 — 실제 합본 acceptance는 미완료

위 절의 미배포 상태 이후 다음 설치·활성화를 수행했다. 전체 목표는 계속 ACTIVE이며,
이 절은 파일을 실제 내려받았다는 완료 증거가 아니다.

| component | 실제 설치 source / 증거 |
| --- | --- |
| Builder·HWPX contracts | `836b6527e501e5b799b4786f97163c0443e24839`; 두 wheel 전체 member bytes 대조, 별도 `eom-hwpx` identity의 새 CLI 확인 |
| API·공유 Platform·API contracts | `9370519199ad8c69df95e23194b0c8f6b39073cf`; clean archive build·RECORD·설치 파일 대조 |
| Catalog·QUERY metadata owner | 위 release의 보호된 비편집 설치 prefix; 실제 API provider 코드 hash와 설정 hash를 함께 갱신 |
| Web 최초 연결 | `93705191`; 서비스 identity의 설치 검증 55 files, HTTPS READY와 실제 delivery JS SHA 일치 |
| DB | `20261104_0072`; 보호된 release operator `1.19`의 ADMIT·정확한 71→72 upgrade·verify 통과 |

API/Catalog/HWPX runtime DB role을 기존 공식 bootstrap으로 reconcile했다. 실제 Catalog 및
Manager identity의 read-only 권한 검사가 통과했고, Manager는 새 queue UPDATE만 허용되고
INSERT는 거부됨을 확인했다. 실제 PID를 subject로 하는 polkit 검사에서도 Manager의 새
curated unit start는 허용, Workflow identity의 같은 start는 거부됐다. 이 권한 검사는
unit을 실행하거나 가짜 build row를 만들지 않는다.

진행 중인 4개 worker를 중단하지 않기 위해 창작 producer만 지원된 graceful stop으로
새 투입을 멈췄다. 기존 worker lease·shared command·QUERY/Builder 실행이 모두 0으로
정상 종료한 시점에 공유 서비스를 교체했다. 이후 창작 producer와 기존 runner들을
재개했다. INDEX PID `2473213`·InvocationID·고정 수치 환경·원본 설정 hash는 전후 같았다.
기출/창작 원본·Graph·실패 기록·기존 벡터의 삭제나 새 모델 실행은 없었다.
재개 직후 producer의 `verified_count`는 이번 프로세스의 재확인 수이며, 기존 등록 수를
삭제하거나 0으로 수정한 것이 아니다. 운영 관측은 정본 acceptance와 구별한다.

Builder wheel 설치 후 owner용 layout checker가 private operator stage를 읽지 못하는
배포 스크립트 오류가 한 번 있었다. 실제 wheel bytes와 기존 rollback archive를 먼저
확인하고, credential이 없는 checker만 root-owned libexec로 설치해 정규화 단계부터
재개했다. wheel을 다시 설치하지 않았고, private stage 접근 권한을 완화하지 않았다.
API/Web 활성화 전 이 설치 검증과 unit 설치를 완료했다. 실패 로그도 보존한다.

기출 선택의 후속 화면 검사에서 예전 `hwpx_exam_eligible`가 새 curated 합본 선택까지
막고 있음을 확인했다. 그 값은 기존 생산/시험지 계약 그대로 유지하고, DB의 조립
선택에서만 예전 flag를 입장권으로 쓰지 않도록 했다. 선택은 Catalog가 pin하고 실제
파일/schema/표현의 제작 가능 여부는 새 delivery owner가 검증한다. 예전 flag=false인
기출 fixture로도 실제 Chromium에서 담기·저장을 확인했으며 관련 14 tests가 PASS다.
해당 Web 후속 source는 `098ef841a2765d70939cc6573a4fa848d69fc55c`다. 이 wheel도 별도
설치 simulation과 service identity 55-file 검증 후 Web만 교체했다. API/QUERY pin과
실행 중인 INDEX/worker는 이 화면 수정 때문에 다시 바꾸거나 재시작하지 않았다.

증거 위치(비밀값이나 전체 문항을 이 문서에 복사하지 않음):

- `/var/lib/eom-curated72-release-20261104/`: 보호된 이전 설정·rollback·배포 기록.
- `/var/lib/eom-curated72-builder-20261104/installed.json`: Builder wheel/unit hash와 보존한 실행 identity.
- `/tmp/eom-curated72-installed-verify-20261104-01.log`: 실제 role·polkit·설치 source·INDEX 보존 검사.
- `/tmp/eom-curated72-release-activate-20261104-01.log`: 정확한 migration/role callback과 활성화 결과.
- `/tmp/eom-curated-web-build-20261104-02.log`: 후속 Web wheel 및 별도 설치 simulation.
- `/tmp/eom-curated72-testdb-cleanup-20261104-01.log`: disposable DB cleanup PASS; 운영 DB/자료 삭제 없음.

아직 남은 gate는 실제 HTTPS guiadmin session으로 저장된 원본 10310·10318 조립과
기출·창작 원본·AI 혼합 조립을 제작하고, Runner→고정 Builder→독립 검증→정식 Artifact
commit→같은 SHA의 다운로드까지 확인하는 것이다. 동일 key 재전송·완료 재조회가
새 render를 만들지 않는지도 실제 build identity로 확인한다. 인증 입력은 tmux `EOM`
`hwpx-check` 창에 준비했고 세션은 검증 프로세스 메모리에만 유지한다. 인증 성공,
실제 파일 생성·저장·다운로드나 Hancom 육안 확인을 아직 PASS로 적지 않는다.

## 실제 HTTPS 합본 발행과 다운로드 — 11월 4일 후속 증거

앞 절의 미검증 상태 이후 두 종류의 실제 저장 순서가 공식 운영 경로를 완주했다.
실제 guiadmin HTTPS 로그인으로 요청했고, 비밀번호는 입력 직후 폐기했으며 세션은
검증 프로세스 메모리에만 유지했다. 두 결과 확인 후 이 테스트 세션만 정상 로그아웃했다.
비밀번호 변경·타인 권한 사용·가짜 DB 입력·모델 추론은 하지 않았다.

| 사례 | build / 실제 내려받은 SHA-256 | 결과 |
| --- | --- | --- |
| 원본 10310·10318 HWP | `hwpxbuild_003ef6e2234e48ccb7889eff503fe104` / `sha256:7dcfe3398d1fc5dc667dd95739b5fea1e5a0badecb131486faadbe3ea5521c2a` | SUCCEEDED/PASS; 390,542 bytes; 2 sections; package 내부 binary 4개 |
| 창작 원본·기출·등록 창작 | `hwpxbuild_ced4c27ad2e44a518ba1fd2d3320b5df` / `sha256:cd5f48de4e5dc2ffedab3acf70484a21d6d7dba4cbe9a6807e78901d46ea0547` | SUCCEEDED/PASS; 269,893 bytes; 3 sections; package 내부 binary 2개 |

두 사례 모두 Manager→고정 Builder→독립 내용/그림/순서 검증→기존 Artifact commit owner를
거쳤다. HTTPS download bytes와 committed output SHA가 같았다. 같은 idempotency key의
재전송은 동일 build/SHA를 반환했고, 완료 상태 두 번 재조회와 latest 조회에서도 build와
resource version이 바뀌지 않았다. 완료 조회를 재제작으로 구현하지 않았다.

이 **실제 다운로드 파일**을 기존 격리 Office 변환기로 읽었다. 원본 합본은 2 pages,
혼합은 5 pages였다. 후자는 native 원본 1쪽 뒤 기출 문제/해설, 등록 창작 문제/해설이
순서대로 읽혔고 native 표·텍스트가 보였다. 원본의 편집/참고 자료란도 원본 문서 그대로
보존했다. 이것은 Office 읽기/페이지 확인이지 Hancom 수동 편집 품질 PASS가 아니다.
`MANUAL_HANCOM_REVIEW=NOT_RECORDED`로 유지한다.

### 실제 실행에서 수정한 두 경계

- 좁은 API import graph에서 curated queue의 FK 대상 Table이 빠졌다. 실 Table/column을
  직접 참조하도록 고쳐 subprocess cold-import 회귀로 고정했다. DDL/schema bytes는
  바뀌지 않았다. source `fd658b03da05959cf2860e9d5a30797ae2c3a3ca`다.
- Manager가 저장된 placement를 재인가할 때 필요한 SELECT가 role matrix에서 빠졌다.
  `curated_document_assembly_placements`의 SELECT만 기존 공식 role bootstrap으로
  reconcile했다. 새 INSERT/UPDATE·credential 권한이나 migration은 추가하지 않았다.
  원래 RUNNING build가 **같은 identity**로 복구돼 위 원본 합본으로 발행됐다.

API에 별도 `PYTHONPATH` drop-in을 붙이는 초기 설치 시도는 QUERY provider의 기존
`DropInPaths` 검증과 호환되지 않았다. 이를 철회하고 원래 호환 shared release 경로를
사용했다. 검증기를 완화하지 않았으며 실패/철회 기록도 보존했다. 공유 배포는 기존
작업의 정상 drain 뒤 수행했고 INDEX identity와 수치 runtime은 바꾸지 않았다.

최종 확인된 component 조합은 API/공유 Platform/API contracts `fd658b03`, 보호된
Catalog/QUERY metadata owner `93705191`, Builder/HWPX contracts `836b6527`, Web
`00e7f41564403cd170cdcf3c26f4bf7725d78f0b`, Manager role 설정 `8bc4936f`다. DB head는
`20261104_0072`다. Web 후속 수정에서는 등록 문항 상세의 예전 exam eligibility 제한도
제거했다. AI/창작을 포함한 **실제 Graph 후보**의 조립 담기는 같은 새 delivery admission을
쓰며 옛 시험지 eligibility 값을 새 합본의 입장권으로 쓰지 않는다. Chromium fixture와
BFF 집중 13 tests, 설치 wheel/RECORD와 Web identity의 55 files 확인 후 Web만 배포했다.
이 Web 배포 전후 API·창작 producer·INDEX PID/InvocationID는 같았다.

### 입력 문제와 남은 AI 운영 검증

첫 혼합 build `hwpxbuild_b631876174334129a9b51d5185c9d3ca`는 FAILED로 보존했다.
선택한 기출의 canonical 그림에는 500×230이 기록돼 있지만 exact PNG bytes는 시험지
전체 페이지인 1653×2337이었다. 공식 Preview/media 읽기로 확인한 인접 세 기출도 같은
종류의 불일치가 있었다. 실제 Builder는 두 번째 입력에서 이를 거부했다. 원본·Graph·
그림 metadata를 고치거나 전체 페이지를 문제 그림으로 강제 변환하지 않았다.

정상 입력인 다섯 번째 기출을 **명시적으로 별도 선택**해 위 성공 혼합을 만들었다.
원 실패의 identity/상태를 바꾸지 않았고, 성공 사례를 모든 기출의 그림 정합성이
보장된다는 증거로 확대하지 않는다. 정확한 그림과 다른 페이지 이미지를 묵인하지 않는
회귀도 추가했다. 이 legacy 입력 정비는 출력기의 그림 검사 완화와 다른 작업이다.

현재 일반 AI 목록의 정본은 두 개다. 하나는 승인 전 @12, 다른 하나는 승인된 @10이며
둘 다 실제 knowledge-analysis run이 없다. 현재 Graph 후보에도 포함되지 않는다.
읽기 전용 metadata 확인과 실제 operator의 공식 등록→Graph 조회가 일치했다.
따라서 **AI를 넣은 운영 저장 순서/합본의 실증은 아직 미완료**다. 새 분석·Graph 출판,
기존 승인 상태 변경이나 노드 위조를 HWPX 검증 편의상 실행하지 않았다.

AI에서 쓰는 콘텐츠팀 2/3의 파일 출력 자체는 구분해 검증했다. opt-in guarded PostgreSQL
테스트가 native·가변 canonical·콘텐츠팀 2/3의 실제 materialization→설치된 격리 Builder→
Manager 독립 acceptance→임시 Artifact store의 실제 commit→FD download를 완주했다.
같은 identity 재호출에서 render 1회/Artifact revision 1개였고 표·수식·embedded binary가
있는 5 sections였다. 이 테스트의 source는 합성 fixture이며 운영 AI 문항으로 표현하지
않는다. 기존 중단/발행 suite와 합쳐 9 PASS였고 disposable DB는 정리했다. native/mixed
파일 회귀 35 PASS도 별도 확인했다. production DB에는 pytest를 실행하지 않았다.

### 완료 판정과 증거 위치

전체 목표는 ACTIVE다. 실제 저장 순서 발행·다운로드 gate는 위 두 사례에서 PASS지만,
기존 체크포인트가 명시한 AI 포함 운영 사례는 선행 Graph source가 없어 아직 닫지 않는다.
AI용 새 분석·정식 Graph 등록을 이 목표에 추가할지 범위를 정한 뒤 해당 실증을 이어간다.
지원하지 않는 source를 다른 종류로 이름만 바꾸거나 가짜 Graph를 만들지 않는다.

- `/tmp/eom-curated72-https-20261104/acceptance.json`: 원본 실제 발행/재조회 증거.
- `/tmp/eom-curated72-https-20261104/verified-mixed-acceptance.json`: 실제 혼합 발행 증거.
- `/tmp/eom-curated72-https-20261104/past-input-observations.json`: 내용 없는 그림 metadata 예외.
- `/tmp/eom-curated72-live-office-20261104/`: 위 실제 다운로드의 Office PDF/페이지 진단.
- `/var/lib/eom-curated72-cold-release-20261104/activated.json`: 호환 shared rollout.
- `/var/lib/eom-curated72-role-monitor-8bc4936f-20261104/applied.json`: 최소 role/누적 보고 수정.
- `/var/lib/eom-curated72-web-registration-20261104/activated.json`: 후속 Web-only 배포와 보존 identity.
- `/tmp/eom-curated72-real-render-testdb-20261104-01.log`: 9 PASS, migration 왕복; 첫 cleanup invocation 오류도 보존.
- `/tmp/eom-curated72-real-render-cleanup-20261104-01.log`: 정확한 disposable DB만 cleanup PASS.

슬롯/GPU의 10분 보고는 계속 유지한다. 누적 Graph는 current snapshot의 accepted source
membership에서 계산하며 재시작별 확인 수를 누적으로 보이지 않는다. INDEX가 active인
것과 실제 GPU 연산 중인 것은 별개이며, 기출 binding 진행과 순간 GPU 사용률을 따로 보고한다.

## 후속 배점 표시 수정과 호환 운영 반영

실제 혼합 파일의 기출 발문에는 원문에 이미 있는 `[2점]` 뒤에 출력기가 배점을 다시
붙인 부분이 보였다. 정본을 고치지 않고 `native_item_format.py`의 기존 publication 표현
함수에서 동일 배점 suffix는 그대로 한 번만 사용하도록 수정했다. 원문 표기와 정본
배점이 다르면 어느 쪽을 임의 채택하지 않고 명시적으로 거부한다. 내부 source text와
완성된 기존 build bytes·identity는 바꾸지 않는다. 새 의존성/schema/DB 변경은 없다.

보통/공백 포함/줄바꿈 포함 원문 suffix의 실제 native 렌더, 배점 충돌 거부를 추가해
native/mixed/materialization 39 tests와 독립 acceptance 9 tests가 통과했다. 핵심 pure
함수의 mypy와 lint/format도 PASS다. Builder와 Manager가 공유하는 함수여서 두 wheel의
실제 코드 bytes와 전체 RECORD를 대조한 뒤 함께 반영했다.

API·공유 Platform·API contracts와 Builder/HWPX contracts의 source
`c0b9d0b57b31f7de408e83ff365e147b6766ca33`을 호환 배포했다. Web은 `00e7f415`, 보호된
Catalog/QUERY metadata owner는 `93705191`, migration은 `20261104_0072` 그대로다.
유효 lease·처리 중 command·실제 worker/Builder unit이 모두 없음을 확인하고 교체했다.
INDEX의 PID/InvocationID·설정·수치 환경은 같았다. 창작 producer는 배포 **전부터**
`AUTOMATIC_ALIGNMENT_NEIGHBORHOOD_TOO_LARGE`로 중단돼 있었고 그 실패 상태도 보존했다.
새 migration·DB 상태 직접 변경·계정 인증 변경·새 모델 실행은 없다.

동일한 실제 입력 세 개를 새 local probe identity로 stage해 설치된 고정 unit에서 출력했다.
Manager 독립 검증 PASS, 3 sections·native table 8·수식 4·binary 2, 269,889 bytes,
SHA `sha256:6b31275a2c08926c5b14a229f4d56453afccd9c9a77ad5eb616dc832505ab922`였다.
해당 문제 section의 `[2점]`은 두 번에서 한 번이 됐다. 원래 성공 파일의 SHA는 그대로였다.
이 probe는 DB/NAS 발행이 없으며 새 인증된 HTTPS delivery라고 표현하지 않는다.
실제 API local READY·HTTPS live·QUERY/Manager active도 배포 후 확인했다.

증거: `/var/lib/eom-curated-score-release-20261104/activated.json`, 같은 디렉터리의
`fixed-real-input-probe.json`, `/tmp/eom-curated-score-compatible-release-20261104-01.log`,
`/tmp/eom-curated-score-fixed-input-probe-20261104-01.log`.

### 목표 종료 감사

| 요구 | 현재 판정 |
| --- | --- |
| HWP/HWPX 원본의 편집 가능한 병합 | 실제 원본 변환·native 역검증·원본 합본 HTTPS 발행 PASS; page PNG 대체 없음 |
| 가변 글·표·수식·그림·해설과 순서 | 실제 기출/등록 창작 합본·설치 고정 unit·canonical/CTI2/3 렌더 및 독립 검증 PASS |
| 영속 발행·복구·멱등·다운로드 | disposable PostgreSQL, 실제 같은 build 복구, 정식 Artifact/download SHA 및 재조회 PASS |
| 설치본·권한·API/BFF·GUI | 호환 wheel/RECORD·role·fixed unit·Chromium와 실제 HTTPS 발행 PASS |
| 정본·실패 이력·INDEX 보존 | 기존 SHA/실패와 INDEX PID/Invocation/config 보존 PASS |
| 실제 AI를 포함한 운영 합본 | **미완료**: 현재 AI 두 개 모두 accepted analysis/Graph source 없음; 합성 CTI 테스트로 대체하지 않음 |

최종 read-only 재조회도 같은 AI 선행조건을 확인했다
(`/tmp/eom-curated-score-ai-prerequisites-20261104-01.log`). 새 AI 분석·정식 Graph 등록의
추가 범위와 실제 관리자 인증 확인이 필요하다. 다른 사용자의 세션을 가져오거나 가짜
Graph를 만들지 않으며 전체 목표를 완료로 판정하지 않는다.

## 출제의도 native cell 확정과 Builder-only 운영 반영 — 2026-11-05 UTC

사용자는 `intent-box-table-check.hwpx`에서 해설 위 출제의도 본문이 Hancom에 정상
표시됨을 확인하고 이 방식을 운영에 반영하도록 승인했다. 이 수동 PASS는 이번 3문항
샘플의 출제의도 표시 범위이며, 다른 출력·교육 품질·AI 합본 gate의 승인을 대신하지 않는다.
최초 캐시 제거 파일의 실패 기록과 사용자가 반환한 같은 SHA의 파일은 보존했다.

운영 Builder source는 `ad761dc5cddb829b1df3909389a9ab587466705e`, wheel SHA-256은
`5925ebd00442728f5088a222f03c9def7a87add7ad94d8e105a9c721d3fafb65`다. 설치 전후 비교에서
기존 코드 변경은 `hwp_conversion_package.py` 하나, 추가는 `native_intent_box.py` 하나뿐이며
다른 Builder 코드와 HWPX contracts bytes는 같았다. 계약 package·변환 JAR·Kordoc·API·Web·
Catalog·Codex·INDEX/QUERY 수치 환경은 설치하거나 교체하지 않았다. 실행 중 Builder가 없는
시점에 HWPX 제작 관리자만 잠깐 정지하고 기존 owner의 non-editable wheel 설치 및 layout
검사를 수행했다. API·Web·창작 producer·INDEX·QUERY의 PID/InvocationID와 보호된 설정은
그대로였고 HWPX 관리자는 다시 active, HTTPS health는 200이었다.

설치된 모듈로 기존 확인용 입력을 다시 처리했을 때 사용자 승인 파일과 동일한 SHA
`8291f2ba23b48c64b83b571c2cb2c2abc32f812e89b98da3b8580112a7596ec6`가 나왔다. 설치본
집중 회귀 71개도 통과했다. 실제 원본 HWP 3건을 새 local workspace로 고정해 운영과 같은
`eom-hwpx-curated@` 격리 unit에서 변환·합쳤고 Manager 독립 package acceptance를 통과했다.
결과는 3 sections·그림 binary 9·native table 15·수식 53, 출제의도 native cell 3곳이었다.
이 local probe는 `hwpxbuild_a4d7ecdc95ae5d80ac83aa7adba79cb5`, SHA는
`a467e6c714ae92c355e57b070e08ad1d46553b67f469408efe49ddd2e51c9d00`다. 문서 내부의
identity 재배정 때문에 승인 파일과 package SHA가 다르며, 위 설치 모듈의 동일-byte 검사와
각 입력/출력의 독립 역검증을 각각 기록했다. DB 쓰기·NAS 발행·새 모델 실행은 없다.

첫 설치본 probe는 operator fixture의 `inputs` 디렉터리가 umask로 `0700`이 되어 Builder
계정이 읽지 못해 입력 단계에서 실패했다. 정식 입력이나 제품 코드를 바꾸지 않고 새
probe identity의 fixture 디렉터리만 정확한 `0750`으로 준비해 재검증했다. 첫 FAILED local
결과는 그대로 남겼으며 원래 성공 합본도 같은 SHA로 보존했다.

이후 **새로 제작하는 합본**에서 이 방식이 적용된다. 기존 성공 build·다운로드 bytes는
불변으로 유지하고 완료 결과 조회·멱등 재전송을 재렌더 경로로 바꾸지 않는다. 원래 파일을
교체하려면 사용자 액션의 별도 새 제작을 사용한다. 새 DB migration/권한/공개 schema는 없다.

배포·보존·rollback 기록은 `/var/lib/eom-hwpx-intent-native-cell-release-20261105/`의
`prepared.json`, `installed.json`, `real-input-probe.json`, `activated.json`에 있다. 이전 Builder
archive와 정확한 이전 wheel을 보관했다. 로컬 검증 기록은
`/tmp/eom-intent-installed-output-20261105.log`,
`/tmp/eom-intent-installed-regression-20261105.log`,
`/tmp/eom-intent-installed-real-input-20261105-02.log`에 있다.
