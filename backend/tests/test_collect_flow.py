"""collect 图接缝(backend-plan §3):entry→AskNext→轮次填格→充分度→分析→Finish;
降级两路(off_topic 陪聊 / negative 收尾);Escalate(risk 复核);问话 LLM 失败
挂起(AskFailed)。LLM 全 stub。"""

import pytest

from app.agents import AskFailed, AskNext, EmpathChat, Escalate, Finish, Turn, run_collect
from app.agents.state import CollectState
from app.llm import LLMError, Message
from app.schema import Formulation


class _ScriptedProvider:
    """按 schema 名分发的 stub:提取/复核/risk/总结流/问话流各自可编程"""

    def __init__(
        self,
        extract: dict[str, object] | None = None,
        review: dict[str, object] | None = None,
        risky: bool = False,
        risk_error: bool = False,
        stream_parts: list[str] | None = None,
        stream_delay: float = 0.0,
        assets: dict[str, str] | None = None,
        ask_parts: list[str] | None = None,
        ask_error: bool = False,
    ) -> None:
        self.extract = extract if extract is not None else {"value": "提炼后的短句", "off_topic": False}
        self.review = review if review is not None else {"label": "焦虑", "intensity": 0.8}
        self.risky = risky
        self.risk_error = risk_error
        self.stream_parts = stream_parts or ["总结第一段", "总结第二段"]
        self.stream_delay = stream_delay
        self.assets = assets or {}
        self.ask_parts = ask_parts if ask_parts is not None else ["嗯,那后来呢?", "你当时在想什么?"]
        self.ask_error = ask_error
        self.ask_messages: list[list[Message]] = []

    async def chat(self, messages: list[Message]) -> str:
        raise AssertionError("collect 图测试不应调用 chat")

    async def stream(self, messages: list[Message]):
        import asyncio

        self.ask_messages.append(messages)
        if self.ask_error:
            raise LLMError("问话断流")
        # 首次调用=问话流,其后=总结流;两者文本可区分断言
        if len(self.ask_messages) > 1:
            for part in self.stream_parts:
                if self.stream_delay:
                    await asyncio.sleep(self.stream_delay)
                yield part
        else:
            for part in self.ask_parts:
                if self.stream_delay:
                    await asyncio.sleep(self.stream_delay)
                yield part

    async def chat_json(self, messages: list[Message], schema: type):
        name = getattr(schema, "__name__", "")
        if name == "_ExtractOut":
            off_topic = bool(self.extract.get("off_topic", False))
            custom = self.extract.get("fields")
            if isinstance(custom, dict):  # 跨字段编程:直接按给定 dict 填
                return schema(fields=dict(custom), assets=dict(self.assets), off_topic=off_topic)
            asked = self._asked_field(messages)
            value = str(self.extract.get("value", "提炼后的短句"))
            return schema(
                fields={} if off_topic else {asked: value},
                assets=dict(self.assets),
                off_topic=off_topic,
            )
        if name == "RouteLabel":
            # fallback 输入走 classifier 的 LLM 分支;低 conf 落 collect 兜底
            return schema(route="collect", emotion_label=None, confidence=0.9)
        if name == "_ReviewOut":
            return schema(**self.review)  # type: ignore[return-value]
        if name == "_RiskOut":
            if self.risk_error:
                raise LLMError("复核断流")
            return schema(risky=self.risky)  # type: ignore[return-value]
        raise AssertionError(f"未预期 schema: {name}")

    @staticmethod
    def _asked_field(messages: list[Message]) -> str:
        """从提取请求的 user 消息里取所问字段(单字段默认回填用)。"""
        for m in messages:
            if m.role == "user":
                for line in m.content.splitlines():
                    if line.startswith("所问字段:"):
                        return line.split(":", 1)[1].strip()
        return ""


class _Recorder:
    """记录 draw/text 的假 emitter;ask_stream 模拟句子泵(消费流攒批发 text)"""

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

    async def ask_stream(self, chunks, **kwargs: object) -> bool:
        from app.agents.emitter import batched_chunks

        sent = False
        pending: str | None = None
        async for batch in batched_chunks(chunks):
            if pending is not None:
                await self.text(pending)
            pending = batch
            sent = True
        if pending is not None:
            await self.text(pending, final=True)
        return sent


def _patch_llm(monkeypatch: pytest.MonkeyPatch, provider: _ScriptedProvider) -> None:
    for target in (
        "app.agents.extract.get_provider",
        "app.agents.analysis.get_provider",
        "app.agents.graph.get_provider",
        "app.router.classifier.get_provider",  # fallback 输入走 classify 的 LLM 分支
    ):
        monkeypatch.setattr(target, lambda: provider)


