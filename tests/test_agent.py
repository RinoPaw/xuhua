from heritage_explorer.agent import (
    Agent,
    AgentResult,
    IntentRouter,
    TaskType,
    _TASK_CONFIGS,
    build_chitchat_answer,
    decision_from_planner_payload,
    has_domain_hint,
    is_chitchat_query,
    normalize_query_with_pinyin_anchor,
    replace_homophone_span,
    should_answer_out_of_scope,
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


def test_intent_router_classifies_short_greeting_as_chitchat():
    router = IntentRouter()

    for query in [
        "你好",
        "您好！",
        "hello",
        "在吗",
        "你是谁",
        "你叫什么名字",
        "你能做什么",
        "你知道什么",
        "资料库里有什么",
    ]:
        task_type, confidence = router.classify(query)
        assert task_type is TaskType.CHITCHAT
        assert confidence >= 0.9

    assert is_chitchat_query("你好。")
    assert not is_chitchat_query("你好，介绍一下皮影戏")
    assert not is_chitchat_query("你是谁，介绍一下皮影戏")


def test_chitchat_answer_handles_identity_and_capability():
    identity = build_chitchat_answer("你是谁")
    capability = build_chitchat_answer("你能做什么")

    assert "我是叙华" in identity
    assert "河南非遗资料库" in identity
    assert "历史" in capability
    assert "筛选" in capability


def test_chitchat_answer_uses_kb_for_knowledge_inventory():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    answer = build_chitchat_answer("你知道什么", kb)

    assert str(len(kb.items)) in answer
    assert "非遗项目" in answer
    assert "筛选" in answer
    assert "推荐" in answer


def test_fact_qa_scope_gate_skips_unrelated_questions():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()

    assert not has_domain_hint("天气怎么样")
    assert has_domain_hint("皮影戏有什么特色")
    assert should_answer_out_of_scope(kb, "天气怎么样")
    assert not should_answer_out_of_scope(kb, "汴绣")
    assert not should_answer_out_of_scope(kb, "落山皮影戏")


def test_fact_qa_normalizes_homophone_item_name_before_generation():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()

    assert replace_homophone_span("落山皮影戏有什么特色", "罗山皮影戏") == "罗山皮影戏有什么特色"
    assert normalize_query_with_pinyin_anchor(kb, "落山皮影戏有什么特色") == "罗山皮影戏有什么特色"


def test_intent_router_decision_is_explicit_about_actions():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    router = IntentRouter()

    greeting = router.decide("你是谁", kb)
    inventory = router.decide("你知道什么", kb)
    factual = router.decide("陈氏太极拳是什么", kb)
    unrelated = router.decide("天气怎么样", kb)
    recommendation = router.decide("推荐3个适合校园展示的传统美术项目", kb)

    assert greeting.task_type is TaskType.CHITCHAT
    assert not greeting.needs_retrieval
    assert not greeting.needs_llm
    assert greeting.direct_answer

    assert inventory.task_type is TaskType.CHITCHAT
    assert not inventory.needs_retrieval
    assert not inventory.needs_llm
    assert "非遗项目" in inventory.direct_answer

    assert factual.task_type is TaskType.FACT_QA
    assert factual.needs_retrieval
    assert factual.needs_llm

    assert unrelated.task_type is TaskType.FACT_QA
    assert not unrelated.needs_retrieval
    assert not unrelated.needs_llm
    assert unrelated.mode == "no_context"
    assert unrelated.direct_answer

    assert recommendation.task_type is TaskType.RECOMMENDATION
    assert recommendation.needs_retrieval
    assert not recommendation.needs_llm


def test_model_planner_payload_becomes_agent_decision():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    decision = decision_from_planner_payload(
        {
            "task_type": "chitchat",
            "confidence": 0.93,
            "needs_retrieval": True,
            "needs_llm": True,
            "reason": "用户在询问智能体掌握什么资料。",
            "direct_answer": "我知道当前非遗资料库里的项目和任务能力。",
            "mode": "local",
        },
        "你知道什么",
        kb,
    )

    assert decision.task_type is TaskType.CHITCHAT
    assert decision.planner == "model"
    assert not decision.needs_retrieval
    assert not decision.needs_llm
    assert decision.direct_answer


def test_model_planner_chitchat_answer_cannot_leak_internal_controller():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    decision = decision_from_planner_payload(
        {
            "task_type": "chitchat",
            "confidence": 0.96,
            "needs_retrieval": False,
            "needs_llm": False,
            "reason": "用户询问智能体身份。",
            "direct_answer": "我是叙华智能体的控制器，负责协调您的查询和回答。",
            "mode": "no_context",
        },
        "你叫什么",
        kb,
    )

    assert decision.task_type is TaskType.CHITCHAT
    assert decision.mode == "local"
    assert "控制器" not in decision.direct_answer
    assert "我是叙华" in decision.direct_answer


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


def test_comparison_with_region_only_terms_does_not_fabricate_duplicate_items():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("四川皮影和湖北皮影有什么区别？", include_speech=False)

    item_ids = [item["id"] for item in result.items]
    source_ids = [source["id"] for source in result.sources]

    assert result.task_type is TaskType.COMPARISON
    assert result.mode == "local"
    assert len(item_ids) == len(set(item_ids))
    assert len(source_ids) == len(set(source_ids))
    assert "暂未找到可直接对应" in result.answer
    assert any("四川皮影" in warning or "湖北皮影" in warning for warning in result.warnings)


def test_agent_dispatch_handles_empty_query():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("")

    assert result.mode == "empty"
    assert result.speech == "请先输入问题。"
    assert result.sources == []


def test_agent_dispatch_handles_chitchat_locally():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("你好")

    assert result.task_type is TaskType.CHITCHAT
    assert result.mode == "local"
    assert result.answer
    assert "我在这里" in result.answer
    assert result.items == []
    assert result.sources == []
    assert result.evidence == []


def test_agent_dispatch_handles_identity_question_locally():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("你是谁")

    assert result.task_type is TaskType.CHITCHAT
    assert result.mode == "local"
    assert "我是叙华" in result.answer
    assert "水晶雕刻" not in result.answer
    assert result.items == []
    assert result.sources == []
    assert result.evidence == []


def test_agent_dispatch_skips_model_for_out_of_scope_question():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("天气怎么样")

    assert result.task_type is TaskType.FACT_QA
    assert result.mode == "no_context"
    assert "非遗资料库" in result.answer
    assert result.sources == []
    assert result.warnings
    assert result.decision["needs_retrieval"] is False
    assert result.decision["needs_llm"] is False


def test_task_type_label_returns_chinese():
    assert task_type_label(TaskType.CHITCHAT) == "对话回应"
    assert task_type_label(TaskType.FACTUAL_QA) == "事实问答"
    assert task_type_label(TaskType.COMPARISON) == "项目对比"
    assert task_type_label(TaskType.RECOMMENDATION) == "项目推荐"


def test_task_type_from_str():
    assert task_type_from_str("fact_qa") is TaskType.FACT_QA
    assert task_type_from_str("comparison") is TaskType.COMPARISON
    assert task_type_from_str("browse_query") is TaskType.BROWSE_QUERY
    assert task_type_from_str("unknown_type") is TaskType.FACT_QA


def test_task_config_retrieval_limits():
    assert _TASK_CONFIGS[TaskType.FACT_QA].retrieval_limit == 5
    assert _TASK_CONFIGS[TaskType.COMPARISON].retrieval_limit == 8
    assert _TASK_CONFIGS[TaskType.RECOMMENDATION].retrieval_limit == 10
    assert _TASK_CONFIGS[TaskType.BROWSE_QUERY].retrieval_limit == 30
    assert _TASK_CONFIGS[TaskType.RECOMMENDATION].handler_name == "_handle_recommend"
    assert _TASK_CONFIGS[TaskType.CONTENT_TRANSFORM].handler_name == "_handle_content_transform"
    assert _TASK_CONFIGS[TaskType.FACT_QA].handler_name is None
    assert _TASK_CONFIGS[TaskType.CHITCHAT].generate_detail == "正在组织简短回应"


def test_dispatch_stream_uses_task_config_generate_detail_for_rule_handler(monkeypatch):
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)

    def fake_recommend(_analysis):
        return AgentResult(
            task_type=TaskType.RECOMMENDATION,
            answer="推荐结果",
            speech="推荐播报",
            mode="local",
        )

    monkeypatch.setattr(agent, "_handle_recommend", fake_recommend)
    events = list(agent.dispatch_stream("推荐3个适合校园展示的传统美术项目"))
    progress_events = [event for event in events if isinstance(event, dict)]
    result = next(event for event in events if isinstance(event, AgentResult))

    assert any(
        event.get("step") == "generate"
        and event.get("detail") == _TASK_CONFIGS[TaskType.RECOMMENDATION].generate_detail
        for event in progress_events
    )
    assert any(event.get("step") == "speech" for event in progress_events)
    assert result.answer == "推荐结果"
    assert result.speech == "推荐播报"


