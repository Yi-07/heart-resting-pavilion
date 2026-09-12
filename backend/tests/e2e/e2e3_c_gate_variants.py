"""e2e3 用例 C·门控复杂变体(acceptance-v1 §3 复杂变体两条)。

C1 概念问句·复杂变体:采集中发 `对了，我一直好奇，mindfulness 这种练习
   是不是就是网上说的冥想啊` → 短答支线(无 first_frame/draw,done 收口,
   正文非空);若判为内容轮(出 draw)则记录实测行为,不硬判挂——但两种
   分支都不允许 first_frame(重开黑板=挂);下一条内容轮增量 draw seq 接得上。
C2 求助句·复杂变体:采集中发 `晚上睁着眼睛到两三点，你说我到底要不要去
   医院看看啊，还是自己调节调节就行` → 留场轻回应(无 first_frame,帧在
   collect 帧序内),不切 answer 抢占;后续内容轮采集恢复。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_c_gate_variants.py`。
"""

from __future__ import annotations

import asyncio
from typing import Any

from e2e_lib import WsClient, result, user_text

R1 = "最近很焦虑睡不着"
R2 = "上周开会的时候，领导当众批评我，我脑子里一片空白。"
CONCEPT_COMPLEX = "对了，我一直好奇，mindfulness 这种练习是不是就是网上说的冥想啊"
HELP_COMPLEX = "晚上睁着眼睛到两三点，你说我到底要不要去医院看看啊，还是自己调节调节就行"
RECOVER = "后来我连着两周天天如此，早上起来头都是昏的。"


async def collect_round(c: WsClient, text: str, label: str) -> tuple[float, dict[str, Any]]:
    """发一条采集轮输入,等增量 draw + 问句流收尾;采集内容轮设计上无 done 帧。"""
    t = await c.send(user_text(text))
    d = await c.wait_for(lambda m: m.get("type") == "draw", 60, f"{label} draw")
    await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"{label} 问句")
    await asyncio.sleep(4.0)  # AskNext 无 done/final 收尾,轮间定时留白防抢占
    return t, (d[1] if d else {})


def no_first_frame(checks: list[tuple[bool, str]], c: WsClient, t: float,
                   label: str) -> list[tuple[float, dict[str, Any]]]:
    win = c.frames_since(t)
    ffs = [m for _, m in win if m.get("type") == "first_frame"]
    checks.append((not ffs, f"{label} 无 first_frame(未重开黑板)" if not ffs
                   else f"{label} 出现 first_frame: {ffs}"))
    return win


async def scene_concept_complex() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "R1 first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "R1 first_frame(route=collect)" if got else "R1 first_frame 未到达"))
        await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿 draw")
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")
        await asyncio.sleep(4.0)  # 与 b/c 对齐:R1 收尾留白,防踩抢占弃态
        _t2, r2_draw = await collect_round(c, R2, "R2")
        r2_seq = r2_draw.get("seq")

        # 复杂概念变体
        t3 = await c.send(user_text(CONCEPT_COMPLEX))
        d3 = await c.wait_for(lambda m: m.get("type") == "done", 150, "C1 done")
        win = no_first_frame(checks, c, t3, "C1")
        draws = [m for _, m in win if m.get("type") == "draw"]
        texts = [m.get("text") or "" for _, m in win if m.get("type") == "text_delta"]
        body = "".join(texts)
        if draws:
            checks.append((True, (f"C1 判为内容轮(记录实测,不硬判挂): "
                                  f"draw seq={[m.get('seq') for m in draws]}")))
        elif d3 is not None:
            checks.append((len(body) > 30, f"C1 短答支线: 正文 {len(body)} 字, done 到"
                           if len(body) > 30 else f"C1 短答正文过短({len(body)}): {body!r}"))
        else:
            checks.append((len(body) > 0, (f"C1 轻回应留场(无 done,记录实测): "
                                           f"正文 {len(body)} 字: {body[:40]!r}")))

        # 恢复采集:增量 draw seq 接得上
        await asyncio.sleep(4.0)
        _t4, r4_draw = await collect_round(c, RECOVER, "R4")
        r4_seq = r4_draw.get("seq")
        base_seq = draws[-1].get("seq") if draws else r2_seq
        checks.append((isinstance(r4_seq, int) and isinstance(base_seq, int) and r4_seq > base_seq,
                       f"恢复采集 draw seq={r4_seq}(> {base_seq})" if r4_seq
                       else f"恢复采集 draw 未到/seq 异常(r4={r4_seq}, base={base_seq})"))
    return checks


async def scene_help_complex() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "R1 first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "R1 first_frame(route=collect)" if got else "R1 first_frame 未到达"))
        r1_draw = await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿 draw")
        r1_seq = (r1_draw[1].get("seq") or 0) if r1_draw else 0
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")
        await asyncio.sleep(4.0)

        # 复杂求助变体:就医犹豫
        t2 = await c.send(user_text(HELP_COMPLEX))
        d2 = await c.wait_for(lambda m: m.get("type") == "done", 150, "C2 done")
        win = no_first_frame(checks, c, t2, "C2")
        draws = [m for _, m in win if m.get("type") == "draw"]
        texts = [m.get("text") or "" for _, m in win if m.get("type") == "text_delta"]
        body = "".join(texts)
        in_collect = bool(texts) or bool(draws)
        checks.append((in_collect and len(body) > 0,
                       (f"C2 留场轻回应: 正文 {len(body)} 字, "
                        f"done={'到' if d2 else '未到(轻回应设计可无)'}")
                       if in_collect else "C2 无任何 collect 帧序内容(疑似切走/无回应)"))
        # 不切 answer 的另一面:不应出现整段 answer 长文(轻回应)
        checks.append((len(body) < 400, f"C2 回应长度 {len(body)} 字(轻回应)"
                       if len(body) < 400 else f"C2 回应 {len(body)} 字,疑似整段 answer 抢占"))

        # 采集恢复
        await asyncio.sleep(4.0)
        _t3, r3_draw = await collect_round(c, RECOVER, "R3")
        r3_seq = r3_draw.get("seq")
        checks.append((isinstance(r3_seq, int) and r3_seq > r1_seq,
                       f"采集恢复 draw seq={r3_seq}(> {r1_seq})" if r3_seq
                       else f"采集恢复 draw 未到/seq 异常(r3={r3_seq}, r1={r1_seq})"))
    return checks


async def main() -> None:
    print("===== e2e3 用例 C·门控复杂变体 =====")
    print("-- C1 概念问句复杂变体 --", flush=True)
    checks = await scene_concept_complex()
    print("-- C2 求助句复杂变体 --", flush=True)
    checks += await scene_help_complex()
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("C·门控复杂变体", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
