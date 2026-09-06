# PRD · RAG 全量语料接入 + bge-m3 换模型

> 产品需求文档。描述「把队友全量心理咨询案例语料接入 RAG + 把 embedding 从 bge-small-zh-v1.5 换成 bge-m3」的需求、方案、测试口径。契约与字段定义单源=`docs/data-contract.md`;本 PRD 只写本新增对现有管线的**改动面**。

## Problem Statement

当前 RAG 的检索语料仅有 **15 条人定稿种子**`rag_retrieve_test_seeds.jsonl`(科普问答对,如"什么是正念"),覆盖窄、召回弱。队友交付了**全量心理咨询案例语料**(14944 条,`dataset/all_base.md`),但格式是 markdown 案例块,我方管线不认、且入库需换语义。同时我方 embedding 用 `bge-small-zh-v1.5`(512 维),检索质量受限于小模型;队友库用 bge-m3(1024 维)。

**用户视角问题**:检索不到足够相关语料,导致 answer 直答/collect 总结/station 方案书引用质量受限;换更强模型可提升整体检索与生成。

## Solution

产出「翻译层 + bge-m3 + 全量接入」:**翻译层把队友 md 案例压平成我方 jsonl 四字段,改用 bge-m3 重灌全量,检索管线换模型并本地化模型资源**。消费者管线(corpus.py/retrieve/三个消费点)不动,翻译层是唯一新增适配。

## User Stories

1. 作为检索管线,我希望语料覆盖案例(而非仅 15 条种子),以便 answer/collect/station 引用到更相关内容。
2. 作为研发,我希望 embedding 用 bge-m3(强多语言 1024 维),以便检索质量优于 bge-small。
3. 作为研发,我希望模型走本地路径(不走 HF hub),以便本机脱网也能加载(reranker 同)。
4. 作为研发,我希望 `ingest` 能分批写,以便单批超 chroma 上限(5461)不崩。
5. 作为研发,我希望语料文件命名消歧(全量语料≠种子),以便不与测试夹具混淆。

## Implementation Decisions

### 翻译层(唯一新增适配;数据契约变换)

`dataset/all_base.md` → `backend/data/rag_corpus.jsonl`(14944 条),映射口径:

| jsonl 字段 | 来源 | 说明 |
| --- | --- | --- |
| `id` | 块头 `conv_xxxxx` / `deep_xxxxx` | 全局唯一(实测 0 重复) |
| `question` | deep 块「规范化问题」;conv 块「来访者问题」 | deep 优先规范化问题(更精炼、检索友好);conv 无则回退(fallback 实测 0 触发) |
| `answer` | 「治疗思路」 | |
| `category` | 一级主题头(如 `钦佩_工作`) | 实测 0 缺失 |

- 翻译脚本是**一次性产物**(原在 `.proto_tmp/`),**不入生产代码**;全量 jsonl 已生成到 `backend/data/rag_corpus.jsonl`,id 唯一。
- **语义注意**:案例语料(`question=来访者问题/answer=治疗思路`)与种子(`提问=科普问/答案=科普答`)语义类型不同——前者是个案处理记录,后者是知识问答。受影响:`answer` 直答链路(可能从"科普"漂移成"案例建议")——**已 mock 掉 answer 直答(显示"TODO 施工中"),留待后期再议**(见 kanban 待议);collect/station 链路适配良好。

### bge-m3 换模型(engine.py)

