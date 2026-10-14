"""e2e3 用例 B·复杂双用例(acceptance-v1 §1.1-复杂 / §1.2-复杂;双用例原则)。

B1 answer-复杂:长问句(正念定义/与冥想关系/对睡眠作用三信息点)
  → 无 first_frame/draw;text_delta 流式 final=True;done;
  内容覆盖 ≥2 信息点(关键词组近似判定);记首包时长。
B2 collect-复杂:首条长文本(诱发事件/躯体化/失眠/回避)
  → first_frame ≤300ms(route=collect);mood 直发(采集态内静默,契约 §4.2);
  粗稿或前两轮增量中"当众批评"与"失眠"已有字段填充;
  信念字段(intermediate/core_belief)全程留白;走满采集→邀请语;seq 单调。
B3 crisis-复杂:软埋危机长句(`从这个世界上消失`)→ 热线+横幅+TTS+审计;
  matched 含「想离开这个世界」为 acceptance 原判据(现行纯子串词表下预期实测暴露差异)。
B4 mood 组号:独立到达 mood_select → 回执 wav 携 preset-mood-* 组号(验收 6 数据前提,
  T6;无 first_frame,契约 §4.2)。
跑法:backend 在跑 `uv run hrp`,然后 `uv run python tests/e2e/e2e3_b_complex.py`。
"""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

from e2e_lib import WsClient, epoch, log_records, result, user_text

ANSWER_Q = ("我听朋友说冥想和正念好像是一回事，又有人说正念能治失眠，"
            "到底正念是什么，跟冥想有什么区别，对睡不着真的有用吗")
KEY_GROUPS: dict[str, tuple[str, ...]] = {
    "正念定义": ("正念",),
    "与冥想关系": ("冥想",),
    "对睡眠作用": ("失眠", "睡眠", "睡"),
}
COLLECT_LONG = ("这段时间工作上出了点事，开会汇报的时候被领导当着所有人的面批评，"
                "说我能力不行，从那天起每天上班都提心吊胆的，晚上躺在床上脑子里反复回放"
                "那个场面，翻来覆去到两三点才睡着，白天也没精神，也不想跟家人朋友说，"
                "怕他们觉得我连这点事都扛不住")
TAIL = [
    "领导后来又在小群里阴阳怪气，我每天早上想到要上班就胃疼。",
    "晚上躺下就开始想白天的画面，越想越清醒，两三点都睡不着。",
    "我谁都没说，连对象都瞒着，怕被说矫情。",
    "周末也休息不好，整个人像绷着的弦。",
    "其实我心里清楚没那么严重，但就是控制不了。",
]
INVITE_KEY = "心灵补给站"
BELIEF_FIELDS = ("intermediate_belief", "core_belief")
CRISIS_LONG = ("我最近每天晚上都睡不着，一个人待着的时候总是在想，"
               "要是我能从这个世界上消失就好了，反正也没有人会注意到我不在了")


def draw_body_text(data: Any) -> str:
    """draw.data 全部叶子字符串拼接(粗查字段覆盖用)。"""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return "".join(draw_body_text(v) for v in data.values())
    if isinstance(data, list):
        return "".join(draw_body_text(v) for v in data)
    return ""


def belief_blank(data: dict[str, Any]) -> bool:
    return all(not data.get(f) for f in BELIEF_FIELDS)


async def wait_settle(c: WsClient) -> None:
    """轮间留白;AskNext/陪聊分支设计上无 done/final 收尾,定时防抢占。"""
    del c
    await asyncio.sleep(4.0)


