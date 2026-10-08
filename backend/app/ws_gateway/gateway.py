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
import threading
from collections.abc import AsyncIterator, Callable
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
    batched_chunks,
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

    async def send_audio(self, wav: bytes, *, final: bool = True) -> None:
        """TTS 直发一块音频。

        final=True = 本回合最后一块(单发场景:安抚语/总结/fillers);
        final=False = 流式中的一块(answer 逐句场景,最后一块在句子泵收尾时补发)。
        前端 AudioQueue 只按序连播,不读 final(ws-contract §3.4 标注"可不依赖"),
        所以这两条路径对它是透明的。
        """
        if not wav:
            return
        await self._send(
            AudioChunk(
                seq=self._next_seq(),
                format="wav",
                data=base64.b64encode(wav).decode("ascii"),
                final=final,
            )
        )
        self.log("audio_sent", bytes_len=len(wav), final=final)

    # ---- TTS 回合打断 ----

    def tts_round_id(self, trace: int | None = None) -> str:
        """本回合的 TTS round_id。抢占后仍指向旧回合,供 cancel 精确命中。"""
        return f"tts-{self.current_trace if trace is None else trace}"

    def cancel_tts(self, round_id: str | None = None, *, cascade: bool = True) -> None:
        """打断某个回合的 TTS(同步门面,内部起线程;抢占路径不能被它阻塞)。

        打断必须穿透到 TTS 服务:否则用户已经换话题了,旧回合还在服务端
        排队出声。cascade 让服务端连带清掉还没开始的排队回合。
        """
        rid = round_id or self.tts_round_id()
        from app.voice import tts

        threading.Thread(
            target=tts.cancel,
            args=(rid,),
            kwargs={"cascade": cascade},
            name=f"tts-cancel-{rid}",
            daemon=True,
        ).start()
        self.log("tts_cancel_sent", round_id=rid, cascade=cascade)


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
        # 打断穿透到 TTS 服务:不然后端停了,服务端还在排队出声。
        # 放在这里而不是 mark_dead 里 —— 安抚语/总结语音用的是独立路径,
        # 它们靠自己的 trace 比对蒸发,不需要打断服务。
        conn.cancel_tts()
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


async def _speak_stream(
    conn: Connection,
    text: str,
    dead: Callable[[], bool],
    *,
    round_id: str | None = None,
    final: bool = True,
) -> None:
    """分句流式合成+直发公共体(每句一个 audio_chunk);dead() 命中即弃余块。
    放线程跑(合成阻塞),帧经 run_coroutine_threadsafe 回事件循环保序。

    round_id 传给 TTS 服务,抢占时才能精确打断服务端的排队。
    final=False 用于 answer 的流式路径:最后一块由句子泵 hold-one 补发。
    """
    from app.voice import tts

    loop = asyncio.get_running_loop()

    def _produce() -> None:
        # 用 synthesize_stream(公共名)而不是 _detailed:单发路径不需要逐块区分
        # "打断"与"故障" —— 打断照样会冒上来(客户端内部就是转发到 _detailed),
        # 但测试桩历来挂在 synthesize_stream 上,换名会打断既有契约。
        for wav in tts.synthesize_stream(text, request_id=round_id):
            if dead():
                return
            asyncio.run_coroutine_threadsafe(
                conn.send_audio(wav, final=final), loop
            ).result()

    await asyncio.to_thread(_produce)


async def _speak(
    conn: Connection, text: str, *, round_id: str | None = None
) -> None:
    """回合内同步语音(危机热线):失败记 degraded——音频缺席不影响文字链路。"""
    from app.voice import tts

    try:
        await _speak_stream(conn, text, lambda: False, round_id=round_id)
    except tts.TTSCancelled:
        return
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
        await _speak_stream(
            conn, text, lambda: _soothe_evaporated(conn, trace),
            round_id=conn.tts_round_id(trace),
        )
    except Exception:  # noqa: BLE001 — 安抚语缺席无副作用,不记 degraded
        return


async def _speak_summary(conn: Connection, text: str, trace: int) -> None:
    """异步总结语音:回合已收尾后继续流出,仅抢占(trace 变)才蒸发——
    蒸发条件与安抚语不同:安抚语随回合收尾蒸发,总结语音恰恰要在收尾后播完。"""
    from app.voice import tts

    try:
        await _speak_stream(
            conn, text, lambda: conn.current_trace != trace,
            round_id=conn.tts_round_id(trace),
        )
    except tts.TTSCancelled:
        return
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
    await _speak(conn, phrases.CRISIS_HOTLINE, round_id=conn.tts_round_id())
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


