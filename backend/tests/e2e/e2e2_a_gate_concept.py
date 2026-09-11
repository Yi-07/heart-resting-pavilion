"""e2e2 用例 A·采集中概念问句 → 短答支线(ADR-003 采集态门控)。

R1 首帧+首问 → R2 增量 draw+第2问 → R3 `什么是正念?` 短答支线
  (断言:只有 text_delta+done,无 first_frame/draw,黑板保活)
→ R4 恢复采集(断言:增量 draw seq>R2,无 first_frame)
→ R5+ 内容轮走到精稿总结收尾(STATION_INVITE+done,回合完整结束)。
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

from e2e_lib import WsClient, result, user_text

R1 = "最近很焦虑睡不着"
R2 = "上周开会的时候，领导当众批评我，我脑子里一片空白。"
R3 = "什么是正念？"
R4 = "就是开会那次，我满脑子都是要搞砸了。"
TAIL = [
    "我一到晚上就在想，要是下次再当众出丑怎么办，越想越怕。",
    "我现在就是硬撑着把事做完，晚上靠刷手机拖着不睡，谁也没告诉。",
    "这种状态持续两三周了，白天上班完全没精神。",
    "其实我最怕的是别人觉得我不行。",
    "我试过早点躺下，但翻来覆去根本睡不着。",
]
INVITE_KEY = "心灵补给站"


async def collect_round(c: WsClient, text: str, label: str) -> tuple[float, dict[str, Any]]:
    """发一条采集轮输入,等增量 draw(60s 内,可缺)+ 问句 text_delta,返回 draw 帧。"""
    t = await c.send(user_text(text))
    d = await c.wait_for(lambda m: m.get("type") == "draw", 60, f"{label} draw")
    await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"{label} 问句")
    return t, (d[1] if d else {})


async def main() -> None:
    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        # R1: 首帧 + 粗稿 + 首问
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "R1 first_frame(route=collect)" if got else "R1 first_frame 未到达"))
        r1_draw = await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿 draw")
        r1_seq = (r1_draw[1].get("seq") or 0) if r1_draw else 0
        checks.append((r1_draw is not None, "R1 粗稿 draw" if r1_draw else "R1 粗稿 draw 未到达"))
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")

        # R2: 增量 draw + 第2问
        _t2, r2_draw = await collect_round(c, R2, "R2")
        r2_seq = r2_draw.get("seq")
        checks.append((isinstance(r2_seq, int) and r2_seq > r1_seq,
                       f"R2 增量 draw seq={r2_seq}(> R1)" if r2_seq else "R2 增量 draw 未到达"))

        # R3: 概念问句 → 短答支线(挂起,不清采集态)
        await asyncio.sleep(4.0)
        t3 = await c.send(user_text(R3))
        d3 = await c.wait_for(lambda m: m.get("type") == "done", 150, "R3 done")
        win = c.frames_since(t3)
        ffs = [m for _, m in win if m.get("type") == "first_frame"]
        draws = [m for _, m in win if m.get("type") == "draw"]
        texts = [m.get("text") or "" for _, m in win if m.get("type") == "text_delta"]
        body = "".join(texts)
        checks.append((not ffs, "R3 无 first_frame" if not ffs else f"R3 出现 first_frame: {ffs}"))
        checks.append((not draws, "R3 无 draw(黑板保活)" if not draws
                       else f"R3 出现 {len(draws)} 帧 draw: {[m.get('seq') for m in draws]}"))
        checks.append((d3 is not None, "R3 done 到达(短答回合收口)" if d3 else "R3 done 未到达"))
        checks.append((len(body) > 50, f"R3 短答正文 {len(body)} 字" if len(body) > 50
                       else f"R3 短答正文过短({len(body)} 字): {body!r}"))
        print(f"  -- R3 短答正文: {body[:160]}...", flush=True)

        # R4: 恢复采集,增量 draw 接得上
        await asyncio.sleep(4.0)
        _t4, r4_draw = await collect_round(c, R4, "R4")
        r4_seq = r4_draw.get("seq")
        ff4 = [m for _, m in c.frames_since(t3) if m.get("type") == "first_frame"]
        checks.append((isinstance(r4_seq, int) and isinstance(r2_seq, int) and r4_seq > r2_seq,
                       f"R4 增量 draw seq={r4_seq}(> R2 的 {r2_seq},采集恢复)" if r4_seq
                       else f"R4 增量 draw 未到达/seq 异常(seq={r4_seq}, R2 seq={r2_seq})"))
        checks.append((not ff4, "R3+R4 全程无 first_frame(黑板未重开)" if not ff4
                       else f"R3+R4 出现 first_frame: {ff4}"))

        # R5+: 内容轮走到精稿总结收尾。停采判别:预置问句瞬时(<8s,预置库不走 LLM);
        # 停采后总结文本走 LLM(>8s)才出现——首帧文本到达时刻区分两态。
        t_end = None
        for i, text in enumerate(TAIL, start=5):
            await asyncio.sleep(4.0)
            t = await c.send(user_text(text))
            first = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"R{i} 首帧文本")
            if first is None:
                print(f"  -- R{i} 无文本帧,继续下一轮 --", flush=True)
                continue
            if first[0] - t >= 8.0:
                got = await c.wait_for(
                    lambda m: m.get("type") == "text_delta" and INVITE_KEY in (m.get("text") or ""),
                    180, f"R{i} 总结邀请语")
                if got:
                    t_end = got[0]
                    break
            print(f"  -- R{i} 未触发停采,继续下一轮 --", flush=True)
        checks.append((t_end is not None, "精稿总结 + 心灵补给站邀请语到达" if t_end
                       else "走完 TAIL 轮仍未触发精稿总结"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 15, "收尾 done")
        checks.append((got is not None, "收尾 done(回合完整结束)" if got else "收尾 done 未到达"))

        # 全程 seq 单调 + 无 error + 仅首回合一个 first_frame
        seqs: list[int] = []
        for _, m in c.frames:
            s_seq = m.get("seq")
            if isinstance(s_seq, int):
                seqs.append(s_seq)
        mono = all(b > a for a, b in itertools.pairwise(seqs))
        checks.append((mono, f"seq 全程单调递增({len(seqs)} 帧)" if mono else f"seq 非单调: {seqs}"))
        nff = sum(1 for _, m in c.frames if m.get("type") == "first_frame")
        checks.append((nff == 1, "全程仅 1 个 first_frame(门控未重开黑板)" if nff == 1
                       else f"first_frame 出现 {nff} 次"))
        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    print("\n===== e2e2 用例 A·采集中概念问句 → 短答支线 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("A·概念问句短答支线", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
