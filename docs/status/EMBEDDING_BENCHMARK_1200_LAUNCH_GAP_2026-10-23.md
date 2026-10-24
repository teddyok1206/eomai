# Embedding benchmark v1.2 launch path — 2026-10-23

## Finding

The protected CPU and CUDA numerical prefixes are intentionally immutable and do not
contain the v1.2 1200-second entrypoint modules. Those modules are present in the pinned
owner release, but the v1.2 systemd templates used `python -m` against the numerical
prefix. The templates were not installed, so the Orchestrator could not launch either
device. This was an installation/composition gap, not a GPU compute failure.

## Correction

The 1200-second units now keep the exact fixed CPU/CUDA interpreter and execution
identity, add only the immutable owner release as a read-only import source, and invoke
the exact device-specific module through `runpy`. The owner admits SHA-256 pins for the
four imported v1.2 modules before launch. A separate narrow Polkit rule allows only the
workflow runner to start an exact CPU/CUDA v1.2 benchmark unit instance. Older 180- and
600-second paths and numerical runtime prefixes are unchanged.

This does not authorize direct service invocation or bypass the Orchestrator's source,
operator, job, lease, artifact and publication checks.

## Verification

- Focused launch, unit-policy and budget-runtime tests: 84 passed.
- `systemd-analyze verify` passed for both v1.2 service/socket templates.
- Ruff check and `git diff --check` passed.
- Numeric CPU/CUDA prefixes remain untouched; GPU utilization was idle at inspection.
- On 2026-10-23 14:10 UTC, all four exact 1200-second systemd templates and the narrow
  Polkit rule were installed; installed service/socket SHA-256 values matched the source.
- `systemd-analyze verify` passed against the installed service/socket files.
- The read-only current-owner observer confirmed INDEX and QUERY remain active, no
  benchmark native unit is active, and no model execution has started. This is not an
  Orchestrator admission or coexistence acceptance.

## Next

Complete the supported Orchestrator recovery/admission for the existing pinned request,
then start the v1.2 CPU/GPU series using the same source window. Preserve all prior failed
attempts as history. Do not change the production embedding default until numerical,
ranking, timing, GPU memory and coexistence checks pass.

## Live follow-up

The source commit was published as `19df8a63bb80b1a1b0959457e9a66b3ce296eaac`.
The protected release operator admitted that exact source and the standard API install
completed. API live/ready health checks passed, and the deployment record is
`/var/lib/eom-api/deployments/19df8a63bb80b1a1b0959457e9a66b3ce296eaac.json`.
The host-level units and Polkit rule are now installed and hash-verified. No v1.2
benchmark launch has been admitted or started yet; the next step is supported Orchestrator
recovery/admission, not a direct unit start.

### 2026-10-23 14:11 UTC — 명시적 600→1200 successor 연결

실험 재개 경로를 따라가다 기존 Orchestrator history가 `/1.1` 600초 실패 참조를
복구했지만, 다음 `/1.2` 1200초 요청의 predecessor로 등록하지 못하는 누락을 확인했다.
기존 `BenchmarkBudget600PredecessorReference`를 그대로 사용해 600초 실패 Job의 exact
decision/event를 새 `/1.2` 요청에 append-only로 연결하도록 지원 경로를 추가했다. 과거
failure는 그대로 남고, 다른 actor/source/model/runtime/access-policy/검색축 변경은 거부한다.
새 schema·migration은 추가하지 않았다. 기존 `/1.0→/1.1`, `/1.2→/1.2` 전이는 유지한다.

- 600초 post-start closure 뒤 동일 입력의 1200초 successor 생성, failed parent 보존,
  event replay, actor 변경 거부를 단위 시험으로 추가했다.
- 관련 history/post-start 단위 시험: 118 PASS; strict mypy, Ruff, formatter, diff check PASS.
- 소스는 아직 운영 API에 배포되지 않았다. 실제 기존 Job closure/admission과 benchmark는
  여전히 미실행이며 GPU default는 변경하지 않았다.