def test_content_transform_llm_branch_uses_spoken_answer_rewrite(monkeypatch):
    from heritage_explorer.dataset import load_dataset
    from heritage_explorer import config

    kb = load_dataset()
    agent = Agent(kb)
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(
        "heritage_explorer.agent._call_transform_model",
        lambda **_kwargs: "展示版改写：汴绣适合年轻受众传播。",
    )
    monkeypatch.setattr(
        "heritage_explorer.ai.build_spoken_answer",
        lambda answer, question="", sources=None, prefer_model=True, max_chars=760: f"播报版：{answer}",
    )

    result = agent.dispatch("把汴绣改写成口播稿")

    assert result.task_type is TaskType.CONTENT_TRANSFORM
    assert result.mode == "llm"
    assert result.answer == "展示版改写：汴绣适合年轻受众传播。"
    assert result.speech == "播报版：展示版改写：汴绣适合年轻受众传播。"


# ── MVP handler tests ──


def test_browse_query_returns_items():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("河南有哪些传统美术")

    assert result.task_type is TaskType.BROWSE_QUERY
    assert result.mode == "local"
    assert result.confidence == 0.95
    assert len(result.items) > 0
    assert len(result.evidence) > 0
    assert "传统美术" in result.answer


def test_browse_query_combined_filters():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("列出河南省的国家级传统技艺")

    assert result.task_type is TaskType.BROWSE_QUERY
    assert result.mode == "local"
    assert len(result.answer) > 0


