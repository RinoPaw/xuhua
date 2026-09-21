"""Prompt construction and bounded retrieval context for the assistant."""

from __future__ import annotations

from collections.abc import Sequence

from .config import AI_MAX_CONTEXT_CHARS
from .dataset import HeritageItem, item_to_dict
from .language import DEFAULT_LOCALE, get_language_profile
from .models import ConversationTurn


def candidate_context(items: Sequence[HeritageItem], max_chars: int) -> str:
    if not items:
        return "未检索到匹配资料。涉及具体事实时请说明资料库暂无对应条目。"

    blocks: list[str] = []
    used = 0
    for item in items:
        payload = item_to_dict(item, include_content=True)
        block = "\n".join(
            part
            for part in (
                f"[{payload['id']}] {payload['title']}",
                f"类别：{payload.get('category', '')}；地区：{payload.get('province', '')} {payload.get('city', '')}",
                f"简介：{str(payload.get('summary') or '')[:320]}",
                f"正文：{str(payload.get('content') or '')[:600]}",
            )
            if part.strip()
        )
        if blocks and used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    candidates: Sequence[HeritageItem],
    history: Sequence[ConversationTurn],
    *,
    short_reply_mode: str | None,
    retrieval_basis: str,
    locale: str = DEFAULT_LOCALE,
    max_context_chars: int = AI_MAX_CONTEXT_CHARS,
) -> list[dict[str, str]]:
    language_profile = get_language_profile(locale)
    system = (
        f"本轮已自动识别用户语言为{language_profile.name}。"
        f"{language_profile.response_instruction}"
        "语言要求只改变表达，不改变事实边界；资料即使是中文，也要用本轮语言自然转述。"
        "你是叙华，一位专注中国非物质文化遗产的数字讲解员。说话温和、自然、有现场讲解感，"
        "像站在展品旁陪用户边看边聊，而不是搜索引擎、百科摘要或客服。"
        "输出的每个字都是叙华实际说出口、会同时用于字幕和 TTS 的台词；情绪只通过措辞和标点表达，"
        "不书写动作、神态、语气标签、旁白或括号舞台说明。开头先给一句有判断、有温度的引导，"
        "宽泛的推荐或比较问题，请根据用户明确的数量要求挑选资料；没有明确数量时只讲最有帮助的几项，"
        "按差异组织出观看线索；单个项目问题就围绕它深入。"
        "严禁用‘根据本地资料’、‘以下是’、‘值得了解的项目有’这类模板开场，"
        "不要逐条复述数据库字段，不要为了覆盖全部结果而堆名单。用户问多个项目时，先帮他建立观看线索，"
        "必须严格区分用户当前说了什么和系统检索到什么：不能把系统主动检索或推荐的项目说成‘你问的这些项目’，"
        "也不要替用户补写没有说过的意图；如果用户只是寒暄，就自然回应并询问想聊哪一项。"
        "再选少量代表项目说明为什么有意思。除非用户明确要求清单或详细长文，否则控制在约二百至四百字，"
        "用自然短段落收住，并邀请用户选择一项继续听。"
        "最近对话中的旧回答只用于理解指代和事实上下文，不得模仿其措辞。事实只能来自提供的资料，"
        "资料不足时用一句自然的话说明，不编造。"
        "消息角色是事实边界：历史中的 role=user 才是用户说过的原话，role=assistant 是你（叙华）上一轮亲口说过的内容。"
        "回顾上一轮时，要把 assistant 内容当作自己的陈述，不得改写成用户说过、问过或讲过；只有 user 消息里明确出现的内容才能归给用户。"
        "正文使用清晰 Markdown，不输出 JSON、XML 或内部流程标签。"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history[-5:]:
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer[:500]})

    if retrieval_basis == "none":
        messages.append(
            {
                "role": "system",
                "content": (
                    "本轮没有识别到明确的非遗项目、类别、地区或目录请求，因此系统没有提供资料候选。"
                    "这不是用户说的话。不要猜测项目名，也不要主动补出‘刚才提到’的项目；"
                    "若用户原话含混，就自然请他重说或补充想聊的对象。"
                ),
            }
        )
    else:
        context = candidate_context(candidates, max_context_chars)
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下内容是系统为本轮自动检索的参考资料，不是用户说的话，也不是用户点名的项目。"
                    "只能用它核对事实，不能据此声称‘你刚才提到/讲到/问到’。\n\n"
                    f"{context}"
                ),
            }
        )

    if short_reply_mode == "continuation":
        messages.append(
            {
                "role": "system",
                "content": "用户本轮只是简短回应，未重新点名项目；请沿着最近一条 assistant 回答自然接续，不要把那条回答的内容归到用户身上。",
            }
        )
    elif short_reply_mode == "pause":
        messages.append(
            {
                "role": "system",
                "content": "用户本轮是在请求暂缓。简短回应并停住，不要展开新项目，也不要把上一条 assistant 回答说成用户讲过。",
            }
        )

    messages.append(
        {
            "role": "system",
            "content": "下一条 user 消息是用户本轮逐字原话；不要把历史 assistant 内容或检索资料拼接进这条用户消息。",
        }
    )
    messages.append({"role": "user", "content": question})
    return messages


__all__ = ["build_messages", "candidate_context"]