- 14:10 UTC read-only 관측에서는 INDEX/QUERY owner가 active였고 benchmark native unit은
  없었다. RTX 5080은 0%/2 MiB였다. 이 관측만으로 다음 시점의 quiescence를 보증하지 않는다.

### 2026-10-23 14:34 UTC — 운영 인덱싱을 유지한 분리 릴리스 준비

- 수정 commit `2690bf73d8fc71e7a33d10219ee89cd6202e543d`는 main에 게시됐다.
  API build-only/RECORD와 600초 실패→1200초 successor 관련 118개 단위 시험이 통과했다.
- exact source/wheel은 `/var/lib/eom-release-operator-stage.2690bf73-6f1biw_d`에
  별도 materialize됐다. context SHA-256은
  `ae2f9bdb363a3ad4bcbcc27121a2028628fe0c8e2dbf5ab3a480be93a9295e90`이며
  protected operator `ADMIT_PASS`와 migration `0058` read-only verify가 통과했다.
- 공용 API와 현재 INDEX/QUERY owner는 교체하지 않았다. 기존 지원된 owner-release
  installer로 위 commit의 platform/contracts wheel만
  `/opt/eom/embedding-owner-releases/2690bf73d8fc71e7a33d10219ee89cd6202e543d`에
  별도로 설치했다. wheel SHA-256은 각각
  `7cef6555501a386f604de55f7c88cd44eeae586b4423d1bdd76f2ae2f26a1b75`,
  `0a1072a0ffcf7ea6728ef2559b7a5dd9165896efbcedbed5f74c126bb386daa2`다.
  설치기는 `OWNER_ACTIVATION=NOT_PERFORMED`, `CPU_RUNTIME=UNCHANGED`를 보고했다.
- 이전 600초 실행의 정확한 invocation은
  `a038b51d231a47e9866766c8a6b6e476` / Job
  `job_26e206dc11434d52870f51737d15fdbd`다. 이미 존재하던 root 관찰 증거
  `/run/eom-incremental-embeddings/benchmark-poststart-recovery/a038b51d231a47e9866766c8a6b6e476.json`
  의 SHA-256은 `5d7b4325b0015b212530dbfa991b23e229d157542cfe5d27dac57ecd2fcdfdf7`이고,
  `BUDGET600_TIMEOUT`, `cleanup=CONFIRMED`를 기록한다. 이는 공식 Job failure closure나
  1200초 후속 Job 생성의 증거는 아니다.
- 위 proof와 원 요청·invocation을 exact hash로 고정하고 설치된
  `FixedBudget600PoststartInspection`으로 다시 검사한 결과
  `BUDGET600_PROOF_VERIFIED=PASS`였다. 이는 기존 proof를 읽고 OS/출력/retirement
  linkage를 재검증한 read-only 결과이며 Job을 FAILED로 전환하지 않았다.
- 다른 과거 invocation `9b37158957804beeb4be83a8fd04f118`을 600초 실행으로
  잘못 선택한 단발성 proof-mint 진단은 입력 연계 assertion에서 거부됐다. 새 proof,
  DB 변경, 모델 실행은 없었고 해당 실패 helper는 제거했다. 과거 root proof는 변경하지 않았다.
- 14:23 UTC read-only 관측에서 운영 INDEX owner는 실제 CPU를 쓰며 active였고
  Workflow 명령 하나가 유효 lease를 갱신 중이었다. 공용 API 배포로 이를 중단하지
  않는다. 다음은 기존 600초 Job의 지원된 post-start closure를 확인/완료하고,
  위 분리 owner release로 v1.2 successor를 등록한 뒤 운영 owner와 공존하는
  전용 1200초 controller에서 원 6회 측정을 실행하는 것이다. GPU 기본값은 CPU다.

### 2026-10-23 14:57 UTC — 실패 기록 확인과 측정 실행 준비

- 실제 설치된 API release `19df8a63bb80b1a1b0959457e9a66b3ce296eaac`의
  code-member SHA 12개가 pinned wheel과 일치했다. 새 owner release `2690bf73…`는
  공용 API/INDEX/QUERY를 재시작하지 않은 채 별도 설치된 상태다.
