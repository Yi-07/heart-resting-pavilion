"""阶段 2:修正后的逐帧 round_id 迟到检测。

上一版按「每个 round_id 第一次出现的顺序」构造 order,再在这个列表里找逆序。
这个算法**结构上发现不了**下面这种回退:

    tts-0 / audio_seq=0 → tts-1 / audio_seq=0 → tts-0 / audio_seq=1

因为 tts-0 仍然排在 tts-1 前面(它首次出现得更早),逆序对判不出来,
但实际上「新回合第一帧之后又收到了旧回合的 PCM」——这才是要检的东西。

修正后的判据(逐帧,不依赖聚合):
  对每一帧 i(按接收顺序),比较它与**紧邻的上一帧**:
    - rid_i != rid_{i-1} 且 rid_i 是**此前已出现过**的回合 → 旧回合迟到帧
    - rid_i != rid_{i-1} 且 rid_i 未出现过            → 新回合首帧
  再叠加:
    - 每个回合内部 audio_seq 是否严格 +1(缺号=丢块,重号=重复)
    - 每个回合的 seq 区间是否与后续回合交错

跑法(backend 与 TTS 服务需启动):
    D:\\miniconda3\\envs\\test\\python.exe tests/diag_round_order.py [delays...]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WS_URL = "ws://127.0.0.1:8000/ws"
OUT = Path(r"D:\aic-project\heart-resting-pavilion\GPT-SoVITS\temp\stage3")
TEXTS = ["焦虑的时候如何缓解", "失眠有什么办法"]


def _num(rid: str) -> int | None:
    tail = rid.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def analyze_frames(frames: list[dict]) -> dict:
    """逐帧判定:找出所有「新回合首帧之后又收到旧回合 PCM」的情况。"""
    seen: set[str] = set()
    late: list[dict] = []
    new_first: list[dict] = []
    for i, f in enumerate(frames):
        rid = str(f["round_id"])
        if i > 0:
            prev = str(frames[i - 1]["round_id"])
            if rid != prev:
                rec = {
                    "at_index": i,
                    "t": f["t"],
                    "from": prev,
                    "to": rid,
                    "audio_seq": f.get("audio_seq"),
                    "seq": f.get("seq"),
                }
                if rid in seen:
                    late.append(rec)
                else:
                    new_first.append(rec)
        seen.add(rid)

    # 回合内 audio_seq 连续性
    per: dict[str, list[int]] = {}
    for f in frames:
        per.setdefault(str(f["round_id"]), []).append(f["audio_seq"])
    seq_issues = []
    for rid, seqs in per.items():
        expect = list(range(seqs[0], seqs[0] + len(seqs)))
        if seqs != expect:
            missing = sorted(set(expect) - set(seqs))
            dup = len(seqs) != len(set(seqs))
            seq_issues.append(
                {"round_id": rid, "n": len(seqs), "first": seqs[0],
                 "last": seqs[-1], "missing": missing, "dup": dup}
            )

    # 编号逆序(仅作参考,判定以逐帧 late 为准)
    order = []
    for f in frames:
        if f["round_id"] not in order:
            order.append(str(f["round_id"]))
    inversions = [
        (order[i], order[j])
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if _num(order[i]) is not None
        and _num(order[j]) is not None
        and _num(order[i]) > _num(order[j])
    ]

    return {
        "total_frames": len(frames),
        "first_appearance_order": order,
        "new_round_firsts": new_first,
        "late_old_round_frames": late,
        "audio_seq_issues": seq_issues,
        "order_inversions": inversions,
        "frames": frames,
    }


async def one_run(delay: float) -> dict:
    frames: list[dict] = []
    t0 = time.perf_counter()
    async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024) as ws:
        for i, text in enumerate(TEXTS):
            await ws.send(json.dumps({"type": "user_input", "text": text, "ts": i}))
            if i == 0:
                await asyncio.sleep(delay)
                continue
            idle = 0.0
            while idle < 6.0:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    idle += 1.0
                    continue
                except websockets.ConnectionClosed:
                    break
                idle = 0.0
                m = json.loads(raw)
                if m.get("type") != "audio_chunk":
                    continue
                if m.get("format") != "pcm_s16le":
                    continue
                frames.append(
                    {
                        "t": round(time.perf_counter() - t0, 4),
                        "round_id": m.get("round_id"),
                        "audio_seq": m.get("audio_seq"),
                        "seq": m.get("seq"),
                        "bytes": len(m["data"]) * 3 // 4,
                    }
                )
    res = analyze_frames(frames)
    res["delay"] = delay
    return res


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    delays = [float(a) for a in sys.argv[1:]] or [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
    results = []
    print("=" * 92)
    print(f"{'delay':>6} {'帧数':>5} {'首次出现序':<16} {'新回合首帧':>10} "
          f"{'旧回合迟到帧':>13} {'audio_seq问题':>13}")
    print("-" * 92)
    for d in delays:
        r = await one_run(d)
        results.append(r)
        print(
            f"{d:>6.1f} {r['total_frames']:>5} {str(r['first_appearance_order']):<16} "
            f"{len(r['new_round_firsts']):>10} {len(r['late_old_round_frames']):>13} "
            f"{len(r['audio_seq_issues']):>13}"
        )
        if r["late_old_round_frames"]:
            for x in r["late_old_round_frames"][:4]:
                print(f"        !! 迟到: #{x['at_index']} t={x['t']}s "
                      f"{x['from']} -> {x['to']} audio_seq={x['audio_seq']}")
        await asyncio.sleep(0.5)

    print("=" * 92)
    late_any = [r for r in results if r["late_old_round_frames"]]
    seq_any = [r for r in results if r["audio_seq_issues"]]
    print(f"出现旧回合迟到帧的扫描点: {[r['delay'] for r in late_any] or '无'}")
    print(f"出现 audio_seq 不连续的扫描点: {[r['delay'] for r in seq_any] or '无'}")
    print()
    print("注意:「本次扫描未观测到」不等于「协议上不可能发生」。")
    print("      前端仍无任何可靠信号区分「新回合」与「迟到的未知旧回合」(见边界测试第 3 项)。")
    (OUT / "round_order_fixed.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"明细已写入 {OUT / 'round_order_fixed.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))