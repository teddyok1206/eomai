# INDEX 실행 상태 조회 지연 복구

## 확인된 원인과 수정 경계

2026-11-07 15:54 UTC 마지막 CUDA batch가 완료된 뒤, INDEX runtime authority의
`systemctl show` 읽기 전용 조회가 2초 안에 끝나지 않았다. 단 한 번의
`TimeoutExpired`가 `EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE`로 전파되어
관리 프로세스가 종료됐다. GPU 계산 실패나 원본 미준비로 인한 대기가 아니다.

책임은 기존 Identity runtime adapter의 OS 상태 관측이다. 이 subprocess만
2/5/10초 상한으로 최대 3회 시도한다. 정상 조회는 추가 호출하지 않으며 결과를
캐시하지 않는다. 재시도 성공 후 기존 PID/invocation/UID/config/wheel/file epoch
검사는 모두 수행한다. 잘못된 응답·비정상 종료·권한 오류·설정 변화는 재시도하거나
무시하지 않는다. 세 차례 모두 시간 초과라면 기존 오류로 명시적으로 거부한다.

추가 구조·DB·schema·queue·설정은 필요 없다. 고정 tuple의 O(1) 읽기 재시도이고,
실패 subprocess는 기존 `subprocess.run`이 종료·회수한다. 공유 상태가 없어 CPU/GPU
관측 스레드 간 새 lock도 필요 없다. 임베딩 submit/commit/claim은 반복하지 않는다.
상태 확인을 생략하거나 서비스 전체를 무조건 재시작하는 대안은 실제 설정 변경을
숨기거나 작업을 중복시킬 수 있어 사용하지 않는다.

## 검증·운영 경계

일시 지연 1/2회 후 정상 응답, 총 시도 상한, 다음 조회의 새 관측, 부분 응답·stderr·
비정상 종료·OS 오류, 지연 중 invocation 변경을 검증한다. 기존 runtime admission 및
파일·hash·권한 거부 검사를 유지한다. production 테스트 row를 만들지 않는다.

운영 반영은 기존 INDEX owner successor 절차를 사용한다. 원래 요청의 실제 상태와
수치 worker 종료를 먼저 확인하고, 미완료 요청은 기존 지원된 recovery/cancel 경계로
분류한다. 기존 완료 벡터·원본·Graph·실패 이력은 보존한다. GPU 모델/space/정규화와
API/Web/QUERY 실행은 바꾸지 않는다. 설치 증거와 실제 재개 결과는 후속 기록한다.
