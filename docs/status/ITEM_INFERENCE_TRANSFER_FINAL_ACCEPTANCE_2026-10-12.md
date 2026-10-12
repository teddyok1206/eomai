# 문항 핵심 착상 전이 — 최종 운영 검증

상태 시각: 2026-10-12 12:03 UTC. 실제 두 쌍의 정본 결과와 replay, 최초 설계 대조와
샘플 정식 보관을 완료했다. 교육적 전이 효과나 과학적 정확성의
전면 승인을 뜻하지 않는다. 사람 평가는 사용자 지시에 따라 완료 조건에서 제외한다.

## 샘플 보관의 책임과 경계

사용자는 실제 검색된 문항 두 개를 한눈에 볼 수 있는 PNG를 요청했다. 기존 공식
Catalog/Orchestrator 조회에서 물리화한 고정 BGE request의 question-field text를 사용한다.
새 RAG 조회, 직접 원문 DB/NAS 검색, 새로운 문항 생성·GPU·임베딩·worker 실행은 없다.
원본 페이지 PNG는 이 staging에 없으므로 **텍스트 비교본**으로 표시하고 원문 그림을
만들어 넣거나 원본 시험지 캡처라고 표현하지 않는다. 원 question text/hash는 보존하며,
세 화학 수식의 LaTeX→Unicode 표시는 별도 명시적인 표시 규칙이다.

샘플은 기존 `control-file-set/1.0`의 `ControlFileSetPublisher`로 commit한다. 개발용
PNG/SVG와 plain-text provenance를 정렬된 typed manifest로 묶는다. 새로운 worker
메시지/JSON schema, DB schema, queue, runtime API는 만들지 않는다. 이 게시에는
기존 file-set bookkeeping Job 한 건이 생기지만 새 worker/model Workflow는 없다.

- 정본 입력: 고정 experiment execution/request와 selected profile/source/text hash.
- 출력 identity: 새 Artifact → immutable Artifact Revision → PNG/SVG/provenance member hash.
- 입력 해석: 존재·소유권·파일 identity·상한·hash·typed source closure를 재검증한다.
  local receipt는 새로운 조회 권한이 아니며, 추가 원문 픽셀을 읽지 않는다.
- 자료 구조: 두 개의 fixed-key source value와 ordered file-set; lookup과 조판은 입력에
  선형이다. 전체520개 forward/원 report 재처리는 없다.
- 트랜잭션·재전송: 기존 publisher의 lock/Job/Artifact commit과 고정 key를 재사용한다.
  unknown publication은 새 key로 우회하지 않는다. 실패 자료·원 실행은 수정하지 않는다.
- dependency: 표시 코드는 로컬 개발용 입력/렌더 경계이고 commit은 설치된 Orchestrator
  owner다. `rsvg-convert`와 Noto font를 재사용하며 production dependency를 추가하지 않는다.
- binary format labels: `eom://schemas/development/paired-item-text-png/1.0`은 PNG signature,
  고정1800px 폭·상한6000px 높이·텍스트 비교본/그림 미포함 표시를 검증한 개발용 media
  식별자다. 대응 SVG label은 `eom://schemas/development/paired-item-text-svg/1.0`이며,
  자체 생성한 escaped text만 포함하고 외부 resource/script를 사용하지 않는다.
  이 labels는 released Catalog/worker JSON Schema의 등록·활성화가 아니다.
- 더 단순한 `/tmp` 링크는 임시 시연에만 쓰며 최종 보관이 아니다. NAS에 직접 복사하는
  방법이나 기존 GPU/문항 이미지 schema로 위장하는 방법은 사용하지 않는다.

## 현재 실제 검증 결과

두 comparison successor는 `COMPLETED / MEMBER_VERIFIED`이며 원 key 두 건과 retry key
두 건 모두 동일한 Workflow/command를 반환한다. 원 FAILED Workflow 두 건은 보존한다.
두 machine judgement는 `INSUFFICIENT`다. 이는 실패나 `NO_TRANSFER`가 아니라
핵심 착상의 전이를 단정할 구조화된 근거가 부족하다는 결과다.

