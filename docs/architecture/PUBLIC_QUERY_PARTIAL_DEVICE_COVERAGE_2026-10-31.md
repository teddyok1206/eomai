# Public 검색 준비 장애: device별 부분 coverage

`webreq_ca3d597215e4bbedd2a1c901`의 서버 요청은 30.48초 뒤 응답 제한에 걸렸다.
준비 쪽 Catalog 검증은 그 뒤에도 계속됐다. DB 관리자 read-only 관측에는 blocker가
없었다. 공통 public GPU/CPU current index의 Graph는 같지만 binding 수는 156/136이었다.
기존 exact device-pair helper는 두 목록이 같아야 하므로 부분 INDEX를 순차로 채우는
public 검색 준비에 그대로 적용할 수 없다. 기존의 exact pair 의미는 바꾸지 않는다.

## 경계와 최소 변경

1. 책임: 기존 Catalog의 device index read/선택과 QUERY transport. 새 검색 엔진/queue 없음.
2. 정본: 각각 정식 등록된 immutable index, 원본/report/Graph/권한과 numerical row.
3. logical/revision/hash는 그대로 고정한다. public 선택(기존 plan1.4)은 각 device의
   독립 index pointer를 이미 갖고 있으며, 응답은 실제 선택된 index의 PARTIAL coverage다.
   원래 exact-pair API/구 plan의 동일 target-set 규칙을 완화하지 않는다.
4. public 전용 owner-local 선택 값은 CPU/GPU pointer와 각 target 수를 별도로 보관한다.
   같은 문항이 양쪽에 있으면 input hash와 source/report/Graph/policy 증거가 같아야 한다.
   한쪽의 점수·vector·coverage를 다른 쪽에 합치거나 전체 완료로 주장하지 않는다.
5. 주요 연산: immutable pointer lookup, source revision map, 공통 target membership 비교.
6. 기존 source/index/row bulk resolver와 dict/set을 사용한다. DB/schema/index 변경 없음.
7. 중첩 비교 대신 O(N+M) 시간·공간. 기존 최대 source/bytes 한도를 유지한다.
8. 실제 operator, 동일 transaction, Graph/policy/current source·artifact provenance fence는
   두 device 모두 그대로 검증한다. Graph 불일치나 source 철회는 허용하지 않는다.
9. contracts/pure value → Catalog read adapter → application route 순서를 유지한다.
10. 원 key/preparation/index를 replay하며 timeout을 새 제출 근거로 쓰지 않는다.
    client/owner response budget은 공통 210초(BFF 240초 미만)로 맞춘다. HMAC capture의
    별도 짧은 deadline과 실제 operator 검증은 늘리지 않는다. 실패 진단에는 단계·정해진
    error code·소요시간만 남기며 request/capture/exception prose는 남기지 않는다.
11. 제한시간만 늘리면 서로 다른 coverage 거부가 남고, 기존 exact helper를 완화하면
    과거 비교/계약의 의미가 변한다. public의 독립 선택만 별도 값으로 표현한다.

원본 FAILED와 미완료 GPU 작업은 수정하지 않는다. source PASS, 설치 PASS, 실제 같은-key
사용자 검색 PASS는 별도 증거로 기록한다. 전체520 완료와 구 벡터 삭제는 여전히 후속 gate다.
