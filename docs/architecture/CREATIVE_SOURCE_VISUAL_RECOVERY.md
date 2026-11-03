# 창작 원문 이미지 복구

목표 설정: 2026-11-02 UTC. 슬롯·모델 호출 없이 등록 문항의 잘린 그림을 복구한다.
사용자는 그림 교체를 위한 정본 변경을 승인했다. 별도 노드를 늘리는 것보다
같은 논리 문항과 기존 풀이·검색 연결을 유지하는 가장 작은 수정 경계를 우선한다.

## 확인된 현상과 완료 범위

- 11740의 높이뛰기 그림/설명과 11739의 수평면 표기가 저장된 PNG에서 잘렸다.
  원본의 PDF 페이지는 해당 부분을 온전히 포함한다. 좌표 유효성/해시 검증은
  시각적 완전성의 증거가 아니다.
- HWP/HWPX 내부 원본 그림을 먼저 추출하고, 문제 영역의 정확한 그림과 대응한다.
  그림이 글자·도형·여러 개체로 조립됐다면 단일 BinData만으로 완전하다고 판단하지 않는다.
- 사용할 수 있는 그림은 실제 원본/후보를 직접 대조한다. 매핑 불명확·미지원 사례는
  이유와 고유번호를 남긴다. 잘린 후보를 정상으로 승인하거나 다른 문제 그림을 빌리지 않는다.
- 기존 등록 그림의 직접 교체와 새 등록 시 같은 잘림 방지가 목표다.
- 추가 확정: PDF 캡처/재크롭으로 복구하지 않는다. HWP/HWPX의 원본 내장
  이미지를 사용하며 BMP 등은 전체 픽셀을 보존해 PNG로만 변환할 수 있다.
  기출변형 문서 우측 하단의 원본 기출 첨부 이미지는 대상에서 제외한다.
  본문에서 사용된 이미지 개체의 위치·참조를 확인하고 같은 모양이라는 이유로 대체하지 않는다.
- 추가 사용자 요구: 완성문항 Preview는 이미지 alt_text를 화면 아래 설명으로
  반복 출력하지 않는다. 이미지의 접근성 alt와 실제 panel label은 유지한다.
- 현재 GPU 전체 재임베딩과 풀이보고서/Graph 원본은 중단·재실행하지 않는다.

## 짧은 설계 검토

1. **책임/경계:** Catalog가 원본과 문항을 검증하고, 기존 격리 문서/이미지 adapter가
   임시 결과를 생성한다. NAS commit은 Orchestrator의 기존 file-set publisher가 담당한다.
   worker/슬롯을 새로 실행하지 않는다.
2. **정본:** 등록 source revision의 선택된 2/3교 HWP/HWPX와 그 원본 Artifact.
   PDF/PNG는 파생물이며 파일명만으로 대응하지 않는다.
3. **식별자:** source·Item 논리 ID를 유지한다. 원본/수정 전 포인터와 실제 출력 SHA를
   구분한다. 사용자 승인은 그림 수정을 위한 것이며 기존 실행의 성공/실패 재해석이 아니다.
4. **포인터 검증:** 원본 edition, source revision, media type, source/member SHA,
   문항 영역, 그림 순서/배치/주석의 포함 여부를 확인한다.
5. **접근 패턴:** source/Item revision indexed lookup, embedded member keyed lookup,
   그림 해시 deduplication, 안정된 문항/그림 순서의 bounded iteration.
6. **구조/복잡도:** map/set과 기존 unique registration/publication key를 재사용한다.
   입력 멤버/픽셀 수에 선형 처리하며, 전체 corpus 파일을 서비스 사이로 반복 복사하지 않는다.
7. **규모:** 현재 수백~천여 원문을 bounded cohort로 처리한다. 문서 하나당 임시 입력만
   materialize하고 hash-pinned 추출 결과를 재사용한다. 새 DB/queue/cache는 기본 범위 밖이다.
