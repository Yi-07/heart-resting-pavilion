"""GPT-SoVITS 推理引擎 —— 本服务唯一的深模块。

对上层(server.py)只暴露四件事:
    load()                          后台加载模型,幂等
    synthesize(text, round_id, ...) 逐句产出完整 wav(阻塞生成器,须在专用线程里拉)
    cancel(round_id, cascade)        打断:立刻停当前句 + 清空排队
    snapshot()                      状态快照,给 /ready 与 /v1/health

三件 api_v2.py 做错、这里必须做对的事:

1. **不阻塞事件循环。** 合成是同步生成器,由 server 的生产者线程拉取。
2. **串行且可打断。** GPT-SoVITS 的 TTS 实例共享 prompt_cache 与模型对象,
   非线程安全,因此用一把锁严格串行;打断靠 token 在"块"这一粒度检查,
   不靠杀线程(杀线程会漏掉 CUDA 同步,导致显存不释放)。
3. **有输入护栏。** 上游对文本长度、音频字节数毫无限制,单个恶意/失控请求
   就能把显存打满;另外 g2p_en 在本机缺 nltk cmudict,任何 ASCII 字母都会
   抛 LookupError 并卡 12s,必须在进模型前挡掉。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from wave import open as wave_open

from .protocol import has_ascii_letter, split_for_tts
from .settings import ROOT, Settings, get_settings


class GuardError(ValueError):
    """输入守卫拒绝:带 code,由 server 映射为 HTTP 400。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class EngineBusy(RuntimeError):
    """排队超时或模型不可用:由 server 映射为 HTTP 503。"""


@dataclass
class SentenceAudio:
    """一句的完整产物。wav 是标准 RIFF/PCM,前端可直接解码播放。"""

    index: int
    sentence: str
    wav: bytes
    sample_rate: int
    duration_s: float
    ttfb_s: float
    gen_s: float
    n_chunks: int


@dataclass
class CancelToken:
    round_id: str
    created: float = field(default_factory=time.perf_counter)
    started: bool = False
    finished: bool = False
    _flag: bool = False

    def cancel(self) -> None:
        self._flag = True

    @property
    def cancelled(self) -> bool:
        return self._flag


def _wav_from_float32(samples: Any, sample_rate: int) -> tuple[bytes, float]:
    """float32 [-1,1] numpy 数组 → 16bit PCM 的完整 wav 字节。

    显式转 int16 而不走 soundfile:少一个依赖,且输出格式确定
    (soundfile 对 float 输入默认落 PCM_16,但那是隐式行为)。
    """
    import numpy as np  # noqa: PLC0415 — 重依赖懒加载,勿在模块顶部 import

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return b"", 0.0
    peak = float(np.abs(arr).max())
    if peak > 1.0:  # 越界会削顶,先归一化
        arr = arr / peak
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16)

    buf = BytesIO()
    with wave_open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue(), arr.size / sample_rate


