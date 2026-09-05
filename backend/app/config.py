"""服务配置:环境变量单源 = backend/.env.example(python-dotenv 加载)。

带约定语义的可调常量(非密钥)也归此;改值不动调用方。
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---- 危机闸门 ----

CRISIS_GATE_THRESHOLD = float(os.getenv("CRISIS_GATE_THRESHOLD", "0.7"))
"""危机闸门命中阈值:severity ≥ 阈值判危机(词典内容运行时补)"""

# ---- LLM 双源(openai 兼容,provider 切换) ----

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

LLM_TIMEOUT_S = 60.0
"""单条 user_input 全链路处理上限(契约 §7 超时兜底)"""

LLM_CLASSIFY_TIMEOUT_S = 8.0
"""分层判定 LLM 调用上限;超时按 collect 兜底(spec §4 L3/L4 不等待)"""

# ---- 分层判定(spec §4 L3 可调常量) ----

CLASSIFIER_RULE_CONF = 0.9
"""规则路径置信度"""

CLASSIFIER_LLM_MIN_CONF = 0.6
"""LLM 置信度下限,低于则兜底 collect(collect 比 answer 安全)"""

# ---- RAG ----

RAG_SEEDS_PATH = os.path.join("data", "rag_seeds.jsonl")
"""种子语料(相对 backend/;定稿见 docs/option.md 编码期人介入环节)"""

RAG_STORE_PATH = os.path.join(".rag_store")
"""Chroma 持久化目录(运行时产物,不入 git)"""

RAG_TOP_K = 3
"""retrieve 默认返回条数(k=None 时用)"""

# ---- 多轮采集(spec §4 L4 可调常量) ----

COLLECT_MAX_ROUNDS = 3
"""轮数上限(常态 2 轮收尾,上限兜底)"""

COLLECT_STOP_THRESHOLD = 0.7
"""充分度停采阈值(常规档)"""

COLLECT_TEST_STOP_THRESHOLD = 0.85
"""测试档停采阈值(约 3 轮挖信念;仅测试用,业务代码不读)"""

# ---- 记忆(层介质与生命周期单源=spec §4 L7,数值不复制到其他文档) ----

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
"""热/温层 Redis(契约 §8.4 重连恢复;单源=backend/.env.example)"""

MEMORY_HOT_TTL_S = 30 * 60
"""热层 TTL:当前会话上下文(spec §4 L7)"""

MEMORY_WARM_TTL_S = 7 * 24 * 3600
"""温层 TTL:会话摘要 + station:input(spec §4 L7)"""

MEMORY_DB_PATH = os.path.join("data", "profile.db")
"""冷层 SQLite(长期画像+情绪趋势,无 TTL;运行时产物不入 git)"""

MOOD_RECENT_CAP = 5
"""热层 mood_recent 滚动上限(喂 snapshot/Live2D 语境)"""

# ---- 工具(步骤9:station 方案书存取 / admin 模型配置) ----

STATION_DB_PATH = os.path.join("data", "station.db")
"""方案书 SQLite(每会话最新胜;运行时产物不入 git)"""

ADMIN_CONFIG_DB_PATH = os.path.join("data", "config.db")
"""模型配置 SQLite(api_key AES-GCM 加密落库;运行时产物不入 git)"""

CONFIG_AES_KEY = os.getenv("HRP_CONFIG_AES_KEY", "")
"""api_key 字段加密密钥(hex,16/24/32 字节);环境变量注入绝不入库(spec §4 L7)"""

CORS_ALLOW_ORIGINS = [
    o for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o
]
"""浏览器跨源访问 REST(station/admin)的白名单;WS 不受同源策略约束无需此表。
默认=前端 dev 两址;生产同源部署可收紧为空(ws-contract §1 端点面不变)"""

# ---- 语音(backend-plan §2 voice 行;ASR=funasr SenseVoice 本地,TTS=CosyVoice sidecar) ----

ASR_MODEL_ID = "iic/SenseVoiceSmall"
"""SenseVoice 小模型(funasr AutoModel 直载;首次调用懒加载)"""

TTS_SIDECAR_PORT = int(os.getenv("TTS_SIDECAR_PORT", "9880"))
"""CosyVoice sidecar 端口(127.0.0.1;与 backend venv 隔离的独立进程)"""

TTS_SIDECAR_PYTHON = os.getenv(
    "TTS_SIDECAR_PYTHON",
    os.path.join("..", "models", "voices", "CosyVoice", ".venv", "Scripts", "python.exe"),
)
"""CosyVoice 仓库自备 venv 的 python(tts_sidecar.py 在该解释器下运行)"""

TTS_SIDECAR_READY_TIMEOUT_S = 120.0
"""sidecar 首次拉起等待(进程+模型加载,CPU/GPU 冷启可到分钟级)"""

AUDIO_INPUT_MAX_S = 15.0
"""语音输入单段上限(契约 §4.1;前端录音侧执行)"""

FILLERS_DIR = os.path.join("data", "fillers")
"""预生成等待语音目录(fillers 脚本产物,运行时直读零合成;gitignored)"""