8. **트랜잭션/동시성:** 파일 추출 동안 DB lock을 잡지 않는다. 최종 그림 교체는
   현재 문항/원본/hash를 다시 확인한 뒤 기존 등록 application의 단일 변경 경계에서 한다.
   진행 중 INDEX가 참조하는 revision·벡터는 먼저 삭제하지 않는다.
9. **의존 방향:** 계약/순수 검증 ← application ← 격리 parser/문서 renderer/Artifact adapter.
   GUI는 검증된 그림을 표시할 뿐 복구 규칙을 구현하지 않는다.
10. **실패/재시도:** 동일 source/그림/도구/결과 해시의 작업은 멱등 재사용한다.
    원본 변동·다중 후보·주석 유실·외부 링크·미지원 형식은 명시적으로 구분한다.
11. **단순 대안:** CSS 확대는 저장된 잘림을 복구하지 못한다. PDF rectangle 전체를
    무조건 확장하면 발문·선지·우측 해설이 섞일 수 있어 원본 개체 대응을 먼저 확인한다.

## 검증과 운영

우선 대표 HWP/HWPX에서 내장 그림과 원본 배치/텍스트를 비교한다. 실행 가능한
복구 경계를 확인한 뒤 schema가 필요한 새 receipt는 구현보다 먼저 정의한다.
추출 실패, 중복/잘못된 개체, 변조 hash, XML/ZIP/OLE 제한, 좌표 경계와 label 보존,
중단/재전송, 기존 문항/Graph/풀이/유사도 조회 보존을 해당 경계에서 검사한다.
기존 문항의 전후 원본·PNG를 실제로 확인하고 운영 조회까지 성공해야 완료다.
원본에서 도저히 복구할 수 없는 항목은 완료 수에 섞지 않고 남긴다.

## 채택한 등록/조회 경계

기존 Item Revision·Graph·풀이보고서·현재 INDEX의 참조는 유지한다. Orchestrator가
같은 문항에 연결된 `control_creative_source_visual_presentation` Artifact를 승인해 발행하고,
Catalog의 공식 표시용 조회에서만 이 원본 이미지 복구본을 해석한다. Artifact는 기존
file-set publisher의 identified publication을 사용한다. 새 DB 테이블·queue·Graph 노드가
필요하지 않으며, 기존 검색 요청·벡터를 다시 계산하거나 다른 문항으로 바꾸지 않는다.

- 표시용 content는 원래 발문·선지·정답·해설·표·순서를 그대로 보존한다.
  복구한 image block의 pointer·크기·표시용 block ID만 달라질 수 있다.
- 공식 canonical content 조회/기존 media block은 원래의 pinned history를 유지한다.
  새 표시용 block ID는 Catalog가 승인된 복구 Artifact에서만 해석한다.
- Preview와 HWPX renderer는 같은 표시용 content Artifact를 사용한다.
  표시 결과의 SHA와 미디어 응답의 SHA를 실제 복구본으로 일치시킨다.
- 최초 버전은 원본을 직접 비교한 operator-assisted 복구만 승인한다.
  원본 기출 첨부·해설 영역을 사용하지 않았다는 기록과 실제 source region을 남긴다.
- 새 조회는 독립된 typed read contract로 추가하며 기존 pinned request schema는 바꾸지 않는다.
  프로필과 문항 revision으로 고정된 publication key를 조회하고 latest 검색은 하지 않는다.
  등록된 복구본이 변조/누락된 경우 원래의 잘린 그림으로 조용히 되돌아가지 않는다.

## 제한된 도구 조사

2026-11-02 대표 4개 파일은 확장자만 HWP인 ZIP이 아니라 실제 HWP5 OLE이다.
내장 BinData를 읽는 조사에는 pure-Python `olefile==0.47`의 read-only API를
격리된 임시 도구 경로에서만 사용한다. 현재 API/INDEX/QUERY Conda 환경은 변경하지 않는다.
이 의존성의 이유는 CFB 파서를 새로 작성하지 않고 검증된 read-only stream reader로
원본 PNG/JPEG를 조사하기 위함이다. 문서 script/OLE 개체/외부 링크는 실행하지 않는다.
제품 경로로 채택할 때는 기존 격리 문서 adapter와 lock/hash 검증 경계에 넣는다.

