"""句子泵时序诊断 —— 临时打点工具,默认关闭。

用途:定位「真实 LLM 已经出完字,但 TTS 第一条请求迟迟不发」到底卡在哪一层。
覆盖链路:LLM 出字 → batched_chunks → 切句 → 入队 → TTS worker → HTTP 发出
        → 首块音频到达 → audio_q → WebSocket 发出

开关:环境变量 TTS_PUMP_DIAG=1 启用(由 main.py 调 enable())。
关闭时 diag() 是一次整数判空,**生产路径无开销**。

所有时间戳统一用 time.perf_counter(),相对 enable() 的时刻。

生命周期契约(调用方必须遵守,否则记录会跨回合累积):
    enable() -> mark()* -> dump() -> disable()
dump() 每次写独立文件(带自增序号),不覆盖。disable() 之后 mark() 退化为
一次判空,生产路径零开销。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_RECORDS: list[dict[str, Any]] | None = None
_T0 = 0.0
_ENV_ON = os.getenv("TTS_PUMP_DIAG", "").strip() not in ("", "0", "false", "no")


def env_on() -> bool:
    return _ENV_ON


def enable() -> list[dict[str, Any]]:
    """开始记录,返回记录列表(调用方负责之后 dump)。"""
    global _RECORDS, _T0
    _T0 = time.perf_counter()
    _RECORDS = []
    return _RECORDS


def disable() -> None:
    global _RECORDS
    _RECORDS = None


def active() -> bool:
    return _RECORDS is not None


def mark(stage: str, **fields: Any) -> None:
    if _RECORDS is None:
        return
    _RECORDS.append({"t": round(time.perf_counter() - _T0, 4), "stage": stage, **fields})


_DUMP_N = 0


def dump(tag: str | None = None) -> Path | None:
    """写盘到系统临时目录(探查产物不进仓库);返回路径,未启用时 None。

    文件名带自增序号:配合 enable/disable 的「一回合一文件」生命周期,
    多次 dump 不会互相覆盖,也不需要事后按 seq_start 人工切分。
    """
    global _DUMP_N
    if _RECORDS is None:
        return None
    import tempfile

    _DUMP_N += 1
    stem = f"{tag}_" if tag else ""
    p = Path(tempfile.gettempdir()) / f"pump_{stem}{_DUMP_N:03d}.json"
    p.write_text(
        json.dumps(_RECORDS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return p


def render(limit_head: int = 30) -> str:
    """人读的表格:按时间排,标出相邻两步之间的间隔。"""
    if not _RECORDS:
        return "(无记录)"
    lines = [
        f"{'t(s)':>8}  {'Δ(ms)':>8}  {'stage':<22}  detail",
        "-" * 96,
    ]
    prev: float | None = None
    for i, r in enumerate(_RECORDS):
        gap = "" if prev is None else f"{(r['t'] - prev) * 1000:8.0f}"
        prev = r["t"]
        detail = {k: v for k, v in r.items() if k not in ("t", "stage")}
        text = json.dumps(detail, ensure_ascii=False) if detail else ""
        if len(text) > 58:
            text = text[:55] + "…"
        lines.append(f"{r['t']:>8.3f}  {gap:>8}  {r['stage']:<22}  {text}")
        if i + 1 >= limit_head:
            lines.append(f"… 共 {len(_RECORDS)} 条")
            break
    return "\n".join(lines)