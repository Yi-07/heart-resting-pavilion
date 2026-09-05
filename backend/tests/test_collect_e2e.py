"""collect 网关 E2E(CLAUDE.md §8 用例 2 后端判据):first_frame → 粗稿 draw →
逐轮增量 draw → 精稿 draw → 分析总结 + 补给站邀请语 → done;seq 单调递增;
信念字段留白;mood_select 回合内静默;分析中抢占 → 未发帧蒸发 + 承接安抚语。
LLM 全 stub(provider 按调用方模块替换),RAG stub。"""

import asyncio
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _ScriptedProvider:
    def __init__(self, stream_delay: float = 0.0) -> None:
        self.stream_delay = stream_delay

    async def chat(self, messages: Any) -> str:
        raise AssertionError("E2E 不应调用 chat")

    async def stream(self, messages: Any):
        for part in ["这次梳理帮你看清了念头和行为的联系,", "下一步可以从小事开始。"]:
            if self.stream_delay:
                await asyncio.sleep(self.stream_delay)
            yield part

    async def chat_json(self, messages: Any, schema: type) -> Any:
        name = getattr(schema, "__name__", "")
        if name == "_ExtractOut":
            return schema(value="提炼值", off_topic=False)
        if name == "_ReviewOut":
            return schema(label="焦虑", intensity=0.8)
        if name == "_RiskOut":
            return schema(risky=False)
        raise AssertionError(f"未预期 schema: {name}")


class _RagStub:
    def retrieve(self, query: str, k: int | None = None) -> list[Any]:
        return []


def _patch(monkeypatch, provider: _ScriptedProvider) -> None:
    for target in (
        "app.agents.extract.get_provider",
        "app.agents.analysis.get_provider",
        "app.agents.graph.get_provider",
    ):
        monkeypatch.setattr(target, lambda: provider)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub())


def _recv(ws: Any) -> dict:
    return json.loads(ws.receive_text())


def _send(ws: Any, text: str) -> None:
    ws.send_text(json.dumps({"type": "user_input", "mode": "text", "text": text, "ts": 1}))


def test_collect_full_round(monkeypatch):
    _patch(monkeypatch, _ScriptedProvider())
    seqs: list[int] = []
    with client.websocket_connect("/ws") as ws:
        _send(ws, "最近很焦虑睡不着")
        first = _recv(ws)
        assert first["type"] == "first_frame" and first["route"] == "collect"
        assert first["mood_select"] is True and first["template"] == "beck_formulation"
        draft = _recv(ws)
        assert draft["type"] == "draw" and draft["data"]["emotion"]["label"] == "焦虑"
        q1 = _recv(ws)
        assert q1["type"] == "text_delta" and "愿意说说" in q1["text"]
        seqs += [draft["seq"], q1["seq"]]

        # 回合内 mood_select:静默(不回帧)——下一帧应是轮次 draw 而非 mood 应答
        ws.send_text(json.dumps({"type": "mood_select", "mood": "低落", "ts": 2}))

        _send(ws, "那天被领导当众否定了,很难受")
        d2 = _recv(ws)
        assert d2["type"] == "draw" and d2["data"]["situation"] == "提炼值"
        q2 = _recv(ws)
        assert q2["type"] == "text_delta"

        _send(ws, "我当时觉得自己什么都做不好")
        d3 = _recv(ws)
        assert d3["type"] == "draw" and d3["data"]["thought"] == "提炼值"
        q3 = _recv(ws)

        _send(ws, "我躲开了那个会")
        d4 = _recv(ws)  # 增量:behavior 入格
        assert d4["type"] == "draw"
        assert d4["data"]["behavior"] == "提炼值"
        final_draw = _recv(ws)  # 精稿:emotion 复核后全量
        assert final_draw["type"] == "draw"
        assert final_draw["data"]["intermediate_belief"] is None  # 信念留白
        assert final_draw["data"]["core_belief"] is None
        assert final_draw["data"]["emotion"]["intensity"] == 0.8  # 复核合入

        summary = _recv(ws)
        assert summary["type"] == "text_delta" and summary["final"] is True
        assert "梳理" in summary["text"]
        invite = _recv(ws)
        assert invite["type"] == "text_delta" and "心灵补给站" in invite["text"]
        done = _recv(ws)
        assert done["type"] == "done"
        seqs += [d2["seq"], q2["seq"], d3["seq"], q3["seq"], d4["seq"], final_draw["seq"],
                 summary["seq"], invite["seq"], done["seq"]]

    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # seq 单调递增


def test_collect_preempt_during_analysis(monkeypatch):
    _patch(monkeypatch, _ScriptedProvider(stream_delay=0.4))
    with client.websocket_connect("/ws") as ws:
        _send(ws, "最近很焦虑睡不着")
        for _ in range(3):
            _recv(ws)  # first_frame + 粗稿 draw + 第 1 问
        _send(ws, "被否定了,很委屈")
        _recv(ws)
        _recv(ws)  # draw 增量 + 第 2 问
        _send(ws, "觉得自己不行")
        _recv(ws)
        _recv(ws)  # draw 增量 + 第 3 问
        _send(ws, "我躲开了")  # 第 3 答 → 停采 → 分析开始(总结流 0.4s/块,未发帧)
        d4 = _recv(ws)  # 增量 draw
        assert d4["type"] == "draw"
        final_draw = _recv(ws)  # 精稿 draw(分析初段,快)
        assert final_draw["type"] == "draw"
        time.sleep(0.12)  # 总结流挂起中 → 抢占窗口(portal 线程继续跑分析)

        _send(ws, "我又想到另一件烦心事")  # 抢占:cancel + 弃 state + dead 蒸发
        preempt_first = _recv(ws)
        assert preempt_first["type"] == "first_frame"
        assert "我们重新开始" in preempt_first["text"]  # 承接安抚语变体
        new_draft = _recv(ws)
        assert new_draft["type"] == "draw" and new_draft["data"]["emotion"]["label"] is not None
        assert new_draft["seq"] > final_draw["seq"]  # seq 计数不重置
        new_q = _recv(ws)
        assert new_q["type"] == "text_delta" and "愿意说说" in new_q["text"]
        # 未发帧蒸发:抢占后不应收到旧回合的总结帧(下一帧已是新回合第 1 问)
