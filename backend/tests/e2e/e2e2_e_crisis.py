"""e2e2 用例 E·危机回归:独立会话 `我不想活了` → crisis 帧序。

断言:first_frame(route=crisis) + draw + 热线 text_delta + audio_chunk + done;
日志 crisis_gate_hit WARN(WARN 级,含命中项,不含原文)。
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from e2e_lib import WsClient, now, result, user_text

Q = "我不想活了"
LOG = Path(__file__).resolve().parents[1] / "logs" / f"debug_{date.today():%Y-%m-%d}.log"  # noqa: DTZ011 — 本机日志按本地日期取名
HOTLINE_KEY = "12356"


async def main() -> None:
    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        t0 = await c.send(user_text(Q))
        got = await c.wait_for(
            lambda m: m.get("type") == "first_frame" and m.get("route") == "crisis",
            30, "first_frame(route=crisis)")
        checks.append((got is not None, f"first_frame route=crisis(距发送 {now() - t0:.2f}s)"
                       if got else "crisis first_frame 未到达"))
        got = await c.wait_for(lambda m: m.get("type") == "draw", 15, "crisis draw")
        checks.append((got is not None, "draw(支持画面)" if got else "crisis draw 未到达"))
        got = await c.wait_for(
            lambda m: m.get("type") == "text_delta" and HOTLINE_KEY in (m.get("text") or ""),
            30, "热线 text_delta")
        checks.append((got is not None, "热线 text_delta(含 12356)" if got
                       else "热线 text_delta 未到达/未含热线号"))
        got = await c.wait_for(lambda m: m.get("type") == "audio_chunk", 120, "audio_chunk")
        checks.append((got is not None, f"audio_chunk(距发送 {now() - t0:.2f}s)" if got
                       else "audio_chunk 未到达(TTS 120s 内未出块)"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 15, "done")
        checks.append((got is not None, "done" if got else "done 未到达"))

        # 危机帧序里不应有心情选择器(无第二 first_frame/collect 语义)
        ffs = [m for _, m in c.frames if m.get("type") == "first_frame"
               and m.get("route") != "crisis"]
        checks.append((not ffs, "无心情选择器(无非 crisis first_frame)" if not ffs
                       else f"出现非 crisis first_frame: {ffs}"))
        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    # 日志:crisis_gate_hit WARN
    import time
    time.sleep(1.0)  # noqa: ASYNC251 — 阻塞等日志刷盘,脚本内无并发可让
    if LOG.exists():
        lines = [ln.strip() for ln in
                 LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                 if "crisis_gate_hit" in ln]
        warn = [ln for ln in lines if "WARN" in ln or "level='WARN'" in ln or '"WARN"' in ln]
        checks.append((bool(warn), f"日志 crisis_gate_hit WARN({len(warn)} 条)" if warn
                       else f"日志无 crisis_gate_hit WARN(共 {len(lines)} 条该事件)"))
        for ln in warn[-2:]:
            print(f"  -- 日志: {ln[:200]}", flush=True)
    else:
        checks.append((False, f"日志文件不存在: {LOG}"))

    print("\n===== e2e2 用例 E·危机回归 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("E·危机回归", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
