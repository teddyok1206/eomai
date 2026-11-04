# EOM 개발 문맥

개발 에이전트가 필요한 코드와 검증 경계를 빨리 찾기 위한 로컬 문맥 저장소다.
작업에 맞는 주제 한두 개만 읽고 연결된 실제 코드를 확인한다. 운영용 GraphRAG,
사용자 자료 검색, worker 프롬프트나 실행 권한과는 무관하다.

## 필요한 부분 찾기

| 작업 | 먼저 읽을 문맥 |
| --- | --- |
| 전체 구조와 책임 모듈 | [시스템 지도](system-map.md) |
| 문항 제작과 검토 피드백 | [출제와 검토](authoring-review.md) |
| DB 등록과 원본 그림과 Graph | [문항 DB와 Graph](item-db-graph.md) |
| 유사도 검색과 GPU 임베딩 | [검색과 임베딩](similarity-embedding.md) |
| 미리보기와 한글 출력과 자료 검토 | [문서 입출력](document-output.md) |
| 일반 채팅과 로그인과 슬롯 | [대화와 계정](chat-identity-slots.md) |
| 테스트와 배포와 장애 진단 | [개발과 운영](development-operations.md) |
| 반복하면 안 되는 접근과 후속 판단 | [유지할 판단](working-decisions.md) |

`index.json`은 같은 주제에 대한 검색어와 실제 source/test/reference 경로를 가진다.
명령은 저장소 root에서 실행한다.

```bash
rg -n -i '유사도|similarity|QUERY' docs/agent-context
rg -n 'class |def ' apps/application_api/eom_api/services/item_db_similarity_searches.py
git log -3 --oneline -- services/catalog_service/eom_catalog_service/creative_cohort_execution.py
```

파일명을 추측해 새 모듈부터 만들지 않는다. index의 `source_paths`에서 현재 담당을
찾고 `rg`로 symbol·호출자를 확인한다. 출제·등록·출력·검색에 걸친 수정은 관련 주제를
함께 읽되 전체 문맥 폴더를 매번 한꺼번에 넣지 않는다.

## 정본과 갱신

`AGENTS.md`와 실제 코드·스키마·테스트가 우선한다. ADR은 결정의 배경이며 날짜가 있는
운영 보고는 그 시점의 증거다. 설치 source와 활성 정책·실행 상태는 현재 운영 기록으로
다시 확인한다. 문맥의 설명이 코드와 다르면 코드를 먼저 확인하고 해당 설명을 갱신한다.

`reviewed_source_commit`은 최초 지도를 검토한 source 기준이지 운영 활성 버전이나
모든 문서가 같은 commit에 포함된다는 뜻이 아니다. 작업 대상 경로의 후속 변경은
`git log`/`git diff`로 확인한다. 새 API·상태·adapter·소유 경계가 생기거나 이동하면 해당
노트와 index 경로를 함께 수정한다. 단순 내부 구현 변경마다 전체 노트를 다시 쓰지는 않는다.

새 노트는 먼저 정본 코드/기존 설계 문서에 연결한다. 긴 설계·실패 로그·프롬프트·문항
본문을 복사하지 않는다. 운영 수치·실행 ID·계정·비밀번호·토큰·인증 파일은 여기에
보관하지 않는다. 같은 주제는 기존 노트를 갱신하고 대화별 사본을 계속 만들지 않는다.

## 간단한 저장 방식

- 책임 경계는 개발 탐색이며 정본은 Git source와 기존 문서다.
- 주제 ID는 작은 key, 노트는 수정 가능한 요약이고 source 경로는 원문을 여는 참조다.
- 접근 패턴은 주제/키워드 조회와 제한된 경로 읽기다. 작은 JSON 목록과 `rg`로 충분하다.
- 경로·주제 중복은 set으로, index 구조는 같은 폴더의 JSON Schema 2020-12로 검사한다.
- 검색은 문맥 파일 수/길이에 선형이며 DB·모델·외부 API·상시 서비스가 필요 없다.
- 변경은 Git diff/commit으로 관리한다. 없어진 경로는 검증 실패로 알리고 다른 최신 경로로
  몰래 바꾸지 않는다. 문맥은 업무 실행이나 재시도 authority를 제공하지 않는다.
- 선택한 변경만 stage한다. 새로운 문맥은 runtime package에 포함하거나 production이
  import하지 않는다. 폴더를 제거해도 운영 실행은 영향을 받지 않는다.
- 벡터 DB나 문서 자동 수집기는 현재 규모에 불필요하므로 만들지 않는다. 주제별 짧은
  설명과 코드 포인터를 먼저 사용하고, 실제 탐색 한계가 확인되면 확장한다.

## 문맥 검사

```bash
/srv/eom/conda/envs/eom-api/bin/python -B -m pytest -q tests/unit/test_code_context_navigation.py
```

index 형식·주제 중복·실제 경로·로컬 링크와 노트 누락을 검사한다. 이 검사가 source의
비즈니스 로직이나 실제 운영 동작을 검증하는 것은 아니다.
