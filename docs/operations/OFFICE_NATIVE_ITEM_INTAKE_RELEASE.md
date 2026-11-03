# 한글 원본 그림 신규 입력 릴리스

2026-11-03 UTC. 설계 기준은
[창작 원문 이미지 복구](../architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md)의
‘향후 한글 문항 신규 입력 설계’다. 기존 333문항 복구와 다른 **새 입력 경로**다.

## 현재 사용자 선택 범위와 운영 결론

사용자가 확정한 범위는 **원본 그림 등록·4슬롯 풀이/Graph 등록·증분 임베딩 우선**이다.
가변 구조 창작 정본의 HWPX 재출력 renderer 확장은 후속 과제다. 아래 시간순 기록에
남은 HWPX 출력 PENDING/FAILED를 이번 우선 범위의 미완료로 다시 편입하지 않는다.

- 실제 HWP 본문 그림의 신규 정본 등록·API 서비스 identity의 Preview/media/재조회가
  성공했다. 새 등록 문항은 기존 333문항 복구 override에 의존하지 않는다.
- 실제 HWPX 11931도 등록됐다. 본문은 native 표이며, 원본 페이지와 내장 PNG 2개를
  직접 대조해 두 이미지가 **참고 기출·그 해설**임을 확인했다. 본문 image block 0개가
  올바른 결과다. 이를 HWPX 본문 PNG 전달 성공으로 확대하지 않는다.
- 03/04/05/06의 실제 일반 작업 lease 4개 동시 실행과 새 native 출처 3건의 실제
  CUDA encoding/committed index5 binding을 확인했다. INDEX-only 연속 reader도 인계했다.
- 전체 1,053개 처리·전수 임베딩 완료는 주장하지 않는다. 기존 순차 owner와 INDEX,
  두 개의 30분 관측 timer를 계속 유지한다. 원본 해석/변환 실패는 별도 예외로 보존한다.

현재 설치는 shared API/Catalog/runner/creative/QUERY metadata `31073cb4`, INDEX metadata
`fd3f0622`, Web `e22ca6e0`, 물리 수치 controller `a70cd434`, DB head
`20261103_0071`이다. Git의 이후 test/docs commit과 실제 설치 source를 구분한다.

## 범위와 소유자

기존 source 권한/원본 resolver → 격리된 HWP5/HWPX 사용 개체 추출 →
Orchestrator 원본 이미지 Artifact 발행 → 기존 분석 worker의 본문 use 선택 →
Catalog 정본 등록 → 기존 Preview/media/HWPX 경로를 사용한다.
이미지 bytes를 PostgreSQL에 넣거나 선택된 PNG를 별도 Artifact에 다시 복사하지 않는다.
파일 확장자가 HWP여도 ZIP/HWPX signature면 HWPX로 해석한다.

| 새 입력 핀 | 값 |
| --- | --- |
| Workflow | `external-item-learning/3.0.0` |
| 실행 설정 | `creative-office-learning` |
| worker protocol / 결과 | `workflow-role/1.36.0` / `external-item-learning-result@3.0` |
| 입력 / plan | `external-item-learning-work-input/2.0` / `resolved-execution-plan/32.0` |
| 그림 목록 / 선택 | `office-picture-use-catalog/1.0` / `office-visual-bindings/1.0` |
| 정본 등록 Pack | `external-creative-item/1.2.0` |
| 새 순차 모집단 | `creative-learning-cohort/2.0`, `office-cohort.json` |

내부 풀이·원문 보고서는 V2를 그대로 쓴다. 새 cohort2는 기존 target/owner/policy
metadata를 바꾸지 않고 native 실행 프로필을 명시한다. 기존 cohort1·continuation·
Workflow1/2·Pack1.0/1.1은 제자리 변경하지 않는다. 새 DB·migration·queue는 없다.

## 설치와 활성화

1. 기존 API build 절차로 non-editable wheel/RECORD와 과거·신규 Workflow를 검사한다.
   API/platform/Catalog/runner가 새 입력·plan·결과를 함께 읽을 수 있어야 한다.
