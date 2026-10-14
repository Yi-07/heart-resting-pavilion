"""记忆模块对外门面:单例 Memory(热/温 Redis + 冷 SQLite,store.py 见层设计与降级)。

网关按 `from app import memory` 后 `memory.record_mood(...)` 使用;测试 monkeypatch
本模块属性即可替身。SQLite/redis 均轻初始化,不违背懒加载分层(网关启动零模型成本)。
"""

from app.memory.store import MaterialState as MaterialState
from app.memory.store import Memory
from app.memory.store import StationMaterial as StationMaterial

_memory: Memory | None = None


def get_memory() -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory


def reset_memory(memory: Memory | None = None) -> None:
    """测试隔离:换实例或清空。"""

    global _memory
    _memory = memory
