"""句子泵:LLM 流 → 文字攒批发帧 + SentenceSplitter 逐句 TTS(backend-plan §8)。

answer 直答与 collect 问话共用同一条泵(契约 §6.2「与 answer 同构」)。三条并发度:
    LLM 读取  →  text_q(文字帧)  +  sentence_q(句子)
    TTS 合成  ←  sentence_q       →  audio_q(wav/PCM 块)
    帧下发    ←  audio_q          →  ws

两条队列的理由:LLM 出字快、TTS 出声慢(约 10 倍)——在读取协程里直接 await TTS
文字会被拖住;先攒完文本再合成则首句音频要等全文,两种都丢掉流式。分开后文字按
LLM 节奏走、音频按合成多快走多快,互不阻塞。帧保序:audio_q 单一消费者。

由 gateway._answer_with_voice 抽取而来,行为不变;TTS 路由(STREAM_MODE 分派、
线程池、round_id 校验)留在网关侧的 produce_sentence 工厂,本模块只管编排。
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app import diag
from app.agents.emitter import ConnEmitter, batched_chunks

ProduceFn = Callable[[str, int], Awaitable[None]]
"""单句合成回调 produce(sentence, idx):网关装配;idx 为泵内句序号(打点用)。"""


def make_produce_sentence(
    conn: Any,
    round_id: str,
    audio_q: "asyncio.Queue[Any | None]",
    dead: Callable[[], bool],
    stats: dict[str, int],
) -> ProduceFn:
    """装配单句合成回调(网关侧;STREAM_MODE 分派唯一住址)。

    TTS 是阻塞 IO 丢线程池跑;每产出一块立刻 call_soon_threadsafe 交给 loop,
    不整句物化(此前 list(generator) 整句合成完才入队,首块白等 0.36~0.87s)。
    PCM 跨句 audio_seq 在此重编号(服务端 seq 是每请求号,直接透传会 [0,1,2] 重复);
    round_id 不动——那是身份,seq 只是块序。dead() 命中即停,服务端队列由 cancel 清。
    """
    from app.voice import tts

    loop = asyncio.get_running_loop()
    pcm_mode = tts.STREAM_MODE == "pcm"
    pcm_seq_base = 0
    # 抢占信号跨线程:loop 侧写、worker 侧只读(GIL 下单字节读写是原子的)
    stop = False

    def _put(wav: bytes, idx: int, n: int) -> None:
        """audio_q 的唯一写入点,跑在 loop 线程(dead 判定因此回到 loop 线程)。"""
        nonlocal stop
        if dead():
            stop = True
            return
        audio_q.put_nowait(wav)
        diag.mark("audio_queued", idx=idx, n=n, nbytes=len(wav))
        stats["chunks"] += 1

    def _put_pcm(chunk: Any, idx: int, n: int) -> None:
        """PCM 块同款写入点;round_id 冲突判在这里。"""
        nonlocal stop, pcm_seq_base
        if dead():
            stop = True
            return
        if chunk.round_id != round_id:
            # 同一 request 内 round_id 自相矛盾 = 协议错误:丢弃并停该回合合成,绝不静默下发
            stats["errors"] += 1
            stop = True
            from app.voice import tts_bench

            tts_bench.mark(
                tts_bench.PROTOCOL_MISMATCH,
                round_id=round_id,
                frame_round_id=chunk.round_id,
                stage="gateway_pcm",
            )
            from app import logger as app_logger

            app_logger.logger.error(
                "tts_pcm_round_id_mismatch want={} got={}",
                round_id,
                chunk.round_id,
            )
            conn.log(
                "degraded",
                level="ERROR",
                reason="tts_round_id_mismatch",
                want=round_id,
                got=chunk.round_id,
            )
            return
        audio_q.put_nowait((chunk, pcm_seq_base))
        pcm_seq_base += 1
        diag.mark("audio_queued", idx=idx, n=n, nbytes=len(chunk.pcm))
        stats["chunks"] += 1

    async def produce(sentence: str, idx: int) -> None:
        nonlocal stop
        if dead():
            return
        diag.mark("tts_call_begin", idx=idx, hanzi=len(sentence))

        def _run() -> int:
            n = 0
            diag.mark("tts_call_enter", idx=idx, hanzi=len(sentence))
            if pcm_mode:
                for chunk in tts.synthesize_pcm_stream(sentence, request_id=round_id):
                    loop.call_soon_threadsafe(_put_pcm, chunk, idx, n)
                    n += 1
                    if stop:  # 被抢占:不再往下合成,generator 就地关闭
                        break
            else:
                for wav in tts.synthesize_stream_detailed(sentence, request_id=round_id):
                    loop.call_soon_threadsafe(_put, wav, idx, n)
                    n += 1
                    if stop:
                        break
            diag.mark("tts_call_exit", idx=idx, n_chunks=n)
            return n

        try:
            await asyncio.to_thread(_run)
        except tts.TTSCancelled:
            diag.mark("tts_cancelled", idx=idx)
        except tts.TTSError as exc:
            stats["errors"] += 1
            diag.mark("tts_error", idx=idx, detail=str(exc)[:80])
            conn.log(
                "degraded", level="WARN", reason="tts_sentence_failed", detail=str(exc)[:120]
            )
        except Exception as exc:  # noqa: BLE001 — 单句失败不杀整回合
            stats["errors"] += 1
            diag.mark("tts_error", idx=idx, detail=str(exc)[:80])
            conn.log(
                "degraded", level="WARN", reason="tts_sentence_failed", detail=str(exc)[:120]
            )

    return produce


async def run_sentence_pump(
    conn: Any,
    emitter: ConnEmitter,
    chunks: AsyncIterator[str],
    round_id: str,
    trace: int,
    *,
    first_max_hanzi: int,
    done_event: str = "tts_answer_done",
) -> bool:
    """句子泵主入口:文字攒批发帧 + 逐句 TTS;返回是否发出过文字帧。

    返回值语义与 stream_final 一致(这回合有没有发过帧):「语音没出来但文字正常」
    不算空流,调用方不补兜底文案。first_max_hanzi 只作用第一句(TTFB 旋钮)。
    """
    from app.voice.sentence_split import SentenceSplitter

    diag.mark("pump_start", round_id=round_id)
    splitter = SentenceSplitter(first_max_hanzi=first_max_hanzi)

    def dead() -> bool:
        # 抢占判定用显式 trace,不从 round_id 字符串拆回(trace 可为 -1,拆分会静默判错)
        return emitter.dead or conn.current_trace != trace

    text_q: asyncio.Queue[str | None] = asyncio.Queue()
    sentence_q: asyncio.Queue[str | None] = asyncio.Queue()
    audio_q: asyncio.Queue[Any | None] = asyncio.Queue()
    """队列元素是 bytes(legacy wav)或 PcmChunk(realtime),由 STREAM_MODE 决定。"""
    stats = {"sentences": 0, "chunks": 0, "errors": 0}
    produce = make_produce_sentence(conn, round_id, audio_q, dead, stats)

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
            async for batch in batched_chunks(_tap()):
                seen["batch"] += 1
                seen["cum"] += len(batch)
                diag.mark("batch_out", idx=seen["batch"], size=len(batch), cum=seen["cum"])
                await text_q.put(batch)
                for sentence in splitter.feed(batch):
                    seen["sent"] += 1
                    diag.mark("sentence_cut", idx=seen["sent"], hanzi=len(sentence), src="feed")
                    await sentence_q.put(sentence)
                    stats["sentences"] += 1
            for sentence in splitter.flush():
                seen["sent"] += 1
                diag.mark("sentence_cut", idx=seen["sent"], hanzi=len(sentence), src="flush")
                await sentence_q.put(sentence)
                stats["sentences"] += 1
        finally:
            await text_q.put(None)
            await sentence_q.put(None)

    async def _synth() -> None:
        idx = 0
        try:
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    diag.mark("tts_worker_drained")
                    return
                if dead():
                    continue  # 丢弃剩余排队句,不浪费一次 HTTP
                idx += 1
                diag.mark("tts_worker_get", idx=idx, hanzi=len(sentence))
                await produce(sentence, idx)
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

    async def _emit_audio() -> None:
        """收到就发,不 hold(hold 会把每句最后一块压到下一句首块到达才下发,实测
        首块音频 6.6s→10.0s)。final 恒 False:前端不依赖(契约 §3.4「可不依赖」),
        单发路径(危机热线/预置话术)另有 final=True 出口。"""
        from app.voice import tts as _tts_mod

        pcm_mode = _tts_mod.STREAM_MODE == "pcm"
        while True:
            item = await audio_q.get()
            if item is None:
                break
            if dead():
                break
            if pcm_mode:
                chunk, audio_seq = item
                diag.mark("ws_pcm_sent", nbytes=len(chunk.pcm))
                await conn.send_pcm(
                    chunk.pcm,
                    round_id=chunk.round_id,
                    # 回合内全局号,跨句连续(ws-contract §3.4;服务端 seq 是每请求号)
                    audio_seq=audio_seq,
                    sample_rate=chunk.sample_rate,
                    channels=chunk.channels,
                    final=False,
                )
            else:
                diag.mark("ws_audio_sent", nbytes=len(item))
                await conn.send_audio(item, final=False, round_id=round_id)

    # 文字与音频必须**并发**下发:串行(先抽干 text_q 再发音频)会把首块音频
    # 拖到 LLM 整段出完才落地,那就不是流式了
    text_sent, _ = await asyncio.gather(
        asyncio.create_task(_emit_text(), name=f"emit-text-{round_id}"),
        asyncio.create_task(_emit_audio(), name=f"emit-audio-{round_id}"),
    )
    await asyncio.gather(read_task, synth_task, return_exceptions=True)

    if stats["chunks"] == 0 and stats["errors"] == 0 and text_sent:
        conn.log("tts_absent", level="INFO", reason="no_audio_produced")
    conn.log(
        done_event,
        sentences=stats["sentences"], chunks=stats["chunks"],
        errors=stats["errors"], text_sent=text_sent,
    )
    return text_sent
