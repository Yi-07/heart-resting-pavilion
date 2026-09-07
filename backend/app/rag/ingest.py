"""ingest 脚本:语料 jsonl → Chroma 混合知识库(docs/data-contract.md §5 机器归本项目)。

用法(backend/ 下):
    uv run python -m app.rag.ingest                    # 重灌 case(全量)+ knowledge(种子) 两库
    uv run python -m app.rag.ingest --reset            # 清空两库重建(--reset 必须,换模型/维度时)
    uv run python -m app.rag.ingest --library case     # 只灌 case 库
    uv run python -m app.rag.ingest --library knowledge # 只灌 knowledge 库
    uv run python -m app.rag.ingest 新案例.jsonl        # 用自定义 case 语料(覆盖 config.RAG_CORPUS_PATH)
换模型(bge-small→bge-m3)后维度 512→1024,必须 --reset;全量语料单批超 chroma 上限,
ingest 内已分批 upsert(engine._UPSERT_BATCH)。样本回验三判据见 docs/data-contract.md §4。
"""

import argparse
from pathlib import Path

from app import config
from app.rag.corpus import RagLibrary, load_corpus
from app.rag.engine import get_engine


def _corpus_and_library(library: RagLibrary, case_override: Path | None) -> tuple[Path, RagLibrary]:
    """按库取语料路径;case 可由位置参数覆盖(换案例语料的旧用法),knowledge 走配置路径。"""
    if library is RagLibrary.CASE:
        return (case_override or Path(config.RAG_CORPUS_PATH)), RagLibrary.CASE
    return Path(config.RAG_KNOWLEDGE_CORPUS_PATH), RagLibrary.KNOWLEDGE


def main() -> None:
    parser = argparse.ArgumentParser(description="语料灌 Chroma 混合知识库")
    parser.add_argument(
        "corpus",
        nargs="?",
        default=None,
        help="jsonl 路径(覆盖 case 语料 config.RAG_CORPUS_PATH;默认不用此参数)",
    )
    parser.add_argument(
        "--library",
        choices=[lib.value for lib in RagLibrary],
        default=None,
        help="只灌指定库(默认省略=case+knowledge 两库都灌)",
    )
    parser.add_argument("--reset", action="store_true", help="清空目标库后重建")
    args = parser.parse_args()

    case_override = Path(args.corpus) if args.corpus else None
    targets = (
        [RagLibrary(args.library)]
        if args.library
        else [RagLibrary.CASE, RagLibrary.KNOWLEDGE]
    )
    engine = get_engine()
    for library in targets:
        path, library = _corpus_and_library(library, case_override)
        refs = load_corpus(path)
        count = engine.ingest(refs, library=library, reset=args.reset)
        print(f"ingest 完成: {library.value} ← {path} → {count} 条(.rag_store/)")

        # 自检:该库首个问题检索应命中自身(回验判据 2 的快照)
        if refs:
            top = engine.retrieve(refs[0].question, k=3, library=library)
            hits = ", ".join(f"{r.id}({r.score:.2f})" for r in top) or "无命中"
            print(f"自检 [{library.value}|{refs[0].question}] → {hits}")


if __name__ == "__main__":
    main()
