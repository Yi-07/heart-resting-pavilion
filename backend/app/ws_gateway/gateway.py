"""WS 网关(backend-plan §8;帧映射=发射侧唯一事实)。

- 连接即建 session_id;user_input / mood_select 入口;JSON 文本帧
- user_input 处理跑独立任务、不阻塞收包:新 user_input 即抢占——取消当前任务
  + 旧 emitter 标 dead(未发帧蒸发)→ 新回合 entry(安抚语承接变体)
- 每条 user_input 先过危机闸门:命中 → 危机序列 + WARN 审计 + 销毁采集态
- 未命中 → 分层判定(规则速判保 first_frame ≤300ms;模糊按 collect 走,
  LLM 仅异步精化 emotion_label,不撤回,spec §4 L4):
  answer → RAG 门控 → LLM 流式直答;collect → first_frame → collect 图
- collect:AskNext/EmpathChat 后保留状态等下一条;Finish → 回合三动作
  (温层摘要+station:input+研判 mood,memory 模块降级不杀回合)+ done + 销毁;
  Escalate → 危机序列 + 销毁;重连带原 session_id → 认领恢复热层(契约 §8.4)
- LLM 失败 → 话术库降级;处理满 LLM_TIMEOUT_S → error(timeout) 兜底
- 发号:仅 draw/text_delta/audio_chunk/done 盖章(seq 预增,首帧=1);
  first_frame/error 不带不消耗;计数器=连接内存(会话内全局递增)
- 非法消息 → error(invalid_message),不崩连接;输入单源文本(语音经 /asr/transcribe
  转写回填,ADR-004);安抚语/总结/危机 TTS 直发 audio_chunk,
  全部可失败跳过(音频缺席不影响文字链路)
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import config
from app import logger as app_logger
from app.agents import (
    AskNext,
    CollectState,
    ConnEmitter,
    EmpathChat,
    Escalate,
    Finish,
    Turn,
    stream_final,
)
from app.agents.state import CollectEvent, FinishCause
from app.llm import LLMError, Message, get_provider
from app.memory import Memory, get_memory
from app.router import classifier, gate, phrases
from app.router.classifier import Classification
from app.schema import (
    AudioChunk,
    CSMsg,
    Done,
    Draw,
    ErrorCode,
    ErrorFrame,
    FirstFrame,
    MoodSelect,
    ReplayFrame,
    ReplayTurn,
    TemplateData,
    TemplateId,
    TextDelta,
    UserInput,
)

if TYPE_CHECKING:
    from app.rag.corpus import Ref

_cs_adapter: TypeAdapter[CSMsg] = TypeAdapter(CSMsg)


def _session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


def _validation_brief(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err["loc"])
    msg = str(err["msg"]).removeprefix("Value error, ")
    return f"{loc}: {msg}"


class Connection:
    """单连接状态:session_id、seq/trace 计数、当前任务与采集态、盖章发帧。"""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.session_id = _session_id()
        self._seq = 0
        self._trace = -1
        self.current: asyncio.Task[None] | None = None
        self.current_emitter: ConnEmitter | None = None
        self.collect_state: CollectState | None = None

    # ---- 计数 ----

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def next_trace(self) -> int:
        """回合自增 ID(会话内从 0 递增,契约 §9.2)。"""
        self._trace += 1
        return self._trace

    @property
    def current_trace(self) -> int:
        """当前回合号(异步音频任务防抢占串扰的 epoch 比对用)。"""
        return self._trace

    # ---- 日志(标准字段 bind,业务字段随 event) ----

    def log(self, event: str, level: str = "INFO", **fields: Any) -> None:
        app_logger.logger.bind(
            service=app_logger.SERVICE,
            session_id=self.session_id,
            event=event,
            **fields,
        ).log(level, event)

    # ---- 发帧(发射侧唯一路径;by_alias 序列化,stage_map.from 别名正确) ----

    async def _send(self, msg: BaseModel) -> None:
        await self.ws.send_text(msg.model_dump_json(by_alias=True))

    async def send_first_frame(
        self,
        *,
        route: Literal["collect", "crisis"],
        text: str,
        mood_select: bool,
        template: TemplateId | None = None,
        emotion_label: str | None = None,
    ) -> None:
        await self._send(
            FirstFrame(
                session_id=self.session_id,
                route=route,
                template=template,
                emotion_label=emotion_label,
                mood_select=mood_select,
                text=text,
            )
        )
        self.log("first_frame_sent", route=route)

    async def send_draw(self, template: TemplateId, data: TemplateData) -> None:
        await self._send(Draw(seq=self._next_seq(), template=template, data=data))
        self.log("draw_sent", template=template)

    async def send_text(self, text: str, *, final: bool = False) -> None:
        await self._send(TextDelta(seq=self._next_seq(), text=text, final=final))

    async def send_done(self) -> None:
        await self._send(Done(session_id=self.session_id, seq=self._next_seq()))
        self.log("done")

    async def send_error(self, code: ErrorCode, message: str) -> None:
        await self._send(ErrorFrame(code=code, message=message))
        self.log("error", level="ERROR", code=code, detail=message)

    async def send_replay(self, frame: ReplayFrame) -> None:
        """ADR-005 重连回放;无 seq 不进回合计数(同 first_frame 语义)。"""
        await self._send(frame)
        self.log(
            "replay_sent",
            mode=frame.mode,
            turns=len(frame.turns),
            has_summary=frame.summary is not None,
        )

    async def send_audio(self, wav: bytes) -> None:
        """TTS 直发:整段 wav 一块(final=True,前端顺序播放);空块调用方负责不传。"""
        await self._send(
            AudioChunk(
                seq=self._next_seq(),
                format="wav",
                data=base64.b64encode(wav).decode("ascii"),
                final=True,
            )
        )
        self.log("audio_sent", bytes_len=len(wav))


# ---- 入口 ----


async def handle_connection(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    conn.log("session_open")
    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001 — 非文本帧(二进制)等非法消息:不崩连接(契约 §8.1)
                conn.log("error", level="ERROR", code="invalid_message", detail=type(exc).__name__)
                await conn.send_error("invalid_message", "不支持的消息类型,请发 JSON 文本")
                continue
            await _on_message(conn, raw)
    except WebSocketDisconnect:
        if conn.current is not None and not conn.current.done():
            conn.current.cancel()
        conn.log("session_close")


async def _on_message(conn: Connection, raw: str) -> None:
    try:
        msg = _cs_adapter.validate_python(json.loads(raw))
    except json.JSONDecodeError:
        await conn.send_error("invalid_message", "非 JSON 文本")
        return
    except ValidationError as exc:
        await conn.send_error("invalid_message", _validation_brief(exc))
        return

    if isinstance(msg, MoodSelect):
        try:
            await _on_mood_select(conn, msg)
        except Exception as exc:  # noqa: BLE001 — 错误集中处理(§5.5):记忆/回复路径异常不杀连接
            conn.log("error", level="ERROR", code="server_error", detail=type(exc).__name__)
            await conn.send_error("server_error", "心情上报处理失败,对话不受影响")
        return

    # user_input:抢占当前处理(分析中 cancel + 弃 state + 旧 emitter 标 dead
    # → 未发帧蒸发),新任务接管;轮次回答不经过此处销毁(state 仅在处理中被弃)
    preempted = False
    if conn.current is not None and not conn.current.done():
        conn.current.cancel()
        preempted = True
    if conn.current_emitter is not None:
        conn.current_emitter.mark_dead()
        conn.current_emitter = None
    if preempted and conn.collect_state is not None:
        conn.collect_state = None
    conn.current = asyncio.create_task(_process_user_input(conn, msg, carried=preempted))
    # 不 await:立刻回收下一条,保持抢占窗口


async def _push_replay(conn: Connection) -> None:
    """重连回放(ADR-005):认领后、first_frame 前推一次;热温均无内容不发。

    bubbles=热层 recent_turns 还在(原话回放+温层摘要附卡);
    digest=热层已过(仅小结卡);读失败按无内容处理(记忆降级原则)。
    """

    ctx = await get_memory().snapshot(conn.session_id)
    has_turns = bool(ctx.recent_turns)
    if not has_turns and ctx.history_summary is None:
        return
    frame = ReplayFrame(
        mode="bubbles" if has_turns else "digest",
        turns=[ReplayTurn(role=t.role, text=t.text) for t in ctx.recent_turns],
        summary=ctx.history_summary,
        session_id=conn.session_id,
    )
    await conn.send_replay(frame)


async def _on_mood_select(conn: Connection, msg: MoodSelect) -> None:
    # 冷层情绪趋势(spec §7:上报→L7;同日同源最新胜)+ 热层 mood_recent
    await get_memory().record_mood(
        msg.mood, source="mood_select", session_id=conn.session_id
    )
    if conn.collect_state is not None:
        # 回合内到达:仅更新 profile,不回帧不推进 trace(契约 §4.2)——
        # trace 递增仅限真回合(D4),否则回合计数虚增、未播完语音被蒸发
        conn.log("mood_select_received", mood=msg.mood, in_round=True)
        return
    trace = conn.next_trace()
    conn.log("mood_select_received", trace_id=trace, mood=msg.mood)
    await conn.send_text(phrases.MOOD_ACK[msg.mood], final=True)
    await conn.send_done()


async def _process_user_input(conn: Connection, msg: UserInput, *, carried: bool) -> None:
    trace = conn.next_trace()
    if msg.session_id and msg.session_id != conn.session_id:
        # 重连认领(契约 §8.4):带上原 session_id → 后端采纳并恢复热层上下文
        # (下一回合 collect entry 经 snapshot 进 state.session_context)
        conn.session_id = msg.session_id
        conn.log("reconnect_adopted", trace_id=trace)
        await _push_replay(conn)  # ADR-005:认领后先回放(先于本回合 first_frame)
    conn.log(
        "user_input_received",
        trace_id=trace,
        fingerprint=app_logger.text_fingerprint(msg.text),
    )

    # 语音输入已在 /asr/transcribe 转写并经用户确认回填(ADR-004),此处只吃文本
    text = msg.text
    # ADR-001/005:用户原话入热层轮次(重连重建 turns+回放数据源;30min TTL)
    await get_memory().append_turn(conn.session_id, "user", text)
    result = gate.check(text)
    conn.log(
        "crisis_gate_hit",
        level="WARN" if result.hit else "INFO",
        trace_id=trace,
        hit=result.hit,
        severity=result.severity,
        matched=result.matched,
        to_hotline=result.hit,
    )
    if result.hit:
        conn.collect_state = None
        conn.log("route_decided", trace_id=trace, route="crisis")
        await _crisis_sequence(conn)
        return

    try:
        cls = classifier.classify_rules(text)
        if cls.route == "answer" and conn.collect_state is not None:
            # 采集态门控(ADR-003):采集中的输入默认服务采集主线——
            # 纯概念问句/连续追问满 2/显式要求回答 → 短答支线:挂起不清空
            # (无 first_frame,前端黑板天然保活),下一输入恢复采集;
            # 其余求助句(怎么办/建议类,依赖场景)→ 留 collect,由提取/陪聊路径
            # 轻回应,不硬切科普
            state = conn.collect_state
            if (
                classifier.is_pure_concept(text)
                or classifier.is_explicit_ask(text)
                or state.pending_ask_count >= 2
            ):
                state.suspended = True
                conn.log(
                    "route_decided",
                    trace_id=trace,
                    route="answer",
                    source=cls.source,
                    needs_rag=cls.needs_rag,
                    via="concept_suspend",
                    ask_count=state.pending_ask_count,
                )
                await asyncio.wait_for(
                    _answer_sequence(conn, text, cls), timeout=config.LLM_TIMEOUT_S
                )
                return
            state.pending_ask_count += 1
            state.suspended = False
            conn.log(
                "route_decided",
                trace_id=trace,
                route="collect",
                source=cls.source,
                via="in_round_gate",
            )
            await asyncio.wait_for(
                _collect_sequence(conn, trace, text, cls, carried=False), timeout=config.LLM_TIMEOUT_S
            )
            return
        if cls.route == "answer":
            conn.log(
                "route_decided",
                trace_id=trace,
                route="answer",
                source=cls.source,
                needs_rag=cls.needs_rag,
            )
            await asyncio.wait_for(
                _answer_sequence(conn, text, cls), timeout=config.LLM_TIMEOUT_S
            )
        else:
            if conn.collect_state is not None:
                conn.collect_state.pending_ask_count = 0  # 回正题:追问计数清零
                conn.collect_state.suspended = False  # 恢复采集:挂起复位(ADR-003 决策1,H8)
            conn.log(
                "route_decided",
                trace_id=trace,
                route="collect",
                source=cls.source,
                confidence=cls.confidence,
                in_round=conn.collect_state is not None,
            )
            await asyncio.wait_for(
                _collect_sequence(conn, trace, text, cls, carried=carried),
                timeout=config.LLM_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        conn.collect_state = None
        conn.log("degraded", level="WARN", trace_id=trace, reason="timeout")
        await conn.send_error("timeout", "这次回应太慢了,先给你一句兜底")
        await conn.send_text(phrases.ANSWER_FALLBACK, final=True)
        await conn.send_done()
    except Exception as exc:  # noqa: BLE001 — 网关收口:任何异常 error 帧 + 不崩连接
        conn.collect_state = None
        conn.log(
            "error", level="ERROR", trace_id=trace, code="server_error", detail=str(exc)[:160]
        )
        await conn.send_error("server_error", "我这边卡了一下,先陪你坐一会儿")
        await conn.send_done()


async def _speak_stream(conn: Connection, text: str, dead: Callable[[], bool]) -> None:
    """分句流式合成+直发公共体(每句一个 audio_chunk);dead() 命中即弃余块。
    放线程跑(合成阻塞),帧经 run_coroutine_threadsafe 回事件循环保序。"""
    from app.voice import tts

    loop = asyncio.get_running_loop()

    def _produce() -> None:
        for wav in tts.synthesize_stream(text):
            if dead():
                return
            asyncio.run_coroutine_threadsafe(conn.send_audio(wav), loop).result()

    await asyncio.to_thread(_produce)


async def _speak(conn: Connection, text: str) -> None:
    """回合内同步语音(危机热线):失败记 degraded——音频缺席不影响文字链路。"""
    from app.voice import tts

    try:
        await _speak_stream(conn, text, lambda: False)
    except tts.TTSError as exc:
        conn.log("degraded", level="WARN", reason="tts_failed", detail=str(exc)[:120])
    except Exception:  # noqa: BLE001 — 发送失败(WS 断开等):音频链路静默收尾
        conn.log("degraded", level="WARN", reason="tts_send_failed")


def _soothe_evaporated(conn: Connection, trace: int) -> bool:
    """安抚语蒸发判定:抢占(trace 变)或回合已收尾(current 完成)。"""
    return conn.current_trace != trace or conn.current is None or conn.current.done()


async def _speak_if_current(conn: Connection, text: str, trace: int) -> None:
    """异步安抚语:逐句合成逐句判定蒸发——已合成未发的部分静默丢弃。"""
    try:
        await _speak_stream(conn, text, lambda: _soothe_evaporated(conn, trace))
    except Exception:  # noqa: BLE001 — 安抚语缺席无副作用,不记 degraded
        return


async def _speak_summary(conn: Connection, text: str, trace: int) -> None:
    """异步总结语音:回合已收尾后继续流出,仅抢占(trace 变)才蒸发——
    蒸发条件与安抚语不同:安抚语随回合收尾蒸发,总结语音恰恰要在收尾后播完。"""
    from app.voice import tts

    try:
        await _speak_stream(conn, text, lambda: conn.current_trace != trace)
    except tts.TTSError as exc:
        conn.log("degraded", level="WARN", reason="tts_failed", detail=str(exc)[:120])
    except Exception:  # noqa: BLE001 — 发送失败(WS 断开/抢占打断发送):静默收尾
        conn.log("degraded", level="WARN", reason="tts_send_failed")


async def _crisis_sequence(conn: Connection) -> None:
    await conn.send_first_frame(
        route="crisis", text=phrases.CRISIS_SOOTHE, mood_select=False
    )
    await conn.send_draw("stage_map", phrases.CRISIS_STAGE)
    await conn.send_text(phrases.CRISIS_HOTLINE, final=True)
    await _speak(conn, phrases.CRISIS_HOTLINE)
    await conn.send_done()


# ---- collect(每条 user_input=一次短图调用,backend-plan §3) ----


async def _collect_sequence(
    conn: Connection, trace: int, text: str, cls: Classification, *, carried: bool
) -> None:
    state = conn.collect_state
    if state is None:
        # entry:first_frame(≤300ms 语义,规则速判)+ 建态;承接变体=抢占后重开;
        # 热层 snapshot 恢复上下文(重连/续话,契约 §8.4;记忆不可用降级空档)
        state = CollectState(
            session_id=conn.session_id,
            route="collect",
            template="beck_formulation",
            emotion_label=cls.emotion_label,
            confidence=cls.confidence,
            max_rounds=config.COLLECT_MAX_ROUNDS,
        )
        state.session_context = await get_memory().snapshot(conn.session_id)
        if state.session_context.history_summary is not None or state.session_context.recent_turns:
            conn.log(
                "memory_restored",
                trace_id=trace,
                summary_len=len(state.session_context.history_summary or ""),
                moods=len(state.session_context.mood_recent),
                turns=len(state.session_context.recent_turns),
            )
            # ADR-001:重连重建 turns(采集上下文接上,不用重说);formulation
            # /round_index 不持久=已知局限(黑板重画,采集从首轮计)
            if not state.turns:
                state.turns = list(state.session_context.recent_turns)
        conn.collect_state = state
        soothe = phrases.collect_soothe(cls.emotion_label, carried=carried)
        await conn.send_first_frame(
            route="collect",
            template="beck_formulation",
            emotion_label=cls.emotion_label,
            mood_select=True,
            text=soothe,
        )
        # 安抚语语音异步合成(不阻塞 ≤300ms first_frame);抢占/收尾后蒸发
        asyncio.create_task(_speak_if_current(conn, soothe, trace))
        conn.log("collection_start", trace_id=trace, carried=carried)
    # 轮次回答:同回合继续,无 first_frame(契约 §6.2)
    state.turns.append(Turn(role="user", text=text))

    emitter = ConnEmitter(conn, "beck_formulation")
    conn.current_emitter = emitter
    try:
        from app.agents import run_collect  # 懒加载:LangGraph 只进 collect 路径

        event = await run_collect(state, emitter)
    finally:
        if conn.current_emitter is emitter:
            # 先标 dead 再摘引用:run_collect 挂掉的残余流(如总结文本)不得再发帧
            emitter.mark_dead()
            conn.current_emitter = None
    await _settle_collect_event(conn, trace, event)


async def _archive_round(
    memory: Memory, conn: Connection, state: CollectState,
    summary: str, trace: int, cause: FinishCause,
) -> None:
    """Finish 归档三动作(shield 下执行,断连取消不打断;B2 发现⑤)。"""
    await memory.save_round_summary(conn.session_id, summary)
    await memory.save_station_input(
        conn.session_id, state.formulation.model_dump_json(by_alias=True), summary
    )
    label = state.formulation.emotion.label
    if label:
        await memory.record_mood(
            label,
            intensity=state.formulation.emotion.intensity,
            source="研判",
            session_id=conn.session_id,
        )
    if summary:
        # ADR-005:总结文本入热层轮次(回放末条=小栖最后对用户说的话)
        await memory.append_turn(conn.session_id, "assistant", summary)
    conn.log(
        "round_archived",
        trace_id=trace,
        cause=cause,
        summary_len=len(summary),
    )
    if summary:
        # 总结语音异步流出(done 后到达,抢占即蒸发):不占 60s 处理窗口,
        # 长总结不再触发 timeout 兜底;ws-contract §6.2 时序措辞已同步
        asyncio.create_task(_speak_summary(conn, summary, trace))


async def _settle_collect_event(
    conn: Connection, trace: int, event: CollectEvent
) -> None:
    if isinstance(event, Finish):
        # 回合结束三动作(backend-plan §3.3):温层摘要 → station:input → 弃 state;
        # 另落研判 mood(复核后标签进冷层情绪趋势)。Escalate 不落(危机不记情绪)
        state = conn.collect_state
        conn.collect_state = None
        if state is not None:
            memory = get_memory()
            summary = event.summary or ""
            try:
                await asyncio.shield(
                    _archive_round(memory, conn, state, summary, trace, event.cause)
                )
            except asyncio.CancelledError:
                # 断连取消不得打断归档(B2 发现⑤):shield 让写入继续,这里只落痕
                conn.log("degraded", level="WARN", reason="finish_archival_interrupted")
                raise
        await conn.send_done()
    elif isinstance(event, Escalate):
        conn.collect_state = None
        conn.log("route_decided", trace_id=trace, route="crisis", via="escalate")
        await _crisis_sequence(conn)
    elif isinstance(event, AskNext):
        # ADR-005:assistant 问句入热层轮次(确认语+问句拼合,与发帧文本一致)
        await get_memory().append_turn(
            conn.session_id, "assistant", event.confirm + event.next_question
        )
    elif isinstance(event, EmpathChat):
        # ADR-005:陪聊回应入热层轮次
        await get_memory().append_turn(conn.session_id, "assistant", event.reply)
    # 其余:Finish/Escalate 已在上方收口


# ---- answer 直答(契约 §6.1:user_input → text_delta ×N → done,无黑板) ----


def _answer_messages(query: str, refs: list[Ref]) -> list[Message]:
    if refs:
        context = "\n\n".join(f"【{r.question}】\n{r.answer}" for r in refs)
        system = (
            "你是心栖阁的心理知识科普助手。优先依据下面的资料回答,科普口吻、简洁"
            f"(150 字内);资料没有的内容不编造;不做医疗诊断。参考资料:\n{context}"
        )
    else:
        system = (
            "你是心栖阁的陪伴助手。温暖、简洁地回应(80 字内),不做医疗诊断,"
            "不连续追问。"
        )
    return [Message("system", system), Message("user", query)]


async def _answer_sequence(conn: Connection, text: str, cls: Classification) -> None:
    refs: list[Ref] = []
    if cls.needs_rag:
        try:
            from app.rag import (
                retrieve_async,  # 懒加载:chroma/模型只在预热/检索路径进内存
            )
            from app.rag.corpus import RagLibrary

            refs = await retrieve_async(
                text, k=config.RAG_TOP_K, library=RagLibrary.KNOWLEDGE
            )
            conn.log("rag_retrieved", refs=[r.id for r in refs])
        except Exception as exc:  # noqa: BLE001 — RAG 失败/未就绪都降级直答,不杀回合
            conn.log("degraded", level="WARN", reason="rag_failed", detail=str(exc)[:120])
            refs = []

    emitter = ConnEmitter(conn, "beck_formulation")  # answer 不画黑板,draw 不触达
    conn.current_emitter = emitter
    try:
        sent = False
        try:
            sent = await stream_final(emitter, get_provider().stream(_answer_messages(text, refs)))
        except LLMError as exc:
            conn.log("degraded", level="WARN", reason="llm_error", detail=str(exc)[:120])
        if not sent:
            conn.log("degraded", level="WARN", reason="empty_stream")
            await emitter.text(phrases.ANSWER_FALLBACK, final=True)
    finally:
        if conn.current_emitter is emitter:
            conn.current_emitter = None
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
