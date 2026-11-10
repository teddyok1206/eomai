# 시스템 책임 지도

## 먼저 볼 경계

```text
Studio 화면과 BFF
  → Application API의 인증된 command/query
  → Catalog와 Workflow Runner의 application
  → Orchestrator의 격리 실행과 검증된 Artifact commit
  → Item과 Graph와 임베딩 및 HWPX 결과
```

이는 모든 화살표가 독립 HTTP microservice라는 뜻이 아니다. Catalog·Identity·
Orchestrator·Workflow Runner에는 기존 ORM/transaction composition을 공유하는 부분이 있다.
`docs/architecture/MODULE_BOUNDARIES.md`의 검토된 cluster를 새 기능으로 넓히지 않는다.

## 경로와 책임

| 경로 | 찾을 책임 |
| --- | --- |
| `apps/web_gui/eom_web_gui` | Studio 화면, 브라우저 상태, BFF, session과 gateway |
| `apps/application_api/eom_api` | HTTP routers, 인증·권한·멱등 요청과 application adapters |
| `services/catalog_service/eom_catalog_service` | 정본 파일 해석, Item·자료·Graph·검색 결과의 application |
| `services/workflow_runner/eom_workflow_runner` | released Workflow, checkpoint, command claim과 역할 피드백 |
| `services/orchestrator/eom_orchestrator` | 고정 실행 계획, worker 격리·상태·검증·Artifact 저장 |
| `services/identity_service/eom_identity_service` | 실제 operator/session 권한과 실행용 fence |
| `services/hwpx_manager/eom_hwpx_manager` | 승인된 입력 선택, delivery lifecycle와 Builder handoff |
| `services/hwpx_builder/eom_hwpx_builder` | 격리된 문서 생성·package 검증 |
| `packages` | typed contract, 식별자, domain/value, wheel에 포함할 schema |
| `schemas`, `config`, `content` | 공개 schema 정본, Workflow/control 설정, Content Pack와 출제 규칙 |
| `scripts`, `infra`, `migrations` | 명시적 검증·배포·운영 identity와 DB 변경 |

실행 Python package는 `pyproject.toml`의 setuptools 검색 경로와 각 component의 pyproject로
확인한다. 비슷한 이름의 초기 placeholder 디렉터리만 보고 실제 owner라고 추정하지 않는다.

## 수정 위치 찾기

화면 반응은 Web static module과 BFF에서 시작한다. API 기술 코드는 router → API service →
담당 Catalog/Runner client 순으로 추적한다. source 부적격·Graph 누락·벡터 없음은 서로
다른 책임이며 UI에서 데이터를 만들어 맞추지 않는다. 공개 계약의 의미가 변할 때는
schema·Pydantic·resource mirror·모든 실제 consumer를 같이 확인한다.

정본의 모델은 `logical entity → immutable revision → Artifact component → SHA-256`이다.
경로는 위치이고 identity가 아니다. 큰 binary는 DB 행이나 서비스 간 임의 dict에 복사하지 않는다.
worker는 local staging만 읽고 local 결과를 내며 정본 commit은 기존 Orchestrator owner가 맡는다.

## 검증과 근거

- `tests/unit/test_dependency_boundaries.py`: 의존 방향·기존 runtime cluster 경계.
- `pyproject.toml`: package 경로·entrypoint·resource packaging·테스트 환경.
- `docs/architecture/MODULE_BOUNDARIES.md`: 기존 의존 구조와 분리 기준.
- `README.md`: 사용자 기능 지도. 운영 활성 판정은 연결된 기록과 현재 설치 상태로 확인한다.

## GUI 표현 유지

초기 표현 원칙은 `docs/product/EOM_SCIENTIFIC_WORKBENCH_DESIGN_SYSTEM.md`다.
후속 폼도 `static/styles.css`의 낮은 specificity 입력 기본값과 기존 semantic token을
사용한다. 상태는 `presentation-vocabulary.ko-KR.json`, 도움말은 `guide-content.js`가
담당하며 화면 표시가 원본 상태/권한을 바꾸지 않는다. 자료 학습도 공통 상태 presenter를
주입받는다. `tests/web_gui/test_gui_principle_alignment.py`와 실제 Chromium suite는
전체 화면/모바일 기준을 검사한다. 등록·검색 등 동작 검증은 기존 feature suite를 같이 쓴다.

관리자 전용 `운영 도구 → 운영 기록`은 기존 `explorer` 화면의 표시 이름·위치다.
기존 API/Observe의 허용된 기록만 읽으며 문항 DB·Excel 편성과 별개다. 메뉴 이동이
route/API/권한 변경이나 운영 기록 수정·삭제 기능 추가를 뜻하지 않는다.
