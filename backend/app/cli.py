"""启动入口(`uv run hrp`):包一层 uvicorn,吃掉默认端口。

uv run uvicorn app.main:app --port 8000 的短命令版;--reload 透传(uvicorn CLI)。
"""

import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(prog="hrp", description="心栖阁 backend 启动入口")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="开发热载(建议配 TTS_SIDECAR_KILL_ON_EXIT=0)")
    args = ap.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
