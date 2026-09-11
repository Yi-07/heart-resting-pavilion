"""e2e2 用例 B·求助句留场(ADR-003):采集态中 `你说我该怎么办啊` 不切 answer 抢占。

断言:无 first_frame(未重开采集),后续帧在 collect 帧序内(text_delta 或 draw),
黑板状态保留(无 done 重开,采集态未清)。
"""

from __future__ import annotations

import asyncio

from e2e_lib import WsClient, result, user_text

R1 = "最近很焦虑睡不着"
R2 = "你说我该怎么办啊"


async def main() -> None:
    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        # R1: 进采集
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "R1 first_frame(route=collect)" if got else "R1 first_frame 未到达"))
        r1_draw = await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿 draw")
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")

        # R2: 求助句 → 留 collect 轻回应
        await asyncio.sleep(4.0)
        t2 = await c.send(user_text(R2))
        got = await c.wait_for(
            lambda m: m.get("type") in ("text_delta", "draw") and m is not None,
            120, "R2 回应(text_delta 或 draw)")
        checks.append((got is not None, "R2 有回应帧" if got else "R2 无任何回应帧"))
        # 给流一点时间走完,再断言窗口内帧序
        await asyncio.sleep(8.0)
        win = c.frames_since(t2)
        ffs = [m for _, m in win if m.get("type") == "first_frame"]
        dones = [m for _, m in win if m.get("type") == "done"]
        texts = [m.get("text") or "" for _, m in win if m.get("type") == "text_delta"]
        draws = [m for _, m in win if m.get("type") == "draw"]
        checks.append((not ffs, "R2 无 first_frame(未重开采集)" if not ffs
                       else f"R2 出现 first_frame: {ffs}"))
        checks.append((bool(texts) or bool(draws),
                       f"R2 在 collect 帧序内(text_delta {len(texts)} 段 / draw {len(draws)} 帧)"
                       if texts or draws else "R2 帧序既无 text_delta 也无 draw"))
        checks.append((not dones, "R2 无 done(采集态保留)" if not dones
                       else f"R2 出现 done(疑似回合被重开): {dones}"))
        body = "".join(texts)
        if body:
            print(f"  -- R2 陪聊/轻回应正文: {body[:160]}", flush=True)

        # 回正题:求助句只消费了 pending 问题(陪聊轮不填格,设计如此),
        # 下一条正常内容先重发问题,再下一条才出增量 draw——两步都验证黑板保留
        await asyncio.sleep(4.0)
        await c.send(user_text("就是开会那次，我满脑子都是要搞砸了。"))
        q3 = await c.wait_for(lambda m: m.get("type") == "text_delta", 120, "R3 重发问题")
        ff3 = [m for _, m in c.frames_since(t2) if m.get("type") == "first_frame"]
        checks.append((q3 is not None, "R3 采集恢复:问题重发(预置库,瞬时)" if q3
                       else "R3 无问句帧"))
        checks.append((not ff3, "R2+R3 无 first_frame(黑板状态保留)" if not ff3
                       else f"R2+R3 出现 first_frame: {ff3}"))

        await asyncio.sleep(4.0)
        await c.send(user_text("领导当众批评我，我脑子里一片空白。"))
        d4 = await c.wait_for(lambda m: m.get("type") == "draw", 120, "R4 增量 draw")
        r1_seq = (r1_draw[1] or {}).get("seq") if r1_draw else None
        r4_seq = d4[1].get("seq") if d4 else None
        checks.append((d4 is not None and r1_seq is not None and r4_seq is not None
                       and r4_seq > r1_seq,
                       f"R4 增量 draw seq={r4_seq}(> R1 的 {r1_seq},采集续上)" if d4 else
                       f"R4 增量 draw 未到达(R4 seq={r4_seq}, R1 seq={r1_seq})"))
        ff4 = [m for _, m in c.frames_since(t2) if m.get("type") == "first_frame"]
        checks.append((not ff4, "R2 起全程无 first_frame(未重开采集)" if not ff4
                       else f"R2 起出现 first_frame: {ff4}"))

        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    print("\n===== e2e2 用例 B·求助句留场 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("B·求助句留场", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
