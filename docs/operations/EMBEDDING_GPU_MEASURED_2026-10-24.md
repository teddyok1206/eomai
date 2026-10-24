# CPU/GPU 임베딩 비교 실측 완료

2026-10-24 UTC. 고정 입력 비교는 **MEASURED**, 운영 기본값 결정은 **KEEP_CPU**다.
GPU 반복 계산은 빨랐지만 cold 시작을 포함한 사전 전환 기준은 통과하지 못했다.
이를 GPU 미실행이나 전체 운영 GPU 활성화 PASS로 해석하지 않는다.

## 결과

| 중앙값 | CPU | CUDA | 해석 |
|---|---:|---:|---|
| cold end-to-end, 장치별3회 | 130.532초 | 141.661초 | GPU가 약8.5% 느림 |
| warm 문서 배치, 장치별5회 | 61.213초 | 15.434초 | GPU가 약3.97배 빠름 |
| 질의1 encode, 장치별5회 | 6.799초 | 6.102초 | encode만 소폭 개선 |
| 질의2 encode, 장치별5회 | 6.345초 | 6.103초 | encode만 소폭 개선 |
| 질의1 end-to-end | 15.589초 | 15.591초 | 실질적으로 비슷함 |
| 질의2 end-to-end | 15.051초 | 15.593초 | 전체 경로는 GPU가 소폭 느림 |

cold는 시작·검증·모델 적재를 포함하고 warm은 이미 적재한 모델의 배치 계산이다.
warm 약4배를 Studio 전체 응답 속도 약4배로 확대하지 않는다. 이는 같은 BGE 모델·FP32·
고정18행/2질의 및 합성 경계 사례의 제한된 비교이며, 전체520개를 GPU로 재구축한 결과나
새 모델 학습이 아니다. 첫 CUDA 실행 일부 구간에는 소스/임시DB 검증과 후보 빌드가 겹쳤다.
후속 cold 측정 동안에는 큰 검사/빌드를 중지했다. 무경합 일반 성능의 보편적 보장은 아니다.

사전에 고정한 기준은 warm 중앙값20% 이상 개선, cold 중앙값10% 이상 개선,
cold 최대값과 질의 지연의 허용 범위 유지다. 이번 실패 사유는
`COLD_MEDIAN_NOT_SUPERIOR` 하나이며 결과를 본 뒤 기준을 바꾸지 않았다.

## 수치·순위·자원·공존

- 유효 측정 CPU3/3, CUDA3/3. 기존 CPU1을 보존하고 같은 Job에서 나머지5회만 이어갔다.
- norm/component/cosine/query-score/wide-gap-order/cluster-order/top5-boundary/
  same-device 실패 수가 모두0이다. NUMERICAL=PASS다.
- SOURCE_AUTHORIZATION, RUNTIME, CAPACITY, GPU_LEASE, CLEANUP=PASS.
- 첫 CUDA 전체 검사에서 reserved7,346,323,456 bytes, whole-process 관측 상한
  7,701,790,719 bytes, whole-device 관측 상한7,712,276,479 bytes였다.
  독립 관측1302회, 다른 GPU 소비자 겹침0, OOM0이다. 관측 상한과 정확한 순간 peak는 다르다.
- 각 완료 뒤 기존 accepted QUERY를 같은 선택/해시로 읽었다. 최초 CPU 뒤1회와 나머지5회
  모두 PASS다. 새 검색·문항·모델 실행을 생성해 대신 확인한 것이 아니다.
- 공식 ACCESS 갱신은 원 authenticated_at을 바꾸지 않았다. 비밀번호·토큰은 저장하지 않았다.
- 최종 게시 및 같은 결과 재조회/idempotent replay PASS. controller는34분1.700초 뒤
  success/status0으로 종료했고 GPU는2MiB 유휴 상태로 돌아왔다.
- 실험 동안 API/Web/QUERY/INDEX 원 invocation을 유지했다. 이후 별도 승인된
  Codex 계정 기능 릴리스는 이 실험과 결과 회수가 끝난 뒤 진행했다.

SANDBOX와 IMAGE_TRAINER_REGRESSION은 이 결과에 연결된 독립 증거가 없어 NOT_RUN이다.
과거 설치/보호 테스트나 이미지 검사를 이번 전환 PASS로 대체하지 않았다. 성능 기준도
실패했으므로 운영 GPU 기본값을 활성화하지 않았고 추가 GPU 모델 실행도 하지 않는다.
CPU 기본값을 유지하는 결정에 불필요한 새 이미지/학습 acceptance를 만들지 않는다.

## 정본과 실행 이력

- Job: `job_a930cfc8b08b4cf385c5cf95370cbcb4`, 최종 SUCCEEDED.
- 요청 SHA: `sha256:be62805b128f63a3e825fdf9eb42b98901dcca9686e61896ad60c2b276d7fc97`.
- 보존한 CPU1: `b3faa85824964cc590e6240728da053d`.
- 새 유효 실행 순서: CUDA2 `f1d7a4fc60f245c9b3a08155884a1d55`,
  CUDA3 `77409166751d4548b76f5eb7e4f7f4be`, CPU4 `2781b39246064340a96f907aba6f0b07`,
  CPU5 `128dfa6a56a94d6b95c07d27aa90f6da`, CUDA6 `655444bd1edf4d00a836bba72dd23730`.
- controller source `7d2ab1553b53a84667d88d51c42f6b436d862fc9`;
  numerical SDK `d381e6bc480606a828898ebe2e9942dd8a143677` 불변.
- Artifact `artifact_26e83e84441c4e9ab4c96e651d6f8c6a`,
  revision `rev_bdc1be6be9ac41538a1abdfef68bf286`, member `result.json`.
- member bytes SHA `sha256:e7edcc9338831136f63fdb2545d50ffe8bc3975ad93d03d69f1222b7667a455e`.
- result self-hash `sha256:c46ae8dc5ab461e6d6a6ba34b45885c72b0ad00a7bb951c3b157dc75c5b786ad`.
- numerical evidence self-hash
  `sha256:50156771c663e9d661a09534eb490f3fe0db9e03f076b7702e7ae9381566583b`.

[정본 결과 JSON](/mnt/nas/eom/artifacts/artifact_26e83e84441c4e9ab4c96e651d6f8c6a/rev_bdc1be6be9ac41538a1abdfef68bf286/result.json)은
실제 bytes SHA를 대조했다. binary·긴 로그·전체 출력은 Git에 복사하지 않았다.

기존 pre-ACK 실패2건 및 ACK 후 실패 `f8f2ef156d344e63bd430bc8dcaa5ba6`은 보존했다.
후자의 모델 진행량은 NOT_RECORDED이며 모델0회로 주장하지 않는다. 지원된 terminal
retirement와 같은 Job의 제한된 recovery를 사용했으며 과거 실패를 성공으로 바꾸지 않았다.
과거 실패까지 포함한 총 모델 호출 수를 유효 측정6회와 동일시하지 않는다.

## 구현 검증

GPU sampler 분리/공통 recovery source222 PASS, 추가 six-receipt journal1 PASS,
marker-guarded disposable PostgreSQL4 PASS/cleanup, strict mypy11 modules와 scoped
Ruff/format PASS 후 private wheel/RECORD와 실제 UID990/groups0 사전 검사를 통과했다.
0.5초 관측 주기·2초 gap 거부·기존 물리 lease/정리 규칙은 유지했다.

실패·수정·설치의 상세 경과는
[기존 실행 기록](../status/EMBEDDING_BENCHMARK_1200_LAUNCH_GAP_2026-10-23.md)에 보존한다.