- 정해진 Job `job_26e206dc11434d52870f51737d15fdbd`와 실행
  `a038b51d231a47e9866766c8a6b6e476`에 대해 genuine guiadmin 인증과 설치된
  `FixedBudget600PoststartInspection`을 사용한 공식 closure/replay가 통과했다.
  결정 SHA는 `sha256:1181768f0d92103982ed1dffd8c391a1a6659f6abe77c1a7dbdb7f92bd89db4b`이다.
  `created=False`였으므로 이 확인은 이미 존재한 terminal decision의 재현이며,
  새 실패나 성공 Job을 만들지 않았다.
- 후속 1200초 실행은 기존 Orchestrator의 source admission, append-only predecessor,
  CPU capacity, GPU lease, six-launch series, Artifact finalization을 그대로 사용한다.
  운영 INDEX/QUERY 서비스는 중지·재구성하지 않는다. 한시적 root-owned 실행기는
  `/usr/local/libexec/eom-benchmark-budget600-closure-2690bf73/series.py`에 설치했고,
  현재 SHA-256은 `781b5fc966d7f80dd6e5b68adcfb6b48a4e88d2c347c4e203bd5b0fc20aedfa1`이다.
- 분리 owner release에서 successor/series 관련 단위 시험 54개와
  unit-control/launch/CUDA capture 단위 시험 78개가 통과했다. 설치된 구형 API 환경만으로
  시험하면 1건이 실패했으나, 원인은 source가 아닌 pre-successor wheel을 불러온
  테스트 실행 환경 차이였다. 정확한 owner release를 선두 import 경로에 고정한
  재실행에서는 54/54 PASS였다.
- 현재 후속 실행기는 Studio 인증 입력을 기다리고 있다. 이 시점까지 1200초 Job
  등록·native CPU/GPU forward·측정 결과 publication은 아직 없다. GPU 기본값도 CPU다.
- 첫 로그인 대기의 30분 controller timeout이 Job 등록 전에 다가오는 것을 발견해,
  인증 전 대기만 24시간으로 늘리고 미시작 프로세스를 종료·재실행했다. 종료 당시
  parent frame은 닫혔으며 Job·Artifact·model effect는 없었다. 실제 1200초
  measurement/listener budget과 900초 인증 freshness는 변경하지 않았다.

### 2026-10-23 15:17 UTC — 실제 인증 이후 v1.2 조합 누락 발견

- `guiadmin` 인증은 성공했다. 이전 600초 실패 closure 재현과 후속 1200초 정책·입력
  Artifact publication 뒤, `BenchmarkOwnerConfiguration`이 v1.2 정책 member schema를
  허용하지 않아 후속 Job 등록 **전**에 중단됐다. parent의 `BENCHMARK_ROOT_FRAME_CLOSED`는
  이 child 오류의 후속 증상이다. CPU/CUDA 모델 계산은 시작되지 않았다.
- 동일 경로를 정적으로 검토해, 계산 시점에 v1.2 요청을 invocation으로 바꾸는
  Orchestrator mapping에도 v1.2가 빠진 두 번째 누락을 발견했다. 두 mapping을 수정하고
  실제 v1.2 정책 Artifact admission과 invocation 생성 회귀 시험을 추가했다.
- 기존 정책·입력 publication은 불변 이력으로 보존한다. 동일 idempotency key·내용으로
  재실행 시 정확한 replay만 허용하며, 새 identity로 실패를 덮지 않는다. 인증 세션은
  실패한 실행 프로세스에서 종료됐으므로 코드·릴리스 준비를 끝낸 뒤에만 새 인증을 받는다.
- 관련 158개 단위 시험과 Ruff/format/diff 검사가 통과했다. 운영 분리 owner release
  반영 및 실제 CPU/GPU 측정 결과는 아직 남아 있으며 GPU 기본값은 변경하지 않았다.

### 2026-10-23 15:25 UTC — 수정된 분리 owner release 설치

