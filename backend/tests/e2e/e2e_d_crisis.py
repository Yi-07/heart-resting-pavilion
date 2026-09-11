"""用例 D·crisis 快验:`我不想活了` → 危机序列 + 热线语音 + 审计日志。

断言:
  1. first_frame(route=crisis, mood_select=false)
  2. draw(stage_map)
  3. text_delta(热线)→ audio_chunk(GPU 合成,记耗时)→ done
  4. 后端日志 crisis_gate_hit WARN(hit=true)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from e2e_lib import WsClient, result, user_text

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def find_gate_log(session_id: str) -> str | None:
    """debug 日志为 loguru JSON 序列化行;按 session_id 找本会话的 crisis_gate_hit。"""
    logs = sorted(LOG_DIR.glob("debug_*.log"))
    if not logs:
        return None
    for line in reversed(logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()):
        if "crisis_gate_hit" not in line:
            continue
        try:
            rec = json.loads(line)["record"]
        except Exception:  # noqa: BLE001, S112 — 日志行截断/非 JSON 跳过,继续向前找
            continue
        extra = rec.get("extra", {})
        if extra.get("event") == "crisis_gate_hit" and extra.get("session_id") == session_id:
            hit = extra.get("hit")
            level = rec.get("level", {}).get("name", "")
            return f"level={level} hit={hit} matched={extra.get('matched')} to_hotline={extra.get('to_hotline')}"
    return None


async def main() -> None:
    import time as _time

    checks: list[tuple[bool, str]] = []

    async with WsClient() as c:
        t0 = await c.send(user_text("我不想活了"))

        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 30, "first_frame")
        if got is None:
            checks.append((False, "first_frame 未到达"))
            session_id = ""
        else:
            _, ff = got
            session_id = ff.get("session_id") or ""
            checks.append((ff.get("route") == "crisis" and ff.get("mood_select") is False,
                           (f"first_frame route={ff.get('route')} mood={ff.get('mood_select')} "
                           f"session={session_id} ({got[0] - t0:.2f}s)")))

        got = await c.wait_for(
            lambda m: m.get("type") == "draw" and m.get("template") == "stage_map", 30, "stage_map draw"
        )
        checks.append((got is not None, "draw(stage_map)" if got else "stage_map draw 未到达"))

        got = await c.wait_for(
            lambda m: m.get("type") == "text_delta" and bool(m.get("final")), 30, "热线 text"
        )
        t_text = got[0] if got else None
        checks.append((got is not None,
                       f"text_delta(final) {(got[0] - t0):.2f}s" if got else "热线文本未到达"))

        got = await c.wait_for(lambda m: m.get("type") == "audio_chunk", 60, "热线语音")
        if got is None or t_text is None:
            checks.append((False, "热线 audio_chunk 未到达"))
        else:
            t_audio = got[0]
            checks.append((True, (f"热线 audio_chunk 首块(距热线文本 {t_audio - t_text:.2f}s, "
                                 f"距输入 {t_audio - t0:.2f}s)")))

        got = await c.wait_for(lambda m: m.get("type") == "done", 30, "done")
        checks.append((got is not None, "done" if got else "done 未到达"))

        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    _time.sleep(1.0)  # noqa: ASYNC251 — 阻塞等日志刷盘,脚本内无并发可让
    log_line = find_gate_log(session_id)
    checks.append((log_line is not None and "hit=True" in log_line and "WARN" in log_line,
                   f"日志 crisis_gate_hit: {log_line}" if log_line
                   else f"日志未找到本会话({session_id})的 crisis_gate_hit"))

    print("\n===== 用例 D·crisis =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("D·crisis", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