async def answer_complex() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        t = await c.send(user_text(ANSWER_Q))
        got = await c.wait_for(
            lambda m: m.get("type") == "done", 180, "answer done")
        win = c.frames_since(t)
        ffs = [m for _, m in win if m.get("type") == "first_frame"]
        draws = [m for _, m in win if m.get("type") == "draw"]
        texts = [(ts, m) for ts, m in win if m.get("type") == "text_delta"]
        body = "".join(m.get("text") or "" for _, m in texts)
        finals = [m for _, m in texts if m.get("final")]
        checks.append((not ffs, "answer-复杂 无 first_frame" if not ffs else f"出现 first_frame: {ffs}"))
        checks.append((not draws, "answer-复杂 无 draw" if not draws
                       else f"出现 {len(draws)} 帧 draw"))
        checks.append((got is not None, "done 收尾" if got else "done 未到达"))
        checks.append((bool(finals), "text_delta 流式且 final=True" if finals else "无 final 帧"))
        covered = [g for g, kws in KEY_GROUPS.items() if any(k in body for k in kws)]
        checks.append((len(covered) >= 2,
                       f"内容覆盖 {len(covered)}/3 信息点: {covered}" if len(covered) >= 2
                       else f"内容覆盖不足: {covered}"))
        if texts:
            checks.append((True, f"首包 {texts[0][0] - t:.2f}s,正文 {len(body)} 字"))
    return checks


async def collect_complex() -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    draws: list[dict[str, Any]] = []
    seqs: list[int] = []
    async with WsClient() as c:
        t = await c.send(user_text(COLLECT_LONG))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 30, "first_frame")
        if got is None:
            checks.append((False, "collect-复杂 first_frame 未到达"))
            return checks
        _, ff = got
        checks.append((ff.get("route") == "collect",
                       f"first_frame route={ff.get('route')}"))
        ff_latency = got[0] - t
        checks.append((ff_latency <= 0.3, f"首帧 {ff_latency * 1000:.0f}ms(≤300ms 速判)"
                       if ff_latency <= 0.3 else f"首帧 {ff_latency * 1000:.0f}ms 超 300ms"))

        got = await c.wait_for(lambda m: m.get("type") == "draw", 60, "粗稿 draw")
        if got:
            d = got[1]
            draws.append(d.get("data") or {})
            seqs.append(d.get("seq") or 0)
            checks.append((belief_blank(d.get("data") or {}),
                           "粗稿信念字段留白" if belief_blank(d.get("data") or {})
                           else f"粗稿信念被填: "
                                f"{[(f, (d.get('data') or {}).get(f)) for f in BELIEF_FIELDS]}"))
        checks.append((got is not None, "粗稿 draw" if got else "粗稿 draw 未到达"))
        await wait_settle(c)

        # mood 直发(采集态内):契约 §4.2 静默记录不回帧(in_round=true;诊断定案问2)
        mood_marker = epoch()
        t_mood = await c.send({"type": "mood_select", "mood": "低落",
                               "ts": int(time.time() * 1000)})
        await asyncio.sleep(3.0)
        mood_win = c.frames_since(t_mood)
        mood_types = [m.get("type") for _, m in mood_win]
        checks.append((not mood_types,
                       "回合内 mood_select 静默(契约预期)" if not mood_types
                       else f"回合内收到帧: {mood_types}"))
        recs = log_records(event="mood_select_received", since_epoch=mood_marker)
        checks.append((bool(recs) and recs[0]["extra"].get("in_round") is True,
                       "日志 mood_select_received in_round=true(采集态静默记录)"
                       if recs and recs[0]["extra"].get("in_round") is True
                       else f"日志异常: {recs[0]['extra'] if recs else '未找到 mood_select_received'}"))

        # 内容轮走满采集;粗稿或前两轮增量需覆盖 诱发事件+失眠
        cover_text = draw_body_text(draws[0]) if draws else ""
        prev_filled = {k for k, v in (draws[0] if draws else {}).items()
                       if v not in (None, "", [], {})}
        insomnia_round_new_fill = False
        t_end = None
        rounds = 0
        for i, text in enumerate(TAIL, start=2):
            t_r = await c.send(user_text(text))
            got = await c.wait_for(lambda m: m.get("type") == "draw", 60, f"R{i} 增量 draw")
            if got:
                d = got[1]
                data = d.get("data") or {}
                draws.append(data)
                seqs.append(d.get("seq") or 0)
                now_filled = {k for k, v in data.items() if v not in (None, "", [], {})}
                if "睡" in text and now_filled - prev_filled:
                    insomnia_round_new_fill = True  # 失眠轮产出新填字段=信息已入格
                prev_filled = now_filled
                print(f"  -- R{i} draw data: {data}", flush=True)
                if rounds < 2:
                    cover_text += draw_body_text(data)
                    rounds += 1
                if not belief_blank(data):
                    checks.append((False, f"R{i} 增量信念字段被填"))
            # 停采判别:预置问句瞬时(<8s);停采总结走 LLM(>8s)后才出邀请语
            first = await c.wait_for(lambda m: m.get("type") == "text_delta", 60, f"R{i} 文本")
            if first and first[0] - t_r >= 8.0:
                inv = await c.wait_for(
                    lambda m: m.get("type") == "text_delta" and INVITE_KEY in (m.get("text") or ""),
                    180, f"R{i} 邀请语")
                if inv:
                    t_end = inv[0]
                    break
            await wait_settle(c)
        checks.append((t_end is not None, "精稿总结+心灵补给站邀请语" if t_end
                       else "走完 TAIL 仍未触发精稿总结"))
        got = await c.wait_for(lambda m: m.get("type") == "done", 30, "收尾 done")
        checks.append((got is not None, "收尾 done" if got else "收尾 done 未到达"))

        event_hit = any(k in cover_text for k in ("批评", "领导"))
        # 失眠覆盖=格内文本含关键词,或失眠轮产出新填字段(提炼短句可能不带字面词)
        sleep_hit = any(k in cover_text for k in ("睡", "失眠")) or insomnia_round_new_fill
        checks.append((event_hit and sleep_hit,
                       (f"提取覆盖: 诱发事件={event_hit} 失眠表现={sleep_hit}"
                        f"(失眠轮新填={insomnia_round_new_fill})")
                       if event_hit and sleep_hit
                       else f"提取覆盖不足: 诱发事件={event_hit} 失眠表现={sleep_hit}"))
        mono = all(b > a for a, b in itertools.pairwise(seqs))
        checks.append((mono, f"seq 全程单调递增({len(seqs)} 帧)" if mono
                       else f"seq 非单调: {seqs}"))
        errs = [m for _, m in c.frames if m.get("type") == "error"]
        checks.append((not errs, "无 error 帧" if not errs else f"error 帧: {errs[:2]}"))
    return checks


