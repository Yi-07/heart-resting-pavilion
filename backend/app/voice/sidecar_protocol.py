"""sidecar 进程协议常量(零依赖单源):backend venv 与 CosyVoice venv 两边共用。

tts_sidecar.py 以脚本方式运行时,其所在目录自动在 sys.path[0],
直接 `from sidecar_protocol import ...` 即可;backend 侧走包导入。
"""

SIDECAR_VERSION = 1
"""协议版本:sidecar 响应体携带,backend 校验;不匹配=进程代码过期,拒绝静默复用。
Step2 引入 /tts_stream 时 bump 到 2。"""
