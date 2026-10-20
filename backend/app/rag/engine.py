"""检索引擎(backend-plan §2 rag 行):混合知识库,Chroma + BM25 + 重排 三件套。

深模块:对外接口小(retrieve/ingest + 一个 RagLibrary 库种类),复杂藏在模块内——
两库、各库召回/融合/重排/分批、Chroma 持久化与 BM25 回建,全由本模块承担,调用方零感知。

库结构(拆两 Chroma 集合,混合知识库):
- hrp_kb_knowledge 科普知识库:CASE 之外的知识问答(question=知识问,answer=科普答),answer 直答用
- hrp_kb_case 案例库:CASE 型治疗思路(question=来访者问题,answer=治疗思路),collect/station 用

打分与融合 = 实现细节:
- 召回:向量(Chroma/bge-m3,余弦)与 BM25(jieba 分词)各取 4×k,RRF(K=60)融合去重
- 重排:bge-reranker-v2-m3 CrossEncoder 对 (query, question+answer) 打分,取 top-k;
  Ref.score = 重排原始分(仅排序语义,非概率)
- 查询侧 embedding 不拼指令前缀(bge-m3 为无前缀训练);文档侧同样不拼
- 重排器加载失败 → 按 RRF 序直接截断返回(降级路径,记 WARN,不致命)
- BM25 索引按库持久化到 .rag_store/bm25/;ingest 后立即重建,缓存缺失/损坏时回建
- 换 embedding 模型 = 重跑 ingest,代码不动(docs/architecture/data-contract.md「变更流程」)
懒加载:重库(chroma/jieba/numpy/bm25/sentence-transformers)与模型/索引首次使用才
import/进内存——模块顶部零重依赖(§5.6,启动零成本);Chroma 持久化 .rag_store/。
"""

from __future__ import annotations

import os
import pickle
import tempfile
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app import config
from app.rag.corpus import RagLibrary, Ref

if TYPE_CHECKING:
    import chromadb
    from rank_bm25 import BM25Okapi
    from sentence_transformers import CrossEncoder, SentenceTransformer

_COLLECTIONS: dict[RagLibrary, str] = {
    RagLibrary.KNOWLEDGE: "hrp_kb_knowledge",
    RagLibrary.CASE: "hrp_kb_case",
}
_LEGACY_COLLECTION = "hrp_kb"  # 旧单库名;重置时兜底清理(自单库迁移残留)
_QUERY_PREFIX = ""  # bge-m3 无检索指令前缀,清空
_RRF_K = 60
_RECALL_FACTOR = 4
_UPSERT_BATCH = 1000  # chroma 单批上限 ~5461(实测),分批写入避免超限
_CACHE_FORMAT_VERSION = 1
_INGEST_STATUS_KEY = "hrp_ingest_status"
_INGEST_GENERATION_KEY = "hrp_ingest_generation"
_INGEST_READY = "ready"
_INGEST_BUILDING = "building"
_INGEST_FAILED = "failed"
_RERANK_MODEL = config.RAG_RERANK_MODEL
_EMBED_MODEL = config.RAG_EMBED_MODEL


