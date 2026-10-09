# Content-team HwpQuestionEditor handoff profile V2

This successor clarifies presentation intent without changing the supported Markdown grammar.
The complete, byte-preserved content-team authoring prompt remains the editorial source. The V1
reference and all released artifacts remain immutable. This clarification is materialized into
the authoring and review templates of Content Pack `generated-knowledge-item@1.20.15` at build
time; it does not require workers to read a new, unstaged filesystem path.

Produce exactly one UTF-8 Markdown item at the editorial handoff boundary. The worker's actual
submission envelope remains the JSON result schema pinned by its role contract. Do not emit
headings, Markdown emphasis, horizontal rules, block quotes, code fences, HTML, Markdown
links/images, URLs, image paths, image prompts, or validation commentary in the item Markdown.
Preserve ①–⑤ choices and one exact answer line. A ㄱ/ㄴ/ㄷ combination item preserves the ordered
statements and an answer such as `정답 : ③ (ㄱ, ㄷ)`; another choice form omits the statement block
and records the selected choice's core answer content in the parentheses, as required by the source
prompt. Use exactly `[출제의도]`, `[개념출처]`, `[풀이 및 정답 해설]`, and `[오답 해설]` in
that order. Preserve the original correct/wrong explanation partition and `[풀이] 참조` behavior.

For a general item, use no visual marker when none is needed, or one of these ordered structures:

1. `그림`
2. one Markdown table, with no standalone `표`
3. `그림` followed by one Markdown table
4. one Markdown table followed by `그림`
5. `그림 (가)` followed by `그림 (나)`
6. `표 (가)` + table followed by `표 (나)` + table

Do not create more than two independent visual items. An image marker is a layout slot, not an
image path. EOM resolves image bytes through a separately validated immutable Artifact Revision.
Native tables remain rectangular, use the supported 2–5 columns, and retain authored row order.

## Student-visible presentation intent

이 규칙은 콘텐츠팀장 원문의 발문·시각자료 구분을 EOM의 기존 typed draft에 적용하는 연동 지침이다.
원문 프롬프트의 두 파일을 수정하거나 대신 요약하는 지침이 아니다.

- 일반 설명·상황 소개는 upper `stem`의 자연스러운 발문으로 쓴다. 설명이 '자료'라는 이유만으로
  별도의 `<자료>`/`[자료]` 제목, DATA block, 표제 없는 DATA 박스나 빈 layout table을 만들지 마라.
  `다음은 …에 대한 설명이다` 같은 말투는 예시일 뿐 고정 문장이 아니다. 기출의 문장 기능과 실제
  제시 구조를 참고하되 문구를 복제하거나 특정 시작 문장을 강제하지 않는다.
- `<자료>` 칸을 없앤다는 것은 모든 정보를 줄글로 옮기라는 뜻이 아니다. 형식 선택이 허용된
  `AUTO`에서는 줄글과 native TABLE을 동등하게 검토한다. 대상·시점·실험별 수치, 속성, 관측 결과,
  대응 관계, 분류 기준을 행·열에 정리하면 읽기와 비교가 쉬운 경우 표를 적극 선택한다.
  값이 적거나 문장으로도 표현할 수 있다는 이유로 표를 피하지 않는다.
- 표는 숫자 전용이 아니다. 짧은 설명 문장, 현상의 예, '발생함/발생하지 않음' 같은 정성 정보,
  비교해야 하는 빈칸도 셀에 담을 수 있다. 숫자 개수나 글자 수의 고정 임계값으로 형식을 결정하지
  마라. 시간적·인과적 맥락을 설명하는 짧은 줄글은 발문에 남기는 것이 적절할 수 있다.
- 발문은 대상·상황·공통 가정과 필요한 기호·단위 정의를 소개하고, 표는 대응·비교할 실제 정보를
  제시한다. 표의 모든 셀을 발문에서 다시 나열하지 마라. 반대로 표에 있어야 할 비교 정보를 전부
  발문으로 밀어 넣거나, 일반 설명을 `<조건>` 칸으로 옮겨 이름만 바꾸지 마라.
- 그림과 표가 각각 필요한 서로 다른 정보를 제공하면 허용된 `MIXED` 배치를 고려한다. 실제
  `IMAGE_TABLE`/`TABLE_IMAGE` 순서와 발문의 소개 순서를 맞추며 별도의 `<자료>` 제목은 만들지
  않는다. 그림이 없고 표만 필요한 문항도 정상이다. TABLE은 headers·rows·alignments를 갖춘
  편집 가능한 native visual이며 PNG, IMAGE placeholder, 장식용 박스로 대체하지 않는다.
- 이미 검토·고정된 `TEXT`/`DATA`/`TABLE`/`IMAGE`/`MIXED`/`INQUIRY` 요청은 그 exact 형식을 지킨다.
  IMAGE의 `image_supporting_data=NONE`에서 설명을 stem에 두라는 규칙은 해당 IMAGE 형식에만
  적용되며, AUTO나 TABLE에서도 줄글을 우선하라는 뜻이 아니다. worker는 TABLE을 TEXT로,
  IMAGE를 MIXED로 임의 변경하지 않는다. 고정 형식과 꼭 필요한 정보 구조가 충돌하면 기존
  지원된 재계획·실패 경계를 사용하고, 다른 형식을 몰래 끼워 넣지 마라.
- DATA는 reviewed requirement가 실제 독립된 boxed source를 요구할 때만 사용한다. 명시적 DATA
  요청과 IMAGE의 `LABELED_DATA` 의미는 유지한다. CONDITION은 실제 가정·제약만 담는다.
  일반 설명이라는 이유로 어느 블록도 생성하지 않는다. 두 블록이 필요한 경우 DATA가 CONDITION
  앞에 온다. historical DATA/CONDITION 문항은 그대로 읽고 재현하며 이 지침으로 소급 변환하지
  않는다. Preview에서 제목만 숨기거나 renderer가 키워드로 원문을 재배치하는 것은 금지한다.
- 검토자는 발문·표·그림·조건의 역할과 중복을 독립적으로 확인한다. 허용된 형식에서 줄글로
  비교 정보를 불필요하게 나열했는지, 작은 표·정성 표가 오히려 명확한지 검토하되 표를 사용할
  수 있다는 이유만으로 정상 줄글을 오류로 판정하지 않는다. 불필요한 자료 칸이나 정보 중복이
  확인되면 기존 `MATERIAL_PRESENTATION_REDUNDANT` finding에 실제 draft scalar leaf와 구체적인
  사유를 남긴다. typed 형식 위반은 기존 `MATERIAL_REQUIREMENT_MISMATCH`로 구분한다.
  표현 취향만으로 blocking finding을 만들거나 고정 요구를 바꾸는 재작업을 지시하지 않는다.

## Inquiry and equations

Inquiry/experiment items keep matching 탐구/실험 labels, an optional goal, and required procedure
and result. Procedure includes `(가)`, `(나)`, `(다)` chronologically without mixing in results.
Result tables stay inside the result section with no standalone `표`. Do not turn a real inquiry
structure into ordinary prose to avoid a box, or mix it with general visual-slot cases.

Keep `$...$` and `$$...$$` sources intact and preserve the existing supported equation families.
Unsupported equations or layouts fail preflight; never approximate them with plain text, rasterized
tables, dropped observations, or guessed HWPX XML. No sample subject, measurement, or wording
becomes a runtime default.

The canonical item is the complete typed content pinned by the role and Catalog contracts, not
its deterministic Markdown projection. Historical content and template revisions remain readable
without coercion to a newer schema. Never invent or silently select a latest template, prototype,
artifact, or revision when a pinned one is unavailable.
