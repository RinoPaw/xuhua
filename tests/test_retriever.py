from heritage_explorer.agent import TaskType
from heritage_explorer.dataset import load_dataset
from heritage_explorer.retriever import QueryAnalyzer


def test_query_analyzer_extracts_province():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐河南省的传统美术项目")

    assert plan.entities.get("province") == ["河南省"]
    assert plan.metadata_filters.get("province") == "河南省"


def test_query_analyzer_extracts_category():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐河南省的传统美术项目")

    assert plan.entities.get("category") == ["传统美术"]
    assert plan.metadata_filters.get("category") == "传统美术"


def test_query_analyzer_extracts_level():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("河南有哪些国家级非遗")

    assert "国家级" in plan.entities.get("level", [])


def test_query_analyzer_extracts_count():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐3个适合校园展览的传统美术项目")

    assert plan.retrieval_count == 3


def test_query_analyzer_extracts_audience_and_scenario():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐适合中小学的校园展览项目")

    assert "audience" in plan.soft_constraints
    assert "scenario" in plan.soft_constraints


def test_query_rewrite_removes_constraint_keywords():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐3个适合校园展览的河南省传统美术项目")

    original = plan.original_query
    rewritten = plan.rewritten_query
    assert rewritten != original
    assert len(rewritten) < len(original)
    assert "河南省" not in rewritten
    assert "推荐" not in rewritten
    assert "3个" not in rewritten


def test_query_rewrite_keeps_core_semantics():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("太极拳是什么")

    assert plan.rewritten_query


def test_comparison_task_extracts_targets():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("比较太极拳和少林功夫", TaskType.COMPARISON)

    targets = plan.entities.get("comparison_targets", [])
    assert len(targets) >= 2
    assert any("太极" in t for t in targets)
    assert any("少林" in t for t in targets)


def test_comparison_task_rewritten_contains_target_names():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("比较太极拳和少林功夫", TaskType.COMPARISON)

    assert "太极" in plan.rewritten_query
    assert "少林" in plan.rewritten_query


def test_default_retrieval_count_varies_by_task_type():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    q = "太极拳"

    factual = analyzer.analyze(q, TaskType.FACTUAL_QA)
    comparison = analyzer.analyze(q, TaskType.COMPARISON)
    recommendation = analyzer.analyze(q, TaskType.RECOMMENDATION)
    data_explore = analyzer.analyze(q, TaskType.DATA_EXPLORE)

    assert factual.retrieval_count == 5
    assert comparison.retrieval_count == 8
    assert recommendation.retrieval_count == 10
    assert data_explore.retrieval_count == 20


def test_query_analyzer_handles_empty_query():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("")

    assert plan.original_query == ""
    assert plan.rewritten_query == ""


def test_query_analyzer_handles_no_entities():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("这个非遗项目有什么特色")

    assert plan.rewritten_query
    assert not plan.metadata_filters
    assert plan.retrieval_count == 5


def test_expansion_terms_are_generated():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("河南省的传统技艺", TaskType.DATA_EXPLORE)

    assert len(plan.expansion_terms) > 0
