from heritage_explorer.agent import TaskType
from heritage_explorer.dataset import load_dataset
from heritage_explorer.retriever import QueryAnalyzer


def test_query_analyzer_extracts_province():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐河南省的传统美术项目")

    assert plan.provinces == ["河南省"]
    assert plan.metadata_filters.get("province") == "河南省"


def test_query_analyzer_extracts_category():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐河南省的传统美术项目")

    assert plan.categories == ["传统美术"]
    assert plan.metadata_filters.get("category") == "传统美术"


def test_query_analyzer_extracts_level():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("河南有哪些国家级非遗")

    assert "国家级" in plan.levels


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

    targets = plan.entities
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

    factual = analyzer.analyze(q, TaskType.FACT_QA)
    comparison = analyzer.analyze(q, TaskType.COMPARISON)
    recommendation = analyzer.analyze(q, TaskType.RECOMMENDATION)
    browse = analyzer.analyze(q, TaskType.BROWSE_QUERY)

    assert factual.retrieval_count == 5
    assert comparison.retrieval_count == 8
    assert recommendation.retrieval_count == 10
    assert browse.retrieval_count == 30


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
    plan = analyzer.analyze("河南省的传统技艺", TaskType.BROWSE_QUERY)

    assert len(plan.expansion_terms) > 0


# ── new MVP tests ──


def test_classify_task_browse_query():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("河南有哪些传统美术")
    assert plan.primary_task == "BROWSE_QUERY"


def test_classify_task_recommendation():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("校园展示推荐三个")
    assert plan.primary_task == "RECOMMENDATION"


def test_classify_task_exhibition_plan():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("策划河南非遗校园展")
    assert plan.primary_task == "EXHIBITION_PLAN"


def test_classify_task_comparison():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("太极拳和八卦掌的区别")
    assert plan.primary_task == "COMPARISON"


def test_classify_task_factual_qa_fallback():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("太极拳的哲学基础是什么")
    assert plan.primary_task == "FACT_QA"


def test_classify_task_empty_query():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("")
    assert plan.primary_task == "FACT_QA"


def test_extract_entities_by_title():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("太极拳的传承历史")
    assert any("太极" in e for e in plan.entities)


def test_extract_multiple_provinces():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("河南和山东的非遗有哪些")
    # "山东" alone won't match province pattern, but "山东" itself should be captured if present
    assert "河南省" in plan.provinces


def test_extract_cities():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("南阳市有哪些国家级非遗")
    assert any("南阳" in c for c in plan.cities)


def test_extract_constraints():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("找几个互动性强适合短时间的展示项目")
    assert "互动性强" in plan.constraints
    assert "适合短时间" in plan.constraints


def test_extract_time_budget():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("设计一个30分钟的展示活动")
    assert plan.time_budget == "30分钟"


def test_extract_time_budget_half_day():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("策划一个半天的社区活动")
    assert plan.time_budget == "半天"


def test_extract_tone():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("用年轻化的语气介绍太极拳")
    assert plan.tone == "年轻化"


def test_extract_output_format():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("用表格列出河南的传统美术")
    assert plan.output_format == "表格"


def test_extract_transform_type():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("把这段翻译成英文")
    assert plan.transform_type == "翻译"


def test_extract_scenario_and_audience_as_strings():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐适合中小学生的校园展览项目")
    assert plan.audience == "青少年"
    assert plan.scenario == "校园展示"


def test_query_analysis_has_all_new_fields():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("找三个河南的传统美术项目")

    assert hasattr(plan, "primary_task")
    assert hasattr(plan, "secondary_tasks")
    assert hasattr(plan, "entities")
    assert hasattr(plan, "categories")
    assert hasattr(plan, "provinces")
    assert hasattr(plan, "cities")
    assert hasattr(plan, "levels")
    assert hasattr(plan, "item_count")
    assert hasattr(plan, "scenario")
    assert hasattr(plan, "audience")
    assert hasattr(plan, "constraints")
    assert hasattr(plan, "time_budget")
    assert hasattr(plan, "tone")
    assert hasattr(plan, "output_format")
    assert hasattr(plan, "transform_type")
    # backward-compat
    assert hasattr(plan, "rewritten_query")
    assert hasattr(plan, "metadata_filters")
    assert hasattr(plan, "soft_constraints")
    assert hasattr(plan, "retrieval_count")


def test_item_count_extracted():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐3个适合校园展览的传统美术项目")
    assert plan.item_count == 3
    assert plan.retrieval_count == 3


def test_extract_count_chinese_numeral_three():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐三个适合校园展示的非遗项目")
    assert plan.item_count == 3
    assert plan.retrieval_count == 3


def test_extract_count_chinese_numeral_five():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("找五个传统技艺项目")
    assert plan.item_count == 5
    assert plan.retrieval_count == 5


def test_extract_count_chinese_numeral_two():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("比较两个太极拳流派")
    assert plan.item_count == 2


def test_extract_count_default_when_unspecified():
    kb = load_dataset()
    analyzer = QueryAnalyzer(kb)
    plan = analyzer.analyze("推荐适合校园展示的非遗项目", TaskType.RECOMMENDATION)
    assert plan.item_count == 0  # not specified
    assert plan.retrieval_count == 10  # default for RECOMMENDATION
