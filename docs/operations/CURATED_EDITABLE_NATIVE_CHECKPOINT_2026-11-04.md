# 편집 가능한 HWP 합본의 설치본 검증

2026-11-04 UTC. DB 조립 출력의 native 변환·병합 단계에 대한 체크포인트다.
운영 GUI의 합본 제작·다운로드는 아직 연결 전이며 전체 목표는 진행 중이다.

## 실제 입력과 결과

고유번호 10310·10318의 원본 HWP를 격리된 `eom-hwpx` 계정에서 변환하고 합쳤다.
별도 wheel 설치본은 저장소·NAS·인증 파일·네트워크에 접근하지 않았다. 두 wheel의
설치 RECORD 84개 파일을 검증했다.

| 입력 순서 | 결과 | section 순서 | 내부 그림 파일 | 경과 시간 |
| --- | --- | --- | --- | --- |
| HWP 10310 다음 HWP 10318 | 성공 | 1 다음 2 | 4개 | 1.739초 |
| HWPX 10991 다음 HWP 10318 | 성공 | 1 다음 2 | 4개 | 1.080초 |
| 같은 HWP 두 건 재실행 | 성공 | 1 다음 2 | 4개 | 1.681초 |

HWP 두 건 합본과 재실행의 SHA-256은 모두
`7dcfe3398d1fc5dc667dd95739b5fea1e5a0badecb131486faadbe3ea5521c2a`다.
혼합 합본은 `e556c572c354af5f83521081a4d37bac66257b7db76be468560a07f951d72a3b`다.
시간은 이 두 문항의 단회 설치본 검사 값이며 대량 처리 성능으로 일반화하지 않는다.

소스 HWP에서 계산한 문단·표 구조·수식 script·binary fingerprint 및 도형 개수를
변환 후보의 native XML·binary와 대조했다. 10310은 문단 53개·표 5개·수식 4개·binary
2개, 10318은 문단 55개·표 4개·수식 4개·binary 2개가 일치했다. 문단 fingerprint는
공백을 제외한 multiset이며 읽기 순서 자체를 증명하지 않는다. section 순서와 native
병합의 ID·resource 역매핑은 별도로 검사한다.

## 도구와 검증 경계

선택적 HWP 변환 bundle identity는
`sha256:dd88564a9f0c569264eb4b87820b7bdf04dcd9b2990c414f3301ec51be9713fb`다.
고정 upstream commit과 JAR·Java hash를 검증하며 Builder는 입력이 지정한 임의 실행
경로나 ambient Java 옵션을 사용하지 않는다. `/srv/eom/vendor/hwp2hwpx`의 이 bundle만
root 소유 읽기 전용으로 설치했다. 운영 Python·GPU·Codex 설치본은 교체하지 않았다.

Writer가 생략한 빈 style name, 원래 크기와 같은 축의 `curSz=0`, ZIP 포장만 명시적으로
정규화했다. 다른 XML·그림은 역검증한다. 원본 HWP와 각 변환 HWPX를 동일한 현재 Office
sandbox에서 PDF로 읽었을 때 페이지는 pixel-equal이었다. 합본의 두 번째 페이지에는
metadata 표의 `해설` 두 글자 위치 차이가 남아 있다. 본문·그림의 native 보존과 구분하며
전체 합본의 pixel equality 또는 Hancom 수동 검수 완료로 보고하지 않는다.

격리 설치 검사 1·2차는 `pip --target`의 entry-point RECORD 상대 경로를 검증 스크립트가
잘못 해석하여 실행 전에 종료했다. 실패 기록을 보존하고 그 검증 경로만 수정한 3차에서
위 세 결과를 얻었다. 운영 build나 사용자 실패를 성공으로 바꾸지 않았다.

## 검증 기록과 다음 경계

HWPX 전체와 dependency boundary·개발 문맥 검사는 397개 통과했다. 기존 opt-in root
ownership 검사 1개는 기본 실행에서 제외됐으며, 이번 새 변환 경로는 위 실제 격리 계정
설치본 실행으로 별도 확인했다. 변경 Python 16개 파일의 formatter·ruff, 핵심 source
11개 파일의 mypy가 통과했다. DB schema와 영속 build는 아직 변경하지 않았다.

격리 실행 결과는 `/tmp/eom-curated-installed-probe-20261104-03.jsonl`, 결과 파일은
`/tmp/eom-curated-installed-result-20261104-03/`에 있다. 이는 개발 검증용 local 산출물이며
사용자에게 발행한 NAS Artifact가 아니다. 기존 실패 진단은 같은 이름의 01·02 기록이다.

이 체크포인트 이후 가변 canonical Item 출력, curated delivery의 영속 build·claim·중단
복구·Artifact commit, API/BFF·DB 배치 화면·인증 다운로드를 연결한다. DB 검사는 임시
PostgreSQL에서 수행하고, 호환 운영 배포 후 저장된 조립으로 실제 다운로드를 검증해야
전체 목표를 종료할 수 있다.

- [전체 설계와 완료 조건](../architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md)
- [기존 native 합본 체크포인트](CURATED_NATIVE_HWPX_CHECKPOINT_2026-10-31.md)
