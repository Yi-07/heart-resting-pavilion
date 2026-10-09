"""retrieve 接缝钉测试(backend-plan §11):种子语料命中(id/question 稳定返回)、k 截断、双库隔离。

真模型真 Chroma(bge-m3 + bge-reranker-v2-m3 本地 backend/models/,docs/architecture/data-contract.md「入库与验证」);
session 级 fixture 只灌一次库。测试用独立种子夹具(rag_retrieve_test_seeds.jsonl,科普库),
与生产案例语料分离;另以合成 case Ref 验证案例库独立 + 两库隔离路由。
"""

import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep

import pytest

from app.rag.corpus import RagLibrary, Ref, load_corpus
from app.rag.engine import _INGEST_BUILDING, _INGEST_FAILED, RagEngine

_SEEDS = Path(__file__).resolve().parents[1] / "data" / "rag_retrieve_test_seeds.jsonl"


@pytest.fixture(scope="session")
def engine(tmp_path_factory: pytest.TempPathFactory) -> RagEngine:
    eng = RagEngine(store_path=tmp_path_factory.mktemp("rag_store"))
    eng.ingest(load_corpus(_SEEDS), library=RagLibrary.KNOWLEDGE, reset=True)
    return eng


def test_seed_question_hits_itself(engine: RagEngine):
    refs = engine.retrieve("什么是正念", k=3, library=RagLibrary.KNOWLEDGE)
    assert refs, "科普库非空却零命中"
    assert refs[0].id == "mindfulness-01"
    assert "正念" in refs[0].question  # id/question 稳定返回
    assert refs[0].answer != ""


def test_paraphrase_hits_same_category(engine: RagEngine):
    refs = engine.retrieve("晚上躺床上翻来覆去睡不着咋整", k=3, library=RagLibrary.KNOWLEDGE)
    ids = [r.id for r in refs]
    assert any(i.startswith("insomnia-") for i in ids), f"改写查询未命中睡眠类: {ids}"


def test_k_truncation(engine: RagEngine):
    refs = engine.retrieve("如何缓解焦虑", k=2, library=RagLibrary.KNOWLEDGE)
    assert len(refs) <= 2


def test_scores_sorted_desc(engine: RagEngine):
    refs = engine.retrieve("正念冥想怎么做", k=3, library=RagLibrary.KNOWLEDGE)
    scores = [r.score for r in refs]
    assert scores == sorted(scores, reverse=True)


def test_case_library_isolated(engine: RagEngine):
    """案例库独立:case 语料只落案例库;知识库不受案例污染,两库按 library 隔离检索。"""
    case_refs = [
        Ref(
            id="case001",
            question="来访者因社会比较而自我怀疑,工作没干劲,觉得比不上同事",
            answer="咨询师引导来访者关注自身优点、制定分步小目标并每日记录成就,以重建自我价值。",
            category="钦佩_工作",
        ),
        Ref(
            id="case002",
            question="来访者近月焦虑失眠、思虑过多,入睡困难",
            answer="咨询师建议做 4-7-8 呼吸、睡前离屏与固定作息,并评估焦虑触发来源。",
            category="焦虑",
        ),
    ]
    engine.ingest(case_refs, library=RagLibrary.CASE)

    stored = engine._ensure_store(RagLibrary.CASE).get(include=["documents", "metadatas"])
    assert all(
        set(metadata) <= {"category"}
        for metadata in (stored["metadatas"] or [])
    )

    refs = engine.retrieve("最近工作没干劲 觉得比别人差", k=3, library=RagLibrary.CASE)
    assert any(r.id.startswith("case") for r in refs), f"案例库未命中 case 语料: {[r.id for r in refs]}"

    # 知识库不受影响:知识查询在知识库命中科普 id
    krefs = engine.retrieve("什么是正念", k=3, library=RagLibrary.KNOWLEDGE)
    assert krefs and all(r.id.startswith("mindfulness") for r in krefs)


def test_empty_store_returns_empty(tmp_path: Path):
    eng = RagEngine(store_path=tmp_path / "empty_store")
    assert eng.retrieve("什么是正念", library=RagLibrary.KNOWLEDGE) == []


@pytest.mark.parametrize(
    ("query", "k", "message"),
    [
        ("", None, "不能为空"),
        ("   ", None, "不能为空"),
        ("正念", 0, "大于 0"),
        ("正念", -1, "大于 0"),
    ],
)
def test_retrieve_rejects_invalid_arguments(
    tmp_path: Path, query: str, k: int | None, message: str
):
    eng = RagEngine(store_path=tmp_path / "empty_store")
    with pytest.raises(ValueError, match=message):
        eng.retrieve(query, k=k, library=RagLibrary.KNOWLEDGE)


def test_bm25_initialization_is_single_flight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """to_thread 并发首次检索时,同一库的 BM25 只构建一次。"""
    engine = RagEngine(store_path=tmp_path / "rag_store")
    calls = 0

    def fake_load_bm25(_library: RagLibrary):
        return None

    def fake_load_tokens(_library: RagLibrary):
        return None

    def fake_refs(_library: RagLibrary):
        return [Ref(id="one", question="问题", answer="答案")]

    def fake_build(library: RagLibrary, refs: list[Ref], **_kwargs):
        nonlocal calls
        calls += 1
        sleep(0.01)
        marker = object()
        engine._bm25[library] = marker  # type: ignore[assignment]
        engine._bm25_refs[library] = refs
        return marker  # type: ignore[return-value]

    monkeypatch.setattr(engine, "_load_bm25_cache", fake_load_bm25)
    monkeypatch.setattr(engine, "_load_tokenized_cache", fake_load_tokens)
    monkeypatch.setattr(engine, "_refs_from_collection", fake_refs)
    monkeypatch.setattr(engine, "_build_bm25", fake_build)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: engine._ensure_bm25(RagLibrary.CASE), range(8)))

    assert calls == 1
    assert len({id(result) for result in results}) == 1


