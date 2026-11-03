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

`DEPLOYMENT=PENDING`, `NEW_INTAKE_PREVIEW_HWPX=PENDING`.
최종 source/설치/활성화와 신규 입력 identity·원본 use·Preview/media·HWPX 증거는
실제 실행이 끝난 후 기록한다.

### 추가 승인된 후속 범위

사용자는 2026-11-03 사용량 리셋 후, 위 경로 완료 다음 **4개 슬롯**으로 원문 풀이·
Graph 등록을 계속하고 새 등록 문항이 기존 공통 임베딩에 연결되는 것까지 목표에
추가했다. 과거의 purpose-limited 3슬롯 계약을 바꾸지 않고 명시적 4슬롯 successor를
기존 capacity/claim/lease/순차 owner 안에 추가한다. 진행 중 문항은 완료를 기다린다.
GPU INDEX를 재시작하거나 이미 만들어진 보고서·벡터를 다시 만드는 요구가 아니다.
