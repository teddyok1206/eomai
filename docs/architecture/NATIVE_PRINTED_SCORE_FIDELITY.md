# Native 자료의 원본 배점 보존

2026-11-15 UTC. 김병훈450문항 목표를 축소하지 않는 실제 입력 호환 보완이다.

## 확인한 사실과 중단 범위

450개의 분리된 원문 HWPX에는 모두 정확히 하나의 `[배점점]` 표시가 있다.
1.5점144개·2.5점146개·2점160개다.16회·18회의 인쇄 배점 합계는50.5점이며 임의로50점으로
보정하지 않는다. 본문·원 해설·그림·Excel 원문·고유번호는 별도 정본이다.

첫 회차의 공식 Native bundle question pointer와 등록 content를 실제 Artifact owner로 읽어
25개를 비교했다.16개가 불일치했다.1.5가15로, 또는 소수 배점이0/2로 저장된 사례가 있다.
기존 '25개 완료'는 기술 상태였으며 배점 충실도 PASS가 아니었다.
`staging/native-registered-score-audit-20261115.json`이 읽기 전용 증거다.

3회차1번은 같은 정수 전용 계약에 대해 proposal을 거부해 `UNSUPPORTED_STRUCTURE`를
기록했다. 파일을 못 읽은 것이 아니다.2번의 공개 풀이 실패는 별개인 앞으로 향한
solution-step dependency이며 그 검증을 완화하지 않는다.

Material owner에는 지원된 main-only SIGINT drain을 요청했다. 기존 작업/실패/원문을
지우지 않았고 INDEX/QUERY는 교체·중단하지 않았다. goal은 계속 active다.

## 소유자와 최소 설계

1. 책임: HWPX 형식 계층은 이미 선택된 문항 XML에서 배점 표시만 읽는다. Catalog가 exact
   Native question pointer·actor 권한·schema/media/hash/lifecycle를 해석하고, 학습 입력 준비와
   등록 직전 같은 원본 배점을 대조한다. worker가 권한이나 기대값을 정하지 않는다.
2. 정본은 approved Native bundle의 문항별 HWPX다. 모델 proposal이나 Excel의 편성용 배점이
   원문 인쇄 배점을 대체하지 않는다. Excel 원문/추후 고유번호 갱신은 그대로 보존한다.
3. parser 결과는 작은 frozen value다. 별도 logical ID/DB/registry/queue/cache를 만들지 않는다.
   문항·revision·Artifact identity와 hash는 기존 포인터를 유지한다.
4. parser는 UTF-8 bounded section XML의 실제 paragraph text만 읽는다. DTD/entity/NUL·과도한
   depth/size를 거부한다. 여러 표시를 하나로 추측하거나 참고 그림/타 문항의 배점을 고르지 않는다.
   MATCHED/ABSENT/AMBIGUOUS를 구분하고 값은 Decimal로 비교하며 float 반올림/배율 변환은 없다.
   `material_native_score.py`는 이미 original/split lineage를 확인한 question descriptor만
   연다. 문서32MiB·ZIP member2048·section32·section별16MiB·XML합계32MiB로 제한하며,
   중복 member·암호화·지원하지 않는 압축을 거부하고 FD를 항상 닫는다. hash/lifecycle와
   권한은 기존 Artifact owner 및 전후 authorize에서 확인한다. 정기 상태 조회는 원문을 읽지 않는다.
5. 새 `source-score/2.0`은 기존 정수/미인쇄 의미를 보존하면서 정확한 반점 문자열을 추가한다.
   실제290개에 필요한 `1.5`/`2.5`는 문자열로 전달해 binary-float·15점 대체를 막는다.
   기존 Preview4가 이미 지원하는 integer/positive half-point 표시 범위만 이번에 약속한다.
   0.5/0.25 같은 미지원 표시를 정수로 바꾸지 않으며 별도 successor가 필요함을 기록한다.
6. `creative-source-item-draft/2.0`과 Native extraction/result successor가 새 score를 사용한다.
   기존 V1 draft/result·ROLE1.37/1.39·Workflow1/2·released Pack bytes는 바꾸지 않는다.
   새 wire/schema와 Pydantic을 먼저 정의하고 실제 필요한 새 ROLE/definition/Pack만 묶어 활성화한다.
   번호는 현재 등록된 family와 대조해 확정하며 임의 latest 재선택을 하지 않는다.
