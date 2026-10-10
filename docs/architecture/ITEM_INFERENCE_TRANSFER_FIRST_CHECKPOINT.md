# 핵심 착상 전이: 첫 구현·로컬 시험 기록

2026-10-10 UTC. Source candidate 기록이며 운영 검색 활성화·교육적 품질 승인이 아니다.

## 보존·구현

- [설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)은 그대로 보존했다. 원문 파일 SHA-256: `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`.
- [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md)에 따라 기존 accepted base/V10 보고서/Graph/evidence 계약을 바꾸지 않고 additive profile·쌍 비교·사람 평가 계약을 추가했다.
- 정확한 report-local step/node/anchor 참조, source/Graph/solution/receipt pins, canonical hash, concrete condition·단위·부정 조건, 불확실성을 유지한다.
- 모델의 `STRUCTURAL_ANALOGY`와 사람의 `CRUX_TRANSFERS`는 서로 다른 기록이다. 일반 단계·소재·공식·동일 정답만으로 전이를 확정하지 않는다.
- Catalog opt-in 후보 입장은 실제 actor 권한과 pin된 policy/Graph를 사용한다. 기존 lexical 경로와 별도의 eligible pool을 입장시켜 다른 소재의 후보를 찾을 수 있게 하고, 반환 직전 재검증한다. 기존 V2 검색은 기본 동작을 유지한다.
- 로컬 모델 adapter는 CPU safetensors, exact model/files/runtime/recipe pins, 명시적 token overflow 거부, immutable model provenance와 eligible profile 집합 hash를 사용한다. fake backend는 TEST_ONLY다. API/core와 기존 이미지 환경은 변경하지 않았다.
- 쌍 비교 준비와 결과 검증은 정확한 A/B claim mapping을 요구한다. `workflow-role/1.29.0` support-only input/result binding을 기존 Orchestrator에 추가했다. 실행 전·commit 전·historical replay 때 재인가하며 exact-purpose resolved plan 없이는 거부한다. 단순 prompt 생성이나 callback 문자열이 실행 권한을 만들지 않는다.
- 긴 rationale/outcome은 complete field 단위로 손실 없이 나눴다. 4,000자 field/128 claim/32 refs 상한 때문에 표현할 수 없는 feature는 통째 UNAVAILABLE로 기록한다. 의미를 바꿀 수 있는 말미 절단은 하지 않는다. 별도로 E5 token overflow는 거부한다.
- top-K 밖의 source와 보고서 없는 source까지 전체 입장 population을 재인가한다. 회수된 자료의 count/hash도 반환하지 않는다. 사람 label·pointer의 `model_copy` hash 우회와 bool/float 예산을 차단했다.

## 실제 CPU toy probe

설명용 6개 synthetic 사례로 content-only와 구체적 추론 표현을 각각 비교했다. 실제 기출·사람 평가 자료가 아니며, 학습이나 모델 fine-tuning을 수행하지 않았다.

| 항목 | 관측 |
|---|---|
| 모델 | `intfloat/multilingual-e5-small` |
| upstream revision | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| model manifest | `sha256:f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb` |
| recipe | CPU float32, 384차원, masked mean + L2, 양쪽 `query: ` |
| 모델 파일 | 7개, 492,794,846 bytes; 전부 upstream expected size/SHA와 실제 bytes 재검증 |
| Python | 독립된 explicit Conda Python 3.12.13; 기존 이미지 Python 3.11 환경 재사용 안 함 |
| runtime | torch `2.7.1+cpu`, transformers `4.56.2`, safetensors `0.6.2`, tokenizers `0.22.2` |
| CPU thread | 4 |
| 모델 입장·로드 | 1,854 ms (해시 검증 포함) |
| 6문장 encoding | content-only 52 ms; concrete-inference 62 ms |
| 반복 최대 차이 | 두 view 모두 0 (동일 입력·runtime의 이번 반복에서만 관측) |
| peak RSS | Linux 791,560 KiB |
| 512-token overflow | 실제 초과 입력을 추론 전에 거부 |
| 실제 기출/교육 평가 | NOT_PERFORMED / NOT_EVALUATED |
| 운영 활성화 | NOT_PERFORMED |

중요한 관측: query는 병렬 용수철이었다. 두 view 모두 같은 소재의 **직렬 용수철**을 구조적 대응 예인 **병렬 저항**보다 높게 매겼다.

| 후보 | content-only cosine (millionths) | concrete-inference cosine (millionths) |
|---|---:|---:|
| 직렬 용수철 | 980885 | 981209 |
| 숫자·이름 변경 병렬 용수철 | 975149 | 978719 |
| 병렬 저항 | 883855 | 913608 |

이는 작고 손으로 쓴 toy set의 관측이다. 실제 corpus의 recall, 모델 일반 성능, 학생의 체감 전이를 증명하지 않는다. 다만 **벡터 점수만으로 착상 전이를 판정하면 안 된다는 설계 이유**를 뒷받침한다. cosine 절대값을 승인 임계값으로 쓰지 않는다.

따라서 후보 discovery는 넓게 유지하되, 가까운 pair에서 무엇이 같고 무엇을 합치는지·전제가 무엇인지·새 추론이 필요한지를 구조적으로 확인하는 다음 단계가 필요하다. 모델을 큰 것으로 바꾸거나 수치 임계값을 튜닝해 이 문제를 해결했다고 선언하지 않는다.

## 실행 이력·자료 위치