2. CPU 전용 Office tool prefix를 root 소유의
   `/opt/eom/office-image-tools/<source-commit>/site-packages`에 설치·검증한다.
   HWP OLE 읽기는 이미 채택한 optional `olefile==0.47`만 사용한다. CUDA나
   INDEX/QUERY 수치 실행환경에는 설치하지 않는다.
   실행 Python은 같은 tool release의 `runtime/bin/python`이다. root 소유의
   system Python 기반 CPU venv에 기존 Pillow/jsonschema/Pydantic/olefile만
   설치한다. 개발자가 소유한 HWPX Conda Python을 운영 기본값으로 쓰지 않는다.
3. 새 입력을 준비하는 owner에 `EOM_OFFICE_IMAGE_TOOL_ROOT`로 그 **정확한 prefix**를
   지정한다. 값은 release 상위 폴더가 아니라 `/opt/eom/office-image-tools/<commit>/site-packages`
   전체 경로다. 해석은 기존 eom-image systemd sandbox에서만 수행한다.
4. 기존 `eomctl creative-learning prepare` application 경계에
   `config/workflows/external-item-learning.v3.yaml`과
   `config/control-plane/creative-office-learning-v1`를 전달한다.
   source 선택은 기존 `ExternalItemLearningStartV1` 그대로다. 실제 Studio operator를
   인증·재확인하며 모델·capacity는 검증된 기존 source-analysis 설정을 그대로 상속한다.
5. 준비와 실행은 기존처럼 분리된다. `start`는 준비된 정확한 selection만 실행한다.
   완료 후 등록에는 Pack1.2를 전달한다. 새 bulk 입력도 이 seed를 등록한 뒤 기존
   `admit-cohort`로 명시적 cohort2를 만들며, 과거 모집단을 자동 승격하지 않는다.

정상 새 Hancom 입력에 과거 Workflow2의 PDF bbox crop 경로를 선택하지 않는다.
과거 pinned 실행의 재조회·복구를 위해 그 경로 자체는 보존한다. PDF-only 입력과
자료 검토/한글 수정 기능을 이 릴리스에서 재설계하지 않는다.

## 선택·잘림 방지

실제 `picture_use_id`는 원본 hash와 native locator에서 정해지며 image hash와 다르다.
본문·참고 기출이 같은 바이너리를 재사용해도 별도 use다. 목록의 paragraph anchor,
배치·viewport·회전과 전체 페이지를 함께 보고 본문 use만 선택한다. viewport는
HWP 원본/reference image extent, HWPX `imgDim` 기준이며 편집된 border 크기가 아니다.
전체 원본은 보존하고 검증된 viewport/직각 회전·반전만 파생 PNG로 만든다.

본문 그림 binding은 block 순서·TARGET_ITEM region·실제 use·원본 hash를 닫는다.
참고 기출/해설, 전체 문항 screenshot, 추정된 반쪽 crop, 같은 composite의 중복 panel은
허용하지 않는다. native group/별도 라벨·도형이 정확히 합성되지 않거나 geometry가
지원되지 않으면 원문·풀이·conflict를 보존하고 기존 NEEDS_DECISION/content-unavailable
경계로 격리한다. 빈 그림 또는 잘린 후보를 정상 HWPX로 승격하지 않는다.
표·수식은 읽을 수 있으면 기존 editable 구조로 남기고 PNG인 것처럼 만들지 않는다.

## 검증 기록 — 배포 전

- HWP5/HWPX 실제 원본 6개를 격리 prefix `d9c52c64fb9ba0e272e5bb03893ed10dcb5641aa`로
  읽어 18개 사용 개체의 이미지·viewport·방향·배치를 확인했다. 이는 private inventory이며
  참고 기출까지 모두 본문으로 승인했다는 뜻이 아니다.
- 원본 추출/위험 입력/좌표·회전 단위 테스트 50 PASS.
- 기존 출제·추출·등록·복구·materializer 집중 회귀 303 PASS.
- 새 원본 선택/사용자 권한/새 cohort/Pack/결과 family 단위 검증을 추가했다.
- 새 disposable PostgreSQL에서 원본 이미지 commit 중단 → 두 동시 resume → 같은
  Artifact 재사용 → 등록용 동일 PNG pointer를 확인했다. 기존 등록·crop 발행 회귀도 PASS.
- 과거 36개 role protocol schema bundle hash는 설치 predecessor와 동일하다.

위 결과는 운영 활성화의 대체 증거가 아니다. 실제 신규 등록 → Preview/media →
새 HWPX 내부 PNG·다운로드 SHA는 아래 완료 기록에 별도로 남긴다.

