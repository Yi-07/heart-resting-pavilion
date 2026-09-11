"""用例 B·ASR 语音输入 → collect 全链。

语音素材以命令行参数传入(真实中文语音 wav;原型区的 bench 样本已随 A2 归档删除,
音频不 gitignore 入库——安全红线 §7 音频绝不落库,repo 不存测试语音):
`uv run python tests/e2e/e2e_b_asr.py 路径/样本.wav`。断言:
  1. 后端日志出现 asr_transcribed 且 length>10
  2. collect 入场 first_frame(route=collect)
  3. 正常帧序(粗稿 draw + 第1问 text_delta)
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import time
from pathlib import Path

from e2e_lib import WsClient, result, user_audio

WAV = Path(sys.argv[1]) if len(sys.argv) > 1 else None
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def find_asr_log(session_id: str) -> str | None:
    """debug 日志为 loguru JSON 序列化行;按 session_id 找本会话的 asr_transcribed。"""
    logs = sorted(LOG_DIR.glob("debug_*.log"))
    if not logs:
        return None
    for line in reversed(logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()):
        if "asr_transcribed" not in line:
            continue
        try:
            rec = json.loads(line)["record"]
        except Exception:  # noqa: BLE001, S112 — 日志行截断/非 JSON 跳过,继续向前找
            continue
        extra = rec.get("extra", {})
        if extra.get("event") == "asr_transcribed" and extra.get("session_id") == session_id:
            return f"length={extra.get('length')} fingerprint={extra.get('fingerprint')}"
    return None


async def main() -> None:
    if WAV is None or not WAV.is_file():
        result("B·ASR 语音输入", False, "未传语音素材或文件不存在:python e2e_b_asr.py 样本.wav")
        return
    b64 = base64.b64encode(WAV.read_bytes()).decode("ascii")
    checks: list[tuple[bool, str]] = []
    t_send = None

    async with WsClient() as c:
        print(f"  发送音频: {WAV.name} ({WAV.stat().st_size} bytes)")
        t_send = await c.send(user_audio(b64))

        # ASR 模型首次加载可能较慢,放宽到 120s
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 120, "first_frame")
        if got is None:
            checks.append((False, "first_frame 未到达(ASR 失败或超时)"))
            session_id = ""
        else:
            _, ff = got
            session_id = ff.get("session_id") or ""
            checks.append((ff.get("route") == "collect",
                           (f"first_frame route={ff.get('route')} emotion={ff.get('emotion_label')!r} "
                           f"session={session_id} (ASR+路由 {got[0] - t_send:.2f}s)")))

        got = await c.wait_for(lambda m: m.get("type") == "draw", 90, "粗稿 draw")
        checks.append((got is not None, "粗稿 draw" if got else "粗稿 draw 未到达"))

        got = await c.wait_for(lambda m: m.get("type") == "text_delta", 90, "第1问")
        checks.append((got is not None, "第1问 text_delta" if got else "第1问未到达"))

        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs}"))

    time.sleep(3.0)  # noqa: ASYNC251 — 阻塞等日志刷盘,脚本内无并发可让
    log_line = find_asr_log(session_id)
    m = re.search(r"length=(\d+)", log_line) if log_line else None
    ok_log = log_line is not None and m is not None and int(m.group(1)) > 10
    checks.append((ok_log,
                   f"日志 asr_transcribed: {log_line}" if log_line
                   else f"日志未找到本会话({session_id})的 asr_transcribed"))

    print("\n===== 用例 B·ASR 语音输入 =====")
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("B·ASR", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
