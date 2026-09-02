"""rag:检索三件套(职责表见 backend-plan §2;数据对接见 docs/data-contract.md)。"""

from .corpus import Ref, load_corpus
from .engine import RagEngine, get_engine

__all__ = ["RagEngine", "Ref", "get_engine", "load_corpus"]
