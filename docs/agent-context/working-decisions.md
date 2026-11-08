# 유지할 개발 판단

이 항목은 같은 문제를 다시 만들지 않기 위한 탐색 메모다. 실행 설정·schema·ADR을
대체하지 않으며, 이후 source가 달라졌다면 해당 owner와 테스트부터 다시 확인한다.

## 원래 경계로 해결

- 새 검색 엔진·벡터 DB·queue·권한 체계를 만들기 전에 기존 Catalog/Graph/Runner owner를 찾는다.
- accepted 풀이를 다시 생성해서 등록 문제를 우회하지 않는다. 같은 source와 멱등 key,
  명시적 Graph CAS/rebase와 supported recovery를 사용한다.
- 정상 입력을 처리하는 deterministic 코드 오류를 AI의 불확실성으로 설명하지 않는다.
  실제 오류 지점과 재현 조건을 확인하고 해당 담당을 고친다.
- Job·Workflow·Graph 등록·INDEX·QUERY의 상태는 독립적이다. lease가 만료된 과거 RUNNING과
  실제 현재 worker의 유효 lease/프로세스를 구분한다.

## 원문과 편집

- 한글 원본은 본문 picture use를 우선한다. PDF crop과 참고란 이미지 혼입을 정상 입력 방식으로
  되돌리지 않는다. 동일 member의 본문 사용과 참고 사용을 구분한다.
- 콘텐츠팀 원문과 별도 연동 지침을 구분한다. `<자료>` 문구·고정 두 칸·그림 지시문을
  정상 문항 내용으로 강제하지 않는다. 표-only는 지원해야 하는 정상 자료형이다.
- whole-exam HWPX 한 건은 per-item build 25건이 없어도 정상이다. 임의로 historical delivery를
  backfill하지 않는다. 원본-only 문항의 editable 합본과 generic HWPX 재출력은 실제 지원 범위를 확인한다.
- 사람 승인과 생성/등록/출력/풀이/검색 준비를 구분한다. 승인 상태를 출처 분류에 섞지 않는다.

## 검색과 실제 사용

- 실제 GUI 검색 결과 표시 → 결과 문항 열기 → 같은 결과 재조회가 성공해야 사용자 경로가 닫힌다.
  health나 source test만으로 대신하지 않는다.
- 완료 결과 확인·최근 기록 조회에서 새 계산을 제출하지 않는다. session 복귀와 Graph head
  이동이 원래 pin을 잃게 하지 않는다.
- 임베딩의 공통 입력/profile/view/space를 확인한다. DB 승인 여부만으로 풀이보고서·벡터 준비를
  가정하지 않는다. 520 기출 기준선과 다른 모집단을 억지로 같은 숫자로 맞추지 않는다.
- 새 벡터와 모든 consumer 전환 검증 전에 구형 벡터를 지우지 않는다.

## 공유 설치본 교체

- 현재 `installed_owner_session_provider.py`는 API의 고정 unit과 비어 있는 `DropInPaths`를
  검사한다. 보호된 wheel이라도 API에 임의 `PYTHONPATH` drop-in을 붙이는 방식은 이
  계약에 맞지 않는다. 검증을 느슨하게 하지 말고 기존 호환 release set으로 반영한다.
  API restart가 `Requires`로 연결된 QUERY owner에도 영향을 주는지 함께 확인한다.
- SQLAlchemy FK owner의 import를 전체 테스트의 fixture 순서에 의존하지 않는다.
  실제 owner column을 참조하고 새 subprocess의 cold import/DDL 검사를 포함한다.
  관련 실제 발견과 배포 경계는 `CURATED_EDITABLE_NATIVE_CHECKPOINT_2026-11-04.md`에 기록한다.

## 기억을 관리하는 방식

새로운 durable 판단은 적절한 ADR/설계/운영 문서에 먼저 남기고 여기에는 탐색 포인터만 둔다.
세션마다 과거 대화 전체를 복사하지 않는다. 현재 진행률·계정·비밀값은 저장하지 않는다.
모든 구현을 새 abstraction이나 wrapper로 만들지 말고 단일 책임·map/set/index·typed pointer와
기존 transaction/claim 경계를 우선한다.

## 관련 근거

- [설계 원칙·실제 오류·단순화 수정 목록](../architecture/DESIGN_ERROR_REMEDIATION_REVIEW_2026-11-08.md):
  미수정 결함, 이미 해결된 오류의 구조 후속, 인과 미확인 후보를 구분한다. 다음 수정 전에
  현재 source와 대조하며, 목록 자체를 운영 변경 권한이나 현재 장애 판정으로 쓰지 않는다.
- `AGENTS.md`
- `docs/architecture/MODULE_BOUNDARIES.md`
- `docs/architecture/CREATIVE_SOURCE_VISUAL_RECOVERY.md`
- `docs/operations/BACKGROUND_NATIVE_RECOVERY_2026-11-04.md`
- `docs/operations/BACKGROUND_RESOURCE_RECOVERY_2026-11-04.md`
- `docs/operations/ITEM_DB_SIMILARITY_LIST_RELEASE_2026-11-02.md`