- `_EMBED_MODEL` → 本地路径 `backend/models/bge-m3/`(基于 `__file__` 的绝对路径,不依赖 cwd;不走 HF hub——本机直连不可达)。
- `_RERANK_MODEL` → 本地路径 `backend/models/bge-reranker-v2-m3/`(同源本地化)。
- `_QUERY_PREFIX` → `""`(**bge-m3 为无前缀训练**,官方 FAQ#2:不再需要 query 指令;原 bge-small 的 `为这个句子生成表示...` 前缀须删除,保留会致域偏移)。
- `_UPSERT_BATCH = 1000`:chroma 单批上限 ~5461(本环境实测),全量 14944 超限,**ingest 分批 upsert**。
- `normalize_embeddings=True` 保留(bge-m3 官方 dense=归一化 CLS,幂等无害);池化默认 CLS(官方正确);`max_seq_length` 自动 8192(ST 读 config)。
- **模型资源本地化**:bge-m3(2.2G)+ reranker(2.1G)均**curl 走 hf-mirror 下载**(huggingface_hub 1.29 走 Xet 分片在本机报 `FileMetadataError` 误判,但底层 HTTP 通;curl -sL 跟随重定向可下)。

### 语料与命名(config.py / ingest.py)

- `RAG_SEEDS_PATH` → **`RAG_CORPUS_PATH`**(消歧,指向全量 `rag_corpus.jsonl`)。
- 原 `rag_seeds.jsonl`(15 条)→ **`rag_retrieve_test_seeds.jsonl`**(git mv 保留历史;**保留作 test_retrieve.py 测试夹具**,与生产语料分离)。
- `ingest.py` default 改用 `config.RAG_CORPUS_PATH`(单源)。

### 防重复/防遗漏契约

全量唯一 id=14944。接入策略验证:
- 已选用标记 `half_stratified_ids.json`(原型"均衡一半" id 清单,7472 条,唯一 ⊆全量)。
- 全量以 **id 差集**保证零重零漏(若分批灌);本次一次性全量灌入 14944 条(非增量),补集口径记录在案。

### 工具链/依赖

- **零新增依赖**(bge-m3/bge-reranker 都是 `sentence-transformers>=6.0.0` 现有;`pyproject.toml` 已含,未加 FlagEmbedding——稠密检索无需)。
- 无需 `HF_ENDPOINT` 环境变量:模型已本地路径,不触发 hub 下载。
- 数据-contract §4 理论"50 条样本三判据回验"**真实演进**:①原型先 50 条翻译验证(0 回退)→ ②半量 7472 条检索验证(**合并命中率 98.5%**)→ ③全量 14944 条灌入。非完全照 §4 理论流程,如实记录。

## Testing Decisions

- **test_retrieve.py**:改用 bge-m3 + `rag_retrieve_test_seeds.jsonl`(测试种子)。已有断言(`什么是正念→mindfulness-01`、k 截断、分数降序、id 唯一)在 bge-m3 下**全过**(7/7,实测)。
- **半量检索验证**:均衡一半 7472 条(跨主题,178 category),抽样 200 条 query,bge-m3+reranker 端到端 → top-3 自身/同 category **合并 98.5%**(≥80% 阈值 PASS)。
- **后端回归**:ruff ✓、mypy(45 文件)✓、pytest **core 全过**(test_retrieve 7 + test_memory 6;全量其余 106 pass)。
- **环境前提**:`test_memory` 是**真链路测试**,前置=本机 Redis(6379)可用(conftest 用 FakeMemory 桩供其他测试;test_memory 直测真 Memory)。Redis 未启动时 test_memory 报 ConnectionError——**非代码问题,环境前提**。

## Out of Scope

- `answer` 直答**语义定位**(科普 vs 案例建议)——已 mock 掉,留后期待议(kankan 记录)。
- 启动 RAG warm-up 预热(bge-m3 冷启动重,answer 60s 预算冲突)——遗留。
- reranker 进一步调优 / FlagEmbedding 稀疏+ColBERT 混合检索。
- 前端设置入口(模型配置 UI)点亮。

## Further Notes

- 模型本地化资源(`backend/models/`)已被 `models/` gitignore,不入库;新克隆需经脚本/curl 重新下载 bge-m3+reranker。
- `dataset/`(队友交付)git 未跟踪、168MB,不入库;`all_base.md` 是翻译层唯一源。
- 当前 `.rag_store` 生产库 `count=14944`(bge-m3 1024 维),较原 bge-small 种子库(512 维)为新库。
