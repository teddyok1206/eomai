# Scientific Studio 표현 사전

## 목적

Scientific Studio는 EOM의 상태 머신, 불변 Revision, Artifact pointer 같은 정밀한 백엔드
개념을 사용한다. 이 정확성은 유지하되, 일반 사용자가 문항 제작과 HWPX 다운로드를 위해
백엔드 용어를 해석할 필요는 없어야 한다. 이 문서는 백엔드 계약과 사용자 표현 사이의
번역 경계를 정의한다.

이 변경은 표시 계층에만 속한다. API 요청·응답, 데이터베이스 값, workflow 전이,
idempotency key, 논리 ID, Revision ID, Artifact Revision ID, SHA-256의 의미는 변경하지
않는다.

## 권위 있는 자료

- 기계 판독 표현 사전:
  `apps/web_gui/eom_web_gui/static/presentation-vocabulary.ko-KR.json`
- 사전 검증 계약:
  `schemas/web-gui/presentation-vocabulary-v1.schema.json`
- 이 문서: 사용자 언어와 기술 언어의 선택 원칙 및 변경 절차

JSON 사전이 런타임 표시값의 유일한 권위 자료다. HTML과 JavaScript에 같은 상태 번역표를
다시 만들지 않는다.

## 핵심 원칙

1. **백엔드 값은 번역하지 않고 표시만 번역한다.** 비교, 폴링, API payload에는
   `RUNNING`, `SUCCEEDED` 같은 원본 값을 그대로 사용한다.
2. **문맥을 포함해 조회한다.** `RUNNING`은 workflow에서는 `문항 제작 중`, HWPX에서는
   `HWPX 제작 중`, 지식 분석에서는 `자료 분석 중`이다.
3. **원본 진단값을 보존한다.** 사용자 badge에는 한국어를 쓰되 `data-raw-state`와 title,
   관리자 운영 기록에는 원본 코드를 남긴다.
4. **모르는 값은 정상처럼 보이지 않는다.** 사전에 없는 값은 `알 수 없는 상태`로 표시하고
   원본 코드를 진단 정보로 보존한다.
5. **오류는 설명과 다음 행동을 함께 제공한다.** 알려진 오류는 한국어 메시지와 사용자가
   취할 수 있는 조치를 표시한다. 원본 오류 코드는 숨기거나 다른 코드로 바꾸지 않는다.
6. **대상 사용자를 구분한다.** `USER`는 일상 업무, `ADMIN`은 운영 설정,
   `DIAGNOSTIC`은 지원·감사에 필요한 표현이다.
7. **일상 작업면에서는 구현명을 노출하지 않는다.** `API`, `Control Plane`, `DB Explorer`,
   `ETag`, `Artifact`, `DRAFT`, `Release`, `Drain`처럼 사용자가 행동을 결정하는 데 필요하지
   않은 구현명은 각각 서비스 역할, 작업 목적, 안전 장치, 사용자 행동을 설명하는 말로
   표시한다. 원본 값은 요청 payload와 접힌 기술 정보에만 보존한다.

## 표현 구조

### 상태

상태 조회 키는 `(domain, raw_state)`다. 먼저 영역별 상태를 찾고, 없으면 `generic` 상태를
찾는다. 둘 다 없으면 fail-visible fallback을 사용한다.

| 영역 | 백엔드 값 | 기본 GUI 표현 |
|---|---|---|
| workflow | `RUNNING` | 문항 제작 중 |
| workflow | `AWAITING_HUMAN_APPROVAL` | 문항 검토 승인 대기 |
| workflow | `COMPLETED` | 문항 등록 완료 |
| knowledge_analysis | `QUEUED` | 분석 대기 |
| knowledge_analysis | `RUNNING` | 자료 분석 중 |
| hwpx_build | `VALIDATING` | HWPX 검증 중 |
| hwpx_build | `SUCCEEDED` | 다운로드 준비 완료 |
| item_revision | `APPROVED` | 사용 가능 |
| codex_account | `DRAINING` | 새 작업 중지 중 |

### 단계

