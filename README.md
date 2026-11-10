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
| Map | 데이터 → Map에서 실제 Graph의 교과서·기출·창작·외부·AI 연결을 읽기 전용으로 탐색합니다. 출처를 선택하면 같은 Graph 전체에서 해당 근거를 찾고, 공통 개념은 여러 출처의 색으로 표시합니다. 근거 확인·문항 미리보기·DB 조회로 이어지며, 그래프 배치 거리는 유사도 점수가 아닙니다. |
| 문항 DB | 메타데이터 표와 선택 문항 상세를 나란히 보고, 여러 조건으로 검색·엑셀 저장·원본 다운로드·PDF 미리보기를 합니다. 간편 출력에서는 선택한 문항을 순서대로 편집 가능한 HWPX로 만들며, 정식 편성·사용 이력과 기존 조립·출력 기록은 Excel에서 관리합니다. |
| Excel 콘텐츠 편성 — 운영 사용 가능 | 자유 콘텐츠·판·회차에 DB 문항을 배치하고 다음 판으로 복사합니다. 반복 사용 표시, 연도별 사용·미사용, 변경·인쇄 이력과 선택 회차 HWPX를 제공합니다. 실제 HTTPS 저장·복사·이력·HWPX 다운로드와 재조회, DB에서 바로 배치한 문항의 저장·새로고침 유지까지 확인했습니다. [설계](docs/architecture/EXCEL_CONTENT_PLACEMENT_DESIGN.md) · [검증·배포 상태](docs/operations/EXCEL_CONTENT_PLACEMENT_IMPLEMENTATION_2026-11-09.md) |
| 내부 자료 대화 | 일반 → ChatGPT에서 전용 Codex 슬롯으로 대화하고, 허용된 내부 검색 도구로 자료를 참고합니다. |
| 시험지 제작 | Excel에서 문항을 편성해 시험지 HWPX를 만듭니다. 기존 25문항 자동 생산 API·이력은 보존하되 구 배치 UI는 퇴역했으며, 다문항 AI 생성 화면은 별도 후속 기능입니다. |