참고: [olefile read-only API](https://olefile.readthedocs.io/en/stable/olefile.html),
[한컴 HWP 구조 설명](https://tech.hancom.com/%ED%95%9C-%EA%B8%80-%EB%AC%B8%EC%84%9C-%ED%8C%8C%EC%9D%BC-%ED%98%95%EC%8B%9D-hwp-%ED%8F%AC%EB%A7%B7-%EA%B5%AC%EC%A1%B0-%EC%82%B4%ED%8E%B4%EB%B3%B4%EA%B8%B0/).

## 2026-11-02 초기 운영 체크포인트 — 당시 전체 작업 진행 중

- Caption 수정 `8afb4f64`, 표시용 복구/미디어/HWPX source 연결 `30d8a985`.
  API·Catalog·Web 호환 릴리스는 `30d8a985`로 반영했다. DB migration은 없다.
- 현재 등록 창작 모집단은 485문항이다. 그림 없는 146문항은 변경하지 않는다.
  그림 369개를 가진 339문항의 원본 Office·PDF 메타데이터를 공식 Catalog 경계로
  읽었으며, 339건 모두 원본 내장 이미지 추출 검사를 마쳤다. 새 PDF 캡처는 0건이다.
- 직접 비교한 11728/11730/11739/11740 및 추가 25문항의 복구 Artifact를
  Orchestrator로 발행하고, 같은 Item Revision의 실제 Catalog 표시용 조회·미디어
  SHA·재조회를 확인했다. 이 29문항의 정본 텍스트·풀이·Graph 참조는 바꾸지 않았다.
- INDEX MainPID `3284474`와 설치/설정 pin은 배포 전후 동일하다. QUERY의 만료된
  비종결 이력 2건은 현재 연산으로 오인하지 않았으며, 유효 lease·실행 unit이 없는
  시점에 배포했다. 해당 과거 이력은 수정하지 않았다.
- 소스 회귀 200 PASS, 내장 이미지 추출 20 PASS, 새 임시 PostgreSQL의 등록/발행
  동시성·중단 재개 6 PASS. 해당 검사들은 실제 그림 교체 증거의 대체물이 아니다.

추가로 발견한 실제 원본 형태를 구분한다. 일부는 도식 PNG만이 아니라 발문·보기까지
포함한 **문항 전체 PNG**의 일부를 본문에서 재사용하기도 한다(예: 10336). 이 전체 PNG를 그대로
그림으로 등록하면 요구사항 위반이다. 또한 native 글자·화살표·도형을 조합한 사례가
있어 BinData 파일 하나만으로 완성 그림이라고 선언할 수 없다.

따라서 다음을 분리하여 직접 검수한다.

1. 순수 그림 PNG/BMP 등: 전체 원본 픽셀 복구 후 승인된 표시 Artifact로 연결.
2. 원본 그림 주변 native 라벨·화살표: 정확한 원본 개체 위치를 보존하되 문항의
   발문/선지/해설을 그림에 섞지 않는다. 바깥 table frame을 그림으로 오인하지 않는다.
3. 문항 전체 PNG에서 그림만 필요한 경우: 현재 whole-image/1.0으로 허위 발행하지
   않는다. 필요 시 원본 bitmap 내부의 명시적 pixel 영역을 검수하는 successor를 먼저
   정의한다. 이는 PDF 페이지 캡처와 다르며, 원본 전체 이미지/기존 표시본은 보존한다.
4. 실제 그림 이미지가 없거나 대응/방향을 확정하지 못한 경우: 해당 고유번호와 사유를
   남기고 정상 교체 수에 포함하지 않는다.

추출된 모든 BinData를 한꺼번에 승인한 것이 아니다. 특히 우측 원본 기출/해설 그림,
본문의 전체 문항 screenshot, 부분 문장만 남는 조합은 검수 전 운영에 연결하지 않는다.
전체 목표는 진행 중이며 29건의 성공을 corpus 전체 완료로 보고하지 않는다.

후속 검수에서 1.0으로 직접 복구한 문항은 283개로 늘었다. 먼저 발행한 237개는
실제 API 서비스 계정에서 private Catalog → PNG stream SHA → 같은 조회 재실행까지
모두 확인했다. 추가 46개는 Orchestrator 발행 및 Catalog read를 확인했다.
10323의 초기 혼입은 bitmap 자체가 아니라 주변 native 문장/표 경계까지 선택했던
조합 문제로 재분류했다. 이미지 전체 크기가 맞다는 사실만으로 그림 선택을 승인하지 않는다.

## 원본 bitmap 영역 선택 — 1.1 추가 설계

추가 원본 조사에서 한 내장 PNG/BMP를 서로 다른 viewport로 재사용하는 HWP를
확인했다. 본문에 쓰인 개체라도 원래 bitmap 전체에는 두 panel 또는 별도 문제까지
들어 있을 수 있다. 기존 1.0의 `source_image_crops=0` 의미는 바꾸지 않는다.

1.1은 기존 표시 Artifact/단일 publication key/Orchestrator commit을 그대로 사용하되,
각 원본 member의 전체 pixel 크기·hash와 선택한 정수 pixel box를 명시한다.
선택 사유는 본문 개체 viewport, composite의 본문 panel, 빈 여백 제거로 한정한다.
PDF page pixel/capture는 여전히 0이며, 본문 위치와 원본 개체를 직접 대조한 경우만
발행한다. DocInfo의 BinData 순번과 실제 storage ID가 다를 수 있어 파일명 숫자만으로
대응하지 않는다. 참고 기출의 개체 위치에서 잘라낸 이미지는 승인하지 않는다.

기존 1.0 Artifact와 source/Item/Graph/풀이/embedding revision은 보존한다. 새 1.1
schema를 먼저 추가하고 Catalog가 정확한 manifest schema를 읽도록 확장한다.
이미 발행한 같은 문항의 1.0을 조용히 바꾸지 않는다. key lookup은 기존 unique/indexed
Job lookup, 그림은 member map, 작업량은 선택한 pixel/개체 수에 선형이다.
경계/순서/해시/참조 대상 불일치는 등록 전 실패하며 같은 계획의 replay는 같은
Artifact를 재사용한다. 새 DB·migration·queue·프레임워크는 만들지 않는다.

단순히 원본 전체 PNG를 쓰는 대안은 panel 중복과 발문/보기 혼입을 만들므로
이 실제 예외에는 부족하다. 1.1은 PDF 재캡처의 우회가 아니라 원본 bitmap의
검수된 부분만 사용하는 추가 표현 계약이다.

## 2026-11-02 종료 체크포인트 — 333문항 복구, 6문항 미복구 예외

API·Catalog·Web의 실제 호환 릴리스는 `eba075219eca5e35caa10ad10dccb06b4860ecc1`이다.
문서만 추가한 이후 Git commit과 실제 설치 commit을 혼동하지 않는다. migration은 없다.

| 범위 | 결과 |
| --- | --- |
| 시작 시점 승인 창작 문항 | 485 |
| 그림 없는 문항 | 146, 변경 없음 |
| 그림을 가진 대상 | 339문항·369개 image block |
| 원본 bitmap 복구·발행 | **333문항·362그림** |
| 복구 프로필 | whole-image/1.0 283문항 + bitmap-region/1.1 50문항 |
| 실제 설치 API 서비스 계정 → private Catalog → PNG stream SHA → 같은 조회 재실행 | 333/333 PASS |
| 제외한 원본 기출·해설 이미지 / PDF page 캡처 / 모델 실행 | 각각 0 |
| 정본 문항·풀이·Graph·embedding revision 변경 | 0 |
| 긴 alt_text의 Preview 화면 캡션 | 제거, 접근성 alt·실제 panel label 유지 |

1.1 발행 후에도 1.0의 schema bytes와 이미 발행한 Artifact는 그대로다. 기존 canonical
Item content와 과거 crop PNG는 역사적 참조로 보존하고, 현재 Preview와 HWPX 입력
projection에서 승인된 새 표시 Artifact를 선택한다. 과거 증거를 새 pixels로 바꾸지 않는다.
INDEX PID `3284474`와 고정 설치/설정은 두 번의 릴리스 전후 동일하며 재시작하지 않았다.

후속 소스 회귀 215 PASS, whole-image extractor 20 PASS, 새 disposable PostgreSQL에서
두 프로필의 동시 발행·중단 후 재개·동일 요청 재사용을 포함한 6 PASS를 확인했다.
그 임시 DB는 제거했다. 333건의 실제 media 검증은 이 테스트들과 별개로 실행했다.
실제 사용자 브라우저 재확인 및 새 HWPX 파일의 Hancom 육안 검수는 이번 기록에 없다.

### 교체하지 않은 6문항 — 잘못된 복구본을 성공으로 승격하지 않음

| 고유번호 | 실제 원본과 중단 이유 |
| --- | --- |
| 10325 | 과정의 bitmap만으로 결과의 분류 도식을 복구할 수 없다. 같은 bitmap을 두 번 넣는 후보와 결과 도형이 누락된 native 재구성본을 모두 거부했다. |
| 10485 | 독립 PNG가 아닌 native 연대표·셀·글자다. 원래 표 경계가 보존되지 않는 재구성본은 발행하지 않았다. |
| 10901 | 염기 서열이 native 글자·수식이며, 대체 폰트의 원형 문자 간격이 원문과 맞지 않았다. 원본 glyph outline을 확인해도 현재 변환본의 겹침을 정확하게 해소할 수 없어 그대로 두었다. |
| 11404 | RNA 서열이 native 수식이다. 현 PDF 변환 결과에 수식 스타일 토큰이 노출돼 있어 그대로 그림으로 승격하지 않았다. |
| 11472 | native 코돈 표의 수식 개체 일부가 현재 converter에서 제대로 표현되지 않는다. 알 수 없는 기호를 임의로 정정하거나 참고 기출 표를 빌리지 않았다. |
| 11657 | DNA/아미노산 표가 native 글자·수식이다. 원래 수식 및 표 구조의 정확한 복원이 먼저 필요하며, 본문의 임의 캡처나 유사한 다른 그림으로 대체하지 않았다. |

이 6문항·7개 block의 기존 정본/그림은 손대지 않았다. 따라서 **339문항 전체의
잘림을 해결했다고 표기하지 않는다.** 원본 내장 이미지를 직접 교체할 수 있는 대상은
마쳤고, 이 예외는 원본 native 표·수식 변환/구조 복원의 별도 작업이다. 픽셀 없는 영역을
억지로 이미지라고 선언하거나 불완전한 프로토타입을 운영에 내보내지 않는다.

### 증거 보관과 미활성 범위

각 문항의 최종 PNG·표시 content·source proof는 Orchestrator가 NAS에 발행했다.
전체 333개 publication pointer·전수 조회 결과·테스트 로그·6개 예외는 별도의 작은
검증 JSON Schema와 함께 같은 file-set publisher로 감사 Artifact에 보관했다.
이 보고서는 이미지 사본이나 새 정본이 아니라 이미 발행한 immutable revision의
목록이며, DB에 binary/긴 로그를 넣지 않는다.

- 감사 Artifact: `artifact_085dfdebefe04fcfa906e5f4091900d7`
- 감사 revision: `rev_4685ea28efdb4e969e239738a4d8e172`
- `report.json` SHA: `sha256:79e571009bf332f5819987fca84420e44d0dff20c4c463847eadb4b2dfb64b50`
- 저장 위치: `/mnt/nas/eom/artifacts/artifact_085dfdebefe04fcfa906e5f4091900d7/rev_4685ea28efdb4e969e239738a4d8e172/`
- 실제 전수 읽기: `/tmp/eom-restored-creative-runtime-333-20261102.metadata`
- 운영 릴리스/rollback: `/var/lib/eom-creative-bitmap-release-20261102/`

현재 복구는 원본을 직접 대조한 operator-assisted 정비 경로다. 이후 신규 등록을
무검수로 자동 추출·교체하는 기능을 활성화했다고 주장하지 않는다. Graph/RAG의 과거
근거 재생은 기존 pinned history를 유지하며, 문항의 표시용 read와 정본 read를 구분한다.

## 향후 한글 문항 신규 입력 설계

2026-11-03 UTC 사용자 결정. **설계 확정, 신규 입력 경로 구현·검증 중이며 운영 활성화는 아직 아니다.**
이번 333문항 복구에서 검증한 원본 이미지 우선 방식을 이후 HWP/HWPX 문항 입력에
적용한다. 신규 문항은 처음부터 정확한 그림 pointer를 canonical Item에 등록한다.
잘린 그림으로 먼저 등록한 뒤 모든 문항에 별도 복구 Artifact를 붙이는 방식을 기본으로
만들지 않는다. 기존 333문항의 표시용 복구와 역사적 참조는 그대로 보존한다.

### 입력에서 등록까지

```text
고정 원본 HWP/HWPX와 실제 사용자 권한 확인
  → 격리 adapter: 원본 내장 이미지 + 실제 사용 개체/배치 추출
  → 기존 분석 worker: 문항 구성 해석 + 본문 그림 개체 선택
  → Orchestrator: 선택·잘림·라벨·출처 검증 및 이미지 Artifact commit
  → 기존 Catalog 등록: 검증된 이미지 pointer를 canonical Item에 연결
  → 같은 그림 pointer를 Preview·HWPX·문항 읽기에서 사용
```

PDF는 전체 문서 열람·페이지 의미 파악·분석 worker 입력에 계속 사용한다. 다만 HWP/HWPX
본문 그림의 정본을 만들기 위해 PDF 페이지를 캡처하거나 모델이 추정한 사각형을
잘라 저장하는 경로를 기본으로 쓰지 않는다. PDF만 받은 입력은 별도 기존 정책이며,
이 설계를 핑계로 원본 Office가 존재한다고 가정하거나 기출·교과서 전체를 재처리하지 않는다.

### 원본 그림 선택 규칙

1. **실제 형식:** 확장자가 아니라 파일 signature로 HWP5/HWPX를 판별한다.
   `.hwp`라는 이름의 실제 HWPX도 같은 지원 경계로 처리한다.
2. **이미지와 사용 개체 분리:** 이미지 member는 원본 bytes이고, 사용 개체는 본문/참고란에
   놓인 위치·표시 영역·회전 등을 갖는다. 같은 member를 두 곳에서 쓰는 경우 본문의
   사용 개체를 선택한다. 참고란과 member가 같다는 이유만으로 정상 본문 그림을 버리거나,
   같은 모양이라는 이유로 참고란의 다른 개체를 대신 선택하지 않는다.
3. **참고 자료 제외:** 우측 하단 원본 기출·해설은 보통 별도 첨부 영역이지만, 좌우 위치만으로
   판정하지 않는다. 대상 문항의 실제 페이지·구성요소·개체 참조를 확인한다. 두 페이지 문서의
   오른쪽 본문을 참고란으로 오인하지 않는다.
4. **표시 영역:** 원본 전체 bitmap은 보존한다. 실제 본문 개체가 하나의 복합 bitmap 중 일부만
   사용하는 경우 그 native viewport 또는 검증된 panel 영역만 선택하고 정확한 pixel box를
   기록한다. 전체 문항 screenshot이나 발문·보기까지 그림으로 넣지 않는다. 두 panel을
   무조건 이미지의 가운데에서 자르는 식의 추정도 사용하지 않는다.
5. **과학 표기:** 축·수치·단위·화살표·A/B 같은 표기가 별도 원본 개체라면 도식과의 관계를
   함께 보존한다. PNG가 하나 추출됐거나 SHA가 맞는 것만으로 그림이 완전하다고 보지 않는다.
   원본의 orientation과 좌표계 변환을 명시하고, 근거 없는 bbox 확장/축소로 처리하지 않는다.
6. **문항 구성:** 하나의 그림은 불필요한 두 번째 칸이나 panel label 없이 배치한다.
   두 그림은 서로 다른 올바른 component를 순서대로 연결하고, 원본의 native `(가)/(나)`
   같은 panel caption은 가능한 한 편집 가능한 text로 유지한다. 원래 bitmap에 들어 있는
   글자를 임의로 지우거나, 두 block에 같은 복합 그림 전체를 중복해서 넣지 않는다.
7. **표·수식 예외:** 원본이 native table/equation이면 기존 문항의 표·수식 표현을 먼저 쓴다.
   정확한 변환이 안 되면 사유와 원본 pointer를 남긴다. 다른 기출의 그림을 빌리거나 수식
   기호를 추측해 채우지 않는다. 긴 그림 설명은 접근성 alt로 유지하고 Preview 아래에
   본문처럼 반복 출력하지 않는다.

### 기존 모듈에 넣을 책임

- Catalog의 기존 source/권한 resolver가 실제 operator, 고정 원본 revision·hash,
  원본-PDF 변환 lineage와 lifecycle을 확인한다. 파일 경로나 worker가 주장한 권한을
  source identity로 쓰지 않는다.
- 기존 `office_embedded_images` adapter를 재사용해 격리된 local workspace에서 추출한다.
  다음 구현은 **native 사용 개체와 배치의 제품 경로 지원**을 보완해야 한다. 현재 whole-image
  추출 함수나 정비용 staging script가 이를 이미 자동 제공한다고 간주하지 않는다.
- Orchestrator가 추출 manifest를 검증·발행하고 필요한 local source-image catalog를
  기존 worker materialization에 전달한다. worker는 실제 제공된 개체 ID를 선택하고
  문항 구성·본문/참고 구분을 설명한다. 임의 NAS 경로·새 Artifact pointer를 발행하지 않는다.
- `creative_item_registration`의 기존 `_prepare_successor_content`/공식 publication 경계에서
  새 입력 계약을 선택하고, 검증된 `ImageBlock` pointer를 기존 materializer에 넘긴다.
  현재 V2의 PDF crop 동작을 모든 역사적 실행에서 제자리 교체하지 않는다.
- Preview·HWPX·문항/Graph 소비자는 등록된 같은 component를 읽는다. 이미지 수정을 이유로
  풀이보고서·Graph 의미·공개 풀이 입력을 재작성하거나 임베딩을 다시 만들지 않는다.

### 포인터·자료구조·트랜잭션

원본 document revision/hash → embedded member/hash → native picture-use ID/viewport →
선택된 문항 component/출력 hash → 등록된 Artifact pointer로 추적한다. 작은 출처·선택 정보는
typed manifest에 두며 PNG와 원본 파일을 DB나 worker 메시지에 반복 복사하지 않는다.
한 member에 여러 사용 개체가 있을 수 있으므로 파일명이나 그림 hash 하나를 use ID로 삼지 않는다.

member/use/region은 각각 keyed map, 중복·참조 검증은 set, 문항과 그림의 순서는 immutable
sequence로 처리한다. metadata의 매핑·검증은 O(member 수 + use 수 + binding 수), byte 작업은
실제 추출한 member/pixel 크기에 비례한다. 정상 매핑에 corpus 전체 유사 이미지 검색이나
매번 후보끼리의 pixel 비교를 추가하지 않는다. 새 DB·별도 queue·검색 엔진은 필요하지 않다.

parse/선택 중 DB lock을 유지하지 않는다. 이미지 Artifact commit이 확인된 뒤 Item pointer를
등록하고, 같은 원본·추출 profile·분석 결과·선택 계획의 재전송은 같은 산출물을 재사용한다.
추출/commit 중단은 기존 owner의 지원된 resume으로 처리한다. FAILED 이력을 바꾸거나 다른
문항의 그림으로 성공을 꾸미지 않는다. source/권한/hash가 바뀌면 다음 mutation 전에 멈춘다.

### 예외 처리와 구현 순서

그림 예외를 전체 자료 접수·메타데이터·풀이보고서 소실이나 다른 문항 처리 중단으로
확대하지 않는다. 해당 문항의 기존 content-unavailable/오류 격리 경계를 재사용하고,
불완전한 그림이 필요한 산출물을 정상 Preview·HWPX 완료로 승격하지 않는다. 검증하지 않은
새 상태나 관리자 화면을 별도로 늘리지 않는다. 현재 6개 예외도 정상 복구 수에 섞지 않는다.

1. native image-use/worker binding/publication의 필요한 successor를 JSON Schema 2020-12와
   Pydantic으로 먼저 정의한다. 기존 추출 manifest·ImageBlock·1.0/1.1 출처 값은 재사용하고,
   released schema bytes·과거 실행 핀은 보존한다. 문서만으로 새 protocol version을 발급하지 않는다.
2. HWP DocInfo의 BinData 참조와 실제 storage ID, HWPX의 binary-item 참조·viewport·회전·group을
   기존 adapter에서 해석한다. 원본 기출과 본문이 같은 member를 재사용하는 fixture를 포함한다.
3. 기존 Orchestrator materialization → 분석 worker 선택 → publication → Catalog 등록에
   연결한다. 사람의 매 문항 수동 매핑이나 사후 복구를 정상 경로의 필수 절차로 만들지 않는다.
4. source/선택/해시 불일치, external link·unsafe ZIP/OLE·oversize, native label 누락, 전체 문항
   bitmap 혼입, 잘못된 panel 순서/중복, 그림 0·1·2개, 표만 있는 경우를 집중 검증한다.
   concurrency·중단·재전송 검사는 disposable PostgreSQL에서 수행한다.
5. 호환 release 후 새 HWP5·HWPX·확장자 위장 표본에서 실제 등록 → Preview/media → HWPX
   embedding/download를 확인하고 나서 새 입력 경로를 활성화한다. 333건의 과거 복구 성공이나
   unit PASS로 이 활성화를 대체하지 않는다. 기존 전체 자료 재등록·Graph 재생성·GPU 재시작은 없다.

새 의존성·추가 GPU·별도 모델 실행 framework를 선행 도입하지 않는다. 더 단순한
‘PDF bbox를 조금 넓혀 다시 crop’ 방식은 잘린 라벨·참고란 혼입·복합 panel 중복을
구조적으로 막지 못하므로, 신규 한글 입력의 기본 방식으로 채택하지 않는다.

### 신규 입력 구현의 구체화

원본 이미지 catalog는 기존 Orchestrator의 비공개 입력 Artifact로 한 번 발행한다.
분석자는 그 catalog의 **사용 개체**를 선택하고, 등록은 같은 Artifact의 검증된 PNG member를
직접 참조한다. 선택 결과용 PNG를 다시 복사·발행하지 않는다. 비선택 참고 이미지가 입력
Artifact에 존재하더라도 일반 문항 media 조회는 등록된 본문 block의 정확한 member만 허용한다.

새 실행은 Workflow `3.0.0` / role `1.36.0` / plan `32.0` / work input `2.0`으로 분리한다.
풀이·원문 분석은 기존 result `2.0`을 그대로 재사용하고 새 outer role result에 Office 그림
binding만 추가한다. 신규 일괄 접수는 기존 target/policy cohort metadata를 보존하는 `2.0`
실행 binding으로 시작한다. 기존 cohort/continuation 및 진행 중 작업의 실행 핀은 바꾸지 않는다.
새 DB·queue·Graph layer·임베딩 형식은 추가하지 않는다.
