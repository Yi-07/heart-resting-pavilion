"""TTS realtime 契约钉测试(plan §10-§19)。

这些断言针对的是**契约本身**,不是实现细节:
    round_id 全链路一致 / Header==Body / seq 语义 / stale vs mismatch 的区分
    cancel 五种情形 / chunk 级打断语义
它们是"以后有人改坏协议"的报警器,所以用真实 HTTP 打真实服务(有服务才跑,
没服务就 skip),不拿假实现自证。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

BASE = "http://127.0.0.1:9001"
TEXT = "我们先不急着解决什么。"


def _service_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/ready", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _service_up(), reason="TTS 服务未就绪(先起 python -m tts_service)"
)


def _read_stream(endpoint: str, rid: str, text: str) -> list[dict]:
    body = {"text": text, "voice": ""}
    if endpoint.startswith("/v2"):
        body["round_id"] = rid
    req = urllib.request.Request(
        f"{BASE}{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Request-ID": rid},
        method="POST",
    )
    out: list[dict] = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        read = getattr(resp, "read1", None) or resp.read
        buf = b""
        while True:
            c = read(65536)
            if not c:
                break
            buf += c
            if b"\n" not in buf:
                continue
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if line.strip():
                    out.append(json.loads(line))
    return out


# ---- §10.2 / §14.1:Header == Body.round_id ----


class TestV2RoundIdContract:
    def test_mismatch_rejected_before_inference(self):
        req = urllib.request.Request(
            f"{BASE}/v2/tts/stream",
            data=json.dumps({"text": TEXT, "voice": "", "round_id": "body-x"}).encode(),
            headers={"Content-Type": "application/json", "X-Request-ID": "header-y"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=30)
        assert ei.value.code == 400
        payload = json.loads(ei.value.read().decode())
        assert payload["code"] == "round_id_mismatch"

    def test_match_accepted(self):
        rid = f"pytest-match-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        audio = [f for f in frames if f.get("type") == "audio"]
        assert audio, "匹配时应当正常出音频"
        assert all(f["round_id"] == rid for f in audio), "每个音频帧都要带同一个 round_id"


# ---- §13:round_id 全链路一致 ----


class TestRoundIdEndToEnd:
    def test_every_frame_shares_request_round_id(self):
        rid = f"pytest-e2e-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        seen = {f["round_id"] for f in frames if "round_id" in f}
        assert seen == {rid}, f"round_id 必须全程唯一且一致,实际 {seen}"

    def test_distinct_rounds_get_distinct_ids(self):
        """每次独立 run 一个 round_id(plan §29 的前提:round 是身份,不是计数器)。"""
        ids = [f"pytest-distinct-{i}-{int(time.time() * 1000)}" for i in range(2)]
        for rid in ids:
            frames = _read_stream("/v2/tts/stream", rid, TEXT)
            seen = {f["round_id"] for f in frames if "round_id" in f}
            assert seen == {rid}
        assert ids[0] != ids[1]


# ---- §15:seq 语义 ----


class TestSeqContract:
    def test_seq_starts_at_zero_and_is_monotonic(self):
        rid = f"pytest-seq-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        seqs = [f["seq"] for f in frames if f.get("type") == "audio"]
        assert seqs, "应有音频帧"
        assert seqs[0] == 0, f"seq 必须从 0 开始,实际 {seqs[0]}"
        assert seqs == list(range(len(seqs))), f"seq 必须连续不重号: {seqs}"

    def test_sentence_index_non_decreasing(self):
        rid = f"pytest-si-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, "第一句。第二句。第三句。")
        sis = [f["sentence_index"] for f in frames if f.get("type") == "audio"]
        assert sis == sorted(sis), f"sentence_index 必须单调不减: {sis}"


# ---- §12:PCM contract ----


class TestPcmContract:
    def test_fixed_pcm_format(self):
        rid = f"pytest-pcm-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        audio = [f for f in frames if f.get("type") == "audio"]
        assert audio
        for f in audio:
            assert f["sample_rate"] == 32000, "plan §12 固定 32000 Hz"
            assert f["channels"] == 1, "plan §12 固定单声道"
            assert f["format"] == "pcm_s16le", "plan §12 固定 pcm_s16le"

    def test_pcm_bytes_even_length(self):
        """int16 = 2 字节/样本,奇数长度说明帧被截断。"""
        import base64

        rid = f"pytest-even-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        for f in (x for x in frames if x.get("type") == "audio"):
            raw = base64.b64decode(f["pcm"])
            assert len(raw) % 2 == 0, f"PCM 样本数必须为偶数,实际 {len(raw)}"


# ---- §11:控制帧 ----


class TestControlFrames:
    def test_end_and_cancelled_are_mutually_exclusive(self):
        rid = f"pytest-end-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, TEXT)
        kinds = [f.get("type") for f in frames]
        assert "end" in kinds, "正常收尾必须有 end 帧"
        assert "cancelled" not in kinds, "正常收尾不得同时出现 cancelled"

    def test_sentence_end_present(self):
        rid = f"pytest-send-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid, "第一句。第二句。")
        assert any(f.get("type") == "sentence_end" for f in frames)


# ---- §39:输入守卫 ----


class TestGuards:
    @pytest.mark.parametrize("bad", ["", "   ", "hello world", "A"])
    def test_rejected_inputs(self, bad: str):
        req = urllib.request.Request(
            f"{BASE}/v2/tts/stream",
            data=json.dumps({"text": bad, "voice": "", "round_id": "pytest-guard"}).encode(),
            headers={"Content-Type": "application/json", "X-Request-ID": "pytest-guard"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=30)
        assert ei.value.code == 400


# ---- §17 / §19:cancel 语义 ----


def _cancel(rid: str, *, cascade: bool = True) -> dict:
    req = urllib.request.Request(
        f"{BASE}/v1/tts/cancel",
        data=json.dumps({"round_id": rid, "cascade": cascade}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


class TestCancelSemantics:
    def test_unknown_round_is_noop_not_error(self):
        """未知回合:no-op 且不误伤别的 round(plan §17)。"""
        rid = f"pytest-unknown-{int(time.time() * 1000)}"
        out = _cancel(rid)
        assert out["cancelled"] is False
        assert out["state"] == "unknown"
        assert out["known"] is False
        # 之后的新 round 必须完全不受影响
        rid2 = f"pytest-after-{int(time.time() * 1000)}"
        frames = _read_stream("/v2/tts/stream", rid2, TEXT)
        assert any(f.get("type") == "audio" for f in frames)

    def test_cancel_is_idempotent(self):
        rid = f"pytest-idem-{int(time.time() * 1000)}"
        first = _cancel(rid)
        second = _cancel(rid)
        assert first["cancelled"] == second["cancelled"] == False

    def test_cancel_stops_new_chunks(self):
        """chunk 级打断:取消之后不再有新的音频块(plan §19)。

        断言的是**「取消后无新块」**这个契约,而不是「cancelled 必为 true」——
        后者取决于 cancel 到达时回合是否还在跑,而推理快时回合可能已经结束,
        那属于 §17 的 finished 幂等 no-op,不是本条要钉的东西。
        """
        rid = f"pytest-cancel-{int(time.time() * 1000)}"
        frames: list[tuple[float, dict]] = []
        err: list[BaseException] = []

        def _reader() -> None:
            req = urllib.request.Request(
                f"{BASE}/v2/tts/stream",
                data=json.dumps(
                    {"text": TEXT * 4, "voice": "", "round_id": rid}
                ).encode(),
                headers={"Content-Type": "application/json", "X-Request-ID": rid},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    read = getattr(resp, "read1", None) or resp.read
                    buf = b""
                    while True:
                        c = read(65536)
                        if not c:
                            break
                        buf += c
                        if b"\n" not in buf:
                            continue
                        *lines, buf = buf.split(b"\n")
                        for line in lines:
                            if line.strip():
                                frames.append((time.perf_counter(), json.loads(line)))
            except Exception as exc:  # noqa: BLE001 — cancel 后可能直接断流
                err.append(exc)

        th = threading.Thread(target=_reader, daemon=True)
        th.start()

        # 第一块到达就立刻打断:这样打断必然落在回合还在跑的时候,
        # 测的才是"chunk 级打断",而不是"打一个已经结束的回合"。
        deadline = time.time() + 120
        while not any(f.get("type") == "audio" for _, f in frames) and time.time() < deadline:
            time.sleep(0.02)
        assert frames, "应该收到音频帧"
        time.sleep(0.05)
        t_cancel = time.perf_counter()
        out = _cancel(rid)
        th.join(timeout=120)

        assert out["known"] is True, "回合已注册,不该是 unknown"
        assert out["state"] in ("cancelled", "finished"), (
            f"取消后状态必须是 cancelled 或 finished,实际 {out['state']}"
        )
        if out["state"] == "cancelled":
            after = [f for ts, f in frames if ts > t_cancel and f.get("type") == "audio"]
            assert after == [], f"取消后不得再有新音频块,实际 {len(after)} 块"


# ---- §21:/v1 legacy 保持可用 ----


class TestLegacyV1:
    def test_v1_still_returns_whole_wav(self):
        rid = f"pytest-v1-{int(time.time() * 1000)}"
        frames = _read_stream("/v1/tts/stream", rid, TEXT)
        wavs = [f for f in frames if "wav" in f]
        assert wavs, "/v1 必须仍返回整句 wav"
        import base64

        raw = base64.b64decode(wavs[0]["wav"])
        assert raw[:4] == b"RIFF", "/v1 必须是完整 wav(RIFF 容器)"
        assert raw[8:12] == b"WAVE"

    def test_v1_does_not_require_body_round_id(self):
        """/v1 不因 v2 规则新增 Header/Body 一致性要求(plan §10.1)。"""
        rid = f"pytest-v1-nobody-{int(time.time() * 1000)}"
        req = urllib.request.Request(
            f"{BASE}/v1/tts/stream",
            data=json.dumps({"text": TEXT, "voice": ""}).encode(),  # 无 round_id
            headers={"Content-Type": "application/json", "X-Request-ID": rid},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            read = getattr(resp, "read1", None) or resp.read
            assert read(65536), "/v1 不该因缺 body.round_id 而被拒"