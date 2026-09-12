"""e2e3 用例 G·Redis 宕机降级(acceptance-v1 §5;破坏性用例,必须全场最后跑)。

1. docker stop hrp-redis → 对话不崩:answer 与 collect 各走一条正常完成;
2. 日志出现 event=degraded(降级路径);
3. docker start hrp-redis → 等PING PONG → 再走一条 answer 确认恢复。
注意:重启后热层会话数据丢失(无持久化)属预期;本用例清场跑。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_g_redis_down.py`。
"""

from __future__ import annotations

import asyncio
import subprocess
import time

from e2e_lib import WsClient, epoch, log_records, result, user_text

CONTAINER = "hrp-redis"


def docker(*args: str, timeout: float = 60.0) -> tuple[int, str]:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, check=False)
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


async def round_answer_ok(label: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("什么是正念"))
        got = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"{label} 首包")
        checks.append((got is not None, f"{label}: 首包到达(对话未崩)" if got
                       else f"{label}: 无首包(对话崩)"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 120, f"{label} done")
        checks.append((got is not None, f"{label}: done 收尾" if got else f"{label}: done 未到"))
        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, f"{label}: 无 error 帧" if not errs
                       else f"{label}: error 帧 {[m.get('code') for m in errs][:3]}"))
    return checks


async def round_collect_ok() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("最近有点低落，想聊聊"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 45, "collect first_frame")
        route = got[1].get("route") if got else None
        checks.append((route == "collect", f"collect first_frame(route={route})" if route == "collect"
                       else f"collect first_frame 异常(route={route})"))
        got = await c.wait_for(lambda m: m.get("type") == "draw", 60, "collect draw")
        checks.append((got is not None, "粗稿 draw 到达(黑板照常)" if got else "draw 未到达"))
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "collect 问句")
        await c.wait_for(lambda m: m.get("type") == "done", 90, "collect done")
    return checks


def wait_redis_ready(seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        code, out = docker("exec", CONTAINER, "redis-cli", "ping", timeout=15)
        if code == 0 and "PONG" in out:
            return True
        time.sleep(2.0)
    return False


async def main() -> None:
    print("===== e2e3 用例 G·Redis 宕机降级(破坏性,全场最后) =====")
    checks: list[tuple[bool, str]] = []
    code, out = docker("ps", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}")
    if CONTAINER not in out:
        result("G·Redis 宕机降级", False, f"容器 {CONTAINER} 不在运行,跳过执行(现况: {out!r})")
        return

    marker = epoch()
    print(f"-- docker stop {CONTAINER} --", flush=True)
    code, out = docker("stop", CONTAINER, timeout=60)
    if code != 0:
        result("G·Redis 宕机降级", False, f"docker stop 失败: {out!r}")
        return
    await asyncio.sleep(2.0)

    checks += await round_answer_ok("宕机中 answer")
    checks += await round_collect_ok()
    # 记忆层降级事件名=memory_degraded(store.py 各吞点 WARN;B2 实测宕机窗口 4 条)
    recs = log_records(event="memory_degraded", since_epoch=marker) \
        or log_records(event="degraded", since_epoch=marker)
    layers = [str(r["extra"].get("layer")) for r in recs[:5]]
    checks.append((bool(recs), f"降级日志 memory_degraded ×{len(recs)}(layers={layers})"
                   if recs else "日志无 memory_degraded/degraded(降级路径未体现)"))

    print(f"-- docker start {CONTAINER} --", flush=True)
    code, out = docker("start", CONTAINER, timeout=60)
    if code != 0:
        result("G·Redis 宕机降级", False, f"docker start 失败: {out!r}")
        return
    redis_ok = await asyncio.to_thread(wait_redis_ready)
    checks.append((redis_ok, "Redis 重启后 PING→PONG" if redis_ok else "Redis 重启后未就绪"))
    if redis_ok:
        await asyncio.sleep(2.0)  # 等后端连接池重连
        checks += await round_answer_ok("恢复后 answer")

    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("G·Redis 宕机降级", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
