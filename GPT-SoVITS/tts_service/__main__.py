"""入口:python -m tts_service

    python -m tts_service                  # 127.0.0.1:9001
    python -m tts_service --port 9880      # 换端口
    python -m tts_service --host 0.0.0.0   # 对外
    python -m tts_service --check          # 只跑输入守卫自检,不加载模型、不占显存
"""

from __future__ import annotations

import argparse
import logging
import sys

from .settings import get_settings


def _self_check() -> int:
    """输入守卫自检:不碰模型,秒级完成。

    存在的意义是把"哪些文本会进模型"这条边界固定下来可回归 ——
    g2p_en 缺 nltk cmudict 是个环境相关的坑,只有守卫挡着。
    """
    from .engine import GuardError, TTSEngine

    engine = TTSEngine(get_settings())
    cases: list[tuple[str, str, bool]] = [
        ("正常中文", "我们先不急着解决什么，就从今晚开始，选一件最小的事做一做。", True),
        ("短句", "我在的。", True),
        ("空文本", "", False),
        ("纯空格", "   \n ", False),
        ("单个英文字母", "A", False),
        ("中英混排", "我在的 OK", False),
        ("阿拉伯数字", "我在 3 点", True),
        ("中文标点", "嗯……我想想。", True),
    ]
    print("=" * 60)
    print("输入守卫自检")
    print("=" * 60)
    failures = 0
    for name, text, should_pass in cases:
        try:
            sentences = engine.guard(text)
            ok, detail = True, f"{len(sentences)} 句"
        except GuardError as exc:
            ok, detail = False, f"{exc.code}: {exc}"
        mark = "PASS" if ok == should_pass else "FAIL"
        if ok != should_pass:
            failures += 1
        print(f"  [{mark}] {name:<12} 期望{'放行' if should_pass else '拒绝'}"
              f"  实际{'放行' if ok else '拒绝'}  {detail}")
    print("=" * 60)
    print("全部通过" if failures == 0 else f"{failures} 项不符预期")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tts_service",
        description="GPT-SoVITS 远程 TTS 服务",
    )
    parser.add_argument("-a", "--host", default=None, help="绑定地址,默认 127.0.0.1")
    parser.add_argument("-p", "--port", type=int, default=None, help="端口,默认 9001")
    parser.add_argument("-c", "--config", default=None, help="tts_infer.yaml 路径")
    parser.add_argument("--voice", default=None, help="音色名,对应 reference/<name>.wav")
    parser.add_argument(
        "--check", action="store_true", help="只跑输入守卫自检后退出"
    )
    args = parser.parse_args()

    if args.check:
        return _self_check()

    if args.host:
        import os

        os.environ["TTS_SERVICE_HOST"] = args.host
    if args.port:
        import os

        os.environ["TTS_SERVICE_PORT"] = str(args.port)
    if args.config:
        import os

        os.environ["GPT_SOVITS_CONFIG"] = args.config
    if args.voice:
        import os

        os.environ["GPT_SOVITS_VOICE"] = args.voice

    cfg = get_settings()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    import uvicorn

    # workers 必须为 1:多进程会各加载一份模型,单卡 8GB 装不下两份
    # (实测单实例独占约 3.8~4.4 GiB 显存),而且会破坏引擎内的串行保证。
    logger = logging.getLogger("tts_service")
    logger.info(
        "starting · %s on %s:%s  voice=%s model=%s",
        SERVICE_LABEL, cfg.host, cfg.port, cfg.voice or "(未指定)", cfg.version,
    )
    uvicorn.run(
        "tts_service.server:app",
        host=cfg.host,
        port=cfg.port,
        workers=1,
        log_level="info",
    )
    return 0


SERVICE_LABEL = "hrp-tts-gpt-sovits"

if __name__ == "__main__":
    sys.exit(main())