class TTSEngine:
    """串行、可打断、带护栏的 GPT-SoVITS 推理引擎。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._cfg = settings or get_settings()
        self._state_lock = threading.Lock()
        self._tts: Any = None
        self._ready = False
        self._error: str | None = None
        self._load_started = False

        # 严格串行:同一时刻只有一个推理在跑
        self._infer_lock = threading.Lock()
        self._rounds: dict[str, CancelToken] = {}
        self._rounds_lock = threading.Lock()
        self._started_at = time.time()
        self._counters = {"requests": 0, "sentences": 0, "cancelled": 0, "errors": 0}

    # ---------------- 生命周期 ----------------

    def load(self) -> None:
        """加载模型。可能跑很久,设计上就是给后台线程调的。"""
        with self._state_lock:
            if self._load_started:
                return
            self._load_started = True

        try:
            os.chdir(ROOT)
            for p in (str(ROOT), str(ROOT / "GPT_SoVITS")):
                if p not in sys.path:
                    sys.path.insert(0, p)

            # 上游 TextPreprocessor 通过全局 i18n 查语言表;这里保持与 api_v2.py 一致地
            # 先把 locale 装好。失败不阻断启动 —— P0 已修掉类体内的 import i18n。
            try:
                from tools.i18n.i18n import I18nAuto  # noqa: PLC0415

                I18nAuto()
            except Exception as exc:  # noqa: BLE001 — 只是提示,不是致命
                print(f"[tts_service] i18n 初始化跳过: {exc}", flush=True)

            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: PLC0415

            cfg = TTS_Config(self._cfg.tts_config)
            tts = TTS(cfg)

            self._validate_voice()

            with self._state_lock:
                self._tts = tts
                self._ready = True
                self._error = None
        except Exception as exc:  # noqa: BLE001 — 失败要能被 /ready 看到
            with self._state_lock:
                self._ready = False
                self._error = f"{type(exc).__name__}: {exc}"[:300]
            traceback.print_exc()

    def _validate_voice(self) -> None:
        cfg = self._cfg
        if not cfg.ref_audio_path:
            raise RuntimeError(
                "未配置参考音频:设置 GPT_SOVITS_REF_AUDIO,或 GPT_SOVITS_VOICE "
                "指向 reference/voice_list.json 里的音色名"
            )
        ref = Path(cfg.ref_audio_path)
        if not ref.is_absolute():
            ref = ROOT / ref
        if not ref.exists():
            raise RuntimeError(f"参考音频不存在: {ref}")
        if not cfg.prompt_text:
            raise RuntimeError(
                "未配置参考音频文本:设置 GPT_SOVITS_PROMPT_TEXT,或让 "
                "GPT_SOVITS_VOICE 命中 reference/voice_list.json"
            )

    # ---------------- 状态 ----------------

    @property
    def ready(self) -> bool:
        with self._state_lock:
            return self._ready

    @property
    def error(self) -> str | None:
        with self._state_lock:
            return self._error

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            ready, err = self._ready, self._error
        with self._rounds_lock:
            active = [
                {"round_id": r.round_id, "started": r.started, "finished": r.finished}
                for r in self._rounds.values()
            ]
        return {
            "ready": ready,
            "error": err,
            "uptime_s": round(time.time() - self._started_at, 1),
            "voice": self._cfg.voice,
            "ref_audio": self._cfg.ref_audio_path,
            "model_version": self._cfg.version,
            "inference_busy": self._infer_lock.locked(),
            "rounds": active,
            "counters": dict(self._counters),
        }

    # ---------------- 输入守卫 ----------------

    def guard(self, text: str) -> list[str]:
        """校验并分句。任一不合规抛 GuardError(→ HTTP 400)。"""
        cfg = self._cfg

        if not text or not text.strip():
            raise GuardError("text 不能为空", "empty_text")

        n = len(text)
        if n > cfg.max_text_len:
            raise GuardError(
                f"text 超长:{n} 字符,上限 {cfg.max_text_len}", "text_too_long"
            )

        # g2p_en 在本机缺 nltk cmudict,含 ASCII 字母会抛 LookupError 且卡 12s。
        # 与其让它把整个进程拖住,不如立刻 400。
        if has_ascii_letter(text):
            raise GuardError(
                "text 含 ASCII 英文字母,当前环境的 g2p_en 缺 nltk cmudict 语料,"
                "无法合成英文;请仅使用中文文本",
                "ascii_unsupported",
            )

        sentences = split_for_tts(text, max_len=cfg.max_sentence_chars)
        if not sentences:
            raise GuardError("text 分句后为空", "no_sentence")
        if len(sentences) > cfg.max_sentences:
            raise GuardError(
                f"分句数 {len(sentences)} 超过上限 {cfg.max_sentences}", "too_many_sentences"
            )
        return sentences

    # ---------------- 打断 ----------------

    def _register(self, round_id: str) -> CancelToken:
        token = CancelToken(round_id=round_id)
        with self._rounds_lock:
            self._rounds[round_id] = token
        with self._state_lock:
            self._counters["requests"] += 1
        return token

    def _release(self, token: CancelToken) -> None:
        token.finished = True
        with self._rounds_lock:
            self._rounds.pop(token.round_id, None)

    def cancel(self, round_id: str, cascade: bool = True) -> dict[str, Any]:
        """打断一个回合。

        cascade=True 时同时清掉所有"还没开始跑"的排队回合 ——
        主程序取消后必须立刻把队列清空,不能让旧回合接着出声。
        """
        with self._rounds_lock:
            token = self._rounds.get(round_id)
            others = [
                t for rid, t in self._rounds.items()
                if rid != round_id and not t.started and not t.finished
            ]
        if token is not None:
            token.cancel()
        dropped = []
        if cascade:
            for t in others:
                t.cancel()
                dropped.append(t.round_id)
        if token is not None or dropped:
            with self._state_lock:
                self._counters["cancelled"] += 1
        return {
            "round_id": round_id,
            "cancelled": token is not None,
            "state": _token_state(token),
            "cascaded": dropped,
        }

    # ---------------- 合成 ----------------

    def _build_req(self, sentence: str, voice: str | None) -> dict[str, Any]:
        cfg = self._cfg
        if voice and voice != cfg.voice:
            ref = f"reference/{voice}.wav"
            prompt = cfg.voices.get(voice, "")
        else:
            ref = cfg.ref_audio_path
            prompt = cfg.prompt_text
        return {
            "text": sentence,
            "text_lang": cfg.text_lang,
            "ref_audio_path": ref,
            "aux_ref_audio_paths": [],
            "prompt_text": prompt,
            "prompt_lang": cfg.prompt_lang,
            "top_k": cfg.top_k,
            "top_p": cfg.top_p,
            "temperature": cfg.temperature,
            "text_split_method": cfg.text_split_method,
            "batch_size": 1,
            "batch_threshold": 0.75,
            "split_bucket": True,
            "speed_factor": cfg.speed_factor,
            "fragment_interval": cfg.fragment_interval,
            "seed": cfg.seed,
            "media_type": "wav",
            "streaming_mode": cfg.streaming_mode,
            "return_fragment": False,
            "fixed_length_chunk": False,
            "parallel_infer": cfg.parallel_infer,
            "repetition_penalty": cfg.repetition_penalty,
            "sample_steps": 32,
            "super_sampling": False,
            "overlap_length": cfg.overlap_length,
            "min_chunk_length": cfg.min_chunk_length,
        }

    def synthesize(
        self,
        text: str,
        *,
        round_id: str,
        voice: str | None = None,
    ) -> Iterator[SentenceAudio]:
        """逐句产出完整 wav。**阻塞生成器,必须在专用线程里消费。**

        生命周期:注册 token → 排队等锁(带超时) → 逐句合成 → 逐句检查取消。
        取消发生在句中时,已产出的半句直接丢弃 —— 宁可少一句,也不让旧音频漏出去。
        """
        if not self.ready:
            raise EngineBusy(self.error or "模型未就绪")

        sentences = self.guard(text)
        token = self._register(round_id)

        acquired = self._infer_lock.acquire(timeout=self._cfg.queue_wait_timeout_s)
        if not acquired:
            self._release(token)
            raise EngineBusy(f"排队超时({self._cfg.queue_wait_timeout_s}s),推理被占用")

        try:
            if token.cancelled:
                return
            token.started = True
            tts = self._tts

            total_bytes = 0
            for i, sentence in enumerate(sentences):
                if token.cancelled:
                    break
                t_sent = time.perf_counter()
                req = self._build_req(sentence, voice)

                pieces: list[Any] = []
                sample_rate = 0
                n_chunks = 0
                ttfb = 0.0
                aborted = False

                for chunk_sr, chunk in tts.run(req):
                    if token.cancelled:  # 句中打断:丢弃半句
                        aborted = True
                        break
                    if n_chunks == 0:
                        ttfb = time.perf_counter() - t_sent
                    sample_rate = int(chunk_sr) or sample_rate
                    pieces.append(chunk)
                    n_chunks += 1

                if aborted or token.cancelled:
                    break
                if n_chunks == 0:
                    continue

                import numpy as np  # noqa: PLC0415

                merged = np.concatenate([np.asarray(p).reshape(-1) for p in pieces])
                wav, duration = _wav_from_float32(merged, sample_rate)
                if not wav:
                    continue

                total_bytes += len(wav)
                if total_bytes > self._cfg.max_audio_bytes:
                    raise GuardError(
                        f"音频字节数超过上限 {self._cfg.max_audio_bytes}", "audio_too_large"
                    )

                with self._state_lock:
                    self._counters["sentences"] += 1

                yield SentenceAudio(
                    index=i,
                    sentence=sentence,
                    wav=wav,
                    sample_rate=sample_rate,
                    duration_s=round(duration, 3),
                    ttfb_s=round(ttfb, 4),
                    gen_s=round(time.perf_counter() - t_sent, 4),
                    n_chunks=n_chunks,
                )
        except Exception:
            with self._state_lock:
                self._counters["errors"] += 1
            raise
        finally:
            self._release(token)
            self._infer_lock.release()


def _token_state(token: CancelToken | None) -> str:
    if token is None:
        return "not_found"
    if token.cancelled:
        return "cancelled"
    if token.finished:
        return "finished"
    if token.started:
        return "running"
    return "queued"