## 최초 설계 대조

| 원문 요구 | 구현 근거 | 실제 확인 / 한계 |
|---|---|---|
| 직접 조건·숨은 관계·결정적 추론·오개념 | `inference_transfer_projection.py`의 승인 report exact step/node/anchor refs | 고정520개 profile. decisive 후보 보유 profile425개/미보유95개; 부재를 임의 착상으로 채우지 않음 |
| 원 풀이보고서·정본 문항·metadata 활용 | `inference_transfer_item_projection.py`, Catalog snapshot/source owner | 정답/해설을 배제한 question text와 기존 구조/수식/승인 summary; 원문 픽셀은 관찰하지 않음 |
| 벡터는 보조 후보 검색 | 제거 가능한 local adapter와 세 view/common pool 실험 | BGE520/1560 MEASURED·COMMITTED,4query×3view; E5 INSUFFICIENT 보존. 품질/recall 증명 아님 |
| 조건·추론의 대응, 차이, 추가 추론 | comparison contract/preparation와 전용 Orchestrator/Runner | 실제 두 쌍 모두 MEMBER_VERIFIED. mappings/differences/new_reasoning 및 exact selected refs 확인 |
| 개념·소재·착상 독립 설명 | PairResult1.1, role1.30/V22의 세 축 | 쌍1 PARTIAL/PARTIAL/INSUFFICIENT, 쌍2 SAME/PARTIAL/INSUFFICIENT; 독립 설명 확인 |
| 닮은 소재와 전이 가능한 착상 구분 | released rubric과 양측 decisive 참조 요건 | 둘 다 판정 유보. 코사인859128/813578을 착상 일치 확률로 사용하지 않음 |
| 기존 RAG·권한·정본·재현성 유지 | 공식 source resolution/owner read/START와 failed-parent successor | 원 key2+retry key2 replay PASS, 원FAILED2 보존. DB grant/queue/schema migration 변경 없음 |
| 사람의 체감 전이 평가 | 기존 optional 계약만 보존 | 사용자 명시 지시로 NOT_EVALUATED/NOT_REQUIRED; 모델 판정을 사람 label로 저장하지 않음 |

원문 SHA는 `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a` 그대로다.
source/runtime/control의 정확한 identity·정본 hash는
[운영 검증 기록](../architecture/ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md)에 있다.
최신 source83파일/2,899 PASS, 실제 API privilege matrix의 disposable PostgreSQL26 PASS,
console49 PASS다. 각 독립 범위이며 이전 suite와 합산하지 않는다. strict mypy/Ruff/format,
설치 RECORD/의존성/isolation/API READY/기존8 service 복원은 PASS다.

## ‘핵심 착상 근거 부족’이 뜻하는 것

**같은 개념·비슷한 소재를 쓴다는 판단과, A를 푼 아이디어가 B의 어떤 판단을 줄여 주는지
설명할 수 있다는 판단은 다르다.** 이번 INSUFFICIENT는 후자를 뒷받침할 양측 근거가
부족하다는 판정 유보다. 문항에 착상이 없거나 전이가 불가능하다고 판정한 것이 아니며,
프로그램 실행 실패도 아니다. 조건·차이·추가 추론 설명은 정본 결과로 저장됐다.

현재 deterministic producer는 승인 보고서의 `INFERENCE_OPERATION` 역할 연결에서
DECISIVE_INFERENCE 후보를 얻는다. 그 후보에도 `inferred=True`와 한계를 붙인다.
일반 풀이 단계나 같은 법칙 이름만 보고 확정 착상을 만들어내지 않는다. 이번 실제 고정
profile에서는 쌍1 A 전체/선택 후보0, B2/2; 쌍2 A3/3, B0/0이었다. 선택 상한 때문에
존재하는 후보를 놓친 경우가 아니라 한쪽 비교 표현에 이 종류의 후보가 없던 경우다.
이는 기존 보고서의 모든 가능한 착상을 조사했다는 뜻이 아니라 현재 투영의 coverage다.

