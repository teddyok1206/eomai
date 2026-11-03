# 한글 원본 그림 신규 입력 릴리스

2026-11-03 UTC. 설계 기준은
[창작 원문 이미지 복구](../architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md)의
‘향후 한글 문항 신규 입력 설계’다. 기존 333문항 복구와 다른 **새 입력 경로**다.

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
   지정한다. 해석은 기존 eom-image systemd sandbox에서만 수행한다.
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

INDEX PID·InvocationID·고정 prefix/설정, 현재 풀이보고서/Graph, 기존 Item과 과거
실패 이력을 보존한다. 소비자 QUERY는 유효 작업과 실제 실행이 없는 시점에만
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
INDEX의 PID·InvocationID·수치 prefix는 모든 단계에서 보존한다.

추가 회귀에서는 실제 disposable PostgreSQL에서 동시 4claim/각 1lease/5번째 거부와
동일 claim replay를 확인했고, 기존 3슬롯 테스트도 유지했다. 원본 Work2를 plan32에서
참조할 때 schema registry가 빠져 있던 오류를 재현·수정했다. 이 연결 검사는 실제
등록 전에 실행되며, source test PASS와 실제 신규 문항 acceptance는 구분한다.
