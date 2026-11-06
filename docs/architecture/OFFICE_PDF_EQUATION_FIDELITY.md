# 한글 원본 PDF의 수식 보존

2026-11-06 UTC. 목표: 확인된 수식 명령문 노출·단독 연산자 오류를 수정하고,
실제 원본 반복 검증과 운영 PDF 열람까지 완료한다. 구현/설치/실제 사용 결과는
별도 운영 기록으로 구분한다.

## 확인한 결함

공식 Catalog로 읽은 HWP8/HWPX4의 기존 PDF와 native 수식180개를 조사했다.
글꼴 지시어 노출9건·붉은 Math 오류 기호3건은 중복을 포함한 표본 관측이다.
현재 설치 변환기로 HWP/HWPX 각1건을 다시 변환해 같은 결함을 재현했다.
`rmA` 등은 지시어가 번역되지 않고, 단독 `TIMES`/`-`는 피연산자 없는 식으로
StarMath에 전달된다. Math 패키지 누락/버전 차이는 아니며 글꼴 설치만으로 해결되지 않는다.
원본의 embedded thumbnail은 오래된 값일 수도 있어 native equation script와 함께 대조했다.

## 책임과 변경 범위

- HWP/HWPX parser→StarMath 번역은 기존 H2Orestart `ConvEquation`의 책임이다.
  검증한 upstream v0.7.14와 기존 그림 crop 호환 패치를 유지하고 수식 호환 패치만 추가한다.
  별도 Python 수식 해석기, 페이지 raster 대체, 원본/정본 덮어쓰기는 만들지 않는다.
- 기존 converter adapter에 두 개의 닫힌 불변 profile을 둔다. legacy는 기존 unit/bundle/
  key를 그대로 사용하고, corrected profile은 별도의 고정 unit과 새 bundle/hash를 사용한다.
  현재 API의 DB PDF와 새 Office 자료 검토 입력은 corrected profile을 명시적으로 선택한다.
- 배포는 기존 private Catalog 설치 prefix와 새 고정 converter source pin을 우선한다.
  공개 RPC/HTTP schema가 바뀌지 않으므로 API/Web·QUERY provider·INDEX/슬롯의 공용
  설치본을 불필요하게 재설치하지 않는다. 실제 compatible-set/RECORD/권한 조회 검증은 유지한다.
- 이미 pin된 학습/Graph/자료 학습 실행은 원래 profile과 Artifact를 유지한다. 기존
  검토·풀이 결과를 새 PDF로 재해석하거나 현재 GPU/슬롯 runtime을 임의 교체하지 않는다.

## 계약·정본·revision

정본은 기존 Intake 원본 revision/member/hash다. PDF는 source와 정확한 conversion
identity를 기록하는 별도 immutable Artifact다. `external-item-preview-manifest/1.0`,
`OfficeDocumentReviewConversionIdentity`, JSON Schema 2020-12의
`office-document-conversion-outcome/1.0`는 이미 converter SHA와 `OUTPUT_VALIDATION` /
`OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID`를 표현하므로 bytes나 의미를 바꾸지 않는다.
새 worker 메시지/권한 필드는 추가하지 않는다. 새 profile 선택은 trusted composition과
고정 systemd argv만 소유하며 사용자·모델이 bundle 경로나 명령을 정하지 못한다.

legacy preview key는 그대로 보존한다. corrected generation은 source revision/edition과
새 renderer profile과 bundle SHA를 포함한 별도 key를 사용한다. manifest에도 실제 bundle SHA를 대조한다.
현재 profile에 해당하는 PDF가 없으면 명시적으로 준비 필요를 반환하고 옛 PDF로 fallback하지
않는다. 기존 GUI의 준비 명령으로 새 파생물을 만들며 과거 Artifact·실패 기록은 보존한다.

## 접근 패턴·자료구조·복잡도