- 쌍1: 개념·자료의 일부 대응과 두 가지 차이를 설명했지만 A의 결정적 착상을 B의 추론에
  연결할 근거가 없었다. 공유 착상을 임의로 채우지 않고 shared_idea=null로 남겼다.
- 쌍2: 같은 개념이라고 판정했으나 B에 결정적 추론 후보가 없었다. A의 착상이 B의 정확히
  어느 판단에 도움이 되는지 특정하지 못했다. B에 추가되는 MgO의 결합 유형 판단도
  별도 기록했다. 이는 원문에 그 판단이 있다는 확인이지 과학적 정답을 새로 승인한 것이 아니다.
- 고정520개 중425개에는 후보가 있고95개에는 없다. **425개가 올바른 전이로 검증됐다는
  뜻은 아니다.** 두 쌍의 근거 부족을 전 corpus의 전이 불가능으로 확대하지 않는다.
- 첫 쌍의 질문 텍스트와 기존 intermediate claim에는 기호 대응 정합성 위험이 있었다.
  해당 배정은 이번 비교 모델에서 처음 생긴 것이 아니라 보존된 profile에 이미 있었다.
  원 페이지 픽셀을 검사하지 않았으므로 문항 텍스트/원 분석 중 어느 쪽 오류인지는
  확정하지 않았다. refs/hash의 일치는 그 과학적 진실성의 증명이 아니다.

더 강한 의미 판정이 필요하면 부족한 **비교 표현의 근거 연결**과 원문/분석 정합성을
검증·보강해야 한다. 기존 승인 report/원 Item을 덮거나 판단을 긍정으로 강제하지 않는다.
이 후속 품질 보강을 이번 기술 완료의 미실시 사람 평가와 혼동하지 않는다.

## 정식 PNG 샘플

- Artifact `artifact_2ba41bbeb1444153a590235791aa6be0`.
- Revision `rev_135b7907adee43d19006b97a77139824`.
- primary member `pair-2-text.png`,1800×1647px.
- raw PNG SHA `652662dc94639ad17f346aaad307559927a14a33f80b275aff36288eeb50e672`.
- manifest SHA `b8763fa6010c283b2db54e5aa6c6852043b051c2743038d05fcbbec47b85759f`.
- bookkeeping Job `job_64177e38047b440f906bc657f3f9d3c9`. 새 worker/model 실행0.
- final directory
  `/mnt/nas/eom/artifacts/artifact_2ba41bbeb1444153a590235791aa6be0/rev_135b7907adee43d19006b97a77139824`.

PNG/SVG/provenance를 Orchestrator publisher가 commit했고, 보관된 PNG·manifest raw SHA를
위 출력과 다시 대조했다. 표시용 sample은 새로운 정본 문항이나 원본 시험지 이미지가 아니다.

```text
TECHNICAL_GOAL=COMPLETE
ORIGINAL_DESIGN_SHA=UNCHANGED
INSTALLED_API_PLATFORM=8e36e6de7440f979c43423c28b84a145dab526fa
CORPUS_EXPERIMENT=MEASURED_COMMITTED_520_PROFILES_1560_TEXTS
BOUNDED_PAIR_RESULT=2_MEMBER_VERIFIED
ORIGINAL_KEY_REPLAY=2_PASS
RETRY_KEY_REPLAY=2_PASS
ORIGINAL_FAILED_HISTORY=PRESERVED_2
MACHINE_TRANSFER_JUDGEMENT=INSUFFICIENT_FOR_BOTH_OBSERVED_PAIRS
RETAINED_DECISIVE_CANDIDATE_COVERAGE=425_PRESENT_95_ABSENT
HUMAN_TRANSFER_REVIEW=NOT_EVALUATED_NOT_REQUIRED
EDUCATIONAL_ACCURACY_AND_TRANSFER_EFFECT=NOT_ESTABLISHED
PNG_PRESENTATION=COMMITTED_TEXT_ONLY_NOT_ORIGINAL_PAGE_PIXELS
```
