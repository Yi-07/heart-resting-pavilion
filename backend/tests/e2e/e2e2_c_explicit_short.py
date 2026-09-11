"""e2e2 用例 C·显式升级短答(ADR-003):采集态中 `你先回答我，什么是正念` → 短答支线。

断言:R2 短答帧序(text_delta 流 + done,无 first_frame/无 draw);
R3 正常内容输入 → 增量 draw 到达(state 保留,采集恢复)。
"""

from __future__ import annotations

import asyncio

from e2e_lib import WsClient, result, user_text

R1 = "最近很焦虑睡不着"
R2 = "你先回答我，什么是正念"
R3 = "睡不着的时候脑子特别乱。"


async def main() -> None:
    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        # R1: 进采集
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "R1 first_frame(route=collect)" if got else "R1 first_frame 未到达"))
        r1_draw = await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿 draw")
        r1_seq = r1_draw[1].get("seq") if r1_draw else None
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")

        # R2: 显式要求回答 → 短答支线
        await asyncio.sleep(4.0)
        t2 = await c.send(user_text(R2))
        d2 = await c.wait_for(lambda m: m.get("type") == "done", 150, "R2 done")
        win = c.frames_since(t2)
        ffs = [m for _, m in win if m.get("type") == "first_frame"]
        draws = [m for _, m in win if m.get("type") == "draw"]
        texts = [m.get("text") or "" for _, m in win if m.get("type") == "text_delta"]
        body = "".join(texts)
        checks.append((not ffs, "R2 无 first_frame(短答支线)" if not ffs
                       else f"R2 出现 first_frame: {ffs}"))
        checks.append((not draws, "R2 无 draw(黑板保活)" if not draws
                       else f"R2 出现 draw: {[m.get('seq') for m in draws]}"))
        checks.append((d2 is not None, "R2 done 到达(短答回合收口)" if d2 else "R2 done 未到达"))
        checks.append((len(body) > 50, f"R2 短答正文 {len(body)} 字" if len(body) > 50
                       else f"R2 短答正文过短({len(body)} 字): {body!r}"))
        print(f"  -- R2 短答正文: {body[:160]}", flush=True)

        # R3: 正常内容 → 采集恢复。注意:`睡不着的时候脑子特别乱。` 无具体场景,
        # 提取 LLM 判 off_topic → 陪聊回复(门控仍留 collect);场景具体内容才出增量 draw。
        await asyncio.sleep(4.0)
        await c.send(user_text(R3))
        q3 = await c.wait_for(lambda m: m.get("type") == "text_delta", 120, "R3 回应")
        checks.append((q3 is not None, "R3 有回应帧" if q3 else "R3 无回应帧"))
        ff3 = [m for _, m in c.frames_since(t2) if m.get("type") == "first_frame"]
        checks.append((not ff3, "R2+R3 全程无 first_frame" if not ff3
                       else f"R2+R3 出现 first_frame: {ff3}"))

        # R4/R5: 具体场景内容 → 增量 draw(state 保留的最终证据)
        await asyncio.sleep(4.0)
        await c.send(user_text("上周开会的时候，领导当众批评我，我脑子里一片空白。"))
        await c.wait_for(lambda m: m.get("type") == "text_delta", 120, "R4 问句")
        await asyncio.sleep(4.0)
        await c.send(user_text("领导让我当众改方案，我一句话都说不出来。"))
        d5 = await c.wait_for(lambda m: m.get("type") == "draw", 120, "R5 增量 draw")
        r5_seq = d5[1].get("seq") if d5 else None
        checks.append((d5 is not None and r1_seq is not None and r5_seq is not None
                       and r5_seq > r1_seq,
                       f"R5 增量 draw seq={r5_seq}(> R1 的 {r1_seq},state 保留)" if d5 else
                       f"R5 增量 draw 未到达(R5 seq={r5_seq}, R1 seq={r1_seq})"))
        ff5 = [m for _, m in c.frames_since(t2) if m.get("type") == "first_frame"]
        checks.append((not ff5, "R2 起全程无 first_frame(黑板未重开)" if not ff5
                       else f"R2 起出现 first_frame: {ff5}"))

        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    print("\n===== e2e2 用例 C·显式升级短答 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("C·显式升级短答", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
