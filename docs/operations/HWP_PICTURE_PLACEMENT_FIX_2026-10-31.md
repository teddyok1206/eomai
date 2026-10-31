# HWP→HWPX 그림 가림 원인과 source-preserving 수정

시각: 2026-10-31 UTC. 대상은 기존 10310·10318 실험 원본이며 원본·DB·NAS
Artifact를 수정하지 않았다. 이 기록은 이전 보존 실패를 성공으로 재해석하지 않는다.

## 재현과 원인

두 HWP와 기존 HWPX 변환 후보를 기존 고정 Office sandbox로 각각 PDF 변환했다.
각 문서의 그림 2개는 변환본에도 있었다. PDF에서 추출한 그림 pixel digest는
원본과 같았다. 따라서 이번 표본은 파일 payload가 사라진 것이 아니다.

문제는 hwp-cli 1.3.1의 picture writer가 원본 공통 개체 속성 대신 다음을
상수로 출력하는 경계다.

- floating 그림: `IN_FRONT_OF_TEXT`, `flowWithText=0`, `allowOverlap=1`.
- 그림의 가로 위치 기준: `PARA`.
- 원본 10318은 `TOP_AND_BOTTOM`, `flowWithText=1`, `allowOverlap=0`,
  가로 위치 `COLUMN`이다. 앞 그림의 자리를 확보하지 않으면서 뒤 그림과
  본문이 겹쳐 가려졌다.

그림의 bbox Y좌표(단위 pt)는 다음과 같다. 나머지 변환 경계의 공통 8pt 이동은
여전히 남으므로 전체 레이아웃 동등성 PASS가 아니다.

| 10318 그림 | 원본 HWP PDF | 이전 변환 후보 | 원본 그림 속성 복원 후 |
| --- | --- | --- | --- |
| 첫 그림 상단 | 551.05 | 543.05 | 543.05 |
| 다음 그림 상단 | 883.85 | 581.35 | 875.85 |

`--preserve-layout`만 켠 별도 후보는 같은 문제가 재현됐다. 수정은 그 옵션을
무작정 활성화하는 것이 아니다. XML 기본값을 모든 그림에 동일하게 적용하지
않고 원본 HWP의 common properties 비트/offset/margin을 정확히 해석한다.

독립 자료:

- [고정 converter picture writer](https://github.com/STAIxBWLB/hwp-cli/blob/v1.3.1/crates/hwpx/src/write/section.rs)
- [HWP 공통 개체 속성의 독립 reader](https://github.com/ebandal/H2Orestart/blob/v0.7.14/source/HwpDoc/paragraph/Ctrl_Common.java)

## 수정 코드와 검증 경계

`eom_hwpx_builder.hwp_picture_placement`는 고정 HWP reader가 읽은 원본
common properties와 exact image SHA로 그림 배치를 복원한다. 값은 작은 frozen
local value이며 별도 worker 명령이나 NAS 접근 권한이 아니다.

- 그림 ordinal/count, 원본 bytes SHA, 크기, z-order가 다르면 실패한다.
- wrap·flow·위치 기준/정렬·offset·margin만 복원한다. 임의 새 위치를 추정하지 않는다.
- 지원하지 않는 flag 값, 잘린 common bytes, 누락된 member는 실패한다.
- 그림 payload는 그대로이며 글·표·수식·다른 XML과 package member의 변경을 거부한다.
- 동일 이미지의 hash는 한 번만 계산한다. XML+고유 media bytes에 대해 선형 비용이다.
- 출력은 새 파일이며 원본, 기존 실패 candidate, 기존 결과를 덮어쓰지 않는다.

실제 영구 모듈로 10310/10318을 각각 복원하고 native 합본기로 순서대로 합쳤다.
조립은 2 sections/4 embedded image members이며 같은 source pointer를 재사용한다.

| 출력 후보 | SHA-256 |
| --- | --- |
| 10310 | `67ee703e5ddbc0af404e888cec6f06406fa611089988ea06e0166efedd8ac1ad` |
| 10318 | `99c41dec6a389cc737684b0498f0bded473b6bd171e8e6fce5a77b72677adbb6` |
| 합본 | `db7cc291f366ecb1348c2200d55180d29100a6414f04eac0c2053fbe4d19d857` |

임시 후보: `/tmp/eom-hwp-permanent-placement-20261031/`.
독립 렌더: `/tmp/eom-hwp-preserved-assembly-visual-20261031/`.

새 모듈 포함 `tests/hwpx`: 341 PASS / 1 SKIP(기존 opt-in root 소유권 검사).
formatter/linter/type checker PASS. 두 개별 후보와 2쪽 합본 모두 기존 Office
sandbox에서 열렸고, 합본에서의 그림 bbox는 개별 수정본과 일치했다.

추가 음성 증거도 보존한다. 개별 수정본과 합본 대응 페이지의 pixel 비교에서
1쪽은 동일했지만 2쪽은 선택지 부근 416 pixels가 달랐고 PDF text extraction
길이도 15자 달랐다. 이미지 둘의 위치/크기/byte digest는 같았다. 자원 역매핑
XML 검증만으로 importer/Hancom의 글꼴 표시까지 단정하지 않는다. 이 차이와
위 공통 8pt 이동 때문에 HWP 전체 보존형 변환을 아직 승인하지 않는다.

## 완료하지 않은 범위

이 모듈은 그림 배치 보존 경계의 수정이며, converter의 다른 `control_removed`
또는 metadata 손실을 승인하는 allow-list가 아니다. DB 영속 build queue와
Manager/Builder 실행·검증·commit·다운로드·GUI 연결은 별도 미완료 상태다.
현재 `render-curated` native profile은 HWP를 여전히 명시적으로 거부한다.
새 HWP 보존 profile을 검증·연결하기 전 운영 HWP 전체 지원으로 광고하지 않는다.

이번 운영 배포는 유사도 요청의 Web hotfix뿐이다. HWPX 코드 후보는 소스 검증
단계이며 GPU INDEX/QUERY/창작 슬롯과 기존 입력 문서·승인 이력은 변경하지 않았다.
