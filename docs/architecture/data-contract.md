# 数据契约 · 队友数据集对接

> **范围**:数据生产者(队友)≠消费者(本项目)的数据接口——交付物、字段、样本回验、治理。RAG 机器(ingest 脚本/Chroma collection/embedding/检索)全部归本项目(backend-plan §2 rag 行),队友只交付数据文件。

## 1. 数据集清单

| 数据集 | 生产者→消费者 | 交付物 |
|---|---|---|
| 心理知识问答对语料 | 队友 → rag 模块(ingest 灌 Chroma) | 语料文件,格式见 §2 |
| 检索测试用例 | 队友 → 验收与检索评估 | 用例文件,格式见 §3 |

## 2. 语料字段

建议格式(种子语料同款;队友照此交付则适配为零):jsonl,UTF-8,一行一条。

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| id | string | ✓ | 全集唯一且稳定,测试用例与审计靠它引用 |
| question | string | ✓ | 问题文本,进检索与生成上下文 |
| answer | string | ✓ | 回答文本,进生成上下文 |
| category | string \| null | | 可选,评估分组用 |

入库要求(无论队友格式为何):能映射到上表四字段 · id 唯一稳定 · UTF-8。语料格式与 embedding 无关:换模型由我方重跑 ingest,不影响交付。种子语料起草流程与文件路径单源=docs/guides/option.md,格式同本表。

[待回填] 队友实际格式说明与字段映射——格式说明与 50 条样本到手后填;若与建议格式一致,映射记"零"。

## 3. 测试用例字段

jsonl,一行一条:`{"id": string, "query": string, "expect_ref_id": string}`——query 检索应命中 expect_ref_id 指向的语料条目。链路级用例不在此另定,复用 docs/tests/acceptance-v1.md §1 简单用例。

## 4. 样本回验(全量灌库之前,必经)

队友先交 50 条样本,我方跑 ingest 与检索,三判据全过才收全量:

1. ingest 零报错,id 无重复
2. 样本内 question 检索 top-3 命中自身或同 category 的比例 ≥80%
3. acceptance-v1 §1.1 answer 简单用例跑通,不因语料格式崩

由我方执行(机器在本仓库),时机卡在队友全量产出之前。

## 5. 治理

- 机器(ingest 脚本/Chroma collection/embedding 选型)归本项目,队友不碰
- 队友变更数据内容:重交文件,重走 §4 回验
- 字段格式变更:双方协商改本文档,再动数据
