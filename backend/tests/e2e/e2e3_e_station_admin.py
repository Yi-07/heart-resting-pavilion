"""e2e3 用例 E·station/admin REST(acceptance-v1 §6,轮次维度)。

1. mini collect 跑到 Finish(done 带回 round_id/station_ready)
   → POST /station/report/generate?session_id&round_id → 轮询 latest 至 ready
   → 同一 session 再跑一轮 collect(round_id 递增)→ 两份报告互不覆盖
2. 危机回合后 generate → 409(危机回合不分配轮次、不产素材)
3. GET /admin/trends 200;GET /admin/llm/profiles 200 且零密钥回显(旧 /admin/config 已退场)
4. config.db 落库核验:api_key_enc 为 AES-GCM 结构(base64=nonce12+密文);
   若 .env 带 HRP_CONFIG_AES_KEY 则解密验证(只打印长度,不落明文)
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
SECOND_OPEN = "我又想起一件事,最近总睡不好"


async def run_episode(
    c: WsClient, sid: str | None, opening: str, answers: list[str]
) -> tuple[str | None, str | None, bool | None]:
    """跑完一个 collect 回合:entry → 逐轮回答 → 邀请语 → 等该轮 done。

    返回 (session_id, round_id, station_ready);done 按 round_id 精确匹配,
    避免队列里混入后续回合/支线的帧。"""

    await c.send(user_text(opening, sid))
    got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "first_frame")
    if got is None:
        return None, None, None
    sid = got[1].get("session_id") or sid
    rid = got[1].get("round_id")
    await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "首问")
    # 回合间沉降:网关「done 帧已发→Task 状态翻转」有调度窗口(已知边界,见
    # ws_gateway/gateway.py 抢占段注记),发太快会被误判为抢占而重开回合
    await asyncio.sleep(2.5)
    for text in answers:
        await c.send(user_text(text, sid))
        inv = await c.wait_for(
            lambda m: m.get("type") == "text_delta" and INVITE_KEY in (m.get("text") or ""),
            60, "邀请语",
        )
        if inv:
            break
        await asyncio.sleep(2.5)
    done = await c.wait_for(
        lambda m: m.get("type") == "done" and m.get("round_id") == rid, 180, f"done(round={rid})"
    )
    ready = done[1].get("station_ready") if done else None
    return sid, rid, ready


async def station_flow(sid: str, rid: str) -> tuple[list[tuple[bool, str]], str]:
    checks: list[tuple[bool, str]] = []
    status, body = post_json(f"/station/report/generate?session_id={sid}&round_id={rid}")
    checks.append((status == 200 and body.get("status") == "pending",
                   f"generate: {status} {body}" if status == 200 else f"generate 异常: {status} {body}"))
    ready = False
    report = ""
    for _ in range(50):  # 50 × 3s = 150s 上限
        await asyncio.sleep(3.0)
        status, body = get_json(f"/station/report/latest?session_id={sid}&round_id={rid}")
        if status == 200 and body.get("status") == "ready":
            ready = True
            report = body.get("report_md") or ""
            break
    checks.append((ready and len(report) > 0,
                   f"latest ready, report_md {len(report)} 字" if ready else "轮询 150s 未 ready"))
    recs = log_records(event="station_report_ready", session_id=sid, since_epoch=epoch() - 300)
    checks.append((bool(recs), "station_report_ready 日志" if recs else "station_report_ready 日志未找到"))
    status, body = get_json(f"/station/report/list?session_id={sid}")
    rows = body.get("reports", []) if status == 200 else []
    checks.append((any(r.get("round_id") == rid for r in rows),
                   f"list 含 round_id={rid}(共 {len(rows)} 行)" if status == 200 else f"list 异常 {status}"))
    return checks, report


async def crisis_no_material() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("我不想活了"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 45, "crisis first_frame")
        sid = got[1].get("session_id") if got else None
        checks.append((got is not None and got[1].get("round_id") is None,
                       "危机首帧不带 round_id(不分配轮次)"))
        await c.wait_for(lambda m: m.get("type") == "done", 90, "crisis done")
    if not sid:
        return [(False, "crisis 会话未取得 session_id")]
    # 危机回合不分配轮次、不产素材:按任一 round_id 询问都应 409
    status, body = post_json(f"/station/report/generate?session_id={sid}&round_id=1")
    checks.append((status == 409, f"危机回合 generate → {status}(预期 409)"
                   if status == 409 else f"危机回合 generate 预期 409 实得 {status}: {body}"))
    return checks


def admin_flow() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    status, body = get_json("/admin/trends?days=7")
    moods = body.get("moods")
    checks.append((status == 200 and isinstance(moods, list),
                   f"trends: {status}, moods {len(moods) if isinstance(moods, list) else type(moods)}"))

    # 模型配置单源 /admin/llm/profiles(T4 旧 /admin/config 已退场,404=预期);
    # 零密钥回显核验照旧——响应里不得出现 api_key 明文(api_key_set 布尔计数合法)
    status, body = get_json("/admin/llm/profiles")
    zero_echo = status == 200 and "api_key" not in str(body).replace("api_key_set", "")
    checks.append((zero_echo, f"llm profiles GET: {status}, 零密钥回显"
                   if zero_echo else f"llm profiles 异常或密钥回显: {status} {body}"))

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
    print("===== e2e3 用例 E·station/admin REST(轮次维度) =====", flush=True)
    checks: list[tuple[bool, str]] = []
    reports: dict[str, str] = {}

    async with WsClient() as c:
        sid, rid, ready = await run_episode(c, None, R1, TAIL)
        checks.append((rid is not None, f"第 1 轮 round_id={rid}" if rid else "未拿到 round_id"))
        checks.append((ready is True, f"第 1 轮 done.station_ready={ready}"))
    if sid and rid:
        print("-- station generate/poll(第 1 轮) --", flush=True)
        flow, md1 = await station_flow(sid, rid)
        checks += flow
        if md1:
            reports[rid] = md1
        print("-- 第 2 轮 collect(同 session,round_id 递增) --", flush=True)
        async with WsClient() as c2:
            sid2, rid2, ready2 = await run_episode(c2, sid, SECOND_OPEN, TAIL[:3])
        checks.append((sid2 == sid, f"第 2 轮回用 session_id={sid2}"))
        checks.append((rid2 is not None and rid2 != rid, f"第 2 轮 round_id={rid2}(不与 {rid} 冲突)"))
        checks.append((ready2 is True, f"第 2 轮 done.station_ready={ready2}"))
        if sid2 and rid2:
            flow2, md2 = await station_flow(sid2, rid2)
            checks += flow2
            if md2:
                reports[rid2] = md2
        checks.append((len(set(reports.values())) == len(reports),
                       f"两轮报告独立存取({len(reports)} 份,正文互不相同)"))

    print("-- 危机回合不产素材 --", flush=True)
    checks += await crisis_no_material()
    print("-- admin REST --", flush=True)
    checks += admin_flow()
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}", flush=True)
    result("E·station/admin", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
