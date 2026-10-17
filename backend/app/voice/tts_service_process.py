"""GPT-SoVITS tts_service 子进程编排(方案 B)。

`TTS_SERVICE_SPAWN=1` 时由 backend 在 lifespan 里拉起 `python -m tts_service`,
这样使用者只需要 `uv run hrp` 一个命令,不用另开终端手工起 TTS。

为什么是子进程而不是同进程直接 import:两套推理栈装不进同一个 venv
(torch 2.6.0+cu124 vs 2.12.1+cu126;transformers 4.50 vs 4.51;numpy 1.26 vs 2.2),
同进程必须二选一,而 `GPT_SoVITS/configs/tts_infer.yaml` 的推理参数
(repetition_penalty / top_k / top_p / seed)是按当前这套钉版标定的,换版本要重标。
两个进程各持独立 CUDA context,显存互不干扰。

三件事都在本模块:
- spawn()  起进程(cwd / 环境 / Windows 进程组)
- is_running()  存活判定(启动期能尽早发现秒退)
- stop()  杀整棵树(taskkill /T /F),不只杀那个 pid
"""

from __future__ import annotations

import contextlib
import io
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
from pathlib import Path

from app import config
from app import logger as app_logger

_logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts_process")

_lock = threading.Lock()
_proc: subprocess.Popen[bytes] | None = None
_sink_handler: logging.Handler | None = None
_pump_thread: threading.Thread | None = None

# Windows 上要清的环境变量:子进程不该看见 backend 这一侧的解释器线索
_SCRUB_KEYS = ("CONDA_PREFIX", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP")


def _child_env() -> dict[str, str]:
    """给子进程构造环境:清污染项 + 把 GPT-SoVITS venv 的 Scripts 前置到 PATH。

    还必须钉死 PYTHONIOENCODING:Windows 上子进程 stdio 默认跟本机 ANSI 代码页
    (cp936 → gbk),父进程抽水时按 config.TTS_SERVICE_PYTHONIOENCODING 解码。
    两边不定死同一个值,日志就全是 U+FFFD。
    """
    env = dict(os.environ)
    if config.TTS_SERVICE_SCRUB_ENV:
        for key in _SCRUB_KEYS:
            env.pop(key, None)
        scripts = str(Path(config.TTS_SERVICE_PYTHON).parent)
        env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = config.TTS_SERVICE_PYTHONIOENCODING
    return env


def _open_sink_handler() -> logging.Handler | None:
    """开一个带轮转的日志 handler。落不了盘就返回 None,调用方退回继承终端。

    encoding 与抽水侧的解码用同一个 config 值,避免两边漂移。
    """
    path = Path(config.TTS_SERVICE_CWD) / config.TTS_SERVICE_STDOUT_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=config.TTS_SERVICE_STDOUT_MAX_BYTES,
            backupCount=config.TTS_SERVICE_STDOUT_BACKUP_COUNT,
            encoding=config.TTS_SERVICE_PYTHONIOENCODING,
            errors="replace",
        )
    except (OSError, LookupError):
        return None
    # 只留原文:上游的 ANSI 颜色码和 \\r 语义都要原样保住,不加分隔符与时间戳
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    return handler


def _pump(proc: subprocess.Popen[bytes], handler: logging.Handler) -> None:
    """把子进程 stdout 抽进 handler。

    为什么不能让子进程直接写文件(那样最省事):
    - `RotatingFileHandler` 没有 `fileno()`,`Popen(stdout=handler)` 直接
      AttributeError;
    - 就算传它内部的 stream,轮转判定只写在 `emit()` 里,而子进程是**直接往
      fd 写字节**,不经过 `emit()`,永远不会触发轮转。
    所以只能父进程读 PIPE,再经自己的 handler 落盘 —— 轮转才真的会发生。

    按 `\\n` 切分后整行投喂:handler 的 emit 会补换行,保持行的完整性;
    子进程只写 `\\r` 的进度条片段会攒在 buf 里等到下一个 `\\n`。
    (实测本机这套 TTS 不打印进度条,见 docs/guides/jl-option.md §6.3。)
    """
    stream = proc.stdout
    # bufsize=-1 时 Popen 给的是 io.BufferedReader;类型标注只写了 IO[bytes],
    # 而只有 BufferedReader 才有 read1。这里 isinstance 兼作类型收窄与运行期护栏。
    if not isinstance(stream, io.BufferedReader):  # pragma: no cover — 没开 PIPE 时才会这样
        return
    codec = config.TTS_SERVICE_PYTHONIOENCODING

    def emit(raw: bytes) -> None:
        handler.handle(
            logging.LogRecord("tts_stdout", logging.INFO, "", 0, raw.decode(codec, "replace"), None, None)
        )

    buf = b""
    try:
        while True:
            # 必须 read1 不能 read:BufferedReader.read(n) 在管道上会**阻塞到凑满
            # n 字节或 EOF**。整轮 TTS 日志量远小于 8192,子进程又一直活着,
            # 用 read() 的话这个线程会永远卡住,日志一个字都落不下来。
            # read1() 最多一次 raw read,有多少给多少(实测 202 字节 / 0.06s)。
            chunk = stream.read1(8192)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                emit(line)
        if buf:  # 末尾没有换行也别丢
            emit(buf)
    except (OSError, ValueError):  # 管道被 stop() 拆掉是正常收尾
        pass
    finally:
        with contextlib.suppress(OSError, ValueError):
            handler.close()


