"""用例 A·collect 全流程回归(entry + 3 轮采集 → 精稿 → 总结 → done → 总结音频异步流出)。

充分度路径(emotion 0.2 → situation 0.4 → thought 0.6 → behavior 0.75 ≥ 0.7 停采):
  R1(entry,粗稿+问情境) → R2(情境) → R3(想法) → R4(行为) → 停采 finish
断言:
  1. first_frame(route=collect, mood_select=true) → 粗稿 draw
  2. 每轮增量 draw,seq 单调递增
  3. 停采后精稿 draw(全量)
  4. 总结 text_delta(final=true) → done ≤2s
  5. 总结 audio_chunk 多帧在 done 之后到达(记首块延迟/块数/总时长)
  6. 全程无 error 帧
"""

from __future__ import annotations

import asyncio
import itertools

import e2e_lib
from e2e_lib import WsClient, result, user_text

R1 = "最近这一个月我压力特别大，晚上翻来覆去到两三点都睡不着，白天上班完全没精神。"
R2 = "上周开始领导天天临时加需求，我加班到十点才回家，躺在床上脑子里还在过工作的事，越想越睡不着。"
R3 = "脑子里老是在想，我要是连这点事都扛不住，工作早晚保不住，心里又急又怕。"
R4 = "我一般就是硬撑着把活干完，晚上刷手机拖到很晚才睡，谁也没告诉。"


async def wait_draw(c: WsClient, timeout: float, label: str):
    return await c.wait_for(lambda m: m.get("type") == "draw", timeout, label)


async def wait_text(c: WsClient, timeout: float, label: str, *, final: bool | None = None):
    def pred(m: dict) -> bool:
        return (m.get("type") == "text_delta"
                and (final is None or m.get("final") == final))

    return await c.wait_for(pred, timeout, label)


async def main() -> None:
    checks: list[tuple[bool, str]] = []
    draws: list[dict] = []

    async with WsClient() as c:
        t_r1 = await c.send(user_text(R1))

        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        if got is None:
            checks.append((False, "first_frame 未到达"))
            return
        _, ff = got
        checks.append((ff.get("route") == "collect" and ff.get("mood_select") is True,
                       (f"first_frame route={ff.get('route')} mood={ff.get('mood_select')} "
                       f"emotion={ff.get('emotion_label')!r} (首帧延迟 {got[0] - t_r1:.2f}s)")))

        # ---- R1:粗稿 + 第1问 ----
        got = await wait_draw(c, 60, "粗稿 draw")
        checks.append((got is not None, "粗稿 draw(seq=1)" if got else "粗稿 draw 未到达"))
        if got:
            draws.append(got[1])
        got = await wait_text(c, 90, "第1问")
        checks.append((got is not None, "第1问 text_delta" if got else "第1问未到达"))

        # ---- R2/R3:增量 draw + 问题 ----
        for i, text in enumerate((R2, R3), start=2):
            await asyncio.sleep(4)  # 避免触发抢占重开
            await c.send(user_text(text))
            got = await wait_draw(c, 90, f"R{i} 增量 draw")
            checks.append((got is not None, f"R{i} 增量 draw" if got else f"R{i} draw 未到达"))
            if got:
                draws.append(got[1])
            got = await wait_text(c, 90, f"第{i}问")
            checks.append((got is not None, f"第{i}问 text_delta" if got else f"第{i}问未到达"))

        # ---- R4:增量 draw → 停采分析(等待语音 filler 可能出现)→ 精稿 draw ----
        await asyncio.sleep(4)
        await c.send(user_text(R4))
        got = await wait_draw(c, 90, "R4 增量 draw")
        checks.append((got is not None, "R4 增量 draw" if got else "R4 draw 未到达"))

        got = await wait_draw(c, 120, "精稿 draw")
        checks.append((got is not None, "精稿 draw(停采分析后)" if got else "精稿 draw 未到达"))
        if got:
            draws.append(got[1])

        # ---- 总结 text(final=true) → done ≤2s ----
        got = await wait_text(c, 90, "总结 final", final=True)
        if got is None:
            checks.append((False, "总结 text_delta(final=true) 未到达"))
            t_final = None
        else:
            t_final, _ = got
            checks.append((True, "总结 text_delta(final=true) 到达"))

        got = await c.wait_for(lambda m: m.get("type") == "done", 10, "done")
        if got is None or t_final is None:
            checks.append((False, "done 未到达"))
            return
        t_done = got[0]
        dt = t_done - t_final
        checks.append((dt <= 2.0, f"done 距总结 final {dt:.2f}s(判据 ≤2s)"))

        # ---- 总结音频:done 后异步流出,等流静止 ----
        await c.drain_idle(idle_s=10.0, hard_cap=240.0)
        chunks = c.frames_since(t_done, "audio_chunk")
        total_dur = sum(e2e_lib.wav_seconds(m.get("data", "")) for _, m in chunks)
        if chunks:
            first_delay = chunks[0][0] - t_done
            checks.append((len(chunks) >= 1,
                           (f"总结音频 {len(chunks)} 块,首块距 done {first_delay:.2f}s,"
                           f"总时长 {total_dur:.1f}s")))
        else:
            checks.append((False, "done 后无总结 audio_chunk"))

        # ---- 全局判定 ----
        errs = [f"{m.get('code')}: {m.get('message')}"
                for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

        seqs: list[int] = []
        for _, m in c.frames:
            s_seq = m.get("seq")
            if m.get("type") in ("draw", "text_delta", "audio_chunk", "done") and isinstance(s_seq, int):
                seqs.append(s_seq)
        monotonic = all(b > a for a, b in itertools.pairwise(seqs))
        checks.append((monotonic, f"seq 单调递增({len(seqs)} 个带 seq 帧)"
                       if monotonic else f"seq 非单调: {seqs}"))

        belief_blank = all(
            d.get("data", {}).get("intermediate_belief") is None
            and d.get("data", {}).get("core_belief") is None
            for d in draws
        )
        checks.append((belief_blank, "信念字段全程留白"))

    print("\n===== 用例 A·collect 全流程 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("A·collect", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