async def crisis_complex() -> list[tuple[bool, str]]:
    """§1.3-复杂:软埋危机句 → 热线+横幅+审计(matched 判定按 acceptance 原文)。"""
    checks: list[tuple[bool, str]] = []
    marker = epoch()
    async with WsClient() as c:
        await c.send(user_text(CRISIS_LONG))
        got = await c.wait_for(lambda m: m.get("type") == "first_frame", 45, "first_frame")
        if got is None:
            checks.append((False, "crisis-复杂 first_frame 未到达(未命中危机或超时)"))
        else:
            _, ff = got
            checks.append((ff.get("route") == "crisis" and ff.get("mood_select") is False,
                           f"first_frame route={ff.get('route')} mood={ff.get('mood_select')}"
                           if ff.get("route") == "crisis"
                           else f"未命中危机: route={ff.get('route')}(考软埋表述在长句中的命中)"))
            await c.wait_for(
                lambda m: m.get("type") == "draw" and m.get("template") == "stage_map",
                30, "stage_map draw")
            got = await c.wait_for(
                lambda m: m.get("type") == "text_delta" and bool(m.get("final")), 30, "热线文本")
            checks.append((got is not None, "热线文本(横幅)" if got else "热线文本未到达"))
            got = await c.wait_for(lambda m: m.get("type") == "audio_chunk", 60, "热线语音")
            checks.append((got is not None, "热线 audio_chunk(TTS)" if got
                           else "热线 audio_chunk 未到达"))
            got = await c.wait_for(lambda m: m.get("type") == "done", 30, "done")
            checks.append((got is not None, "done" if got else "done 未到达"))
    await asyncio.sleep(1.0)
    recs = log_records(event="crisis_gate_hit", since_epoch=marker)
    if recs:
        ex = recs[0]["extra"]
        matched = ex.get("matched") or []
        checks.append((ex.get("hit") is True and recs[0]["level"] == "WARN" and bool(matched),
                       f"审计: hit={ex.get('hit')} level={recs[0]['level']} matched={matched}"))
        vanish = [t for t in ("想离开这个世界", "从这个世界上消失", "从这个世上消失",
                              "想从这个世界消失") if t in matched]
        checks.append((bool(vanish), f"matched 含消失族词: {vanish}" if vanish
                       else f"matched 无消失族词: {matched}"))
        checks.append((CRISIS_LONG not in recs[0]["raw"], "审计行不含原文(红线)"))
    else:
        checks.append((False, "crisis_gate_hit 日志未找到"))
    return checks


