# 편집 가능한 HWPX 출력 검증

2026-11-04 UTC. DB 조립 출력의 native 변환·병합 단계에 대한 체크포인트다.
운영 GUI의 합본 제작·다운로드는 아직 연결 전이며 전체 목표는 진행 중이다.

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
