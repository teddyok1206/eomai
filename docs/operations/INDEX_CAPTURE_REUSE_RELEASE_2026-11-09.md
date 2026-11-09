# INDEX 반복 풀이 해석 병목 수정

## 범위와 원인

사용자 요청: 완료된 임베딩·풀이보고서를 변경하지 않고 임베딩 처리 병목을 해결한다.
정본/완료 데이터 정리, 재생성, 모델·space·recipe 변경, DB migration은 하지 않는다.

기존 INDEX는 중단되지 않았고, GPU 수치 작업 뒤에도 전체 source/report의 JSON Schema와
Pydantic 해석을 반복하고 있었다. 기존 4-target CUDA 작업의 `encode_batch`는
2026-11-09 03:56:43–04:40:03 UTC, workflow 완료는 04:44:12였다. 모델 kernel 시간과
이 전체 처리 시간을 혼동하지 않는다. 별도 읽기 전용 1,556-source 실측은 설계 문서에 있다.

## 검증된 후보

- Source: `a668b70a955b29ecab058d4c0a9ef4f74695229d`.
- [설계](../architecture/PUBLIC_SOLUTION_INDEX_CAPTURE_REUSE.md): 같은 DB root에서만
  strict capture 재사용. 매 호출 current SQL closure·service authority·provenance 검사 유지.
- Source unit/dependency 264 PASS, 최종 focused 84 PASS, disposable PostgreSQL 79 PASS.
  suite들이 겹치므로 합산하지 않는다. 설치본 직접 focused 89 PASS.
- Ruff/format/focused mypy PASS. 전체 import 추적 mypy의 기존 오류는 설계 문서에 분리 기록.
- `scripts/api/deploy_release.sh --build-only`: wheel RECORD와 installed simulation PASS.
- INDEX owner 독립 wheel 설치·실제 interpreter import PASS.
- 이전 설치본 대비 platform JSON resources 1,211개, API contracts JSON 77개 모두 동일.
- 최초 installer 호출은 실행 bit가 없는 보호된 shell 파일을 직접 실행하여 거부됐다.
  설치/운영 변경은 없었다. 동일 검증된 파일을 `/bin/bash`로 실행해 설치 성공했다.

## 설치·전환 경계

INDEX만 `b9007cbd6b3d70fa8b53190f2fa0e1fc552a4ae9`에서 후보로 전환한다.
QUERY와 GPU/CPU numerical runtime `c915281ea3acda63ea066ba9de397f7bbc335295`,
API/Web/Catalog/일반 runner/창작 풀이 owner는 교체하거나 재시작하지 않는다.
CPU/CUDA service grant successor는 source identity/config hash만 갱신하고 범위는 보존한다.
원래 wheel·설정은 보관한다. 운영 되돌림도 진행 중 요청을 먼저 drain하는 공식 identity
handoff이며, 완료 이력을 되돌리거나 DB를 직접 수정하는 rollback이 아니다.

전환 기록은 `/var/lib/eom-index-capture-release-20261109`에 보호된 상태로 남긴다.
수치 작업을 끊지 않는 SIGINT drain을 05:03:38 UTC 요청했다. 원래 PID 931727과
invocation을 고정하고 다음 두 작업이 실제 `COMPLETED`인지 확인한 뒤에만 전환한다.

- CPU: `workflow_65860bfd9ec34ed38219c39b18052fe5`.
- CUDA: `workflow_9cf52cda4a704e16ae7fe362c0b31962`.

정상 종료 뒤 추가 CPU standby가 생기면 `REQUESTED/PENDING/attempts=0`인 정확한 요청에
한해서 기존 `cancel_unstarted_indexing_workflow`를 쓰고 receipt와 replay 결과를 보존한다.
시작한 작업/완료 기록/실패 이력에는 적용하지 않는다. 예기치 않은 상태는 추가 side effect
없이 중단한다. 유한 handoff 대기 service는 새 production queue나 무한 retry가 아니다.

## 데이터 보존 증거

운영 전 기존 행을 identity별 metadata SHA로 고정했다.
`/var/lib/eom-index-capture-audit-20261109/metadata.before.json`:

- encoding 4,946
- source binding 133,530
- index revision 575
- accepted analysis 2,883
- registered report 1,038

여기에는 과거 revision·장치별 관계가 포함되므로 현재 검색 가능 문항 수와 다르다.
배포 후 모든 기존 key/hash가 유지되는지 검사하며 추가 완료 행은 허용한다.
검증용 disposable DB는 공식 cleanup으로 제거했고 운영 DB 테스트/row repair는 하지 않았다.

## 상태

05:40:57 UTC INDEX successor activation 완료. 원래 두 요청 모두 COMPLETED, API/Web/
QUERY/일반 runner PID와 invocation은 유지했다. 05:41:19 새 INDEX가 시작했다.

05:54:29 실제 Registry publication의 정상 savepoint를 새 read set이 거부해
`EMBEDDING_REGISTRY_POINTER_INVALID`로 owner가 종료했다. 실행 결과를 검증하기 전
성공으로 보고하지 않았고 이 로그는 보존했다. Workflow
`workflow_82b2a9e760ea4b1795b2b233c4fc7a28`은 RUNNING/INDEX_PREPARED이며 GPU encoding
4건은 이미 SUCCEEDED/완료 receipt 있음이다. 기존 index head는 유지됐고 완료된 벡터와
보고서의 삭제·재해석은 하지 않았다.

보정은 clean outer root에서만 재사용하고 Registry savepoint/dirty session에서는
기존 strict capture를 사용하는 것이다. 별도 고정 source 후보에서 기존 publication-only
복구를 CUDA에도 적용해 정확한 이 요청의 미완료 등록만 이어간다. 새 모델 실행 없이
원래 prepared index와 SUCCEEDED receipts를 사용한다. 기존 current head가 달라졌거나
다른 활성 요청이 있으면 전환하지 않는다.

추가 disposable PostgreSQL·unit 52 PASS: 실제 savepoint commit/rollback, CPU/CUDA
prepared publication 완료/replay와 numerical forward 증가 0 포함. 첫 추가 실행의
observer savepoint 거부와 CPU-only 테스트 launcher의 CUDA fixture 거부도 보존했다.
보정본의 실제 publication 완료와 최종 데이터 불변성 확인은 아직 진행 중이다.
