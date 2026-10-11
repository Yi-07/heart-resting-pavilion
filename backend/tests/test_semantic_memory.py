"""语义记忆层测试(看板 semantic-memory S6):parse_notes/读写/召回防线/治理。

不依赖真 Redis/LLM;chroma 临时库隔离(每测重建 store 目录)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.memory import reset_memory
from app.memory.semantic import SemanticMemory, parse_notes


@pytest.fixture()
def sem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SemanticMemory:
    """注入桩 embedder 的 SemanticMemory(零模型成本);chroma 库随 tmp_path 生命周期。"""

    class _StubEmbedder:
        """三维单位向量按序号指派:同组近正交,跨组反向——闸门/命中都可预测。"""

        def __init__(self) -> None:
            self._vectors = {
                "left": [1.0, 0.0, 0.0],
                "right": [-1.0, 0.0, 0.0],
                "near": [0.99, 0.141, 0.0],  # 与 left cos≈0.99(过闸),与 right≈-0.99(挡)
            }

        def encode(self, texts: list[str], *, show_progress_bar: bool = False) -> Any:
            import numpy as np

            def _pick(t: str) -> list[float]:
                for key, vec in self._vectors.items():
                    if key in t:
                        return list(vec)
                return [0.0, 1.0, 0.0]  # 默认组(与 near 组 cos=0.141,低于闸门)

            return np.asarray([_pick(t) for t in texts])

    mem = SemanticMemory(str(tmp_path / "mem_store"), embedder=_StubEmbedder())  # type: ignore[arg-type]
    reset_memory(semantic=mem)
    yield mem
    reset_memory()
    import shutil

    shutil.rmtree(tmp_path / "mem_store", ignore_errors=True)


class TestParseNotes:
    def test_valid_json(self) -> None:
        news, settled = parse_notes('{"new":["a笔记","b笔记"],"settled":["m123"]}')
        assert news == ["a笔记", "b笔记"]
        assert settled == ["m123"]

    def test_fallback_plain_text(self) -> None:
        news, settled = parse_notes("聊到工作压力,情绪低落")
        assert news == ["聊到工作压力,情绪低落"]
        assert settled == []

    def test_fallback_bad_types(self) -> None:
        news, settled = parse_notes('{"new":"不是列表","settled":"m1"}')
        assert news == ['{"new":"不是列表","settled":"m1"}'.strip()]
        assert settled == []

    def test_fallback_empty_string_item(self) -> None:
        news, settled = parse_notes('{"new":[""],"settled":[]}')
        assert news == ['{"new":[""],"settled":[]}']
        assert settled == []

    def test_settled_id_prefix_filter(self) -> None:
        _, settled = parse_notes('{"new":["n"],"settled":["m1","x99",""]}')
        assert settled == ["m1"]

    def test_json_with_fences(self) -> None:
        news, _ = parse_notes('```json\n{"new":["围栏笔记"],"settled":[]}\n```')
        assert news == ["围栏笔记"]


class TestSaveAndRecall:
    async def test_save_and_list(self, sem: SemanticMemory) -> None:
        await sem.save_notes("sess1", 0, "用户聊到工作压力,担心做不好")
        items = sem.list_items()
        assert len(items) == 1
        assert items[0]["status"] == "open"
        assert items[0]["text"] == "用户聊到工作压力,担心做不好"

    async def test_save_empty_raw_noop(self, sem: SemanticMemory) -> None:
        await sem.save_notes("sess1", 0, "")
        assert sem.list_items() == []

    async def test_recall_gate_filters_noise(self, sem: SemanticMemory) -> None:
        # 桩 embedder:含 left 的条目与含 right 的查询反向(cos<0)→ 闸门滤掉
        await sem.save_notes("s", 0, "left 条目内容")
        got = await sem.recall("right 查询内容")
        assert got == []

    async def test_recall_hits_same_group(self, sem: SemanticMemory) -> None:
        await sem.save_notes("s", 0, "left 条目内容")
        got = await sem.recall("near 查询内容")
        assert len(got) == 1
        assert got[0]["cos"] > 0.5

    async def test_recall_top_k_and_fields(self, sem: SemanticMemory) -> None:
        for i in range(5):
            await sem.save_notes("s", i, f"长度相同的一些内容文本{i}")
        got = await sem.recall("长度相同的一些内容文本", k=3)
        assert len(got) == 3
        for m in got:
            assert set(m) == {"id", "text", "cos", "status", "date", "aged"}
            assert m["status"] == "open"
            assert not m["aged"]

    async def test_save_multi_notes_metadata_aligned(self, sem: SemanticMemory) -> None:
        # 回归:LLM 返回多条笔记时 metadatas 须与 ids 数量对齐(chroma 否则整批拒)
        await sem.save_notes("s", 0, '{"new":["笔记甲","笔记乙","笔记丙"],"settled":[]}')
        items = sem.list_items()
        assert len(items) == 3
        assert all(it["status"] == "open" for it in items)
        assert all(it["date"] for it in items)

    async def test_settled_loopback(self, sem: SemanticMemory) -> None:
        await sem.save_notes("s", 0, "与室友闹矛盾,回避回宿舍")
        first = sem.list_items()[0]
        await sem.save_notes("s", 1, '{"new":["聊到和好了"],"settled":["' + first["id"] + '"]}')
        after = sem.list_items()
        target = [x for x in after if x["id"] == first["id"]]
        assert target and target[0]["status"] == "settled"

    def test_recall_sync_empty_store(self, sem: SemanticMemory) -> None:
        assert sem.recall_sync("随便什么") == []


class TestGovernance:
    async def test_delete_item(self, sem: SemanticMemory) -> None:
        await sem.save_notes("s", 0, "条目一")
        target = sem.list_items()[0]
        sem.delete_items([target["id"]])
        assert sem.list_items() == []

    def test_clear_all(self, sem: SemanticMemory) -> None:
        sem.save_notes_sync("s", 0, "条目一")
        assert sem.clear_all() >= 1
        assert sem.list_items() == []
        # 清除后仍可继续写(重建空库)
        sem.save_notes_sync("s", 1, "清除后新条目")
        assert len(sem.list_items()) == 1


class TestDegradation:
    async def test_recall_degrades_on_failure(self, tmp_path: Path) -> None:
        # 指向一个文件路径当 store:chroma 初始化失败 → recall 吞异常返回空
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x")
        mem = SemanticMemory(str(blocker))
        assert await mem.recall("查询") == []

    async def test_save_degrades_on_failure(self, tmp_path: Path) -> None:
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x")
        mem = SemanticMemory(str(blocker))
        await mem.save_notes("s", 0, "不会被写入")
        # 不抛异常即降级成功
