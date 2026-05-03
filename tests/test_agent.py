from heritage_explorer.agent import (
    Agent,
    IntentRouter,
    TaskType,
    _TASK_CONFIGS,
    task_type_from_str,
    task_type_label,
)


def test_all_task_types_have_configs():
    for task_type in TaskType:
        assert task_type in _TASK_CONFIGS


def test_intent_router_classifies_factual_qa():
    router = IntentRouter()
    task_type, confidence = router.classify("太极拳是什么")
    assert task_type is TaskType.FACTUAL_QA
    assert confidence >= 0.5


def test_intent_router_classifies_comparison():
    router = IntentRouter()
    queries = [
        "比较太极拳和少林功夫",
        "太极拳和少林功夫有什么区别",
        "对比朱仙镇木版年画与登封木版年画",
        "罗山皮影戏和南阳烙画哪个更适合校园展览",
        "太极拳 vs 少林功夫",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.COMPARISON, f"query={q!r} got {task_type}"


def test_intent_router_classifies_recommendation():
    router = IntentRouter()
    queries = [
        "推荐3个适合校园展览的传统美术项目",
        "哪些非遗项目适合在中小学推广",
        "帮我找适合社区活动的传统音乐项目",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.RECOMMENDATION, f"query={q!r} got {task_type}"


def test_intent_router_classifies_exhibition_plan():
    router = IntentRouter()
    queries = [
        "设计一个关于中药的校园展览",
        "为太极拳做一个展板文案",
        "策划一个传统技艺的展示方案",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.EXHIBITION_PLAN, f"query={q!r} got {task_type}"


def test_intent_router_classifies_curriculum_design():
    router = IntentRouter()
    queries = [
        "为太极拳设计一份研学教案",
        "给小学生上一堂关于南阳烙画的课",
        "设计一个非遗手工课程",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.CURRICULUM_DESIGN, f"query={q!r} got {task_type}"


def test_intent_router_classifies_creative_brief():
    router = IntentRouter()
    queries = [
        "基于南阳烙画设计文创产品",
        "为朱仙镇木版年画设计纹样和包装",
        "做一个非遗IP联名方案",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.CREATIVE_BRIEF, f"query={q!r} got {task_type}"


def test_intent_router_classifies_data_explore():
    router = IntentRouter()
    queries = [
        "河南有哪些国家级非遗项目",
        "列出所有的传统技艺",
        "一共有多少个民俗类项目",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.DATA_EXPLORE, f"query={q!r} got {task_type}"


def test_intent_router_classifies_multi_filter():
    router = IntentRouter()
    queries = [
        "筛选出河南省的国家级传统美术项目",
        "只看省级的非遗",
        "只要南阳市的项目",
    ]
    for q in queries:
        task_type, conf = router.classify(q)
        assert task_type is TaskType.MULTI_FILTER, f"query={q!r} got {task_type}"


def test_agent_dispatch_returns_task_result():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("太极拳是什么")

    assert result.task_type is TaskType.FACTUAL_QA
    assert result.answer
    assert result.speech
    assert result.mode
    assert result.confidence
    assert isinstance(result.sources, list)


def test_agent_dispatch_handles_comparison_intent():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("比较太极拳和少林功夫")

    assert result.task_type is TaskType.COMPARISON
    assert result.answer
    assert len(result.sources) >= 1


def test_agent_dispatch_handles_empty_query():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("")

    assert result.mode == "empty"
    assert result.speech == "请先输入问题。"
    assert result.sources == []


def test_task_type_label_returns_chinese():
    assert task_type_label(TaskType.FACTUAL_QA) == "事实问答"
    assert task_type_label(TaskType.COMPARISON) == "项目对比"
    assert task_type_label(TaskType.RECOMMENDATION) == "项目推荐"


def test_task_type_from_str():
    assert task_type_from_str("factual_qa") is TaskType.FACTUAL_QA
    assert task_type_from_str("comparison") is TaskType.COMPARISON
    assert task_type_from_str("unknown_type") is TaskType.FACTUAL_QA


def test_task_config_retrieval_limits():
    assert _TASK_CONFIGS[TaskType.FACTUAL_QA].retrieval_limit == 5
    assert _TASK_CONFIGS[TaskType.COMPARISON].retrieval_limit == 8
    assert _TASK_CONFIGS[TaskType.RECOMMENDATION].retrieval_limit == 10
    assert _TASK_CONFIGS[TaskType.DATA_EXPLORE].retrieval_limit == 20