## 배포/rollback 불변식

진행 중인 수치 실행의 PID·InvocationID·고정 실행환경, 현재 풀이보고서/Graph,
기존 Item과 과거 실패 이력을 보존한다. metadata owner의 호환 인계는 해당 finite
Workflow가 완료되고 실제 수치 자식도 없는 경계에서만 한다. coordinator PID까지
영구 고정한다는 뜻은 아니다. 소비자 QUERY는 유효 작업과 실제 실행이 없는 시점에만
호환 application release로 맞추며 numerical runtime pin은 바꾸지 않는다.
rollback은 보관된 호환 wheel/config로 서비스 설치를 복원하는 것이며 새 Artifact나
과거 실패를 삭제·성공 재해석하는 것이 아니다.

## 실제 완료 기록

2026-11-03 19:18 UTC 체크포인트. **배포·등록·그림 조회와 HWPX 출력 성공은 다르다.**

| 경계 | 실제 결과 |
| --- | --- |
| API/Web/Catalog/Workflow/HWPX queue 호환 설치 | `e22ca6e0af37d383daab24d24b3f3b796ebaedd3`, migration `20261103_0070` |
| CPU Office parser | 보호된 CPU prefix `6e3b5860497d2106ed529cb78bf9ff8e526b4978`; 실제 HWP/HWPX 6건 추출 PASS, 일반 회색조 원본 2건 추가 PASS |
| 신규 Workflow3 등록 | 원본 번호 11744–11749, 6건 실제 등록. 완료 보고서를 새 identity로 재생성하지 않음 |
| 실제 API 서비스 identity → Catalog 그림 조회 | 11744·11745의 Preview/content/PNG SHA·크기·재조회 PASS. 원본 이미지 목록 Artifact의 동일 member를 재사용 |
| 신규 HWPX 출력 | **PENDING / 실제 canary 2건 FAILED 보존.** 아래 확인된 출력 경계 참조 |
| creative continuation | `creative-learning-continuation/1.2`, `rev_a6fe27b5036d4595833680588c01b634`, original target set 1,053 유지 |
| 4슬롯 모델 호환성 | 01–06 기존 7개 model/effort 조합과 03 xhigh 추가 조합의 실제 8회 PASS. 이전 scope를 무근거 복사하지 않고 새 committed proof로 모두 재확인 |
| Graph publication owner | `8d19ae309ba6609516bb22efbdb5c4e8d95e8cde` 설치·재개. 실제 4건 publication/4개 동시 일반 작업/새 임베딩 capture는 관측 중 |

그림 조회 canary는 이전 복구 override가 아니라 신규 정본 자체를 읽었다.
11744는 `itemrev_945f90d669784350b3bfba838ba63f71`, 11745는
`itemrev_9672ead850d0493c8af2282199e3011e`다. service identity의 실제 bytes를 읽어
등록된 member SHA·PNG header 크기와 대조했다. 이 기록은 브라우저 또는 Hancom 수동
육안 PASS를 주장하지 않는다.

4슬롯 공식 호환성 보고서는 `artifact_d35dbfb821144414b8117fabe415efc0` /
`rev_866ba6c9b1714316b450973418aa2460` / `report.json`, SHA
`62bae4c766f7f50f761cc91d7484cc90c63e504a0b9809748ed3fa4ce26f6fe1`이다.
03의 물리 image role은 유지하며 해당 보고서의 xhigh support 용도만 허용했다.
첫 진단의 4개 PASS checkpoint는 OBSERVE가 다른 binding version을 갱신해 후속
검사와 연결되지 못했다. 그 checkpoint를 고치지 않고 정기 관측 담당을 잠깐 멈춘
새 진단 8회로 전체를 재확인했다. 정기 관측 담당은 다시 시작했다. 총 실제 진단
추론은 12회이며, 준비/빈 디렉터리 오류 두 번은 모델 호출이 아니다.

### 확인된 HWPX 출력 경계 — 미완료

가져온 창작 정본은 가변 paragraph/table/image의 `assessment-item-content/1.0`이다.
기존 auto delivery는 이 schema를 초기 `eom-question-template-v1`에 보냈다. 이 renderer는
고정된 6 block, 2×3 표, 800×500 PNG 1개만 지원하므로 실제 native 원본 크기·가변
그림 수의 문항을 처리할 수 없다. 11744·11745를 실제 요청해 확인했으며, 그림 bytes를
줄이거나 빈 표를 만들어 그 계약에 억지로 맞추지 않았다.

