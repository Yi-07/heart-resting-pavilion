"""e2e3 用例 F·记忆与回放(ADR-001/005;acceptance-v1 §5)。

F1 bubbles(30min 内重开,带原身份):collect 两轮后断开 → 同 session_id 重连
   → 先收 replay(mode=bubbles,turns 含用户+assistant 双边原话),再进本回合
   (first_frame + memory_restored,采集上下文接续)。
F2 新连接不推回放:不带身份的新会话,整个连接无 replay 帧。
F3 digest(模拟隔天):collect 走到 Finish(温层有摘要)→ 手动把热层 key TTL 压到 1s
   → 重连 → replay(mode=digest,无 turns,summary 非空)+ memory_restored
   (turns≥1 且 summary>0:新轮次与播种的温层摘要共存,F3 修复后语义)。
F4 clear_memory 治理(--clear 独立入口):POST /admin/clear_memory 200(ok)→
   重连旧会话无回放。清空全部会话记忆/心情/方案书,故拆为独立入口,全场最后单独跑。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_f_replay.py`。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from e2e_lib import WsClient, epoch, log_records, post_json, result, user_text

R1 = "最近很焦虑睡不着"
R2 = "上周开会的时候，领导当众批评我，我脑子里一片空白。"
TAIL = [
    "我现在每天硬撑着上班，晚上靠刷手机拖着不敢睡，谁也没告诉。",
    "其实我最怕的是别人觉得我什么都做不好。",
    "这种状态持续两三周了，白天上班完全没精神。",
    "一想到第二天要上班，我整晚都睡不着。",
]
INVITE_KEY = "心灵补给站"


def replay_frame(frames: list[tuple[float, dict[str, Any]]]) -> dict[str, Any] | None:
    return next((m for _, m in frames if m.get("type") == "replay"), None)


async def collect_two_rounds() -> tuple[str | None, list[tuple[bool, str]]]:
    """起 collect 并走两轮(assistant 问句入轮次),返回 (session_id, 断言)。"""
    checks: list[tuple[bool, str]] = []
    sid: str | None = None
    async with WsClient() as c:
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "R1 first_frame")
        if got:
            sid = got[1].get("session_id")
        await c.wait_for(lambda m: m.get("type") == "draw", 60, "R1 粗稿")
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R1 首问")
        await asyncio.sleep(4.0)
        await c.send(user_text(R2))
        got = await c.wait_for(lambda m: m.get("type") == "draw", 60, "R2 增量")
        checks.append((got is not None, "R2 增量 draw" if got else "R2 增量 draw 未到"))
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "R2 问句")
        await asyncio.sleep(4.0)
    return sid, checks


async def reconnect_bubbles(sid: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    marker = epoch()
    async with WsClient() as c:
        await c.send(user_text("晚上还是两点多才睡着，白天一点精神都没有。", session_id=sid))
        got = await c.wait_for(lambda m: m.get("type") == "replay", 20, "replay")
        if got is None:
            checks.append((False, "重连未收到 replay 帧"))
            return checks
        idx = next(i for i, (_, m) in enumerate(c.frames) if m.get("type") == "replay")
        rp = got[1]
        turns: list[dict[str, Any]] = rp.get("turns") or []
        roles = {t.get("role") for t in turns}
        texts = "".join(t.get("text") or "" for t in turns)
        checks.append((rp.get("mode") == "bubbles", f"replay mode={rp.get('mode')}"))
        checks.append((bool(turns), f"bubbles turns={len(turns)} 条"))
        checks.append(("user" in roles and "assistant" in roles,
                       f"turns 双边: roles={sorted(r for r in roles if r)}"))
        checks.append(("焦虑" in texts, "回放含已说内容(焦虑起)" if "焦虑" in texts
                       else f"回放未含已说内容: {texts[:60]!r}"))
        checks.append((idx == 0, "replay 先于本回合其他帧"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "重连 first_frame")
        checks.append((got is not None and got[1].get("route") == "collect",
                       "重连后 collect first_frame(上下文接续)" if got
                       else "重连后 first_frame 未到达"))
        recs = log_records(event="memory_restored", session_id=sid, since_epoch=marker)
        if recs:
            ex = recs[0]["extra"]
            checks.append((int(ex.get("turns") or 0) > 0,
                           f"memory_restored turns={ex.get('turns')} summary_len={ex.get('summary_len')}"))
        else:
            checks.append((False, "memory_restored 日志未找到"))
        sent = log_records(event="replay_sent", session_id=sid, since_epoch=marker)
        checks.append((bool(sent) and sent[0]["extra"].get("mode") == "bubbles",
                       f"replay_sent 日志 mode={sent[0]['extra'].get('mode') if sent else '?'}"))
    return checks


async def fresh_no_replay() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send(user_text("最近工作压力大，晚上睡不好。"))
        await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "新会话 first_frame")
        rp = replay_frame(c.frames)
        checks.append((rp is None, "新连接(无身份)无 replay 帧" if rp is None
                       else f"新连接出现 replay: mode={rp.get('mode')}"))
    return checks


async def collect_finish() -> str | None:
    """走满采集到 Finish(温层写摘要),返回 session_id。"""
    sid: str | None = None
    async with WsClient() as c:
        await c.send(user_text(R1))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "F3 first_frame")
        if got:
            sid = got[1].get("session_id")
        await c.wait_for(lambda m: m.get("type") == "draw", 60, "F3 粗稿")
        await c.wait_for(lambda m: m.get("type") == "text_delta", 60, "F3 首问")
        await asyncio.sleep(4.0)
        for i, text in enumerate(TAIL, start=2):
            t_r = await c.send(user_text(text))
            await c.wait_for(lambda m: m.get("type") == "draw", 60, f"F3 R{i} draw")
            first = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"F3 R{i} 文本")
            if first and first[0] - t_r >= 8.0:
                inv = await c.wait_for(
                    lambda m: m.get("type") == "text_delta" and INVITE_KEY in (m.get("text") or ""),
                    180, f"F3 R{i} 邀请语")
                if inv:
                    # 等 Finish 收口 done:过早断连会 cancel 温层摘要/station:input 归档
                    await c.wait_for(lambda m: m.get("type") == "done", 60, "F3 Finish done")
                    break
            await asyncio.sleep(4.0)
    return sid


async def reconnect_digest(sid: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    expired = expire_hot_key(sid)
    checks.append((expired, "热层 key TTL 已压到 1s(模拟隔天)" if expired
                   else "热层 key 不存在/Redis 不可用,digest 前提不成立"))
    if not expired:
        return checks
    await asyncio.sleep(2.5)
    marker = epoch()
    async with WsClient() as c:
        await c.send(user_text("又睡不着了", session_id=sid))
        got = await c.wait_for(lambda m: m.get("type") == "replay", 20, "digest replay")
        if got is None:
            checks.append((False, "digest 重连未收到 replay"))
            return checks
        rp = got[1]
        checks.append((rp.get("mode") == "digest", f"replay mode={rp.get('mode')}"))
        checks.append((not (rp.get("turns") or []), f"digest 无 turns({len(rp.get('turns') or [])})"))
        checks.append((bool(rp.get("summary")), "digest summary 非空"
                       if rp.get("summary") else f"digest summary 为空: {rp.get('summary')!r}"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "digest first_frame")
        checks.append((got is not None, "digest 后 collect first_frame" if got
                       else "digest 后 first_frame 未到达"))
        recs = log_records(event="memory_restored", session_id=sid, since_epoch=marker)
        if recs:
            ex = recs[0]["extra"]
            t_n = int(ex.get("turns") or 0)
            s_len = int(ex.get("summary_len") or 0)
            # F3 修复后语义:append_turn 冷启动从温层播种 history_summary,
            # 新轮次(turns≥1)与跨天摘要(summary_len>0)共存
            checks.append((t_n >= 1 and s_len > 0,
                           f"memory_restored turns={t_n} summary_len={s_len}(期望 turns≥1 且 summary>0)"))
        else:
            checks.append((False, "digest memory_restored 日志未找到"))
    return checks


def expire_hot_key(sid: str) -> bool:
    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True, socket_timeout=5)
        key = f"hrp:v1:hot:{sid}"
        if r.ttl(key) is None or r.ttl(key) < 0:
            return False
        return bool(r.expire(key, 1))
    except Exception:  # noqa: BLE001 — Redis 不可用直接报前提不成立
        return False


async def clear_memory_check(sid: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    status, body = post_json("/admin/clear_memory")
    checks.append((status == 200 and body.get("ok") is True,
                   f"clear_memory: {status} ok={body.get('ok')} "
                   f"redis_keys={body.get('redis_keys')}" if status == 200
                   else f"clear_memory 异常: {status} {body}"))
    async with WsClient() as c:
        await c.send(user_text("还在吗，我们接着聊。", session_id=sid))
        await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "清后 first_frame")
        rp = replay_frame(c.frames)
        checks.append((rp is None, "清记忆后重连旧会话无 replay" if rp is None
                       else f"清记忆后仍有 replay: mode={rp.get('mode')}"))
    return checks


async def clear_only() -> list[tuple[bool, str]]:
    """--clear 独立入口:起一个会话 → 清库 → 重连旧会话无回放(其余段不跑)。"""
    sid: str | None = None
    async with WsClient() as c:
        await c.send(user_text("在吗，想聊聊最近的状态。"))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 60, "起场 first_frame")
        if got:
            sid = got[1].get("session_id")
    if not sid:
        return [(False, "起场未取得 session_id")]
    return await clear_memory_check(sid)


async def main() -> None:
    if "--clear" in sys.argv:
        print("===== e2e3 用例 F·clear_memory 治理(独立入口) =====")
        clear_checks = await clear_only()
        ok = all(p for p, _ in clear_checks)
        for passed, detail in clear_checks:
            print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
        result("F4·clear_memory", ok, "见上" if ok else "存在失败项")
        return
    print("===== e2e3 用例 F·记忆与回放 =====")
    checks: list[tuple[bool, str]] = []
    print("-- F1 bubbles 重连回放 --", flush=True)
    sid, base_checks = await collect_two_rounds()
    checks += base_checks
    if sid:
        checks += await reconnect_bubbles(sid)
    print("-- F2 新连接不推回放 --", flush=True)
    checks += await fresh_no_replay()
    print("-- F3 digest(热层过期模拟隔天) --", flush=True)
    sid2 = await collect_finish()
    if sid2:
        checks += await reconnect_digest(sid2)
    else:
        checks.append((False, "F3 未能取得 session_id"))
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("F·记忆与回放", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