개발용 staged model store: `/tmp/eom-inference-transfer-model.6DLzgT`. 실험 환경: `/tmp/eom-inference-transfer-runtime.T3lA5o/env`. 운영 설치나 canonical NAS Artifact가 아니다. 모델 bytes를 Git에 넣지 않았다.

성공한 이번 probe의 local 결과: `/tmp/eom-inference-transfer-model.6DLzgT/cpu-toy-probe.json`; result self-hash `sha256:1db1f31f7563011920a2f1372f2eed72d6235a55f780410de35a8cbb1ebf8e5d`.

그 전 실행은 추론·overflow 검사 후 **결과 직렬화에서 실패**했다. EOM canonical messages는 float를 허용하지 않는데 측정값을 float로 기록한 것이 원인이었다. 정수 milliseconds/millionths/billionths로 수정하고 동일 입력·모델로 재실행했다. 실패를 성공 receipt로 바꾸지 않았다. 두 실행 합계 8 encoding commands/48 texts, 2 overflow checks다. 이 횟수는 모델 생성·GPU·HWPX 실행 횟수와 혼합하지 않는다.

이번 실험은 developer process의 offline flags/local-files-only 모드다. systemd의 PrivateNetwork·권한 격리 acceptance를 수행했다는 뜻이 아니다. production runtime 준비 시 별도의 동일 boundary 검증이 필요하다.

## 검증 및 남은 gate

- 첫 묶음: 계약·prompt 준비·사람 metric·schema resource·기존 V10/retrieval 회귀 **103 PASS**. formatter/Ruff/관련 strict mypy PASS. 이후 통합/worker binding 변경은 별도 최종 검사 대상이다.
- 기존 schema resource test의 고정 숫자 281은 착수 HEAD의 실제 284와 이미 달랐다. 새 schema 하나를 추가했다. 고정 숫자 대신 실제 schema resource 파일 집합과 registry 집합의 정확한 대응을 검사하도록 바꿨으며, 기존 canonical bytes/hash checks는 유지했다.
- 실제 disposable PostgreSQL `/tmp/eom-api-testdb-20261010090657_7a7a9999`에서 기존 chat knowledge suite와 신규 candidate SQL 2개를 합쳐 **25 PASS**. migration upgrade/downgrade/upgrade cycle `20261009_0050` PASS, 지원된 cleanup으로 해당 DB·전용 역할·임시 credential state를 제거했다. 운영 DB는 변경하지 않았다. 신규 SQL 2개는 pg_temp fixtures와 mocked source resolution을 사용하므로 실제 NAS source chain/production 권한 acceptance로 과장하지 않는다.
- 운영 설치 API wheel의 29 predecessor role bundle hash와 source candidate의 동일 버전을 대조하여 **mismatch 0**을 확인했다. predecessor hash-set SHA: `sha256:9ef59f0a5a690f886d45cd51be59debe69b53b410fc86818a94a3193b6c49c5d`. 새 `workflow-role/1.29.0`만 추가됐고 기존 canonical role/knowledge schema bytes와 Pack은 변경하지 않았다.
- 첫 root 통합 **291 PASS**, 별도 workflow/package/기존 API 경계 **164 PASS**. 이후 최종 새 묶음은 **457 PASS**(39.42s). 최초 최종 묶음 중 설치 테스트용 subprocess import fixture가 수정 전 상태로 이미 collection돼 NameError가 발생했다(456 PASS/1 fixture failure). fixture 수정 뒤 fresh process로 전체 gate를 재실행하여 457 PASS를 확인했다. 이를 production failure나 새 worker 실행으로 집계하지 않는다.
- 최종 Ruff/lint·formatter·관련 **17 production source files strict mypy PASS**, diff check와 `testdb_run.sh` shell syntax PASS. Wheel packaging과 임시 non-editable install에서 신규 support schema/비교 application/prompt preparer를 source checkout 없이 로드했고, torch/transformers가 core import에 유입되지 않았다. 이 package 검증은 운영 배포·서비스 identity isolation 검증이 아니다.
- 실제 기출 520개 profile의 token overflow 비율, source-resolution query/file read 비용은 미측정이다. 전체 report를 512 tokens에서 잘라 넣는 우회는 하지 않는다. chunk/facet 정책 변경이 필요하면 새로운 projection/recipe revision으로 설계한다.
- 실제 eligible corpus에서 lexical/content-only/crux/metadata ablation 및 bounded pair Codex 실행은 아직 남아 있다. Orchestrator/preset/runtime activation 없이 worker를 직접 실행하지 않는다.
- human scorecard와 육안 확인은 모아서 요청한다. 지금 `HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`이며 전체 goal은 진행 중이다.

## 상태 구분

- F0–F4: 원문·goal·source 구현 및 기술 검증 checkpoint. 실제 worker pair execution은 아직 하지 않았다.
- F5: 실제 authorized corpus 측정·ablation·사람 평가 대기.
- F6: compatible runtime release, 보호된 모델 설치/격리 및 opt-in 운영 활성화 대기.
- 기존 검색/출제/검토/승인/Graph grounding은 대체하지 않았으며 서비스 restart·runtime policy activation은 수행하지 않았다.
- 코드와 문서만 Git에 둔다. 임시 모델·벡터·긴 결과를 Git에 넣지 않는다. 실험용 `/tmp` model/env는 canonical NAS 등록이나 운영 모델 설치가 아니다.
