// Reviewed UI copy only. No runtime state, user text, permissions or requests.
const guide = (title, description) => Object.freeze({title, description});

const views = new Map(Object.entries({
  dashboard: guide("작업함", "진행 중인 작업과 최근에 만든 문항을 한곳에서 봅니다. 이어서 할 작업을 누르면 그 문항의 진행 상황이나 한글 파일 제작·승인 화면으로 이동합니다."),
  chat: guide("ChatGPT", "평소 말하듯 질문하면 답변을 받을 수 있습니다. 시스템에 있는 문항과 교과서·기출 자료도 참고할 수 있습니다. 참고한 자료는 답변 아래에서 확인하세요. 대화만으로 문항 제작이나 승인이 시작되지는 않습니다."),
  workflow: guide("문항 제작 진행", "문항을 만들고 검토하는 과정을 확인합니다. 문항이 등록되면 이 화면에서 한글 파일 제작으로 이어갈 수 있습니다. 완성된 내용을 확인한 뒤 최종 승인하세요."),
  request: guide("새 문항 요청", "만들고 싶은 문항을 적고 단원·난이도·자료 형식을 고른 뒤 ‘문항 제작 시작’을 누르세요. 나중에 이어서 준비하려면 ‘초안 저장’을 누르세요. 저장만으로 문항 제작이 시작되지는 않습니다."),
  item: guide("완성 문항", "만들어진 문항의 문제·그림·표·선지·정답·해설을 봅니다. 승인 여부도 확인할 수 있습니다. 내용을 확인한 뒤 한글 파일 제작으로 이어가세요."),
  "item-db": guide("DB", "‘조회’에서 문항을 찾고, ‘유사도’에서 비슷한 문항을 찾습니다. 고른 문항은 ‘간편 출력’에서 한글 합본으로 받거나 Excel에 배치하세요. 교재·회차별 배치 저장과 사용 이력 관리는 Excel에서 합니다."),
  excel: guide("Excel", "교재나 시험지를 만들고 회차별로 문항을 배치합니다. 배치를 저장하면 어디에 쓴 문항인지 기록됩니다. 작년 구성을 새 판으로 복사할 수 있고, 실제 인쇄에 들어간 구성은 따로 체크해 남깁니다."),
  hwpx: guide("HWPX·문항 승인", "선택한 문항을 한글에서 열 수 있는 파일로 만듭니다. 완료되면 내려받아 문제·그림·표를 확인하세요. 파일 제작과 최종 승인은 별개입니다. 내용을 확인한 뒤 승인 버튼을 눌러주세요."),
  "pdf-review": guide("자료 검토", "검토할 문제지를 올리세요. 해설이 별도 파일이면 해설지도 함께 올릴 수 있습니다. 특히 확인할 부분을 적으면 기본 검토에 더해 살펴봅니다. 결과에서 잘못된 내용과 자료 속 위치를 확인하세요."),
  "quality-review": guide("품질 평가", "완성된 시험지를 사람이 읽고 평가하는 곳입니다. 문제와 해설이 좋은지, 얼마나 고쳐야 하는지, 수정에 몇 분 걸렸는지 남깁니다. 파일 제작 성공과 문항의 품질은 따로 확인합니다."),
  control: guide("Codex 실행 관리", "문항 제작과 검토에 쓰는 작업 자리가 사용 중인지 확인합니다. ‘슬롯’은 작업 자리 하나를 뜻합니다. 로그인에 문제가 있을 때는 관리자가 해당 자리의 로그인 상태를 확인할 수 있습니다."),
  "admin-settings": guide("관리자 설정", "관리자가 직원 계정을 만들고 사용할 수 있는 기능을 정하는 곳입니다. 문항 제작·검토의 실행 설정도 여기서 관리합니다. 안내 모드는 설명을 보여줄 뿐 다른 기능을 사용 가능하게 만들지는 않습니다."),
  account: guide("내 계정", "내 로그인 정보와 사용할 수 있는 기능을 확인합니다. 아이디나 비밀번호를 바꾸려면 현재 비밀번호를 먼저 입력하세요. 다른 사람의 계정은 이곳에서 바꾸지 않습니다."),
  learning: guide("자료 학습", "교과서·참고서·문제집·시험지를 PDF나 한글 파일로 올리세요. 설명과 문항을 나누어 읽고 검색에 쓸 수 있도록 정리합니다. 올린 자료의 진행 상태와 기존 기출의 풀이보고서 현황도 확인할 수 있습니다."),
  knowledge: guide("Map", "교과서·기출·창작·AI 문항과 개념이 어떻게 연결되어 있는지 봅니다. 점을 누르면 설명과 연결된 자료가 오른쪽에 나오고, ‘주변 연결 펼치기’로 계속 살펴볼 수 있습니다. 점 사이의 거리는 유사도 점수가 아닙니다."),
  "knowledge-quality": guide("학습 범위·품질", "학습한 문서의 페이지가 빠지거나 겹쳤는지 확인하는 관리자용 점검 화면입니다. 자료 학습 화면의 분석 기록에서 열 수 있습니다."),
  explorer: guide("운영 기록", "관리자가 문항 제작과 파일 제작 등의 기록을 찾아보는 곳입니다. 종류·상태·기간으로 검색하거나 알고 있는 작업 번호를 입력하세요. 기록을 직접 고치는 화면은 아닙니다."),
  support: guide("고객센터", "사용법이 궁금하거나 오류가 나면 문의를 남기세요. 어느 화면에서 무엇을 눌렀는지와 화면에 나온 문의 번호를 적으면 도움이 됩니다. 비밀번호나 로그인 인증 코드는 보내지 마세요."),
}));