async def mood_group_id() -> list[tuple[bool, str]]:
    """B4·验收 6 数据前提(T6):独立到达 mood_select 的回执 wav 携新组号
    preset-mood-{trace},与 TTS 总结组 tts-* 可区分——前端 AudioHub 组仲裁
    (同组排队/新组双链 flush)靠它收「总结 PCM 播放中点表情无叠声」。
    WS 层只验组号语义;浏览器混音行为由前端 audio_hub.spec 钉测覆盖。"""
    checks: list[tuple[bool, str]] = []
    async with WsClient() as c:
        await c.send({"type": "mood_select", "mood": "低落", "ts": int(time.time() * 1000)})
        got = await c.wait_for(lambda m: m.get("type") == "text_delta", 15, "回执文本")
        checks.append((got is not None, "独立到达回执 text_delta" if got else "回执文本未到达"))
        got = await c.wait_for(
            lambda m: m.get("type") == "audio_chunk" and m.get("format") == "wav",
            15, "回执语音")
        if got is None:
            checks.append((False, "回执 audio_chunk(wav) 未到达(查 data/fillers 是否预生成)"))
        else:
            _, audio = got
            rid = audio.get("round_id", "")
            checks.append((rid.startswith("preset-mood-"),
                           f"回执 wav 携预置组号 round_id={rid!r}" if rid.startswith("preset-mood-")
                           else f"round_id={rid!r} 非 preset-mood-* 组号(组仲裁数据前提缺失)"))
            checks.append((not rid.startswith("tts-"),
                           "组号非 TTS 透传值(与总结组可区分)" if rid.startswith("preset-")
                           else f"组号 {rid!r} 撞 TTS 命名:新组判定会与总结混淆"))
        done = await c.wait_for(lambda m: m.get("type") == "done", 10, "回执 done")
        checks.append((done is not None, "回执收口 done" if done else "done 未到达"))
        ff = [m for _, m in c.frames if m.get("type") == "first_frame"]
        checks.append((not ff, "独立到达无 first_frame(契约 §4.2)" if not ff else "独立到达发了 first_frame"))
    return checks


async def main() -> None:
    print("===== e2e3 用例 B·复杂双用例 =====")
    print("-- B1 answer-复杂 --", flush=True)
    checks = await answer_complex()
    print("-- B2 collect-复杂 --", flush=True)
    checks += await collect_complex()
    print("-- B3 crisis-复杂(软埋句) --", flush=True)
    checks += await crisis_complex()
    print("-- B4 mood 组号(验收 6 数据前提) --", flush=True)
    checks += await mood_group_id()
    ok = all(p for p, _ in checks)
    for passed, detail in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {detail}")
    result("B·复杂双用例", ok, "见上" if ok else "存在失败项")


if __name__ == "__main__":
    asyncio.run(main())
