"""用例 C·抢占蒸发:总结音频流出期间发 answer 输入 → 旧音频流停止,新回合正常应答。

自建会话:负面词输入触发降级收尾(快路径拿到总结音频)→ done 后音频异步流出
→ 2s 后发 `什么是正念`:
  1. 新回合 answer 应答:无 first_frame、text_delta 流(final)、done
  2. 新输入到达后不再出现旧总结 audio_chunk
"""

from __future__ import annotations

import asyncio

from e2e_lib import WsClient, result, user_text

NEGATIVE = "最近这阵子实在太累了，感觉自己快撑不住了。"
NEG_ROUND = "我觉得自己就是个废物，做什么都没用。"
ANSWER_Q = "什么是正念"


async def main() -> None:
    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        await c.send(user_text(NEGATIVE))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "collect first_frame" if got else "first_frame 未到达"))

        # 等第1问 → 轮次回答命中负面词表 → 降级收尾(粗稿+已采字段)
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "第1问")
        await asyncio.sleep(2.0)
        await c.send(user_text(NEG_ROUND))

        got = await c.wait_for(
            lambda m: m.get("type") == "text_delta" and bool(m.get("final")), 120, "总结 final"
        )
        checks.append((got is not None, "收尾 text_delta(final)" if got else "收尾文本未到达"))

        got = await c.wait_for(lambda m: m.get("type") == "done", 10, "done")
        checks.append((got is not None, "done" if got else "done 未到达"))
        t_done = got[0] if got else None

        # 等总结音频开始流出(确认 done 后确实有音频在流)
        got = await c.wait_for(lambda m: m.get("type") == "audio_chunk", 30, "总结音频首块")
        if got is None or t_done is None:
            checks.append((False, "done 后无总结音频,无法测抢占(先看 A 是否总结音频正常)"))
            t_preempt = None
        else:
            t_first_audio = got[0]
            await asyncio.sleep(2.0)  # 让音频流跑到中段
            pre_count = len(c.frames_since(t_done, "audio_chunk"))
            t_preempt = await c.send(user_text(ANSWER_Q))
            print(f"  -- 抢占前总结音频 {pre_count} 块,首块距 done "
                  f"{t_first_audio - t_done:.2f}s,发抢占输入 --", flush=True)

            # 新回合应答:无 first_frame
            got = await c.wait_for(
                lambda m: m.get("type") == "text_delta" and bool(m.get("final")), 90, "answer final"
            )
            checks.append((got is not None, "answer text_delta(final)" if got else "answer 应答未到达"))

            ff_after = c.frames_since(t_preempt, "first_frame")
            checks.append((not ff_after, "新回合无 first_frame(answer 语义)"
                           if not ff_after else "answer 回合出现 first_frame(违背契约)"))

            got = await c.wait_for(lambda m: m.get("type") == "done", 10, "answer done")
            checks.append((got is not None, "answer done" if got else "answer done 未到达"))

            # 等流静止,检查旧总结音频是否蒸发
            await c.drain_idle(idle_s=10.0, hard_cap=120.0)
            leaked = c.frames_since(t_preempt, "audio_chunk")
            checks.append((not leaked,
                           "新输入后无 audio_chunk(旧总结流已蒸发)"
                           if not leaked else
                           f"新输入后仍出现 {len(leaked)} 块 audio_chunk(蒸发失败)"))

        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    print("\n===== 用例 C·抢占蒸发 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("C·抢占蒸发", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