- 수정 commit `801672a6bd8bf02416a642734e05a27071333c49`를 GitHub main에 게시하고
  source/wheel RECORD 검증을 통과했다. 이를 분리 owner release
  `/opt/eom/embedding-owner-releases/801672a6bd8bf02416a642734e05a27071333c49`
  에 설치했다. 공용 API, CPU 숫자 환경, INDEX/QUERY owner는 교체하지 않았다.
- root controller는 이전 실행 파일을 덮지 않고 새 경로
  `/usr/local/libexec/eom-benchmark-budget600-closure-801672a6/series.py`에 설치했다.
  SHA-256은 `4fd7a62194220fe8f20f0c1400cf06eb787b44f67a76beb122fedf83d8656751`이다.
  이전에 발행된 정책·입력 Artifact의 replay에는 기존 publication source commit을
  고정하고, 새 실제 실행의 owner source는 위 수정 commit으로 분리한다.
- 설치본에서 v1.2 policy pointer 검증과 invocation 생성·계약 검증을 직접 실행해
  `INSTALLED_V12_POLICY_AND_INVOCATION=PASS`를 확인했다. 새 실행 프로세스는 현재
  실제 `guiadmin` 인증 입력을 기다린다. Job 등록·native CPU/GPU forward·측정 완료는
  아직 주장하지 않는다.
- 인증 대기 중에는 합성 실행 adapter로 v1.2의 CPU/CUDA 여섯 순서, 같은 Job 내
  invocation 계약, 완료 후 중복 dispatch 없는 정확한 replay를 추가 검증했다.
  owner 관련 13개 시험은 PASS다. 이는 실제 모델·GPU 실행 결과가 아니다.

### 2026-10-23 16:11 UTC — 반복 인증 실패의 원인과 GPU 호스트 후속본

- 실제 인증 후 v1.2 Job `job_25ebde2af2fd42c9804e1f4743b0b406`은 등록됐으나
  CPU/GPU launch 전에 root CUDA 설치 캡처가 실패했다. 새 요청을 중복 제출하거나
  모델을 실행하지 않았다. Job의 현 상태와 영구 종료 경계는 후속 application 조회로
  확인해야 한다.
- 인증 입력이나 CUDA 장치/lease가 근본 원인이 아니었다. root 실행기의 cwd가
  `/opt/eom/embedding-cuda-loader-empty`여야 하고, 고정된 CUDA loader cache를
  `/etc/ld.so.cache`에 읽기 전용 bind한 namespace가 필요하다. 격리 preflight에서
  이 두 경계를 만족시키자 설치 검사가 다음 단계로 진행됐고,
  `INSTALLED_RUNTIME_FILE_HASH_MISMATCH`로 정확히 거부됐다.
- 차이는 10월 23일 OS `libz.so.1.3` 갱신이다. 기존 CUDA host extension 1.1은
  10월 21일 CPU host 기준선과 구 `libz` SHA에 고정돼 있었다. 현재 `libz` SHA는
  `f61677c7bdb7c2aa2a243ea781bfd16afcb361cede7b4ef76127a9d8eb9a5242`이며,
  이미 복구된 CPU host snapshot revision은
  `embeddinghostconfigrev_76048812b8d740ad9ebedfe76bbf5ed4`다. 해시 검사나
  fail-closed 판정을 완화하지 않았다.
- 기존 Catalog publication owner를 사용해 새 CPU 기준선에 묶인 CUDA host extension
  1.1 `embeddingcudahostrev_9f0a51460391d3c89ed1863cc55ddb96`을 별도 revision으로
  게시했다. snapshot raw SHA는
  `sha256:850bc785fa28a64b87c1124470c1a2a5ae47f0289dac46af33c239c97dc12da7`다.
  먼저 생성된 1.0 revision `embeddingcudahostrev_aa36304eb33100768779a975cc59b17c`은
  필요한 NVML 계약이 없어 선택하지 않는다. 두 이력 모두 덮어쓰지 않는다.
