# 로컬 임베딩 GPU 실험 — 실행 목표와 완료 기준

작성: 2026-10-20 UTC. 사용자가 GPU 실험을 별도 goal로 승인했다.
이 문서는 새 검색 시스템 설계가 아니라, 이미 구현된 CPU/CUDA 비교 경로의 실제 실행 계획이다.

## 현재 확인한 사실

- 기존 증분 RAG 연결 목표는 완료됐으며 그 acceptance와 정본 이력을 다시 열지 않는다.
- 기존 CPU/CUDA 여섯 비교는 `NOT_STARTED`; GPU 기본값은 아직 승인·활성화되지 않았다.
- 착수 시 GPU는 RTX 5080, VRAM 16,303 MiB, 사용량 2 MiB, utilization 0%였다.
  이는 실행 중 독점·호환성 증거가 아니며 입장 직전에 다시 확인한다.
- 저장소는 `742e7188b49166118dfd44eb357300fdd716be67` 기준 clean이었다.
- 이전 기출 비교 PDF를 위한 다섯 QUERY와 이번 benchmark는 서로 다른 작업이다.
  PDF의 완료 요청을 다시 실행하거나 그 시간을 CPU/GPU 측정으로 재해석하지 않는다.

## 재사용할 원 설계

- [GPU runtime §§6–8](../architecture/INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md)
- [고정 측정 계약](../architecture/INCREMENTAL_EMBEDDING_DEVICE_BENCHMARK_PROPOSAL.md)
- [기존 owner 구성](../architecture/EMBEDDING_BENCHMARK_OWNER_COMPOSITION.md)
- [유한 6회 root 제어](../architecture/EMBEDDING_BENCHMARK_SERIES_CONTROL.md)
- [실제 CUDA 파일 관찰](../architecture/EMBEDDING_BENCHMARK_CUDA_CAPTURE.md)
- [모델 로드 없는 token 준비](../architecture/EMBEDDING_BENCHMARK_TOKEN_PREPARATION.md)

새 DB, queue, vector engine, 모델 재학습, 상시 benchmark service는 만들지 않는다.
기존 supported application/Orchestrator/native worker/Artifact publication 경계를 사용한다.

## 실행 순서

1. **실제 설치·원래 실패 inventory.** CPU/CUDA configuration·bundle·admission·owner·unit과
   physical lease, 현재 INDEX/QUERY 작업을 읽기 전용 확인한다. 예전 script의 미완료 placeholder나
   과거 source pins를 현재 운영 사실로 사용하지 않는다. 진행 중 작업·실패 이력은 보존한다.
2. **고정 입력·실행 준비.** 공식 Catalog 경계로 승인된 기출 6 profile을 길이 층별로 선택하고,
   가능한 3 view의 DOCUMENT 최대18행과 genuine QUERY2개를 pin한다. 기존 tokenizer-only
   준비와 공개 fixture를 사용한다. 준비·root controller를 먼저 완성하고 실제 로그인은 필요한
   직전에 받아 반복 입력을 최소화한다. password 저장·freshness 연장·관리자 사칭은 하지 않는다.
3. **실제 유한 비교.** 같은 모델 payload·recipe·token 입력으로
   `CPU → CUDA → CUDA → CPU → CPU → CUDA`를 기존 original-Job/idempotency 경계에서 실행한다.
   device별 첫 process 안에서 warm-up1, warm5, QUERY2×5, 2048-token capacity batch1/4를 측정한다.
   나머지 process는 cold만 측정한다. 각 실행의 기존180초/RAM6GiB/GPU8GiB 경계를 유지한다.
