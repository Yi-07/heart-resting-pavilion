"""WS 网关(backend-plan §8;帧映射=发射侧唯一事实)。

- 连接即建 session_id;user_input / mood_select 入口;JSON 文本帧
- user_input 处理跑独立任务、不阻塞收包:新 user_input 即抢占——取消当前任务
  + 旧 emitter 标 dead(未发帧蒸发)→ 新回合 entry
- 每条 user_input 先过危机闸门:命中 → 危机序列 + WARN 审计 + 销毁采集态
- 未命中 → 分层判定(规则速判在前保 first_frame ≤300ms;模糊调 LLM 语义判定,
  超时/失败/低 conf 落 collect 兜底,spec §4 L3/L4):
  answer → RAG 门控 → LLM 流式直答;collect → first_frame → collect 图
- collect:AskNext/EmpathChat 后保留状态等下一条;Finish → 回合三动作
  (温层摘要+station:input+研判 mood,memory 模块降级不杀回合)+ done + 销毁;
  Escalate → 危机序列 + 销毁;重连带原 session_id → 认领恢复热层(契约 §8.4)
- LLM 失败 → 话术库降级;处理满 LLM_TIMEOUT_S → error(timeout) 兜底
- 发号:仅 draw/text_delta/audio_chunk/done 盖章(seq 预增,首帧=1);
  first_frame/error 不带不消耗;计数器=连接内存(会话内全局递增)
- 非法消息 → error(invalid_message),不崩连接;输入单源文本(语音经 /asr/transcribe
  转写回填,ADR-004);总结/危机 TTS 直发 audio_chunk,
  全部可失败跳过(音频缺席不影响文字链路)
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from asyncio import AbstractEventLoop
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import config
from app import logger as app_logger
from app.agents import (
    AskFailed,
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
from app.memory import Memory, get_memory, get_semantic
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
    SceneNoteData,
    TemplateData,
    TemplateId,
    TextDelta,
    UserInput,
    WallReply,
)

if TYPE_CHECKING:
    from app.rag.corpus import Ref

_cs_adapter: TypeAdapter[CSMsg] = TypeAdapter(CSMsg)


def _session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


def _now_iso() -> str:
    """归档时刻(报告有效期锚点);本地时区,与 reports 同基准。"""

    return datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005 — 单机原型


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
        self.note_tasks: list[asyncio.Task[None]] = []
        """回合末检索笔记写入任务(done 后异步;连接存活期自然完成,断连取消不追讨)"""

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
        template: TemplateId | None = None,
        emotion_label: str | None = None,
        round_id: str | None = None,
    ) -> None:
        # mood_select 恒 False:自动浮出废弃,心情上报由前端「今日心情」按钮主动发
        await self._send(
            FirstFrame(
                session_id=self.session_id,
                route=route,
                template=template,
                emotion_label=emotion_label,
                mood_select=False,
                text=text,
                round_id=round_id,
            )
        )
        self.log("first_frame_sent", route=route, round_id=round_id)

    async def send_draw(self, template: TemplateId, data: TemplateData) -> None:
        await self._send(Draw(seq=self._next_seq(), template=template, data=data))
        self.log("draw_sent", template=template)

    async def send_text(self, text: str, *, final: bool = False) -> None:
        await self._send(TextDelta(seq=self._next_seq(), text=text, final=final))

    async def send_done(self, *, round_id: str | None = None, station_ready: bool | None = None) -> None:
        await self._send(
            Done(
                session_id=self.session_id,
                seq=self._next_seq(),
                round_id=round_id,
                station_ready=station_ready,
            )
        )
        self.log("done", round_id=round_id, station_ready=station_ready)

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

    async def send_audio(
        self, wav: bytes, *, final: bool = True, round_id: str | None = None
    ) -> None:
        """TTS 直发一块**整句 wav**(legacy 链路)。

        final=True = 本回合最后一块(单发场景:总结/fillers);
        final=False = 流式中的一块(answer 逐句场景,最后一块在句子泵收尾时补发)。
        前端 AudioQueue 只按序连播,不读 final(ws-contract §3.4 标注"可不依赖"),
        所以这两条路径对它是透明的。

        round_id 带上后,前端按组路由仲裁(ws-contract §3.4「预置 wav 组号」):
        TTS 透传值与预置组号(preset-*)同语义——同组排队续播,新组双链 flush
        后接管,旧组迟到帧丢弃;缺组号按 legacy 入队(无隔离降级,可观测)。
        """
        if not wav:
            return
        await self._send(
            AudioChunk(
                seq=self._next_seq(),
                format="wav",
                data=base64.b64encode(wav).decode("ascii"),
                final=final,
                round_id=round_id,
            )
        )
        self.log("audio_sent", bytes_len=len(wav), final=final, round_id=round_id)

    async def send_pcm(
        self,
        pcm: bytes,
        *,
        round_id: str,
        audio_seq: int,
        sample_rate: int,
        channels: int = 1,
        final: bool = False,
    ) -> None:
        """TTS 直发一块 PCM16(realtime 链路)。

        round_id / audio_seq **原样透传** TTS 服务给的值,网关不重新生成:
        前端靠 round_id 隔离回合、靠 audio_seq 保序(ws-contract §3.4)。
        """
        if not pcm:
            return
        await self._send(
            AudioChunk(
                seq=self._next_seq(),
                format="pcm_s16le",
                data=base64.b64encode(pcm).decode("ascii"),
                final=final,
                round_id=round_id,
                audio_seq=audio_seq,
                sample_rate=sample_rate,
                channels=channels,
            )
        )
        self.log(
            "pcm_sent", bytes_len=len(pcm), audio_seq=audio_seq, round_id=round_id
        )

    # ---- TTS 回合打断 ----

    def tts_round_id(self, trace: int | None = None) -> str:
        """本回合的 TTS round_id。抢占后仍指向旧回合,供 cancel 精确命中。"""
        return f"tts-{self.current_trace if trace is None else trace}"

    def preset_round_id(self, kind: str, trace: int | None = None) -> str:
        """回合外预置语音的逻辑组号(ws-contract §3.4「预置 wav 组号」)。

        kind = mood/crisis;trace 提供组间唯一性(危机两句同 trace 同组保顺播)。
        回合内预置语音(等待话术)不在此列——携组号会丢同回合总结 PCM,实测回归。
        与 tts_round_id 前缀区分:前端按字符串相等路由,不看内部结构。
        """
        return f"preset-{kind}-{self.current_trace if trace is None else trace}"

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

    async def send_wall_reply(self) -> None:
        """留言墙回复通知(§3.7);无 seq 不进回合计数。发帧失败由调用方兜底。"""
        await self._send(WallReply(session_id=self.session_id))


# ---- 在线连接注册表(wall worker 推 wall_reply 用;跨模块只经这两个口) ----

_connections: dict[str, Connection] = {}
"""session_id → 活跃连接;同 id 重连以新代旧,断连摘除。"""


def register_connection(conn: Connection) -> None:
    _connections[conn.session_id] = conn


def unregister_connection(session_id: str) -> None:
    _connections.pop(session_id, None)


async def push_wall_reply(session_id: str) -> bool:
    """wall worker 协程内调:向该会话在线连接推 wall_reply(§3.7)。

    worker 与连接同在 lifespan 主事件循环(asyncio.create_task),直接 await。
    返回是否推到;无连接返回 False。发送失败视为连接已死:摘除注册表防泄漏,
    worker 静默跳过(留言保留未读态,下次打开拉列表)。
    """

    conn = _connections.get(session_id)
    if conn is None:
        return False
    try:
        await conn.send_wall_reply()
        return True
    except Exception:  # noqa: BLE001 — 连接已死:摘除防泄漏
        unregister_connection(session_id)
        return False


# ---- 入口 ----


async def handle_connection(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    conn.log("session_open")
    register_connection(conn)
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
        unregister_connection(conn.session_id)
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

    # user_input:抢占当前处理(分析中 cancel + 旧 emitter 标 dead → 未发帧蒸发),
    # 新任务接管;**采集态保留**(体验重构裁定:进度不丢,新输入由图当本轮回答
    # 消费,无 first_frame 无清板);轮次回答不经过此处销毁(state 仅在收尾/危机时弃)。
    # 已知边界:task.done() 判定在「done 帧已发→Task 状态翻转」的调度窗口内有
    # 误判可能(挂起态被误清、抢占后重开),间歇性,记 backlog 待单独修复
    preempted = False
    if conn.current is not None and not conn.current.done():
        conn.current.cancel()
        preempted = True
    if conn.current_emitter is not None:
        conn.current_emitter.mark_dead()
        conn.current_emitter = None
    # 打断穿透到 TTS 服务:不然后端停了,服务端还在排队出声。
    # 放在这里而不是 mark_dead 里 —— 总结语音用的是独立路径,
    # 它靠自己的 trace 比对蒸发,不需要打断服务。
    # T0 = 抢占决定的那一刻(最接近"用户点了"的 backend 侧观测点;
    # 浏览器内的真实点击时刻由前端 bench 上报,两者可对照)。
    from app.voice import tts_bench

    tts_bench.mark(
        tts_bench.T0,
        round_id=conn.tts_round_id(),
        trigger="preempt_user_input",
    )
    conn.cancel_tts()
    if preempted and conn.collect_state is not None:
        # 流式中途 cancel 的半截问句不落 pending_question(_ask 在泵返回后才赋值),
        # ask_retry 未置位——新输入走轮次分支消费,旧问句语境自然失效,无需补偿
        conn.log("preempt_collect_retained")
    conn.current = asyncio.create_task(_process_user_input(conn, msg))
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
    # 预置回执语音随文同步(契约 §4.2:预置 wav 直发,失败跳过)
    from app.voice import fillers

    wav = await asyncio.to_thread(fillers.pick_named, fillers.mood_ack_name(msg.mood))
    if wav is not None:
        await conn.send_audio(wav, round_id=conn.preset_round_id("mood"))
    await conn.send_done()


async def _process_user_input(conn: Connection, msg: UserInput) -> None:
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
        # 分层判定(spec §4 L4):classify() 内部规则速判在前(命中即返,零 LLM),
        # 规则全不命中才 LLM 语义判定;
        # 超时/失败/低 conf 均落 collect 兜底(fallback),不杀回合
        cls = await classifier.classify(text)
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
                # 采集期打岔(ADR-003):场景帧由 _answer_sequence 统一先发,answer 场景淡入
                # 接管黑板;恢复=下一 collect 轮照常发全量 draw,模板切换触发前端转场
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
                _collect_sequence(conn, trace, text, cls), timeout=config.LLM_TIMEOUT_S
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
                _collect_sequence(conn, trace, text, cls),
                timeout=config.LLM_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        # 采集态保留(同抢占语义):超时只结束本次处理,进度不丢,下一条输入继续;
        # 挂起态(打岔支线)本就不弃采集(ADR-003)
        conn.log("degraded", level="WARN", trace_id=trace, reason="timeout")
        await conn.send_error("timeout", "这次回应太慢了,先给你一句兜底")
        await conn.send_text(phrases.ANSWER_FALLBACK, final=True)
        await conn.send_done()
    except Exception as exc:  # noqa: BLE001 — 网关收口:任何异常 error 帧 + 不崩连接
        # 采集态保留(同抢占语义):异常只结束本次处理,进度不丢
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
    final=False 用于 answer 的流式路径:最后一块由句子泵收尾(见 _answer_with_voice)。
    """
    from app.voice import tts

    loop = asyncio.get_running_loop()

    def _produce() -> None:
        # 用 synthesize_stream(公共名)而不是 _detailed:单发路径不需要逐块区分
        # "打断"与"故障" —— 打断照样会冒上来(客户端内部就是转发到 _detailed),
        # 但测试桩历来挂在 synthesize_stream 上,换名会打断既有契约。
        if tts.STREAM_MODE == "pcm":
            _produce_pcm(text, round_id, dead, loop, conn, final)
            return
        for wav in tts.synthesize_stream(text, request_id=round_id):
            if dead():
                return
            asyncio.run_coroutine_threadsafe(
                conn.send_audio(wav, final=final, round_id=round_id), loop
            ).result()

    await asyncio.to_thread(_produce)


