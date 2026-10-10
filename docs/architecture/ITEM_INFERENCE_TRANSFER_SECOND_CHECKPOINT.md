# 핵심 착상 전이: 모집단·전용 실행·3-view 실험 checkpoint

2026-10-10 UTC. Source 구현 및 개발용 기술 검증 기록이다.
운영 활성화, 실제 기출 검색 품질, 사람의 풀이 전이 평가 완료를 뜻하지 않는다.

## 보존한 원문과 이번 책임 경계

[원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)의 파일 SHA는
`f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`로 유지한다.
[첫 checkpoint](ITEM_INFERENCE_TRANSFER_FIRST_CHECKPOINT.md)의 과거 증거는 변경하지 않는다.

- [모집단·쌍 재인가](ITEM_INFERENCE_TRANSFER_CORPUS_SCOPE.md): 기본 검색 범위는 그대로다.
  원래 기출만의 opt-in 범위는 exact Graph/run/Item/revision의 occurrence membership을
  LIMIT 전에 확인한다. 520을 코드에 고정하거나 canary를 억지로 포함하지 않는다.
  쌍 비교 재인가는 실제 actor/policy와 정확히 두 accepted 보고서에서 profile을 다시 만들어
  전체 immutable 값을 대조한다. 아직 accepted profile producer가 없는 `CODEX_DERIVED`는 거부한다.
- [전용 실행 목적](ITEM_INFERENCE_TRANSFER_EXECUTION_PURPOSE.md): V21 plan과
  `INFERENCE_TRANSFER` stage를 추가했다. authoring Pack이나 기존 support/PDF 목적을
  비교 작업으로 재해석하지 않는다. 전용 wrapper/resolver/materializer/bootstrap은 별도 후속 경계다.
- [worker binding](ITEM_INFERENCE_TRANSFER_WORKER_BINDING.md): step/job CAS callback과
  source 재인가 callback을 분리했다. 새 작업·replay·실행 직전·commit 직전에 재인가한다.
  생성 뒤 권한 철회도 기존 job failure 경계에서 기록하고 QUEUED job을 방치하지 않는다.
  실제 UTF-8 prompt SHA와 core prompt SHA를 분리하고, terminal replay에도 plan 문서와
  저장된 identity/hash/preset/capacity/Graph/resolver/UTC 시각의 일치를 요구한다.
- [실험 계약](ITEM_INFERENCE_TRANSFER_EXPERIMENT.md): 본문·exact 풀이 claims·metadata를
  같은 encodable 후보 집합에서 비교한다. 실제 prefix/special tokens 포함 길이를 측정하며
  초과 문구를 자르지 않는다. view별 한 번 인코딩한 matrix로 여러 query를 비교한다.
  공급된 기존 Graph baseline은 보존하되 공통 후보 집합에서의 품질 비교가 완료됐다고 주장하지 않는다.

## 실제 disposable PostgreSQL

기존 guarded runner로 `/tmp/eom-api-testdb-20261010093144_e8ee41ca`를 사용했다.

- migration `20261010_0051`의 실제 upgrade → downgrade → upgrade PASS.
- model-free chat knowledge/query-plan 및 새 occurrence/단계 검증 **38 PASS** (8.43s).
- 새 scope 사례 13개는 중복 placement, canary, 같은 logical Item의 다른 historical revision,
  pre-limit indexed filtering과 exact 두 run admission을 포함한다.
- 단계 검증 2개는 실제 CHECK의 새 stage 허용/미지원 stage 거부를 확인한다. 새 stage row가
  남아 있는 downgrade는 PostgreSQL이 거부하며 rollback 뒤 row/constraint/head를 보존한다.
- 지원된 cleanup으로 해당 DB·전용 역할·임시 credential state를 제거했다.

이 DB는 테스트용이다. 운영 DB/migration/서비스는 변경하지 않았다. source-resolution fixtures와
mocked owner reads를 실제 NAS source chain 또는 실제 사용자 권한 acceptance로 확대하지 않는다.

## 실제 pinned CPU CLI smoke

기존 개발용 `multilingual-e5-small` 모델과 독립 Python 3.12 CPU 환경을 재사용했다.
새 다운로드, GPU 학습, Codex worker 호출 또는 기출 재처리는 하지 않았다.

