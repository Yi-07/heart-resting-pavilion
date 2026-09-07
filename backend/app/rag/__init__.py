"""rag:检索三件套(职责表见 backend-plan §2;数据对接见 docs/data-contract.md)。

深模块:对外接口小(Ref/load_corpus/get_engine/rag.retrieve),复杂藏在 engine 内。
两库(科普知识库/案例库)由 RagLibrary 标识,调用方只传库种类,不接触 Chroma/BM25/重排。
"""

from .corpus import RagLibrary, Ref, load_corpus
from .engine import RagEngine, get_engine

__all__ = ["RagEngine", "RagLibrary", "Ref", "get_engine", "load_corpus"]