def _produce_pcm(
    text: str,
    round_id: str | None,
    dead: Callable[[], bool],
    loop: AbstractEventLoop,
    conn: Connection,
    final: bool,
) -> None:
    """realtime 链路:逐块 PCM 直发(ws-contract §3.4 的 pcm_s16le 帧)。

    与 legacy 的差别只有「交付粒度」——TTS 服务侧是同一段推理,音色语速一致。
    round_id 原样透传,网关不重新生成;audio_seq 是服务端请求内块序,单发路径
    一句一请求,透传即可(answer 句子泵的跨句重编号在 _answer_with_voice 内)。
    """
    from app.voice import tts

    for chunk in tts.synthesize_pcm_stream(text, request_id=round_id):
        if dead():
            return
        asyncio.run_coroutine_threadsafe(
            conn.send_pcm(
                chunk.pcm,
                round_id=chunk.round_id,
                audio_seq=chunk.seq,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
                final=final,
            ),
            loop,
        ).result()


async def _speak_summary(conn: Connection, text: str, trace: int) -> None:
    """异步总结语音:回合已收尾后继续流出,仅抢占(trace 变)才蒸发——
    总结语音恰恰要在回合收尾后播完,蒸发条件比打断型语音宽。"""
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


async def _speak_preset(conn: Connection, name: str, round_id: str) -> None:
    """预置语音直发(危机 P10/P11):缺文件/发送失败记 degraded 跳过——
    音频缺席不影响文字链路(危机话术正文照常发帧,契约 §6.3)。

    round_id = 预置组号(§3.4):安抚+热线两句同组,前端同组排队保顺播。
    """
    from app.voice import fillers

    try:
        wav = await asyncio.to_thread(fillers.pick_named, name)
        if wav is not None:
            await conn.send_audio(wav, round_id=round_id)
        else:
            conn.log("degraded", level="WARN", reason="preset_wav_missing", name=name)
    except Exception as exc:  # noqa: BLE001 — 发送失败(WS 断开等):音频链路静默收尾
        conn.log("degraded", level="WARN", reason="preset_wav_failed", detail=str(exc)[:120])