def _state() -> CollectState:
    return CollectState(
        session_id="sess_t",
        route="collect",
        template="scene_default",  # 建态=暖场景开场,接力在图内
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
    assert any("当时在想" in t or "后来呢" in t for t, _ in rec.texts)  # 第 1 问来自 LLM 流
    assert ev1.question  # AskNext 携问话全文(无 confirm 字段,契约 §3.4)
    assert cs.pending_question is not None and cs.pending_question.text == ev1.question

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
    off = _ScriptedProvider(extract={"value": None, "off_topic": True}, ask_parts=["嗯,慢慢来,不急。"])
    _patch_llm(monkeypatch, off)
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry → AskNext(situation)

    cs.turns.append(Turn(role="user", text="你听说过昨天那个热搜吗"))  # 答非所问
    ev = await run_collect(cs, rec)
    assert isinstance(ev, EmpathChat)  # 陪聊轮,不填格无 draw
    assert ev.reply  # 陪聊回应由 LLM 流产出(非固定文案)
    assert len(rec.draws) == 1

    _patch_llm(monkeypatch, _ScriptedProvider())  # 回到正题
    cs.turns.append(Turn(role="user", text="还是说回我吧"))
    ev2 = await run_collect(cs, rec)
    assert isinstance(ev2, AskNext)  # 清降级位,恢复提问


async def test_ask_llm_failed_suspends_and_retries(monkeypatch):
    """问话 LLM 失败 → AskFailed(不发预置问句、不填格不计数);下一条输入重试成功。
    (ask_retry 置位是网关 settle 职责,挂起消费在图 prepare。)"""
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))

    bad = _ScriptedProvider(ask_error=True)
    _patch_llm(monkeypatch, bad)
    ev = await run_collect(cs, rec)
    assert isinstance(ev, AskFailed)
    assert cs.pending_question is None  # 不落预置问句(不掩盖错误)
    assert cs.round_index == 0  # 失败轮不计数
    assert not rec.texts  # 失败路径零文字帧(无预置兜底文本)

    # 下一条输入:挂起重试(网关置位模拟),回答尚未被消费 → 不计轮、直接重问
    cs.ask_retry = True
    cs.turns.append(Turn(role="user", text="被领导当众否定了,很焦虑"))
    good = _ScriptedProvider()
    _patch_llm(monkeypatch, good)
    ev2 = await run_collect(cs, rec)
    assert isinstance(ev2, AskNext)
    assert cs.ask_retry is False
    assert cs.round_index == 0  # 重试轮不推进计数(该回答随后由下一调用消费)


async def test_cross_field_extraction_fills_multiple(monkeypatch):
    """跨字段提取:一条回答里包含多字段信息时一次填全(单字段瓶颈修复的钉测)。"""
    provider = _ScriptedProvider(
        extract={"fields": {"situation": "被当众批评", "thought": "我觉得我不行"}}
    )
    _patch_llm(monkeypatch, provider)
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry → AskNext(situation)

    cs.turns.append(Turn(role="user", text="被领导当众批评了,满脑子都是我不行"))
    ev = await run_collect(cs, rec)
    assert isinstance(ev, AskNext) and ev.target_field == "behavior"
    assert rec.draws[-1].situation == "被当众批评"
    assert rec.draws[-1].thought == "我觉得我不行"  # 跨字段一次入格
    assert cs.pending_question is not None  # 所问 situation 已答→挂起清除后已换新问
    assert ev.target_field == "behavior"  # 下一问跳过已填字段


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


# ---- 板式接力(scene_default → scene_focus,选材驱动) ----


def _with_selector(cs: CollectState, catalog: dict[str, list[str]]) -> CollectState:
    from app.board import AssetSelector

    cs.asset_selector = AssetSelector(catalog=catalog)
    return cs


async def test_template_switches_on_first_substantive_disclosure(monkeypatch):
    """接力主链:situation 入格+有效选材 → scene_default 切 scene_focus,单向不变。"""
    provider = _ScriptedProvider(extract={"fields": {"situation": "被当众批评"}})
    _patch_llm(monkeypatch, provider)
    cs = _with_selector(
        _state(),
        {
            "desk.cluttered": ["杂乱", "文件堆"],
            "desk.overwhelmed": ["被压垮", "桌前"],
            "state.storm-cloud": ["乌云", "焦虑"],
        },
    )
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry:粗稿,暖场景
    assert cs.template == "scene_default"

    provider.assets = {"situation": "desk.cluttered", "subject": "desk.overwhelmed"}
    cs.turns.append(Turn(role="user", text="被领导当众批评了"))
    await run_collect(cs, rec)
    assert cs.template == "scene_focus"  # 触发集字段入格+图标有效
    assert rec.draws[-1].assets == {
        "situation": "desk.cluttered",
        "subject": "desk.overwhelmed",
    }

    provider.assets = {}
    cs.turns.append(Turn(role="user", text="后来我就躲着走"))
    await run_collect(cs, rec)
    assert cs.template == "scene_focus"  # 单向:后续轮不再回退


async def test_template_stays_default_without_icon(monkeypatch):
    """无有效选材图标(目录无对应素材)维持暖场景候着,切换不发生。"""
    provider = _ScriptedProvider(extract={"fields": {"situation": "和妈妈吵架了"}})
    _patch_llm(monkeypatch, provider)
    cs = _with_selector(_state(), {"state.storm-cloud": ["乌云", "焦虑"]})  # 目录无 situation 可选
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)

    provider.assets = {}  # LLM 无图标可给 → 校验空 → 不触发
    cs.turns.append(Turn(role="user", text="和妈妈大吵了一架"))
    await run_collect(cs, rec)
    assert cs.template == "scene_default"
    assert rec.draws[-1].situation == "和妈妈吵架了"  # 字段照常入格,只是不切板式
