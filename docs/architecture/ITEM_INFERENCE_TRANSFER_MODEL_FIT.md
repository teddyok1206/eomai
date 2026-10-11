# 착상 비교 입력 길이에 맞는 로컬 모델 보완

상태: 2026-10-11 10:15 UTC. 실제 E5 실패 측정을 바탕으로 한 구현 설계와 모델
acquisition/admission 기록이다. BGE 추론·품질 PASS가 아니며 원문과 이전 실행은 보존한다.

## 필요한 이유와 보존할 범위

원래 520개/4 query/3-view 실험에서 착상 표현 517개가 E5의 512-token 한도를
넘었다. 최대 1,330, 중간값 844토큰이며 공통 pool 3개에 선택 query는 없었다.
결과는 INSUFFICIENT_ENCODING_COVERAGE, embedding forward 0이다.
[실제 검증 기록](ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md)의 원래 request/result/
모델/실패 및 게시 key를 보존한다. 먼저 같은 key의 게시만 복구하며, 게시 성공을
MEASURED나 이전 owner 실행 성공으로 바꾸지 않는다.

내용을 요약·절단하거나 실패한 모델의 한도 pin을 바꾸지 않는다. 기존
`LocalEmbeddingModelSpec`와 generic offline backend가 이미 지원하는 BGE-M3 dense
recipe를 사용해 같은 원문·profile·metadata·Graph baseline을 비교한다. 새 벡터 DB,
ANN, 검색 엔진, queue, GPU 경로, FlagEmbedding dependency, GUI, 사람 평가를 만들지 않는다.
모델 변경은 명시적인 successor experiment/execution이며 원래 실행의 retry가 아니다.

## 짧은 설계 절차

1. **책임/경계:** 기존 모델 acquisition/보호 snapshot 입장 경계와 고정 CPU adapter에
   두 번째 실제 모델의 resource profile을 추가한다. Catalog 인가와 Orchestrator
   staging·결과 검증·게시가 계속 유일한 자료/실행 소유자다.
2. **정본:** 원래 accepted 보고서·문항 및 pin된 Graph/policy가 정본이다. upstream
   exact commit의 안전한 모델 파일과 local manifest는 embedding recipe의 근거다.
   벡터·순위는 파생물이고 source나 사람 label을 대체하지 않는다.
3. **entity/revision:** E5 logical model/revision은 보존한다. BGE에 별도 model/revision,
   request hash, experiment/revision/execution을 사용한다. 같은 모집단/profile/query
   hash와 recipe를 대조하고 resource/batch 변경을 새 request에 명시한다.
4. **pointer/check:** 모델 member별 path/media/byte bound/raw SHA, manifest hash,
   root 보호·FD identity·symlink/hardlink/쓰기 권한과 exact runtime package version을
   확인한다. 현재 사용자 권한·source lifecycle 및 header/index도 다시 확인한다.
   PR·main·변환된 weights를 서로 같은 release로 표현하지 않는다.
5. **access pattern:** 모델/revision keyed lookup, allowlisted file membership, immutable
   model admission, ordered whole-population encode, bounded exact vector scan이다.
6. **구조/index:** 기존 frozen model spec·manifest, fixed resource-profile lookup 및
   ordered hash/file 목록을 재사용한다. DB schema/index와 wire contract는 변경하지 않는다.
   resource profile은 검토된 두 고정 값만 허용하고 arbitrary unit/command override는 없다.
7. **규모/복잡도:** 최대 1,024 profiles·4 query·세 view, exact O(Nd) 순위를 유지한다.
   acquisition/검증은 파일 bytes에 선형, 임베딩은 기존 batch 처리다. 모델 weights는
   2,271,064,456 bytes여서 이전 2 GiB ceiling으로 적합성을 주장할 수 없다.
8. **transaction/concurrency:** 기존 claim/marker/CPU isolation/publication idempotency를
   유지한다. 새 모델은 새 successor input으로 한 번 명시 실행하며, unknown 종료에서
   retry하지 않는다. 모델 입장은 no-clobber이고 이전 설치/terminal 이력을 지우지 않는다.
9. **dependency/adapter:** contracts와 pure projection은 그대로다. optional transformers
   adapter와 고정 systemd/보호 filesystem adapter만 다룬다. 기존 torch/transformers/
   safetensors/tokenizers를 사용하며 외부 LLM API·remote code·pickle 로딩을 하지 않는다.
10. **failure/retry:** 모델 file/hash/형식·runtime·resource·token coverage 불일치는 명시적으로
    거부한다. tokenizer만 성공하거나 unit exit 0이어도 MEASURED로 판단하지 않는다.
    failed/INSUFFICIENT 결과는 보존하고 실패를 성공으로 바꾸지 않는다.
11. **더 단순한 대안:** E5-base도 512-token 모델이어서 현재 overflow를 해결하지 못한다.
    잘라내거나 최소 common pool 조건을 낮추면 조건·추론 보존 또는 비교 의미가 달라진다.
    이미 지원된 긴 입력 모델을 입장시키는 것이 새 chunk/aggregation 계약보다 작다.

## 안전한 고정 모델 후보 — 설치 전 조사

