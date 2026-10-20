"""GPT-SoVITS 推理引擎 —— 本服务唯一的深模块。

对上层(server.py)只暴露五件事:
    load()                          后台加载模型,幂等
    synthesize(text, round_id, ...) 逐句产出完整 wav(legacy /v1 专用)
    synthesize_pcm(text, round_id,..) 逐 chunk 产出 PCM16(realtime /v2 专用)
    cancel(round_id, cascade)        round 级打断:停止新 chunk + 清空未开始的排队回合
    snapshot()                      状态快照,给 /ready 与 /v1/health

PCM 的**单一来源**是 synthesize_pcm:synthesize 只是把它的 chunk 按句拼成 WAV。
两者共用一份推理代码,保证 /v1 与 /v2 的音色、语速、音色完全一致,不会各自漂移。

四件这里必须做对的事(plan §1/§13/§17/§21):

1. **不阻塞事件循环。** 合成是同步生成器,由 server 的生产者线程拉取。
2. **串行且可打断。** GPT-SoVITS 的 TTS 实例共享 prompt_cache 与模型对象,
   非线程安全,因此用一把锁严格串行;打断靠 round 级 CancelToken 在"块"这一粒度
   检查,不靠杀线程(杀线程会漏掉 CUDA 同步,导致显存不释放),
   也**不用全局 TTS.stop_flag**(那是跨 round 串扰的根源)。
3. **round_id 全链路一致。** 一个 request 一个 round_id,从入口到每个 audio frame
   到 cancel 都是同一个值,引擎内部不重新生成、不覆盖(plan §13)。
4. **PCM 不做二次量化。** TTS.run() 的产物已经是 int16;旧的 _wav_from_float32
   把它当 float32 归一化再量化一次,是错的(plan §21)。现在 int16 → WAV 容器。
"""

from __future__ import annotations

import hmac
import hashlib
import secrets
import threading
import time
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from wave import open as wave_open

from . import bench
from .protocol import has_ascii_letter, split_for_tts
from .settings import ROOT, Settings, get_settings

PCM_FORMAT = "pcm_s16le"
"""plan §12:v2 固定的 PCM 编码。与 frontend AudioBuffer 侧一一对应。"""

LONG_FORM_THRESHOLD = 80
"""超过该字数走长文本模式(整段一次 tts.run + cut2)。句子泵单句 ≤30 字,不受影响。"""


class GuardError(ValueError):
    """输入守卫拒绝:带 code,由 server 映射为 HTTP 400。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class EngineBusy(RuntimeError):
    """排队超时或模型不可用:由 server 映射为 HTTP 503。"""


class ProtocolMismatch(RuntimeError):
    """同一 request 内 frame.round_id 与 request.round_id 不一致。

    与「stale frame」严格区分(plan §14.2):stale 是旧 round 的迟到帧,正常丢弃;
    protocol mismatch 是同一个 request 自己前后不一致,属于协议错误,必须暴露。
    """

    def __init__(self, message: str, want: str, got: str) -> None:
        super().__init__(message)
        self.want = want
        self.got = got


_GUARD_KEY = secrets.token_bytes(32)
"""进程内随机密钥,用于给 GuardedText 盖章。

