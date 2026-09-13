"""模型配置存取(spec §4 L7):LLM 引擎配置存 SQLite,api_key 字段 AES-GCM 加密。

- 加密密钥环境变量注入(config.CONFIG_AES_KEY,hex 16/24/32 字节),绝不入库;
  未配置时拒存 api_key(明文落库是红线,ConfigKeyError→路由 400),其余字段可存
- 单行配置(id=1 最新胜);启动时 load_and_apply 读回并覆盖 env 应用
  (治理语义:用户显式配置优先;解密失败仅 WARN 丢密钥,其余照常)
- 读口返回进程内明文 api_key 供应用,但**绝不进 HTTP 响应**(前端零密钥)
"""

from __future__ import annotations

import base64
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="admin")


class ConfigKeyError(Exception):
    """加密密钥缺失/非法,无法加密存储 api_key。"""


@dataclass(frozen=True)
class StoredLLMConfig:
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


def _aes_key() -> bytes:
    raw = config.CONFIG_AES_KEY
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise ConfigKeyError("HRP_CONFIG_AES_KEY 需为合法 hex") from exc
    if len(key) not in (16, 24, 32):
        raise ConfigKeyError("HRP_CONFIG_AES_KEY 需为 16/24/32 字节的 hex")
    return key


def _encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(blob: str) -> str:
    data = base64.b64decode(blob)
    return AESGCM(_aes_key()).decrypt(data[:12], data[12:], None).decode()


class ConfigStore:
    def __init__(self, db_path: str = config.ADMIN_CONFIG_DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    provider TEXT NOT NULL,
                    model TEXT,
                    base_url TEXT,
                    api_key_enc TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _existing_key_enc(self) -> str | None:
        """读现库存量密文(D5):api_key 缺省保留旧值,POST 不带 key 不清库内密钥。"""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT api_key_enc FROM llm_config WHERE id = 1").fetchone()
        return str(row[0]) if row is not None and row[0] else None

    def save(self, cfg: StoredLLMConfig) -> None:
        """最新胜单行;api_key 有值则加密存储,缺省保留旧值(与 apply_llm_config
        「None 字段不动」同语义;密钥缺失抛 ConfigKeyError,整体不落)。"""

        enc = _encrypt(cfg.api_key) if cfg.api_key else self._existing_key_enc()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO llm_config (id, provider, model, base_url, api_key_enc, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    api_key_enc = excluded.api_key_enc,
                    updated_at = excluded.updated_at
                """,
                (
                    cfg.provider,
                    cfg.model,
                    cfg.base_url,
                    enc,
                    datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005 — 单机原型
                ),
            )

    def load(self) -> StoredLLMConfig | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT provider, model, base_url, api_key_enc FROM llm_config WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        api_key: str | None = None
        if row[3]:
            try:
                api_key = _decrypt(row[3])
            except Exception as exc:  # noqa: BLE001 — 解密失败丢密钥不炸启动
                logger.warning(
                    "degraded", layer="config_decrypt", reason=str(exc)[:120]
                )
        return StoredLLMConfig(provider=row[0], model=row[1], base_url=row[2], api_key=api_key)


def apply_llm_config(cfg: StoredLLMConfig) -> None:
    """应用到进程 config(get_provider 每次动态读,即时生效;None 字段不动)。"""

    config.LLM_PROVIDER = cfg.provider
    if cfg.provider == "deepseek":
        if cfg.model:
            config.DEEPSEEK_MODEL = cfg.model
        if cfg.base_url:
            config.DEEPSEEK_BASE_URL = cfg.base_url
        if cfg.api_key:
            config.DEEPSEEK_API_KEY = cfg.api_key
    else:
        if cfg.model:
            config.OLLAMA_MODEL = cfg.model
        if cfg.base_url:
            config.OLLAMA_URL = cfg.base_url


_store: ConfigStore | None = None


def get_config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store


def reset_config_store(store: ConfigStore | None = None) -> None:
    """测试隔离:换实例或清空。"""

    global _store
    _store = store


def load_and_apply() -> None:
    """启动读回持久配置并应用(main lifespan 调;无配置/失败=WARN 走 env)。"""

    try:
        cfg = get_config_store().load()
    except Exception as exc:  # noqa: BLE001 — 配置读回失败不炸启动
        logger.warning("degraded", layer="config_load", reason=str(exc)[:120])
        return
    if cfg is None:
        return
    apply_llm_config(cfg)
    logger.info("config_applied", provider=cfg.provider, has_key=cfg.api_key is not None)