def test_recommendation_returns_items():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("推荐3个适合校园展示的传统美术项目")

    assert result.task_type is TaskType.RECOMMENDATION
    assert result.mode == "fallback"
    assert result.selection_reason
    assert "推荐" in result.answer


def test_recommendation_has_evidence():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("推荐适合社区活动的项目")

    assert result.task_type is TaskType.RECOMMENDATION
    for ev in result.evidence:
        assert ev["type"] == "inferred"
        assert "item_id" in ev


def test_exhibition_plan_returns_template():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("策划一个河南非遗校园展")

    assert result.task_type is TaskType.EXHIBITION_PLAN
    assert result.mode == "fallback"
    assert "展示策划方案" in result.answer
    assert "推荐展项" in result.answer
    assert len(result.warnings) >= 1


def test_agent_result_has_all_required_fields():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("太极拳是什么")

    assert hasattr(result, "task_type")
    assert hasattr(result, "answer")
    assert hasattr(result, "items")
    assert hasattr(result, "sources")
    assert hasattr(result, "evidence")
    assert hasattr(result, "selection_reason")
    assert hasattr(result, "mode")
    assert hasattr(result, "confidence")
    assert hasattr(result, "warnings")
    assert hasattr(result, "speech")  # backward-compat


def test_browse_query_has_backward_compat_speech():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("列出河南省的传统技艺")

    assert result.task_type is TaskType.BROWSE_QUERY
    # speech may be empty for local mode (no LLM), but field must exist
    assert isinstance(result.speech, str)
