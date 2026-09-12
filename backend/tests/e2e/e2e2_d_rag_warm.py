"""e2e2 用例 D·RAG 启动预热 + 检索防阻塞(ADR-003)。

1. 读 backend/logs/debug_当日.log:确认 rag_warm_ready 存在;统计 event_loop_lag WARN。
2. WS 独立 answer 输入 `什么是正念`:text_delta 流正常、帧间隔无 >5s 冻结、done 正常。
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from e2e_lib import T0, URI, WsClient, now, result, user_text

Q = "什么是正念"
LOG = Path(__file__).resolve().parents[2] / "logs" / f"debug_{date.today():%Y-%m-%d}.log"  # noqa: DTZ011 — 本机日志按本地日期取名


def check_log() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    if not LOG.exists():
        return [(False, f"日志文件不存在: {LOG}")]
    content = LOG.read_text(encoding="utf-8", errors="replace")
    warm = [ln for ln in content.splitlines() if "rag_warm_ready" in ln]
    checks.append((bool(warm), f"rag_warm_ready 存在({len(warm)} 条)" if warm
                   else "rag_warm_ready 不存在(预热未完成或失败)"))
    for ln in warm:
        print(f"  -- 日志: {ln.strip()[:160]}", flush=True)
    fail = [ln for ln in content.splitlines() if "rag_warm_failed" in ln]
    if fail:
        for ln in fail:
            print(f"  !! 日志: {ln.strip()[:160]}", flush=True)
    lags = [ln for ln in content.splitlines() if "event_loop_lag" in ln]
    checks.append((not lags, "日志无 event_loop_lag WARN" if not lags
                   else f"日志出现 {len(lags)} 条 event_loop_lag(需报告)"))
    for ln in lags[:5]:
        print(f"  !! event_loop_lag: {ln.strip()[:200]}", flush=True)
    return checks


async def main() -> None:
    checks = check_log()

    async with WsClient() as c:
        t0 = await c.send(user_text(Q))
        got = await c.wait_for(lambda m: m.get("type") == "text_delta", 90, "首段 text_delta")
        checks.append((got is not None, f"首段 text_delta 距发送 {now() - t0:.2f}s" if got
                       else "answer text_delta 未到达"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 120, "done")
        checks.append((got is not None, "done 到达" if got else "done 未到达"))

        # 帧间隔:TTFT(发送→首帧)单列(LLM 首 token 延迟,非阻塞证据看 event_loop_lag);
        # 首帧之后的相邻帧间隔 >5s 才算流中冻结
        win = c.frames_since(t0)
        gaps: list[tuple[float, str]] = []
        prev = win[0][0] if win else t0
        for ft, m in win[1:]:
            gap = ft - prev
            if gap > 5.0:
                gaps.append((gap, m.get("type", "?")))
            prev = ft
        tail_gap = now() - prev
        if win and tail_gap > 5.0:
            gaps.append((tail_gap, "(尾部静默)"))
        checks.append((not gaps, "首帧后帧间隔无 >5s 冻结" if not gaps
                       else f"首帧后出现 >5s 帧间隔: {[(round(g, 2), t) for g, t in gaps]}"))
        ndelta = sum(1 for _, m in win if m.get("type") == "text_delta")
        checks.append((ndelta >= 2, f"text_delta 流式 {ndelta} 段" if ndelta >= 2
                       else f"text_delta 仅 {ndelta} 段(疑似整段一次吐出)"))
        total = sum(len(m.get("text") or "") for _, m in win if m.get("type") == "text_delta")
        print(f"  -- answer 总字数 {total},帧数 {len(win)},endpoint {URI},t0 偏移 "
              f"{T0:.0f}", flush=True)

    print("\n===== e2e2 用例 D·RAG 预热 + 检索防阻塞 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("D·RAG 预热防阻塞", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
