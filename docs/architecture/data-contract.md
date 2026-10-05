# 数据契约 · RAG 语料资产

> **范围**：RAG 语料资产的清单、schema 与变更流程——案例库与科普知识库两个库的数据面。RAG 机器（ingest 脚本、Chroma collection、embedding 选型）全部归本项目（backend-plan「模块职责表」rag 行），队友只交付数据文件。

## 1. 数据资产清单

| 资产 | 位置 | 条数 | 来源 | 角色 |
|---|---|---|---|---|
| 案例库语料 | `backend/data/rag_corpus.jsonl` | 14944 | 队友交付（`dataset/all_base.md` 经翻译层压平，一次性脚本已删） | ingest 灌 `hrp_kb_case`，collect/station 用 |
| 科普知识库语料（已交付，未接线） | `backend/data/knowledge_generated.jsonl` | 1022 | 队友交付 | 待接线：config 灌库源改指本文件并重灌后，ingest 灌 `hrp_kb_knowledge`，answer 直答用。**接线前灌库实况见下行** |
| 科普知识库现行灌库源 | `backend/data/rag_knowledge_corpus.jsonl` | 15 | 初版自建种子 | 接线前 ingest 实际读取的路径（`backend/app/config.py` `RAG_KNOWLEDGE_CORPUS_PATH`）；知识库实况 15 条 |
| 检索钉测夹具 | `backend/data/rag_retrieve_test_seeds.jsonl` | 15 | 初版自建种子 | 仅 [test_retrieve.py](../../backend/tests/test_retrieve.py) 灌测试库，与生产语料分离。内容与现行灌库源种子相同，归并方式待定（见 backlog） |

Chroma 向量库 `backend/.rag_store/` 是运行时产物：不入 git，clone 后首次必跑灌库；两 collection 各自对应一个语料文件，条数以灌库实况为准。灌库命令与模型下载细则唯一记录处见 [option.md](../guides/option.md)「RAG 检索模型与灌库」，不在此复制。

> ⚠️ 接线现状：科普库 1022 条新语料尚未接线（config 灌库源仍指 15 条种子），知识库 Chroma 实况 15 条；接线操作（config 改指+重灌+新文件入 git）未执行，接线后本表两行并回一行。语料交付与接线动作的状态登记见 `docs/todos/backlog.md`。

## 2. 语料 schema 与两库语义

两库同 schema：jsonl、UTF-8、一行一条，四字段（`backend/app/rag/corpus.py` `Ref`）：

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| id | string | ✓ | 全集唯一且稳定，测试用例与审计靠它引用 |
| question | string | ✓ | 问题文本，进检索与生成上下文 |
| answer | string | ✓ | 回答文本，进生成上下文 |
| category | string \| null | | 可选，评估分组用 |

两库 `question`/`answer` 语义不同，是本契约的关键区分：

| 库 | question | answer | 消费方 |
|---|---|---|---|
| `hrp_kb_knowledge`（科普） | 知识问法 | 科普回答 | answer 直答（网关 `_answer_messages`） |
| `hrp_kb_case`（案例） | 来访者问题 | 治疗思路 | collect 总结与 station 方案书 |

案例语料是个案处理记录、科普语料是知识问答，语义类型不同——直答只查科普库，防止「科普」漂移成「案例建议」（演进记录见 [PRD](../prds/rag-full-corpus-bge-m3.md)）。

## 3. 入库与验证

- 灌库：`uv run python -m app.rag.ingest`（`backend/` 下）；换 embedding 模型或维度必须 `--reset` 清空重建，代码不动。
- 检索质量验证：[test_retrieve.py](../../backend/tests/test_retrieve.py) 钉测（种子命中/k 截断/双库隔离/分数降序）+ ingest 自检（每库首问检索命中自身）。
- 历史回验记录：50 条翻译验证 → 半量 7472 条检索验证（合并命中率 98.5%）→ 全量灌入，详见 [PRD](../prds/rag-full-corpus-bge-m3.md)「工具链/依赖」演进记录。

## 4. 变更流程

- 队友再交付：同 schema 重交文件 → 我方重灌对应库 → 跑钉测确认 → 完毕。
- 语料内容变更：重交文件重灌，id 保持稳定（下游引用与审计靠 id）。
- 字段格式变更：双方协商先改本契约，再动数据。
- 机器与选型（ingest 脚本/Chroma/embedding）归本项目，队友不碰。
