# EOM Scientific Studio

기출·교과서 근거를 활용해 과학 문항을 만들고, 자료 검토와 HWPX 편집·출력까지 연결하는 제작 시스템입니다.

## 주요 기능

| 기능 | 할 수 있는 일 |
| --- | --- |
| 문항 제작 | 단원·난이도·자연어 요구에 맞춰 출제하고, 출제자와 검토자의 피드백으로 최대 3차 개선합니다. |
| 기출변형 | 원문항의 개념·핵심 착상을 참고하되, 단순한 숫자·표현 변경을 넘어 새 문항을 만듭니다. |
| 자료 검토 | PDF·HWP·HWPX를 검토합니다. 문제지·해설지 분리 입력, 지적 위치 표시와 주석 PDF 다운로드를 지원합니다. |
| HWPX 제작 | 문항·표·수식·그림을 편집 가능한 문서로 출력합니다. 선택 가능한 HWPX 교정에서는 원본을 보존하고 수정 글자를 빨간색으로 표시합니다. |
| 근거·유사도 검색 | GraphRAG와 로컬 임베딩으로 기출·등록 문항·풀이보고서의 관련 근거를 찾습니다. |
| 문항 DB | 메타데이터 표와 선택 문항 상세를 나란히 보고, 여러 조건으로 검색·엑셀 저장·원본 다운로드·PDF 미리보기·조립 순서 저장을 합니다. 원본 전용 문항의 편집 가능한 합본 출력은 아직 지원하지 않습니다. |
| 내부 자료 대화 | 일반 → ChatGPT에서 전용 Codex 슬롯으로 대화하고, 허용된 내부 검색 도구로 자료를 참고합니다. |
| 시험지 제작 | 25문항 생산과 검토를 관리하고, 문항들을 묶은 시험지 HWPX를 만듭니다. |

관리자는 계정·역할·실행 설정을 관리합니다. 사용자는 자신의 로그인 정보와 작업 상태를 확인할 수 있습니다.

## 문항 제작 흐름

~~~text
출제 요청 → 출제·자료/그림 구성 → 자동 검토·피드백
          → 문항 DB 등록 → HWPX 제작·확인 → 사람 승인
~~~

문항 등록과 HWPX 제작을 사람 승인 전에 진행할 수 있어 여러 문항 제작의 병목을 줄입니다.
등록된 문항의 승인 대기·승인 상태는 구분해 조회합니다. 자동 검토 통과가 사람의 최종 승인을 대신하지는 않습니다.

자료는 문항에 맞게 줄글·표·그림으로 구성합니다. 그림 없이 표만 있는 문항도 정상적인 형식입니다.
그림이 하나면 불필요한 빈 칸이나 (가)/(나) 표지를 넣지 않으며, 두 그림의 표지는 HWPX 안의 편집 가능한 텍스트로 다룹니다.
시험지 한 개를 만들었다고 문항별 HWPX 25개가 각각 생성되는 것은 아닙니다.

## 근거를 다루는 방식

- 자료 학습은 모델 가중치 훈련이 아니라 원문·문항·승인 분석·풀이보고서를 검색 가능한 근거로 구조화하는 과정입니다.
- GraphRAG는 출처와 개념 관계를, 로컬 임베딩은 관련 후보 탐색을 돕습니다. 서로 대체하지 않습니다.
- 새 자료와 검토 근거는 기존 증분 인덱싱 경로로 연결하며, 이미 완료된 같은 실행 조건의 벡터는 재사용합니다.
- 답변·문항이 참고한 자료는 접근 권한과 정확한 버전·해시를 검증합니다. 분석 기록, 원문 인용, 모델 추론을 구분합니다.
- 유사도 점수는 풀이가 같을 확률이나 표절 판정이 아닙니다. 후보와 근거를 함께 확인해야 합니다.

기출 520개는 원래 승인된 기출 분석 모집단입니다. 추가 분석·생성 문항·view별 인덱스 수와 같은 분모로 합산하지 않습니다.

## 현재 상태

아래는 연결된 검증 기록 기준이며, 저장소 구현·운영 설치·실제 사용 검증은 구분합니다.

