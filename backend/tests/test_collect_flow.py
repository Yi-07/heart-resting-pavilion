"""collect 图接缝(backend-plan §3):entry→AskNext→轮次填格→充分度→分析→Finish;
降级两路(off_topic 陪聊 / negative 收尾);Escalate(risk 复核);问话 LLM 失败
挂起(AskFailed)。LLM 全 stub。"""

import pytest

from app.agents import (
    AskFailed,
    AskNext,
    EmpathChat,
    Escalate,
    Finish,
    Turn,
    run_collect,
)
from app.agents.state import CollectState, PendingQuestion
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
            asked = ""
            opening = False
            for m in messages:
                if m.role != "user":
                    continue
                for line in m.content.splitlines():
                    if line.startswith("所问字段:"):
                        asked = line.split(":", 1)[1].strip()
                    elif line.startswith("问题:") and "(开场" in line:
                        opening = True  # entry 即提取(非轮次回答)
            if opening:
                # entry 提取:走 asked 默认桩(单字段),custom 编程留给轮次跨字段用
                return schema(
                    fields={} if self.extract.get("off_topic") else {asked: "提炼后的短句"},
                    assets=dict(self.assets),
                    off_topic=False,
                )
            off_topic = bool(self.extract.get("off_topic", False))
            custom = self.extract.get("fields")
            if isinstance(custom, dict):  # 跨字段编程:直接按给定 dict 填
                return schema(fields=dict(custom), assets=dict(self.assets), off_topic=off_topic)
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
    assert isinstance(ev1, AskNext) and ev1.target_field == "thought"  # entry 已提取 situation
    assert len(rec.draws) == 1  # entry 粗稿
    assert rec.draws[0].emotion.label == "焦虑"  # 快速研判入粗稿
    assert rec.draws[0].situation == "提炼后的短句"  # entry 即提取:首条输入实质入格(PRD)
    assert any("当时在想" in t or "后来呢" in t for t, _ in rec.texts)  # 第 1 问来自 LLM 流
    assert ev1.question  # AskNext 携问话全文(无 confirm 字段,契约 §3.4)
    assert cs.pending_question is not None and cs.pending_question.text == ev1.question

    # entry 已采 situation+emotion(0.4),两轮即足 0.75 收尾
    for answer in ("被领导当众否定了", "觉得自己什么都做不好"):
        cs.turns.append(Turn(role="user", text=answer))
        ev = await run_collect(cs, rec)

    assert isinstance(ev, Finish) and ev.cause == "sufficient"
    assert len(rec.draws) == 4  # entry 粗稿 + 2 轮增量 + 精稿
    assert cs.sufficiency == 0.75  # .2(situation entry)+.2(emotion)+.2(thought)+.15(behavior)
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
    assert cs.round_index == 1  # 第 1 问发出计数

    cs.turns.append(Turn(role="user", text="你听说过昨天那个热搜吗"))  # 答非所问
    ev = await run_collect(cs, rec)
    assert isinstance(ev, EmpathChat)  # 陪聊轮,不填格无 draw
    assert ev.reply  # 陪聊回应由 LLM 流产出(非固定文案)
    assert len(rec.draws) == 1
    assert cs.round_index == 1  # 陪聊轮不占轮次(轮计提问轮)

    _patch_llm(monkeypatch, _ScriptedProvider())  # 回到正题
    cs.turns.append(Turn(role="user", text="还是说回我吧"))
    ev2 = await run_collect(cs, rec)
    assert isinstance(ev2, AskNext)  # 清降级位,恢复提问
    assert cs.round_index == 2  # 第 2 问发出才计数