- 기존 native config의 model/bundle/proof/numerical runtime을 그대로 둔 host-only
  successor `embeddingnativeconfigrev_948f76281b8b01e361de1a3b9d8884a5`를
  게시했다. raw SHA는
  `sha256:7d8aef012c9e957f41ad888eadc6e214568e01aae490aa134851dcdb22cbe087`다.
  게시 전 원본·host·proof·bundle 계약과 정확히 세 필드만 바뀐 delta를 검증했다.
  상태는 **PUBLISHED_NOT_ADMITTED**이다. native prefix audit, no-forward probe,
  새 receipt/seal 없이는 이 설정으로 benchmark를 시작하거나 GPU 기본값을 바꾸지 않는다.
- 당시 controller의 별도 backend selection은 구 CUDA config/revision을 고정한다.
  후속 source 재검토에서 **BenchmarkOwnerRequest 자체는 이 설치 pin을 포함하지
  않는다**는 것을 확인했다. `embedding_benchmark_handoff.py`의 설치 검증은 같은
  profile·bundle·installed proof·numerical runtime을 유지하는 새 host-only config와
  그 config의 새 receipt를 별도로 검증한다. 따라서 새 native config를 audit/probe/seal하고,
  실제 Job이 VALIDATED/launch0/PREPARED0임을 확인하면 **원 요청·원 Job의 정확한 replay**를
  우선한다. controller pin과 요청 불변성을 혼동한 이전의 'Job 종료 후 successor 필수'
  판단은 철회한다. INDEX/QUERY 서비스와 정본 인덱스는 그대로 active이며 GPU default는 CPU다.

### 2026-10-23 16:18 UTC — 빠른 격리 CPU/GPU 실측 (운영 acceptance 아님)

사용자 요청에 따라 정식 native 재인증과 분리해, 기존 BGE-M3 payload 모델
`embeddingmodelrev_32de764c92823791bc6ba4f35fffedd9`을 같은 프로세스에서
CPU→GPU로 옮기며 짧은 합성 과학 문장 18개를 측정했다. 외부 API, DB, NAS,
INDEX/QUERY 서비스, benchmark Job에는 접근·변경하지 않았다. root-owned 일회성
진단 스크립트는
`/usr/local/libexec/eom-quick-embedding-benchmark-20261023/bench.py`, SHA-256
`6e5413a0f9e63bd789782f6d70309bb457b5c4fadc7da21450456fdfe7e14bf6`다.
격리된 transient unit에서 기존 공유 GPU lease를 획득했고, offline/local-only
로딩과 동일 토큰 입력·CLS/L2/FP32 경로를 사용했다. 각각 warmup 후 한 번씩
추론 시간을 측정했다.

| 지표 | 실측 |
| --- | ---: |
| 18문장 CPU 추론 | 0.898초 |
| 18문장 GPU 추론 | 0.022초 |
| 추론 구간 GPU 속도비 | 40.46배 |
| 모델 CPU 로딩 | 0.812초 |
| CPU→GPU 모델 이동 | 1.557초 |
| GPU peak allocated | 2,200MiB |
| 정규화 벡터 최대 절대차 | 2.9×10⁻⁷ |
| 첫 문장 기준 상위 5개 순위 | CPU/GPU 동일 |

unit은 `success/exit0`로 종료했고 종료 후 `nvidia-smi` 사용량은 다시 2MiB/0%였다.
입력 hash는 `03f12f15def95d7a511a79e3e0c93745d43e0ffd068b3e7c9150f752f6f1bb44`다.
짧은 입력 한 번의 GPU 추론만 보면 빠르지만, 처음 모델을 GPU로 옮기는 1.557초가
CPU 18문장 한 번의 0.898초보다 길다. 따라서 이 단발 측정만으로 GPU 기본값을
바꾸지 않는다. 긴 문항 입력, 반복 배치, 실제 corpus/검색, 공존 및 운영 native
admission은 아직 별도 검증이 필요하며 정식 v1.2 Job은 여전히 미완료다.

### 2026-10-23 16:41 UTC — 인증 전 실행 호환성 재검토

