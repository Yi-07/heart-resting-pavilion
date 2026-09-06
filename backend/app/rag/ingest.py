"""ingest 脚本:语料 jsonl → Chroma(docs/data-contract.md §5 机器归本项目)。

用法(backend/ 下):
    uv run python -m app.rag.ingest               # 默认 config.RAG_CORPUS_PATH(全量语料),追加/更新
    uv run python -m app.rag.ingest --reset       # 清空重建
    uv run python -m app.rag.ingest 新语料.jsonl   # 换语料(全量替换用 --reset)
换模型(bge-small→bge-m3)后维度 512→1024,必须 --reset;全量语料单批超 chroma 上限,
ingest 内已分批 upsert(engine._UPSERT_BATCH)。样本回验三判据见 docs/data-contract.md §4。
"""

import argparse
from pathlib import Path

from app import config
from app.rag.corpus import load_corpus
from app.rag.engine import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="语料灌 Chroma")
    parser.add_argument(
        "corpus",
        nargs="?",
        default=config.RAG_CORPUS_PATH,
        help="jsonl 路径(默认 config.RAG_CORPUS_PATH)",
    )
    parser.add_argument("--reset", action="store_true", help="清空 collection 后重建")
    args = parser.parse_args()

    path = Path(args.corpus)
    refs = load_corpus(path)
    count = get_engine().ingest(refs, reset=args.reset)
    print(f"ingest 完成: {path} → {count} 条(Chroma 持久化于 .rag_store/)")

    # 自检:首个问题检索应命中自身(回验判据 2 的快照)
    if refs:
        top = get_engine().retrieve(refs[0].question, k=3)
        hits = ", ".join(f"{r.id}({r.score:.2f})" for r in top) or "无命中"
        print(f"自检 [{refs[0].question}] → {hits}")


if __name__ == "__main__":
    main()