// Related controls share one description; stable IDs are the lookup keys.
const groups = [
  [["excel-save", "excel-choose", "excel-empty-slot"], "문항 배치", "먼저 왼쪽에서 회차를 고르세요. ‘DB에서 문항 선택’으로 문항을 찾아 ‘Excel에 배치’를 누르면 돌아옵니다. 빈 자리를 먼저 만들 수도 있습니다. ‘배치 저장’을 눌러야 사용 기록에 반영됩니다."],
  [["excel-copy", "excel-new-edition"], "다음 판 준비", "‘다음 판으로 복사’는 현재 저장한 구성을 새 이름과 연도로 복사합니다. 이전 판은 바뀌지 않습니다. 처음부터 배치하려면 ‘빈 판 만들기’를 누르세요."],
  [["excel-print-panel"], "인쇄 기록", "실제로 인쇄한 회차를 선택해 기록하세요. 이후 배치를 수정해도 인쇄 당시 구성은 남습니다. 파일을 내려받기만 한 것은 인쇄 기록에 포함하지 않습니다. 잘못 체크한 기록은 이유를 적어 취소할 수 있습니다."],
  [["guide-mode-toggle"], "안내 모드", "켜면 메뉴·버튼·입력 항목에 마우스를 올리거나 키보드로 이동할 때 설명을 볼 수 있습니다. 끄면 안내가 사라집니다. 새로고침하면 다시 꺼진 상태로 시작합니다."],
  [["global-id", "global-load"], "작업 번호로 열기", "문항이나 파일 제작의 작업 번호를 알고 있다면 여기에 입력하세요. 번호를 모르셔도 괜찮습니다. 작업함이나 각 화면의 최근 목록에서 찾을 수 있습니다."],
  [["mobile-menu", "sidebar-scrim"], "메뉴 열기·닫기", "좁은 화면에서 왼쪽 메뉴를 열거나 닫습니다. 메뉴에서 이동할 화면을 선택할 수 있습니다."],
  [["logout", "mobile-logout"], "로그아웃", "이 브라우저에서 로그아웃합니다. 이미 시작한 문항 제작이나 검토는 취소되지 않고, 저장된 기록도 남습니다. 다시 이용하려면 로그인하세요."],
  [["api-health", "observe-health"], "시스템 연결 상태", "시스템에 연결할 수 있는지 보여줍니다. 연결이 정상이라는 뜻이지, 요청한 작업이 끝났다는 뜻은 아닙니다. 작업의 진행 상황은 해당 화면에서 확인하세요."],
  [["workbench-refresh", "chat-refresh", "recent-items-refresh", "hwpx-recent-refresh", "control-refresh", "learning-refresh", "quality-review-refresh", "pdf-review-refresh", "support-refresh", "timeline-refresh"], "새로고침", "목록과 진행 상황을 최신 내용으로 다시 불러옵니다. 문항이나 파일을 새로 만들거나 검토를 다시 시작하는 버튼은 아닙니다."],
  [["chat-new"], "새 대화", "새로운 주제로 대화를 시작합니다. 이전 대화는 왼쪽 목록에 남습니다. 새 대화에서도 참고할 자료가 있다면 다시 골라 첨부하세요."],
  [["chat-input", "chat-send"], "질문 보내기", "궁금한 내용을 평소 말하듯 적고 보내세요. 내부 자료를 참고한 답변에는 참고 자료가 표시됩니다. 오류가 나면 화면의 안내를 확인하고, 같은 질문을 연달아 보내지는 마세요."],
  [["chat-more-conversations", "chat-more-messages", "item-db-more", "pdf-review-more", "support-more", "explorer-next"], "기록 더 보기", "아직 화면에 나오지 않은 이전 기록이나 다음 목록을 불러옵니다. 원하는 기록이 바로 보이지 않을 때 눌러보세요. 현재 목록에 없다고 삭제된 것은 아닙니다."],
  [["chat-knowledge-panel", "chat-knowledge-query", "chat-knowledge-submit"], "참고할 문항 찾기", "개념이나 주제를 입력해 관련 문항을 찾으세요. 필요한 문항을 골라 대화에 첨부할 수 있습니다. 답변이 실제로 참고한 자료는 답변 아래에서 따로 확인합니다."],
  [["chat-knowledge-recent", "chat-knowledge-generated"], "최근 문항 찾기", "최근에 등록되었거나 시스템에서 만든 문항을 찾습니다. 문항을 열어 내용과 승인 여부를 확인한 뒤 대화에 참고 자료로 붙여주세요."],
  [["chat-knowledge-exam-year", "chat-knowledge-exam-month", "chat-knowledge-exam-grade", "chat-knowledge-exam-number"], "시험 조건으로 찾기", "시험 연도·월·학년으로 범위를 좁힙니다. 문항 번호를 비워두면 해당 시험의 문항들을 찾고, 번호를 넣으면 그 문항으로 좁힙니다."],
  [["workflow-id", "workflow-load"], "제작 진행 불러오기", "작업 번호를 입력해 이미 시작한 문항의 진행 상황을 봅니다. 번호를 모르면 작업함에서 선택하세요. 불러오기만으로 새 문항이 만들어지지는 않습니다."],
  [["workflow-hwpx-continue", "item-hwpx-continue"], "한글 파일 만들기로 이동", "현재 보고 있는 문항으로 한글 파일을 만드는 화면에 갑니다. 문항이 등록된 뒤 사용할 수 있습니다. 완성된 파일과 내용을 확인한 다음 최종 승인하세요."],
  [["request-text"], "어떤 문항을 만들까요?", "다룰 개념과 만들고 싶은 상황을 적으세요. 예를 들어 ‘포물선 운동을 다루는 중간 난이도 문제, 그림 한 개 포함’처럼 쓰면 됩니다. 단원과 자료 형식을 고른 뒤 ‘문항 제작 시작’을 누르세요."],
  [["draft-new"], "새 요청", "현재 입력을 비우고 새 문항 요청을 준비합니다. 이미 시작한 제작이나 만들어진 문항은 삭제하지 않습니다. 같은 내용으로 새 문항을 만들 때도 새 요청에서 작성하세요."],
  [["draft-save"], "초안 저장", "수정한 주제·난이도·자료 형식 등을 저장합니다. 저장만으로 문항 제작이 시작되지는 않습니다. 준비가 되면 ‘문항 제작 시작’을 눌러주세요."],
  [["draft-submit"], "문항 제작 시작", "확인한 초안대로 문항을 만들고 자동으로 내용을 검토합니다. 시작한 뒤에는 진행 화면에서 확인하세요. 기다리는 동안 같은 요청을 여러 번 보내지 마세요."],
  [["past-exam-variation-clear"], "기출변형 해제", "선택한 기출을 바탕으로 만드는 대신 일반 문항 요청으로 돌아갑니다. 원래 기출이나 이전에 만든 문항은 삭제되지 않습니다."],
  [["recent-items", "item-load", "item-id", "revision-id"], "문항 선택", "최근 목록에서 문항을 고르거나 알고 있는 문항 번호를 입력하세요. 문항을 여러 번 수정했다면 ‘버전’으로 수정본을 구별합니다. 고른 수정본으로 미리보기와 파일 제작이 이어집니다."],
  [["structured-intake", "structured-load-sources", "structured-base-revision", "structured-revision-etag", "structured-review-reason", "structured-content-json", "structured-reviewed", "structured-import-submit"], "문항 수정 · 고급 기능", "정해진 입력 형식으로 문항의 새 수정본을 등록하는 기능입니다. 원래 문항은 남습니다. 이 형식에 익숙하지 않다면 직접 입력하기 전에 관리자에게 문의하세요."],
  [["item-db-search-tab", "item-db-assembly-tab", "item-db-similarity-tab"], "조회·간편 출력·유사도", "‘조회’에서 문항을 열고, ‘유사도’에서 비슷한 문항을 찾습니다. ‘간편 출력’에서는 고른 문항을 한글 합본으로 받습니다. 교재·회차에 배치하고 사용 이력을 남기려면 Excel로 보내세요."],
  [["item-db-similarity-start"], "비슷한 문항 찾기", "지금 선택한 문항과 비슷한 문항을 찾습니다. 결과를 고르면 조회 화면에서 자세히 보고 출력할 문항 목록에도 담을 수 있습니다."],
  [["item-db-similarity-refresh"], "같은 검색 결과 확인", "진행 중인 검색의 결과를 다시 확인합니다. 검색을 새로 여러 번 시작하는 버튼은 아닙니다."],
  [["item-db-similarity-run", "item-db-similarity-top-k"], "검색 시작과 결과 수", "목록에 담은 문항마다 비슷한 문항을 몇 개씩 볼지 정한 뒤 검색을 시작하세요. 이미 끝난 검색을 다시 보려면 아래 최근 검색에서 열어주세요."],
  [["item-db-similarity-source-select"], "기준 문항 바꾸기", "여러 문항을 함께 검색했다면 여기서 결과를 볼 기준 문항을 고르세요. 아래 미리보기와 결과 목록이 선택한 문항에 맞게 바뀝니다."],
  [["item-db-quick-create"], "간편 출력", "고른 문항을 현재 순서대로 하나의 한글 파일로 만듭니다. 제목이나 교재를 먼저 만들 필요는 없습니다. 이 출력만으로 교재 배치나 인쇄 기록이 생기지는 않습니다."],
  [["item-db-draft-to-excel"], "Excel에 배치", "고른 문항을 넣을 교재·판·회차를 선택합니다. 문항을 가져온 뒤 Excel의 ‘배치 저장’을 눌러야 사용 이력에 반영됩니다. 취소하면 현재 선택은 유지됩니다."],
  [["excel-output-library", "excel-output-refresh", "excel-output-more"], "기존 조립·간편 출력", "예전에 저장한 조립과 간편 출력 기록을 찾습니다. ‘Excel에 가져오기’로 배치를 이어가거나 기존 한글 파일을 확인할 수 있습니다. 목록을 여는 것만으로 새 파일을 만들지는 않습니다."],
  [["material-title", "material-kind", "material-description"], "올릴 자료 정보", "나중에 찾기 쉬운 제목과 자료 종류를 고르세요. 출처 설명에는 출판사나 교재명처럼 이 자료가 어디에서 왔는지 적어주세요."],
  [["material-main", "material-solutions"], "학습할 파일 선택", "PDF 또는 한글 파일을 고르세요. 본문과 문제 파일은 필수이고, 해설이 다른 파일에 있다면 별도로 함께 올릴 수 있습니다. 보통 파일 한 개는 256MB까지이며, 문항 정보 엑셀과 함께 올리는 한글 파일은 각각 50MB까지입니다."],
  [["material-workbook"], "문항 정보 엑셀 함께 올리기", "모의고사 한 회차의 문제·해설 한글 파일과 문항 번호·단원이 있는 엑셀을 함께 올립니다. 글·표·수식을 편집할 수 있는 문항별 한글 파일로 등록하며, 빈 고유번호는 임의로 만들지 않습니다. 엑셀은 .xlsx 형식, 8MB 이하여야 합니다. 일반 PDF 자료를 학습할 때는 이 칸을 비워 두세요."],
  [["material-instructions"], "자료 읽는 방법 알려주기", "문제·해설의 번호 체계나 자료 배치에서 주의할 점을 적어주세요. 설명이 없어도 기본 기준으로 읽지만, 특이한 구성을 알려주면 도움이 됩니다."],
  [["material-rights", "material-learning-start"], "자료 학습 시작", "내부 학습과 문항 등록에 사용할 권한이 있는 자료만 올려주세요. 접수한 뒤에는 화면을 닫아도 처리가 이어집니다. 진행 상태는 ‘올린 자료’에서 확인하세요."],
  [["material-learning-refresh", "item-db-similarity-history-refresh"], "저장된 목록 새로고침", "이미 접수하거나 저장한 작업의 목록을 다시 불러옵니다. 같은 파일을 다시 올리거나 새 검색을 시작하는 버튼은 아닙니다."],
  [["map-query", "map-layer"], "개념과 자료 종류로 찾기", "찾을 개념을 입력하거나 교과서·기출·창작·외부·AI 중 자료 종류를 골라 연결을 살펴보세요. 점 사이의 거리는 문항의 유사도 점수가 아닙니다."],
  [["map-fit", "map-refresh"], "지도 화면 정리", "화면 맞춤은 보이는 점들을 한 화면에 모아 보여줍니다. 새로고침은 현재 연결 정보를 다시 불러오며, 원문 자료나 문항을 바꾸지 않습니다."],
  [["item-db-graph-unit", "item-db-graph-year", "item-db-graph-month", "item-db-graph-number"], "기출 검색 조건", "기출을 선택한 뒤 단원이나 시행 연도·월·문항 번호로 찾습니다. 찾은 문항은 기출변형에 쓰거나 출력할 문항 목록에 담을 수 있습니다."],
  [["hwpx-existing-build-id", "hwpx-build-load", "hwpx-recent-builds"], "이전에 만든 파일 찾기", "최근 목록에서 파일 제작 작업을 고르거나 작업 번호를 입력하세요. 새로 만들지 않고 기존 진행 상황과 내려받을 파일을 확인합니다."],
  [["hwpx-revision-id"], "파일로 만들 문항", "한글 파일로 만들 문항의 수정본을 나타냅니다. 작업함이나 완성 문항에서 넘어오면 자동으로 연결됩니다. 보고 있던 문항이 맞는지 확인하세요."],
  [["hwpx-item-number"], "파일에 표시할 문항 번호", "한글 파일에서 문제 앞에 붙일 번호입니다. 예를 들어 3을 입력하면 3번 문제로 표시합니다. 문항 내용이나 승인 여부는 바뀌지 않습니다."],
  [["hwpx-build-submit"], "한글 파일 만들기", "선택한 문항을 한글에서 열 수 있는 파일로 만듭니다. 완료되면 내려받아 그림·표·수식을 확인하세요. 파일을 만드는 것과 최종 승인하는 것은 별개입니다."],
  [["hwpx-build-refresh"], "파일 제작 진행 확인", "이미 요청한 파일이 준비됐는지 다시 확인합니다. 새 파일 제작을 요청하는 버튼이 아니므로, 목록이나 진행 상황이 오래된 것 같을 때 사용하세요."],
  [["hwpx-download-link", "pdf-review-correction-download"], "한글 파일 내려받기", "준비된 한글 파일을 내 컴퓨터에 내려받습니다. 한글 프로그램에서 열어 그림·표·수식과 배치를 확인하세요. 내려받았다고 내용까지 확인된 것은 아닙니다."],
  [["hwpx-approval-reason", "hwpx-approval-submit"], "문항 최종 승인", "문제와 해설, 완성된 파일을 확인한 뒤 승인 이유를 적고 승인하세요. 파일을 만들기만 해서는 승인되지 않습니다. 승인 결과는 문항을 조회할 때도 표시됩니다."],
  [["codex-reauth-slot", "codex-reauth-label", "codex-reauth-ack", "codex-reauth-start", "codex-reauth-close"], "작업 자리 다시 로그인", "로그인이 필요한 작업 자리를 골라 화면의 안내대로 로그인합니다. 관리자가 진행하는 기능입니다. 비밀번호나 인증 코드는 고객센터나 대화에 보내지 마세요."],
  [["operator-create-username", "operator-create-display-name", "operator-create-password"], "직원 계정 만들기", "관리자가 직원의 로그인 아이디·이름·임시 비밀번호를 적습니다. 사용할 기능도 골라주세요. 만든 뒤 직원에게 로그인 정보를 안전하게 전달하세요."],
  [["preset-base-select", "preset-base-revision", "preset-display-name", "preset-general-knowledge", "preset-description", "preset-capacity-revision", "preset-protocols", "preset-draft-submit"], "작업 설정 준비 · 관리자용", "문항 제작과 검토에 쓸 설정을 준비합니다. 저장만으로 실제 설정이 바뀌지는 않습니다. 관리자가 변경 내용을 확인하고 적용하는 절차를 따릅니다."],
  [["preset-review-open", "preset-review-confirm", "preset-review-cancel"], "작업 설정 확인", "준비한 설정에서 무엇이 바뀌는지와 동시에 할 수 있는 작업 수를 확인합니다. 확인 버튼을 눌러도 바로 실제 작업에 적용되는 것은 아닙니다."],
  [["preset-release-confirm", "preset-release-cancel", "preset-release-submit"], "작업 설정 발행", "확인한 작업 설정을 발행하는 관리자 기능입니다. 바뀌는 내용과 진행 중인 작업을 먼저 확인하세요. 안내 모드는 이 버튼의 설명만 보여줍니다."],
  [["account-current-password"], "지금 쓰는 비밀번호", "아이디나 비밀번호를 바꾸기 전에 본인인지 확인하는 칸입니다. 지금 로그인할 때 쓰는 비밀번호를 입력하세요. 다른 사람에게 알려주지 마세요."],
  [["account-new-username"], "새 로그인 아이디", "앞으로 로그인할 때 쓸 아이디를 적습니다. 아이디를 바꾸지 않으려면 비워두세요. 다른 사람이 이미 쓰는 아이디는 사용할 수 없습니다."],
  [["account-new-password", "account-new-password-confirm"], "새 비밀번호", "비밀번호를 바꾸려면 새 비밀번호를 두 칸에 똑같이 입력하세요. 지금 비밀번호를 그대로 쓰려면 두 칸 모두 비워두면 됩니다."],
  [["account-credentials-submit"], "계정 변경 저장", "입력한 새 아이디나 비밀번호를 저장합니다. 현재 비밀번호도 입력해야 합니다. 저장 후 다시 로그인해야 할 수 있으니 새 정보를 기억해두세요."],
  [["knowledge-batch-id", "knowledge-quality-load"], "자료 정리 기록 찾기", "관리자가 알고 있는 작업 번호로 자료를 정리한 기록을 찾습니다. 어느 페이지를 확인했고 빠진 곳이 있는지 볼 수 있습니다."],
  [["density-toggle"], "표 표시 밀도", "운영 조회 표의 행 간격을 바꿉니다. 데이터·정렬·권한을 변경하는 기능은 아닙니다."],
  [["json-copy", "json-close"], "자세한 기록 보기", "선택한 기록의 작업 번호를 복사하거나 설명 창을 닫습니다. 관리자에게 문의할 때 작업 번호가 도움이 됩니다. 기록 자체는 바뀌지 않습니다."],
  [["quality-assembly-select", "quality-secondary-positions", "quality-plan-create"], "평가할 시험지 선택", "평가할 시험지를 고르고 두 사람이 각각 확인할 문항 번호를 정합니다. 이미 완성된 시험지를 평가하며, 문항이나 파일을 다시 만드는 기능은 아닙니다."],
  [["quality-reviewer-role", "quality-session-start", "quality-session-finalize"], "평가 시작·완료", "전체 문항을 볼지, 정해진 문항을 한 번 더 볼지 선택하고 평가를 시작합니다. 필요한 점수와 의견을 모두 남긴 뒤 완료하세요."],
  [["quality-open-item", "quality-open-hwpx", "quality-open-evidence"], "평가할 자료 열기", "평가할 문제와 한글 파일, 참고 자료를 엽니다. 실제로 내용을 읽어본 뒤 확인했다고 표시하세요. 단순히 열기 버튼을 누른 것과는 다릅니다."],
  [["pdf-review-file"], "문제지 올리기", "검토할 문제지 파일을 고르세요. PDF와 한글 파일을 올릴 수 있습니다. 한글 파일은 화면 확인용 PDF로 바꿔 검토하며, 원본 PDF 내용을 고치지는 않습니다."],
  [["pdf-review-solution-file"], "해설지도 올릴까요?", "해설이 별도 파일이면 함께 올려주세요. 문제와 정답·풀이가 맞는지 확인하는 데 도움이 됩니다. 별도 해설지가 없으면 비워두셔도 됩니다."],
  [["pdf-review-submit"], "자료 검토 시작", "올린 파일을 선택한 유형과 추가 설명에 맞춰 검토합니다. 진행 상황과 결과는 ‘최근 검토’에서 확인하세요. 기다리는 동안 같은 파일을 여러 번 보내지 마세요."],
  [["pdf-review-page-prev", "pdf-review-page-next"], "문서 페이지 이동", "선택한 문제지 또는 해설지의 이전·다음 페이지를 봅니다. 검토사항을 선택하면 연결된 문서 위치도 함께 확인할 수 있습니다."],
  [["pdf-review-correction-submit"], "선택한 내용 고치기", "한글 문서에서 수정할 수 있는 검토사항을 골라 새 한글 파일로 만듭니다. 원본은 남기고 바뀐 글자는 빨간색으로 표시합니다. PDF 원본을 직접 고치는 기능은 아닙니다."],
  [["pdf-review-annotation-submit"], "검토 표시가 있는 PDF 만들기", "원래 내용은 그대로 두고 확인할 위치에 연한 보라색 표시와 설명을 붙인 PDF를 만듭니다. 내려받은 파일의 주석 목록에서 설명을 읽을 수 있습니다."],
  [["support-submit"], "문의 보내기", "적은 문의 내용을 보냅니다. 어느 작업에서 문제가 생겼는지와 화면에 나온 문의 번호도 적어주세요. 비밀번호와 로그인 인증 코드는 보내지 마세요."],
];

