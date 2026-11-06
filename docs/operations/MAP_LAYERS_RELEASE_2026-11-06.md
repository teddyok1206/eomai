# Map 출처 Layer 조회와 기존 슬롯 작업 재개

2026-11-06 UTC. 구현/검증 중 기록이며 실제 배포 완료를 뜻하지 않는다.

## 범위

- 같은 published Graph에서 교과서·기출·창작·외부·AI를 읽는다. 선택한 Layer를 현재
  화면의 일부 노드에서만 숨기는 대신 서버에서 seed 제한 전에 조회한다.
- 기존 Map V2 response/Layer enum을 그대로 쓰고 API/BFF OpenAPI에 optional `layer`
  query만 추가한다. 새 Graph·벡터·schema version·DB migration·캐시·worker는 없다.
- 표시와 SQL은 한 불변 분류 rule tuple을 공유한다. 최초 화면은 각 주요 출처를 조금씩
  보여주며 공통 개념은 복제하지 않고 여러 색으로 표시한다. 상세 근거도 선택한 출처로
  제한한다. 같은 snapshot/hash와 실제 권한·정본 문항 열기는 유지한다.
- 기존 INDEX/numerical 환경과 accepted/FAILED 이력·원본은 변경하지 않는다.

## 슬롯 재개

기존 원본 보류를 원본 변환 실패·읽기 불가·실제 과거 FAILED로 나눴다. `WORKER_RESULT_INVALID`
중 기존 공식 recovery가 허용하는 네 문항11771·11791·11853·11891을 동일 source/controls로
successor 준비·START했다. 원래 실패는 그대로 두고 기존 Orchestrator의 전역 동시4/lease를
사용한다.09:27 UTC 실제03·04·05·06 슬롯 모두 RUNNING 및 유효 lease를 확인했다.
복구 계획/결과는 `/var/lib/eom-map-layer-slot-recovery-20261106`이다. 다른 실패 종류를
억지로 같은 recovery로 취급하거나 읽을 수 없는 원본을 가짜 문항으로 등록하지 않는다.

## 검증

- 집중 API/BFF/분류·SQL·브라우저/문맥/의존 경계54 PASS. 선택 Layer의 source bound
  검사도 포함한다. 실제 Chromium은 기존 설치를 명시적으로 사용했다.
- disposable PostgreSQL material suite44 PASS: 실제 교과서/일반 설명 Graph의 Layer
  조회·고정한 이전 Graph·동일 조회 재전송·근거 조회 및 EXPLAIN을 확인했다. 모델 응답은
  합성 fixture이고 DB/Artifact/Graph owner는 실제다. 작은 fixture의 seq scan을 실패로
  취급하거나 운영 규모 성능의 증거로 확대하지 않는다.
- core6개 mypy 및 formatter/linter PASS. 검증 범위는 겹치므로 합산하지 않는다.
- 후보 설치 wheel·실제 운영 read timing/호환 배포·HTTPS와 background 보존은 후속이다.

## 후속 정리

사용자가 요청한 로컬 파일 정리는 기능 작업 완료 뒤 별도로 수행한다. 활성 프로세스의
argv/cwd/exe/FD·설치/rollback·원본·현재/구 벡터와 모델 참조를 확인하고, 정확한 목록과
감사 기록을 만든다. 광범위한 디렉터리를 이름/나이만으로 삭제하지 않는다.