- Profile은 독립 수명 없는 작은 frozen value 두 개다. 임의 registry/framework는 없다.
- 조회는 기존 Job idempotency unique index와 Artifact Revision key lookup이다.
- 같은 source/profile 준비는 기존 Artifact publication-lock adapter의 별도 namespace로
  직렬화하고, lock 안에서 이미 완료된 결과를 다시 확인해 변환을 중복 실행하지 않는다.
- 수식 지시어 정규화는 quote/brace를 보존하는 bounded 순회다. 단독 기호와 계산식의
  연산자를 구분하고 이온 전하의 끝 부호도 literal로 보존한다. 단순 변수명·단위·인용
  문자열·분수·첨자·그리스 문자 등을 회귀한다. 구조 변환 후 스타일을 적용해 upstream의
  분수/행렬 변환이 새 스타일 인수의 중괄호를 잘못 해석하지 않게 한다.
- PDF 품질 검사는 기존 PyMuPDF로 한 번 순회하며 page/span 상한을 둔다. 현재 확인한
  StarMath의 OpenSymbol/오류 색/오류 glyph 조합을 거부한다. 정상 텍스트의 물음표나
  단어 일부만 보고 거부하지 않는다. 모든 수학적 타당성이나 무손실 배치를 증명하는 검사는 아니다.
- 입력 길이에 선형인 순회와 작은 lookup/set을 사용한다. DB schema/index·대형 binary
  저장 방식은 바꾸지 않으며 새 dependency를 추가하지 않는다.

## 트랜잭션·실패·의존 방향

Catalog use case가 current source를 재인가·검증하고 local workspace에만 materialize한다.
고정 converter는 NAS/DB/네트워크 권한 없이 PDF를 만든다. 새 PDF의 품질·hash 확인 후에만
기존 Orchestrator Artifact commit owner로 발행한다. 같은 source/profile의 replay는 기존
동일 결과를 반환한다. 실패·불명확한 실행은 임의 성공/새 key로 우회하지 않는다.

Profile/번역은 저장소·DB에 의존하지 않고, unit/글꼴/PDF는 infrastructure adapter가 소유한다.
CLI/GUI에 수식 규칙을 복제하지 않는다. 새 unit도 기존 sandbox/고정 경로·polkit allowlist만
사용한다. 새 polkit 허용은 shared50의 명시적 owner 거부보다 앞선45에서 exact unit/start/owner만
허용한다. rollback은 Catalog composition/profile을 이전 compatible release로 복구하며 새/옛
Artifact·원본·Graph를 삭제하지 않는다.

## 단계와 완료 gate

1. 설계·호환성 검토: legacy와 current preview·기존 학습 pin·자료 검토 선택 경계를 확인한다.
2. 번역/품질 회귀: Java 직접 실행, Python unit·formatter/lint/type, known-bad PDF 거부와
   정상 수식 허용을 확인한다. 새 dependency/넓은 정규식 삭제로 대신하지 않는다.
3. 실제 입력: 고정된 HWP8/HWPX4와 추가 합성 수식으로 여러 차례 독립 렌더·시각 대조한다.
   파일을 여는 것만으로 PASS라 하지 않고 문자/기호·그림/표·순서·페이지도 확인한다.
4. 임시 PostgreSQL: 새 generation/legacy 보존·동시 준비1회·replay·잘못된 pointer/hash를 검증한다.
   운영 DB에 pytest를 실행하지 않는다.
5. 설치 wheel/RECORD·새 고정 unit·기존 unit 호환을 검증한 뒤 필요한 owner만 호환 배포한다.
6. 실제 DB 준비→PDF 열람→같은 결과 재조회를 확인하고 기존 잘못된 preview를 명시적으로
   새 generation으로 연결한다. 기존 GPU/슬롯과 원본·실패 이력 보존을 확인한 뒤 완료한다.

이전 bundle을 덮어 바꾸고 동일 key로 새 PDF를 밀어 넣는 방식이 더 짧지만,
pin된 학습 입력과 역사적 receipt의 재현성을 깨므로 선택하지 않는다.
