"""collect 图接缝(backend-plan §3):entry→AskNext→轮次填格→充分度→分析→Finish;
降级两路(off_topic 陪聊 / negative 收尾);Escalate(risk 复核)。LLM 全 stub。"""

import pytest

from app.agents import AskNext, EmpathChat, Escalate, Finish, Turn, run_collect
from app.agents.state import CollectState
from app.llm import LLMError, Message
from app.schema import Formulation


class _ScriptedProvider:
    """按 schema 名分发的 stub:提取/复核/risk/总结流各自可编程"""

    def __init__(
        self,
        extract: dict[str, object] | None = None,
        review: dict[str, object] | None = None,
        risky: bool = False,
        risk_error: bool = False,
        stream_parts: list[str] | None = None,
        stream_delay: float = 0.0,
    ) -> None:
        self.extract = extract if extract is not None else {"value": "提炼后的短句", "off_topic": False}
        self.review = review if review is not None else {"label": "焦虑", "intensity": 0.8}
        self.risky = risky
        self.risk_error = risk_error
        self.stream_parts = stream_parts or ["总结第一段", "总结第二段"]
        self.stream_delay = stream_delay

    async def chat(self, messages: list[Message]) -> str:
        raise AssertionError("collect 图测试不应调用 chat")

    async def stream(self, messages: list[Message]):
        import asyncio

        for part in self.stream_parts:
            if self.stream_delay:
                await asyncio.sleep(self.stream_delay)
            yield part

    async def chat_json(self, messages: list[Message], schema: type):
        name = getattr(schema, "__name__", "")
        if name == "_ExtractOut":
            return schema(**self.extract)  # type: ignore[return-value]
        if name == "_ReviewOut":
            return schema(**self.review)  # type: ignore[return-value]
        if name == "_RiskOut":
            if self.risk_error:
                raise LLMError("复核断流")
            return schema(risky=self.risky)  # type: ignore[return-value]
        raise AssertionError(f"未预期 schema: {name}")


class _Recorder:
    """记录 draw/text 的假 emitter"""

    def __init__(self) -> None:
        self.draws: list[Formulation] = []
        self.texts: list[tuple[str, bool]] = []
        self.logs: list[str] = []

    async def draw(self, formulation: Formulation) -> None:
        self.draws.append(formulation.model_copy(deep=True))

    async def text(self, s: str, *, final: bool = False) -> None:
        self.texts.append((s, final))

    def audio(self, chunk: bytes) -> None:
        pass

    def log(self, event: str, level: str = "INFO", **fields: object) -> None:
        self.logs.append(event)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, provider: _ScriptedProvider) -> None:
    for target in (
        "app.agents.extract.get_provider",
        "app.agents.analysis.get_provider",
        "app.agents.graph.get_provider",
    ):
        monkeypatch.setattr(target, lambda: provider)


def _state() -> CollectState:
    return CollectState(
        session_id="sess_t",
        route="collect",
        template="beck_formulation",
        emotion_label="焦虑",
        confidence=0.9,
        max_rounds=3,
    )


async def test_happy_path_three_rounds_to_finish(monkeypatch):
    _patch_llm(monkeypatch, _ScriptedProvider(stream_parts=["你看清了情境,", "也看清了念头怎么带出行为。"]))
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))

    ev1 = await run_collect(cs, rec)
    assert isinstance(ev1, AskNext) and ev1.target_field == "situation"
    assert len(rec.draws) == 1  # 粗稿
    assert rec.draws[0].emotion.label == "焦虑"  # 快速研判入粗稿
    assert any("愿意说说" in t for t, _ in rec.texts)  # 第 1 问来自预置库

    for answer in ("被领导当众否定了", "觉得自己什么都做不好", "躲开了会议"):
        cs.turns.append(Turn(role="user", text=answer))
        ev = await run_collect(cs, rec)

    assert isinstance(ev, Finish) and ev.cause == "sufficient"
    assert len(rec.draws) == 5  # 粗稿 + 3 轮增量 + 精稿
    assert cs.sufficiency == 0.75  # .2(emotion)+.2+.2+.15
    final = rec.draws[-1]
    assert final.emotion.label == "焦虑" and final.emotion.intensity == 0.8  # 复核合入
    assert final.intermediate_belief is None and final.core_belief is None  # 信念留白
    assert any("提炼后的短句" == f.situation for f in rec.draws)  # 提取值入格
    joined = "".join(t for t, _ in rec.texts)
    assert "你看清了情境,也看清了念头怎么带出行为。" in joined  # 总结流式
    assert "sufficiency_scored" in rec.logs and "analysis_end" in rec.logs


async def test_off_topic_degrades_to_chat_then_resumes(monkeypatch):
    off = _ScriptedProvider(extract={"value": None, "off_topic": True})
    _patch_llm(monkeypatch, off)
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry → AskNext(situation)

    cs.turns.append(Turn(role="user", text="你听说过昨天那个热搜吗"))  # 答非所问
    ev = await run_collect(cs, rec)
    assert isinstance(ev, EmpathChat)  # 陪聊轮,不填格无 draw
    assert len(rec.draws) == 1

    _patch_llm(monkeypatch, _ScriptedProvider())  # 回到正题
    cs.turns.append(Turn(role="user", text="还是说回我吧"))
    ev2 = await run_collect(cs, rec)
    assert isinstance(ev2, AskNext)  # 清降级位,恢复提问


async def test_negative_answer_finishes_with_cause(monkeypatch):
    _patch_llm(monkeypatch, _ScriptedProvider())
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)

    cs.turns.append(Turn(role="user", text="我就是个废物,什么都做不好"))
    ev = await run_collect(cs, rec)
    assert isinstance(ev, Finish) and ev.cause == "negative"


async def test_soft_signal_risk_review_escalates(monkeypatch):
    _patch_llm(monkeypatch, _ScriptedProvider(risky=True))
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)
    for answer in ("被否定了", "很绝望,撑不住了", "躲开了会议"):
        cs.turns.append(Turn(role="user", text=answer))
        ev = await run_collect(cs, rec)

    assert isinstance(ev, Escalate)
    assert cs.escalated is True
    assert "crisis_gate_hit" in rec.logs  # 审计 WARN 留痕
    assert "analysis_start" not in rec.logs  # Escalate 短路:无分析无总结


async def test_risk_review_failure_does_not_escalate(monkeypatch):
    _patch_llm(monkeypatch, _ScriptedProvider(risk_error=True))
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)
    for answer in ("被否定了", "很绝望", "躲开了会议"):
        cs.turns.append(Turn(role="user", text=answer))
        ev = await run_collect(cs, rec)

    assert isinstance(ev, Finish)  # 复核失败不升级,按常规收尾
    assert "risk_review_failed" in rec.logs
