"""整段 wav 拼接(fillers 离线生成路径)。

synthesize_stream 逐句产出的是**完整 wav 文件**（各带 RIFF 头）；直接 b"".join
会得到损坏文件——播放器只认第一个 RIFF 头，按其 nframes 声明截断，第 2 句起的
头字节沦为噪音、后续句子全部丢失。本模块把每句 wav 解析出 PCM 后拼合，重写
单一 RIFF 头（参数取首句；句间参数不一致视为服务端异常，抛 TTSError 拒拼）。
"""

from __future__ import annotations

import io
import wave

from app.voice.tts_errors import TTSError


def join_sentence_wavs(wavs: list[bytes]) -> bytes:
    """逐句完整 wav → 拼合单 RIFF 头的整段 wav（空列表返回空 bytes）。

    参数（声道/采样宽/帧率）取首句；后续句不一致即抛（10 倍时长差的根因
    是裸拼接，宁可 fail loud 也不落第二个损坏产物）。
    """
    if not wavs:
        return b""
    frames: list[bytes] = []
    params: tuple[int, int, int] | None = None  # (channels, sampwidth, framerate)
    for wav in wavs:
        try:
            with wave.open(io.BytesIO(wav), "rb") as r:
                cur = (r.getnchannels(), r.getsampwidth(), r.getframerate())
                if params is None:
                    params = cur
                elif cur != params:
                    raise TTSError(
                        f"wav 参数不一致: {params} vs {cur},拒绝拼接(裸拼会产生损坏文件)"
                    )
                frames.append(r.readframes(r.getnframes()))
        except (wave.Error, EOFError) as exc:
            # EOFError:chunk 层对过短/截断文件的穿透(非 RIFF 数据常走这条)
            raise TTSError(f"句 wav 解析失败: {exc}") from exc
    assert params is not None
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(params[1])
        w.setframerate(params[2])
        w.writeframes(b"".join(frames))
    return out.getvalue()
