# EOM 문서 안내

제품 소개는 [README](../README.md), 작업별 코드 위치는 [개발 문맥](agent-context/README.md)에서 시작합니다.
아래 설계 문서는 기능의 책임과 동작을, 날짜가 있는 운영 기록은 당시 배포·검증 범위를 설명합니다.
과거 기록의 수치나 설치 버전을 현재 상태로 간주하지 않습니다.

## 기능별 찾아보기

| 영역 | 설계·사용 흐름 | 검증·운영 기록 |
| --- | --- | --- |
| 문항 제작·검토 | [담당 모듈과 흐름](agent-context/authoring-review.md) | [운영 기록 모음](operations/) |
| 문항 DB·간편 출력 | [DB와 Excel의 역할](architecture/DB_QUICK_OUTPUT_EXCEL_CONSOLIDATION.md) | [문항 DB·조립](operations/ITEM_DB_CURATED_ASSEMBLY_RELEASE_2026-10-27.md) |
| Excel 콘텐츠 편성 | [콘텐츠·판·회차와 사용 이력](architecture/EXCEL_CONTENT_PLACEMENT_DESIGN.md) | [실제 저장·출력 검증](operations/EXCEL_CONTENT_PLACEMENT_IMPLEMENTATION_2026-11-09.md) |
| 자료 학습·Map | [자료 입력·Graph 등록](architecture/MATERIAL_LEARNING_UPLOAD_PIPELINE.md) | [자료 학습](operations/MATERIAL_LEARNING_RELEASE_2026-11-06.md) · [Map Layer](operations/MAP_LAYERS_RELEASE_2026-11-06.md) |
| 유사도·임베딩 | [GraphRAG·증분 인덱싱](architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md) | [목록 검색·기록](operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md) · [저장 병목 개선](operations/INDEX_PUBLICATION_PERFORMANCE_2026-11-09.md) |
| 자료 검토·한글 출력 | [문서 입출력 지도](agent-context/document-output.md) | [편집 가능한 합본](operations/CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md) · [한글→PDF 수식](operations/OFFICE_PDF_EQUATION_RELEASE_2026-11-06.md) |
| 채팅·계정·슬롯 | [대화와 계정의 책임](agent-context/chat-identity-slots.md) | [6번 채팅 전용·슬롯 복구](operations/CHAT_SLOT06_RELEASE_2026-11-10.md) |

## 개발·운영

- [개발 규칙과 검토 체크리스트](../AGENTS.md)
- [시스템 지도](agent-context/system-map.md) · [모듈·의존 경계](architecture/MODULE_BOUNDARIES.md)
- [실제 사용자 오류 위험과 설계 원칙 검토](architecture/REAL_USER_FAILURE_RISK_REVIEW_2026-11-13.md)
- [테스트·호환 배포·파일 정리](agent-context/development-operations.md)
- [API 문제 진단](operations/API_TROUBLESHOOTING.md)
- [운영 배포 실행 경계](operations/RELEASE_OPERATOR_RUNTIME.md)
- [격리 PostgreSQL 테스트](operations/API_INTEGRATION_TEST_DATABASE.md)
- [DB·Artifact 복구 훈련](operations/DATABASE_ARTIFACT_RECOVERY_DRILL.md)

원본·결과물·인증 정보는 이 문서 폴더에 보관하지 않습니다.
[상세 상태표 보존본](status/README_CHECKPOINT_2026-11-10.md)은 이전 README의 이력을 보존하며,
최신 운영 판정은 실제 설치 기록과 해당 기능의 후속 운영 문서에서 확인합니다.
