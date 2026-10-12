"""模型配置存取(spec §4 L7 · ws-contract §1 /admin/llm/*):profiles 多配置 + 全局单激活。

- 表 `llm_profiles`(id/provider_id/model_id/api_key_enc/verified)+ `active_profile`
  单行激活指针;前端只提交 provider_id/model_id/api_key 三字段,展示名由后端生成
- **写操作全走单事务**(`_txn`):新建即激活 = INSERT(verified=1)+ 指针同提交;
  切换激活 = 指针 + verified 同提交。杜绝"指针落了、verified 没落"的半提交;
  提交失败异常外抛,路由层据此不翻内存
- **顺序铁律**:候选先在内存构造并真实验证 → 通过才落库(单事务)→ 提交成功
  才翻内存(config.ACTIVE_*)。验证失败/提交失败时,库与内存双不动,
  原激活配置继续服务
- api_key 字段 AES-GCM 加密落库;密钥环境变量注入(config.CONFIG_AES_KEY,
  hex 16/24/32 字节),**绝不入库**;未配置时拒存 api_key(ConfigKeyError→路由 400)
- 读口返回进程内明文 api_key 仅供拼装调用,**绝不进 HTTP 响应**(前端零密钥)
- 并发锁由路由层持(`_activate_lock` 覆盖新建/编辑/激活/删除),本模块不自治锁
"""

from __future__ import annotations

import base64
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="admin")

# 自举密钥落点(backend/.hrp_config_key);环境变量优先,见 ensure_aes_key
_KEY_FILE = Path(config.__file__).resolve().parent.parent / ".hrp_config_key"


class ConfigKeyError(Exception):
    """加密密钥缺失/非法,无法加密存储 api_key。"""


class ActiveProfileError(Exception):
    """激活中的配置不可删除。"""


@dataclass(frozen=True)
class StoredLLMConfig:
    """旧版 /admin/config 兼容记录；新界面使用 profiles 表。"""

    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


@dataclass(frozen=True)
class Profile:
    id: str
    provider_id: str
    model_id: str
    api_key: str | None = None  # 解密后明文,仅进程内
    verified: bool = False

    @property
    def display_name(self) -> str:
        """展示名:DeepSeek · deepseek-chat(preset label + model_id)。"""

        from app.llm.presets import get_preset  # 函数内 import:避免循环

        preset = get_preset(self.provider_id)
        label = preset.label if preset is not None else self.provider_id
        return f"{label} · {self.model_id}"


