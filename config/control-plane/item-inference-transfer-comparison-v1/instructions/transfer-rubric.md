# 문항 A의 핵심 착상은 문항 B에 어떻게 전이되는가

방향은 A_TO_B다. 소재나 표현이 비슷한지보다, A를 푼 사람이 B에서 재사용할 수 있는
구체적인 조건 해석과 결정적 추론이 있는지를 비교한다. 제공된 selected claim과 각
profile의 limitations만 근거로 삼는다. 비공개 사고 과정 대신 검증 가능한 짧은 근거를
쓴다.

## 대응 확인

1. GIVEN_CONDITION: 어떤 값·조건이 실제 추론을 제한하는가. 단위·차원·변환, 부정 조건,
   성립 범위, 보존의 계와 전제가 서로 일치하는지 확인한다.
2. INTERMEDIATE_RELATION: 주어진 정보를 결합해 얻는 중간 관계가 어떻게 대응되는가.
3. DECISIVE_INFERENCE: 답을 결정하는 숨은 관계나 구별 기준이 무엇이며, A에서 배운
   착상이 B의 정확히 어느 판단을 줄여 주는가.
4. ASKED_JUDGEMENT: 같은 관계를 써도 묻는 대상이나 참·거짓의 방향이 달라지는가.
5. MISCONCEPTION: 같은 오개념을 드러내는지, 아니면 표면상 비슷하지만 다른 실수를
   요구하는지 확인한다.

단순히 같은 공식·정답·그림 소재이거나 '자료 해석 → 관계 도출 → ㄱㄴㄷ 판단'처럼
일반적인 단계가 같다는 이유로 착상 전이를 인정하지 않는다. 각 mapping은 같은 facet의
양쪽 selected claim ID와 그 대응 이유를 가진다. 없는 claim을 만들어내지 않는다.

## 판정과 반증

- INSUFFICIENT: 조건·추론이 부족하거나 unresolved/inferred 관측 때문에 전이를 판단할
  수 없다. limitations에 부족한 근거를 명시한다.
- NO_TRANSFER: 제공된 근거에서는 결정적인 착상의 재사용을 찾지 못했다. 단순 소재
  공통점과 전이 부재를 구별한다.
- STRUCTURAL_ANALOGY: 양쪽 GIVEN_CONDITION과 DECISIVE_INFERENCE의 구체적 대응이 있으며
  shared_idea로 재사용할 착상을 설명할 수 있다. 이는 검증이 필요한 구조 대응 가설이다.
- NEAR_IDENTICAL_CANDIDATE: 구조뿐 아니라 조건·질문도 거의 같고 숫자·이름 변경에
  가까운 후보다. 유용한 전이와 구별하며 표절 판정으로 표현하지 않는다.

differences와 new_reasoning을 별도로 기록한다. B에만 추가되는 전제·예외·추론이 A의
착상을 무효화하는지도 검토한다. 빈 배열은 허용되지만, 중요한 차이가 없다고 추측하지
않는다. 차이마다 한쪽 이상 실제 selected claim을 연결한다.

## 출력 규칙

request/profile/rubric pins와 direction은 입력과 정확히 같아야 한다. mappings의 claim
ID는 해당 방향과 facet을 지킨다. STRUCTURAL_ANALOGY/NEAR_IDENTICAL_CANDIDATE에는
GIVEN_CONDITION·DECISIVE_INFERENCE 대응과 shared_idea가 필요하다. 입력에서 판정에 영향을
주는 한계는 limitations에 유지한다. 모든 결과는
assessment_kind=MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION으로 제출한다.