7. canonical block content의 successor `1.1`은 기존 body/interaction/solution 배치를 그대로
   쓰고 소수 배점만 정확한 문자열로 보존한다. 정수/미인쇄 입력의 기존 canonical1.0 경로는
   유지한다. content-team2/3로 억지 재배치하지 않는다. `BLOCKS_V1`은 같은 block-layout
   renderer를 뜻하며 source schema URI/version은1.0/1.1로 정확히 구분한다. Preview4의
   score_display는 이미1.5/2.5를 허용하므로 wire 의미/화면 구조를 바꿀 이유가 없다.
8. Catalog canonical reader·approved Item knowledge source·Preview·공통 풀이/임베딩 projection을
   같은1.1 pointer로 연결한다. imported Native 합본은 기존 원문 HWPX를 그대로 사용한다.
   지원하지 않는 template 재출력을 가능하다고 표시하지 않으며 별도 renderer를 만들지 않는다.
9. dominant operation은 문항 pointer별 bounded XML 선형 읽기와 task/Item PK lookup이다.
   parser O(XML bytes), space O(bounded text/depth/candidates); 기존 set/map·indexed joins를
   사용한다. 새 index/DB migration은 현재 필요가 입증되지 않았다.
10. 새 기대값은 검증한 Native question pointer와 기존 request/plan/receipt hash에 묶는다.
    등록 전 원본 배점과 proposal/canonical을 비교한다. 불일치는 stable source-score 오류로
    거절하고 원본이 '안 읽힘'으로 오인하지 않는다. model output을 제자리 고치지 않는다.
11. 복구는 기존 terminal/lease/retry 경계를 사용한다. source-score 때문에 proposal이 없는
    예외는 exact source·기술 원인·새 계약 지원을 증명한 후 새 linked task에서 다시 추출한다.
    이미 등록된 배점 오류는 원본 근거의 reviewed successor Item Revision·정확한 lineage로
    수정한다. 기존 task/accepted result/Graph/벡터를 성공으로 재해석하거나 덮어쓰지 않는다.
    기존 image correction에서 재사용 가능한 owner/transaction을 우선하고 새 수정 framework는 만들지 않는다.
12. 더 단순해 보이는 대안인 old schema의 integer→number 변경,0/15/반올림 저장,정상 자료를
    UNPRINTED라 부르기, metadata만 고쳐 canonical 오류를 숨기기는 원본 의미/immutable
    계약을 깨므로 사용하지 않는다. 공통 Graph·INDEX 숫자 recipe를 이 문제 때문에 바꾸지 않는다.

## 구현 후보와 활성 경계

score2·draft2·extraction2·block content1.1의 schema/Pydantic과 순수 compiler/reader를
추가했다. shared region/reference/answer 검증은 두 실제 형식이 같은 기반을 사용하며
archive/result1은 새 draft를 수용하지 않는다. block1.1의 Preview는 exact source URI와
schema_version을 확인하고 template 재생성 가능 여부는 false다. 실제 원문 전달/합본은 별개다.
같은 문항에서 배점만 바뀌어도 question embedding text/hash는 동일하다는 회귀를 추가했다.

이 단계는 아직 source 후보다. ROLE/request/result·실행 plan과 등록/HTTP 응답의 닫힌
계약에는 이전 형식만 허용된 곳이 있으므로, 값 모델을 추가한 것만으로 운영 지원을
선언하거나 Material owner를 다시 켜지 않는다. 해당 소비 경계의 필요한 successor를
호환 묶음으로 연결하고 기존 등록의 reviewed correction까지 검증해야 한다.

## 구현·검증 순서

- 원본290개/기존 등록16개 불일치를 보존하고 새 등록을 안전하게 drain한다.
- pure bounded parser, 새 score schema/value, source/canonical successor와 단위 검사.
- 기존 worker/등록 owner에 연결하고 원본 배점 대조를 강제한다. 원문/그림/해설은 바꾸지 않는다.
- 역사적 schema replay·Native2/3·정수/미인쇄·반점·위조/모호 XML·pointer/권한/hash 검증.
- disposable DB에서 linked correction/retry·동시 생성·중단/replay·immutability를 검증한다.
- 호환 private runtime과 Web에 반영하고 실제1.5/2.5/2점 문항을 각각 확인한다.
- 전체450 및 현재/후속 Item Revision의 배점을 원문과 대조하고 Graph/공개 풀이/INDEX를
  끝까지 연결한다. 기술 완료와 source fidelity를 분리해 최종 판정한다.

이 문서/개발 후보는 운영 활성화나450개 완료 증거가 아니다. 실제 gate는 자료 학습 운영
checkpoint에 append한다. 원문 파일과 과거 실행은 계속 보존한다.
