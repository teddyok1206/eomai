# 한글→PDF 수식 보존 수정·검증·배포

2026-11-06 UTC. 수식 수정과 반복 검증 후 Catalog·고정 변환기의 운영 반영을 완료했다.
실제 설치 API client를 통한 준비·다운로드·재조회는 PASS이며, 사용자 브라우저 육안 확인은
별도로 요청했으나 아래 기록 시점에는 아직 회신을 받지 않았다.
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
- 첫 Catalog 후보의 연결 검토에서, 현재 UI preview 인스턴스를 기존 creative late authorization에도
  공유하던 composition을 발견했다. 기존 실행은 legacy PDF를 pin하므로 Catalog 선택을 즉시
  이전0373ef48로 복구했다. 후보710d4748·설치·rollback 기록은 보존한다. 새로운 풀이/Graph/
  임베딩은 시작하지 않았고 기존 실패를 성공으로 바꾸지 않았다. UI에는 corrected profile,
  frozen learning authorization에는 독립 legacy 인스턴스를 주도록 보완하고 회귀를 추가했다.
  이 보완 후 기존 창작 source/claim authorization 검사를 포함한238개가 PASS했다.
  API/Catalog의 preview·peer socket 회귀3개도 별도로 통과했다.
- 최종 Catalog 설치본의 첫 실제 private client 호출에서는 수식 변환 전 실행이 거부됐다.
  새polkit55 규칙보다 shared50의 명시적 owner 거부가 먼저 적용되는 문제였다. 공유 규칙의
  권한을 넓히지 않고 exact Catalog/start/unit 허용을45로 앞당겼다. 실제 권한 판정과 동일
  원본의 변환·다운로드·재전송을 다시 확인하며, 처음 실패한 검증 로그는 보존한다.

감사 자료 NAS 보관·전체 readback 뒤 임시 검증 DB 두 개와 해당 임시 credential state만
공식 cleanup guard로 제거했다. 운영 DB·원본·과거 PDF·검증 실패/성공 로그와 실제 표본은
제거하지 않았다. runtime bundle은 보호된 로컬 설치와 NAS 감사 Artifact 양쪽에서 확인 가능하다.
실제 자료 내용·PDF·PNG·OXT·긴 로그·인증 자료는 Git에 넣지 않는다.

## 운영 배포와 실제 PDF

- Catalog와 고정 converter의 설치 source는 `f5572fa982042789a916dee4041ff26d4443246c`.
  polkit 순서 보정의 배포 source는 `8696684461976bf56ae7990fd16f1ef642fbae9a`.
  실제 platform wheel은
  `sha256:109cd9c19dff033a549e2ea52f00077a58cf96d83e73b896f5d35d8ef58eba3e`,
  함께 설치한 API contracts wheel은
  `sha256:0890242bf2f164fa9cb427a295906b7aae6d6127fd761df4f8ab3d3bba98f711`.
- 기존 보호 설치기를 통해 별도 prefix에 설치하고 wheel/RECORD와 실제 API/Catalog UID import,
  module origin을 확인했다. API client와 Catalog RPC 계약 bytes는 기존 버전과 동일하다.
  공유 API·Web·QUERY·INDEX·creative/material 서비스는 교체/재시작하지 않았다.
- 고정 converter의 polkit 판정은 실제 Catalog UID의 정확한 unit start만 허용하고,
  같은 UID의 다른 unit 및 API UID의 converter start는 거부했다. 첫 pkcheck invocation은
  비특권 caller가 action details를 지정해 거부됐으며 실제 renderer 결함으로 해석하지 않았다.
  trusted action caller에서 실제 subject UID/PID/start time으로 검사해 위 결과를 확인했다.
- 18:35 UTC, 기존 cohort의 실제 operator 권한을 다시 확인한 운영 CLI에서 변경하지 않은
  설치 API client→운영 Catalog→고정 unit→Orchestrator commit→media 다운로드를 수행했다.
  새 로그인이나 session 위조, worker 실행·원본 교체·Graph 변경은 없었다.