const controls = new Map(groups.flatMap(([ids, title, description]) => {
  const value = guide(title, description);
  return ids.map(id => [id, value]);
}));

const fieldGroups = {
  "draft-form": {
    topic: guide("세부 주제", "단원보다 구체적인 주제가 있으면 적으세요. 비워두면 선택한 단원 또는 출제 요구를 사용합니다."),
    authoring_guidance: guide("출제 설명", "어떤 상황을 다루고 무엇을 묻고 싶은지 평소 말하듯 적으세요. 피하고 싶은 내용도 적을 수 있습니다. 고른 난이도·자료 형식과 맞는지 함께 확인하세요."),
    curriculum_large_unit_key: guide("대단원", "출제할 대단원을 고르세요. 대단원을 바꾸면 중단원과 소단원도 원하는 범위가 맞는지 다시 확인해주세요."),
    curriculum_middle_unit_key: guide("중단원", "고른 대단원 안에서 출제할 중단원을 선택하세요. 원하는 단원이 없다면 대단원 선택이 맞는지 먼저 확인해주세요."),
    curriculum_small_unit_key: guide("소단원", "출제 범위를 더 좁히고 싶다면 소단원을 고르세요. 선택할 소단원이 없다면 위에서 고른 대단원·중단원을 확인해주세요."),
    item_format: guide("문항 유형", "현재는 선택지 다섯 개의 객관식 문항을 만듭니다."),
    task_type: guide("주로 무엇을 묻나요?", "계산이 중심인지, 개념 이해가 중심인지, 표나 그림을 읽는 것이 중심인지 골라주세요. 만들고 싶은 문항에 가장 가까운 것을 선택하면 됩니다."),
    difficulty: guide("난이도", "만들고 싶은 문항의 난이도를 하·중·상 중에서 고르세요. 완성된 문항을 읽어보고 학생들에게 적절한 난이도인지 다시 확인해주세요."),
    variation_axis: guide("기출을 어떻게 바꿀까요?", "원래 문제의 핵심 개념은 살리면서 상황·난이도·선지 등을 어떻게 바꿀지 고르세요. 원래 기출은 남고, 변형한 새 문항이 만들어집니다."),
    material_form: guide("표·그림 등 자료 형식", "표·그림·글 중 문항에 필요한 자료를 고릅니다. 표만 있는 문항도 괜찮습니다. 그림이 꼭 필요하지 않다면 억지로 넣을 필요는 없습니다."),
    material_panel_count: guide("자료 개수", "자료를 하나로 할지, 두 부분으로 할지 고르세요. 그림 하나에는 (가)·(나)를 붙이지 않고, 자료 둘을 구별해야 할 때 나눠 표시합니다."),
    image_supporting_data: guide("그림 옆에 다른 자료도 둘까요?", "그림과 함께 표나 글 자료도 필요한지 고르세요. 그림만으로 충분하다면 다른 자료를 추가하지 않아도 됩니다."),
  },
  "operator-create-form": {
    "operator-create-role": guide("사용할 수 있는 기능", "직원이 조회·출제·검토·편집·관리 중 어떤 일을 할지 고르세요. 관리 기능은 필요한 사람에게만 허용해주세요."),
  },
  "pdf-review-form": {
    preset_key: guide("문서 유형", "올린 자료가 N제·주간지·모의고사 중 무엇인지 고르세요. 유형에 맞는 기본 기준으로 검토합니다. 따로 확인할 내용은 추가 설명에 적어주세요."),
    additional_guidance: guide("특히 확인할 부분", "기본 검토 외에 더 신경 써야 할 부분을 적으세요. 예를 들어 ‘정답과 해설이 맞는지 자세히 봐주세요’ 또는 ‘단위와 오탈자를 확인해주세요’처럼 쓰면 됩니다."),
  },
  "support-form": {
    category: guide("어떤 문의인가요?", "사용법이 궁금한지, 오류가 난 것인지 등 상황에 맞게 고르세요. 어느 화면에서 생긴 일인지도 문의 내용에 적어주세요."),
    subject: guide("문의 제목", "무엇이 궁금하거나 안 되는지 짧게 적으세요. 예를 들어 ‘자료 검토 파일이 올라가지 않아요’처럼 쓰면 됩니다."),
    question: guide("문의 내용", "어느 화면에서 무엇을 눌렀고 어떤 결과가 나왔는지 적으세요. 화면에 문의 번호가 보이면 함께 적어주세요. 비밀번호는 넣지 마세요."),
    stable_error_code: guide("화면에 나온 오류 코드", "오류 안내에 영문 코드가 보이면 그대로 옮겨 적으세요. 모르겠으면 비워두셔도 됩니다. 대신 어떤 문제가 생겼는지 설명해주세요."),
  },
  "explorer-form": {
    entity: guide("찾을 기록 종류", "문항 제작·완성 문항·파일 제작 중 어떤 기록을 찾을지 고르세요. 종류를 고른 다음 상태와 기간으로 더 좁힐 수 있습니다."),
    exact_id: guide("작업 번호로 찾기", "알고 있는 작업 번호가 있으면 입력하세요. 번호를 모르면 비워두고 기록 종류·상태·기간으로 찾을 수 있습니다."),
    status: guide("진행 상태로 찾기", "진행 중·완료·실패 등 보고 싶은 상태를 고르세요. 예전에 실패한 기록과 지금 진행에 문제가 있는 작업은 구별해주세요."),
    date_from: guide("조회 시작일", "언제부터의 기록을 볼지 정하세요. 화면의 날짜와 시간은 한국 시간으로 표시됩니다. 종료일도 함께 확인해주세요."),
    date_to: guide("조회 기간", "확인할 기간의 끝 시각을 지정합니다. 시작 시각보다 앞선 값을 넣지 마세요."),
    sort: guide("목록 정렬", "최근·오래된 생성 또는 변경 순으로 정렬합니다. 정렬을 바꾸어도 원본 기록과 생성 순서는 바뀌지 않습니다."),
    limit: guide("한 번에 표시할 수", "목록에서 한 번에 가져올 기록 수를 지정합니다. 다음 페이지로 이어서 조회할 수 있습니다."),
  },
  "quality-observation-form": {
    preview_checked: guide("미리보기를 읽었나요?", "화면에서 문제·선지·해설을 직접 읽어본 뒤 체크하세요. 버튼을 누르기만 하거나 다른 문항을 본 것은 확인으로 표시하지 않습니다."),
    hwpx_checked: guide("한글 파일을 확인했나요?", "평가할 한글 파일을 열어 그림·표·수식과 배치를 확인한 뒤 체크하세요. 파일을 내려받기만 했다면 아직 확인한 것이 아닙니다."),
    evidence_checked: guide("참고 자료를 확인했나요?", "이 문항이 참고한 자료를 읽고 관련 있는 내용인지 확인한 뒤 체크하세요. 문제의 조건이나 개념과 맞는지도 살펴보세요."),
    science_score: guide("과학적으로 맞나요?", "문제·조건·수치·단위·해설이 과학적으로 맞는지 1점부터 5점까지 평가해주세요. 틀린 곳이 있으면 의견에도 적어주세요."),
    evidence_score: guide("참고 자료가 적절한가요?", "문항이 참고한 자료가 문제의 내용과 실제로 관련 있는지 1점부터 5점까지 평가해주세요. 관련이 약한 부분은 의견에 남겨주세요."),
    authoring_value_score: guide("좋은 평가 문항인가요?", "학생이 무엇을 알아야 풀 수 있는지 분명하고 의미 있는 사고를 요구하는지 평가해주세요. 단순히 표현만 바꾼 문항인지도 살펴보세요."),
    explanation_quality_score: guide("해설이 충분한가요?", "풀이 과정과 각 선지가 맞거나 틀린 이유를 학생이 이해할 수 있는지 평가해주세요. 빠진 설명이나 문제와 다른 내용도 확인하세요."),
    visual_score: guide("그림과 표가 맞나요?", "그림·표의 글자와 수치가 문제 내용과 맞는지 평가해주세요. 그림과 표가 없는 문항이면 해당 없음으로 표시하고 이유를 적으세요."),
    unique_answer: guide("정답이 하나인가요?", "주어진 조건으로 정답을 하나만 고를 수 있는지 확인하세요. 답이 여러 개이거나 조건이 애매하면 그에 맞는 항목을 선택해주세요."),
    disposition: guide("얼마나 고쳐야 하나요?", "그대로 쓸 수 있는지, 조금 고치면 되는지, 크게 고쳐야 하는지, 쓰기 어려운지 고르세요. 실제 사용 가능성을 기준으로 판단해주세요."),
    edit_minutes: guide("수정에 몇 분 걸렸나요?", "문항을 사용할 수 있도록 고치는 데 직접 쓴 시간을 분으로 적으세요. 시스템이 답변이나 파일을 만드는 동안 기다린 시간은 빼주세요."),
    critical_error: guide("그대로 쓰면 안 되는 오류", "정답이 틀리거나 중요한 조건·그림에 오류가 있으면 체크하세요. 다른 점수가 높더라도 이런 오류를 그대로 넘어가지는 않습니다."),
    visual_not_applicable_reason: guide("그림·표를 평가하지 않은 이유", "예를 들어 ‘그림과 표가 없는 문항’처럼 시각 자료를 평가하지 않은 이유를 적으세요. 자료가 있는데 확인하지 않은 경우와 구별해주세요."),
    short_reason: guide("평가 의견", "왜 이런 점수와 수정 판단을 내렸는지 적으세요. 잘된 점과 고쳐야 할 부분을 구체적으로 남기면 다음 개선에 도움이 됩니다."),
  },
};
const fields = new Map(Object.entries(fieldGroups).map(([id, entries]) => [id, new Map(Object.entries(entries))]));
const formActions = new Map(Object.entries({
  "operator-create-form": controls.get("operator-create-username"),
  "chat-knowledge-exam-form": guide("시험 문항 찾기", "입력한 시험 연도·월·학년으로 기출을 찾습니다. 문항 번호까지 입력하면 해당 문제로 좁힐 수 있습니다. 새 문항을 만들지는 않습니다."),
  "item-db-form": guide("문항 검색", "문항 종류와 조건을 골라 찾습니다. 기출도 이 화면에서 시험 연도·월·문항 번호로 찾을 수 있습니다."),
  "explorer-form": guide("기록 찾기", "입력한 종류·상태·기간으로 기록을 찾아봅니다. 조회만 하는 버튼이며, 진행 상태나 문항 내용을 바꾸지 않습니다."),
  "quality-observation-form": guide("평가 저장", "현재 문항에 남긴 점수·수정 의견·걸린 시간을 저장합니다. 평가 기록을 남기는 기능이며, 문항 최종 승인 버튼은 아닙니다."),
}));
const lists = new Map(Object.entries({
  "material-learning-runs": guide("올린 자료 진행 확인", "접수한 자료가 어디까지 처리됐는지 봅니다. 상세 보기를 누르면 단계별 진행 상태를 확인할 수 있습니다. 완료 표시와 원본 확인이 필요한 상태는 구분해서 보세요."),
  "material-learning-detail": guide("학습 상세와 오류 확인", "처리 단계와 원문 확인이 필요한 위치를 봅니다. 일시 정지는 시작된 작업까지 마친 뒤 멈추고, 다시 처리는 오류 난 부분만 이어갑니다. 완료한 내용은 보존됩니다."),
  "excel-output-list": guide("기존 조립과 출력 활용", "저장한 문항 목록을 Excel에 가져오거나 한글 파일을 확인합니다. 가져오기 뒤에는 배치 저장을 눌러야 사용 이력에 반영됩니다. 목록에서 삭제해도 원래 문항과 이미 만든 파일은 보존됩니다."),
  "item-db-quick-result": guide("간편 출력 결과", "요청한 한글 합본의 진행 상태와 다운로드를 확인합니다. 상태를 다시 확인하는 것은 새 제작 요청이 아닙니다. 이전 출력은 Excel의 ‘기존 조립·간편 출력’에서도 찾을 수 있습니다."),
  "item-db-similarity-history": guide("이전 검색 다시 보기", "최근에 실행한 검색을 열어 저장된 결과를 확인합니다. 완료된 결과를 다시 보는 것만으로 새 계산을 시작하지 않습니다."),
  "map-layer-controls": guide("자료 종류별 연결", "교과서·기출·창작·외부·AI 중 보고 싶은 자료 종류를 고르세요. 선택한 종류와 연결된 개념을 보여주며, 자료나 연결 자체를 지우지는 않습니다."),
  "work-inbox": guide("이어 할 작업", "선택한 작업의 현재 상태에 맞는 화면으로 이동합니다. 같은 제작을 다시 시작하지 않고 기존 작업에서 이어갑니다."),
  "chat-conversations": guide("이전 대화 열기", "목록에서 대화를 골라 이전 질문과 답변을 다시 읽습니다. 새 대화를 만드는 버튼과 구별하세요. 다른 사람의 개인 기록을 열어주는 기능은 아닙니다."),
  "chat-knowledge-results": guide("참고할 문항 선택", "검색된 문항을 확인하고 필요한 것을 대화에 붙입니다. 검색 목록을 본 것과 답변이 실제로 참고한 것은 다르므로 답변 아래의 참고 자료도 확인하세요."),
  "chat-knowledge-selected": guide("첨부에서 빼기", "다음 질문에 참고할 문항에서 제외합니다. 원래 문항이나 이전 답변은 삭제되지 않습니다. 다시 필요하면 검색해 첨부할 수 있습니다."),
  "item-db-results": guide("찾은 문항 활용", "왼쪽 목록에서 문항을 고르면 오른쪽에 자세한 정보가 나옵니다. 기출은 변형에 쓸 수 있고, 고른 문항은 간편 출력하거나 Excel의 교재·회차에 배치할 수 있습니다."),
  "pdf-review-list": guide("검토 결과 열기", "목록에서 검토를 골라 진행 상황이나 검토 결과를 봅니다. 문제지·해설지의 페이지와 발견한 내용을 확인할 수 있습니다. 다시 검토를 시작하는 버튼은 아닙니다."),
  "pdf-review-findings": guide("어디를 고쳐야 하나요?", "검토에서 찾은 내용과 문서 속 위치를 함께 확인합니다. 한글 문서에서 수정 가능한 항목은 골라서 새 수정 파일로 만들 수 있습니다."),
  "support-list": guide("문의 답변 보기", "남긴 문의의 처리 상태와 답변을 확인합니다. 답변을 받았더라도 실제 오류가 수정되었는지는 안내 내용을 읽고 확인해주세요."),
  "quality-item-list": guide("평가할 문항 선택", "시험지에서 평가할 문항을 고릅니다. 문제·해설과 한글 파일, 참고 자료를 확인한 뒤 점수와 의견을 남겨주세요."),
}));
const disclosure = guide("상세 정보 펼치기", "클릭하거나 Enter 키로 접혀 있는 상세 정보를 열고 닫습니다. 펼치기 자체가 제작·승인·삭제를 실행하지는 않습니다.");
const source = guide("답변의 참고 자료", "답변이 참고한 문항이나 교과서·기출 자료를 확인합니다. 자료를 정리한 설명을 참고한 것과 원본 페이지나 그림을 직접 확인한 것은 구분해주세요.");
const documentRole = guide("문제지·해설지 전환", "현재 검토에 연결된 문제지와 해설지를 전환합니다. 별도 해설지가 없으면 해당 문서는 표시할 수 없습니다.");
// These are copy lookup keys, never permission grants or authorization checks.
const actions = new Map(Object.entries({
  "operator:assign_role": guide("사용할 기능 추가", "이 직원이 사용할 수 있는 기능을 추가합니다. 조회·출제·검토·편집·관리 중 실제로 필요한 것만 골라주세요."),
  "operator:revoke_role": guide("사용할 기능 해제", "이 직원이 더 이상 사용하지 않을 기능을 해제합니다. 이유를 남겨주세요. 계정 자체가 삭제되는 것은 아닙니다."),
  "operator:disable": guide("계정 잠시 정지", "이유를 남기고 이 계정으로 시스템을 쓰지 못하게 합니다. 영구 삭제는 아니므로 관리자가 나중에 다시 사용할 수 있게 할 수 있습니다."),
  "operator:enable": guide("계정 다시 사용", "사용을 정지했던 계정을 다시 쓸 수 있게 합니다. 새 계정을 만드는 것이 아니며, 사용할 수 있는 다른 기능이 자동으로 추가되지는 않습니다."),
  "operator:revoke_sessions": guide("이 계정 모두 로그아웃", "이 계정으로 로그인한 브라우저들을 로그아웃시킵니다. 다시 사용하려면 로그인해야 합니다. 계정이나 만든 문항은 삭제되지 않습니다."),
  "operator:delete": guide("계정 영구 삭제", "확인 후 이 계정의 로그인 정보를 영구 삭제합니다. 로그인 정보는 되살릴 수 없습니다. 만든 문항과 이전 작업 기록은 남습니다. 잠시 사용을 막으려면 계정 정지를 이용하세요."),
}));

export function resolveGuideTarget(target) {
  if (!(target instanceof Element)) return null;
  const element = target.closest('button, a, input, select, textarea, summary, [data-view-target], .status-badge');
  if (!element || element.closest('[hidden], [inert], [aria-hidden="true"]') || !element.getClientRects().length) return null;
  let value = controls.get(element.id) || actions.get(element.dataset.guideKey) || views.get(element.dataset.viewTarget);
  const form = element.closest("form");
  if (!value && form) {
    value = fields.get(form.id)?.get(element.getAttribute("name"));
    if (!value && element.matches('button[type="submit"]')) value = formActions.get(form.id);
  }
  if (!value && element.classList.contains("chat-source-link")) value = source;
  if (!value && element.dataset.documentRole) value = documentRole;
  if (!value && element.tagName === "SUMMARY") value = controls.get(element.parentElement.id) || disclosure;
  for (let parent = element.parentElement; !value && parent; parent = parent.parentElement) value = lists.get(parent.id);
  if (!value) value = views.get(element.closest("[data-view]")?.dataset.view);
  return value ? {element, ...value} : null;
}
