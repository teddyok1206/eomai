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
- 기존 1200초 Job 요청은 구 CUDA config/revision을 고정한다. 새 설정으로 조용히
  치환할 수 없다. 다음은 지원된 application에서 그 Job의 무실행/상태를 조회·정식
  종료하고, 새 native config를 audit/probe/seal한 후에만 별도 successor를 제출하는
  순서다. INDEX/QUERY 서비스와 정본 인덱스는 그대로 active이며 GPU default는 CPU다.

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
