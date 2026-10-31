# 편집 가능한 native HWPX 합본 체크포인트

시각: 2026-10-31 UTC. 운영 서비스·DB·원본 Artifact는 변경하지 않았다.

## 구현과 자동 증거

`eom_hwpx_builder.curated_package_merge.merge_native_hwpx`는 최대 200개 로컬
HWPX의 section 순서와 글·표·수식·페이지 설정을 보존하고, 언어별 글꼴,
문단/문자/스타일과 내장 그림 ID를 전역 충돌 없이 재배정한다. forward/cyclic
style 참조도 모든 ID를 먼저 배정한 후 처리한다. 원본과 역변환한 출력의 XML
정의/section 및 미디어 hash/type lineage를 비교한다. 지원하지 않는 참조,
active content, 외부 경로, 누락된 대상과 다른 전역 설정은 명시적으로 거부한다.

`render-curated --request request.json --result result.json`은 고정 로컬 입력,
정확한 byte count/hash, schema-valid terminal receipt와 private Manager handoff를
사용한다. HWP 입력의 비엄격 변환이나 raster fallback은 하지 않는다.

- 집중 회귀: 42 PASS.
- `tests/hwpx` 전체: 328 PASS / 1 SKIP(기존 opt-in root 소유권 검사).
- 명시적 eom-hwpx Conda Python과 API dependency site를 함께 지정했다.
  첫 전체 실행의 SQLAlchemy collection error는 테스트 환경 구성 오류였으며,
  의존성을 설치/변경하지 않고 명시적 환경 경로로 재실행했다.
- 새 생산 의존성 없음. DB migration 없음. 아직 운영 활성화하지 않음.

## 실제 두 문항

- 10991 원본 SHA: `736a722f9f1dda7f8cc05c862745e67c69cdaaf6d4717ffa25995d15ac251e99`
- 11436 원본 SHA: `abad699d2ea599d5612561094cdb5c46cddd328543d54310471ed7d742d56f9b`
- 새 합본 SHA: `f2e637490ccdfb2c230d07cb09d114ca695cf67f372ab5b5148e363da4d161a9`
- section 순서 `[1,2]`, 내장 그림 멤버 3개.
- 합본 임시 검증 파일: `/tmp/eom-native-curated-merge-646t9lq6/merged.hwpx`
- 독립 렌더 검증: `/tmp/eom-native-curated-visual-20261031/`

기존 고정 `eom-office-converter@...` sandbox에서 원본 2개·합본 1개를 변환했다.
새 unit/서비스 설정은 추가하지 않았다. 생성된 합본 PDF는 A3 2쪽이다.
`pdftoppm -scale-to 1100 -png`로 비교한 대응 페이지 PNG SHA는 다음과 같다.

| 원본/합본 페이지 | PNG SHA-256(양쪽 동일) |
| --- | --- |
| 10991 / 1쪽 | `4d7710e33afe894d4f6d5368c6457da8f21827bde7cdc41603488dfc6cac782d` |
| 11436 / 2쪽 | `6798f7d5c8c55212efb63bf0616c44fbac611eb52db1fa116ee6e423b3c709d2` |

원본과 합본의 픽셀 동등성은 이 두 문항/이 변환기에 대한 증거이며,
모든 HWP/HWPX나 Hancom 자체 편집 품질의 승인을 뜻하지 않는다.

## 남은 경계

1. 원래 HWP의 그림이 사라지는 변환 경계 확인·수정 및 독립 렌더 비교.
2. curated assembly 전용 영속 build record/claim/recovery를 기존 Manager에 연결.
3. 현재 operator의 공개 Catalog 입력 권한 재검증, 검증된 로컬 materialization,
   Orchestrator commit, API/BFF/DB 배치 탭의 제작·다운로드.
4. disposable PostgreSQL 멱등/동시성/중단 검사와 실제 installed release 검증.

기존 Item·Assessment Assembly 전용 FK를 가짜 입력으로 채우거나 기존 동질
템플릿 합본기의 계약을 완화하지 않는다. 저장된 조립 입력을 바꾸지 않는다.