async def _crisis_sequence(conn: Connection) -> None:
    rid = conn.preset_round_id("crisis")
    await conn.send_first_frame(route="crisis", text=phrases.CRISIS_SOOTHE)
    # 危机话术全部预置 wav 随文同步(契约 §6.3;P10 安抚/P11 热线)
    await _speak_preset(conn, "crisis_soothe", rid)
    await conn.send_draw("scene_crisis", SceneNoteData(note=phrases.CRISIS_SCENE_NOTE))
    await conn.send_text(phrases.CRISIS_HOTLINE, final=True)
    await _speak_preset(conn, "crisis_hotline", rid)
    await conn.send_done()


# ---- collect(每条 user_input=一次短图调用,backend-plan §3) ----


async def _collect_sequence(conn: Connection, trace: int, text: str, cls: Classification) -> None:
    state = conn.collect_state
    if state is None:
        # entry:first_frame(≤300ms 语义,规则速判)+ 建态;抢占不清采集态后,
        # 这里只剩首次进入/收尾后/危机后重开三种;
        # 热层 snapshot 恢复上下文(重连/续话,契约 §8.4;记忆不可用降级空档)
        # 板式接力:建态=scene_default 暖场景开场,图内首次实质披露切
        # scene_focus;template 单源在 state
        state = CollectState(
            session_id=conn.session_id,
            route="collect",
            template="scene_default",
            emotion_label=cls.emotion_label,
            confidence=cls.confidence,
            max_rounds=config.COLLECT_MAX_ROUNDS,
        )
        from app.board import AssetSelector  # 懒加载:目录读盘只进 collect 路径

        state.asset_selector = AssetSelector()
        state.session_context = await get_memory().snapshot(conn.session_id)
        # 语义记忆召回(危机闸门判定之后;查询=首轮输入,后续轮次输入在图内,不重召回)
        # 降级纪律:失败返回空列表;注入由 graph 侧消费 state.recalled_memories
        state.recalled_memories = await get_semantic().recall(text)
        if state.recalled_memories:
            conn.log("semantic_recalled", ids=[m["id"] for m in state.recalled_memories])
        # 轮次标识=后端权威(session 级高水位,跨连接/重启/治理清除都不复用);
        # 分配失败(如 SQLite 不可用)= None → 本轮不产素材,done 带 station_ready=false
        from app.station.reports import (
            get_reports,  # 懒加载:station 包只进 collect 路径
        )

        state.round_id = get_reports().next_round_id(conn.session_id)
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
        await conn.send_first_frame(
            route="collect",
            template=state.template,  # first_frame 随开场板式(scene_default)
            emotion_label=cls.emotion_label,
            text="",  # 开场不设安抚语(契约「3.1 first_frame」):第一句话由问话 LLM 生成后随流到达
            round_id=state.round_id,  # R4 裁定:mood_select 恒 False(本地 T5 终态),只取 PR 的 round_id
        )
        conn.log("collection_start", trace_id=trace)
    # 轮次回答:同回合继续,无 first_frame(契约 §6.2)
    state.turns.append(Turn(role="user", text=text))

    # 板式接力:emitter 每帧读 state.template,图内中途切板式即时生效
    emitter = ConnEmitter(conn, lambda: state.template or "scene_default")
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
) -> bool:
    """Finish 归档三动作(shield 下执行,断连取消不打断;B2 发现⑤)。

    返回素材是否归档成功(供 Done.station_ready);round_id 分配失败时跳过素材
    写入并明确记 degraded——链接显式不可用,不静默进入生成。"""

    archived = False
    if state.round_id is None:
        conn.log("degraded", level="WARN", trace_id=trace, reason="round_id_alloc_failed")
    else:
        state.collected_at = _now_iso()
        archived = await memory.save_station_input(
            conn.session_id,
            state.round_id,
            state.formulation.model_dump_json(by_alias=True),
            summary,
            state.collected_at,
        )
    await memory.save_round_summary(conn.session_id, summary)
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
        round_id=state.round_id,
        station_ready=archived,
        summary_len=len(summary),
    )
    _spawn_note_task(conn, state, trace)
    # 方案书回合末自动生成(spec「L5 · 计划制定者」):归档后后台起任务,done
    # 照发不等待;素材损坏/记忆降级由 station 侧降级纪律兜底,不杀回合收尾。
    # 归档成功才触发(R1 裁定):素材带轮次键与归档时刻,station 侧按 (sid,round) 寻址
    if archived and state.round_id is not None:
        try:
            state_, material = await memory.load_station_input(conn.session_id, state.round_id)
            if state_ == "ok" and material is not None:
                from app.station.routes import start_auto_generate

                await start_auto_generate(conn.session_id, state.round_id, material)
            else:
                conn.log(
                    "degraded", level="WARN",
                    reason="station_auto_material_missing",
                    detail=f"state={state_}",
                )
        except Exception as exc:  # noqa: BLE001 — 自动生成触发失败不杀回合收尾
            conn.log("degraded", level="WARN", reason="station_auto_generate_failed", detail=str(exc)[:120])
    if summary:
        # 总结语音异步流出(done 后到达,抢占即蒸发):不占 60s 处理窗口,
        # 长总结不再触发 timeout 兜底;ws-contract §6.2 时序措辞已同步
        asyncio.create_task(_speak_summary(conn, summary, trace))
    return archived