**威胁模型的边界,先说清楚**:这不是防"同进程内的恶意攻击者"的安全边界 ——
那种攻击者能直接调 engine._tts,读模块私有属性也不难。它防的是**误用**:
手搓一个 GuardedText、把 A 的结果喂给 B、或者传上一轮用过的对象。
要让伪造成立,必须同时拿到这个密钥并对内容重新算一遍签名。
"""

_GUARD_TAG = hmac.new(_GUARD_KEY, digestmod=hashlib.sha256)


def _stamp(text: str, sentences: tuple[str, ...]) -> str:
    """对 (text, sentences) 盖章。内容变了签名就变。"""
    h = _GUARD_TAG.copy()
    h.update(text.encode("utf-8"))
    h.update(b"\x00")
    for s in sentences:
        h.update(s.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


@dataclass(frozen=True)
class GuardedText:
    """**已通过守卫**的文本及其切分结果(plan §36 H3 的守卫边界)。

    为什么是一个类型而不是裸 list[str]:
        engine 必须能区分「server 已经守过、可以直接用」与「调用方随手传进来的
        一串字符串」。裸 list 无法区分这两者,于是只有两条路 —— 要么无条件采信
        (等于给绕过输入校验开后门),要么重新分句来验证(那就没去重)。
        用一个由 prepare() 盖章的类型,把「已验证」变成可校验的事实。

    **frozen 只防篡改,不防构造** —— 这是实测踩到的坑:
        GuardedText(text="合法原文", sentences=("任意长句",)) 完全可以手搓,
        而只校验 text 相等的话,max_sentences 与单句长度两条限制
        会被完全绕过(审计已实测:60 句上限放行 30000 句)。
        所以加了 `tag`:内容绑定的签名,伪造需要对内容重算。

    **frozen**:一旦守卫产出就不可篡改。调用方拿它去 engine,途中改不了内容。
    """

    text: str
    sentences: tuple[str, ...]
    tag: str = ""
    """prepare() 打的签名。见 _stamp。"""

    def __len__(self) -> int:
        return len(self.sentences)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.sentences)


@dataclass
class SentenceAudio:
    """一句的完整产物(legacy /v1)。wav 是标准 RIFF/PCM,前端可直接解码播放。"""

    index: int
    sentence: str
    wav: bytes
    sample_rate: int
    duration_s: float
    ttfb_s: float
    gen_s: float
    n_chunks: int


@dataclass
class PcmChunk:
    """一个 PCM16 chunk(realtime /v2)。

    seq 在**一个 round 内全局单调递增**,跨 sentence 连续、不重置(plan §15);
    sentence_index 只用于标记句边界,不参与排序。
    peak / rms 仅在 bench 开启时计算(plan §28:observation 用途,不做阈值判定)。
    """

    seq: int
    sentence_index: int
    round_id: str
    sample_rate: int
    channels: int
    format: str
    pcm: bytes
    duration_s: float
    ttfb_s: float
    is_first: bool
    peak: float = 0.0
    rms: float = 0.0


class CancelToken:
    """round 级取消令牌(plan §17)。

    状态机:
        queued ──acquire──> running ──> finished
          │                   │
          └───cancel──────────┴──────────> cancelled

    cancel() 幂等:已 cancelled / 已 finished 时返回 False(没有发生状态迁移),
    调用方据此区分「真的打断了」与「来晚了」(plan §17 五种情形)。
    """

    __slots__ = (
        "round_id",
        "created",
        "created_ms",
        "started",
        "finished",
        "_cancel",
        "_lock",
    )

    def __init__(self, round_id: str) -> None:
        self.round_id = round_id
        self.created = time.perf_counter()
        self.created_ms = time.time() * 1000
        self.started = False
        self.finished = False
        self._cancel = False
        self._lock = threading.Lock()

    def cancel(self) -> bool:
        """标记取消;返回是否真的发生了 queued/running → cancelled 的迁移。"""
        with self._lock:
            if self._cancel or self.finished:
                return False
            self._cancel = True
            return True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    @property
    def state(self) -> str:
        if self._cancel:
            return "cancelled"
        if self.finished:
            return "finished"
        if self.started:
            return "running"
        return "queued"


def _pcm_metrics(samples: Any) -> tuple[float, float]:
    """int16 chunk → (peak, RMS)。口径见 bench.chunk_metrics 的文档。"""
    import numpy as np  # noqa: PLC0415 — 重依赖懒加载

    arr = np.asarray(samples, dtype=np.int16).reshape(-1)
    if arr.size == 0:
        return 0.0, 0.0
    peak = float(np.abs(arr).max())
    rms = float(np.sqrt(np.mean(np.square(arr.astype(np.float64)))))
    return peak, rms


def _wav_from_pcm16(pcm_int16: Any, sample_rate: int, channels: int = 1) -> tuple[bytes, float]:
    """int16 PCM → 标准 RIFF/PCM 的完整 wav 字节。**不做任何重采样或再量化。**

    plan §21:这是对旧 `_wav_from_float32(int16 产物)` 的修正 —— 旧路径把 int16
    当 float32 归一化(除以 peak)再量化一次,既损精度又改变了音量。WAV 容器只负责
    加 44 字节头,样本必须与 TTS 产物逐样本相同。
    """
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(pcm_int16, dtype=np.int16).reshape(-1)
    if arr.size == 0:
        return b"", 0.0

    buf = BytesIO()
    with wave_open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())
    return buf.getvalue(), arr.size / (sample_rate * channels)


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
        self._counters_lock = threading.Lock()
        """counters 的专用锁。

        guard 可能在后台推理线程里跑(不经 server 的直连路径),而 snapshot()
        在事件循环线程读 counters —— 原来只靠 _state_lock,而 guard 走的是
        另一把锁,两个线程并发写同一个 dict。
        """
        self._started_at = time.time()
        self._counters = {"requests": 0, "sentences": 0, "cancelled": 0, "errors": 0}
        self._bench_round_id = ""
        """当前推理中的 round_id,只给 TTS.py 的首包钩子回填用(串行推理下唯一)。"""
        self._bench_first_semantic_done = ""
        """已经打过 P3 的 round_id;保证一个 round 只出现一次 first semantic(plan §27)。"""

    # ---------------- 生命周期 ----------------

    def load(self) -> None:
        """加载模型。可能跑很久,设计上就是给后台线程调的。

        **不在这里 chdir**(plan §7):cwd 是进程级状态,不能由后台线程改。
        cwd / sys.path 由 `__main__.py` 在进程入口设定好。
        """
        with self._state_lock:
            if self._load_started:
                return
            self._load_started = True

        try:
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
            # 首包埋点:让 TTS.run() 在第一个 semantic 块产出时回调(plan §27 P3)。
            # 钩子挂在**实例**上(与 stop_flag 同属 TTS 实例状态),串行推理下唯一。
            # 未注册时 TTS.py 侧只是一次 None 判空,零开销。
            tts.set_bench_hook(self._mark_first_semantic)

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

    def _mark_first_semantic(self) -> None:
        """TTS AR 侧的「第一个 semantic token 块」钩子(plan §27 P3)。

        TTS.run() 每句调一次,所以引擎侧再按 round 去重:
        P3 的定义是**一个 round 的**第一个 semantic 块,重复打点会污染首包坐标。
        """
        rid = self._bench_round_id
        if not rid or rid == self._bench_first_semantic_done:
            return
        self._bench_first_semantic_done = rid
        bench.mark(bench.P3, round_id=rid)

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
            active = [{"round_id": r.round_id, "state": r.state} for r in self._rounds.values()]
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
        # 分句次数单独计数:guard 次数与分句次数是两件事,审计 H3 时要能分开看
        with self._counters_lock:
            self._counters["splits"] = self._counters.get("splits", 0) + 1
        if not sentences:
            raise GuardError("text 分句后为空", "no_sentence")
        if len(sentences) > cfg.max_sentences:
            raise GuardError(
                f"分句数 {len(sentences)} 超过上限 {cfg.max_sentences}", "too_many_sentences"
            )
        with self._counters_lock:
            self._counters["guards"] = self._counters.get("guards", 0) + 1
        return sentences

    def prepare(self, text: str) -> GuardedText:
        """校验 + 分句,产出**只有本引擎能构造**的 GuardedText。

        server 路径:prepare() → 把 GuardedText 交给 synthesize*(),engine 不再
        重复校验也不再重复分句(plan §36 H3 的既定边界)。
        直连路径(不经 server):synthesize*(text) 不传 GuardedText,走完整 guard。

        分句**只在这里发生一次**;engine 消费时直接用 `guarded.sentences`,
        不重跑 split_for_tts。
        """
        sentences = tuple(self.guard(text))
        return GuardedText(text=text, sentences=sentences, tag=_stamp(text, sentences))

    # ---------------- 打断 ----------------

    _RECENT_CAP = 32
    """保留最近若干个已结束回合。

    plan §17 要求「finished + cancel」是可观测的幂等 no-op,而不是 unknown。
    抢占时 cancel 经常晚于回合结束到达,所以要留住一小段已结束的 token;
    上限 32 防止无限增长。
    """

    def _register(self, round_id: str) -> CancelToken:
        token = CancelToken(round_id=round_id)
        with self._rounds_lock:
            self._prune_locked()
            self._rounds[round_id] = token
        with self._state_lock:
            self._counters["requests"] += 1
        return token

    def _prune_locked(self) -> None:
        """丢掉最老的 finished token,直到 active(未结束)回合数回到上限内。"""
        if len(self._rounds) <= self._RECENT_CAP:
            return
        stale = [rid for rid, t in self._rounds.items() if t.finished]
        for rid in stale:
            if len(self._rounds) <= self._RECENT_CAP:
                break
            self._rounds.pop(rid, None)

    def _release(self, token: CancelToken) -> None:
        token.finished = True

    def cancel(self, round_id: str, cascade: bool = True) -> dict[str, Any]:
        """round 级打断(plan §16-§18)。

        cascade=True 时连带清掉所有**还没 started** 的排队回合 —— 主程序抢占后必须
        立刻把队列清空,不能让旧回合接着出声。已 running 的回合不受 cascade 影响
        (plan §18:cascade 只作用于尚未 started 的 queued round)。
        """
        t_ms = time.time() * 1000
        with self._rounds_lock:
            token = self._rounds.get(round_id)
            others = [
                t
                for rid, t in self._rounds.items()
                if rid != round_id and not t.started and not t.finished
            ]

        hit = token.cancel() if token is not None else False
        bench.mark(
            bench.T3,
            round_id=round_id,
            hit=hit,
            state=token.state if token is not None else "unknown",
            ts_mark=t_ms,
        )

        dropped: list[str] = []
        if cascade:
            for t in others:
                if t.cancel():
                    dropped.append(t.round_id)

        if hit or dropped:
            with self._state_lock:
                self._counters["cancelled"] += 1

        if token is None:
            # 未知回合:no-op,绝不影响别的 round(plan §17 最后一种情形)
            return {
                "round_id": round_id,
                "cancelled": False,
                "state": "unknown",
                "known": False,
                "cascaded": dropped,
            }
        return {
            "round_id": round_id,
            "cancelled": hit,
            "state": token.state,
            "known": True,
            "cascaded": dropped,
        }

    # ---------------- 合成 ----------------

    def _build_req(
        self, sentence: str, voice: str | None, split_method: str | None = None
    ) -> dict[str, Any]:
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
            "text_split_method": split_method or cfg.text_split_method,
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

    def _require_sentences(
        self,
        text: str,
        guarded: GuardedText | None,
    ) -> list[str]:
        """合成入口的守卫边界(plan §36 H3)。

        三条硬规则,对应 plan §36「server 一次 guard → sentences → engine 直接消费」:

        1. **server 路径不重复分句。** 传入 GuardedText 时直接用它的 sentences,
           不再跑 split_for_tts。上一版在这里重跑一遍分句做"校验" —— 那是把去重
           做成假象:分句照跑两遍,只是第二次的结果被丢掉了。
        2. **不提供预校验结果的直连,仍执行完整 guard。** 传 None 走 self.guard()。
        3. **不允许绕过输入限制。** 见下面两道检查。

        为什么单靠 `guarded.text == text` 不够(审计实测的反例):
            GuardedText 是公开的 frozen dataclass —— frozen 只防篡改,**不防构造**。
            手搓 GuardedText(text="我在的。", sentences=(任意内容,)) 就能通过
            text 相等这一关,于是 max_sentences 与单句长度两条
            基于 sentences 的限制被完全绕过(实测 60 句上限放行了 30000 句)。
        所以补两道**廉价**检查 —— 都不需要重新分句:
            (a) tag 签名:内容绑定,伪造需重算;
            (b) 直接对 sentences 重验两条上限。O(n) 字符串长度,不碰模型、不分句。
        (b) 不是冗余:它保证"即便签名被绕过(比如同进程读到密钥),上限依然成立"。

        两条上限的语义**不同**,别混用:
            max_sentences  —— 硬上限,guard() 显式 raise,这里照抄同一判据。
            单句长度      —— 硬上限取 max_text_len,不是 max_sentence_chars。
                             后者是软分句目标(见下面注释),当判据会误杀合法输入。
        """
        if guarded is None:
            # 直连路径:完整守,分句在这里发生
            return self.guard(text)
        if not isinstance(guarded, GuardedText):  # pragma: no cover — 类型已保证
            raise GuardError("需要 GuardedText,不能传裸句子列表", "not_guarded")
        if guarded.text != text:
            raise GuardError(
                "GuardedText 与本次 text 不一致(把 A 的守卫结果喂给了 B)",
                "guard_text_mismatch",
            )
        if not guarded.sentences:
            raise GuardError("GuardedText 内无句子", "no_sentence")

        # (a) 签名:确认这批 sentences 确实由某次 prepare() 对这份 text 盖过章。
        expect = _stamp(guarded.text, guarded.sentences)
        if not hmac.compare_digest(guarded.tag, expect):
            raise GuardError(
                "GuardedText 签名不匹配(未经 prepare 盖章)", "guard_tag_invalid"
            )

        # (b) 对基于 sentences 的两条限制重验 —— 廉价,且不重新分句
        cfg = self._cfg
        if len(guarded.sentences) > cfg.max_sentences:
            raise GuardError(
                f"分句数 {len(guarded.sentences)} 超过上限 {cfg.max_sentences}",
                "too_many_sentences",
            )
        for s in guarded.sentences:
            if len(s) > cfg.max_text_len:
                # 阈值取 max_text_len,不是 max_sentence_chars —— 后者是**软分句目标**,
                # 不是可强制的不变量。依据:
                #   guard() 只把 max_sentence_chars 当 max_len 传给 split_for_tts,
                #   事后从不用它判罚(对比:max_text_len / max_sentences 都有显式 raise)。
                #   而 protocol._soft_split 找不到软标点时会 break 并原样保留整块,
                #   所以 split 的输出长度**本就没有上界**。
                # 之前这里用 `max_sentence_chars * 2`,实测会把合法的无标点长文本
                # (61 字 / 100 字等)当成伪造拦下 —— 那是误杀用户输入。
                # 现在用可证明的不变量:每句都是 text 的子串,而 guard 已保证
                # len(text) <= max_text_len,故此判据永不误拒合法输入,
                # 同时仍能挡住"比任何合法请求文本都长的伪造句"。
                raise GuardError(
                    f"单句 {len(s)} 字,超过请求文本上限 {cfg.max_text_len}",
                    "sentence_too_long",
                )

        # server 路径到此为止:直接消费,**不重新分句**
        return list(guarded.sentences)

    def _acquire(self, token: CancelToken) -> bool:
        """排队等推理锁。返回 False = 排队超时的情形已由调用方处理完。"""
        acquired = self._infer_lock.acquire(timeout=self._cfg.queue_wait_timeout_s)
        if not acquired:
            raise EngineBusy(
                f"排队超时({self._cfg.queue_wait_timeout_s}s),推理被占用"
            )
        return True

    def synthesize_pcm(
        self,
        text: str,
        *,
        round_id: str,
        voice: str | None = None,
        guarded: GuardedText | None = None,
    ) -> Iterator[PcmChunk]:
        """逐 chunk 产出 PCM16(realtime /v2 的单一数据源)。**阻塞生成器。**

        guarded 由 server 的 prepare() 产出时直接消费,不重复守也不重复分句;
        为 None 则走完整 guard(直连路径)。见 _require_sentences。

        生命周期:注册 token → 排队等锁(带超时) → 逐句逐 chunk 合成 → 逐 chunk 检查取消。

        chunk 级打断(plan §19)的准确含义:
            - 取消命中后**不再开始新的 chunk**,也不再开始新的句子;
            - 已经在跑的 chunk 由 TTS.run() 跑完这一段才返回 —— 不杀线程
              (杀线程会漏掉 CUDA 同步,导致显存不释放);
            - 因此最坏 cancel latency 由 benchmark 实测(Phase 6),不预先承诺数值。
        """
        if not self.ready:
            raise EngineBusy(self.error or "模型未就绪")

        sentences = self._require_sentences(text, guarded)
        token = self._register(round_id)
        self._bench_round_id = round_id

        self._acquire(token)
        try:
            if token.cancelled:
                bench.mark(bench.T4, round_id=round_id, reason="cancelled_before_start")
                return
            token.started = True
            tts = self._tts

            seq = 0
            total_bytes = 0
            first_emitted = False

            import numpy as np  # noqa: PLC0415

            # 长文本整段一次 tts.run(cut2 约 50 字一片),减少段间 BERT/prefill 死区。
            long_form = len(text) > LONG_FORM_THRESHOLD
            units = [text] if long_form else sentences
            for i, sentence in enumerate(units):
                if token.cancelled:
                    break
                t_sent = time.perf_counter()
                req = self._build_req(
                    sentence, voice, split_method="cut2" if long_form else None
                )
                ttfb = 0.0

                for chunk_sr, chunk in tts.run(req):
                    # chunk 级打断的检查点:在**开始下一个 chunk** 之前
                    if token.cancelled:
                        bench.mark(bench.T5D, round_id=round_id, sentence_index=i)
                        bench.mark(
                            bench.T4,
                            round_id=round_id,
                            reason="chunk_level",
                            sentence_index=i,
                            seq=seq,
                        )
                        return

                    sr = int(chunk_sr)
                    samples = np.asarray(chunk, dtype=np.int16).reshape(-1)
                    if samples.size == 0:
                        continue
                    if ttfb == 0.0:
                        ttfb = time.perf_counter() - t_sent
                        # P4 = 引擎侧第一个 PCM 产出(与 P3 第一个 semantic 区分)
                        bench.mark(bench.P4, round_id=round_id, sentence_index=i, sample_rate=sr)

                    n = samples.size
                    duration = n / sr if sr else 0.0
                    peak, rms = _pcm_metrics(samples) if bench.enabled() else (0.0, 0.0)

                    total_bytes += n * 2
                    if total_bytes > self._cfg.max_audio_bytes:
                        raise GuardError(
                            f"音频字节数超过上限 {self._cfg.max_audio_bytes}",
                            "audio_too_large",
                        )

                    is_first = not first_emitted
                    if is_first:
                        first_emitted = True
                        # P5 = engine 第一次 yield(P4 是生成,P5 是交出去)
                        bench.mark(bench.P5, round_id=round_id, seq=seq, sentence_index=i)

                    bench.chunk_metrics(
                        round_id=round_id,
                        seq=seq,
                        sentence_index=i,
                        sample_rate=sr,
                        channels=1,
                        n_samples=n,
                        peak=peak,
                        rms=rms,
                        duration_s=duration,
                    )

                    yield PcmChunk(
                        seq=seq,
                        sentence_index=i,
                        round_id=round_id,
                        sample_rate=sr,
                        channels=1,
                        format=PCM_FORMAT,
                        pcm=samples.tobytes(),
                        duration_s=duration,
                        ttfb_s=ttfb,
                        is_first=is_first,
                        peak=peak,
                        rms=rms,
                    )
                    # P5b 语义点:engine 交出这一块
                    bench.mark(bench.T5B, round_id=round_id, seq=seq, sentence_index=i)
                    seq += 1

                with self._state_lock:
                    self._counters["sentences"] += 1

            bench.mark(
                bench.T4 if token.cancelled else bench.T5A,
                round_id=round_id,
                reason="round_end" if not token.cancelled else "cancelled",
                n_chunks=seq,
            )
        except Exception:
            with self._state_lock:
                self._counters["errors"] += 1
            raise
        finally:
            self._release(token)
            self._infer_lock.release()

    def synthesize(
        self,
        text: str,
        *,
        round_id: str,
        voice: str | None = None,
        guarded: GuardedText | None = None,
    ) -> Iterator[SentenceAudio]:
        """逐句产出完整 wav(legacy /v1)。**阻塞生成器,必须在专用线程里消费。**

        与 synthesize_pcm 共用同一段推理与同一份 PCM(int16 → WAV 容器),
        差别只有「什么时候交付」:/v1 等整句齐了才给,/v2 一块一块给。
        这样两路的音色、语速、音量必然一致,不会各自漂移(plan §21)。
        """
        if not self.ready:
            raise EngineBusy(self.error or "模型未就绪")

        sentences = self._require_sentences(text, guarded)
        token = self._register(round_id)
        self._bench_round_id = round_id

        self._acquire(token)
        try:
            if token.cancelled:
                return
            token.started = True
            tts = self._tts

            import numpy as np  # noqa: PLC0415

            total_bytes = 0
            for i, sentence in enumerate(sentences):
                if token.cancelled:
                    break
                t_sent = time.perf_counter()

                pieces: list[Any] = []
                sample_rate = 0
                n_chunks = 0
                ttfb = 0.0

                for chunk_sr, chunk in tts.run(self._build_req(sentence, voice)):
                    if token.cancelled:  # 句中打断:丢弃半句
                        bench.mark(bench.T5D, round_id=round_id, sentence_index=i)
                        bench.mark(bench.T4, round_id=round_id, reason="chunk_level",
                                   sentence_index=i)
                        return
                    if n_chunks == 0:
                        ttfb = time.perf_counter() - t_sent
                        bench.mark(bench.P4, round_id=round_id, sentence_index=i,
                                   sample_rate=int(chunk_sr))
                    sample_rate = int(chunk_sr) or sample_rate
                    pieces.append(np.asarray(chunk, dtype=np.int16).reshape(-1))
                    n_chunks += 1

                if n_chunks == 0:
                    continue

                wav, duration = _wav_from_pcm16(np.concatenate(pieces), sample_rate)
                if not wav:
                    continue

                total_bytes += len(wav)
                if total_bytes > self._cfg.max_audio_bytes:
                    raise GuardError(
                        f"音频字节数超过上限 {self._cfg.max_audio_bytes}", "audio_too_large"
                    )

                with self._state_lock:
                    self._counters["sentences"] += 1

                bench.mark(bench.P5, round_id=round_id, sentence_index=i)
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
                bench.mark(bench.T5B, round_id=round_id, sentence_index=i)

            bench.mark(
                bench.T4 if token.cancelled else bench.T5A,
                round_id=round_id,
                reason="round_end" if not token.cancelled else "cancelled",
            )
        except Exception:
            with self._state_lock:
                self._counters["errors"] += 1
            raise
        finally:
            self._release(token)
            self._infer_lock.release()