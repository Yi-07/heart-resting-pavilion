"""e2e3 用例 D·语音输入两步式(ADR-004;acceptance-v1 §2 输入链路)。

素材=backend/tests/voices/(gitignore,不入库):
  1. collect_test.wav → POST /asr/transcribe 200,text 非空(len>10);
     asr_transcribed 日志只记 length+fingerprint,不含原文(红线)。
  2. crisis_test.wav → 200,转写含危机词 → 转写文本经 WS 发送照常命中 crisis 全链
     (转写吞词=挂)。
  3. 静音段(内存合成 1s PCM16 零) → 200 空串 + asr_empty 日志。
  4. 故障注入:合法 base64 但非法音频字节 → 503;超限 1.1MB → 413。
  5. 503 后 WS 主链路不受影响(answer 正常完成)。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_d_asr.py`。
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_lib import WsClient, epoch, log_records, post_json, result, user_text

from app.router.gate import CORE_TERMS

VOICES_DIR = Path(__file__).resolve().parents[1] / "voices"


def file_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def silence_wav_b64(seconds: float = 1.0, rate: int = 16000) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return base64.b64encode(buf.getvalue()).decode()


def transcribe(audio_b64: str) -> tuple[int, dict[str, Any]]:
    return post_json("/asr/transcribe", {"audio": audio_b64}, timeout=120.0)


def find_core_term(text: str) -> str | None:
    return next((t for t in CORE_TERMS if t in text), None)


async def ws_crisis_chain(text: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text(text))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 45, "first_frame")
        route = got[1].get("route") if got else None
        checks.append((route == "crisis", f"危机全链命中(route={route})" if route == "crisis"
                       else f"转写文本未命中危机(route={route})"))
        await c.wait_for(lambda m: m.get("type") == "text_delta" and bool(m.get("final")),
                         45, "热线文本")
        got = await c.wait_for(lambda m: m.get("type") == "done", 60, "done")
        checks.append((got is not None, "done 收尾" if got else "done 未到达"))
    return checks


async def ws_answer_ok(label: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("什么是正念"))
        got = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"{label} 首包")
        checks.append((got is not None, f"{label}: WS 主链路正常(首包到)" if got
                       else f"{label}: WS 主链路异常(无首包)"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 120, f"{label} done")
        checks.append((got is not None, f"{label}: done 收尾" if got
                       else f"{label}: done 未到达"))
    return checks


async def main() -> None:
    checks: list[tuple[bool, str]] = []
    print("===== e2e3 用例 D·语音输入两步式 =====")

    # 1. 采集话术段
    f_collect = VOICES_DIR / "collect_test.wav"
    if not f_collect.exists():
        checks.append((False, f"缺素材 {f_collect}"))
    else:
        marker = epoch()
        status, body = transcribe(file_b64(f_collect))
        text = body.get("text") or ""
        checks.append((status == 200, f"collect.wav 转写 status={status}"))
        checks.append((len(text) > 10, f"转写 len={len(text)}: {text[:40]!r}"
                       if len(text) > 10 else f"转写过短({len(text)}): {text!r}"))
        recs = log_records(event="asr_transcribed", since_epoch=marker)
        if recs:
            ex = recs[0]["extra"]
            fp = str(ex.get("fingerprint", ""))
            fp_ok = "sha1:" in fp  # 实际格式 "len={n} sha1:{8hex}"
            checks.append((ex.get("length") == len(text) and fp_ok,
                           f"日志 length={ex.get('length')} fingerprint={fp}"
                           if ex.get("length") == len(text) and fp_ok
                           else f"日志字段异常: length={ex.get('length')} fp={fp}"))
            checks.append((text not in recs[0]["raw"], "日志不含原文(红线)"))
        else:
            checks.append((False, "asr_transcribed 日志未找到"))

    # 2. 危机短句段 → 转写 → 确认文本走 WS 命中危机全链
    f_crisis = VOICES_DIR / "crisis_test.wav"
    if not f_crisis.exists():
        checks.append((False, f"缺素材 {f_crisis}"))
    else:
        status, body = transcribe(file_b64(f_crisis))
        text = body.get("text") or ""
        term = find_core_term(text)
        checks.append((status == 200, f"crisis.wav 转写 status={status}"))
        checks.append((term is not None, f"转写含危机词 {term}: {text[:40]!r}"
                       if term else f"转写吞词(无危机词): {text!r}"))
        if term:
            checks += await ws_crisis_chain(text)

    # 3. 静音段 → 200 空串 + asr_empty
    marker = epoch()
    status, body = transcribe(silence_wav_b64())
    empty_text = (body.get("text") or "") == ""
    empty_log = bool(log_records(event="asr_empty", since_epoch=marker))
    checks.append((status == 200 and empty_text and empty_log,
                   (f"静音段: status={status} text={'' if empty_text else body.get('text')!r} "
                    f"asr_empty={'有' if empty_log else '无'}")))

    # 4. 故障注入:非法音频 → 503;超限 → 413
    garbage_b64 = base64.b64encode(bytes(range(256)) * 8).decode()
    status, body = transcribe(garbage_b64)
    checks.append((status == 503, f"非法音频 status={status} detail={body.get('detail')!r}"
                   if status == 503 else f"非法音频预期 503 实得 {status}: {body}"))
    big_b64 = base64.b64encode(bytes(1_100_000)).decode()
    status, _ = transcribe(big_b64)
    checks.append((status == 413, f"超限音频 status={status}(预期 413)"))

    # 5. 503 后 WS 主链路不受影响
    checks += await ws_answer_ok("503 后")

    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("D·ASR 两步式", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
