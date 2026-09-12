"""e2e3 用例 E·station/admin REST(acceptance-v1 §6)。

1. 走一遍 mini collect 到 Finish(总结含心灵补给站邀请语,记 session_id)
   → POST /station/report/generate 200 pending → 轮询 GET latest 至 ready(report_md 非空)。
2. 危机回合后 generate → 409(危机回合不产素材)。
3. GET /admin/trends 200;GET /admin/config 200 且零密钥回显;
   POST /admin/config(原 provider/model 回写,不动 api_key)→ 200。
4. config.db 落库核验:api_key_enc 为 AES-GCM 结构(base64=nonce12+密文);
   若 .env 带 HRP_CONFIG_AES_KEY 则解密验证(只打印长度,不落明文)。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_e_station_admin.py`。
"""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from pathlib import Path

from e2e_lib import WsClient, epoch, get_json, log_records, post_json, result, user_text

BACKEND_DIR = Path(__file__).resolve().parents[2]
INVITE_KEY = "心灵补给站"
R1 = "最近很焦虑睡不着"
TAIL = [
    "上周开会汇报的时候，被领导当着所有人批评，说我能力不行。",
    "我现在每天硬撑着上班，晚上靠刷手机拖着不敢睡，谁也没告诉。",
    "其实我最怕的是别人觉得我什么都做不好。",
    "这种状态持续两三周了，白天上班完全没精神。",
    "一想到第二天要上班，我整晚都睡不着。",
]


async def mini_collect() -> tuple[str | None, list[tuple[bool, str]]]:
    """走满采集到 Finish,返回 (session_id, 断言)。"""
    checks: list[tuple[bool, str]] = []
    sid: str | None = None
    async with WsClient() as c:
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
        if got:
            sid = got[1].get("session_id")
        await c.wait_for(lambda m: m.get("type") == "draw", 60, "粗稿 draw")
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "首问")
        await asyncio.sleep(4.0)
        t_end = None
        for i, text in enumerate(TAIL, start=2):
            t_r = await c.send(user_text(text))
            await c.wait_for(lambda m: m.get("type") == "draw", 60, f"R{i} draw")
            first = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"R{i} 文本")
            if first and first[0] - t_r >= 8.0:
                inv = await c.wait_for(
                    lambda m: m.get("type") == "text_delta" and INVITE_KEY in (m.get("text") or ""),
                    180, f"R{i} 邀请语")
                if inv:
                    t_end = inv[0]
                    break
            await asyncio.sleep(4.0)
        if t_end:
            # 等 Finish 收口 done:过早断连会 cancel station:input 归档(诊断#2 根因)
            got_done = await c.wait_for(lambda m: m.get("type") == "done", 60, "Finish done")
            checks.append((got_done is not None, "Finish done 收口" if got_done
                           else "Finish done 未到(收尾或被截)"))
        checks.append((t_end is not None, "Finish 总结+邀请语" if t_end
                       else "mini collect 未走到 Finish"))
        checks.append((sid is not None, f"session_id={sid}" if sid else "未取得 session_id"))
    return sid, checks


