# DB 간편 출력과 Excel 편성의 역할 정리

2026-11-10. 사용자 결정: DB에는 간편 출력만 남기고 정식 편성·저장·사용 이력은
Excel로 모은다. DB의 모의고사 서버 배치는 화면에서 퇴역한다. 향후 여러 문항 AI
생성 기능에서 기존 생산·조립 경계를 검토해 재사용하되 이번에 그 기능을 만들지 않는다.
이 문서는 구현 범위이며 운영 배포나 사용자 검증 완료를 뜻하지 않는다.

## 사용자 동선

- DB의 기존 배치 탭은 `간편 출력`이다. 문항 선택·순서 변경·빼기·교체와
  `한글 파일 만들기`, `Excel에 배치`만 제공한다. 제목/조립 저장 작업은 요구하지 않는다.
- 간편 출력 버튼 한 번이 기존 조립 저장 → 기존 HWPX 제작으로 이어진다. 저장은 재현·
  복구를 위한 내부 출력 입력 확정이며 콘텐츠 배치·사용·인쇄 기록을 만들지 않는다.
- Excel에서 시작한 대량 문항 선택은 별도 occurrence 목록을 계속 사용한다. 기존 개인
  선택 목록을 덮지 않으며 반복 문항과 200개 초과 선택을 간편 출력의 구 계약으로 보내지 않는다.
- 기존 개인 조립과 간편 출력 기록은 Excel의 접힌 `기존 조립·간편 출력`에서 열람한다.
  정확한 저장본을 `Excel에 가져오기`로 편집 초안에 전달하고 실제 저장은 `배치 저장`이다.
  기존 HWPX 조회·다운로드와 공식 목록 제외를 보존한다. 열람만으로 재제작하지 않는다.
- 모의고사 서버 계획의 자동 조회·확정 UI를 제거한다. 기존 application/API/불변 결과는
  삭제하지 않는다. 자동 생성 작업을 Excel의 수동 사용 기록으로 재해석하지 않는다.

## 경계와 구현 판단

1. 책임: Web 선택/출력 controller, Excel의 개인 출력 목록 controller, 기존 Catalog
   조립 application, 기존 HWPX delivery가 각 책임을 유지한다. backend/schema 변경 없음.
2. 정본: 기존 owner별 조립 revision/manifest와 build/Artifact, Excel composition이다.
   브라우저 선택 목록은 임시 typed pointer 배열이며 정본이나 권한이 아니다.
3. identity: 기존 logical assembly / immutable revision / manifest hash를 그대로 사용한다.
   간편 출력의 작은 표시 제목은 문항 수에서 만들며 콘텐츠 이름·출판 연도를 추정하지 않는다.
4. 해석: 기존 exact assembly/revision/hash 검사 후 위치 pointer를 전달한다. 콘텐츠 대상은
   기존 destination picker와 SAVE_SECTIONS의 권한·revision 검사에서 확정한다.
5. 접근: 선택 목록은 ordered iteration, 출력 재전송은 요청 signature/key lookup,
   기록은 owner별 cursor pagination이다. 문항/파일 bytes를 목록에 복사하지 않는다.
6. 구조: 기존 draft/occurrence 모델과 작은 Map·배열을 재사용한다. 새 DB/index 없음.
7. 규모: 기존 개인 출력 200개 계약 유지, Excel 대량 선택은 100행 화면 pagination과
   기존 occurrence 한도 유지. 선택 변환 O(n), 출력 기록 화면은 page size에 비례한다.
8. 동시성: 저장·제작은 기존 서로 다른 멱등 경계다. 저장 응답 손실은 같은 key/body 재전송,
   저장 성공 후 제작 재확인은 같은 assembly의 latest/build 조회다. 브라우저를 transaction으로
   부르지 않는다. 사용자 변경·모드 변경·늦은 응답을 fence하고 중복 클릭을 막는다.
9. 의존: 화면→기존 API→Catalog/Manager/Builder. 다른 서비스 DB/private 구현 접근 없음.
10. 실패: 출력 실패는 기존 FAILED로 남긴다. 목록 조회/다운로드가 새 build를 만들지 않는다.
    명시적 다시 제작만 기존 retry 동작을 사용한다. Excel 가져오기 실패는 기존 초안을 보존한다.
11. 대안: 배치 화면 전체 삭제는 Excel 선택·과거 다운로드를 깨뜨린다. 모든 개인 조립을
    콘텐츠로 자동 이관하면 거짓 사용 이력이 생긴다. 기존 기능의 표시·책임 분리만 수행한다.

## 검증

간편 출력 1회·중복 클릭·저장 응답 손실·제작 상태 재조회, owner/선택 변경과 늦은 응답,
Excel 다중 선택/반복/대량 handoff, 개인 선택 보존, 과거 조립 읽기·다운로드·목록 제외,
정식 편성의 명시적 저장, 모의고사 자동 조회 부재를 실제 DOM/browser와 기존 경계 테스트로
확인한다. HWPX renderer·GPU INDEX/QUERY·Graph·worker·운영 DB를 변경하지 않는다.

## 구현·검증 체크포인트

Web-only 후보로 구현했다. `item-db-assembly.js`는 간편 출력/Excel 선택,
`curated-output-library.js`는 Excel의 기존 개인 조립·출력 목록,
`item-db-delivery.js`는 두 화면이 공유하는 제작/상태/다운로드를 소유한다.
`app.js`의 구 모의고사 계획 자동 조회·확정·polling과 관련 화면/안내/CSS를 제거했다.
기존 backend/API/BFF·HWPX 기록과 numeric execution은 변경하지 않았다.

- 실제 Chromium DB/Excel/안내·BFF·정렬·문맥의 집중 suite: 78 PASS.
- release inventory/build script 계약 검사: 14 PASS. 신규 JS를 필수 설치 파일에 추가했다.
- 변경 Python Ruff/format/mypy와 JS module syntax, `git diff --check` PASS.
- 저장 응답 손실·제작 응답 손실은 각각 같은 body/key를 재사용한다. 성공한 결과 재조회는
  POST하지 않는다. `latest` 응답을 기다리다 owner가 바뀌어 control이 폐기되면 제작하지 않는다.
- 이미 FAILED인 build의 명시적 재제작도 응답 손실 때 새 key를 반복 발급하지 않는다.
- 기존 조립 exact revision/hash 검증, 조회·가져오기로 사용/인쇄 기록 생성 없음,
  목록 삭제 재전송과 원본 보존, 301개 Excel 반복 선택, 계정 전환·늦은 응답을 확인했다.
- 독립 코드 검토에서 두 행 삭제와 늦은 목록 조회가 겹치면 삭제된 행이 다시 나타나는
  화면 경합을 재현했다. 목록 내 삭제 작업을 직렬화하고 확인된 삭제만 즉시 목록에 반영한다.
  계정 전환 전 작업의 종료가 새 작업 잠금을 풀지 않도록 작업 identity를 비교한다.
- 테스트는 합성 입력/응답을 사용하는 실제 browser와 non-live API fixture다. 운영 실제
  HWPX를 새로 만들거나 사람의 한글 레이아웃 검수를 수행했다는 뜻은 아니다.

운영 배포·운영 사용자 확인은 아직 수행하지 않았다. 기존 API 계약을 재사용하므로
후속 배포 대상은 Web이며 DB migration/API/GPU/worker 재시작은 필요하지 않다.