_TIK_ENC: Any = None


def _tok_count(text: str) -> int | None:
    """tiktoken 估算 token 数;不可用则返回 None(调用方据此标注「未估算」)。

    首次 get_encoding 要读/下 BPE 缓存,可能几百毫秒 —— 只在诊断开启时被调用,
    且必须由测量脚本**预热**,否则那次耗时会被算进被测区间。
    """
    try:
        import tiktoken

        global _TIK_ENC
        if _TIK_ENC is None:
            _TIK_ENC = tiktoken.get_encoding("cl100k_base")
        return len(_TIK_ENC.encode(text, disallowed_special=()))
    except Exception:  # noqa: BLE001 — 诊断辅助,失败标 None,绝不影响回答
        return None


def _answer_messages(query: str, refs: list[Ref]) -> list[Message]:
    if refs:
        context = "\n\n".join(f"【{r.question}】\n{r.answer}" for r in refs)
        system = (
            "你是心栖阁的心理知识科普助手。优先依据下面的资料回答,科普口吻、简洁"
            f"(150 字内);资料没有的内容不编造;不做医疗诊断。参考资料:\n{context}"
        )
    else:
        context = ""
        system = (
            "你是心栖阁的陪伴助手。温暖、简洁地回应(80 字内),不做医疗诊断,"
            "不连续追问。"
        )
    msgs = [Message("system", system), Message("user", query)]
    from app import diag

    diag.mark(
        "prompt_shape",
        n_refs=len(refs),
        sys_chars=len(system), ctx_chars=len(context), user_chars=len(query),
        tok_sys=_tok_count(system), tok_ctx=_tok_count(context),
        tok_user=_tok_count(query),
    )
    return msgs