def _rrf_fuse(*ranklists: list[str], k: int) -> dict[str, float]:
    """Reciprocal Rank Fusion:多路召回按名次融合成单一分。"""
    scores: dict[str, float] = {}
    for ranklist in ranklists:
        for rank, doc_id in enumerate(ranklist, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


class RagEngine:
    """单实例持有模型与索引;懒加载状态由锁保护,检索计算保持并发。

    library 参数(可选,默认 case)区分混合知识库里查哪一库;两库各自独立 count/BM25。
    """

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._store_path = Path(store_path if store_path is not None else config.RAG_STORE_PATH)
        self._client: chromadb.ClientAPI | None = None
        self._embedder: SentenceTransformer | None = None
        self._reranker: CrossEncoder | None = None
        self._reranker_failed = False
        self._bm25: dict[RagLibrary, BM25Okapi] = {}
        self._bm25_refs: dict[RagLibrary, list[Ref]] = {}
        self._bm25_generations: dict[RagLibrary, str] = {}
        self._state_lock = threading.RLock()

    @property
    def _bm25_cache_dir(self) -> Path:
        """BM25 缓存固定在当前 RAG store 内,测试可用独立 store 隔离。"""
        return self._store_path / "bm25"

    def _cache_path(self, library: RagLibrary, kind: str) -> Path:
        return self._bm25_cache_dir / f"{kind}_{library.value}.pkl"

    def _trusted_cache_path(self, path: Path, *, create: bool = False) -> Path | None:
        """只允许从本地 store 下的非符号链接 BM25 目录读写 pickle。"""
        try:
            if self._store_path.is_symlink():
                return None
            store = self._store_path.resolve()
            if store.anchor.startswith(("\\\\", "//")):
                return None
            cache_dir = store / "bm25"
            if cache_dir.exists() and cache_dir.is_symlink():
                return None
            if create:
                cache_dir.mkdir(parents=True, exist_ok=True)
            if not cache_dir.is_dir():
                return None
            target = cache_dir / path.name
            if target.exists() and target.is_symlink():
                return None
            return target
        except OSError:
            return None

    def _load_pickle(self, path: Path) -> object | None:
        trusted_path = self._trusted_cache_path(path)
        if trusted_path is None or not trusted_path.exists():
            return None
        try:
            with trusted_path.open("rb") as handle:
                return pickle.load(handle)
        except Exception as exc:  # noqa: BLE001 — 任意缓存损坏都走回建
            logger.warning(
                "rag_bm25_cache_invalid", path=str(trusted_path), reason=type(exc).__name__
            )
            return None

    @staticmethod
    def _package_versions() -> dict[str, str]:
        from importlib.metadata import PackageNotFoundError, version

        def package_version(distribution: str) -> str:
            try:
                return version(distribution)
            except PackageNotFoundError:
                return "unknown"

        return {
            "jieba_version": package_version("jieba"),
            "rank_bm25_version": package_version("rank-bm25"),
        }

    @classmethod
    def _cache_metadata_matches(
        cls, payload: object, expected: dict[str, str], required: tuple[str, ...]
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        metadata = payload.get("metadata")
        return isinstance(metadata, dict) and all(
            metadata.get(key) == expected[key] for key in required
        )

    def _write_pickle(self, path: Path, payload: object) -> None:
        """临时文件写完再替换,避免进程中断留下半份缓存。"""
        trusted_path = self._trusted_cache_path(path, create=True)
        if trusted_path is None:
            raise RuntimeError("BM25 缓存路径不在可信本地目录")
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=trusted_path.parent, prefix=f".{trusted_path.name}.", delete=False
            ) as handle:
                temp_name = handle.name
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, trusted_path)
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    @staticmethod
    def _refs_from_payload(payload: object) -> list[Ref] | None:
        if not isinstance(payload, dict) or payload.get("version") != _CACHE_FORMAT_VERSION:
            return None
        raw_refs = payload.get("refs")
        if not isinstance(raw_refs, list):
            return None
        try:
            return [Ref.model_validate(raw_ref) for raw_ref in raw_refs]
        except (TypeError, ValueError):
            return None

    def _collection_state(self, library: RagLibrary) -> tuple[str, str]:
        collection = self._ensure_store(library)
        metadata = collection.metadata or {}
        return (
            str(metadata.get(_INGEST_STATUS_KEY, _INGEST_READY)),
            str(metadata.get(_INGEST_GENERATION_KEY, "")),
        )

    @staticmethod
    def _set_collection_state(
        collection: chromadb.Collection, *, status: str, generation: str
    ) -> None:
        # metadata 整体替换:hnsw:space 不可重申(chroma 禁改 distance),
        # 须先 pop 再写——实测度量不受影响(建库时已定,存 hnsw 段不存 metadata)。
        metadata = dict(collection.metadata or {})
        metadata.pop("hnsw:space", None)
        metadata[_INGEST_STATUS_KEY] = status
        metadata[_INGEST_GENERATION_KEY] = generation
        collection.modify(metadata=metadata)

    def _load_bm25_cache(self, library: RagLibrary) -> BM25Okapi | None:
        payload = self._load_pickle(self._cache_path(library, "bm25"))
        versions = self._package_versions()
        _, generation = self._collection_state(library)
        versions["collection_generation"] = generation
        if not self._cache_metadata_matches(
            payload, versions, ("jieba_version", "rank_bm25_version", "collection_generation")
        ):
            return None
        refs = self._refs_from_payload(payload)
        if refs is None or not isinstance(payload, dict):
            return None
        bm25 = payload.get("bm25")
        if bm25 is None or not callable(getattr(bm25, "get_scores", None)):
            return None
        self._bm25_refs[library] = refs
        return bm25

    def _load_tokenized_cache(
        self, library: RagLibrary
    ) -> tuple[list[Ref], list[list[str]]] | None:
        payload = self._load_pickle(self._cache_path(library, "tokenized_docs"))
        versions = self._package_versions()
        _, generation = self._collection_state(library)
        versions["collection_generation"] = generation
        if not self._cache_metadata_matches(
            payload, versions, ("jieba_version", "collection_generation")
        ):
            return None
        refs = self._refs_from_payload(payload)
        if refs is None or not isinstance(payload, dict):
            return None
        tokens = payload.get("tokens")
        if not isinstance(tokens, list) or len(tokens) != len(refs):
            return None
        if not all(isinstance(doc_tokens, list) for doc_tokens in tokens):
            return None
        return refs, tokens

    def _persist_bm25(
        self, library: RagLibrary, refs: list[Ref], tokens: list[list[str]], bm25: BM25Okapi
    ) -> None:
        ref_payload = [ref.model_dump() for ref in refs]
        versions = self._package_versions()
        _, generation = self._collection_state(library)
        versions["collection_generation"] = generation
        self._write_pickle(
            self._cache_path(library, "tokenized_docs"),
            {
                "version": _CACHE_FORMAT_VERSION,
                "metadata": {
                    "jieba_version": versions["jieba_version"],
                    "collection_generation": versions["collection_generation"],
                },
                "refs": ref_payload,
                "tokens": tokens,
            },
        )
        self._write_pickle(
            self._cache_path(library, "bm25"),
            {
                "version": _CACHE_FORMAT_VERSION,
                "metadata": versions,
                "refs": ref_payload,
                "bm25": bm25,
            },
        )

    def _refs_from_collection(self, library: RagLibrary) -> list[Ref]:
        collection = self._ensure_store(library)
        got = collection.get(include=["documents", "metadatas"])
        docs = got["documents"] or []
        metas = got["metadatas"] or []
        refs: list[Ref] = []
        for id_, doc, meta in zip(got["ids"], docs, metas, strict=True):
            question, separator, answer = str(doc).partition("\n")
            if not separator:
                # 兼容旧库:旧版本曾把 question/answer 重复写入 metadata。
                question = str(meta.get("question", ""))
                answer = str(meta.get("answer", ""))
            refs.append(
                Ref(
                    id=id_,
                    question=question,
                    answer=answer,
                    category=str(meta["category"]) if meta.get("category") else None,
                )
            )
        return refs

    def _build_bm25(
        self,
        library: RagLibrary,
        refs: list[Ref],
        *,
        tokens: list[list[str]] | None = None,
        persist: bool = True,
    ) -> BM25Okapi:
        import jieba
        from rank_bm25 import BM25Okapi

        with self._state_lock:
            tokenized = tokens or [
                list(jieba.lcut(f"{ref.question} {ref.answer}")) for ref in refs
            ]
            bm25 = BM25Okapi(tokenized if tokenized else [["空"]])
            self._bm25_refs[library] = refs
            self._bm25[library] = bm25
            self._bm25_generations[library] = self._collection_state(library)[1]
            if persist:
                try:
                    self._persist_bm25(library, refs, tokenized, bm25)
                except Exception as exc:  # noqa: BLE001 — 缓存失败不影响内存检索
                    logger.warning(
                        "rag_bm25_cache_write_failed",
                        library=library.value,
                        reason=type(exc).__name__,
                    )
            return bm25

    # ---- 懒初始化 ----

    def _ensure_store(self, library: RagLibrary) -> chromadb.Collection:
        import chromadb  # 重库函数内懒加载(§5.6);类型标注走 TYPE_CHECKING

        with self._state_lock:
            if self._client is None:
                self._client = chromadb.PersistentClient(path=str(self._store_path))
            return self._client.get_or_create_collection(
                name=_COLLECTIONS[library], metadata={"hnsw:space": "cosine"}
            )

    def _ensure_embedder(self) -> SentenceTransformer:
        from sentence_transformers import SentenceTransformer

        with self._state_lock:
            if self._embedder is None:
                self._embedder = SentenceTransformer(_EMBED_MODEL)
            return self._embedder

    def _ensure_reranker(self) -> CrossEncoder | None:
        from sentence_transformers import CrossEncoder

        with self._state_lock:
            if self._reranker is None and not self._reranker_failed:
                try:
                    # 设备由 config.RAG_RERANK_DEVICE 决定；留空则沿用 sentence-transformers 自选
                    kwargs: dict[str, str | int] = {"max_length": 512}
                    if config.RAG_RERANK_DEVICE:
                        kwargs["device"] = config.RAG_RERANK_DEVICE
                    self._reranker = CrossEncoder(_RERANK_MODEL, **kwargs)
                except Exception:  # noqa: BLE001 — 任意加载失败都降级到 RRF 序,不致命
                    self._reranker_failed = True
                    logger.warning("reranker 加载失败,检索按 RRF 序降级")
            return self._reranker

    def _ensure_bm25(self, library: RagLibrary) -> BM25Okapi:
        with self._state_lock:
            status, generation = self._collection_state(library)
            if status != _INGEST_READY:
                raise RuntimeError(f"RAG collection is not ready: {status}")
            if (
                library in self._bm25
                and self._bm25_generations.get(library) == generation
            ):
                return self._bm25[library]

            self._bm25.pop(library, None)
            self._bm25_refs.pop(library, None)
            self._bm25_generations.pop(library, None)

            cached = self._load_bm25_cache(library)
            if cached is not None:
                self._bm25[library] = cached
                self._bm25_generations[library] = generation
                return cached

            cached_tokens = self._load_tokenized_cache(library)
            if cached_tokens is not None:
                refs, tokens = cached_tokens
                built = self._build_bm25(library, refs, tokens=tokens)
                self._bm25_generations[library] = generation
                return built

            refs = self._refs_from_collection(library)
            built = self._build_bm25(library, refs)
            self._bm25_generations[library] = generation
            return built

    # ---- 写入 ----

    def ingest(self, refs: list[Ref], *, library: RagLibrary, reset: bool = False) -> int:
        """语料按库灌入(upsert 按 id 幂等);reset 清空该库重建。返回该库入库条数。"""
        import numpy as np
        from chromadb.errors import NotFoundError

        collection = self._ensure_store(library)
        if reset and self._client is not None:
            self._client.delete_collection(_COLLECTIONS[library])
            try:  # 兜底清旧单库名(自单库迁移残留;不存在时 chroma 抛 NotFoundError/ValueError)
                self._client.delete_collection(_LEGACY_COLLECTION)
            except (NotFoundError, ValueError):
                pass
            collection = self._ensure_store(library)
        generation = uuid.uuid4().hex
        with self._state_lock:
            self._set_collection_state(
                collection, status=_INGEST_BUILDING, generation=generation
            )
        docs = [f"{r.question}\n{r.answer}" for r in refs]
        try:
            embeddings = self._ensure_embedder().encode(docs, normalize_embeddings=True)
            # 分批 upsert:chroma 单批上限 ~5461(本环境实测),全量语料会超;分成小块写入
            batch = _UPSERT_BATCH
            for start in range(0, len(refs), batch):
                end = start + batch
                collection.upsert(
                    ids=[r.id for r in refs[start:end]],
                    embeddings=np.asarray(embeddings[start:end]).tolist(),
                    documents=docs[start:end],
                    metadatas=[{"category": r.category or ""} for r in refs[start:end]],
                )
        except Exception:
            try:
                with self._state_lock:
                    self._set_collection_state(
                        collection, status=_INGEST_FAILED, generation=generation
                    )
            except Exception as state_exc:  # noqa: BLE001 — 状态更新失败只记 WARN,不得覆盖原始 ingest 异常
                logger.warning(
                    "rag_ingest_state_update_failed",
                    library=library.value,
                    reason=type(state_exc).__name__,
                )
            raise
        with self._state_lock:
            self._set_collection_state(
                collection, status=_INGEST_READY, generation=generation
            )
        with self._state_lock:
            self._bm25.pop(library, None)
            self._bm25_refs.pop(library, None)
            self._bm25_generations.pop(library, None)
            try:
                self._build_bm25(library, self._refs_from_collection(library))
            except Exception as exc:  # noqa: BLE001 — BM25 缓存失败不影响入库结果
                logger.warning(
                    "rag_bm25_rebuild_failed",
                    library=library.value,
                    reason=type(exc).__name__,
                )
        return collection.count()

    # ---- 检索 ----

    def retrieve(self, query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE) -> list[Ref]:
        """混合检索 + 重排,返回带分 Ref(k=None → config.RAG_TOP_K);library 指定查哪一库。"""
        import jieba
        import numpy as np

        query = query.strip()
        if not query:
            raise ValueError("检索 query 不能为空")
        if k is not None and k <= 0:
            raise ValueError("检索 k 必须大于 0")
        top_k = k if k is not None else config.RAG_TOP_K
        collection = self._ensure_store(library)
        status, _ = self._collection_state(library)
        if status != _INGEST_READY:
            raise RuntimeError(f"RAG collection is not ready: {status}")
        if collection.count() == 0:
            return []
        bm25 = self._ensure_bm25(library)  # 先建索引(填充 _bm25_refs[library]),再读 refs
        refs = self._bm25_refs[library]
        by_id = {r.id: r for r in refs}

        recall_n = min(_RECALL_FACTOR * top_k, collection.count())
        vec = self._ensure_embedder().encode(
            [_QUERY_PREFIX + query], normalize_embeddings=True
        )
        vec_hits: list[str] = collection.query(
            query_embeddings=np.asarray(vec).tolist(), n_results=recall_n
        )["ids"][0]

        scores = bm25.get_scores(list(jieba.lcut(query)))
        bm25_ranked = [
            refs[i].id for i in np.argsort(scores)[::-1][:recall_n] if scores[i] > 0
        ]

        fused = _rrf_fuse(vec_hits, bm25_ranked, k=_RRF_K)
        candidates = sorted(fused, key=lambda c: fused[c], reverse=True)

        reranker = self._ensure_reranker()
        if reranker is None or not candidates:
            return [by_id[c].model_copy(update={"score": fused[c]}) for c in candidates[:top_k]]
        pairs = [(query, f"{by_id[c].question}\n{by_id[c].answer}") for c in candidates]
        ce_scores = reranker.predict(pairs)
        ranked = sorted(zip(candidates, ce_scores, strict=True), key=lambda p: p[1], reverse=True)
        return [by_id[c].model_copy(update={"score": float(s)}) for c, s in ranked[:top_k]]


_engine: RagEngine | None = None


def get_engine() -> RagEngine:
    """进程级单例(懒构造;测试用独立 store 时自行 new RagEngine)。"""
    global _engine
    if _engine is None:
        _engine = RagEngine()
    return _engine