| 항목 | 이번 관측 |
| --- | --- |
| 입력 | `TEST_ONLY_SYNTHETIC`, 9 profiles, 3 queries |
| 모델 | `PINNED_MODEL`, 기존 exact model manifest |
| 모델 manifest SHA | `sha256:f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb` |
| 실험 request SHA | `sha256:42cd3457ec36f81a716a384c476a52ec654b60360dcc2170d0a9cc96e9716999` |
| 실험 result SHA | `sha256:970ad1fe0244b296f59c208cdae05e03d8af4c4dd822dd0ffee7b2f808f04bd8` |
| 공통 집합 | 9 profiles, 27 encodable view rows |
| encoding | 3 logical encode requests, 27 texts; query마다 재인코딩하지 않음 |
| 모델 검증·로드 | 2,548 ms |
| 실제 token 길이 검사 | 4 ms |
| encoding 합계 | 150 ms |
| Linux process peak RSS | 795,408 KiB; view별 독립 메모리나 운영 상한이 아님 |
| 기존 Graph baseline | NOT_MATERIALIZED |
| 현재 인가 / 사람 평가 / 운영 활성화 | NOT_VERIFIED_BY_HARNESS / NOT_EVALUATED / NOT_PERFORMED |

실제 CLI를 실행하는 opt-in integration test **1 PASS** (5.46s).
결과는 개발 임시 workspace
`/tmp/eom-inference-transfer-f5-cpu.tmug2P/pytest-retry/test_pinned_cpu_model_runs_thr0/result.json`에 있다.
이는 canonical NAS Artifact나 인가 영수증이 아니다. 합성 입력에는 실제 문항 품질 label이 없다.

앞선 test invocation은 query pointer의 기본 `schema_ref`를 포함하지 않아 canonical request
hash 검증에서 실패했다. typed pointer serialization으로 fixture를 수정했다. 그 실패는
request 구성 단계에서 발생하여 model/CLI forward는 실행하지 않았다. 성공한 이번 실행만
27 texts/3 encode requests로 집계한다.

## 추가 회귀와 남은 gate

- replay plan-row binding 포함 focused worker/authority regression **43 PASS**.
- installed-wheel 및 dependency 검증 **24 PASS**. 뒤에 resource load assertions를 보강했으므로
  최종 합동 gate에서 fresh installed simulation을 다시 실행한다.
- 초기 합동 source suite는 **410 PASS / 1 test-path failure**였다. 동시에 정리된 pure text helper의
  옛 service 경로를 dependency test가 읽던 것이 원인이었다. 실제 contract 소유 경로로 수정했다.
  운영 failure로 분류하지 않으며 최종 fresh 합동 검증 결과를 별도로 기록한다.
- 수정·보강 뒤 fresh 합동 source/regression/package 묶음은 **484 PASS** (23.18s).
  신규 schema의 실제 installed resource load, legacy 29 role bundle hash 불변, 기존 V10/retrieval와
  재실행 경계를 포함한다. 관련 production source **20개 strict mypy PASS**, Ruff lint PASS,
  검사 대상 Python **49개 formatter PASS**, diff 및 release/test-runner shell syntax PASS.
  이 installed simulation은 테스트한 source 기능의 package 검증이지 compatible 운영 release 증거가 아니다.
- 실제 corpus source 준비는 [인증된 snapshot 설계](ITEM_INFERENCE_TRANSFER_AUTHORIZED_SNAPSHOT.md)를
  따른다. 현재 설치된 chat의 3개 문항·요약 문맥은 전체 기출 export와 동일하지 않다.
- [전용 Workflow admission](ITEM_INFERENCE_TRANSFER_WORKFLOW_ADMISSION.md)은 후속 source 단계다.
  다른 목적의 request를 비교 definition에 넣지 못하게 하며, actor별 active dedup을 분리한다.
- 실제 기출 token overflow 분포, 공식 Graph 대비 ablation, bounded Codex pair, 사람의 전이 위치
  평가는 아직 수행하지 않았다. callback 존재나 manifest의 인가 문자열로 이 gate를 대체하지 않는다.

Goal은 계속 진행 중이다. 승인된 Item/보고서·기존 GraphRAG·출제/검토/승인/출판 이력은 보존한다.
