"""语料对象与加载(docs/data-contract.md §2:jsonl → 四字段)。"""

import json
from pathlib import Path

from pydantic import BaseModel


class Ref(BaseModel):
    id: str
    question: str
    answer: str
    score: float = 0.0  # ingest 侧恒 0;retrieve 返回时带打分
    category: str | None = None


def load_corpus(path: Path | str) -> list[Ref]:
    """读 jsonl 语料;校验 id 全集唯一(测试用例与审计靠 id 引用)。"""
    refs: list[Ref] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        refs.append(Ref.model_validate(json.loads(line)))
    ids = [r.id for r in refs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"语料 id 重复: {sorted(dupes)}")
    return refs
