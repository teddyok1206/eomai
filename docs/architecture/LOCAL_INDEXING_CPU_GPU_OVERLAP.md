# INDEX의 CPU 예비 처리와 GPU 진행 분리

2026-11-07 UTC. 기존 owner는 `CPU run_once → CUDA reconcile_once`를 동기 실행한다.
운영 journal에서 소량 CUDA 완료 사이에 약 28–32분의 CPU command 처리가 끼었다.
CPU 수치 연산뿐 아니라 자료 검증·publication 비용을 포함한 시간이며, GPU 고장이나
전체 corpus 완료를 뜻하지 않는다.

## 변경 경계

1. **책임:** 기존 INDEX service의 호출 순서만 바꾼다. routed namespace에 한해
   CPU command 하나를 별도 thread에서 처리하는 동안 main thread가 GPU 준비·처리를
   이어간다. CPU-only 구버전 실행 순서는 유지한다.
2. **정본:** 기존 Workflow/command, encoding ledger, committed binding/index다.
   thread/future는 실행 중 호출을 관찰하는 임시 값이며 새 queue나 authority가 아니다.
3. **identity:** 기존 요청·Graph·policy·source revision/hash와 device space를 보존한다.
   CPU로 선택한 요청을 CUDA로 바꾸거나 CPU 벡터를 CUDA 벡터로 등록하지 않는다.
4. **해결 검사:** 기존 Runner claim/heartbeat, service fence, source/Artifact/hash 검증,
   numerical capacity와 commit owner를 그대로 사용한다. Session/transaction은 thread 간
   전달하지 않는다. 공유 Engine/session factory와 불변 설정만 재사용한다.
5. **접근 패턴:** 기존 indexed command queue를 namespace별 round-robin으로 소비한다.
   GPU discovery·정확한 CPU standby 요청 생성은 기존 main lane이 담당한다.
6. **구조:** CPU executor 최대 thread 1개, outstanding future 최대 1개다. 제출할 때마다
   다음 namespace로 이동한다. 대기 작업을 메모리 future 목록에 쌓지 않는다.
7. **규모:** scheduling 상태는 O(namespace 수), outstanding 실행은 O(1)이다.
   자료 수에 따른 기존 DB/index lookup과 수치 batch 상한은 바꾸지 않는다.
8. **동시성:** CPU 하나와 GPU 하나의 owner 호출만 겹친다. 각 요청은 기존 별도 Session,
   원래 command lease와 unique encoding reservation을 사용한다. device별 namespace가
   달라도 같은 source의 immutable pointer를 공유하며 bytes를 복제하지 않는다.
9. **의존:** service entry → bounded CPU lane → 기존 Runner. domain/contract에 thread,
   SQL 또는 systemd를 추가하지 않는다. 새 dependency, migration, wire schema는 없다.
10. **실패/중단:** CPU 예외는 다음 scheduling 경계에서 전달하며 성공으로 숨기지 않는다.
    종료/오류 시 새 호출을 중지하고 이미 시작한 CPU/GPU 호출은 자연 종료까지 기다린다.
    capture/Engine은 그 후 닫는다. QUERY 우선, storage/maintenance 대기, 기존 replay와
    실패 이력은 유지한다. 재배포는 기존 INDEX의 현재 호출이 끝난 뒤 인계한다.
11. **대안:** CPU standby 제거는 CPU/CUDA 공통 published scope를 쓰는 검색을 깨뜨린다.
    GPU 우선 순차 실행만으로는 CPU를 굶기거나 다시 GPU를 오래 막는다. 별도 daemon,
    queue, 큰 source cache보다 같은 owner의 bounded overlap이 변경 범위가 작다.

## 검증

- CPU가 막혀 있는 동안 GPU reconciliation이 실제 호출되는 Event 기반 회귀.
- CPU outstanding 최대 1, namespace 순환, 동일 command 재호출 방지, CPU 예외 전달,
  stop/자원 대기/QUERY 대기 및 양쪽 graceful drain.
- disposable PostgreSQL의 기존 indexed claim·동시 생성·replay·중단 검사. 운영 pytest 금지.
- 기존 wheel/RECORD와 installed identity 검증, INDEX-only release handoff.
- 운영에서 실제 CPU command와 다음 GPU 준비/완료의 중첩·commit을 확인한다.
  GPU 사용률 100%, 전체 완료, 검색 품질 개선을 단순 thread 도입만으로 주장하지 않는다.