실패 build `hwpxbuild_0fe59152f8cf400e9da662b2e2ce907b` 및
`hwpxbuild_d5c5fa44505b4cb6b20047034599ce01`은 그대로 FAILED다. canary 요청의
item_number 기본값 누락도 있었으며, 고정형 projector를 따로 호출했을 때 실제 콘텐츠가
지원 범위 밖임을 확인했다. 따라서 단순 item_number 보충만으로 HWPX 성공이라 할 수 없다.
기존 AI content-team V2/V3 renderer나 원본 다운로드의 성공을 이 신규 정본 출력 성공으로
대체하지 않는다. 기존 정본과 실패를 유지하며 이 출력 경계는 아직 닫지 않았다.

### INDEX reader의 안전한 호환 인계

기존 INDEX coordinator `aac48433`은 Workflow3 source lineage를 읽지 못한다. 현재
finite command가 끝나도록 main에 정상 종료 신호를 주고, 실제 inactive/exit0·자식
수치 실행 없음·기존 작업 완료를 확인했다. 이후 기존 release/identity/activation
application으로 reader `6e3b5860`을 선택해 재개했다. 수치 controller `a70cd434`,
CPU/GPU 모델·환경·bundle·이미 만들어진 벡터는 바꾸거나 지우지 않았다. **coordinator
PID까지 불변이라는 뜻은 아니다.** 새 coordinator의 실제 등록 보고서 capture/임베딩
연결은 별도로 확인 중이다.

### 추가 승인된 후속 범위

사용자는 2026-11-03 사용량 리셋 후, 위 경로 완료 다음 **4개 슬롯**으로 원문 풀이·
Graph 등록을 계속하고 새 등록 문항이 기존 공통 임베딩에 연결되는 것까지 목표에
추가했다. 과거의 purpose-limited 3슬롯 계약을 바꾸지 않고 명시적 4슬롯 successor를
기존 capacity/claim/lease/순차 owner 안에 추가한다. 진행 중 문항은 완료를 기다린다.
GPU INDEX를 재시작하거나 이미 만들어진 보고서·벡터를 다시 만드는 요구가 아니다.

이 후속 범위만 `20261103_0070` migration을 사용한다. 과거 parent capacity ceiling은
3으로 유지하고 정확한 `worker-capacity-policy/1.5`만 4를 허용한다. 기존 parallel
continuation을 `prepare_creative_office_continuation` application으로 읽어 원래 제출자의
현재 권한을 재확인하고, `creative-learning-continuation/1.2`에 Workflow3/Pack1.2와
slot03·04·05·06 설정을 pin한다. 기존 `creative_learning_runner`가 동일 모집단 잠금과
claim/lease를 사용해 실행한다. 별도 worker/queue나 가짜 Studio session은 만들지 않는다.

운영 순서는 보호된 release operator의 `MIGRATION_UPGRADE_0070` → 호환 wheel 설치 →
정확한 successor 준비 → 기존 owner 설정의 revision/tool prefix 갱신 → 재개다.
새 capacity history가 생기면 downgrade는 거부한다. rollback은 successor claim을 멈추고
호환 code를 유지/복구하는 것이며 정책·실패 history를 지워서 schema를 되돌리지 않는다.
실행 중인 INDEX 수치 작업의 PID·InvocationID·수치 prefix는 보존한다. metadata reader의
추가 호환 인계는 아래 별도 기록처럼 작업 종료 경계에서만 한다.

추가 회귀에서는 실제 disposable PostgreSQL에서 동시 4claim/각 1lease/5번째 거부와
동일 claim replay를 확인했고, 기존 3슬롯 테스트도 유지했다. 원본 Work2를 plan32에서
참조할 때 schema registry가 빠져 있던 오류를 재현·수정했다. 이 연결 검사는 실제
등록 전에 실행되며, source test PASS와 실제 신규 문항 acceptance는 구분한다.

## 원본 그림·4슬롯·임베딩 우선 범위의 후속 체크포인트