async def test_off_topic_stays_chat_until_round_budget_exhausted_by_questions_only(monkeypatch):
    """陪聊驻留不占轮次(裁定 2026-10-13):连续陪聊后轮数预算只由提问消耗——
    max_rounds=1 时陪聊任意多轮不触发 finish(max_rounds),第 2 问发出才到顶。"""
    off = _ScriptedProvider(extract={"value": None, "off_topic": True}, ask_parts=["嗯。"])
    _patch_llm(monkeypatch, off)
    cs = _state()
    cs.max_rounds = 1
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry → AskNext,round_index=1 已到 max_rounds
    assert cs.round_index == cs.max_rounds

    for text in ("聊聊天气吧", "你吃了吗", "热搜看了吗"):
        cs.turns.append(Turn(role="user", text=text))
        ev = await run_collect(cs, rec)
        assert isinstance(ev, EmpathChat)  # 陪聊轮不触发 finish(max_rounds)
        assert cs.round_index == 1


async def test_chat_messages_carries_pending_question_guide(monkeypatch):
    """陪聊 prompt 引导回题(spec「陪聊引导」):挂起提问的 info_need 进 prompt,
    system 段带衔接约束;问话 LLM 化后 entry 后挂起提问恒在,断言其存在。"""
    from app.agents import ask as ask_mod

    cs = _state()
    cs.pending_question = PendingQuestion(text="当时你在想什么?", target_field="thought")
    msgs = ask_mod.chat_messages(cs, "聊聊天气吧")
    user_text = msgs[1].content
    assert "自动思维" in user_text  # thought 字段的 info_need 进 prompt
    assert "还没聊完" in user_text
    assert "前面你提到" in msgs[0].content  # system 段回指点题约束

    cs.pending_question = None
    msgs_plain = ask_mod.chat_messages(cs, "聊聊天气吧")
    assert "还没聊完" not in msgs_plain[1].content  # 无挂起提问只共情不引导
    assert "前面你提到" not in msgs_plain[0].content


async def test_ask_messages_injects_turns_history(monkeypatch):
    """问话 prompt 注入对话历史(spec L7 注入通道,T3):turns 原话进 user 段
    (含小栖自己的问句——「接住上文」语境);本轮回答不重复注入。"""
    from app.agents import ask as ask_mod

    cs = _state()
    cs.turns = [
        Turn(role="user", text="最近很焦虑睡不着"),
        Turn(role="assistant", text="那件事之后你是怎么应对的?"),
        Turn(role="user", text="被领导否定了,很委屈"),
    ]
    msgs = ask_mod.ask_messages(cs, "thought", "被领导否定了,很委屈")
    user_text = msgs[1].content
    assert "最近很焦虑睡不着" in user_text  # 历史原话注入
    assert "你是怎么应对的" in user_text  # assistant 问句(小栖自己说过什么)在语境里
    assert user_text.count("被领导否定了,很委屈") == 1  # 本轮回答不重复进历史段
    assert "刚才的对话" in user_text


async def test_ask_messages_falls_back_to_summary_when_turns_empty():
    """热层过期降级(T3):turns 空时注入回合摘要(截断);都无则无历史段。"""
    from app.agents import ask as ask_mod
    from app.agents.state import SessionContext

    cs = _state()
    cs.session_context = SessionContext(history_summary="上次聊了工作压力,情绪以焦虑为主" * 20)
    msgs = ask_mod.ask_messages(cs, "thought", "被否定了")
    assert "之前那次梳理的摘要" in msgs[1].content
    assert "上次聊了工作压力" in msgs[1].content

    cs.session_context = SessionContext()
    msgs_plain = ask_mod.ask_messages(cs, "thought", "被否定了")
    assert "刚才的对话" not in msgs_plain[1].content
    assert "之前那次梳理的摘要" not in msgs_plain[1].content


