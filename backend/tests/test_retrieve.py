"""retrieve 接缝钉测试(backend-plan §11):种子语料命中(id/question 稳定返回)、k 截断。

真模型真 Chroma(bge-small-zh + bge-reranker 本地缓存,docs/data-contract.md §4 回验判据 2);
session 级 fixture 只灌一次库。
"""

from pathlib import Path

import pytest

from app.rag.corpus import Ref, load_corpus
from app.rag.engine import RagEngine

_SEEDS = Path(__file__).resolve().parents[1] / "data" / "rag_seeds.jsonl"


@pytest.fixture(scope="session")
def engine(tmp_path_factory: pytest.TempPathFactory) -> RagEngine:
    eng = RagEngine(store_path=tmp_path_factory.mktemp("rag_store"))
    eng.ingest(load_corpus(_SEEDS), reset=True)
    return eng


def test_seed_question_hits_itself(engine: RagEngine):
    refs = engine.retrieve("什么是正念", k=3)
    assert refs, "种子库非空却零命中"
    assert refs[0].id == "mindfulness-01"
    assert "正念" in refs[0].question  # id/question 稳定返回
    assert refs[0].answer != ""


def test_paraphrase_hits_same_category(engine: RagEngine):
    refs = engine.retrieve("晚上躺床上翻来覆去睡不着咋整", k=3)
    ids = [r.id for r in refs]
    assert any(i.startswith("insomnia-") for i in ids), f"改写查询未命中睡眠类: {ids}"


def test_k_truncation(engine: RagEngine):
    refs = engine.retrieve("如何缓解焦虑", k=2)
    assert len(refs) <= 2


def test_scores_sorted_desc(engine: RagEngine):
    refs = engine.retrieve("正念冥想怎么做", k=3)
    scores = [r.score for r in refs]
    assert scores == sorted(scores, reverse=True)


def test_empty_store_returns_empty(tmp_path: Path):
    eng = RagEngine(store_path=tmp_path / "empty_store")
    assert eng.retrieve("什么是正念") == []


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
