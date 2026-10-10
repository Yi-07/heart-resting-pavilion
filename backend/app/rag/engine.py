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
- BM25 索引按库在 ingest 时失效、首次检索从对应 Chroma 回建
- 换 embedding 模型 = 重跑 ingest,代码不动(docs/data-contract.md §5)
懒加载:重库(chroma/jieba/numpy/bm25/sentence-transformers)与模型/索引首次使用才
import/进内存——模块顶部零重依赖(§5.6,启动零成本);Chroma 持久化 .rag_store/。
"""

from __future__ import annotations

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
    """单实例持有模型与索引;网关单事件循环串行调用,无需加锁。

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

    # ---- 懒初始化 ----

    def _ensure_store(self, library: RagLibrary) -> chromadb.Collection:
        import chromadb  # 重库函数内懒加载(§5.6);类型标注走 TYPE_CHECKING

        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._store_path))
        return self._client.get_or_create_collection(
            name=_COLLECTIONS[library], metadata={"hnsw:space": "cosine"}
        )

    def _ensure_embedder(self) -> SentenceTransformer:
        from sentence_transformers import SentenceTransformer

        if self._embedder is None:
            self._embedder = SentenceTransformer(_EMBED_MODEL, device="cuda")
        return self._embedder

    def _ensure_reranker(self) -> CrossEncoder | None:
        from sentence_transformers import CrossEncoder

        if self._reranker is None and not self._reranker_failed:
            try:
                self._reranker = CrossEncoder(_RERANK_MODEL, max_length=512, device="cuda")
            except Exception:  # noqa: BLE001 — 任意加载失败都降级到 RRF 序,不致命
                self._reranker_failed = True
                logger.warning("reranker 加载失败,检索按 RRF 序降级")
        return self._reranker

    def _ensure_bm25(self, library: RagLibrary) -> BM25Okapi:
        import jieba
        from rank_bm25 import BM25Okapi

        if library not in self._bm25:
            collection = self._ensure_store(library)
            got = collection.get(include=["documents", "metadatas"])
            metas = got["metadatas"] or []
            self._bm25_refs[library] = [
                Ref(
                    id=id_,
                    question=str(meta.get("question", "")),
                    answer=str(meta.get("answer", "")),
                    category=str(meta["category"]) if meta.get("category") else None,
                )
                for id_, meta in zip(got["ids"], metas, strict=True)
            ]
            tokens = [list(jieba.lcut(f"{r.question} {r.answer}")) for r in self._bm25_refs[library]]
            self._bm25[library] = BM25Okapi(tokens if tokens else [["空"]])
        return self._bm25[library]

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
        self._bm25.pop(library, None)  # 该库索引失效,下次检索回建
        return collection.count()

    # ---- 检索 ----

    def retrieve(self, query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE) -> list[Ref]:
        """混合检索 + 重排,返回带分 Ref(k=None → config.RAG_TOP_K);library 指定查哪一库。"""
        import jieba
        import numpy as np

        from app import diag

        diag.mark("eng_enter", library=library.value, q_len=len(query), k=k)
        top_k = k if k is not None else config.RAG_TOP_K
        collection = self._ensure_store(library)
        n_docs = collection.count()
        diag.mark("eng_store", n_docs=n_docs)
        if n_docs == 0:
            return []
        bm25 = self._ensure_bm25(library)  # 先建索引(填充 _bm25_refs[library]),再读 refs
        diag.mark("eng_bm25_ready", cached=library in self._bm25)
        refs = self._bm25_refs[library]
        by_id = {r.id: r for r in refs}

        recall_n = min(_RECALL_FACTOR * top_k, n_docs)
        vec = self._ensure_embedder().encode(
            [_QUERY_PREFIX + query], normalize_embeddings=True
        )
        diag.mark("eng_embed_done", dim=len(vec[0]))
        vec_hits: list[str] = collection.query(
            query_embeddings=np.asarray(vec).tolist(), n_results=recall_n
        )["ids"][0]
        diag.mark("eng_chroma_done", recall_n=recall_n, hits=len(vec_hits))

        scores = bm25.get_scores(list(jieba.lcut(query)))
        bm25_ranked = [
            refs[i].id for i in np.argsort(scores)[::-1][:recall_n] if scores[i] > 0
        ]
        diag.mark("eng_bm25_score_done", hits=len(bm25_ranked))

        fused = _rrf_fuse(vec_hits, bm25_ranked, k=_RRF_K)
        candidates = sorted(fused, key=lambda c: fused[c], reverse=True)
        diag.mark("eng_fused", candidates=len(candidates))

        reranker = self._ensure_reranker()
        if reranker is None or not candidates:
            diag.mark("eng_done", reranked=False, n=len(candidates[:top_k]))
            return [by_id[c].model_copy(update={"score": fused[c]}) for c in candidates[:top_k]]
        pairs = [(query, f"{by_id[c].question}\n{by_id[c].answer}") for c in candidates]
        ce_scores = reranker.predict(pairs)
        diag.mark("eng_rerank_done", pairs=len(pairs))
        ranked = sorted(zip(candidates, ce_scores, strict=True), key=lambda p: p[1], reverse=True)
        diag.mark("eng_done", reranked=True, n=len(ranked[:top_k]))
        return [by_id[c].model_copy(update={"score": float(s)}) for c, s in ranked[:top_k]]


_engine: RagEngine | None = None


def get_engine() -> RagEngine:
    """进程级单例(懒构造;测试用独立 store 时自行 new RagEngine)。"""
    global _engine
    if _engine is None:
        _engine = RagEngine()
    return _engine