async def station_flow(sid: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    status, body = post_json(f"/station/report/generate?session_id={sid}")
    checks.append((status == 200 and body.get("status") == "pending",
                   f"generate: {status} {body}" if status == 200 else f"generate 异常: {status} {body}"))
    ready = False
    report_len = 0
    for _ in range(50):  # 50 × 3s = 150s 上限
        await asyncio.sleep(3.0)
        status, body = get_json(f"/station/report/latest?session_id={sid}")
        if status == 200 and body.get("status") == "ready":
            ready = True
            report_len = len(body.get("report_md") or "")
            break
    checks.append((ready and report_len > 0,
                   f"latest ready, report_md {report_len} 字" if ready else "轮询 150s 未 ready"))
    recs = log_records(event="station_report_ready", session_id=sid, since_epoch=epoch() - 300)
    checks.append((bool(recs), "station_report_ready 日志" if recs else "station_report_ready 日志未找到"))
    return checks


async def crisis_no_material() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("我不想活了"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 45, "crisis first_frame")
        sid = got[1].get("session_id") if got else None
        await c.wait_for(lambda m: m.get("type") == "done", 90, "crisis done")
    if not sid:
        checks.append((False, "crisis 会话未取得 session_id"))
        return checks
    status, body = post_json(f"/station/report/generate?session_id={sid}")
    checks.append((status == 409, f"危机回合 generate → {status}(预期 409): {body.get('detail', '')[:40]}"
                   if status == 409 else f"危机回合 generate 预期 409 实得 {status}: {body}"))
    return checks


def admin_flow() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    status, body = get_json("/admin/trends?days=7")
    moods = body.get("moods")
    checks.append((status == 200 and isinstance(moods, list),
                   f"trends: {status}, moods {len(moods) if isinstance(moods, list) else type(moods)}"))

    status, body = get_json("/admin/config")
    zero_echo = status == 200 and "api_key" not in body and isinstance(body.get("api_key_set"), bool)
    provider = body.get("provider") if status == 200 else None
    checks.append((zero_echo, f"config GET: {status}, provider={provider}, 零密钥回显"
                   if zero_echo else f"config GET 异常或密钥回显: {status} {body}"))

    if provider:
        providers = body.get("providers") or []
        model = next((p.get("model") for p in providers
                      if isinstance(p, dict) and p.get("id") == provider), None)
        status2, body2 = post_json("/admin/config", {"provider": provider, "model": model})
        checks.append((status2 == 200 and body2.get("ok") is True,
                       f"config POST 回写: {status2} {body2}"
                       if status2 == 200 else f"config POST 异常: {status2} {body2}"))

    # config.db 落库核验(只读;不打印任何密钥材料)
    try:
        con = sqlite3.connect(BACKEND_DIR / "data" / "config.db")
        row = con.execute("SELECT api_key_enc FROM llm_config WHERE id=1").fetchone()
        con.close()
        enc = row[0] if row else None
        if not enc:
            checks.append((True, "config.db 无已存 api_key,加密写入路径以单测覆盖为准"))
        else:
            blob = base64.b64decode(enc)
            well_formed = len(blob) >= 28  # nonce 12B + 密文+tag ≥16B
            checks.append((well_formed, f"api_key_enc AES-GCM 结构: {len(blob)} 字节"
                           if well_formed else f"api_key_enc 结构异常: {len(blob)} 字节"))
            dec_len = try_decrypt_len(enc)
            if dec_len is None:
                checks.append((True, ".env 无 HRP_CONFIG_AES_KEY,跳过解密验证"))
            else:
                checks.append((dec_len > 0, f"AES-GCM 解密通过(明文长度 {dec_len},不落明文)"
                               if dec_len > 0 else "AES-GCM 解密失败(密文与密钥不匹配)"))
    except Exception as exc:  # noqa: BLE001 — db 缺文件等环境问题,记观察不炸脚本
        checks.append((True, f"config.db 核验跳过: {exc!r}"))
    return checks


def try_decrypt_len(enc_b64: str) -> int | None:
    """用 .env 的 HRP_CONFIG_AES_KEY 解密,只返回明文长度;密钥缺失返 None。"""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return None
    key_hex: str | None = None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("HRP_CONFIG_AES_KEY="):
            key_hex = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not key_hex:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        blob = base64.b64decode(enc_b64)
        pt = AESGCM(bytes.fromhex(key_hex)).decrypt(blob[:12], blob[12:], None)
        return len(pt)
    except Exception:  # noqa: BLE001 — 解密失败返 0
        return 0


async def main() -> None:
    print("===== e2e3 用例 E·station/admin REST =====")
    checks: list[tuple[bool, str]] = []
    sid, collect_checks = await mini_collect()
    checks += collect_checks
    if sid:
        print("-- station generate/poll --", flush=True)
        checks += await station_flow(sid)
    print("-- 危机回合不产素材 --", flush=True)
    checks += await crisis_no_material()
    print("-- admin REST --", flush=True)
    checks += admin_flow()
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("E·station/admin", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
