"""采集态门控钉测试(ADR-003):in_round 时 answer 命中不得弃采集态。

矩阵:
- 概念问句 → 短答支线(scene_answer 场景帧接管黑板;无 first_frame),state.suspended
- 求助句(怎么办类) → 留 collect(提取/陪聊),不 preempt
- 挂起后下一输入 → 恢复采集(全量 draw 模板切回,无新 first_frame)
- 连续概念问句 → 两次短答,state 保留
- 危机词 → crisis 优先(回归钉,scene_crisis 场景帧)
"""

import pytest
from test_collect_flow import _patch_llm, _ScriptedProvider
from test_gateway import (
    _RagStub,
    _recv,
    _send_input,
    _StreamStub,
    client,
)

from app.rag.corpus import Ref


@pytest.fixture(autouse=True)
def _gate_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """collect 图 LLM 脚本化 + 概念短答流 stub + RAG stub(真引擎加载秒级,单测不背)。"""

    _patch_llm(monkeypatch, _ScriptedProvider())  # 提取恒成功,答复均入格
    monkeypatch.setattr(
        "app.ws_gateway.gateway.get_provider",
        lambda: _StreamStub(["正念是觉察当下的练习。"]),
    )
    monkeypatch.setattr(
        "app.rag.get_engine",
        lambda: _RagStub(
            [Ref(id="mindfulness-01", question="什么是正念?", answer="正念是觉察练习")]
        ),
    )


def test_in_round_concept_suspends_and_resumes(monkeypatch):
    """概念问句:scene_answer 场景帧接管黑板;下一条输入恢复采集,模板切回。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")  # 入场
        assert _recv(ws)["type"] == "first_frame"
        draw1 = _recv(ws)
        assert draw1["type"] == "draw" and draw1["seq"] == 1
        assert _recv(ws)["type"] == "text_delta"  # 首问

        _send_input(ws, "上周开会的时候,领导当众批评我,我脑子里一片空白。")  # 轮1
        draw2 = _recv(ws)
        assert draw2["type"] == "draw" and draw2["seq"] == 3  # 增量(seq 全局递增)
        assert _recv(ws)["type"] == "text_delta"  # 确认+第2问

        _send_input(ws, "什么是正念?")  # 概念问句 → 短答支线
        suspend = _recv(ws)
        assert suspend["type"] == "draw" and suspend["template"] == "scene_answer"  # 挂起:场景接管
        assert "first_frame" not in (suspend["type"],)  # 无回合重开
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "就是开会那次,我满脑子都是要搞砸了。")  # 恢复:答挂起前问题
        draw3 = _recv(ws)
        assert draw3["type"] == "draw"  # 恢复采集:模板切回(无 first_frame)
        assert draw3["seq"] > draw2["seq"]


def test_in_round_help_seeking_stays_collect(monkeypatch):
    """求助句(怎么办类,依赖场景)不切 answer:无 first_frame、无 preempt 弃态。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        _recv(ws)  # 粗稿
        _recv(ws)  # 首问

        _send_input(ws, "你说我该怎么办啊")  # 求助句:KNOWLEDGE_PATTERNS 会命中
        frame = _recv(ws)
        assert frame["type"] == "draw"  # 仍在 collect 帧序内(提取→增量)
        # 关键判据:没有 first_frame(未弃采集态重开)


def test_two_consecutive_concepts_keep_state(monkeypatch):
    """连续概念问句:两次短答,state 全程保留,第三次输入仍回采集。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        _recv(ws)
        _recv(ws)

        _send_input(ws, "什么是正念")
        assert _recv(ws)["type"] == "draw"  # 挂起场景帧
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "什么是认知行为疗法")
        assert _recv(ws)["type"] == "draw"  # 同模板,场景帧幂等
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "睡不着的时候脑子特别乱。")  # 恢复
        draw = _recv(ws)
        assert draw["type"] == "draw"  # 采集态还活着


def test_explicit_ask_upgrades_to_short_answer(monkeypatch):
    """用户明确要求先回答:不必凑满两次追问,直接短答支线,state 保留。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        _recv(ws)
        _recv(ws)

        _send_input(ws, "你先回答我，什么是正念")
        suspend = _recv(ws)
        assert suspend["type"] == "draw" and suspend["template"] == "scene_answer"  # 场景接管
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "睡不着的时候脑子特别乱。")  # 恢复
        assert _recv(ws)["type"] == "draw"


def test_crisis_during_suspended(monkeypatch):
    """危机词:无论挂起与否 crisis 优先(回归钉;crisis 分支清采集态)。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        _recv(ws)
        _recv(ws)

        _send_input(ws, "什么是正念")
        assert _recv(ws)["type"] == "draw"  # 挂起场景帧
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "我不想活了")
        assert _recv(ws)["type"] == "first_frame"  # crisis 有自己的回合起点
        crisis_draw = _recv(ws)
        assert crisis_draw["type"] == "draw"
        assert crisis_draw["template"] == "scene_crisis"  # 危机固定场景
