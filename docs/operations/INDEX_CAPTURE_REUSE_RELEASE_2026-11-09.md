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
보정본의 실제 publication과 데이터 불변성은 아래 실행 증거에서 별도로 확인한다.

## 보정 릴리스

- INDEX source `4a2e242aa5c710550c6d4d6a160dfc98db08094a`.
- 추가 source unit/dependency/context 207 PASS, 별도 설치 wheel 직접 focused 31 PASS.
- 새 platform wheel SHA-256
  `acc8237c3b2d4839e8ad2a5e397a4fa6cf0ddad9e7c8cd22f33a1a7a011007f0`.
- 새 contracts wheel SHA-256
  `a502f56b4eced75e4efd2b1bd4dcdb6a95205bc0519cadccbdde218b9398d796`.
- 두 후보 사이 platform JSON 1,211개와 API contracts JSON 77개는 byte-identical.
- 설치·동등 grant·전환 기록:
  `/var/lib/eom-index-savepoint-release-20261109`.

실행 중인 numerical 작업이 없고 원래 command lease가 만료된 뒤, 정확한 준비 요청의
request/intent/registration hash, 성공한 numerical receipt 4개와 기존 index predecessor를
대조했다. 첫 전환 preflight는 관계없는 과거 namespace까지 세어 거부했고 DB 변경 없이
종료했다. 원래 service revision과 public-solution scope로 한정해 다시 검증했으며,
과거 비완료 기록을 취소·수정하지 않았다. INDEX만 보정 source로 선택하고 새 daemon은
아직 시작하지 않은 상태에서 기존 publication-only application을 호출했다.

2026-11-09 06:16:31 UTC 같은 prepared CUDA request의 등록 복구를 시작했다.
06:19:27에 GPU index의 binding count가 936에서 940으로 증가했다. 06:33:54
`encode_batch=SUCCEEDED`, 06:37:25 `complete=SUCCEEDED`가 기록됐다.
이 시각에는 원래 CUDA 미완료 요청이 더 이상 없었다. 명시적 복구의 final read와
INDEX 자동 처리 재개는 이 DB 완료 확인과 구분한다.

## 완료 데이터 불변성

`/var/lib/eom-index-capture-audit-20261109/metadata.verified.json`의 전후 비교:

| 기존 저장 데이터 | 기존 행 | 변경 또는 누락 | 새 행 |
| --- | ---: | ---: | ---: |
| Encoding | 4,946 | 0 | 12 |
| Source binding | 133,530 | 0 | 12 |
| Index revision | 575 | 0 | 3 |
| Accepted analysis | 2,883 | 0 | 0 |
| Registered report | 1,038 | 0 | 0 |

새 행에는 배포 전 자연 완료시킨 CPU/CUDA 작업과 이번 준비된 CUDA publication이
함께 포함된다. 기존 numerical 결과 4건을 다시 실행한 횟수가 아니다. 원래 실패
service invocation과 workflow의 재claim/복구 이력도 보존했다. 현재 GPU의 distinct
문항 binding은 기출 427, 등록 문항 513이다. 서로 다른 device/view의 encoding 행 수를
이 문항 수로 대체하지 않는다. 추가 임시 DB도 공식 cleanup으로 제거했다.

## 복구 완료와 자동 처리 재개

06:40:49 UTC publication-only application도 최종 검증을 마쳐 `COMPLETED`를 반환했다.
원래 command 한 개를 재claim했고, numerical 실행은 executor에서 금지된 상태였다.
새 index는 `embeddingindexrev_d70ba3fe844fc913a248cd121457c504`, SHA-256은
`4bea4b8953ddbd2e2578129fb1e14f6ef6c8877508c78009bff17f71dd1243ea`다.
같은 명령 replay의 무계산/무중복 동작은 disposable CPU/CUDA 테스트로 확인했으며,
이번 live 복구를 다시 호출해 전체 원본 검증을 반복하지 않았다.

06:41:21 INDEX daemon을 시작했고 06:41:43 다음 reconciliation이 실제로 시작됐다.
PID 1821159 / invocation `3997555c68b84b52814eccb55bc1e55e`다. 기존 API
`eom-api.service` PID 855959, QUERY PID 856231, Web PID 969034와 각각의 invocation은
유지됐다. 복구 raw snapshot의 `eom-application-api.service`는 존재하지 않는 이름으로,
API 판정에 사용하지 않는다. `resumed.json`에는 정확한 `eom-api.service`를 확인했다.

재개 후 `metadata.verified.final.json`으로 같은 기존 key/hash 전부를 다시 대조했고
변경·누락 0건이었다. 실제 새 owner의 `PUBLIC_POPULATION_REVALIDATION`은 11,156ms.
06:42 memory current 약 846MiB, swap 0을 관측했다. 이는 해당 읽기 단계의 실측이지
새 일반 batch 전체 완료나 전체 corpus 완료를 뜻하지 않는다. 새 정상 batch의 전체
처리시간과 남은 corpus 진행은 기존 10분 observer가 계속 기록한다.
