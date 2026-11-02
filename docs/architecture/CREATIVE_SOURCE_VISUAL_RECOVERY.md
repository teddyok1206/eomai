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
