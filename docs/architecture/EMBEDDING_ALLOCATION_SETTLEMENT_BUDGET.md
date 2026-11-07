# GPU 임베딩 완료 확인 시간 분리

2026-11-07. 실제 INDEX 실패를 대상으로 한 기존 실행 경계 수정이다.

## 관측과 결정

원 allocation은 09:07:02 UTC부터 최대 420초였다. 입력 파일은 09:11:26,
벡터와 결과 파일은 09:13:54에 생성됐지만 원 deadline은 09:14:02였다.
worker는 09:14:03, controller는 09:14:08 실패했다. 저장 파일은 완료 승인이나
index publication 증거가 아니다. CPU/GPU 병행 시 완료 처리 여유가 사라졌고,
worker의 180초 kernel timer도 모델 계산뿐 아니라 최종 통신 ACK까지 감싸고 있었다.

1. 책임은 기존 allocation control과 numerical worker다. 새 서비스나 큐를 만들지 않는다.
2. 정본은 기존 allocation의 absolute monotonic expiry, batch timeout, 설치된 unit이다.
   JSON Schema/wire bytes 형식과 logical/revision/artifact/hash 의미는 변경하지 않는다.
3. 새 allocation만 control allowance 600초 + numerical timeout(최대 180초)을 사용한다.
   관측된 준비 264초와 후속 여러 source 검증을 감안한 유한 예산이며 무한 연장이 아니다.
   기존 allocation의 nonce/deadline은 replay에서도 그대로다.
4. kernel compute timer는 backend 검증·model load·encode·backend cleanup을 감싼다.
   descriptor 결과 검증·출력·최종 ACK는 원 allocation deadline에 묶는다. 모델이 살아 있는
   동안의 child authorization은 compute 시간에 포함되므로 계산 상한을 우회할 수 없다.
5. source/actor/lease/schema/hash/physical GPU checks는 생략하거나 캐시하지 않는다.
   입력과 출력은 기존 typed pointer/FD 경계이며 binary 복사나 DB 저장을 추가하지 않는다.
6. access pattern은 O(1) 시간 예산 계산과 기존 순차 batch 처리다. DB/index 변경은 없다.
7. transaction/claim/lease/reservation과 current authorization은 기존 소유자에 남는다.
   expiry나 결과 파일 존재만으로 성공, CPU fallback, 재계산을 허용하지 않는다.
8. pure timing rule은 catalog contracts, kernel timer는 native worker, systemd hard bound는
   기존 physical adapter가 소유한다. worker 840초, controller 900초로 cleanup 여유를 둔다.
9. 이전 실패는 원 physical retirement와 supported workflow reconciliation으로 닫는다.
   accepted output이 없는 실패만 기존 producer가 후속 시도할 수 있다. 기존 성공 벡터 보존.
10. numerical/runtime control bytes 변경을 숨기지 않는다. idle 확인 후 기존 private-successor
    설치·qualification·호환 INDEX/controller activation을 사용하며 rollback bytes를 보존한다.
    모델·dtype·입력·vector space는 동일성 검증 없이 변경/재분류하지 않는다.
11. deadline만 없애거나 검증을 건너뛰는 대안은 종료/권한 보장을 깨뜨린다. 단순 상한 증가만은
    ACK가 compute timer를 소비하는 별도 문제를 남기므로 timer 범위도 함께 바로잡는다.

## 검증

old expiry/replay 불변, bounded new deadline, compute 180초 상한과 실제 kernel 종료,
ACK 대기 시 compute timer 해제·allocation expiry 유지, 예외 cleanup, unit/hash 정렬,
관련 disposable DB replay/recovery, 설치 wheel/qualification을 검증한다. 운영에서는
source/READY PASS와 별도로 새 index commit 및 다음 batch 진행을 확인한다.
