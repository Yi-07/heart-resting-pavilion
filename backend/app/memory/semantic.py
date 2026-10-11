"""语义记忆层(spec §4 L7「语义」层;PRD docs/prds/semantic-memory.md)。

- 独立 Chroma collection(`hrp_mem_v1`),持久化 `.mem_store/`,与知识库
  .rag_store 物理分离;embedding 复用 rag engine 的常驻 bge-m3 实例,不双份驻留。
- 条目 = 检索笔记(LLM 转述非原文)+ metadata {status, session_id, turn_index,
  date};隐私红线「记忆粗摘要不存原文」延续。
- 写入:collect 回合末(done 后异步);解析笔记 LLM 输出入库,同时执行状态
  闭环(化解的旧条目回写 settled,化解条目不再召回;召回语境由调用方拼进笔记
  prompt,本模块只落库)。
- 召回:同步,查询串 = 本轮输入+热层最近话题;候选超采样 → 余弦噪声闸门
  低档(SEMANTIC_MEM_MIN_COS)→ 超期(SEMANTIC_MEM_DECAY_DAYS)折减重排 → top-k。
- 降级分两档:读写路径异常吞掉记 WARN 绝不杀回合(延续 memory/store.py 纪律);
  治理路径(list/delete/clear)异常上抛 → admin 503(治理不降级例外,同 store)。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app import config
from app import logger as app_logger

if TYPE_CHECKING:
    import chromadb
    from sentence_transformers import SentenceTransformer

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="semantic")

_COLLECTION = "hrp_mem_v1"
_ID_STEM = "m"  # 条目 id 前缀;笔记 LLM 输出的 settled 列表按此前缀过滤

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_AGE_COS_FACTOR = 0.92
"""超期条目余弦折减系数(排序级降权,不剔除——LLM 临场取舍,PRD 防线设计)"""

_RECALL_OVERSAMPLE = 3
"""召回候选超采样倍数:先取 k×N 候选,闸门/衰减后截 top-k(衰减才有重排空间)"""


def _now() -> datetime:
    return datetime.now()  # noqa: DTZ005 — 单机原型,时区即用户时区(同 store.py)


def parse_notes(raw: str) -> tuple[list[str], list[str]]:
    """解析笔记 LLM 输出 → (新笔记列表, 化解的旧条目 id 列表)。

    期望 JSON `{"new": [...], "settled": ["m..."]}`;任意偏差(非 JSON/缺字段/
    类型不符/空串)降级整段当单条新笔记,化解列表为空——内容不因解析失败丢弃。
    """

    def _fallback() -> tuple[list[str], list[str]]:
        text = raw.strip()
        return ([text] if text else [], [])

    try:
        match = _JSON_BLOCK.search(raw)
        if match is None:
            return _fallback()
        data = json.loads(match.group(0))
        news = data.get("new")
        olds = data.get("settled")
        if not isinstance(news, list) or not all(isinstance(s, str) and s.strip() for s in news):
            return _fallback()
        settled = (
            [s for s in olds if isinstance(s, str) and s.startswith(_ID_STEM)]
            if isinstance(olds, list)
            else []
        )
        return [s.strip() for s in news], settled
    except Exception:  # noqa: BLE001 — 非法 JSON 整段当单条,不丢内容
        return _fallback()


class SemanticMemory:
    """独立 Chroma collection 的语义记忆;懒加载 + 全降级纪律。"""

    def __init__(self, store_path: str, embedder: SentenceTransformer | None = None) -> None:
        self._store_path = store_path
        self._embedder = embedder
        self._client: chromadb.ClientAPI | None = None
        self._col: chromadb.Collection | None = None
        self._lock = threading.Lock()

    # ---- 懒加载 ----

    def _ensure(self) -> chromadb.Collection:
        """collection 懒加载;embedder 缺省时向 rag engine 借常驻实例(PRD 单例共享)。"""
        import chromadb

        with self._lock:
            if self._col is None:
                if self._embedder is None:
                    from app.rag.engine import get_engine

                    self._embedder = get_engine()._ensure_embedder()  # 单例共享是设计决定(PRD)
                self._client = chromadb.PersistentClient(path=self._store_path)
                self._col = self._client.get_or_create_collection(
                    _COLLECTION, metadata={"hnsw:space": "cosine"}
                )
            return self._col

    def _encode(
        self, texts: list[str]
    ) -> Any:  # 返回交给 chroma 的向量数组;宽联合钉由 np.asarray 后直接透传规避
        assert self._embedder is not None  # _ensure 已填充
        import numpy as np

        return np.asarray(self._embedder.encode(texts, show_progress_bar=False))

    # ---- 写入(同步实现;async 包装放 to_thread) ----

    def save_notes_sync(
        self,
        session_id: str,
        turn_index: int,
        notes_raw: str,
        *,
        mood_label: str | None = None,
        intensity: float | None = None,
    ) -> None:
        """解析笔记 LLM 输出入库 + 状态闭环回写。

        notes_raw = 笔记 LLM 输出(期望 JSON `{"new": [...], "settled": [id...]}`),
        解析失败整段降级当单条。mood_label/intensity = 写入时点研判情绪(Q4 schema;
        供召回侧 LLM 衡量相关性),缺失时字段省略。异常上抛,由 save_notes 记 WARN。
        """
        col = self._ensure()
        news, settled = parse_notes(notes_raw)
        capped = [n[: config.SEMANTIC_MEM_NOTE_MAX_CHARS] for n in news if n.strip()]
        if capped:
            meta: dict[str, Any] = {
                "status": "open",
                "session_id": session_id,
                "turn_index": turn_index,
                "date": _now().date().isoformat(),
            }
            if mood_label:
                meta["mood"] = mood_label
            if intensity is not None:
                meta["intensity"] = intensity
            col.upsert(
                ids=[f"{_ID_STEM}{uuid4().hex}" for _ in capped],
                documents=capped,
                embeddings=self._encode(capped),
                metadatas=[meta],
            )
        if settled:
            col.update(ids=settled, metadatas=[{"status": "settled"}] * len(settled))
        logger.info(
            "semantic_saved", notes=len(capped), settled=len(settled), turn=turn_index
        )

    async def save_notes(
        self,
        session_id: str,
        turn_index: int,
        notes_raw: str,
        *,
        mood_label: str | None = None,
        intensity: float | None = None,
    ) -> None:
        """save_notes_sync 的 async 包装:异常吞掉记 WARN,绝不杀回合。"""
        try:
            await asyncio.to_thread(
                self.save_notes_sync,
                session_id,
                turn_index,
                notes_raw,
                mood_label=mood_label,
                intensity=intensity,
            )
        except Exception as exc:  # noqa: BLE001 — 语义记忆降级:写入失败不影响回合
            logger.warning("semantic_degraded", layer="save", reason=str(exc)[:120])

    # ---- 召回 ----

    def recall_sync(self, query: str, recent_topics: str = "", k: int | None = None) -> list[dict[str, Any]]:
        """同步召回:候选超采样 → 噪声闸门 → 超期折减重排 → top-k。

        recent_topics 拼进查询串(查询增强:模糊回指靠热层话题补齐,PRD)。
        返回 [{id, text, cos, status, date, aged}],cos 为折减后值。库空返回
        空列表;异常上抛,由 recall 记 WARN。
        """
        top_k = k if k is not None else config.SEMANTIC_MEM_TOP_K
        col = self._ensure()
        total = col.count()
        if total == 0:
            return []
        full_query = f"{query} {recent_topics}".strip()
        res = col.query(
            query_embeddings=[self._encode([full_query])[0]],
            n_results=min(total, top_k * _RECALL_OVERSAMPLE),
            include=["documents", "metadatas", "distances"],
        )
        docs = res["documents"] or []
        metas = res["metadatas"] or []
        dists = res["distances"] or []
        ids = res["ids"] or []
        if not docs or not docs[0]:
            return []
        today = _now().date()
        gated: list[dict[str, Any]] = []
        for i, (doc, meta, dist) in enumerate(
            zip(docs[0], metas[0], dists[0], strict=True)
        ):
            cos = 1.0 - float(dist)
            if cos < config.SEMANTIC_MEM_MIN_COS:
                break  # cosine 降序返回,后面只会更低
            age_days = (today - date.fromisoformat(str(meta["date"]))).days
            aged = age_days > config.SEMANTIC_MEM_DECAY_DAYS
            gated.append(
                {
                    "id": ids[0][i],
                    "text": doc,
                    "cos": round(cos * (_AGE_COS_FACTOR if aged else 1.0), 3),
                    "status": str(meta["status"]),
                    "date": str(meta["date"]),
                    "aged": aged,
                }
            )
        gated.sort(key=lambda item: item["cos"], reverse=True)
        return gated[:top_k]

    async def recall(self, query: str, recent_topics: str = "", k: int | None = None) -> list[dict[str, Any]]:
        """recall_sync 的 async 包装:异常吞掉记 WARN 返回空,绝不杀回合。"""
        try:
            return await asyncio.to_thread(self.recall_sync, query, recent_topics, k)
        except Exception as exc:  # noqa: BLE001 — 语义记忆降级:召回失败返回空档
            logger.warning("semantic_degraded", layer="recall", reason=str(exc)[:120])
            return []

    # ---- 治理(异常上抛 → admin 503,不降级) ----

    def list_items(self, limit: int = 50) -> list[dict[str, Any]]:
        """治理列表(collection.get 全取,date 降序截断)。"""
        col = self._ensure()
        got = col.get(include=["documents", "metadatas"])
        docs = got["documents"] or []
        metas = got["metadatas"] or []
        items = [
            {
                "id": got["ids"][i],
                "text": doc,
                "status": str(meta.get("status", "open")),
                "date": str(meta.get("date", "")),
            }
            for i, (doc, meta) in enumerate(zip(docs, metas, strict=True))
        ]
        items.sort(key=lambda item: str(item["date"]), reverse=True)
        return items[:limit]

    def delete_items(self, ids: list[str]) -> None:
        """治理删除(单条/批量;chroma 对不存在 id 幂等)。"""
        self._ensure().delete(ids=ids)

    def clear_all(self) -> int:
        """治理一键清除:删 collection 重建空。返回删除条数(计数失败记 -1,不阻断清除)。

        刻意不走 _ensure:清除是纯 collection 操作,不得为此加载 embedder
        (治理路径零模型成本,否则 admin 测试/无模型环境会白拉 bge-m3)。
        """
        count = -1
        try:
            import chromadb

            client = chromadb.PersistentClient(path=self._store_path)
            try:
                count = client.get_collection(_COLLECTION).count()
            except Exception:  # noqa: BLE001 — collection 不存在=本来就没东西
                count = 0
            try:
                client.delete_collection(_COLLECTION)
            except Exception as exc:  # noqa: BLE001 — 删不掉如实告警,下次 _ensure 重建空库即达成清空
                logger.warning("semantic_clear_delete_failed", reason=str(exc)[:120])
        except Exception as exc:  # noqa: BLE001 — client 建不起来(store 路径异常等):清除未完成,由上层 503
            logger.warning("semantic_clear_client_failed", reason=str(exc)[:120])
        self._col = None
        self._client = None
        return count