def _spawn_note_task(conn: Connection, state: CollectState, trace: int) -> None:
    """检索笔记异步写入(回合末,done 后跑,不碰回合时延;spec L7 语义层)。

    回合内已召回的语义记忆暂存 state.recalled_memories(注入点写入),
    供笔记 LLM 做状态闭环(判「本轮化解了哪些」);召回失败/库空=空列表,闭环自然跳过。
    LLM 失败/超时降级 formulation 拼接(parse_notes 整段兜底);写入全降级(WARN)。
    """
    from app.agents.analysis import generate_note_raw

    recalled = list(state.recalled_memories)

    async def _run() -> None:
        try:
            raw = await asyncio.wait_for(
                generate_note_raw(state, recalled), timeout=config.SEMANTIC_MEM_NOTE_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 — LLM 失败降级确定性拼接
            conn.log(
                "degraded",
                level="WARN",
                reason="semantic_note_llm_failed",
                detail=str(exc)[:120],
            )
            raw = " ".join(
                part
                for part in (state.formulation.situation, state.formulation.thought)
                if part
            )
            if not raw.strip():
                return
        await get_semantic().save_notes(
            state.session_id,
            state.round_index,
            raw,
            mood_label=state.formulation.emotion.label,
            intensity=state.formulation.emotion.intensity,
        )

    conn.note_tasks.append(asyncio.create_task(_run()))


async def _settle_collect_event(
    conn: Connection, trace: int, event: CollectEvent
) -> None:
    if isinstance(event, Finish):
        # 回合结束三动作(backend-plan §3.3):温层摘要 → station:input(带轮次) → 弃 state;
        # 另落研判 mood(复核后标签进冷层情绪趋势)。Escalate 不落(危机不记情绪)
        state = conn.collect_state
        conn.collect_state = None
        station_ready: bool | None = None
        if state is not None:
            memory = get_memory()
            summary = event.summary or ""
            try:
                station_ready = await asyncio.shield(
                    _archive_round(memory, conn, state, summary, trace, event.cause)
                )
            except asyncio.CancelledError:
                # 断连取消不得打断归档(B2 发现⑤):shield 让写入继续,这里只落痕
                conn.log("degraded", level="WARN", reason="finish_archival_interrupted")
                raise
        # station_ready 只在 collect Finish 携带:素材未归档成功时前端不启用该轮入口
        await conn.send_done(
            round_id=state.round_id if state is not None else None,
            station_ready=station_ready,
        )
    elif isinstance(event, Escalate):
        conn.collect_state = None
        conn.log("route_decided", trace_id=trace, route="crisis", via="escalate")
        await _crisis_sequence(conn)
    elif isinstance(event, AskFailed):
        # 问话 LLM 失败(ws-contract §3.8/§8):error 帧 + 采集态挂起待重试;
        # 不发预置问句兜底(不掩盖错误),也不弃 state——下一条输入重试
        state = conn.collect_state
        if state is not None:
            state.ask_retry = True
        conn.log("degraded", level="WARN", trace_id=trace, reason="ask_llm_failed", source=event.source)
        await conn.send_error(
            "ask_llm_failed", "小栖这边没把话组织好,先告诉我你的想法,我们再继续"
        )
    elif isinstance(event, AskNext):
        # ADR-005:assistant 问句入热层轮次(与发帧文本一致——问话全文,无独立 confirm)
        await get_memory().append_turn(conn.session_id, "assistant", event.question)
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


def _answer_messages(
    query: str,
    refs: list[Ref],
    memories: list[dict[str, Any]] | None = None,
    history: list[Turn] | None = None,
) -> list[Message]:
    """answer prompt:RAG 引用 + 对话历史 + 语义记忆注入(记忆行只做「想起」,
    不引申不翻旧账——已化解条目等 LLM 临场取舍,LLM 失败时无记忆注入不影响回答)。
    history=热层 recent_turns 原话(末条 user 轮即本轮查询,注入时排除)。
    """
    from app.agents.ask import turns_context

    context = ""
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
    history_ctx = turns_context(history or [], exclude_last_user=True)
    if history_ctx:
        system += f"\n\n刚才的对话:\n{history_ctx}"
    if memories:
        mem_desc = "\n".join(
            f"- (相关度 {m['cos']}, {m['date']}{' ,较早' if m.get('aged') else ''}) {m['text']}"
            for m in memories
        )
        system += (
            "\n\n你可能还记得用户之前聊过(自然衔接即可,用户没提就别主动翻旧账;"
            "若与当前话题无关就忽略):\n" + mem_desc
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
    """answer 路的语音:句子泵统一实现(collect 问话同构复用,agents/sentence_pump)。

    LLM 逐字流 → 攒批发帧 + 增量切句 → 逐句 TTS → audio_chunk;文字与音频
    两条队列并发下发,互不阻塞(细节与理由见 sentence_pump 模块 docstring)。

    返回是否发出过文字帧(调用方据此决定要不要兜底/记降级,语义与 stream_final 一致)。
    """
    from app import diag

    # _answer_sequence 已经 enable 过一轮;这里只在没有记录时兜底建一次,
    # 不能无条件 enable —— 那会把 RAG / provider 段的记录清掉、时间基准重置。
    if diag.env_on() and not diag.active():
        diag.enable()
    from app.agents.sentence_pump import run_sentence_pump

    return await run_sentence_pump(
        conn,
        emitter,
        chunks,
        round_id,
        trace,
        first_max_hanzi=config.TTS_FIRST_SENTENCE_HANZI,
    )


async def _answer_sequence(conn: Connection, text: str, cls: Classification) -> None:
    from app import diag

    # 一回合一文件:无条件重新 enable(清掉上一回合的记录),末尾 dump+disable。
    # 之前只在首次 enable,记录会跨回合累积到同一个文件,得靠 seq_start 人工切分。
    diag_on = diag.env_on()
    if diag_on:
        diag.enable()
    diag.mark("seq_start", needs_rag=cls.needs_rag)

    # 纯 answer 回合起点发场景帧(空板缺口):同模板不转场、同 data 不重画,前端幂等
    await conn.send_draw("scene_answer", SceneNoteData(note=None))
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
            conn.log(
                "rag_retrieved",
                trace_id=conn.current_trace,
                library=RagLibrary.KNOWLEDGE.value,
                ref_ids=[ref.id for ref in refs],
                ref_count=len(refs),
                ref_ranks=[
                    {"rank": rank, "id": ref.id, "score": ref.score}
                    for rank, ref in enumerate(refs, start=1)
                ],
            )
        except Exception as exc:  # noqa: BLE001 — RAG 失败/未就绪都降级直答,不杀回合
            conn.log("degraded", level="WARN", reason="rag_failed", detail=str(exc)[:120])
            refs = []
    diag.mark("rag_done", refs=len(refs))

    # 语义记忆同步召回(危机闸门判定之后才到这里——历史不参与路由判定,spec L7 红线):
    # 查询 = 本轮输入 + 热层最近话题(查询增强);降级纪律全吞异常,空列表=无注入
    memory_ctx = await get_memory().snapshot(conn.session_id)
    recent_topics = " ".join(
        t.text for t in memory_ctx.recent_turns[-3:]
    )
    memories = await get_semantic().recall(text, recent_topics=recent_topics)
    if memories:
        conn.log("semantic_recalled", ids=[m["id"] for m in memories])
    diag.mark("semantic_done", n=len(memories))

    emitter = ConnEmitter(conn, "scene_answer")  # answer 不走 collect 图,emitter 仅兜底用
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
            stream = provider.stream(
                _answer_messages(text, refs, memories, memory_ctx.recent_turns)
            )
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
        if conn.current_emitter is emitter:
            conn.current_emitter = None
    diag.mark("seq_end")
    if diag_on:
        app_logger.logger.info(
            "diag_dumped",
            path=str(diag.dump(tag=round_id)),
            round_id=round_id,
        )
        diag.disable()
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
