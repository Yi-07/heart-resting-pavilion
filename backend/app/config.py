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
