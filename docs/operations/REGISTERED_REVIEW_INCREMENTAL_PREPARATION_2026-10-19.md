# 생성 문항 검토 근거의 증분 입력 준비 — 2026-10-19

## 범위와 판정

사용자 승인에 따라 정상 CPU INDEX/QUERY를 유지하고, 실패한 전체 GPU 검증을 반복하는
대신 생성 문항의 기존 풀이·검토 기록을 재사용하는 경계를 먼저 구현했다.
설계는 [생성 문항 검토 근거 설계](../architecture/REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md)를 따른다.

이 기록은 **첫 source 수직 경로**의 증거다. 운영 증분 연결이나 상위 목표 전체의 완료
기록이 아니다. 실제 운영 API/QUERY/INDEX의 설치·선택은 이번 작업에서 변경하지 않았다.
새 로그인, 모델 추론·학습, GPU 수치 실행, 문항 생성, 운영 DB 쓰기는 모두 0회다.

## 구현한 것

- `registered-item-review-solution-evidence/1.0`: APPROVED_ITEM의 등록 manifest,
  정본 콘텐츠, 최종 authoring/review occurrence, trusted receipt pair와 exact SHA를
  고정하는 별도 pointer 계약이다. accepted 기출 V10을 위조하거나 확장하지 않는다.
- `item-inference-transfer-profile/2.0`: 원 검토의 독립 답 도출 결론·선지·진술 판정을
  원 report/draft 위치와 함께 보존한다. 없는 풀이 DAG·Graph anchor·decisive facet은
  만들지 않는다. claim key는 audit에 보존하지만 임베딩 text와 순서에서는 제외한다.
- 단일 source Catalog resolver: 필수 source authorization callback을 읽기 전/후
  호출하고, 현재 승인 상태·등록 manifest·정본·성공 final step/Job·raw role 결과·
  실제 기존 public receipt owner를 대조한다. bulk INDEX의 source별 loop로 연결하지 않았다.
- 정본 materialization: WorkflowCatalog와 resolver가 같은 공개 순수 함수를 사용한다.
  원 draft와 등록 JSON의 발문/수식 정규화를 서로 다르게 재구현하지 않는다.
- 기존 순수 delta planner: legacy profile1과 명시적 registered-review 입력을 구분해서
  수치 입력을 결정한다. 같은 text/space/partition은 재계산하지 않고, Graph만 바뀌면
  vector를 재사용하되 새 profile association을 유지한다. 원문·metadata가 없는 view는
  빈 벡터나 placeholder로 채우지 않는다.
- 기존 source-plan1/index1 owner는 profile2를 명시적으로 거부한다. 순수 planner의
  확장이 released wire나 운영 활성화를 조용히 넓히지 않는다.
- 단일 source 해석 결과는 원 authoring/review typed 값을 같은 검증 root에서 넘긴다.
  실제 임시 파일 해석 후 Artifact/DB 재읽기를 금지한 상태에서도 profile→수치 입력→
  같은 row 재사용까지 통과한다. report를 다시 가져오는 중복 materialization은 없다.

## 최종 소스 검증 — 2026-10-19 11:36 UTC

| 경계 | 실제 결과 |
|---|---|
| 신규 계약/등록 해석/profile/delta/정본 + 기존 관련 회귀 15개 suite | **524 PASS**, 15.92초 |
| 변경 Python 21개 Ruff/format | PASS |
| 주요 production 모듈 12개 strict mypy | PASS |
| 독립 검토 | 위조 frozen model 추가 필드 소실과 typed manifest 해시 결함을 발견·수정 후 PASS |
| source wheel | offline `pip wheel --no-deps --no-build-isolation --no-index` PASS |
| wheel RECORD/최종 source member 비교 | **1,792개 해시/길이 PASS** |
| `python -I` wheel-only module/resource import | PASS; 운영 설치는 아님 |