def ensure_aes_key() -> None:
    """部署前置:AES 密钥自举(env 优先;未设则生成并落 .hrp_config_key)。

    - **丢失该密钥 = 已存 api_key 永久不可解密**(仅能重填),故落盘而非每次随机
    - 落盘文件 gitignored、权限收紧;日志只记路径,**绝不记密钥本身**(§6.2)
    """

    if config.CONFIG_AES_KEY:
        return
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            config.CONFIG_AES_KEY = key
            logger.info("config_aes_key_loaded", source=str(_KEY_FILE))
            return
    key = os.urandom(32).hex()
    try:
        _KEY_FILE.write_text(key, encoding="utf-8")
        os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logger.warning("config_aes_key_write_failed", path=str(_KEY_FILE), reason=str(exc)[:120])
        raise ConfigKeyError("无法写入 AES 密钥文件") from exc
    config.CONFIG_AES_KEY = key
    logger.warning(
        "config_aes_key_generated",
        path=str(_KEY_FILE),
        hint="删除或丢失该文件=已存 API Key 永久不可解密,请备份",
    )


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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_profiles (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    api_key_enc TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_profile (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    profile_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    model TEXT,
    base_url TEXT,
    api_key_enc TEXT,
    updated_at TEXT NOT NULL
);
"""


class ConfigStore:
    def __init__(self, db_path: str = config.ADMIN_CONFIG_DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)

    def save(self, cfg: StoredLLMConfig) -> None:
        """兼容旧 /admin/config 的单行 AES-GCM 配置。"""

        with sqlite3.connect(self._db_path) as conn:
            old = conn.execute("SELECT api_key_enc FROM llm_config WHERE id = 1").fetchone()
            encrypted = _encrypt(cfg.api_key) if cfg.api_key else (old[0] if old else None)
            conn.execute(
                "INSERT INTO llm_config (id, provider, model, base_url, api_key_enc, updated_at) "
                "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, "
                "model=excluded.model, base_url=excluded.base_url, api_key_enc=excluded.api_key_enc, "
                "updated_at=excluded.updated_at",
                (cfg.provider, cfg.model, cfg.base_url, encrypted, _now()),
            )

    def load(self) -> StoredLLMConfig | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT provider, model, base_url, api_key_enc FROM llm_config WHERE id = 1").fetchone()
        if row is None:
            return None
        key: str | None = None
        if row[3]:
            try:
                key = _decrypt(row[3])
            except Exception as exc:  # noqa: BLE001
                logger.warning("degraded", layer="config_decrypt", reason=str(exc)[:120])
        return StoredLLMConfig(row[0], row[1], row[2], key)

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """单事务上下文:块内全部语句共一次提交,异常整体回滚。

        路由层所有写操作(新建即激活/编辑/激活/删除)都必须整块走这里,
        杜绝"指针落了、verified 没落"之类的半提交状态;提交失败(如磁盘错)
        异常外抛,路由层因此不会翻内存。
        """

        conn = sqlite3.connect(self._db_path)
        try:
            with conn:  # __exit__ 提交;块内异常回滚
                yield conn
        finally:
            conn.close()

    # ---- 读写 ----

    def _row_to_profile(self, row: tuple) -> Profile:
        profile_id, provider_id, model_id, api_key_enc, verified = row
        api_key: str | None = None
        if api_key_enc:
            try:
                api_key = _decrypt(api_key_enc)
            except Exception as exc:  # noqa: BLE001 — 解密失败丢密钥不炸启动/读取
                logger.warning("degraded", layer="config_decrypt", reason=str(exc)[:120])
        return Profile(
            id=profile_id,
            provider_id=provider_id,
            model_id=model_id,
            api_key=api_key,
            verified=bool(verified),
        )

    def create_and_activate(self, provider_id: str, model_id: str, api_key: str | None) -> Profile:
        """新建即激活:**单事务** INSERT(verified=1)+ 置 active 指针。

        调用方必须先完成真实验证(路由流程:内存构造候选 → 验证 → 本方法 →
        翻内存)。事务提交后返回已解密 Profile;失败(含 ConfigKeyError)整体
        回滚,库里不留残行,激活指针不动。
        """

        enc = _encrypt(api_key) if api_key else None  # 无 AES 密钥时在此抛,整体不落
        now = _now()
        profile_id = f"p_{uuid.uuid4().hex[:12]}"
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO llm_profiles (id, provider_id, model_id, api_key_enc, verified,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (profile_id, provider_id, model_id, enc, now, now),
            )
            conn.execute(
                "INSERT INTO active_profile (singleton, profile_id) VALUES (1, ?)"
                " ON CONFLICT(singleton) DO UPDATE SET profile_id = excluded.profile_id",
                (profile_id,),
            )
        return self.get_profile(profile_id) or Profile(
            id=profile_id, provider_id=provider_id, model_id=model_id, api_key=api_key, verified=True
        )

    def apply_edit(
        self,
        profile_id: str,
        *,
        model_id: str | None = None,
        api_key: str | None = None,
        verified: bool | None = None,
    ) -> Profile:
        """编辑(单事务):model_id/api_key 缺省不动;api_key 空值=保留旧密文
        (读原行密文,不明文回灌);model/key 变化时默认清 verified(过期),
        调用方显式传 verified=True 表示候选已验证(激活中配置的编辑)。

        激活中的配置被编辑时,**先验证再调本方法、提交后才翻内存**:
        验证失败根本走不到这里;提交失败则内存不动。
        """

        current = self.get_profile(profile_id)
        if current is None:
            raise KeyError(profile_id)
        new_model = model_id if model_id else current.model_id
        changed = new_model != current.model_id or bool(api_key)
        with self._txn() as conn:
            row = conn.execute(
                "SELECT api_key_enc FROM llm_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            old_enc = row[0] if row is not None else None
            final_enc = _encrypt(api_key) if api_key else old_enc
            if verified is None:
                new_verified = 0 if changed else int(current.verified)
            else:
                new_verified = 1 if verified else 0
            conn.execute(
                "UPDATE llm_profiles SET model_id = ?, api_key_enc = ?, verified = ?,"
                " updated_at = ? WHERE id = ?",
                (new_model, final_enc, new_verified, _now(), profile_id),
            )
        updated = self.get_profile(profile_id)
        assert updated is not None
        return updated

    def activate_verified(self, profile_id: str) -> Profile:
        """切换激活(单事务):active 指针 + verified=1 同一提交,不半提交。

        调用方必须先完成真实验证;提交成功返回 Profile,由路由层翻内存。
        """

        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        now = _now()
        with self._txn() as conn:
            conn.execute(
                "INSERT INTO active_profile (singleton, profile_id) VALUES (1, ?)"
                " ON CONFLICT(singleton) DO UPDATE SET profile_id = excluded.profile_id",
                (profile_id,),
            )
            conn.execute(
                "UPDATE llm_profiles SET verified = 1, updated_at = ? WHERE id = ?",
                (now, profile_id),
            )
        refreshed = self.get_profile(profile_id)
        assert refreshed is not None
        return refreshed

    def delete_profile(self, profile_id: str) -> None:
        """删除(单事务);激活中的配置拒删(ActiveProfileError,先切换再删)。"""

        if self.active_id() == profile_id:
            raise ActiveProfileError(profile_id)
        with self._txn() as conn:
            conn.execute("DELETE FROM llm_profiles WHERE id = ?", (profile_id,))

    def list_profiles(self) -> list[Profile]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, provider_id, model_id, api_key_enc, verified FROM llm_profiles"
                " ORDER BY created_at"
            ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def get_profile(self, profile_id: str) -> Profile | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT id, provider_id, model_id, api_key_enc, verified FROM llm_profiles"
                " WHERE id = ?",
                (profile_id,),
            ).fetchone()
        return self._row_to_profile(row) if row is not None else None

    # ---- 激活指针 ----

    def active_id(self) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT profile_id FROM active_profile WHERE singleton = 1"
            ).fetchone()
        return str(row[0]) if row is not None else None

    def active_profile(self) -> Profile | None:
        active = self.active_id()
        return self.get_profile(active) if active else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005 — 单机原型


def apply_active(profile: Profile | None) -> None:
    """把激活配置(或空)应用到进程 config —— get_provider 每次现读,即时生效。"""

    if profile is None:
        config.ACTIVE_PROFILE_ID = ""
        config.ACTIVE_PROVIDER_ID = ""
        config.ACTIVE_MODEL = ""
        config.ACTIVE_API_KEY = ""
        config.ACTIVE_BASE_URL = ""
        return
    from app.llm.presets import get_preset  # 函数内 import:避免循环

    preset = get_preset(profile.provider_id)
    config.ACTIVE_PROFILE_ID = profile.id
    config.ACTIVE_PROVIDER_ID = profile.provider_id
    config.ACTIVE_MODEL = (
        f"{preset.litellm_key}/{profile.model_id}" if preset is not None else profile.model_id
    )
    config.ACTIVE_API_KEY = profile.api_key or ""
    # base_url 仅 openai 兼容族透传;anthropic/gemini 原生路由由 litellm 内置端点
    config.ACTIVE_BASE_URL = preset.base_url if preset is not None and preset.api_base_supported else ""


def apply_llm_config(cfg: StoredLLMConfig) -> None:
    """旧配置接口应用到环境回落槽位；激活 profile 仍具有更高优先级。"""

    config.LLM_PROVIDER = cfg.provider
    if cfg.provider == "deepseek":
        if cfg.model:
            config.DEEPSEEK_MODEL = cfg.model
        if cfg.base_url:
            config.DEEPSEEK_BASE_URL = cfg.base_url
        if cfg.api_key:
            config.DEEPSEEK_API_KEY = cfg.api_key
    elif cfg.provider == "ollama":
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
    """启动读回激活配置并应用(main lifespan 调;无激活=保持 env 兜底)。"""

    try:
        store = get_config_store()
        profile = store.active_profile()
    except Exception as exc:  # noqa: BLE001 — 配置读回失败不炸启动
        logger.warning("degraded", layer="config_load", reason=str(exc)[:120])
        return
    if profile is not None:
        apply_active(profile)
        logger.info(
            "config_applied", profile_id=profile.id, provider=profile.provider_id,
            model=profile.model_id, has_key=profile.api_key is not None,
        )
        return
    legacy = store.load()
    if legacy is not None:
        apply_llm_config(legacy)
        logger.info("legacy_config_applied", provider=legacy.provider)
