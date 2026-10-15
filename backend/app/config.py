"""服务配置:环境变量单源 = backend/.env.example(python-dotenv 加载)。

带约定语义的可调常量(非密钥)也归此;改值不动调用方。
"""

import os

from dotenv import load_dotenv

load_dotenv()

# backend/ 根目录:一切内置资源/运行时路径的基准(由 __file__ 推导,不依赖进程 cwd)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 危机闸门 ----

CRISIS_GATE_THRESHOLD = float(os.getenv("CRISIS_GATE_THRESHOLD", "0.7"))
"""危机闸门命中阈值:severity ≥ 阈值判危机(词典内容运行时补)"""

# ---- LLM 双源(openai 兼容,provider 切换) ----

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# ---- 模型服务 profiles 的热激活槽位 ----
# 为空时继续回落上面的旧 .env 双源，兼容已有部署。
ACTIVE_PROFILE_ID = ""
ACTIVE_PROVIDER_ID = ""
ACTIVE_MODEL = ""
ACTIVE_API_KEY = ""
ACTIVE_BASE_URL = ""

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

RAG_CORPUS_PATH = os.path.join(_BACKEND_DIR, "data", "rag_case_corpus.jsonl")
"""案例库语料 jsonl(question=来访者问题,answer=治疗思路)"""

RAG_KNOWLEDGE_CORPUS_PATH = os.path.join(_BACKEND_DIR, "data", "rag_knowledge_corpus.jsonl")
"""科普知识库语料 jsonl(question=知识问,answer=科普答;1022 条队友交付)"""

RAG_STORE_PATH = os.path.join(_BACKEND_DIR, ".rag_store")
"""Chroma 持久化目录(运行时产物,不入 git;内分 hrp_kb_knowledge / hrp_kb_case 两集合)"""

RAG_MODELS_DIR = os.path.join(_BACKEND_DIR, "models")
"""RAG 模型目录(bge-m3 / bge-reranker-v2-m3;gitignore 不入库)"""

RAG_EMBED_MODEL = os.path.join(RAG_MODELS_DIR, "bge-m3")
"""embedding 模型"""

RAG_RERANK_MODEL = os.path.join(RAG_MODELS_DIR, "bge-reranker-v2-m3")
"""reranker 重排模型"""

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

MEMORY_DB_PATH = os.path.join(_BACKEND_DIR, "data", "profile.db")
"""冷层 SQLite(长期画像+情绪趋势,无 TTL;运行时产物不入 git)"""

MOOD_RECENT_CAP = 5
"""热层 mood_recent 滚动上限(喂 snapshot/Live2D 语境)"""

# ---- 语义记忆(spec §4 L7「语义」层;PRD docs/prds/semantic-memory.md) ----

SEMANTIC_MEM_STORE_PATH = os.path.join(_BACKEND_DIR, ".mem_store")
"""语义记忆 Chroma 持久化目录(运行时产物,不入 git;与知识库 .rag_store 物理分离)"""

SEMANTIC_MEM_TOP_K = 3
"""召回条数上限"""

SEMANTIC_MEM_MIN_COS = 0.5
"""噪声闸门低档:余弦低于此值静默(原型定标,硬卡高阈值会误杀,取舍权在 LLM)"""

SEMANTIC_MEM_DECAY_DAYS = 30
"""超期降权天数:条目 age 超此值降低排序权重(未过期不衰减)"""

SEMANTIC_MEM_NOTE_TIMEOUT_S = 8.0
"""检索笔记 LLM 生成上限(回合末异步,超时降级拼接,不阻塞任何帧)"""

SEMANTIC_MEM_NOTE_MAX_CHARS = 80
"""检索笔记长度上限(30~60 字目标,80 兜底截断)"""

# ---- 工具(步骤9:station 方案书存取 / admin 模型配置) ----

STATION_DB_PATH = os.path.join(_BACKEND_DIR, "data", "station.db")
"""方案书 SQLite(每会话最新胜;运行时产物不入 git)"""

WALL_DB_PATH = os.path.join(_BACKEND_DIR, "data", "wall.db")
"""留言墙 SQLite；与会话记忆和一键清除记忆分离，worker 按七日清理。"""

ADMIN_CONFIG_DB_PATH = os.path.join(_BACKEND_DIR, "data", "config.db")
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
    os.path.join(_BACKEND_DIR, "..", "models", "voices", "CosyVoice", ".venv", "Scripts", "python.exe"),
)
"""CosyVoice 仓库自备 venv 的 python(tts_sidecar.py 在该解释器下运行)"""

TTS_SIDECAR_READY_TIMEOUT_S = 120.0
"""sidecar 首次拉起等待(进程+模型加载,CPU/GPU 冷启可到分钟级)"""

TTS_SIDECAR_KILL_ON_EXIT = os.getenv("TTS_SIDECAR_KILL_ON_EXIT", "1") != "0"
"""backend 退出时是否关停自己拉起的 sidecar;--reload 热载开发设 0,免得改一行代码陪杀模型"""

TTS_MODE = os.getenv("TTS_MODE", "remote")
"""TTS 运行模式: remote = HTTP 远程服务(默认); local = sidecar 子进程(回滚用)"""

TTS_FIRST_SENTENCE_HANZI = int(os.getenv("TTS_FIRST_SENTENCE_HANZI", "12"))
"""首句字数上限(仅 answer 语音链路的第一句生效,后续句子仍按 30 字)。

流水线 TTFB ≈ 首句字数 × LLM 每字耗时 + 服务侧首块耗时,首句是唯一的调节旋钮:
实测首句 4 字 -> TTFB 0.72s;24 字 -> 3.14s;31 字 -> 4.29s。
调小换取更快出声与更高的音文交错率,代价是首句语气更碎。
"""

TTS_ANSWER_VOICE = os.getenv("TTS_ANSWER_VOICE", "1") not in ("0", "false", "no")
"""answer 路由是否同时流式出语音。默认开:句子泵让首句音频不必等 LLM 全文生成完。

关掉 = 只走文字流(调试语音链路、或想对比"有无语音"的体感差异时用)。
其余路由(crisis 安抚语 / collect / 总结 / fillers)不受此开关影响。
"""

TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:9001")
"""远程 TTS 服务地址;必须写 127.0.0.1 不写 localhost(IPv6 ::1 先解析会白等 2.1s)"""

TTS_SERVICE_TIMEOUT_S = float(os.getenv("TTS_SERVICE_TIMEOUT_S", "600"))
"""远程 TTS 合成流整体超时(秒);首包超时 30s 固定在客户端"""

SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")
"""远程服务共享认证 token(Bearer header);空=跳过验证(开发环境)"""

AUDIO_INPUT_MAX_S = 15.0
"""语音输入单段上限(契约 §4.1;前端录音侧执行)"""

FILLERS_DIR = os.path.join(_BACKEND_DIR, "data", "fillers")
"""预生成等待语音目录(运行时直读零合成;gitignored)"""