사용자가 `그림 등록·4슬롯·임베딩 우선`을 선택했다. 가변 구조 정본의 신규 HWPX
renderer 확장은 후속 과제이며 이번 완료 조건에 다시 추가하지 않는다. 위의 실패 build는
보존한다. 2026-11-03 19:42:04 UTC 실제 03/04/05/06 일반 작업 lease 4개와 이후 각
슬롯의 성공을 확인했다. API·Catalog·runner의 설치 source는 `20ad28d3`, Web은
`e22ca6e0`을 유지했다. slot03의 7,200초 고정 실행 unit을 용도 한정으로 추가했고
기존 GPU/CPU가 pin한 Polkit50 bytes·모델·벡터는 바꾸지 않았다.

INDEX는 새 native result@3 출처를 구 Entry1의 allow-list에서 거부했다. 이 실패를
성공으로 바꾸지 않는다. 후속 후보는 Entry3/index5/metadata5와 QUERY metadata successor로
실제 출처를 전달한다. 내부 풀이 텍스트·recipe·encoding identity·numeric INDEX1/QUERY2·
물리 GPU batch2는 동일하다. 기존 수치 입력에 native PNG나 편집 설명을 추가하지 않는다.
disposable PostgreSQL에서 새 provenance의 실제 저장·중단 후 재개·동시 등록 재전송이
통과했다. migration71은 manifest schema allow-list 3개 CHECK만 확장하며 새5 history가
존재하면 downgrade를 거부한다. 새 table/index/권한·queue·모델 의존성은 없다.

위 후속 후보의 운영 설치·INDEX 실제 처리 결과는 아직 PENDING이며 아래에 따로 기록한다.
모델 호출 전 slot03 unit 불일치로 실패했던 8건은 `aa145e10`의 명시적 launch recovery
application으로만 재개한다. 원래 FAILED Job/Workflow와 source/plan/preset pins를 유지하고
source 등록 business key로 중복 Item/Graph를 막는다. 일반적인 content/worker 실패 전체를
자동 재실행하거나 새 identity로 무관한 작업을 만드는 허용이 아니다.

### 21:09 UTC 운영 인계 결과

- API·Catalog·QUERY metadata receiver·공유 runner·creative owner: `31073cb4` 설치.
  Web `e22ca6e0`은 PID/Invocation과 파일을 유지했다. 보호된 operator의 migration71
  upgrade/verify와 ownership5 초기화·조회 검증을 완료했다.
- 진행 중 마지막 slot04 Job는 21:04 UTC 정상 성공 후 교체했다. 초기 배포의 protocol
  초기화 호출에 root transaction이 빠져 guard가 거부했다. 설치/설정 교체 전임을 확인하고
  기존 실패 기록과 wheel/config 백업을 보존한 명시적 resume으로 배포를 마쳤다.
- 8건 prelaunch 실패는 원래 target/preset/plan으로 successor 준비와 동일 요청 재전송을
  확인했다. 원래 FAILED는 그대로다. 21:09 UTC 새 successor에서 실제 03/04/05/06
  lease 4개를 재확인했다. 실행 창 8 source와 실제 모델 동시 실행 4개는 다른 수다.
- INDEX metadata owner도 `31073cb4` identity/config로 인계해 재개했다. 수치 controller
  `a70cd434`와 GPU 환경·모델·space·기존 벡터는 유지했다. CPU fallback의 metadata
  preparer만 association5를 읽는 설치본으로 선택했다. QUERY의 수치 preparer는 유지했다.
- 새 설치본의 실제 API identity에서 11744·11745 Preview/PNG bytes·크기·SHA·재조회가
  다시 PASS했다. 새로운 HWPX 빌드는 제출하지 않았다.
- 공개 풀이·검색 계열 회귀 1,119 PASS. native head5 발행 뒤 두 번째 discovery에서
  같은 head를 재사용하는 successor reader의 경계도 추가 점검했다. 이 후속 수정은
  기존 refresh application의 버전 판별만 정렬하며 새 queue/DB/수치 실행은 만들지 않는다.

현재 INDEX는 새 보고서 읽기 단계를 통과해 처리 중이다. 이 체크포인트는 native source의
벡터·binding 등록 완료를 주장하지 않는다. 그 실제 완료 증거는 후속 기록으로 닫는다.

### 21:24 UTC 실제 GPU·native 인덱스 증거