4. **기존 판정기로 평가.** 원 수치·순위·성능 기준을 결과를 보고 바꾸지 않는다.
   norm 오차≤1e-5, 대응 cosine≥0.99999, component 오차≤1e-4, score 오차≤2e-5,
   gap>4e-5 순서 보존 및 사전 near-tie 규칙을 검증한다. GPU 우수 조건은 warm≤CPU×0.80,
   cold median≤CPU×0.90, 각 QUERY encode/end-to-end≤CPU×1.10, cold max≤CPU max×1.20이다.
   peak RSS/VRAM, 실제 physical lease·cgroup 종료와 image/trainer 공존 증거를 별도로 확인한다.
5. **조건부 운영 선택.** 실제 correctness/performance/resource/isolation/regression을 모두
   통과할 때만 CUDA DOCUMENT/QUERY compatible family와 별도 CUDA index를 연결하고
   default를 활성화·read back한다. CPU index/policy와 rollback 경로를 보존·검증한다.
   GPU가 불리하면 CPU 유지가 정당한 결론이며 임계값을 낮춰 GPU를 억지로 채택하지 않는다.
6. **종료 보고.** 실제 실행·실패·미실행 범위를 구분한 비교표와 Artifact pointers/hashes,
   기본값·복구 상태를 문서화하고 중요한 milestone을 Slack으로 보고한다.

## 완료 및 실패 경계

- 설치/소스 테스트 PASS만으로 측정 완료라고 보고하지 않는다.
- 원 6회 실행과 실제 비교 판정, 필요한 안전 회귀, 조건부 운영 결정·검증까지 종료 근거를 남긴다.
- 기존520개 전체를 device마다 재인코딩하는 것을 비교의 선행조건으로 추가하지 않는다.
- 사람의 유사성/교육 품질 평가는 이 기술 목표의 필수 gate가 아니다.
- 불명확한 실행·revocation·hash/space mismatch·미정리 GPU 작업이면 추가 side effect를 멈춘다.
  실패를 성공으로 덮지 않고 original key의 지원된 reconcile/replay만 사용한다.
- stage마다 원 설계와 대조한다. 공통 소비자·Chat·출제 UI의 무관한 확장이나 별도 연구로 새지 않는다.

## 착수 상태

`GOAL=ACTIVE`, `SIX_MODEL_RUNS=NOT_STARTED`, `DEFAULT_DEVICE=CPU`,
`GPU_SUPERIORITY=NOT_EVALUATED`. 후속 실제 증거로만 갱신한다.

### 06:38 UTC 준비 확인

- 원 benchmark allocation `7255032e`의 입력/정책/실행 Job 조회 결과0: 이전 여섯 모델 실행을
  재실행하거나 알 수 없는 실행에 새 identity를 발급하는 단계가 아니다.
- 원 CPU configuration `e0afda42`의 설치 관찰은 실제 `PASS`; 기존 protected EE owner
  `ee97239d`의 RECORD hash도 원 pin과 같다. 수치 prefix를 다시 설치하지 않았다.
- 현재 API provider는 `60af9e5d`; 운영 QUERY가 고정한 provider/code12개를 실제 설치 바이트와
  대조했다. 예전 `881584aa` provider pin을 그대로 사용해 로그인부터 실패시키지 않는다.
- 관련 집중 소스 테스트118 PASS. 실험 전용 operator의 별도 합성12 PASS, 새 HTTP leaf strict
  type·Ruff/format PASS. 이 수치는 실제 인증/모델/GPU/성능 PASS가 아니다.
- 임시 실험 전용 HTTP leaf는 login/me/system-info만 허용하고 기존 Identity FD capture와
  benchmark application에 세션을 연결한다. C1–C5·Chat·출제·Pack activation은 호출하지 않는다.
  기존 root lifecycle/tokenizer helper는 보호된 정확한 바이트를 재사용하며 루트의 기존
  6회 제어 순서가 동일하다는 AST 회귀를 포함했다. 새 production service는 추가하지 않는다.
- 준비 진단·검사 기록: `/tmp/eom-gpu-experiment-20261020.9jWy7rO3`.
  아직 실제6회와 GPU 기본값 전환은 수행하지 않았다.
