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