| 영역 | 상태와 확인할 기록 |
| --- | --- |
| 생성 문항 → GraphRAG·증분 임베딩 | 실제 검색·결과 조회·같은 요청 재전송 검증 완료. [운영 검증](docs/operations/REGISTERED_REVIEW_INCREMENTAL_ACCEPTANCE_2026-10-20.md) |
| 일반 채팅 | 부가 알림 호환 수정 배포 및 새 메시지의 실제 답변·완료 상태 확인. [배포 기록](docs/operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md) |
| 문항 DB | 원본 조회·다중 조건 검색·엑셀 저장·교정본 다운로드·PDF 준비·조립 순서 저장과 재열기를 지원합니다. 표/상세 분할 화면은 운영 배포했고, 원본 전용 편집 합본의 활성화는 별도 범위입니다. [운영 기록](docs/operations/ITEM_DB_CURATED_ASSEMBLY_RELEASE_2026-10-27.md) |
| 창작 문항 등록·Graph | 2026-10-30 18:17 UTC 관측 기준 98/1,053건 등록·공식 조회 검증 완료, 다음 문항 처리 중입니다. 서로 다른 출처의 공통 용어 유형 충돌을 수정해 10413을 원래 풀이보고서로 복구했습니다. 기출·교과서 node 17,000개/edge 40,652개와 기존 source hash 변경 0을 실제 확인했습니다. 3개 슬롯 병렬 처리는 준비 중이며 아직 운영 활성화하지 않았습니다. [등록 복구·운영 현황](docs/operations/CREATIVE_INCREMENTAL_EMBEDDING_ACTIVATION_2026-10-30.md) · [3슬롯 설계](docs/architecture/CREATIVE_COHORT_THREE_SLOT_CONTINUATION.md) |
| 풀이 양식과 임베딩 | 기출·창작의 공통 정규화 후속 계약은 후보 검증 상태입니다. 2026-10-29 GPU 재발 원인인 준비 중 할당 만료·캐시의 불필요한 GPU 할당·새 Graph 조회 반복을 수정해 INDEX 전용 운영 배포했습니다. 추가 CUDA 8행의 정식 계산·등록과 워크플로 완료를 확인했으며 CUDA 벡터는 1,538→1,546, 해당 metadata index 연결은 487→503입니다. 이어지는 캐시 등록도 새 GPU 할당·수치 계산 없이 자동 완료했습니다. CPU·기존 검색·창작 등록은 유지합니다. 새 공개 풀이 recipe 검색과 전체 인덱스 완결은 별도 미완료입니다. [호환 설계](docs/architecture/SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md) · [복구·연결 기록](docs/operations/PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md) |
| 시험 운영 생성 문항 정리 | AI 샘플 1개를 남기고 승인된 과거 생성 문항 110개와 파생 이력을 운영에서 정리했습니다. 기출·교과서·가져온 창작 정본과 NAS 감사 파일·백업은 보존했습니다. 일반 삭제와 구분되는 일회성 정리입니다. [실행 기록](docs/architecture/AI_ITEM_PURGE_BOUNDARY_2026-10-28.md) |
| CPU/GPU 임베딩 비교 | 고정 입력 비교 완료. GPU는 적재 후 문서 배치 계산에서 약 3.97배 빨랐으나 단일 질의 전체 시간은 비슷했습니다. [실측 결과](docs/operations/EMBEDDING_GPU_MEASURED_2026-10-24.md) |
| GPU 우선·CPU 대체 실행 | 후속 구현과 CUDA 인덱스 증분 채우기가 진행 중입니다. 모델 재사용·장치별 선택의 코드 검증과 일부 실제 GPU 묶음 실행은 확인했지만, 전체 인덱스 짝·GPU 검색·자원 부족 시 CPU 대체·운영 기본값 전환은 아직 검증 전입니다. 기존 CPU 검색을 유지합니다. [설계](docs/architecture/EMBEDDING_GPU_PREFERRED_BATCH_EXECUTION.md) · [운영 검증 현황](docs/status/GPU_PREFERRED_LIVE_ACCEPTANCE_2026-10-25.md) |

소스 테스트 통과만으로 운영 활성화나 문항의 교육적 품질까지 확인됐다고 간주하지 않습니다.
세부 설치 버전·실패 보존·미검증 범위는 각 운영 기록을 기준으로 봅니다.

## 구조와 개발 원칙

~~~text
Scientific Studio → Application API → Catalog / Workflow Runner / Orchestrator
                                      ├─ 격리된 Codex·로컬 이미지 실행
                                      ├─ GraphRAG·증분 임베딩
                                      └─ HWPX Manager → 격리된 Builder
~~~

- JSON Schema 2020-12와 Pydantic을 기준으로 입력·출력 계약을 먼저 정의합니다.
- 작업 실행과 결과 저장은 Orchestrator를 거칩니다. Worker끼리 직접 통신하거나 DB·NAS에 직접 쓰지 않습니다.
- 논리 ID, 불변 버전, Artifact 참조, SHA-256을 분리합니다. 누락·권한·해시 오류를 최신값으로 몰래 대체하지 않습니다.
- PostgreSQL에는 관계·상태·포인터를, 파일 저장소에는 PDF·PNG·HWPX 등 정본과 manifest를 보관합니다.
- 언어 모델 작업은 격리된 Codex 실행 경로를 사용하며 외부 LLM API를 직접 호출하지 않습니다. 이미지·임베딩 모델은 로컬에서 실행합니다.

| 경로 | 책임 |
| --- | --- |
| schemas / packages | 버전별 계약·도메인·식별자 |
| services / apps | 실행·저장·API·화면 |
| content / config | Content Pack·프롬프트·Workflow·실행 정책 |
| migrations / infra / scripts | DB 변경·명시적 실행환경·배포·검증 |
| docs | 설계 결정·운영 절차·검증 이력 |

## 개발·운영 문서

- [개발 규칙과 검토 체크리스트](AGENTS.md)
- [모듈 경계와 의존 방향](docs/architecture/MODULE_BOUNDARIES.md)
- [GraphRAG 구조](docs/architecture/EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md)
- [유사도·증분 임베딩 통합 설계](docs/architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md)
- [자료 검토 설계](docs/architecture/PDF_DOCUMENT_REVIEW_V1_IMPLEMENTATION_PLAN.md)
- [HWPX 제작 API](docs/architecture/HWPX_APPLICATION_API_V0.md)
- [Codex 로그인·모델 검증](docs/operations/CODEX_AUTH_AUTOMATIC_MODEL_VERIFICATION_RELEASE.md)
- [API 문제 진단](docs/operations/API_TROUBLESHOOTING.md)
- [격리 PostgreSQL 테스트](docs/operations/API_INTEGRATION_TEST_DATABASE.md)
- [DB·Artifact 복구 훈련](docs/operations/DATABASE_ARTIFACT_RECOVERY_DRILL.md)

개발·검증은 각 구성요소에 지정된 Conda 환경과 기존 검증 스크립트를 사용합니다.
DB 변경 테스트는 운영 DB가 아닌 disposable DB에서만 수행합니다.
비밀번호·토큰·Codex 인증·SSH 키·환경 비밀값과 생성 파일은 Git에 넣지 않습니다.

세부 변경 이력과 과거 검증 수치는 [운영 기록](docs/operations/), [상태 기록](docs/status/) 및 Git 이력에 보존합니다.
