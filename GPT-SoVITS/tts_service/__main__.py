"""入口:python -m tts_service

    python -m tts_service                  # 127.0.0.1:9001
    python -m tts_service --port 9880      # 换端口
    python -m tts_service --host 0.0.0.0   # 对外
    python -m tts_service --check          # 只跑输入守卫自检,不加载模型、不占显存
"""

from __future__ import annotations

import argparse
import os
import sys

from .settings import FIELDS, ROOT, build_settings


def _print_config(cfg) -> int:
    """打印最终配置 + 每一项来自哪一级(cli/env/yaml/default)。

    配置问题最费时间的从来不是"值不对",而是"我改了为什么没生效"。
    这张表一眼就能看出该项是被更高优先级盖住了,还是根本没读到。
    """
    print("=" * 72)
    print("最终配置(值 / 来源)")
    print("=" * 72)
    print(f"{'字段':<24}{'来源':<9}{'值'}")
    print("-" * 72)
    for f in FIELDS:
        src = cfg.config_sources.get(f.name, "?")
        val = getattr(cfg, f.name)
        if isinstance(val, str) and len(val) > 34:
            val = val[:31] + "..."
        print(f"{f.name:<24}{src:<9}{val}")
    print("-" * 72)
    print(f"auth_token: {'(已设置)' if cfg.auth_token else '(空,不校验)'}")
    print(f"voices: {len(cfg.voices)} 个(只读映射)")
    print("=" * 72)
    return 0


def _prepare_process_env() -> None:
    """进程入口设置 cwd 与 sys.path(plan §7)。

    **必须在进程入口做,不能在 engine.load() 里做。**
    cwd 是进程级状态:engine.load() 跑在后台线程,在那里 os.chdir() 会让
    「哪个线程碰文件系统」变成不确定行为,而且这段代码是复制的上游惯例。

    cwd = GPT-SoVITS 根是硬需求,不是风格问题:
        - tts_infer.yaml 里的权重路径全��相对路径("GPT_SoVITS/pretrained_models/...");
        - 参考音频是 "reference/<voice>.wav";
        - TTS_Config 构造时还会 os.makedirs("GPT_SoVITS/configs/")。
    三者都相对 cwd,进程从别处启动就会静默走到错误路径或直接崩。

    显式校验并快速失败:cwd 不对时给出可操作的提示,而不是让模型加载到一半
    才报一个看不懂的 FileNotFoundError。
    """
    os.chdir(ROOT)
    for p in (str(ROOT), str(ROOT / "GPT_SoVITS")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _self_check() -> int:
    """输入守卫自检:不碰模型,秒级完成。

    存在的意义是把"哪些文本会进模型"这条边界固定下来可回归 ——
    g2p_en 缺 nltk cmudict 是个环境相关的坑,只有守卫挡着。
    """
    from .engine import GuardError, TTSEngine

    engine = TTSEngine(build_settings())
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
        "--service-config",
        default=None,
        help="本服务 YAML 配置路径(默认 tts_service/config.yaml)",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="打印最终配置与每一项的来源(cli/env/yaml/default)后退出,不加载模型",
    )
    parser.add_argument(
        "--check", action="store_true", help="只跑输入守卫自检后退出"
    )
    args = parser.parse_args()

    if args.check:
        return _self_check()

    # CLI 是最高优先级,但**不写回 os.environ**:写回去就分不清"是 CLI 给的"还是
    # "ENV 本来就有",config_sources 的来源表会失去意义(见 settings.py)。
    cli: dict[str, object] = {}
    if args.host:
        cli["host"] = args.host
    if args.port:
        cli["port"] = args.port
    if args.config:
        cli["tts_config"] = args.config
    if args.voice:
        cli["voice"] = args.voice
    if args.service_config:
        os.environ["GPT_SOVITS_SERVICE_CONFIG"] = args.service_config

    from .logger import logger

    cfg = build_settings(cli)

    if args.print_config:
        _print_config(cfg)
        return 0

    # 日志不在这里初始化:server 模块是唯一初始化点(见 server.py 顶部注释)。
    # uvicorn.run 会导入 tts_service.server,届时一次性装配,两条启动路径共用。
    # 顺序上必须先 chdir —— engine.load 的权重路径是相对 cwd 的。
    _prepare_process_env()

    import uvicorn

    # workers 必须为 1:多进程会各加载一份模型,单卡 8GB 装不下两份
    # (实测单实例独占约 3.8~4.4 GiB 显存),而且会破坏引擎内的串行保证。
    logger.info(
        f"starting · {SERVICE_LABEL} on {cfg.host}:{cfg.port}  "
        f"voice={cfg.voice or '(未指定)'} model={cfg.version}"
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
