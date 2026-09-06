"""检索引擎(backend-plan §2 rag 行):Chroma + BM25 + 重排 三件套。

打分与融合 = 实现细节(本 docstring 即文档):
- 召回:向量(Chroma/bge-m3,余弦)与 BM25(jieba 分词)各取 4×k,
  RRF(K=60)融合去重
- 重排:bge-reranker-v2-m3 CrossEncoder 对 (query, question+answer) 打分,
  取 top-k;Ref.score = 重排原始分(仅排序语义,非概率)
- 查询侧 embedding 不拼指令前缀(bge-m3 为无前缀训练);文档侧同样不拼
- 重排器加载失败 → 按 RRF 序直接截断返回(降级路径,记 WARN,不致命)
- BM25 索引在 ingest 时失效、首次检索从 Chroma 回建
- 换 embedding 模型 = 重跑 ingest,代码不动(docs/data-contract.md §5)
懒加载:模型/索引首次使用才进内存(网关启动零成本);Chroma 持久化 .rag_store/。
"""

from pathlib import Path

import chromadb
import jieba
import numpy as np
from loguru import logger
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from app import config
from app.rag.corpus import Ref

_COLLECTION = "hrp_kb"
_QUERY_PREFIX = ""  # bge-m3 无检索指令前缀,清空
_RRF_K = 60
_RECALL_FACTOR = 4
_UPSERT_BATCH = 1000  # chroma 单批上限 ~5461(实测),分批写入避免超限
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
    """单实例持有模型与索引;网关单事件循环串行调用,无需加锁。"""

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._store_path = Path(store_path if store_path is not None else config.RAG_STORE_PATH)
        self._client: chromadb.ClientAPI | None = None
        self._embedder: SentenceTransformer | None = None
        self._reranker: CrossEncoder | None = None
        self._reranker_failed = False
        self._bm25: BM25Okapi | None = None
        self._bm25_refs: list[Ref] = []

    # ---- 懒初始化 ----

    def _ensure_store(self) -> chromadb.Collection:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._store_path))
        return self._client.get_or_create_collection(
            name=_COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def _ensure_embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            self._embedder = SentenceTransformer(_EMBED_MODEL)
        return self._embedder

    def _ensure_reranker(self) -> CrossEncoder | None:
        if self._reranker is None and not self._reranker_failed:
            try:
                self._reranker = CrossEncoder(_RERANK_MODEL, max_length=512)
            except Exception:  # noqa: BLE001 — 任意加载失败都降级到 RRF 序,不致命
                self._reranker_failed = True
                logger.warning("reranker 加载失败,检索按 RRF 序降级")
        return self._reranker

    def _ensure_bm25(self) -> BM25Okapi:
        if self._bm25 is None:
            collection = self._ensure_store()
            got = collection.get(include=["documents", "metadatas"])
            metas = got["metadatas"] or []
            self._bm25_refs = [
                Ref(
                    id=id_,
                    question=str(meta.get("question", "")),
                    answer=str(meta.get("answer", "")),
                    category=str(meta["category"]) if meta.get("category") else None,
                )
                for id_, meta in zip(got["ids"], metas, strict=True)
            ]
            tokens = [list(jieba.lcut(f"{r.question} {r.answer}")) for r in self._bm25_refs]
            self._bm25 = BM25Okapi(tokens if tokens else [["空"]])
        return self._bm25

    # ---- 写入 ----

    def ingest(self, refs: list[Ref], *, reset: bool = False) -> int:
        """语料灌库(upsert 按 id 幂等);reset 清空重建。返回入库条数。"""
        collection = self._ensure_store()
        if reset and self._client is not None:
            self._client.delete_collection(_COLLECTION)
            collection = self._ensure_store()
        docs = [f"{r.question}\n{r.answer}" for r in refs]
        embeddings = self._ensure_embedder().encode(docs, normalize_embeddings=True)
        # 分批 upsert:chroma 单批上限 ~5461(本环境实测),全量语料会超;分成小块写入
        batch = _UPSERT_BATCH
        for start in range(0, len(refs), batch):
            end = start + batch
            collection.upsert(
                ids=[r.id for r in refs[start:end]],
                embeddings=np.asarray(embeddings[start:end]).tolist(),
                documents=docs[start:end],
                metadatas=[
                    {"question": r.question, "answer": r.answer, "category": r.category or ""}
                    for r in refs[start:end]
                ],
            )
        self._bm25 = None  # 索引失效,下次检索回建
        return collection.count()

    # ---- 检索 ----

    def retrieve(self, query: str, k: int | None = None) -> list[Ref]:
        """混合检索 + 重排,返回带分 Ref(k=None → config.RAG_TOP_K)。"""
        top_k = k if k is not None else config.RAG_TOP_K
        collection = self._ensure_store()
        if collection.count() == 0:
            return []
        bm25 = self._ensure_bm25()
        by_id = {r.id: r for r in self._bm25_refs}

        recall_n = min(_RECALL_FACTOR * top_k, collection.count())
        vec = self._ensure_embedder().encode(
            [_QUERY_PREFIX + query], normalize_embeddings=True
        )
        vec_hits: list[str] = collection.query(
            query_embeddings=np.asarray(vec).tolist(), n_results=recall_n
        )["ids"][0]

        scores = bm25.get_scores(list(jieba.lcut(query)))
        bm25_ranked = [
            self._bm25_refs[i].id for i in np.argsort(scores)[::-1][:recall_n] if scores[i] > 0
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