신규 수치 Job 4개가 실제 `CUDA`에서 SUCCEEDED이며 종료 시각은 21:14:54 UTC다.
21:23:46 UTC 설치된 Catalog Artifact reader로 committed index5 member의 SHA와
닫힌 schema를 다시 검증했다. 해당 CUDA view의 binding 528개 중 native binding5가
3개이며 각 profile3 → role result@3.0 → 기존 encoding ledger의 space/text SHA 및
row index 연결이 일치했다. 이것은 전체 corpus 문항 수가 아니라 해당 view/index의 수다.

- index revision: `embeddingindexrev_0531f24dbaa062374b102de34ac17b0f`
- committed member SHA: `dcf124e8d63830bdfb54c3062f271707780f22b1051d84aefae7e84522cfac05`
- 원본 그림 등록 → 공개 풀이 출처 → 실제 CUDA vector → native binding: **3건 PASS**.

이후 동일 head5의 증분 discovery/reuse 수정 후보 `fd3f0622`도 비편집 설치 패키지
검증과 집중 회귀 31 PASS를 마쳤다. 기존 실행은 끊지 않고 마지막 application commit/
receipt를 마칠 때까지 유지한다. 수정 후보 INDEX-only identity/config는 미리 준비했으며,
현재 실행의 quiescence와 정확한 담당 오류를 확인한 뒤만 인계한다. 공유 API/4슬롯,
물리 GPU·모델·space·벡터는 이 후속 인계에서 다시 교체하지 않는다.

### 21:59 UTC 연속 갱신 reader 인계 확인

원래 `31073cb4`의 CUDA Workflow `workflow_f603cafaeb714aba87e92cbdb7e8ae0e`와
CPU Workflow `workflow_00f89196fcda40b0bc05f84187df69b7`가 모두 정상 완료한 뒤
coordinator가 exit0으로 종료했다. 같은 원래 작업을 실패/성공으로 재해석하거나
수치 프로세스를 죽이지 않았다. 이후 기존 identity/config publication 경계로 INDEX-only
`fd3f0622`를 활성화했다. API/Catalog/QUERY/4슬롯의 `31073cb4`와 Web `e22ca6e0`은
다시 교체하지 않았다.

새 설치본이 실제 committed CPU index5(binding 504)와 CUDA index5(binding 528)를
각각 hash/schema 검증해 읽고, 같은 membership을 두 번 제공해 모두 추가 refresh가
없음을 확인했다. 이 검사는 새 모델 실행 0회이며 기존 수치 Job 재실행도 아니다.
두 장치 각각 native binding5 3개가 기존 ledger에 연결돼 있다. 두 view의 수를 합쳐
문항 수로 보고하지 않는다. 30분 관측 timer 두 개의 실행 결과도 success다.

native5 history가 생긴 이후에는 schema71과 이를 읽는 호환 release를 유지한다.
보관된 `20ad28d3` wheel이 있다는 이유만으로 전체 설치를 그 버전으로 되돌리지 않는다.
문제가 생기면 신규 claim을 제한하고 호환 reader를 유지한 채 해당 담당만 수정한다.
native history·벡터를 삭제해서 downgrade 조건을 맞추는 작업은 하지 않는다.

### 최종 입력 형식 점검 — HWPX 등록·표 전용 Preview·참고란 제외

초기 등록 11744–11749의 원본 catalog를 다시 읽으니 6개 모두 실제 HWP5다.
따라서 이를 HWPX 신규 등록 성공으로 확대하지 않았다. 실제 HWPX 11763은 기존
source-unreadable 예외를 보존한다. 동일하게 승인된 1,053 target 안의 HWPX 11931을
같은 cohort source key·preset·4슬롯 claim 경로로 한 건만 먼저 확인했다. 별도
모집단이나 source identity를 추가하지 않으며, 나중의 순차 처리도 같은 Workflow/등록
결과를 찾는다. pipeline 구현을 하나 더 만든 것이 아니라 기존 per-source application의
제한된 실제 검증이다.

