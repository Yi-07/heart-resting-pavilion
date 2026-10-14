"""用例 A·collect 全流程回归(entry + 采集轮 → 精稿 → 总结 → done → 总结音频异步流出)。

自适应编排(LLM 跨字段提取,一轮可能填满四字段提前停采,也可能走满 max_rounds
收口):每轮增量 draw 后按"已填字段数 / 下一帧类型(问题文本或精稿 draw)"判定
走向,不假设固定第几轮停采。充分度路径参考:emotion .2 → situation .4 →
thought .6 → behavior .75 ≥ 0.7 停采;max_rounds=3 兜底。
断言:
  1. first_frame(route=collect, mood_select=false 恒) → 粗稿 draw
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
TAIL = (R2, R3, R4)


def filled_main(draw_msg: dict) -> int:
    """draw.data 非信念四字段已填数(emotion 看 label);停采判定用。"""
    data = draw_msg.get("data", {})
    n = 0
    for key in ("situation", "thought", "behavior"):
        if data.get(key) is not None:
            n += 1
    emotion = data.get("emotion")
    if isinstance(emotion, dict) and emotion.get("label") is not None:
        n += 1
    return n


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
        checks.append((ff.get("route") == "collect" and ff.get("mood_select") is False,
                       (f"first_frame route={ff.get('route')} mood={ff.get('mood_select')} "
                       f"emotion={ff.get('emotion_label')!r} (首帧延迟 {got[0] - t_r1:.2f}s)")))

        # ---- R1:粗稿 + 第1问 ----
        got = await wait_draw(c, 60, "粗稿 draw")
        checks.append((got is not None, "粗稿 draw(seq=1)" if got else "粗稿 draw 未到达"))
        if got:
            draws.append(got[1])
        got = await wait_text(c, 90, "第1问")
        checks.append((got is not None, "第1问 text_delta" if got else "第1问未到达"))

        # ---- R2-R4:增量 draw → 问题或停采(自适应编排) ----
        refine: tuple[float, dict] | None = None  # 精稿 draw;停采路径可能提前拿到
        for i, text in enumerate(TAIL, start=2):
            await asyncio.sleep(4)  # 避免触发抢占重开
            await c.send(user_text(text))
            got = await wait_draw(c, 90, f"R{i} 增量 draw")
            checks.append((got is not None, f"R{i} 增量 draw" if got else f"R{i} draw 未到达"))
            if got is None:
                return
            draws.append(got[1])
            if filled_main(got[1]) >= 4:
                checks.append((True, f"R{i} 一轮填满四字段,服务端停采(自适应编排)"))
                break
            # 未填满:下一帧要么是下一问文本,要么直接停采出精稿 draw(max_rounds)
            got = await c.wait_for(
                lambda m: m.get("type") in ("draw", "text_delta"), 90, f"R{i} 问题或精稿")
            if got is None:
                checks.append((False, f"R{i} 后既无下一问也无精稿 draw"))
                return
            if got[1].get("type") == "draw":
                refine = got
                draws.append(got[1])
                checks.append((True, f"R{i} 后直接停采(max_rounds/充分度)"))
                break
            checks.append((True, f"第{i}问 text_delta 到达"))

        # ---- 停采分析(等待语音 filler 可能出现)→ 精稿 draw ----
        if refine is None:
            got = await wait_draw(c, 120, "精稿 draw")
            checks.append((got is not None, "精稿 draw(停采分析后)" if got else "精稿 draw 未到达"))
            if got is None:
                return
            refine = got
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
