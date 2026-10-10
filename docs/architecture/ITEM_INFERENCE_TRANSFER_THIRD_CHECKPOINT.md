# 문항 핵심 착상 전이 — 제출·준비·실행 경계 검증

상태 시각: 2026-10-10 UTC. **소스 검증 기록**이며 운영 활성화 또는 교육 품질 승인 기록이 아니다.

## 이번에 구현·검증한 것

- 별도 Workflow 요청 계약을 먼저 정의했다. 비교 요청·두 profile·Graph·정책 revision/hash와 최초 권한 snapshot hash를 보존한다. 실제 사용자는 서버의 인증 경계에서 공급해야 하며, 요청의 해시나 내부 context는 권한을 부여하지 않는다.
- 같은 사용자의 동일 요청은 기존 idempotency 경계로 재사용한다. 다른 사용자는 같은 profile을 선택해도 별도 Workflow를 갖고, 다른 사용자의 global idempotency key를 재사용하면 충돌한다. 기존 요청 loader와 fingerprint 의미는 바꾸지 않았다.
- 정본 V1/V2/V3에서 정답·해설을 제외한 문제 본문과, 출처가 확인되는 최소 metadata를 분리했다. 표 셀·선지·단위·부정·수식 원문을 보존하고 길이 초과를 조용히 자르지 않는다. 그림은 pixels가 아니라 원문 alt text/slot만 반영한다.
- V21은 실제 Workflow 정책·권한 pins와 준비된 core/full prompt SHA에 연결한다. 실제 job/step/artifact가 포함된 RoleInput도 준비 단계에서 다시 검증한다.
- 실행 전에는 공개된 instruction bundle의 정확한 ROLE rubric 소속을 확인한다. 임의 rubric pointer를 allowlist에 추가하지 않는다. 실제 manifest·Markdown·prompt bytes 및 안전한 파일 identity를 검증하고 기존 순서대로 `AGENTS.md`를 구성한다.
- 비교 목적에서만 기존 worker adapter의 `prepare → materialize → run_prepared`를 명시적으로 호출한다. 준비 실패·실행 직전 권한 취소는 실패 이력을 보존하고 슬롯을 반환한다. 실제 launch 이후의 불확실한 상태만 기존 프로세스 복구 경계로 넘긴다. 기존 V1–V20 실행 의미는 유지한다.

## 실제 실행 결과

| 검사 | 결과 | 증거의 범위 |
|---|---:|---|
| 관련 source 회귀·계약·패키지 검사 | 693 PASS | 기존 26개 묶음에 새 요청·원문 투영·V21 준비·실행 및 기존 제출/runner/resolver/의존성 검사를 포함. snapshot producer의 미완료 검사는 포함하지 않음 |
| 변경된 production Python 8개 strict mypy | PASS | request/context/schema, Orchestrator/materializer, admission/repository, 원문 투영 |
| 임시 PostgreSQL 검사 | 42 PASS | 기존 검색/권한·후보·stage 검사 38개 + 새 Workflow 제출 검사 4개 |
| 신규 제출 PostgreSQL 4개 | PASS | 사용자별 분리/replay, 다른 사용자의 key 충돌, 실제 unique constraints, 두 동시 요청의 Workflow/event 단일 생성 |
| migration cycle | PASS | 임시 DB에서 `0051 → 0050 → 0051`; 운영 DB에는 적용하지 않음 |
| 임시 DB cleanup | PASS | 지정된 disposable DB·roles·보호된 임시 환경 파일만 지원 스크립트로 정리; 운영 데이터/Artifact 삭제 없음 |
| 설치 패키지 검사 | PASS | checkout 밖의 임시 wheel에서 새 request/context/materializer import 및 schema resource 로딩. 호환 운영 release set 배포·승인으로 확대 해석하지 않음 |
| 원문 보존·predecessor protocol hashes | PASS | 최초 답변 원문과 기존 29개 workflow role bundle hashes 유지 |

42개 PostgreSQL 검사는 `/tmp/eom-api-testdb-20261010095828_ee7d15dc`의 기존 marker/database/user/schema/head guard를 사용했다. Source 작성 중 잘못된 package-root import로 최초 migration invocation이 실패했으나 DB migration 적용 전이었다. 공개 `schemas` 모듈 import로 정정한 뒤 같은 disposable DB에서 정상 migration cycle과 검사를 실행했다. 추가 DB를 우회 생성하지 않았다.

693개 source 검사 전 첫 invocation은 존재하지 않는 dependency test 파일명으로 수집 없이 실패했다. 실제 파일명을 확인해 다시 실행했다. 준비 단계 실패를 감지하는 테스트 작성 중 잘못된 preflight 위치와 테스트 전용 import/export·format 오류도 수정하고 관련 검사를 재실행했다. 실패를 성공 이력으로 바꾸지 않았다. 중간·최종 suite는 겹치므로 단순 합산하지 않는다.

## 아직 완료가 아닌 것

- 승인된 실제 사용자로부터의 운영 corpus snapshot 준비/읽기/최종 재인가 연결.
- 전용 비교 목적의 preset/instruction bootstrap, V21 resolver, Runner의 purpose-aware 실행 및 비교 결과 pointer.
- 실제 운영 설치·호환성 승인·bounded Codex pair canary. 기존 support/PDF/출제 preset을 바꿔 비교를 실행하지 않았다.
- 실제 corpus의 세 표현과 공식 Graph baseline 비교, token overflow/coverage·처리 비용 측정.
- 사람의 풀이 전이 위치 평가. 모델 cosine이나 합성 예제의 expected label을 사람 품질 PASS로 사용하지 않는다.

[권한 있는 snapshot 설계](ITEM_INFERENCE_TRANSFER_AUTHORIZED_SNAPSHOT.md)의 계약·owner producer 구현은 별도로 진행 중이다. 실제 내부 자료를 읽을 때에는 인증된 Scientific Studio 사용자를 사용해야 하며, 로그인 ID만 알려주는 것으로 인증·권한이 생기지 않는다. 작업 중인 source family의 존재가 private socket/API에 해당 operation을 활성화하지 않는다.

현재: `GOAL=ACTIVE`, `HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`, `PRODUCTION_ACTIVATION=NOT_PERFORMED`. 다음은 권한 있는 snapshot과 전용 실행 목적의 연결을 소스에서 닫고, 실행 권한·호환 release 준비가 된 후 bounded 실제 자료 실험을 수행하는 것이다.

## 관련 문서

- [변경하지 않는 설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)
- [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md)
- [Workflow 요청·입장](ITEM_INFERENCE_TRANSFER_WORKFLOW_ADMISSION.md)
- [전용 목적·준비·실행](ITEM_INFERENCE_TRANSFER_EXECUTION_PURPOSE.md)
- [이전 실험 검증](ITEM_INFERENCE_TRANSFER_SECOND_CHECKPOINT.md)

실제 문항·worker prompt/result·모델 파일·긴 실행 로그·인증 정보를 Git이나 Slack에 넣지 않는다.