실제 catalog에서 HWPX·사용 개체 2개·rendered use 2개·미해결 picture use 0과 06번
슬롯의 실제 Job 실행을 확인했다. Workflow `workflow_ed94ef76b73b4ca390d5449c6465012b`의
완료 결과를 `itemrev_0ceaca52c7cb4611ba909a62206aece2`로 등록했다. 원본 페이지와 두
PNG의 실제 픽셀을 직접 보니 본문에는 표만 있고 두 bitmap은 참고 원본 기출/그 해설이다.
따라서 `paragraph → table → paragraph → statement_set`, image block 0과 empty native
bindings가 정확하다. API identity의 Preview·재조회 PASS, PNG delivery는 **NOT_REQUIRED**다.
참고란 그림을 억지로 넣어 HWPX 본문 그림 성공 표본을 만드는 작업은 하지 않았다.

일회성 검증 helper는 일반 서비스의 inline 환경을 자동 상속하지 않는다. 초기 tool 경로
설정 오류 두 건은 모델 전에 거부됐다. 이후 모델 Workflow는 한 번만 실행했고, 검증
helper의 Catalog staging 설정 누락으로 등록이 거부된 호출은 `EOM_CATALOG_STAGING_ROOT`
설정 후 같은 완료 Workflow/target key에서 이어갔다. 표 전용 문항에도 PNG가 있어야
한다는 helper의 잘못된 검증 전제도 원본 대조 후 0개 기대값으로 정정했다. 서비스의
정본·worker 결과·과거 실패를 바꾸거나 보고서를 새로 생성하지 않았다.

22:38:26 UTC 같은 표본의 Graph 등록과 공식 권한 기반 풀이보고서 read도 **VERIFIED**다.
Graph revision은 `graphrev_07bea638dc22d977f574a747350895b6`이다. 첫 일회성 Graph 반영은
정상 순차 owner의 동시 갱신에 대해 `KNOWLEDGE_GRAPH_STALE_CURRENT`로 거부됐다.
해당 기록을 보존하고 같은 이미 accepted된 분석·Item·원본 핀에서 명시적으로 한 번
재조회/반영했다. worker 풀이·source Workflow·정본을 재생성하지 않았으며 일반 순차
owner나 GPU 작업을 중지하지 않았다. 다음 모집단 순회도 같은 등록 business key와
원래 풀이/Graph 관계를 재사용한다.

### 최종 설계 대비 검토와 검증 환경

| 처음 설계한 불변식 | 실제 확인/남은 한계 |
| --- | --- |
| signature로 HWP5/HWPX 분기, 확장자 위장 지원 | 격리 원본 추출·signature 회귀 및 실제 HWP5/HWPX 입력 확인 |
| binary member가 아닌 실제 본문 picture use 선택 | native locator/viewport/회전·반전·회색조·본문 region binding 검증, 동일 member의 별도 사용 개체 테스트 |
| 참고 원본/해설 제외, 표·수식 유지 | HWPX 11931 실제 표 전용 문항에서 참고 bitmap 2개 제외, native table 유지 |
| canonical PNG pointer 재사용 | HWP 11744·11745 실제 API content=display content, PNG SHA/크기·동일 조회 재실행 PASS |
| 불명확한 group/라벨·해석 실패를 허위 승인하지 않음 | 명시적 unresolved/content-unavailable/source 예외 유지. 모든 원본의 정확한 native 합성을 지원한다는 주장은 없음 |
| 기존 owner·worker 격리·Graph·풀이 의미 보존 | 기존 Orchestrator/Catalog/4-slot claim·lease 사용, worker NAS/DB 권한 확대 없음, 내부 공개 풀이 V2/text/recipe·수치 identity 유지 |
| 새 문항이 실제 임베딩까지 연결 | native role@3 → profile3 → 실제 CUDA ledger/index5 3건과 CPU/CUDA 각 두 번 재사용 확인 |
| 중단·동시성·재전송 및 설치 검증 | disposable DB 검증/정리, non-editable wheel·RECORD·OpenAPI, native head5→5 predecessor 재사용 회귀 PASS |
| Preview/HWPX 동일 그림 | Preview/media는 실제 확인. 가변 구조 HWPX 재출력은 사용자 확정 후속 범위이며 기존 실패 2건 보존 |