def test_bm25_cache_load_and_rebuild_chain(engine: RagEngine):
    """BM25 缓存优先,损坏时依次退回分词缓存与 Chroma。"""
    cache_dir = engine._bm25_cache_dir
    tokenized_path = cache_dir / "tokenized_docs_knowledge.pkl"
    bm25_path = cache_dir / "bm25_knowledge.pkl"
    assert tokenized_path.exists()
    assert bm25_path.exists()

    cached = RagEngine(store_path=engine._store_path)
    assert len(cached._ensure_bm25(RagLibrary.KNOWLEDGE).get_scores(["正念"])) == 15

    bm25_path.write_bytes(b"damaged bm25")
    from_tokens = RagEngine(store_path=engine._store_path)
    assert len(from_tokens._ensure_bm25(RagLibrary.KNOWLEDGE).get_scores(["正念"])) == 15
    assert bm25_path.stat().st_size > len(b"damaged bm25")

    bm25_path.write_bytes(b"damaged bm25")
    tokenized_path.write_bytes(b"damaged tokens")
    from_chroma = RagEngine(store_path=engine._store_path)
    assert len(from_chroma._ensure_bm25(RagLibrary.KNOWLEDGE).get_scores(["正念"])) == 15
    assert tokenized_path.stat().st_size > len(b"damaged tokens")
    assert bm25_path.stat().st_size > len(b"damaged bm25")


def test_bm25_cache_package_version_mismatch_rebuilds(engine: RagEngine):
    """jieba/rank-bm25 版本变化使对应缓存失效并自动重建。"""
    cache_dir = engine._bm25_cache_dir
    tokenized_path = cache_dir / "tokenized_docs_knowledge.pkl"
    bm25_path = cache_dir / "bm25_knowledge.pkl"

    tokenized = pickle.loads(tokenized_path.read_bytes())
    tokenized["metadata"]["jieba_version"] = "0.0.0"
    tokenized_path.write_bytes(pickle.dumps(tokenized))
    bm25 = pickle.loads(bm25_path.read_bytes())
    bm25["metadata"]["rank_bm25_version"] = "0.0.0"
    bm25_path.write_bytes(pickle.dumps(bm25))

    rebuilt = RagEngine(store_path=engine._store_path)
    assert len(rebuilt._ensure_bm25(RagLibrary.KNOWLEDGE).get_scores(["正念"])) == 15

    refreshed_tokens = pickle.loads(tokenized_path.read_bytes())
    refreshed_bm25 = pickle.loads(bm25_path.read_bytes())
    assert refreshed_tokens["metadata"]["jieba_version"] != "0.0.0"
    assert refreshed_bm25["metadata"]["rank_bm25_version"] != "0.0.0"


def test_ingest_keeps_original_exception_when_state_update_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """原始 ingest 异常与状态更新异常同时发生 → 最终抛出原始异常,状态停 building(fail-closed)。"""
    from loguru import logger as loguru_logger

    from app.logger import capture_events

    engine = RagEngine(store_path=tmp_path / "rag_store")
    real_set_state = engine._set_collection_state

    def fake_set_state(collection, *, status, generation):
        if status == _INGEST_FAILED:
            raise ValueError("modify failed")
        real_set_state(collection, status=status, generation=generation)

    def fail_embedder():
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(engine, "_set_collection_state", fake_set_state)
    monkeypatch.setattr(engine, "_ensure_embedder", fail_embedder)

    records = []
    handle = capture_events(lambda record: records.append(record))
    try:
        with pytest.raises(RuntimeError, match="embedding failed"):
            engine.ingest(
                [Ref(id="x", question="q", answer="a")], library=RagLibrary.KNOWLEDGE
            )
    finally:
        loguru_logger.remove(handle)

    # 状态更新失败只记脱敏 WARN,不掩盖原始异常
    assert any(r["message"] == "rag_ingest_state_update_failed" for r in records)
    # fail-closed:状态停留在 building,后续检索拒绝而非读取不完整集合
    status, _ = engine._collection_state(RagLibrary.KNOWLEDGE)
    assert status == _INGEST_BUILDING


def test_corpus_id_uniqueness_enforced(tmp_path: Path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"id": "b", "question": "q", "answer": "a"}\n'
        '{"id": "a", "question": "q", "answer": "a"}\n'
        '{"id": "b", "question": "q2", "answer": "a2"}\n'
        '{"id": "a", "question": "q2", "answer": "a2"}\n'
        '{"id": "a", "question": "q3", "answer": "a3"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"语料 id 重复: \['a', 'b'\]"):
        load_corpus(bad)


def test_corpus_parse_error_includes_line_number(tmp_path: Path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"id": "a", "question": "q", "answer": "a"}\n'
        '{"id": "b", "question": \n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"bad\.jsonl:2"):
        load_corpus(bad)


def test_ref_defaults():
    r = Ref(id="x", question="q", answer="a")
    assert r.score == 0.0
    assert r.category is None