| 백엔드 단계 | GUI 표현 |
|---|---|
| `request` | 요청 접수 |
| `authoring` | 문항 작성 |
| `image` | 자료 그림 제작 |
| `review` | 품질 검토 |
| `human_approval` / `approval` | 검토 승인 |
| `item_management` / `registration` | 완성 문항 등록 |
| `hwpx` | HWPX 제작 |

### 주요 식별자와 객체

| 백엔드 표현 | GUI 표현 | 기본 노출 대상 |
|---|---|---|
| Workflow ID | 문항 제작 진행 ID | 진단·지원 |
| Item ID | 문항 ID | 진단·지원 |
| Item Revision ID | 문항 버전 ID | 문항 선택·진단 |
| HWPX Build ID | HWPX 제작 ID | 결과 복구·진단 |
| Artifact Revision ID | 결과 파일 버전 ID | 진단 |
| Source Intake | 참고 자료 묶음 | 사용자 |
| Evidence Bundle | 근거 자료 묶음 | 관리자 |
| Graph Snapshot | 지식 그래프 버전 | 관리자 |
| Execution Preset | 실행 설정 | 관리자 |
| Worker Slot | 작업 슬롯 | 관리자 |
| Analysis Batch | 분석 작업 | 관리자 |
| Content Pack Release | 제작 기준 버전 | 진단·지원 |
| ETag | 동시 편집 확인값 | 편집·승인 |
| Application API | 핵심 서비스 | 사용자 |
| Observability | 운영 상태 | 사용자 |
| DB Explorer | 운영 데이터 조회 | 관리자 |
| SHA-256 | 내용 검증값 | 진단·지원 |

### 사용자 행동

| 내부 동작 | GUI 표현 |
|---|---|
| `ENABLE` | 사용 시작 |
| `DRAIN` | 새 작업 중지 |
| `DISABLE` | 사용 중지 |
| create `DRAFT` | 설정 초안 생성 |
| `Release` preset revision | 설정 사용 가능 전환 |
| `Deprecate` preset | 설정 사용 중단 |

논리 ID와 불변 Revision ID를 합치지 않는다. GUI에서 더 친숙한 이름을 사용하더라도 서로
다른 식별자는 별도 필드로 표시한다.

## 오류 표시 계약

알려진 오류는 다음 형식으로 표시한다.

```text
<사용자 설명> <권장 행동> (기술 코드: <원본 오류 코드>)
```

예를 들어 `HWPX_APPLICATION_REVISION_INELIGIBLE`은 “이 문항 버전은 아직 HWPX로 만들 수
없습니다. 완성 문항에서 현재 승인된 문항 버전을 다시 선택하세요.”로 표시한다. 관리자나
지원 담당자가 원인을 추적할 수 있도록 원본 코드는 함께 유지한다.

사전에 없는 오류는 구체적인 원인을 추측하지 않는다. 일반 실패 메시지와 원본 코드만
표시한다.

## 변경 절차

1. 먼저 사용자 문맥과 원본 백엔드 값이 무엇인지 확인한다.
2. 기존 domain 표현으로 의미가 충분한지 검토한다.
3. 새 항목이 필요하면 JSON Schema를 먼저 확장한다.
4. 사전에 `label`, `audience`, 필요한 `tone`, `action`을 추가한다.
5. API 비교·payload·상태 머신 값이 변경되지 않았음을 테스트한다.
6. 미등록 값 fallback과 원본 진단값 보존을 테스트한다.
7. Web GUI wheel에 사전 파일이 포함되는지 release 검증을 실행한다.

## 범위 밖

- 백엔드 enum 이름 변경
- API 응답 필드 변경
- 데이터베이스 migration
- workflow 단계 또는 상태 전이 변경
- 원본 오류 코드를 한국어 문자열로 덮어쓰기
- Explorer의 원시 감사 데이터 제거

향후 다른 locale이 필요해지면 동일한 schema version을 따르는 별도 locale 자산을 추가할
수 있다. 실제 두 번째 locale 요구가 생기기 전에는 번역 프레임워크나 서버 측 국제화
계층을 추가하지 않는다.