source regression XML:
`/tmp/eom-registered-review-source-regression-20261019-final.xml`.
별도 source wheel:
`/tmp/eom-registered-review-wheel.CZlNHCha/eom_platform-0.1.0-py3-none-any.whl`,
SHA-256 `78895b2e90dfc7863d470f8f1d451053b18b57bb4a54e3d7c99692583d86938d`.
초기 `python -m build`는 현재 환경에 CLI module이 없어 실행되지 않았고, dependency를
추가하지 않고 위 offline pip 경로로 검증했다. source wheel은 **미설치·미활성화**다.

## 실제 producer로 재현한 호환성 결함

독립 재검토에서 role Artifact manifest의 해시 규칙 차이를 발견했다.
Orchestrator의 `stage_structured_artifact`는 typed `ArtifactManifest`를 canonical
serialize해서 해시하지만 DB에는 JSON-mode metadata가 저장된다. microsecond=0이면
원 해시 표현의 `.000000Z`와 DB projection의 `Z`가 달라질 수 있다.

새 resolver와 기존 `OrchestratorEvidenceUsageReceiptResolver` 모두 원 producer의
typed-manifest 해시만 검증하도록 수정했다. 두 가지 해시를 임의 허용하거나 해시 검사를
생략하지 않는다. 기존 합성 fixture도 실제 producer 표현으로 고쳤다.

- RED: `/tmp/registered-review-producer-red.xml` — actual producer 경로의 기존 거부 재현.
- GREEN: `/tmp/registered-review-producer-green.xml` — 실제 임시 role 파일과 기존 public
  receipt resolver를 통과하는 @11/@12 × zero/nonzero-microsecond 검증.

이 파일 테스트는 실제 저장 함수를 사용하는 **합성 단위 검증**이지, 운영 Item이나
PostgreSQL persistence 검증이 아니다. 파일 payload와 긴 로그는 Git에 넣지 않는다.

## 아직 연결하지 않은 경계

1. population용 bounded metadata/receipt batch API. 새 단일 source resolver를 1,024번
   호출하는 N+1 구현으로 INDEX에 붙이지 않는다.
2. 생성 Item이 실제 현재 access policy와 Graph source 출판 경계를 통과하는지 확인.
   기존 V2 분석 지원이 최신 Workflow family의 자동 Graph 출판까지 증명하지는 않는다.
3. source-plan/profile/binding/index/registration/query의 실제 hardpin successor 연결.
   legacy520개 shard/encoding은 재사용하고 old schema bytes·history는 보존한다.
4. DB evidence-kind 관계·CHECK successor·disposable DB·compatible installed INDEX/QUERY와
   새로운 immutable owner identity. 현재 NOT NULL인 solution-analysis FK에 review step을
   위조해서 넣지 않는다. branch별 FK/CHECK/uniqueness가 필요하며 아직 구현하지 않았다.
   기존 INDEX18 identity를 다른 코드로 덮지 않는다.
5. 실제 승인된 새 source delta·같은-key replay·검색·권한 철회와 복구의 운영 증거.

기존 public role JSON reader의 path-hash/read는 이번 source slice에서 재사용했다.
이로써 새로운 file-descriptor identity 검증을 달성했다고 주장하지 않는다. immutable
Artifact owner를 유지하며, 후속 bulk adapter에서 reader 강화가 필요하면 기존 public
owner를 개선하고 별도 경합/교체 negative로 검증한다. 병렬 reader를 만들지 않는다.

## GPU 상태

이번 작업에는 전체 finite/GPU 절차 재실행이 없다. 앞선 준비 오류의 정확한 원인은 아직
미확정이며 원래 여섯 CPU/CUDA 수치 측정은 NOT_STARTED다. CPU 유지가 GPU 성능 열세를
입증하는 것은 아니다. 준비 진단과 수치 비교는 원래 gate를 보존한 별도 후속 작업이다.