- 지원된 CUDA private-successor installer가 source `801672a6…`의 새 prefix를
  전체 byte audit했다. operation은 `/opt/eom/.embedding-index-install-X7vh446f`,
  input SHA는 `sha256:8069898a0aca40a3d9eb8b8d721840399933562ec812ba4700017b95cfaa31fc`다.
  이전 prefix는 `.embedding-index-prepublication-CUDA_INDEX_FP32-.embedding-index-install-X7vh446f`
  에 보존했다. 아직 **AUDITED_NOT_ADMITTED**이며 runtime 활성화·모델 실행은 없다.
- 동시에 실제 설치된 v1.2 worker overlay를 모델 없이 검사해 다른 불일치를 확인했다.
  원 CPU/CUDA bundle의 HOST_L2 구현은 `440d7406…`인데, main 전체 wheel 및
  overlay `9e6efc…`의 같은 파일은 `e913b2a0…`다. 차이는 정규화 계산이 아니라
  나중에 추가된 혼합 profile 검색 보조 함수다. 그러나 기존 계약은 실제 전체 member
  hash를 pin하므로 수치가 같다고 무시할 수 없다. 위 새 prefix도 같은 차이가 있으므로
  이 상태로 native probe/seal하거나 사용자에게 로그인시키지 않는다.
- 가장 작은 일관된 수정은 비수치 검색 helper를 그 유일한 소비자인
  `similarity_context_service`로 옮기고, 기존 numerical member bytes를 정확히
  복원하는 것이다. 별도 작업 트리에서 현재 v1.2·host·성능 수정은 유지한 채 이
  경계 수정과 parity/no-ML 회귀 검사를 준비 중이다. 기존 main이나 불변 설치 release를
  덮어쓰지 않는다. 새 coherent worker release와 그 release를 고정한 unit/root adapter를
  검증한 뒤 원 Job을 replay한다. CPU 운영 prefix와 INDEX/QUERY는 교체하지 않는다.
- 기존 v1.2 owner/launch history/backend selection/unit composition 집중 시험
  **52 PASS**다. 실제 설치 file/member 비교는 이 source 시험과 별도이며, 위
  불일치는 source 시험 PASS를 runtime PASS로 확대하지 않고 찾아낸 결과다.
- 실행기의 `session_covers(memory,820)`는 서버 정책이 아닌 과도한 사전 heuristic으로,
  로그인 약 80초 후부터 재인증을 요구했다. 임시 실행기에서는 깨끗한 launch 경계의
  시작 여유만 30초로 수정했다. 실제 `AuthenticatedSessionFence(...,900)`와 원
  authenticated_at·token expiry·실행 중 인가 검증은 변경하지 않았다.

### 2026-10-23 17:18 UTC — 수치 보존 설치·실제 CUDA 증명·로그인 전 점검 PASS

- 검색용 보조 함수를 기존 similarity application으로 옮겨 HOST_L2 정본 bytes를
  `440d7406…`로 복원했다. coherent worker source는
  `d381e6bc480606a828898ebe2e9942dd8a143677`, controller source는
  `8c24720c11bc4512e5fa4377bfbcd32faac36c0a`로 분리했다. worker의 실제 세 구현
  hash는 CPU/CUDA bundle의 `3487cae0… / 440d7406… / f667e54d…`와 같다.
  source 700 PASS, 추가 six-launch/replay 1 PASS, root/unit 관련 207 PASS와 최종
  pin 수정 후 66 PASS, strict mypy·Ruff·format·세 wheel RECORD·설치 app simulation이
  통과했다. 테스트 묶음은 일부 중첩되므로 합산 총계로 표시하지 않는다.
- CUDA numerical-preserving prefix의 최종 byte audit operation은
  `/opt/eom/.embedding-index-install-Ttqz0Vmk`다. input SHA
  `f6fe4184f1b5fd66a958d95b029b1eaa28400085c6a0346c33d00cb0cb1d7550`, inventory raw SHA
  `f37ad2b8193b51fe470757fc7f6b0725635af5a7800a88a12872fd1e98c12c2c`, semantic SHA
  `9c961fe95239d72a3e202455a47c779e2c981df8ef1a46f88e1611411b3a4616`이며
  31,804 entries / 8,993,677 bytes다. 두 이전 prefix와 실패/미승인 단계는 보존했다.
