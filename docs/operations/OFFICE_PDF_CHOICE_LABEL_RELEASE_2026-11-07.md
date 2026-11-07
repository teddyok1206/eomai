# 한글→PDF 선택지 번호 칸 보정

2026-11-07 UTC. 구현·검증 중이며 이 문서의 초기 기록은 운영 활성화 완료를 의미하지 않는다.
설계는 [기존 수식 변환기의 후속 배치 보정](../architecture/OFFICE_PDF_EQUATION_FIDELITY.md).

## 확인한 원인과 범위

- 사용자가 보고한①–⑤는 글꼴 글리프 소실이 아니라 번호 셀의 들여쓰기 때문에
  옆 칸 A/B/C 수식과 겹친 경우다. 실제10321에서 다섯 번호의 PDF bbox 겹침을 확인했다.
- native HWP record·고정 변환기의 FODT native table과 PDF를 함께 대조했다. 번호 칸 폭은
  약12.52pt, 글꼴 크기는11.5pt인데 번호 문단에11.5pt의 추가 여백이 적용돼 있었다.
  원본 thumbnail은 참고 자료이며 그것만으로 현재 원본 내용을 확정하지 않았다.
- bundle revision3은 기존 revision2 수식/그림 변환을 보존하고, 단독 번호 셀의 여백만
  줄인다. 제목/발문/선지 본문/해설/수식·그림·표 geometry나 원본을 교체하지 않는다.
- 최종 bundle SHA:
  `1aaabf0114d6ec1cee130c9f5b01d756a321ba0525d0ea211cccec01acfeb99a`.
  이전 revision1/2 bundle과 historical PDF는 보존한다. 개발 후보와 실패한 실험도
  운영 성공으로 재해석하지 않는다.

## 검사 기록

- 기존 수식 보존12개 원본에 대한 첫 native 후보에서 페이지 수·문자 구성·이미지 수를
  유지했고10321의 다섯 번호 bbox 겹침이0이 됐다. 추가 control 수 상한을 보완한
  최종 bundle도 반복 검사한다. 최종 gate 결과와 운영 설치는 완료 시 아래 갱신한다.
- Java 레이아웃 규칙18개, 기존 수식41개를 포함한 focused114 PASS.
  실제 Java 코드를 실행한 검사이며 Python으로 규칙을 다시 구현한 테스트가 아니다.
- 기존 학습 재인가·소비자·배포 계약·개발 문맥을 포함한261개 PASS, formatter/linter와
  core5개 mypy PASS. 최종 OXT를 별도 디렉터리에서 다시 빌드해 같은 SHA를 확인했다.
- 검사 harness의 첫 호출은 instance 문자열 자리에 Path를 넘겨 실패했다. 수정 후
  같은 격리 환경에서 재실행했으며 운영 오류나 데이터 변경으로 보지 않는다.
- 초기 FODT 재직렬화 실험은 namespace prefix가 바뀌어 Office가 XML을 일반 텍스트로
  읽었다. 이 실험은 실패로 보존한다. 실제 수정은 원본 HWP/HWPX를 변환기에서 직접
  처리하는 방식이며 그 중간 FODT 실험을 runtime에 넣지 않는다.
- 새 패키지·DB migration·모델 호출은 없다. 실제 native 입력과 이전 수식 보존
  결과를 대조하며, 범용 Office 배치 무손실을 주장하지 않는다.

## 운영 상태

`DEPLOYMENT=PENDING`.
Catalog의 current preview와 새 Office 검토 입력만 후속 profile을 선택한다.
기존 frozen creative learning은 독립 legacy 인스턴스를 계속 사용한다.
이전 수식 profile의 unit·bundle은 유지하고 API/Web·QUERY·INDEX/슬롯을 재시작하지 않는다.
