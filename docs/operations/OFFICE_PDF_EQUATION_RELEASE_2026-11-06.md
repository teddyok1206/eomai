# 한글→PDF 수식 보존 수정·검증·배포

2026-11-06 UTC. 현재 구현·반복 검증 진행 중이며 운영 활성화 전이다.
원본·과거 PDF·풀이/Graph·실패 이력과 현재 GPU/슬롯의 설치 pin은 보존한다.

설계: [수식 보존과 현재/역사적 변환 경계](../architecture/OFFICE_PDF_EQUATION_FIDELITY.md).

## 확인과 수정

- 실제 열람용 HWP8/HWPX4와 native 수식180개에서 글꼴 지시어 노출9건·Math 오류 기호3건을
  관측했다(중복 포함). 그중 HWP/HWPX 각1건은 기존 변환기로 다시 변환해 재현했다.
- 기존 H2Orestart v0.7.14와 그림 crop 호환 패치를 유지한다. 수식의 구조 변환 이후에
  quote/group-aware 스타일 처리를 적용하며 단독 기호와 이온 전하를 계산식과 구분한다.
- 새 bundle의 SHA-256은 `50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb`.
  기존 `0.7.14-eom.1`은 보존한다. 후보 bundle 변경은 운영 배포가 아니며 과거 후보 bytes와
  실패·성공 기록도 별도로 보존한다. Git에는 patch/Java source/provenance만 둔다.
- 알려진 OpenSymbol/오류 색/오류 glyph 조합은 정상 PDF로 발행하지 않는다. 이 검사를
  일반 물음표/명령어 일부 문자열 탐지나 모든 수학적 정확성 보장으로 확대하지 않는다.
- 현재 preview generation은 원본 revision/edition/profile/bundle SHA로 구분한다.
  옛 PDF로 자동 fallback하지 않고 같은 generation의 재조회·동시 준비는 기존 결과를 재사용한다.

## 실제 검사 checkpoint

- Java helper 직접 회귀41개 PASS. 처음의 compiler 실행 경로/Java release metadata 부재는
  설치되어 있는 compiler module과 Java8 source/target 사용으로 정정했다. 새 dependency는 없다.
- 첫 실제 후보의 접근 경로 mode 문제는 설치 UID의 module-origin 확인으로 검출·수정했다.
  source를 읽지 못해 legacy module로 fallback한 후보는 실패 기록으로 보존하고 통과로 바꾸지 않았다.
- 수식 구조 처리 순서를 보완한 후보의 실제 원본12건은 모두 변환 성공·지시어/Math 오류 표시0,
  페이지 수 유지였다. 최종 이온 전하 후보에서도 같은12건을 다시 통과했다.
- 추가 합성 수식20종의 실제 변환을 확인했다. 확대29종에서 이온 전하의 오류를 검출해
  같은 변환기의 스타일 처리에 보완했고, 확대 입력을 다시 변환해 정상·오류 표시0을 확인했다.
  합성 fixture의 수식 box는 크게 잡았으므로 일반 문항의 typography 기준선으로 쓰지 않는다.
- 기존 오류 PDF3건을 새 품질 검사로 거부하고, 수정한 실제 PDF12건의 통과도 독립 확인했다.
- 최종 source suite174 PASS(번역/변환/검토 입력/preview/replay/배포/기존 학습 소비자/개발 문맥).
  Java helper41개는 이 suite에 포함되므로 별도 독립 검사 수로 더하지 않는다.
- 임시 PostgreSQL 첫 suite는32 PASS/1 FAIL이었다. 실패는 다른 test의 synthetic slot 역할을
  재사용한 기존 control fixture 문제였고, guarded disposable DB에서만 inventory를 고정·복원하도록
  고쳤다. 별도 새 임시 DB의 migration 왕복과 해당 suite33 PASS를 확인했다. 운영 역할은 바꾸지 않았다.
- formatter/linter 및 core8개 mypy PASS. JSON Schema/DB migration 변경은 없다.
- 최종 bundle을 별도 output 디렉터리에 다시 빌드해 같은 SHA를 확인했다. 실제 HWP/HWPX와
  합성 전하/음수 지수/벡터 결과를 렌더해 눈으로도 확인했다. 기존 Office 배치의 일부
  편집용 글상자 방향·선지 겹침은 별도 한계이며 이번 수식 수정의 해결 범위로 주장하지 않는다.
- 확대한 배포 소비자 검사에서 현재 migration0074/analysis12와 오래된 test 기대값의
  차이를 발견해 test inventory만 현재 released source에 맞췄다. 실제 migration·정책·workflow는
  수정하지 않았다. 최종174 PASS는 이 보정 후 결과다.

임시 검증 DB와 로컬 수치/시각 자료는 최종 evidence 보관·해시 확인 뒤 정리한다.
실제 자료 내용·PDF·PNG·OXT·긴 로그·인증 자료는 Git에 넣지 않는다.

## 아직 닫지 않은 gate

최종 source/wheel/RECORD·설치 identity·현재/legacy 변환 실행·negative 권한·설치 후 실제
DB 준비→PDF 열람→동일 결과 재조회, compatible Catalog rollout과 기존 background pin 보존을
확인해야 한다. source/실제 격리 후보 검증을 운영 사용 완료로 보고하지 않는다.