관리자는 계정·역할·실행 설정을 관리하며, `운영 도구 → 운영 기록`에서 제작·작업·파일 기록을 읽기 전용으로 조회합니다. 사용자는 자신의 로그인 정보와 작업 상태를 확인할 수 있습니다.

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
| ChatGPT 6번 전용·현재 실행 설정 — 운영 반영 | 기존 6번을 채팅 전용으로 예약하고 새 일반 업무는 1~5번을 사용합니다. 과거 실행 설정은 화면에서 숨기되 참조 이력은 보존합니다. API/Web/platform `59597100`에서 슬롯 조회의 API 권한 불일치를 수정하고 실제 제한 계정으로 6개 슬롯 조회·control 잠금을 확인했습니다. 실제 06 모델 실행·동시성·격리 검증은 보존하며 새 Studio 채팅 답변 확인은 대기 중입니다. GPU INDEX는 재시작하지 않았습니다. [운영 증거·남은 확인](docs/operations/CHAT_SLOT06_RELEASE_2026-11-10.md) |
| DB 간편 출력·Excel 통합 — 운영 반영 | DB에서는 문항 선택 후 한 번에 HWPX를 만들고, 기존 조립·출력 목록과 정식 편성은 Excel로 모았습니다. Web `2e6ec36c` 설치·HTTPS 파일 일치·READY를 확인했고 GPU·검색·슬롯 서비스는 재시작하지 않았습니다. 새 동선의 운영 사용자 확인은 대기 중입니다. 구 모의고사 UI는 제거하되 API·이력은 보존하며, 다문항 AI 생성은 별도 후속 기능입니다. [경계·검증·배포](docs/architecture/DB_QUICK_OUTPUT_EXCEL_CONSOLIDATION.md) |
| 통합 자료 학습 — 운영 반영 | PDF/HWP/HWPX 업로드·준비/복구·설명/문항 분리를 호환 배포했습니다. 실제 작은 PDF의 문항·설명·공개 풀이·공유 Graph 등록, DB 외부 목록·공식 RAG·동일 요청 재조회와 strict 공통 임베딩 입력을 확인했습니다. INDEX의 V11 입력 연결 수정·공식 source 인계 후 새 CUDA 요청의 RUNNING/PROCESSING까지 확인했으며, 전체 corpus 계산은 계속됩니다. 기존 기출·창작·AI 정본을 보존하고 새 자료 문항은 ‘외부’로 구분합니다. [설계·두 차례 검토](docs/architecture/MATERIAL_LEARNING_UPLOAD_PIPELINE.md) · [실제 운영 증거와 검증 한계](docs/operations/MATERIAL_LEARNING_RELEASE_2026-11-06.md) |
| Map·출처 Layer — 운영 반영 | 교과서·기출·창작·외부·AI 선택을 서버 조회에 연결했습니다. 현재 화면에 이미 뜬 점만 숨기는 필터가 아니며, 같은 Graph 버전·근거·문항 열기를 유지합니다. 브라우저 fixture와 설치본의 실제 출처별 조회·재조회·상세 읽기를 확인했고, 사용자도 운영 화면 업데이트를 확인했습니다. 검증 당시 Graph에 연결된 AI 근거는 0건입니다. [호환 릴리스·검증 범위](docs/operations/MAP_LAYERS_RELEASE_2026-11-06.md) |
| 로컬 파일 정리 | 11월 6일 미사용 모델 캐시 11개·Conda 다운로드 473개·pip 캐시와 퇴역 EOMIS 내용을 정리해 약265GB를 추가 확보했습니다. EOMIS는 암호화한 NAS 백업과 전체 대조 후 정리했으며, 보안 차단용 빈 경로만 남겼습니다. 정리 후 SSD 여유는 약276GiB입니다. 현재 설치 모델·DB·원본·벡터·인증은 보존했고, 도중 만료된 INDEX는 같은 설정으로 복구했습니다. [퇴역·검증·복구 기록](docs/operations/LEGACY_MODEL_CACHE_RETIREMENT_2026-11-06.md) · [앞선 빌드 정리 약22.6GB](docs/operations/MAP_LAYERS_RELEASE_2026-11-06.md#로컬-디스크-정리) |
| 창작 문항 그림 복구 | HWP/HWPX 본문에 실제 쓰인 내장 이미지로 333문항·362그림을 복구하고 운영 조회·해시·재조회를 확인했습니다. 우측 참고 기출 그림은 제외했으며, 이미지가 아닌 표·수식 등 6문항은 미복구 예외로 남겼습니다. Preview 아래 긴 이미지 설명도 숨겼습니다. [범위·예외·운영 기록](docs/architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md) |
| 한글 원본 그림 신규 입력 | 새 HWP/HWPX 입력은 PDF crop 대신 본문 내장 그림의 실제 사용 개체·viewport·회전을 등록에 연결합니다. HWP 본문 그림 조회와 HWPX 표 전용 문항의 참고란 제외를 검증했습니다. 이후 발생한 Graph 동시 반영 충돌과 선택 문항의 임베딩 plan 버전 오판을 수정·배포했고, 03–06 실제 동시 실행·새 Graph 등록·새 CUDA 인덱스 저장과 재사용을 확인했습니다. 전체 1,053개 처리와 임베딩은 백그라운드 작업이며, 원본 변환·추출 예외는 별도로 보존합니다. 보류했던 가변 구조의 HWPX 출력 확장은 아래 합본 경로에서 진행합니다. [입력·운영 기록](docs/operations/OFFICE_NATIVE_ITEM_INTAKE_RELEASE.md) · [11월 4일 복구·실제 실행 증거](docs/operations/BACKGROUND_NATIVE_RECOVERY_2026-11-04.md) · [자원 부족 대기·복구 운영 기록](docs/operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md) |
| 생성 문항 → GraphRAG·증분 임베딩 | 실제 검색·결과 조회·같은 요청 재전송 검증 완료. [운영 검증](docs/operations/REGISTERED_REVIEW_INCREMENTAL_ACCEPTANCE_2026-10-20.md) |
| 일반 채팅 | 부가 알림 호환 수정 배포 및 새 메시지의 실제 답변·완료 상태 확인. [배포 기록](docs/operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md) |
| 문항 DB | 원본 조회·다중 조건 검색·엑셀 저장·교정본 다운로드·PDF 준비와 표/상세 분할 화면을 지원합니다. 기존 배치는 위의 간편 출력·Excel 동선으로 통합했으며 조립 정본과 HWPX 이력은 보존했습니다. [기존 운영 기록](docs/operations/ITEM_DB_CURATED_ASSEMBLY_RELEASE_2026-10-27.md) · [합본 배포·검증 범위](docs/operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md) |
| 한글→PDF 수식·번호 보존 — 운영 반영 | 글꼴 명령어·단독 연산자·이온 전하의 변환을 보완했고, 후속으로 좁은 번호 칸의①–⑤가 수식과 겹치던 여백을 수정했습니다. 실제 원본12건 반복 변환 후 운영 PDF 준비·다운로드·동일 결과 재사용을 확인했습니다. 원본·이전 PDF 세대·학습/GPU/슬롯은 보존했습니다. [수식 검증·한계](docs/operations/OFFICE_PDF_EQUATION_RELEASE_2026-11-06.md) · [번호 보정·운영 증거](docs/operations/OFFICE_PDF_CHOICE_LABEL_RELEASE_2026-11-07.md) |
| 편집 가능한 합본 | 호환 운영 배포 후 원본 두 문항 및 기출·원본·등록 창작 혼합의 실제 저장 순서에서 제작→독립 검증→정식 Artifact→HTTPS 다운로드와 동일 결과 재조회를 확인했습니다. 실제 내려받은 두 HWPX도 Office에서 열렸습니다. 콘텐츠팀 2/3 출력은 설치 Builder와 격리 DB의 실제 렌더·발행·다운로드까지 검증했습니다. 현재 AI 샘플에는 accepted analysis/Graph 등록이 없어 AI를 포함한 운영 합본 검증은 남아 있습니다. [설계·완료 조건](docs/architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md) · [범위·입력 예외·남은 검증](docs/operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md) |
| DB 유사도 목록·기록 | 1–32문항과 문항별 상위 결과 수·기준 문항 미리보기·사용자별 최근 기록을 지원합니다. 실제 검색 결과 표시·문항 열기·같은 기록 재조회를 사용자가 확인했습니다. 완료 순위와 정확한 버전을 작은 Artifact로 저장해 재사용하며, 11월 5일 같은 기록의 최초 저장 조회179.9초→재조회17.6초와 계산1회 유지를 확인했습니다. 한 사례의 실측이며 응답시간 보장은 아닙니다. [운영 체크포인트](docs/operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md) |
| 조립·필터 후속 개선 | 제목 저장·목록에서 삭제·번호/카드/동작의 세 열 편집·실제 단원명 등 선택형 필터를 브라우저·임시 DB에서 검증하고 API/Catalog/Web을 호환 운영 배포했습니다. 삭제는 원본 문항과 기존 HWPX를 보존합니다. 새 화면의 실제 사용자 확인은 별도로 기록합니다. [검증·배포 기록](docs/operations/ITEM_DB_ASSEMBLY_LIBRARY_2026-11-05.md) |
| 창작 문항 등록·Graph | 2026-10-30 18:17 UTC 관측 기준 98/1,053건 등록·공식 조회 검증 완료입니다. 서로 다른 출처의 공통 용어 유형 충돌을 수정해 10413을 원래 풀이보고서로 복구했습니다. 당시 기출·교과서 node 17,000개/edge 40,652개와 기존 source hash 변경 0을 확인했습니다. 이후 3슬롯 운영 활성화와 실제 실행을 확인했으며, 최신 처리·배포 대기 상태는 [공통 전환 체크포인트](docs/operations/UNIFIED_ITEM_EMBEDDING_GPU_CHECKPOINT_2026-10-31.md)를 기준으로 봅니다. [등록 복구 기록](docs/operations/CREATIVE_INCREMENTAL_EMBEDDING_ACTIVATION_2026-10-30.md) · [3슬롯 설계](docs/architecture/CREATIVE_COHORT_THREE_SLOT_CONTINUATION.md) |
| 풀이 양식과 임베딩 | 기출·창작·AI의 공개 풀이를 같은 입력 규칙으로 맞추는 GPU 재임베딩 목표가 진행 중입니다. 기출520 대상을 고정했고 INDEX를 공통 형식 우선으로 전환했습니다. 새 결과·검색 전환을 검증한 뒤 구형 벡터를 삭제합니다. 전체 완료·구 벡터 삭제는 아직 아닙니다. [전환 목표](docs/architecture/UNIFIED_ITEM_EMBEDDING_GPU_MIGRATION_GOAL_2026-10-31.md) · [운영 체크포인트](docs/operations/UNIFIED_ITEM_EMBEDDING_GPU_CHECKPOINT_2026-10-31.md) · [기존 복구 기록](docs/operations/PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md) |
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
- [개발 에이전트용 코드 문맥과 탐색 지도](docs/agent-context/README.md)
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