[공식 모델 설명](https://huggingface.co/BAAI/bge-m3)은 MIT, 1024차원, CLS dense 표현과
8192-token 입력을 설명한다. 현재 main `5617a9f61b028005a4858fdac845db406aefb181`에는
`model.safetensors`가 없다. unsafe pickle weights를 다운로드·변환·로드하지 않는다.

검토한 안전 형식 후보는 [공식 저장소 PR #130](https://huggingface.co/BAAI/bge-m3/discussions/130)의
SFconvertbot commit `9a0624b896d81da7492a910ffa53731274b6cf3d`다. 부모는 위 main이며,
main 대비 변경은 safetensors 추가 하나뿐이다. **미병합 변환 기여의 고정 실험 후보**이고
BAAI maintainer 승인 릴리스나 EOM 품질 검증으로 표현하지 않는다.
[고정 revision metadata](https://huggingface.co/api/models/BAAI/bge-m3/revision/9a0624b896d81da7492a910ffa53731274b6cf3d?blobs=true)를
통해 다음 기대값을 확인했다. 실제 acquired bytes도 별도로 재검증해야 한다.

| member | bytes | raw SHA-256 |
|---|---:|---|
| config.json | 687 | `26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa` |
| model.safetensors | 2,271,064,456 | `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e` |
| tokenizer.json | 17,098,108 | `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08` |
| tokenizer_config.json | 444 | `a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4` |
| special_tokens_map.json | 964 | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` |
| sentencepiece.bpe.model | 5,069,051 | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| 1_Pooling/config.json | 191 | `e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352` |

최초 실험 후보는 maximum_tokens 2048, CLS/L2/float32, empty symmetric prefix,
REJECT_OVERFLOW다. 모델의 physical ceiling 8192를 모든 실험의 입력 예산으로 쓰지 않는다.
BGE tokenizer로 같은 520개를 측정하기 전에는 전 corpus fit을 주장하지 않는다.

## 실행 순서와 exit 증거

1. 실제 INSUFFICIENT 결과의 동일-key 게시 복구. CPU 재호출 0, fresh PREPARE/전체
   AUTHORIZE, exact member/timestamp/source commit과 기존 Job identity 대조.
2. 기존 E5/runtime/unit 이력을 유지한 model-only no-clobber admission을 검증한다.
   developer-owned prefix와 CPU history 없음이 전제인 전체 installer는 재실행하지 않는다.
3. BGE 전용 고정 CPU resource profile 후보는 MemoryMax 6 GiB, batch 1/threads 4,
   CPUQuota 400%, TimeoutStartSec 1800, Restart no다. 이전 E5의 2 GiB template,
   launcher default와 probe는 유지한다. 공통 prepare/handoff/stdio는 재사용한다.
   임의 drop-in·unit·권한 확대 없이 exact template/hash와 기존 polkit scope를 검증한다.
4. 보호 model snapshot 및 load/tokenization/RSS/time 검증을 수행한다. resource ceiling
   안에서 확인된 뒤 같은 520/4-query/3-view의 successor CPU experiment를 명시 실행한다.
   현재 runtime이 model-agnostic이라는 소스 사실을 실제 모델 load PASS로 확대하지 않는다.
5. MEASURED, encoded text count, ordered candidates, source/model/recipe/hash와 기존 Graph
   baseline을 정본 Artifact로 확인한다. 이후 기존 V11 owner를 통해 최대 두 쌍의
   CONCEPT/MATERIAL/CRUX 설명·조건/추론 대응·차이·추가 추론과 같은-key replay를 검증한다.
6. 원래 설계 요구별 코드/계약/실제 결과/미평가 한계를 다시 대조한다. 사람 평가를
   다시 필수로 만들거나 label 없는 정확도·교육 효과를 주장하지 않는다.

### 실제 acquisition 관측 — 2026-10-11 10:03:44 UTC

새 eom-owned 0700 임시 store에서 보호 CPU Conda interpreter를 **비root**로 사용해
위 고정 revision의 7개 파일을 다운로드했다. 각 raw SHA/byte bound 검증과 manifest
작성 완료, process exit 0을 확인했다. 기존 runtime은 수정하지 않았다. 실제 설치된
runtime metadata는 safetensors 0.6.2, tokenizers 0.22.2, torch 2.7.1+cpu,
transformers 4.56.2이며 manifest의 exact pin과 일치한다.

- Model: embeddingmodel_c7e50dd14186df98c6cef9a6038f7620.
- Revision: embeddingmodelrev_32de764c92823791bc6ba4f35fffedd9.
- Manifest semantic SHA: 8a6ba60474188d7f1d47a683f56c40b2de06f1aed9f5c914259db0dac8544297.
- Manifest raw SHA: 3b35bc21e7cd49050b2b2cc0060ffc477ce30e3bddbe0703365344730037a4a5,
  1,781 bytes. 이 값은 developer manifest를 권한 증거로 신뢰한다는 뜻이 아니다.

### 실제 model-only admission — 2026-10-11 10:12 UTC

고정 helper SHA fb8db49658483c0efcc325b0c4c8f150234ec51b2c2893066bf42c104e1180bb를
root 소유 0400 leaf로 보존하고 보호 CPU interpreter -I -S -B에서 model-only
경계만 실행했다. exact 7-member raw pins와 독립 생성 manifest를 확인한 no-clobber
입장은 PASS다. model/revision은 위와 같고 기존 CPU runtime/E5/unit history는
변경하지 않았다. fresh acquisition/admission 관련 7 suite 356 PASS, strict 6파일과
Ruff/format/diff PASS를 별도 source 증거로 기록한다.

BGE resource unit/polkit 설치·load/forward·실제 token fit·성능·successor CPU·pair
실행은 미실행이며 production activation도 하지 않았다. 합성 입력의 짧음/중간/긴
부하를 먼저 동일 고정 CPU adapter에서 측정해 6 GiB/1800초 예산 적합성을 확인한다.
