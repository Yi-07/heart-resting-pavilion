"""retrieve 接缝钉测试(backend-plan §11):种子语料命中(id/question 稳定返回)、k 截断、双库隔离。

真模型真 Chroma(bge-m3 + bge-reranker-v2-m3 本地 backend/models/,docs/data-contract.md §4 回验判据 2);
session 级 fixture 只灌一次库。测试用独立种子夹具(rag_retrieve_test_seeds.jsonl,科普库),
与生产案例语料分离;另以合成 case Ref 验证案例库独立 + 两库隔离路由。
"""

from pathlib import Path

import pytest

from app.rag.corpus import RagLibrary, Ref, load_corpus
from app.rag.engine import RagEngine

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

    refs = engine.retrieve("最近工作没干劲 觉得比别人差", k=3, library=RagLibrary.CASE)
    assert any(r.id.startswith("case") for r in refs), f"案例库未命中 case 语料: {[r.id for r in refs]}"

    # 知识库不受影响:知识查询在知识库命中科普 id
    krefs = engine.retrieve("什么是正念", k=3, library=RagLibrary.KNOWLEDGE)
    assert krefs and all(r.id.startswith("mindfulness") for r in krefs)


def test_empty_store_returns_empty(tmp_path: Path):
    eng = RagEngine(store_path=tmp_path / "empty_store")
    assert eng.retrieve("什么是正念", library=RagLibrary.KNOWLEDGE) == []


def test_corpus_id_uniqueness_enforced(tmp_path: Path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"id": "a", "question": "q", "answer": "a"}\n'
        '{"id": "a", "question": "q2", "answer": "a2"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="id 重复"):
        load_corpus(bad)


def test_ref_defaults():
    r = Ref(id="x", question="q", answer="a")
    assert r.score == 0.0
    assert r.category is None