async def test_turns_context_caps_and_excludes_last_user():
    """历史段工具函数钉:轮数上限截断、exclude_last_user 排除本轮、role 标注。"""
    from app.agents.ask import turns_context

    turns = [Turn(role="user", text=f"u{i}") for i in range(10)]
    ctx = turns_context(turns, exclude_last_user=True)
    # 最近 6 轮(u4..u9)再去末条 user → u3..u8
    assert "u9" not in ctx and "u3" in ctx and "u8" in ctx
    assert ctx.count("用户:") >= 4

    mixed = [Turn(role="user", text="u"), Turn(role="assistant", text="a")]
    ctx_mixed = turns_context(mixed)
    assert "小栖:a" in ctx_mixed and "用户:u" in ctx_mixed
    assert turns_context([]) == ""


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
    assert cs.round_index == 0  # 失败轮不计数(轮计提问轮:问话未发出)
    assert not rec.texts  # 失败路径零文字帧(无预置兜底文本)

    # 下一条输入:挂起重试(网关置位模拟),回答尚未被消费 → 直接重问;重问发出才计轮
    cs.ask_retry = True
    cs.turns.append(Turn(role="user", text="被领导当众否定了,很焦虑"))
    good = _ScriptedProvider()
    _patch_llm(monkeypatch, good)
    ev2 = await run_collect(cs, rec)
    assert isinstance(ev2, AskNext)
    assert cs.ask_retry is False
    assert cs.round_index == 1  # 重试问话发出:第 1 问计数(该回答随后由下一调用消费)


async def test_cross_field_extraction_fills_multiple(monkeypatch):
    """跨字段提取:一条回答里包含多字段信息时一次填全(单字段瓶颈修复的钉测)。

    entry 即提取后 situation 已在格,轮次回答补 thought+behavior 两个字段。"""
    provider = _ScriptedProvider(
        extract={"fields": {"thought": "满脑子我不行", "behavior": "躲开了会议"}}
    )
    _patch_llm(monkeypatch, provider)
    cs = _state()
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)  # entry:提取 situation → AskNext(thought)

    cs.turns.append(Turn(role="user", text="被领导当众批评了,满脑子都是我不行,躲在了工位上"))
    ev = await run_collect(cs, rec)
    # entry 已采 situation+emotion(0.4),本轮 thought+behavior 一次入两格 → 0.75 收尾
    assert isinstance(ev, Finish) and ev.cause == "sufficient"
    assert rec.draws[-1].thought == "满脑子我不行"
    assert rec.draws[-1].behavior == "躲开了会议"  # 跨字段一次入格


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
    """接力主链:entry 提取 situation(无图标,暖场景候着)→ 轮次 thought 入格
    +有效图标 → scene_default 切 scene_focus,单向不变。"""
    provider = _ScriptedProvider(extract={"fields": {"thought": "被领导当众批评"}})
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

    provider.assets = {"thought": "desk.cluttered", "subject": "desk.overwhelmed"}
    cs.turns.append(Turn(role="user", text="被领导当众批评了"))
    await run_collect(cs, rec)
    assert cs.template == "scene_focus"  # 触发集字段入格+图标有效
    assert rec.draws[-1].assets == {
        "thought": "desk.cluttered",
        "subject": "desk.overwhelmed",
    }
    assert rec.draws[-1].thought == "被领导当众批评"  # 轮次提取值入格

    provider.assets = {}
    cs.turns.append(Turn(role="user", text="后来我就躲着走,满脑子都是我不行"))
    await run_collect(cs, rec)
    assert cs.template == "scene_focus"  # 单向:后续轮不再回退


async def test_template_stays_default_without_icon(monkeypatch):
    """无有效选材图标(目录无对应素材)维持暖场景候着,切换不发生。"""
    provider = _ScriptedProvider(extract={"fields": {"thought": "和妈妈吵架很委屈"}})
    _patch_llm(monkeypatch, provider)
    cs = _with_selector(_state(), {"state.storm-cloud": ["乌云", "焦虑"]})  # 目录无 thought 可选
    rec = _Recorder()
    cs.turns.append(Turn(role="user", text="最近很焦虑睡不着"))
    await run_collect(cs, rec)

    provider.assets = {}  # LLM 无图标可给 → 校验空 → 不触发
    cs.turns.append(Turn(role="user", text="和妈妈大吵了一架"))
    await run_collect(cs, rec)
    assert cs.template == "scene_default"
    assert rec.draws[-1].thought == "和妈妈吵架很委屈"  # 字段照常入格,只是不切板式
