"""诊断:同一 WebSocket 连续两轮询问,记录 backend 收到的帧序列。

目的:验证第二轮的 first_frame / audio_chunk 是否完整抵达前端,
      以及两轮之间是否有帧丢失或 round_id 不匹配。

跑法(在 backend 目录):
    D:\\miniconda3\\envs\\test\\python.exe tests/diag_two_rounds.py

需要:backend(:8000) 与 TTS 服务(:9001) 均已启动。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

WS_URL = "ws://127.0.0.1:8000/ws"
# 命中 KNOWLEDGE_PATTERNS(如何/怎么办/什么是)→ 走 answer 路,才有 PCM 音频
ROUND_TEXTS = [
    "焦虑的时候如何缓解",
    "失眠有什么办法",
]


async def _recv(ws, timeout: float = 30.0) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def main() -> int:
    print("=" * 70)
    print("诊断:同一 WebSocket 连续两轮询问")
    print("=" * 70)

    frames: list[dict] = []
    round_idx = -1

    async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024) as ws:
        # 连接后可能有 replay 帧,先收掉
        try:
            while True:
                msg = await _recv(ws, timeout=2.0)
                frames.append({"phase": "replay", "msg": msg})
                if msg.get("type") == "replay":
                    break
        except asyncio.TimeoutError:
            pass

        for i, text in enumerate(ROUND_TEXTS):
            round_idx = i
            print(f"\n--- 第 {i+1} 轮: {text!r} ---")
            await ws.send(json.dumps({"type": "user_input", "text": text, "ts": i}))

            # 收集本轮帧:直到 done 或 timeout
            round_frames: list[dict] = []
            try:
                while True:
                    msg = await _recv(ws, timeout=60.0)
                    round_frames.append(msg)
                    t = msg.get("type")
                    if t in ("done", "error"):
                        break
                    # collect 阶段的 draw/text_delta 也要收
                    if t == "text_delta" and msg.get("final"):
                        # 收到 final text_delta 后继续等(可能还有 audio_chunk)
                        pass
            except asyncio.TimeoutError:
                print(f"  [WARN] 第 {i+1} 轮超时未收到 done")

            # 统计本轮帧
            audio_chunks = [f for f in round_frames if f.get("type") == "audio_chunk"]
            first_frames = [f for f in round_frames if f.get("type") == "first_frame"]
            draws = [f for f in round_frames if f.get("type") == "draw"]
            text_deltas = [f for f in round_frames if f.get("type") == "text_delta"]

            print(f"  first_frame : {len(first_frames)} 帧")
            for f in first_frames:
                print(f"    round_id={f.get('round_id')} route={f.get('route')}")
            print(f"  draw        : {len(draws)} 帧")
            print(f"  text_delta  : {len(text_deltas)} 帧")
            print(f"  audio_chunk : {len(audio_chunks)} 帧")
            if audio_chunks:
                seqs = [f.get("audio_seq") for f in audio_chunks]
                rids = set(f.get("round_id") for f in audio_chunks)
                total_pcm = sum(len(f.get("data", "")) for f in audio_chunks)
                print(f"    round_id 集合: {rids}")
                print(f"    audio_seq 范围: {min(seqs)}..{max(seqs)}")
                print(f"    base64 总字节: {total_pcm}")
                # 检查 seq 是否连续
                expected = list(range(min(seqs), max(seqs) + 1))
                if seqs != expected:
                    print(f"    [WARN] audio_seq 不连续! 期望 {expected[:10]}... 实际 {seqs[:10]}...")
                else:
                    print(f"    audio_seq 连续 OK")

            frames.extend({"phase": f"round{i+1}", "msg": f} for f in round_frames)

    # 汇总
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    all_audio = [f["msg"] for f in frames if f["msg"].get("type") == "audio_chunk"]
    print(f"总 audio_chunk 帧数: {len(all_audio)}")
    all_first = [f["msg"] for f in frames if f["msg"].get("type") == "first_frame"]
    print(f"总 first_frame 帧数: {len(all_first)}")
    for i, f in enumerate(all_first):
        print(f"  first_frame[{i}]: round_id={f.get('round_id')} route={f.get('route')}")

    # 检查每轮 round_id 是否不同
    rids = [f.get("round_id") for f in all_first if f.get("round_id")]
    if len(rids) == len(set(rids)):
        print("first_frame round_id 各不相同 OK")
    else:
        print(f"[WARN] first_frame round_id 有重复: {rids}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
