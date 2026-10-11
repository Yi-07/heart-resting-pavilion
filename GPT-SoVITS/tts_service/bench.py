"""benchmark 事件记录 —— 跨进程可对齐的 JSONL 埋点(plan §26/§27/§30)。

为什么不用 backend 的 diag.py:diag 是「一回合一文件 + 进程内 perf_counter」,
只看得到 backend 自己那一段。本改造要量的是 **TTS 服务(:9001) / backend(:8000)
/ 浏览器** 三段拼起来的时间线,必须有一个三边共用的坐标:

    ts_ms  = time.time() * 1000    wall-clock,跨进程可比(同机)
    mono   = time.perf_counter()   同进程内的单调间隔,不受 NTP 跳变影响

事件名是**冻结契约**(plan §26/§27):两边同名同义,不允许各自解释。
新增事件要同时改这里和 backend/app/voice/tts_bench.py 的同名常量。

开关:
    TTS_BENCH=1        开启(默认关)
    TTS_BENCH_DIR=...  落盘目录(默认 <仓库根>/temp/bench)

关闭时 mark() 是一次布尔判空,生产路径零开销。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# ---- 冻结事件字典(plan §26 T0-T7)----
T0 = "T0_cancel_click"
T1 = "T1_cancel_http_sent"
T2 = "T2_server_cancel_receive"
T3 = "T3_engine_cancel_mark"
T4 = "T4_inference_stop"
T5A = "T5a_last_pcm_generated"
T5B = "T5b_engine_last_yield"
T5C = "T5c_server_last_send"
T5D = "T5d_last_pcm_dropped"
T6 = "T6_client_receive"
T7 = "T7_frontend_flush"

CANCEL_EVENTS = (T0, T1, T2, T3, T4, T5A, T5B, T5C, T5D, T6, T7)

# ---- 冻结事件字典(plan §27 首包 8 点)----
P1 = "P1_client_send"
P2 = "P2_server_receive"
P3 = "P3_first_semantic"
P4 = "P4_first_pcm"
P5 = "P5_engine_first_yield"
P6 = "P6_server_first_send"
P7 = "P7_client_first_receive"
P8 = "P8_frontend_enqueue"

FIRST_PACKET_EVENTS = (P1, P2, P3, P4, P5, P6, P7, P8)

# ---- 辅助事件(不在上述两套计数内,单独成组)----
FIRST_SOURCE_SCHEDULED = "first_source_scheduled"
PLAYBACK_TIMELINE = "playback_timeline"
CHUNK = "chunk_audio_metrics"
AUDIOBUFFER_RATE = "audio_buffer_sample_rate"
AUDIOCONTEXT_RATE = "audio_context_sample_rate"
BUFFER_DEPTH = "playback_buffer_depth"
PROTOCOL_MISMATCH = "protocol_mismatch"
STALE_FRAME_DROP = "stale_frame_drop"

_COMPONENT = "tts_service"

_LOCK = threading.Lock()
_FH: Any = None
_PATH: Path | None = None
_ENABLED = False


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _dir() -> Path:
    """落盘目录。TTS 服务侧默认落在仓库根的 temp/bench(即 GPT-SoVITS/temp/bench)。"""
    env = os.getenv("TTS_BENCH_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "temp" / "bench"


def enabled() -> bool:
    """是否在记录。显式给 TTS_BENCH_DIR 也视为开启(免得跑 benchmark 还要记环境变量)。"""
    return _ENABLED or _truthy(os.getenv("TTS_BENCH", "")) or bool(
        os.getenv("TTS_BENCH_DIR", "").strip()
    )


def sink_path() -> Path:
    """当前/将来的 JSONL 落盘路径(聚合脚本按这个找文件)。"""
    return _dir() / f"{_COMPONENT}.jsonl"


def _open() -> Any:
    """懒开文件句柄。首次写入才建目录,关闭状态下完全不碰磁盘。"""
    global _FH, _PATH
    if _FH is not None:
        return _FH
    p = sink_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _PATH = p
    _FH = p.open("a", encoding="utf-8", buffering=1)  # 行缓冲:一次 mark 一行
    return _FH


def mark(event: str, *, round_id: str = "", **fields: Any) -> None:
    """记一条事件。event 取上面的冻结常量;fields 是该事件的专属字段。

    写盘用行缓冲 + 一把锁:一次 mark = 一次 write 系统调用,量级在 µs,
    不会成为延迟来源(Phase 6 用 TTS_BENCH on/off 对照验证这一点)。
    """
    if not enabled():
        return
    rec: dict[str, Any] = {
        "ts_ms": round(time.time() * 1000, 3),
        "mono": round(time.perf_counter(), 6),
        "comp": _COMPONENT,
        "pid": os.getpid(),
        "ev": event,
    }
    if round_id:
        rec["round_id"] = round_id
    if fields:
        rec.update(fields)
    line = json.dumps(rec, ensure_ascii=False, default=str)
    with _LOCK:
        try:
            fh = _open()
            fh.write(line + "\n")
        except Exception:  # noqa: BLE001, S110 — 埋点绝不能把请求带崩
            pass


def chunk_metrics(
    *,
    round_id: str,
    seq: int,
    sentence_index: int,
    sample_rate: int,
    channels: int,
    n_samples: int,
    peak: float,
    rms: float,
    duration_s: float,
) -> None:
    """plan §28:每个 PCM chunk 的 peak / RMS / duration。

    口径(plan §28,与 chunk_metrics 文档同源):
        peak     = max(abs(int16_sample))            单位:LSB(int16 绝对值)
        rms      = sqrt(mean(int16_sample ** 2))     单位:LSB
        duration = sample_count / (sample_rate * channels)   单位:秒

    **不设故障阈值** —— 本阶段的用途是 observation / detection,
    「相邻 chunk 音量跳变」先当现象记录,不预设它等于 bug(plan §28)。
    """
    mark(
        CHUNK,
        round_id=round_id,
        seq=seq,
        sentence_index=sentence_index,
        sample_rate=sample_rate,
        channels=channels,
        n_samples=n_samples,
        peak=peak,
        rms=rms,
        duration_s=round(duration_s, 6),
    )