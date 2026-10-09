"""语料对象与加载(docs/architecture/data-contract.md「语料 schema 与两库语义」:jsonl → 四字段)。"""

import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ValidationError


class RagLibrary(str, Enum):
    """RAG 两个库(混合知识库):科普知识库(answer 直答用)与案例库(collect/station 用)。

    str 子类以 JSON/序列化友好;传参须用成员(RagLibrary.KNOWLEDGE),禁裸字符串。
    """

    KNOWLEDGE = "knowledge"
    CASE = "case"


class Ref(BaseModel):
    id: str
    question: str
    answer: str
    score: float = 0.0  # ingest 侧恒 0;retrieve 返回时带打分
    category: str | None = None


def load_corpus(path: Path | str) -> list[Ref]:
    """读 jsonl 语料;校验 id 全集唯一(测试用例与审计靠 id 引用)。"""
    refs: list[Ref] = []
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"语料 JSONL 格式错误: {source}:{line_number}: {exc.msg}"
            ) from exc
        try:
            ref = Ref.model_validate(raw)
        except ValidationError as exc:
            error_count = len(exc.errors())
            raise ValueError(
                f"语料字段校验失败: {source}:{line_number}: {error_count} 个字段错误"
            ) from exc
        if ref.id in seen_ids:
            duplicate_ids.add(ref.id)
        else:
            seen_ids.add(ref.id)
        refs.append(ref)
    if duplicate_ids:
        raise ValueError(f"语料 id 重复: {sorted(duplicate_ids)}")
    return refs