def _creation_flags() -> int:
    """Windows 专属创建标志。POSIX 上必须返回 0(Popen 拒绝非 0)。"""
    if os.name != "nt" or not config.TTS_SERVICE_PROCESS_GROUP:
        return 0
    # CREATE_NEW_PROCESS_GROUP:让 taskkill /T 能作用到它的后代
    # CREATE_NO_WINDOW:别在桌面弹一个黑框
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def spawn() -> subprocess.Popen[bytes] | None:
    """拉起 tts_service。已有一个自己拉起的在跑就直接复用。

    返回 None 表示"没能拉起也不该拉起"(缺 venv),调用方只记 WARN,不抛。
    端口被占用等真正的启动失败由子进程自己报错,本模块不吞。
    """
    global _proc, _sink_handler, _pump_thread

    python = Path(config.TTS_SERVICE_PYTHON)
    if not python.is_file():
        _logger.warning(
            "tts_spawn_missing_python",
            path=str(python),
            hint="先跑 cd GPT-SoVITS && uv sync(两个 venv 都要建)",
        )
        return None

    cwd = Path(config.TTS_SERVICE_CWD)
    if not cwd.is_dir():
        _logger.warning("tts_spawn_missing_cwd", path=str(cwd))
        return None

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return _proc
        redirect = not config.TTS_SERVICE_STDOUT_TO_CONSOLE
        handler = _open_sink_handler() if redirect else None
        if redirect and handler is None:
            redirect = False  # 落不了盘就退回继承终端,别为了日志把 TTS 拉不起来
        _proc = subprocess.Popen(
            [str(python), "-m", "tts_service"],
            cwd=str(cwd),
            env=_child_env(),
            stdout=subprocess.PIPE if redirect else None,
            stderr=subprocess.STDOUT if redirect else None,
            creationflags=_creation_flags(),
        )
        if handler is not None:
            _sink_handler = handler
            _pump_thread = threading.Thread(
                target=_pump,
                args=(_proc, handler),
                name="tts-stdout-pump",
                daemon=True,
            )
            _pump_thread.start()
        else:
            _sink_handler = None
            _pump_thread = None
        _logger.info(
            "tts_spawned",
            pid=_proc.pid,
            python=str(python),
            cwd=str(cwd),
            url=config.TTS_SERVICE_URL,
            stdout_log=(config.TTS_SERVICE_STDOUT_LOG if handler is not None else None),
        )
        return _proc


def is_running() -> bool:
    """自己拉起的进程是否还活着。启动期用它尽早发现秒退(端口占用等)。"""
    with _lock:
        return _proc is not None and _proc.poll() is None


def stop(*, timeout_s: float = 10.0) -> None:
    """关停子进程。

    优先 taskkill /T /F 杀整棵树 —— 只 terminate() 那个 pid,
    torch / onnxruntime 起来的后代进程会活下来变成孤儿,继续占显存和端口。
    非 Windows 或没开进程组时退回 terminate → wait → kill。

    日志 handler 由抽水线程在读到 EOF 后自己关(它比 stop() 更清楚管道什么时候完),
    这里只 join 一下确认它收干净了,不抢着关 —— 抢关会让线程往已关的 handler 写。
    """
    global _proc

    with _lock:
        proc, _proc = _proc, None

    if proc is None:
        return

    _terminate(proc, timeout_s)
    _drain_pump(proc)


def _drain_pump(proc: subprocess.Popen[bytes], timeout_s: float = 5.0) -> None:
    """等抽水线程把管道里的残余输出写完。线程是 daemon,这里只是不让它被硬切。"""
    thread = _pump_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout_s)


def _terminate(proc: subprocess.Popen[bytes], timeout_s: float) -> None:
    if proc.poll() is not None:
        return

    if not config.TTS_SERVICE_KILL_ON_EXIT:
        _logger.info("tts_stop_skipped", pid=proc.pid, reason="KILL_ON_EXIT=0")
        return

    _logger.info("tts_stopping", pid=proc.pid)

    if os.name == "nt" and config.TTS_SERVICE_PROCESS_GROUP:
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
            proc.wait(timeout=timeout_s)
            return
        except (subprocess.SubprocessError, OSError):
            pass  # 落到下面的兜底

    try:
        proc.terminate()
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        _logger.warning("tts_stop_killed", pid=proc.pid)


def _child_env_summary() -> dict[str, str]:
    """测试口:看子进程实际会拿到的环境(排查 PATH/污染用)。"""
    env = _child_env()
    return {
        "PATH_head": env.get("PATH", "").split(os.pathsep)[0],
        **{k: env.get(k, "<已清>") for k in _SCRUB_KEYS},
    }


if __name__ == "__main__":  # pragma: no cover — 人工排查入口
    print(sys.executable)
    print(_child_env_summary())