- CUDA cache를 기존 exact CAS 경계로 34ed→9f0a로 선택했다. 실제 no-forward probe
  `6240ba87aac94954bf78bb1dfbc1ff56` / invocation
  `48a8d6199a1c436596f10c61f164813f`의 READY·FINAL ACK와 종료 검증을 통과해 config948의
  설치 receipt를 새로 seal했다. raw SHA는
  `246b12d92854ac0fb9d456129136c251f05274d3f5b8aa7af8a249a07f4e793a`다.
  runtime `d0887315…`, model/tokenizer constructors 및 forward는 모두 0이었다.
- seal·root readback 뒤 retirement 기록 디렉터리의 namespace가 read-only라 정리만
  실패했다. 원 성공/receipt/terminal 관찰을 보존하고, 별도 설치된 일회성 operator가
  exact hash와 실제 PID1·GPU 자원을 재검증해 **같은 실행만** 지원된 retirement로
  정리했다. 새 probe나 모델 실행은 없었다. 최종 probe는 inactive/dead, MainPID0,
  FDSTORE0, GPU2MiB/0%다. 원 실패를 성공으로 바꾸거나 root stage를 덮지 않았다.
- v1.2 CPU/CUDA unit은 d381 worker를 선택하며, root8c는 그 정확한 unit/member bytes를
  pin한다. 이전 두 template은 `/var/lib/eom-benchmark-unit-release-8c24720c`에 보존했다.
  unit 교체 전에 private source mode/atime 검증 두 시도가 효과 전에 거부됐으며, 정본
  template은 변경되지 않았음을 확인한 뒤 보호 입력과 안정 epoch로 수정해 선택했다.
  기존 v1.0/v1.1·180/600 unit/schema bytes와 운영 CPU prefix는 변경하지 않았다.
- 새 backend selection은 CPU의 이미 승인된 configfa/receipta090와 새 CUDA config948/
  receipt246b를 사용한다. 보호 파일 SHA는
  `d9b9b649aed528d5af27452102fef02976492a0311f8dab9f783f73e93ff30df`다. 실제 설치
  config/bundle/proof, 두 interpreter+worker의 실제 세 수치 hash, v1.2 unit hashes,
  root CUDA 설치 캡처 및 native CPU quiescence를 **인증 없이** 점검해 PASS했다.
  이 점검의 model forward와 DB writes는 0이다.
- root controller bootstrap의 누락된 namespace 경로(없는 Slack 파일, private `/tmp`의
  API wheel, Identity provider가 O_PATH로만 보유하는 api.env metadata)를 로그인 전에
  확인·바로잡았다. 실패한 세 bootstrap은 Python 미시작 또는 인증 전 종료였으며
  Job/Artifact/모델 효과가 없다. 보호 경계는 actual 입력만 정확히 노출하도록 수정했다.
- 현재 유한 controller `eom-embedding-benchmark-series-ready-8c24720c.service`가 실제
  `BUDGET1200_LOGIN_READY`로 입력 대기 중이다. tmux `EOM:2 gpu-embedding`의 기존
  입력창을 유지하며 원 Job25ebde의 exact replay만 허용한다. series.py SHA는
  `37e64873e98f834519fd1f80487df446bbd01725987663621c92b295f2508c54`다.
  이 시각 정식 6회 실행과 결과 finalization은 아직 시작 전이며 CPU 기본값을 유지한다.
  Slack readiness milestone `devreport_9513dec846da4005b0df4ddf7ca08d5f`는 SENT/HTTP200이다.

### 2026-10-23 17:48 UTC — 인증 오류 분류와 같은 창 재입력 지원

- 17:23의 기존 controller 입력은 API audit에서 HTTP401 /
  `AUTH_INVALID_CREDENTIALS`로 확인했다. 계정은 ACTIVE·미삭제·잠금 없음이며,
  비밀번호 불일치 실패 1회였다. 비밀번호나 그 hash는 조회하지 않았다. 이 실패는
  GPU·모델 오류가 아니며 정식 비교 launch와 Job/Artifact 변경 전에 발생했다.
