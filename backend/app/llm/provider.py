"""LLM 统一传输层(litellm-core 原生路由;ws-contract §1 /admin/llm/* 的调用底座)。

- 所有 provider 走 `litellm.acompletion`:协议翻译/异步/流式由 litellm-core 托管,
  本模块不再持有任何 AsyncOpenAI 客户端(原 openai SDK 直连的老实现已移除)
- **litellm 懒加载**:模块顶部不 import(冷启实测 ~6s),首次调用才进内存;
  且 import 前必须置 `LITELLM_LOCAL_MODEL_COST_MAP=true` —— 否则 litellm
  启动时联网拉 model_cost 目录(本机实测连不上 GitHub 时退避重试 ~7s 才回落
  包内备份,拖慢每次冷启)
- **双层重试全关**:`num_retries=0`(litellm 自己的)+ `max_retries=0`
  (底层 Provider SDK 默认各带重试:openai SDK 2、anthropic SDK 2)——
  契约是「失败显式降级话术库」,不做任何自动重试
- 出错抛 LLMError,由调用方捕获后降级;异常文本先脱敏(可能回显密钥)再外抛
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ValidationError

from app import config, diag

MessageRole = Literal["system", "user", "assistant"]

_litellm: object | None = None


@dataclass(frozen=True)
class Message:
    role: MessageRole
    content: str


class LLMError(Exception):
    """LLM 调用/解析失败;调用方降级到话术库。"""


@dataclass(frozen=True)
class ProviderSpec:
    """一次调用的全部入参:litellm 完整模型 ID + 密钥 +(可选)base_url。

    base_url 仅 openai 兼容族透传(litellm api_base);anthropic/gemini
    原生路由留空,端点由 litellm 内置维护(presets.api_base_supported=False)。
    """

    model: str
    api_key: str = ""
    base_url: str = ""


# 传输函数签名:(spec, messages, stream, max_tokens, timeout) -> 响应对象。
# 默认实现走 litellm;测试注入替身(见 tests/test_llm_provider.py)。
ProviderCall = Callable[[ProviderSpec, list[Message], bool, "int | None", float], Awaitable[object]]

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def load_litellm() -> object:
    """litellm 懒加载(进程内一次)。必须先于 import 置离线目录开关。"""

    global _litellm
    if _litellm is None:
        os.environ.setdefault("LITELLM_LOG", "ERROR")  # 默认只留 ERROR,防 DEBUG 刷屏
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
        import litellm  # 函数内 import:AGENTS.md §4.6 重依赖不进模块顶部

        # 静音:litellm 默认开 verbose(DEBUG 级,刷屏且踩 Windows GBK 控制台
        # 的 emoji 编码 error);本项目的可读日志走 app.logger(loguru),输出形态
        # 与 litellm 无关。
        for attr, value in (("set_verbose", False), ("suppress_debug_info", True)):
            with contextlib.suppress(Exception):  # 属性不存在就跳过,不影响调用
                setattr(litellm, attr, value)
        _litellm = litellm
    return _litellm


def extract_json(text: str) -> str:
    """剥掉 ```json 围栏;无围栏返回原文。"""

    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _redact(text: str, secret: str) -> str:
    """异常文本脱敏:密钥片段绝不进日志/响应(AGENTS.md §6.2)。"""

    if secret and len(secret) >= 8 and secret in text:
        return text.replace(secret, "***")
    return text


_shared_session: object | None = None


def llm_shared_session() -> object | None:
    """进程内共享 aiohttp session:litellm 默认**每次调用新建 ClientSession**
    (实测日志 NEW SESSION per call),即每个请求白付一次 TCP+TLS 握手;
    传入 shared_session 后连接池跨调用复用(openai 兼容族 6 家全覆盖;
    anthropic/gemini 走各自 SDK,不受此影响)。取不到返回 None,退化为
    litellm 默认行为,不影响正确性。"""

    global _shared_session
    if _shared_session is None:
        try:
            import aiohttp

            _shared_session = aiohttp.ClientSession()
        except Exception:  # noqa: BLE001 — 没有 aiohttp 环境就退化成 litellm 默认
            return None
    return _shared_session


async def close_llm_session() -> None:
    """关停共享 session(main lifespan shutdown 调;测试/env 无会话时空转)。"""

    global _shared_session
    session, _shared_session = _shared_session, None
    if session is not None:
        with contextlib.suppress(Exception):  # 关停失败不挡进程退出
            await cast("Any", session).close()


def _oai_messages(messages: list[Message]) -> list[object]:
    """Message → litellm messages 参数;cast 收窄字面量联合。"""

    return cast("list[object]", [{"role": m.role, "content": m.content} for m in messages])


async def _litellm_call(
    spec: ProviderSpec,
    messages: list[Message],
    stream: bool,
    max_tokens: int | None,
    timeout: float,
) -> object:
    """默认传输:litellm.acompletion;异常包 LLMError(脱敏后)。"""

    litellm = load_litellm()
    kwargs: dict[str, object] = {
        "model": spec.model,
        "messages": _oai_messages(messages),
        "api_key": spec.api_key or "litellm-no-key",  # ollama 等免密钥也需非空
        "num_retries": 0,  # litellm 自己的重试
        "max_retries": 0,  # 底层 Provider SDK 的重试
        "timeout": timeout,
    }
    if spec.base_url:
        kwargs["api_base"] = spec.base_url
    if stream:
        kwargs["stream"] = True
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    session = llm_shared_session()
    if session is not None:
        kwargs["shared_session"] = session  # 连接池跨调用复用(见 llm_shared_session)
    try:
        return await litellm.acompletion(**kwargs)  # type: ignore[attr-defined]
    except Exception as exc:  # 网络/鉴权/限流统一包装
        raise LLMError(_redact(str(exc), spec.api_key)) from exc


class OpenAICompatProvider:
    """litellm 参数化实现;call 可注入(测试替身,不打真 API)。"""

    def __init__(
        self,
        spec: ProviderSpec | object,
        call: ProviderCall | None = None,
        *,
        model: str | None = None,
    ) -> None:
        # 保留 yxw 旧测试/本地替身的 OpenAICompatProvider(client, model=...) 入口。
        self._legacy_client = None if isinstance(spec, ProviderSpec) else spec
        self._spec = spec if isinstance(spec, ProviderSpec) else ProviderSpec(model=model or "")
        self._call = call if call is not None else _litellm_call

    @property
    def model(self) -> str:
        return self._spec.model

    async def chat(
        self, messages: list[Message], *, max_tokens: int | None = None, timeout: float | None = None
    ) -> str:
        try:
            if self._legacy_client is not None:
                resp = await cast(Any, self._legacy_client).chat.completions.create(
                    model=self.model,
                    messages=_oai_messages(messages),
                )
            else:
                resp = await self._call(self._spec, messages, False, max_tokens, timeout or config.LLM_TIMEOUT_S)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(_redact(str(exc), self._spec.api_key)) from exc
        choices = getattr(resp, "choices", None)
        if not choices:
            raise LLMError("响应无 choices")
        return choices[0].message.content or ""

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        # 注意:本方法是 async generator function,调用它只创建 generator 对象,
        # 下面的调用要到第一次 __anext__ 才真正执行 —— 「LLM 请求发出」的时刻
        # 是消费端的第一次迭代,不是调用 stream() 的时刻。
        n = 0
        try:
            diag.mark(
                "llm_create_begin",
                model=self._spec.model,
                n_msgs=len(messages),
                # 实际发给 litellm 的 kwargs(model/messages/api_key/num_retries/
                # max_retries/timeout;stream/ max_tokens 按需)
                sent_kwargs=["model", "messages", "stream", "num_retries=0", "max_retries=0"],
            )
            if self._legacy_client is not None:
                raw = await cast(Any, self._legacy_client).chat.completions.create(
                    model=self.model,
                    messages=_oai_messages(messages),
                    stream=True,
                )
            else:
                raw = await self._call(self._spec, messages, True, None, config.LLM_TIMEOUT_S)
            diag.mark("llm_headers")
            stream_obj = cast("AsyncIterator[Any]", raw)
            async for chunk in stream_obj:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    n += 1
                    if n == 1:
                        diag.mark("llm_token_1", size=len(delta), head=delta[:12])
                    elif n == 2:
                        diag.mark("llm_token_2", size=len(delta))
                    yield delta
            diag.mark("llm_stream_end", n_chunks=n)
        except LLMError:
            diag.mark("llm_stream_error", n_chunks=n)
            raise
        except Exception as exc:
            diag.mark("llm_stream_error", n_chunks=n, detail=str(exc)[:80])
            raise LLMError(f"stream 调用失败: {_redact(str(exc), self._spec.api_key)}") from exc

    async def chat_json(self, messages: list[Message], schema: type[T]) -> T:
        text = await self.chat(messages)
        try:
            data = json.loads(extract_json(text))
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM 返回非 JSON: {text[:80]}") from exc
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise LLMError(f"LLM JSON 不合 schema: {exc.errors()[0]}") from exc


def provider_for(spec: ProviderSpec) -> OpenAICompatProvider:
    """按显式配置构造(激活验证用:不走 active 解析)。"""

    return OpenAICompatProvider(spec)


async def verify_provider(spec: ProviderSpec, *, timeout: float = 10.0) -> None:
    """激活前真实验证:对所选模型发 max_tokens=1 的最小调用。

    /models 列表只证明 key 可见该模型,调用权限/额度只有真调用能证明。
    失败抛 LLMError;调用方(路由)负责保留现状。429/5xx 也按失败处理
    (提示层区分「可重试」),不猜放行。
    """

    prov = provider_for(spec)
    await prov.chat([Message("user", "ping")], max_tokens=1, timeout=timeout)


def _ollama_base(url: str) -> str:
    """env 的 OLLAMA_URL 是 openai 兼容风格(带 /v1);litellm ollama handler
    要原生基址,剥掉尾部 /v1。"""

    u = url.rstrip("/")
    return u.removesuffix("/v1")


def get_provider() -> OpenAICompatProvider:
    """当前生效 provider:激活配置(config.ACTIVE_*,热切换只翻这几个属性)优先;
    无激活回落 .env 双源(DeepSeek/Ollama,同样走 litellm,不直连 SDK)。

    每次调用现读 config —— 激活指针翻新后,下一次调用即用新配置;
    在途请求已持有自己的 provider 对象,不受影响。
    """

    if config.ACTIVE_PROVIDER_ID:
        return provider_for(
            ProviderSpec(
                model=config.ACTIVE_MODEL,
                api_key=config.ACTIVE_API_KEY,
                base_url=config.ACTIVE_BASE_URL,
            )
        )
    if config.LLM_PROVIDER == "ollama":
        return provider_for(
            ProviderSpec(
                model=f"ollama/{config.OLLAMA_MODEL}",
                api_key="ollama",
                base_url=_ollama_base(config.OLLAMA_URL),
            )
        )
    return provider_for(
        ProviderSpec(
            model=f"deepseek/{config.DEEPSEEK_MODEL}",
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    )
