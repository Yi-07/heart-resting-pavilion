"""benchmark 埋点(plan §26/§27/§30)—— backend 侧的跨进程事件记录。

与 GPT-SoVITS/tts_service/bench.py 是**同一套事件字典的两端**:事件名必须逐字相同,
否则聚合脚本拼不出时间线。改动任一端的事件名,另一端要跟着改。

坐标:
    ts_ms  = time.time() * 1000    wall-clock,与 TTS 服务(:9001)可比(同机)
    mono   = time.perf_counter()   backend 进程内的单调时钟

开关:TTS_BENCH=1(或 TTS_BENCH_DIR 指向目录即视为开启)。关闭时 mark() 是一次
布尔判空,句子泵的生产路径零开销。

与 app/diag.py 的分工:
    diag   —— 回合一文件、进程内相对毫秒、面向「这一次为什么慢」的临时排查
    本模块 —— 追加式 JSONL、跨进程绝对时间、面向「多轮聚合出 P50/P90」的 benchmark
两者不互相替代。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# ---- 冻结事件字典(必须与 tts_service/bench.py 逐字一致)----
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

P1 = "P1_client_send"
P2 = "P2_server_receive"
P3 = "P3_first_semantic"
P4 = "P4_first_pcm"
P5 = "P5_engine_first_yield"
P6 = "P6_server_first_send"
P7 = "P7_client_first_receive"
P8 = "P8_frontend_enqueue"

FIRST_PACKET_EVENTS = (P1, P2, P3, P4, P5, P6, P7, P8)

# ---- 辅助事件(与上面两套计数无关)----
FIRST_SOURCE_SCHEDULED = "first_source_scheduled"
PLAYBACK_TIMELINE = "playback_timeline"
CHUNK = "chunk_audio_metrics"
AUDIOBUFFER_RATE = "audio_buffer_sample_rate"
AUDIOCONTEXT_RATE = "audio_context_sample_rate"
BUFFER_DEPTH = "playback_buffer_depth"
PROTOCOL_MISMATCH = "protocol_mismatch"
STALE_FRAME_DROP = "stale_frame_drop"

_COMPONENT = "backend"

_LOCK = threading.Lock()
_FH: Any = None
_ENABLED = False


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _dir() -> Path:
    env = os.getenv("TTS_BENCH_DIR", "").strip()
    if env:
        return Path(env)
    # 默认与 TTS 服务同目录:GPT-SoVITS/temp/bench(plan §30 的「temp/ JSONL」)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "GPT-SoVITS").is_dir():
            return parent / "GPT-SoVITS" / "temp" / "bench"
    return Path(os.getenv("TEMP", ".")) / "tts_bench"


def enabled() -> bool:
    return _ENABLED or _truthy(os.getenv("TTS_BENCH", "")) or bool(
        os.getenv("TTS_BENCH_DIR", "").strip()
    )


def sink_path() -> Path:
    return _dir() / f"{_COMPONENT}.jsonl"


def _open() -> Any:
    global _FH
    if _FH is not None:
        return _FH
    p = sink_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _FH = p.open("a", encoding="utf-8", buffering=1)
    return _FH


def mark(event: str, *, round_id: str = "", **fields: Any) -> None:
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
    with _LOCK:
        try:
            _open().write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except Exception:  # noqa: BLE001, S110 — 埋点绝不能把回合带崩
            pass


def record_frontend(events: list[dict[str, Any]]) -> int:
    """收下浏览器 POST 上来的事件,原样落进同一个 JSONL;返回条数。

    单独一个入口而不是让路由层自己拼行:这样浏览器侧的 ts_ms / ev 名字
    与上面两套字典天然共用同一份校验与同一个文件,聚合脚本不用特判来源。
    """
    if not enabled() or not events:
        return 0
    now = time.time() * 1000
    lines: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        rec: dict[str, Any] = {
            "ts_ms": float(ev.get("ts_ms") or now),
            "comp": _COMPONENT,
            "src": "frontend",
            "ev": str(ev.get("ev", "")),
        }
        if ev.get("round_id"):
            rec["round_id"] = str(ev["round_id"])
        for k, v in ev.items():
            if k not in ("ts_ms", "comp", "ev", "round_id"):
                rec[k] = v
        lines.append(json.dumps(rec, ensure_ascii=False, default=str))
    if not lines:
        return 0
    with _LOCK:
        try:
            fh = _open()
            fh.write("\n".join(lines) + "\n")
        except Exception:  # noqa: BLE001 — 埋点写盘失败不影响回合
            return 0
    return len(lines)