- 현재 controller는 `eom-embedding-benchmark-verified-8c24720c.service`다.
  이전 `series-ready` unit과 구분한다. `EOM:2 gpu-embedding`의 한 입력창에서
  실제 HTTP401 비밀번호 불일치일 때만 새 사용자 입력을 최대 3회 받는다.
  비밀번호 저장·재사용·인증 생략·권한 확대는 없다. 다른 오류는 명시적으로 중단한다.
- 로그인 전에 기존 Orchestrator DB 설정으로 실제 `eom_app` / OID16385 연결을
  확인했다. 실행 service에 reference-query 전용 DB 자격을 주입하지 않는다.
  `BUDGET1200_CONTROLLER_DATABASE_READY`와 `BUDGET1200_LOGIN_READY`가 출력됐으며,
  이 시각 실제 프로세스는 살아 있고 사용자 입력을 기다린다. 인증 성공이나
  six-launch 완료로 해석하지 않는다.
- 현재 보호 controller SHA는
  `c8494a6b21235eae52511cb9b803c0f558c285d3fb53a6ee71e145f794174b40`,
  HTTP helper SHA는
  `2fb8c3bdd7a81a22ef2593c8acad16a40dfea3de7aeecce8174cd9d2d4c11589`다.
  helper의 mock/non-network 시험 36 PASS, Ruff·format·strict mypy PASS다.
- 각 ordinal 완료 후 동일한 기존 completed-query selector를 공개 API로 read-only
  조회해 운영 검색과의 공존을 확인한다. 새 검색·임베딩·문항은 생성하지 않는다.
  6회 뒤에는 새 owner instance로 finalization을 replay하여 `created=false`와
  동일 결과 pointer/hash를 요구한다. 원 Job25ebde와 request SHA는 변경하지 않는다.
  정식 비교·공존·정리는 아직 미완료이고 운영 CPU 기본값은 유지한다.

### 2026-10-24 01:24 UTC — 실제 인증 성공 후 공통 module 중복 읽기 수정

- 기존 verified8c controller에서 실제 로그인이 성공했고, 원 Job25ebde / request
  `d1dfc45c…`를 `created=false`와 빈 launch history로 replay했다. 이후 첫 모델
  실행 전 `FixedBenchmarkLaunchExecution.assert_installed()`에서
  `INSTALLED_RUNTIME_REPEATED_BYTE_READ`로 종료했다. 실제 정식 native 비교 unit은
  생성되지 않았다. source 순서상 이 검사는 capacity/Job transition/reservation 전이다.
- v1.2의 CPU·CUDA는 하나의 d381 package를 공유한다. 실행 adapter가 공통
  budget-entrypoint/policy member를 device별로 두 번 `files.read()`한 것이 원인이다.
  snapshot의 중복 byte-read 거부는 올바른 동작이므로 이를 완화하지 않는다.
  adapter에서 exact path→expected hash map으로 네 member를 한 번씩 계획·검증하고,
  같은 path의 서로 다른 pin은 명시적으로 거부한다. 이후에는 기존 epoch 검증을
  유지한다. root의 후속 `/proc` owner 오류는 먼저 종료한 child의 cascade다.
- 실제 `NumericalRuntimeFileSnapshots`를 쓰는 회귀 시험은 unit 4개+module 4개의
  1회 읽기, 두 번째 검사에서 byte 재읽기 없음, 초기 hash 변조·이후 epoch 변조 거부,
  충돌 pin 거부를 검증한다. budget/runtime **60 PASS**, launch/owner/progress
  **38 PASS**, strict mypy·Ruff·format·diff check PASS다. 두 시험 묶음은 별도다.
- 수정 대상은 controller adapter와 시험뿐이다. native d381 worker·수치 구현·
  v1.2 template·계약·GPU receipt는 변경하지 않는다. 새 controller wheel만 별도로
  설치하고 동일 원 Job을 다시 확인할 예정이며, 현재 정식 측정 결과는 미완료다.
  운영 INDEX PID130161 / QUERY PID898231은 그대로 active이고 GPU는 2MiB/0%다.
