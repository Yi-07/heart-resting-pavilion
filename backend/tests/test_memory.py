"""memory 接缝钉测试:温层→snapshot 回读 / 同日同源 upsert 最新胜 / station:input /
热层 mood_recent 滚动 / Redis 不可达降级不抛。

前置=本机 Redis 可用(handoff §2);测试用 db 15 + hrp:v1: 前缀,夹具收尾清键。
冷层 SQLite 用 tmp_path,不触真 data/profile.db。
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import redis as sync_redis

from app import config
from app.memory.store import Memory

_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture()
def mem(tmp_path: pytest.TempPathFactory) -> Memory:
    m = Memory(url=_TEST_URL, db_path=str(tmp_path / "t.db"))
    yield m
    r = sync_redis.from_url(_TEST_URL, decode_responses=True)
    keys = list(r.scan_iter("hrp:v1:*"))
    if keys:
        r.delete(*keys)
    r.close()


async def test_warm_summary_and_snapshot_roundtrip(mem: Memory):
    sid = "sess_m1"
    await mem.save_round_summary(sid, "第一回:加班焦虑睡不着")
    ctx = await mem.snapshot(sid)
    assert ctx.history_summary == "第一回:加班焦虑睡不着"
    assert ctx.mood_recent == []

    await mem.save_round_summary(sid, "第二回:考试心慌")
    ctx = await mem.snapshot(sid)
    assert ctx.history_summary == "第二回:考试心慌"  # 热层最新胜

    # 热亡回退温层:snapshot 语义(删热键后仍能从温层最新一条恢复)
    r = sync_redis.from_url(_TEST_URL, decode_responses=True)
    r.delete(f"hrp:v1:hot:{sid}")
    r.close()
    ctx = await mem.snapshot(sid)
    assert ctx.history_summary == "第二回:考试心慌"


async def test_record_mood_upsert_same_day_same_source(mem: Memory):
    await mem.record_mood("难过", source="mood_select")
    await mem.record_mood("平静", source="mood_select")  # 同日同源:最新胜
    await mem.record_mood("焦虑", source="研判", intensity=0.8)
    rows = mem.recent_moods()
    labels = sorted(r["mood_label"] for r in rows)
    assert labels == ["平静", "焦虑"]  # 难过被 upsert 覆盖;跨源各留一行
    by_source = {r["source"]: r for r in rows}
    assert by_source["研判"]["intensity"] == 0.8
    assert by_source["mood_select"]["intensity"] is None


async def test_mood_recent_rolls_in_hot_layer(mem: Memory):
    sid = "sess_m2"
    for mood in ["难过", "低落", "平静", "还好", "开心", "很好", "难过"]:
        await mem.record_mood(mood, source="mood_select", session_id=sid)
    ctx = await mem.snapshot(sid)
    assert ctx.mood_recent == ["平静", "还好", "开心", "很好", "难过"]  # cap=5 滚动


async def test_station_input_write_and_load(mem: Memory):
    sid = "sess_m3"
    formulation = json.dumps({"situation": "加班", "emotion": {"label": "焦虑"}}, ensure_ascii=False)
    ok = await mem.save_station_input(sid, "1", formulation, "总结文本")
    assert ok is True
    state, loaded = await mem.load_station_input(sid, "1")
    assert state == "ok" and loaded is not None
    assert loaded.payload["summary"] == "总结文本"
    assert json.loads(loaded.payload["formulation"])["emotion"]["label"] == "焦虑"
    # deadline 由素材自身证据得出:payload collected_at + RETENTION,与 Redis TTL 同锚点
    expected = loaded.collected_at + timedelta(seconds=config.STATION_RETENTION_S)
    assert abs((loaded.deadline - expected).total_seconds()) <= 1

    r = sync_redis.from_url(_TEST_URL, decode_responses=True)
    ttl = r.ttl(f"hrp:v1:station:input:{sid}:1")
    r.close()
    assert 0 < ttl <= 7 * 24 * 3600  # TTL 已设(spec §4 L7 温层 7 天)


async def test_station_input_round_scoped(mem: Memory):
    """同 session 两轮各一份素材,互不覆盖。"""

    sid = "sess_m3b"
    await mem.save_station_input(sid, "1", '{"situation":"第一轮"}', "总结一")
    await mem.save_station_input(sid, "2", '{"situation":"第二轮"}', "总结二")
    _, one = await mem.load_station_input(sid, "1")
    _, two = await mem.load_station_input(sid, "2")
    assert one is not None and two is not None
    assert json.loads(one.payload["formulation"])["situation"] == "第一轮"
    assert json.loads(two.payload["formulation"])["situation"] == "第二轮"


async def test_station_material_absent_and_probe(mem: Memory):
    sid = "sess_m3c"
    assert await mem.load_station_input(sid, "1") == ("absent", None)
    assert await mem.probe_station_input(sid, "1") == "absent"
    await mem.save_station_input(sid, "1", "{}", "s")
    assert await mem.probe_station_input(sid, "1") == "ok"


async def test_clear_all_wipes_redis_and_cold(mem: Memory):
    sid = "sess_m4"
    await mem.save_round_summary(sid, "摘要")
    await mem.save_station_input(sid, "1", "{}", "总结")
    await mem.record_mood("低落", source="mood_select")
    cleared = await mem.clear_all()
    assert cleared["redis_keys"] >= 2  # warm + station(治理不降级,如实计数)
    assert cleared["mood_rows"] >= 1
    assert await mem.load_station_input(sid, "1") == ("absent", None)
    ctx = await mem.snapshot(sid)
    assert ctx.history_summary is None
    assert mem.recent_moods() == []


async def test_degrade_when_redis_down(tmp_path: pytest.TempPathFactory):
    mem = Memory(url="redis://localhost:9/15", db_path=str(tmp_path / "t.db"))
    # 全部操作不抛;冷层照写(SQLite 本地),热/温降级吞掉
    await mem.record_mood("低落", source="mood_select", session_id="s")
    await mem.save_round_summary("s", "摘要")
    ctx = await mem.snapshot("s")
    assert ctx.history_summary is None
    assert await mem.save_station_input("s", "1", "{}", "x") is False  # 写失败回 false
    assert await mem.load_station_input("s", "1") == ("unknown", None)  # 不可确认
    assert await mem.probe_station_input("s", "1") == "unknown"
    assert [r["mood_label"] for r in mem.recent_moods()] == ["低落"]


async def test_recent_turns_roundtrip_and_cap(mem: Memory):
    """ADR-001/005:热层轮次原话 roundtrip + 20 条上限滚动;30min TTL 随热层键。"""
    sid = "sess_rt"
    for i in range(25):
        await mem.append_turn(sid, "user", f"用户话{i}")
        await mem.append_turn(sid, "assistant", f"小栖话{i}")
    ctx = await mem.snapshot(sid)
    assert len(ctx.recent_turns) == 20  # cap 滚动,旧轮被挤掉(50 写 20 留,首条=i15)
    assert ctx.recent_turns[0].text == "用户话15"
    assert ctx.recent_turns[-1].text == "小栖话24"
    assert ctx.recent_turns[0].role == "user"

    # 坏数据不炸(手改热层 JSON 防御)
    r = sync_redis.from_url(_TEST_URL, decode_responses=True)
    raw = r.get(f"hrp:v1:hot:{sid}")
    assert raw is not None
    data = json.loads(raw)
    data["recent_turns"] = [{"role": "bogus", "text": "x"}, "not-a-dict"]
    r.set(f"hrp:v1:hot:{sid}", json.dumps(data, ensure_ascii=False))
    r.close()
    ctx = await mem.snapshot(sid)
    assert ctx.recent_turns == []  # role 非法条目被滤掉


async def test_append_turn_creates_hot_key_with_ttl(mem: Memory):
    """append_turn 在无热层键时自建(30min TTL);与 summary/mood 同键共存。"""
    sid = "sess_rt2"
    await mem.save_round_summary(sid, "旧摘要")
    await mem.append_turn(sid, "user", "新一句话")
    ctx = await mem.snapshot(sid)
    assert ctx.history_summary == "旧摘要"  # 共存不互踩
    assert len(ctx.recent_turns) == 1
    assert ctx.recent_turns[0].text == "新一句话"
    r = sync_redis.from_url(_TEST_URL, decode_responses=True)
    ttl = r.ttl(f"hrp:v1:hot:{sid}")
    r.close()
    assert 0 < ttl <= 30 * 60
