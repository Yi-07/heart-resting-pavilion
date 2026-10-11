"""记忆模块对外门面:单例 Memory(热/温 Redis + 冷 SQLite,store.py 见层设计与降级)
与单例 SemanticMemory(.mem_store Chroma,semantic.py 见检索笔记与状态闭环)。

网关按 `from app import memory` 后 `memory.record_mood(...)` 使用;测试 monkeypatch
本模块属性即可替身。SQLite/redis 均轻初始化,不违背懒加载分层(网关启动零模型成本);
SemanticMemory 更轻(只存路径,chroma/embedder 首次读写才加载)。
"""

from app import config
from app.memory.semantic import SemanticMemory
from app.memory.store import Memory

_memory: Memory | None = None
_semantic: SemanticMemory | None = None


def get_memory() -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory


def get_semantic() -> SemanticMemory:
    global _semantic
    if _semantic is None:
        _semantic = SemanticMemory(config.SEMANTIC_MEM_STORE_PATH)
    return _semantic


def reset_memory(memory: Memory | None = None, semantic: SemanticMemory | None = None) -> None:
    """测试隔离:换实例或清空。"""

    global _memory, _semantic
    _memory = memory
    _semantic = semantic