| 고유번호 | 원본 | 처음 준비 | 같은 결과 재준비 | 새 PDF Artifact Revision |
| --- | --- | ---: | ---: | --- |
| 10321 | HWP | 6.345초 | 0.017초 | `rev_5de09a6722454747976a35925fca13e9` |
| 11931 | HWPX | 3.736초 | 0.019초 | `rev_b2bf02e9a1174584827969f497450a5a` |

위 시간은 두 원본의 해당 실행 실측이다. 전체 HTTP 응답/모든 문항의 처리시간 보장이 아니다.
두 건 모두 새 PDF의 committed/downloaded/replayed SHA가 같았고 페이지 수·원본 source SHA·
옛 preview revision을 유지했다. 새 PDF를 직접 렌더해 수식도 확인했다. 같은 generation의
재준비는 새 변환/Artifact를 만들지 않는다.

- 10321: `artifact_e5dedea343b94c0f84255bdb9fe8ab37`, PDF SHA
  `40ec20c7105e4e330a71f91d109369a57e8965f134de3f02cdabed32ebdf6a4d`.
- 11931: `artifact_dd4e0a68ea6940ea8d46bbb04ead5f1f`, PDF SHA
  `65c3158513024f240f985b546e9caea09924295458a3e6fa2bb5d5b4985a1b53`.

운영 관련18개 설정 hash와 API/Web/QUERY/INDEX/creative/material의 MainPID/InvocationID를
배포 전후 대조해 변화 없음을 확인했다. legacy bundle/unit/PDF와 기존 frozen learning 입력은
그대로다. migration·모델 실행은0이다. 기존 legacy PDF는 새 세대가 아니므로 현재 DB에서
기존 잘못된 PDF를 열고 있었다면 `PDF 미리보기 준비`로 새 결과를 받아야 한다.

## 증거 보관과 복구

기존 Orchestrator Artifact commit owner로 OXT·빌드·실패/성공 로그·실제 PDF 검증 manifest·
보존/권한 확인·PNG 표본24개 member를 NAS에 발행하고 모든 member를 공식 read 계약으로
다시 읽어 해시를 확인했다. PNG/OXT의 format reference는 raw binary codec 표지이며 JSON
Schema로 binary bytes를 검증했다는 뜻이 아니다.

- 감사 Artifact: `artifact_addb0cfa311d4ebab6357b50ecdb76a4`.
- 감사 Revision: `rev_4d44e9f709a64cecab77b88acf89452c`.
- 감사 manifest hash: `sha256:23069b6910234692d0cc08165143706f27f84e919f2eea0c6b492718cbc23fb9`.
- 보호된 설치·이전 Catalog drop-in·rollback·postchecks:
  `/var/lib/eom-office-equation-release-v2-20261106`.
  rollback은 해당 `catalog.before`의 정확한 이전 선택을 복원해 Catalog만 재시작한다.
  새/옛 Artifact나 실패 이력은 삭제하지 않는다.

최종 source suite238 PASS, 별도 private socket 회귀3 PASS, disposable PostgreSQL33 PASS와
migration 왕복을 확인했다. 새 polkit 위치 반영 후238개를 다시 PASS했다.
이 테스트들의 일부는 겹치므로 합쳐서 독립 검증 개수로 보고하지 않는다.

## 사용자 확인과 남은 한계

`MANUAL_HTTPS_DB_PREVIEW=NOT_RECORDED`(확인 요청 전송). 실제 운영 private API client 성공을
사용자 로그인·브라우저 육안 확인 성공으로 확대 해석하지 않는다. HTTPS 로그인 화면은200을
확인했지만, 인증된 UI 확인의 대체 증거는 아니다.
확인은 DB의10321 또는11931에서 `PDF 미리보기 준비 → PDF 열기`로 할 수 있다.
검증한 오류군의 수정이며 모든 임의 수식·글꼴·Office 배치를 완전히 보장하는 결과는 아니다.
기존11931 편집용 출제의도 box의 세로 배치나10321 선지 표지 겹침은 이번 수식 변경의
해결 범위로 주장하지 않는다. 기존 리뷰·등록·임베딩 입력을 새 PDF로 재해석하지 않았다.