마지막 Office interface 검사는 API Conda의 기존 SQLAlchemy와 별도 HWPX Conda의 기존
Pillow 경로를 **테스트 프로세스에서만** 조합해 79 PASS, 순수 parser는 HWPX Conda에서
57 PASS였다. 처음 HWPX Conda로 전체 interface 검사를 호출한 collection 오류는 해당
환경의 SQLAlchemy 부재였다. 제품 결함으로 해석해 운영 환경에 의존성을 추가하지 않았다.
공개 풀이/검색 회귀는 1,119 PASS이며 기존 Starlette/httpx 경고 1개는 그대로 기록했다.
새 schema·기존 released bytes·동시성/수치 입력 경계의 집중 검증과 실제 운영 증거를
서로 대체하지 않는다. 이번 실제 사용자 브라우저/Hancom 수동 육안 검토는 NOT_RECORDED다.

최종 변경 Python 91개는 ruff/format 검사가 통과했고, 명시적 기존 Pillow 경로와
`--follow-imports=silent`를 사용한 집중 production mypy는 67개 파일 PASS다.
확대된 파일 전체 type-check가 무오류였다고 주장하지 않는다. 이 과정에서는 이번에 바꾸지
않은 PDF request union 분기와 10월의 generic `_message` 반환 타입, optional `olefile`
typing 문제가 함께 나타났다. 해당 기존 구간은 Git blame으로 구분했고 이번 입력/4슬롯
기능에 무관한 type 정리를 추가 배포하지 않았다. 첫 API 단독 호출의 Pillow 부재와,
전역 `import-untyped` 비활성화가 만든 unused-ignore도 환경/호출 문제로 구분했다.

## 우선 범위 완료 기록과 계속 실행할 작업

2026-11-03 22:39 UTC 관측에서 API READY·실제 HTTPS Studio 200, creative owner·INDEX·
QUERY·Web active를 확인했다. 현재 재개된 순회의 검증 수는 16이며, 추가 HWPX 11931
canary는 같은 1,053 target 안에서 별도로 VERIFIED다. 이 수를 전체 corpus 등록 수나
완료율로 해석하지 않는다. 22:28 UTC에는 일반 03/04/05/06 lease 4개를 다시 확인했다.
22:39에는 일부 문항이 Graph 반영을 기다리는 동안 3개가 실행 중이었다. 4는 동시 실행
상한이며 항상 네 슬롯에 불필요한 새 작업을 넣는다는 뜻이 아니다.

전체 원본 처리와 GPU 증분 임베딩은 현재 owner·같은 모집단·기존 30분 timer로 계속한다.
현재 순회가 별도로 기록한 16개 해석/변환/추출 실패는 성공 수에 섞지 않는다. 신규로
발견된 11791의 `WORKER_RESULT_INVALID`도 해당 실패 Workflow/Job를 그대로 보존한다.
과거 333문항 복구의 미복구 6개와 이 순차 입력의 예외 집합은 다른 모집단이다.

이번 우선 범위의 체크 18개와 실제 조회·슬롯·CPU/CUDA index·HWPX 표본·회귀/설치
증거 파일 17개는 기존 Orchestrator file-set publisher로 NAS에 보관했다. 그림 사본이나
worker 전체 결과를 다시 발행하지 않았고 긴 로그/binary를 PostgreSQL에 넣지 않았다.
감사 schema는 이 file set에 동봉한 사후 검증용이며 새 worker protocol/권한 활성화가 아니다.

- Artifact: `artifact_938713f6ddda4cda9a703c54167cfc7b`
- Revision: `rev_425ba3acd9744d1cad12c9e3ad35dd29`
- `report.json` SHA: `sha256:b73dd057ccdf37f6ede596c5bbefc4d62de8537ecf8e04d35e90a1b7c9451a2c`
- [NAS 검증 보고서](/mnt/nas/eom/artifacts/artifact_938713f6ddda4cda9a703c54167cfc7b/rev_425ba3acd9744d1cad12c9e3ad35dd29/report.json)
- 같은 publication을 재전송해 같은 Job/Artifact/revision을 재사용했고, 실제 committed
  member readback/schema/hash도 PASS했다. 과거 실패 로그는 원래 의미로 함께 보존했다.

**사용자 확정 우선 범위는 완료**다. 전체 1,053개 처리·전수 벡터 완료, 모든 native
group/수식 합성 지원, 가변 구조 HWPX 재출력 및 새 Hancom 수동 검수를 완료했다고
주장하지 않는다. 후속 작업에서 이 구분과 기존 정본·실패 이력·수치 실행 핀을 유지한다.
