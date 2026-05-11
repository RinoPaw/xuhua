from heritage_explorer.agent import (
    Agent,
    AgentDecision,
    AgentResult,
    IntentRouter,
    TaskType,
    _TASK_CONFIGS,
    decision_from_planner_payload,
    normalize_query_with_pinyin_anchor,
    replace_homophone_span,
    task_type_from_str,
    task_type_label,
)


def test_all_task_types_have_configs():
    for task_type in TaskType:
        assert task_type in _TASK_CONFIGS


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


def test_model_planner_direct_answer_is_not_rewritten_offline():
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
    assert "控制器" in decision.direct_answer


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
    assert _TASK_CONFIGS[TaskType.CHITCHAT].generate_detail == "正在整理上下文，生成简短回应"


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


def test_content_transform_targets_specific_title_in_suggestion_query(monkeypatch):
    from heritage_explorer import config
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    monkeypatch.setattr(config, "AI_API_KEY", "")

    result = agent.dispatch("给朱仙镇木版年画生成讲解词")

    assert result.task_type is TaskType.CONTENT_TRANSFORM
    assert result.items[0]["title"] == "朱仙镇木版年画"
    assert result.sources[0]["title"] == "朱仙镇木版年画"
    assert "滑县木版年画" not in result.answer.splitlines()[0]


def test_router_uses_model_planner_decision_without_offline_repair(monkeypatch):
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    router = IntentRouter()
    planner_calls = []

    def fake_planner(*_args, **_kwargs):
        planner_calls.append(True)
        return AgentDecision(
            task_type=TaskType.EXHIBITION_PLAN,
            confidence=0.7,
            needs_retrieval=True,
            needs_llm=False,
            reason="模型误判为展示策划。",
            planner="model",
        )

    monkeypatch.setattr("heritage_explorer.agent.call_agent_planner_model", fake_planner)

    decision = router.decide("给朱仙镇木版年画生成讲解词", kb)

    assert planner_calls
    assert decision.task_type is TaskType.EXHIBITION_PLAN
    assert decision.needs_llm is False
    assert decision.planner == "model"
    assert decision.warnings == []


def test_model_planner_keeps_valid_exhibition_plan(monkeypatch):
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    router = IntentRouter()
    monkeypatch.setattr(
        "heritage_explorer.agent.call_agent_planner_model",
        lambda *_args, **_kwargs: AgentDecision(
            task_type=TaskType.EXHIBITION_PLAN,
            confidence=0.8,
            needs_retrieval=True,
            needs_llm=False,
            reason="模型判断为展示策划。",
            planner="model",
        ),
    )

    decision = router.decide("帮我策划一个朱仙镇木版年画社区展", kb)

    assert decision.task_type is TaskType.EXHIBITION_PLAN
    assert decision.planner == "model"


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


def test_browse_query_uses_normalized_title_and_family():
    from heritage_explorer.dataset import load_dataset

    kb = load_dataset()
    agent = Agent(kb)
    result = agent.dispatch("列出木版年画")

    assert result.task_type is TaskType.BROWSE_QUERY
    assert "滑县木版年画" in result.answer
    assert "木版年画（滑县木版年画）" not in result.answer
    assert any(item.get("title") == "滑县木版年画" and item.get("family") == "木版年画" for item in result.items)


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
