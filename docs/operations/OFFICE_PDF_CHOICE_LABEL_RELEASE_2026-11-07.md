# 한글→PDF 선택지 번호 칸 보정

2026-11-07 UTC. 반복 검증 후 Catalog·고정 변환기를 운영 반영했다.
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
- 최종 bound 보완 bundle도 같은12개 HWP/HWPX를 다시 변환해 모두 PASS했다.
  페이지 수·공백을 제외한 문자 구성·이미지 수를 이전 수식 보존 결과와 대조했고,
  10321의 다섯 번호가 옆 수식과 겹치지 않음을 정량 검사·시각 확인했다.
- Java 레이아웃 규칙18개, 기존 수식41개를 포함한 focused114 PASS.
  실제 Java 코드를 실행한 검사이며 Python으로 규칙을 다시 구현한 테스트가 아니다.
- 기존 학습 재인가·소비자·배포 계약·개발 문맥을 포함한261개 PASS, formatter/linter와
  core5개 mypy PASS. 최종 OXT를 별도 디렉터리에서 다시 빌드해 같은 SHA를 확인했다.
- 검사 harness의 첫 호출은 instance 문자열 자리에 Path를 넘겨 실패했다. 수정 후
  같은 격리 환경에서 재실행했으며 운영 오류나 데이터 변경으로 보지 않는다.
- 초기 FODT 재직렬화 실험은 namespace prefix가 바뀌어 Office가 XML을 일반 텍스트로
  읽었다. 이 실험은 실패로 보존한다. 실제 수정은 원본 HWP/HWPX를 변환기에서 직접
  처리하는 방식이며 그 중간 FODT 실험을 runtime에 넣지 않는다.
- 추가 FODT export를 붙였던 검증 helper에서도 보너스 export 실패가 있었다. 이를
  PDF 성공으로 바꿔 보고하지 않았으며, 해당 보너스 검사를 제거한 실제 PDF-only
  고정 경로에서 최종12건을 재검증했다. FODT는 운영 출력/worker 계약이 아니다.
- 새 패키지·DB migration·모델 호출은 없다. 실제 native 입력과 이전 수식 보존
  결과를 대조하며, 범용 Office 배치 무손실을 주장하지 않는다.

## 운영 상태

`DEPLOYMENT=PASS`, `PRIVATE_API_PREPARE_DOWNLOAD_REPLAY=PASS`.
Catalog의 current preview와 새 Office 검토 입력만 후속 profile을 선택한다.
기존 frozen creative learning은 독립 legacy 인스턴스를 계속 사용한다.
이전 수식 profile의 unit·bundle은 유지하고 API/Web·QUERY·INDEX/슬롯을 재시작하지 않는다.

- 설치 source: `4b4dcc2132783f08d23dbd8f56c005213048a8fe`.
- platform wheel: `sha256:6966fdbeca302b75cc1681ae0e029cbf243be0bfc7a8561a6c24f8660aeef735`.
- API contracts wheel: `sha256:d27a433b8e7bf0aea13aba80e09fd94c93721fbc4be77b845513b56f9a6372ff`.
- 기존 보호 설치기에 별도 prefix로 설치하고 전체 wheel member/RECORD와 실제 API/Catalog
  UID의 import origin을 확인했다. 공유 API의 code/wheel과 공개 RPC bytes는 그대로다.
- 기존 수식 profile의 bundle SHA는50d8cf43… 그대로이며 새 source의 동일 v2 분기를
  사용한다. 새 선택지 profile은 별도 unit/argv/bundle이다. 기존 legacy unit은 변경하지 않았다.
- 새 unit은 실제 Catalog UID의 정확한 start만 허용한다. 다른 unit과 API UID의
  직접 converter 실행은 거부했다. 기존18개 설정 hash와 API/Web/QUERY/INDEX/creative/
  material의 PID/InvocationID도 그대로임을 대조했다.

05:44 UTC에 실제 기존 operator의 현재 권한을 확인하고, 변경하지 않은 설치 API client로
새 profile의 운영 준비→PDF 다운로드→같은 요청의 재준비/재다운로드를 검증했다.
새 로그인·세션 위조나 worker 실행은 하지 않았다. 새 결과와 committed/downloaded/
replayed SHA가 같고, 원본과 legacy/v2 두 세대의 PDF revision도 보존됐다.

| 고유번호 | 원본 | 새 준비 | 같은 결과 재준비 | 새 PDF revision |
| --- | --- | ---: | ---: | --- |
| 10321 | HWP | 6.445초 | 0.015초 | `rev_e50befc1dac543d9a11f1793680de870` |
| 11931 | HWPX | 3.613초 | 0.014초 | `rev_64138aba19e94b95918df4e9a51d05a7` |

10321 Artifact는 `artifact_5e0f44a8276840b88936c5b8d7dad78a`, PDF SHA는
`bae353ea89706ccea48319b2512b6c1e8d989d857ac1faff6e07a7d127a1db31`이다.
실제 내려받은 PDF에서도 선택지 번호5개 bbox 겹침0을 확인했다. 위 시간은 private API의
이 두 사례 실측이지 HTTPS/전체 문항 응답시간 보장이 아니다.

## 증거·복구·검증 한계

- 기존 Orchestrator Artifact owner로20개 member(OXT·검사/설치/실패 로그·정량 결과·PNG)를
  NAS에 commit하고 모든 member를 공식 read 계약으로 다시 읽어 hash를 확인했다.
- 감사 Artifact: `artifact_b156790eb3b746fdb506402b538f3bb4`.
- 감사 Revision: `rev_b2a627dd7b3b4fc7b3d20f798222ac92`.
- 감사 manifest hash: `sha256:7078dfcdcd88d52236aae55d82782cfbd7d52579bb3d9b3a7fabd21809458a9c`.
- root-owned 설치/이전 drop-in/보존 검사: `/var/lib/eom-office-choice-release-20261107`.
  `catalog.before`의 정확한 이전 선택으로 Catalog만 복구할 수 있다. 옛/새 Artifact와
  실패 기록을 지우는 방식으로 롤백하지 않는다.
- DB 구조나 publication 저장/잠금 코드는 바뀌지 않았다. 이전 disposable PostgreSQL33 PASS를
  해당 불변 저장 경계의 증거로 참조하며 이번에 새 DB suite를 실행했다고 주장하지 않는다.
  새 generation 분리·각 profile의 고정 실행·legacy 학습 분리는261 source tests와 실제
  새 profile의 운영 준비/재조회에서 확인했다.
- `MANUAL_HTTPS_BROWSER=NOT_RECORDED`. 사용자의 기존 보고는 문제 발견의 증거이지
  이번 수정본의 수동 승인으로 확대하지 않는다. DB에서 새로고침 후 PDF 준비로 확인할 수 있다.
- 단독①–⑤ 번호 셀의 겹침에 한정한 보정이다. 일반 Office 배치 무손실, 다른 글상자 방향,
  기존 tab leader/표현까지 고쳤다고 주장하지 않는다. 원본과 기존 Graph/풀이/임베딩은 유지했다.