async def _answer_with_voice(
    conn: Connection,
    emitter: ConnEmitter,
    chunks: AsyncIterator[str],
    round_id: str,
    trace: int,
) -> bool:
    """answer 路的语音:LLM 逐字流 → 增量切句 → 逐句 TTS → audio_chunk。

    三个并发度:
        LLM 读取  →  text_q(文字帧)  +  sentence_q(句子)
        TTS 合成  ←  sentence_q       →  audio_q(wav)
        帧下发    ←  audio_q          →  ws

    为什么要有两条队列:LLM 出字很快、TTS 出声很慢(约 10 倍)。
    如果在读取 LLM 的协程里直接 await TTS,文字会被音频拖住;
    如果先攒完文本再合成,首句音频要等整段生成完 —— 两种都丢掉流式。
    分开之后:文字按 LLM 的节奏走,音频按能合成多快走多快,互不阻塞。

    帧保序:audio_q 单一消费者 + hold-one 补 final,与 emitter.stream_final 同思路。
    抢占:dead() 命中即停止发新请求;服务端那一侧由 /v1/tts/cancel 清队列。

    返回是否发出过音频帧(调用方据此决定要不要记降级)。
    """
    from app import diag
    from app.voice import tts
    from app.voice.sidecar_protocol import SentenceSplitter

    # _answer_sequence 已经 enable 过一轮;这里只在没有记录时兜底建一次,
    # 不能无条件 enable —— 那会把 RAG / provider 段的记录清掉、时间基准重置。
    if diag.env_on() and not diag.active():
        diag.enable()
    diag.mark("pump_start", round_id=round_id)

    # 首句限短:TTFB 与音文交错率都只取决于首句长度(见 config 的说明)
    splitter = SentenceSplitter(
        first_max_hanzi=config.TTS_FIRST_SENTENCE_HANZI,
    )

    def dead() -> bool:
        # 抢占判定用显式传入的 trace,不要从 round_id 字符串里拆回来 ——
        # trace 可以是 -1(未开始),拼成 "tts--1" 再 split 会拿到 "1",静默判错。
        return emitter.dead or conn.current_trace != trace

    loop = asyncio.get_running_loop()
    text_q: asyncio.Queue[str | None] = asyncio.Queue()
    sentence_q: asyncio.Queue[str | None] = asyncio.Queue()
    audio_q: asyncio.Queue[bytes | None] = asyncio.Queue()
    stats = {"sentences": 0, "chunks": 0, "errors": 0}

    async def _read_llm() -> None:
        seen = {"cum": 0, "batch": 0, "sent": 0}

        async def _tap() -> AsyncIterator[str]:
            """只做打点:标出 LLM 第一个 chunk 真正到达的时刻(不改变流语义)。"""
            first = True
            async for piece in chunks:
                if first:
                    first = False
                    diag.mark("llm_first_token")
                yield piece
            diag.mark("llm_stream_end")

        try:
            # 必须走 batched_chunks:LLM 逐字吐,直接转发就是"逐字发帧"消息风暴
            # (实测 30 字文本会变成 30 个 text_delta)。攒批规则与 stream_final 共用同一处。
            async for batch in batched_chunks(_tap()):
                seen["batch"] += 1
                seen["cum"] += len(batch)
                diag.mark(
                    "batch_out", idx=seen["batch"],
                    size=len(batch), cum=seen["cum"], head=batch[:20],
                )
                await text_q.put(batch)
                diag.mark("text_q_put", idx=seen["batch"])
                for sentence in splitter.feed(batch):
                    seen["sent"] += 1
                    diag.mark(
                        "sentence_cut", idx=seen["sent"], hanzi=len(sentence),
                        src="feed", head=sentence[:30],
                    )
                    await sentence_q.put(sentence)
                    diag.mark("sentence_queued", idx=seen["sent"])
                    stats["sentences"] += 1
            for sentence in splitter.flush():
                seen["sent"] += 1
                diag.mark(
                    "sentence_cut", idx=seen["sent"], hanzi=len(sentence),
                    src="flush", head=sentence[:30],
                )
                await sentence_q.put(sentence)
                diag.mark("sentence_queued", idx=seen["sent"])
                stats["sentences"] += 1
        finally:
            await text_q.put(None)
            await sentence_q.put(None)

    async def _synth() -> None:
        # TTS 是阻塞 IO,每句丢线程池;dead 命中后不再发起新请求。
        idx = 0
        # 抢占信号跨线程:loop 侧写、worker 侧只读(GIL 下单字节读写是原子的)。
        stop = False

        def _put(wav: bytes, idx: int, n: int) -> None:
            """audio_q 的**唯一**写入点,跑在 loop 线程,所以不需要加锁。

            dead() 判定因此也回到了 loop 线程(此前在 worker 线程里读
            emitter.dead / conn.current_trace,是跨线程读)。
            """
            nonlocal stop
            if dead():
                stop = True
                return
            audio_q.put_nowait(wav)
            diag.mark("audio_queued", idx=idx, n=n, nbytes=len(wav))
            stats["chunks"] += 1

        try:
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    diag.mark("tts_worker_drained")
                    return
                if dead():
                    continue  # 丢弃剩余排队句,不浪费一次 HTTP

                idx += 1
                diag.mark(
                    "tts_worker_get", idx=idx, hanzi=len(sentence),
                    head=sentence[:30],
                )

                def _run(sentence: str = sentence, idx: int = idx) -> int:
                    """worker 线程:每产出一块就立刻交给 loop,不整句物化。

                    此前是 ``list(generator)`` —— 整句音频全部合成完才入队,
                    于是第一块要白等最后一块(实测多等 0.36~0.87s)。
                    现在 call_soon_threadsafe 一块一块送,首块落地只差一次
                    事件循环的调度。
                    """
                    n = 0
                    diag.mark("tts_call_enter", idx=idx, hanzi=len(sentence))
                    for wav in tts.synthesize_stream_detailed(
                        sentence, request_id=round_id
                    ):
                        loop.call_soon_threadsafe(_put, wav, idx, n)
                        n += 1
                        if stop:  # 被抢占:不再往下合成,generator 就地关闭
                            break
                    diag.mark("tts_call_exit", idx=idx, n_chunks=n)
                    return n
                diag.mark("tts_call_begin", idx=idx)
                try:
                    await asyncio.to_thread(_run)
                except tts.TTSCancelled:
                    diag.mark("tts_cancelled", idx=idx)
                    return
                except tts.TTSError as exc:
                    stats["errors"] += 1
                    diag.mark("tts_error", idx=idx, detail=str(exc)[:80])
                    conn.log(
                        "degraded", level="WARN",
                        reason="tts_sentence_failed", detail=str(exc)[:120],
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 — 单句失败不杀整回合
                    stats["errors"] += 1
                    diag.mark("tts_error", idx=idx, detail=str(exc)[:80])
                    conn.log(
                        "degraded", level="WARN",
                        reason="tts_sentence_failed", detail=str(exc)[:120],
                    )
                    continue
        finally:
            audio_q.put_nowait(None)

    read_task = asyncio.create_task(_read_llm(), name=f"llm-read-{round_id}")
    synth_task = asyncio.create_task(_synth(), name=f"tts-synth-{round_id}")

    async def _emit_text() -> bool:
        """hold-one 保证末帧 final=True(与 stream_final 同思路)。"""
        pending: str | None = None
        while True:
            piece = await text_q.get()
            if piece is None:
                break
            if pending is not None:
                diag.mark("ws_text_sent", size=len(pending))
                await emitter.text(pending)
            pending = piece
        if pending is None:
            return False
        diag.mark("ws_text_sent", size=len(pending), last=True)
        await emitter.text(pending, final=True)
        return True

    async def _emit_audio() -> bool:
        """收到就发,不 hold。

        这里刻意**不**做 hold-one:hold-one 是为了给最后一块标 final=True,
        代价是每句最后一块都要压到「下一句第一块到达」才下发 —— 实测把首块音频
        从 6.6s 推到 10.0s,等于丢掉一整句的延迟。

        final 在流式路径上恒为 False:前端 round.ts 对 audio_chunk 直接 break、
        AudioQueue 也不读该字段,契约 §3.4 标注"可不依赖"。
        单发路径(危机热线/安抚语/总结/fillers)只有一块,那里 final=True 无成本。
        """
        sent = False
        n = 0
        while True:
            wav = await audio_q.get()
            if wav is None:
                break
            if dead():
                break
            diag.mark("ws_audio_sent", n=n, nbytes=len(wav))
            await conn.send_audio(wav, final=False)
            n += 1
            sent = True
        return sent

    # 文字与音频必须**并发**下发。之前串行(先把 text_q 抽干再发音频)会导致
    # 首块音频要等 LLM 整段出完才落地 —— 那就不是流式了。
    text_sent, audio_sent = await asyncio.gather(
        asyncio.create_task(_emit_text(), name=f"emit-text-{round_id}"),
        asyncio.create_task(_emit_audio(), name=f"emit-audio-{round_id}"),
    )
    await asyncio.gather(read_task, synth_task, return_exceptions=True)

    if not audio_sent and stats["errors"] == 0 and text_sent:
        conn.log("tts_absent", level="INFO", reason="no_audio_produced")
    conn.log(
        "tts_answer_done",
        sentences=stats["sentences"], chunks=stats["chunks"],
        errors=stats["errors"], audio_sent=audio_sent,
    )
    # 返回值语义必须与 stream_final 一致:**这回合有没有发过帧**。
    # 之前误返回 audio_sent,于是「语音没出来但文字正常」会被上层当成空流,
    # 再补一句兜底文案 —— 等于把回答重复一遍。
    return text_sent


async def _answer_sequence(conn: Connection, text: str, cls: Classification) -> None:
    from app import diag

    # 一回合一文件:无条件重新 enable(清掉上一回合的记录),末尾 dump+disable。
    # 之前只在首次 enable,记录会跨回合累积到同一个文件,得靠 seq_start 人工切分。
    diag_on = diag.env_on()
    if diag_on:
        diag.enable()
    diag.mark("seq_start", needs_rag=cls.needs_rag)

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
    diag.mark("rag_done", refs=len(refs))

    emitter = ConnEmitter(conn, "beck_formulation")  # answer 不画黑板,draw 不触达
    conn.current_emitter = emitter
    trace = conn.current_trace
    round_id = conn.tts_round_id(trace)
    try:
        sent = False
        try:
            diag.mark("rag_done_llm_phase_begin")
            diag.mark("provider_get_begin")
            provider = get_provider()
            diag.mark("provider_get_done")
            stream = provider.stream(_answer_messages(text, refs))
            diag.mark("llm_messages_ready")
            if config.TTS_ANSWER_VOICE:
                # 文字与音频同时流:句子泵把 LLM 流切句逐句送 TTS,首句音频不等全文。
                sent = await _answer_with_voice(conn, emitter, stream, round_id, trace)
            else:
                sent = await stream_final(emitter, stream)
        except LLMError as exc:
            conn.log("degraded", level="WARN", reason="llm_error", detail=str(exc)[:120])
        if not sent:
            conn.log("degraded", level="WARN", reason="empty_stream")
            await emitter.text(phrases.ANSWER_FALLBACK, final=True)
    finally:
        diag.mark("seq_end")
        if diag_on:
            app_logger.logger.info(
                "diag_dumped",
                path=str(diag.dump(tag=round_id)),
                round_id=round_id,
            )
            diag.disable()
        if conn.current_emitter is emitter:
            conn.current_emitter = None
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
