"""Retrieval-augmented question answering over the heritage dataset."""

from __future__ import annotations

import json
import logging
import re
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import config
from .dataset import HeritageItem, KnowledgeBase, item_to_dict, normalize_text
from .search import search_items


LOGGER = logging.getLogger(__name__)

STRUCTURED_LABELS = (
    "序号",
    "标题",
    "归属",
    "类别",
    "城市",
    "地区",
    "报道地区",
    "介绍",
    "重大地区",
    "主要特色",
    "重要价值",
    "传承人",
    "企业",
    "展示形式",
    "联系",
    "电话",
    "省份",
    "地点",
    "面积",
    "operation",
    "经纬度",
    "历史",
    "主要时间",
    "内容",
    "省份ject",
)


@dataclass(frozen=True)
class Answer:
    answer: str
    mode: str
    sources: list[dict[str, Any]]
    speech: str = ""


def answer_question(kb: KnowledgeBase, question: str, category: str = "") -> Answer:
    question = normalize_text(question)
    category = normalize_text(category)
    if not question:
        answer = "请先输入问题。"
        return Answer(answer=answer, mode="empty", sources=[], speech=answer)

    sources, _ = search_items(kb, query=question, category=category, limit=5)
    if not sources:
        answer = "没有在数据集中找到足够相关的资料。"
        return Answer(answer=answer, mode="no_context", sources=[], speech=answer)

    if config.AI_API_KEY:
        try:
            answer = call_chat_model(question, sources)
            return Answer(
                answer=answer,
                mode="llm",
                sources=[source_payload(item) for item in sources],
                speech=build_speech_text(answer, question=question, sources=sources),
            )
        except Exception as exc:  # noqa: BLE001 - API failures should gracefully fall back.
            LOGGER.warning("Chat model unavailable: %s", describe_model_error(exc))
            fallback = build_local_answer(question, sources)
            fallback += (
                "\n\n模型服务暂时不可用，已为你切换成本地依据式回答。"
            )
            return Answer(
                answer=fallback,
                mode="fallback",
                sources=[source_payload(item) for item in sources],
                speech=build_speech_text(fallback, question=question, sources=sources),
            )

    answer = build_local_answer(question, sources)
    return Answer(
        answer=answer,
        mode="local",
        sources=[source_payload(item) for item in sources],
        speech=build_speech_text(answer, question=question, sources=sources),
    )


def call_chat_model(question: str, sources: list[HeritageItem]) -> str:
    if should_use_zhipu_sdk():
        return call_zhipu_sdk(question, sources)
    return call_openai_compatible_model(question, sources)


def call_zhipu_sdk(question: str, sources: list[HeritageItem]) -> str:
    from zhipuai import ZhipuAI

    client = ZhipuAI(
        api_key=config.AI_API_KEY,
        base_url=config.AI_BASE_URL.rstrip("/"),
        timeout=config.AI_TIMEOUT,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=build_messages(question, sources),
        temperature=0.2,
        top_p=0.8,
        max_tokens=1000,
        **zhipu_extra_options(),
        stream=False,
    )
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {response}") from exc

    text = (getattr(message, "content", "") or "").strip()
    if text:
        return text

    finish_reason = getattr(choice, "finish_reason", "")
    reasoning = getattr(message, "reasoning_content", "")
    detail = "Empty model response"
    if finish_reason:
        detail += f"; finish_reason={finish_reason}"
    if reasoning:
        detail += "; reasoning_content was returned without final content"
    raise RuntimeError(detail)


def call_openai_compatible_model(question: str, sources: list[HeritageItem]) -> str:
    payload = {
        "model": config.AI_MODEL,
        "messages": build_messages(question, sources),
        "temperature": 0.2,
    }
    url = config.AI_BASE_URL.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.AI_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {body}") from exc


def build_messages(question: str, sources: list[HeritageItem]) -> list[dict[str, str]]:
    context = build_context(sources, config.AI_MAX_CONTEXT_CHARS)
    return [
            {
                "role": "system",
                "content": (
                    "你是一个严谨的非物质文化遗产知识库助手。"
                    "只能依据给定资料回答；资料不足时要直接说明。"
                    "回答应使用中文，先用一句话概括，再用少量短段或短列表说明历史、技艺特点、代表作品、传承价值。"
                    "不要照抄经纬度、电话、地址、面积、序号、销售额等后台管理字段，除非用户明确询问。"
                    "不要用“基本信息”字段表作为开头。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{question}\n\n资料：\n{context}",
            },
    ]


def should_use_zhipu_sdk() -> bool:
    host = urllib.parse.urlparse(config.AI_BASE_URL).hostname or ""
    return host.endswith("bigmodel.cn")


def zhipu_extra_options() -> dict[str, Any]:
    model = config.AI_MODEL.lower()
    thinking_models = ("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")
    if any(name in model for name in thinking_models):
        return {"thinking": {"type": "disabled"}}
    return {}


def describe_model_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = f"HTTPError {exc.code}"
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best effort diagnostics only.
            body = ""
        if body:
            detail += f": {body}"
        return sanitize_error(detail)

    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", "")
        return sanitize_error(f"URLError: {reason or exc}")

    detail = str(exc)
    if not detail:
        detail = type(exc).__name__
    return sanitize_error(f"{type(exc).__name__}: {detail}")


def sanitize_error(value: str, max_chars: int = 220) -> str:
    text = normalize_text(value)
    if config.AI_API_KEY:
        text = text.replace(config.AI_API_KEY, "***")
    return textwrap.shorten(text, width=max_chars, placeholder="...")


def build_context(sources: list[HeritageItem], max_chars: int) -> str:
    chunks = []
    remaining = max_chars
    for index, item in enumerate(sources, start=1):
        text = item_context_text(item)
        chunk = f"[{index}] 标题：{item.title}\n类别：{item.category}\n资料：{text}"
        if len(chunk) > remaining:
            chunk = chunk[: max(0, remaining - 20)] + "..."
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n".join(chunks)


def item_context_text(item: HeritageItem) -> str:
    parts = []
    for label in ("介绍", "历史", "主要特色", "重要价值", "传承人"):
        value = extract_structured_field(item.content, label)
        if value:
            parts.append(f"{label}：{clean_knowledge_text(value)}")
    if parts:
        return "\n".join(parts)
    return clean_knowledge_text(item.summary or item.content)


def extract_structured_field(text: str, label: str) -> str:
    text = normalize_text(text)
    marker = f"{label}:"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for next_label in STRUCTURED_LABELS:
        if next_label == label:
            continue
        for next_marker in (f", {next_label}:", f"，{next_label}:"):
            position = text.find(next_marker, start)
            if position >= 0:
                end = min(end, position)
    return text[start:end].strip(" ，,")


def clean_knowledge_text(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"经纬度[:：]?\s*[-\d.,，\s]+", " ", text)
    text = re.sub(r"电话[:：]?\s*[\d\- ]+", " ", text)
    text = re.sub(r"序号[:：]?\s*\d+", " ", text)
    text = re.sub(r"\boperation[:：]?\s*\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ，,")
    return text


def build_local_answer(question: str, sources: list[HeritageItem]) -> str:
    lead = f"根据数据集中与“{question}”最相关的资料，可以先这样理解："
    bullets = []
    for item in sources[:3]:
        text = item.summary or item.content
        snippet = summarize_snippet(text)
        bullets.append(f"- {item.title}（{item.category}）：{snippet}")
    return "\n".join([lead, *bullets])


def summarize_snippet(text: str, max_chars: int = 180) -> str:
    text = normalize_text(text)
    if not text:
        return "暂无摘要。"
    sentences = [part.strip() for part in text.replace("；", "。").split("。") if part.strip()]
    snippet = "。".join(sentences[:2]) if sentences else text
    snippet = textwrap.shorten(snippet, width=max_chars, placeholder="...")
    return snippet.rstrip("。") + "。"


def build_speech_text(
    answer: str,
    question: str = "",
    sources: list[HeritageItem] | None = None,
    max_chars: int = 760,
) -> str:
    spoken = build_answer_speech(answer, max_chars=max_chars)
    if spoken:
        return spoken

    return build_source_speech(question, sources or [], max_chars=max_chars)


def build_answer_speech(answer: str, max_chars: int = 760) -> str:
    text = str(answer or "")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)

    spoken_lines = []
    active_section = ""
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        section = speech_section_heading(line)
        if section:
            active_section = section
            continue

        converted = speech_line(line, active_section)
        if converted:
            spoken_lines.append(converted)
            active_section = ""

    text = "。".join(spoken_lines)
    text = re.sub(r"[>#*_~|]+", " ", text)
    text = re.sub(r"[，、；：]\s*([。！？])", r"\1", text)
    text = re.sub(r"。{2,}", "。", text)
    text = normalize_text(text)
    text = text.replace("。。", "。").strip(" 。")
    if len(text) > max_chars:
        boundary = max(text.rfind(mark, 0, max_chars) for mark in "。！？")
        if boundary < max_chars // 2:
            boundary = max_chars
        text = text[: boundary + 1].rstrip("，、；： ")
        if text and text[-1] not in "。！？":
            text += "。"
    return text


def speech_section_heading(line: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
    text = re.sub(r"^\s*[-*+]\s+", "", text).strip()
    text = text.strip(" ：:。；;")
    headings = {
        "历史",
        "历史渊源",
        "历史渊源与发展",
        "起源与发展",
        "技艺特点",
        "主要特色",
        "代表作品",
        "传承价值",
        "文化价值",
        "传承与保护",
    }
    return text if text in headings else ""


def speech_line(line: str, section: str = "") -> str:
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
    line = re.sub(r"^\s*[-*+]\s+", "", line).strip()
    line = re.sub(r"^\s*(\d+)[.)、]\s+", r"第\1点，", line).strip()
    line = re.sub(r"^\s*([一二三四五六七八九十]+)、\s*", r"第\1部分，", line).strip()
    line = line.strip("。；; ")
    if not line:
        return ""

    if line in {"基本信息", "相关信息", "关键信息", "总结"}:
        return ""
    if is_admin_sentence(line):
        return ""

    label_match = re.match(r"^([^：:]{2,12})[：:]\s*(.+)$", line)
    if label_match:
        label = label_match.group(1).strip()
        body = clean_speech_body(label_match.group(2).strip())
        if label == "代表作品":
            body = clean_representative_body(body)
        transitions = {
            "历史": "从历史来看，{body}",
            "历史渊源": "从历史来看，{body}",
            "历史渊源与发展": "从历史来看，{body}",
            "起源与发展": "从起源看，{body}",
            "技艺特点": "在技艺特点上，{body}",
            "主要特色": "在技艺特点上，{body}",
            "代表作品": "代表作品包括{body}",
            "传承价值": "从传承价值看，{body}",
            "文化价值": "文化价值在于，{body}",
            "价值": "价值在于，{body}",
            "传承与保护": "在传承保护方面，{body}",
            "类别": "它属于{body}",
            "制作工艺": "制作工艺上，{body}",
            "表演形式": "表演形式上，{body}",
            "音乐特色": "音乐特色上，{body}",
            "表演特点": "表演特点上，{body}",
            "艺术价值": "艺术价值在于，{body}",
            "历史价值": "历史价值在于，{body}",
            "社会价值": "社会价值在于，{body}",
        }
        template = transitions.get(label)
        if template:
            line = template.format(body=body)
        else:
            line = f"{label}，{body}"
    else:
        line = clean_speech_body(line)

    if section:
        line = apply_section_intro(section, line)

    line = re.sub(r"[，、；：]\s*([。！？])", r"\1", line)
    return line.strip(" 。")


def apply_section_intro(section: str, line: str) -> str:
    intros = {
        "历史": "从历史来看",
        "历史渊源": "从历史来看",
        "历史渊源与发展": "从历史来看",
        "起源与发展": "从起源看",
        "技艺特点": "在技艺特点上",
        "主要特色": "在技艺特点上",
        "代表作品": "代表作品包括",
        "传承价值": "从传承价值看",
        "文化价值": "从文化价值看",
        "传承与保护": "在传承保护方面",
    }
    intro = intros.get(section)
    if not intro or line.startswith(intro):
        return line
    if section == "代表作品":
        line = re.sub(r"(.+?)剧目包括", r"\1有", line)
        line = re.sub(r"(.+?)代表剧目有", r"\1有", line)
        return f"代表作品方面，{line}"
    return f"{intro}，{line}"


def clean_speech_body(text: str) -> str:
    text = text.replace("：", "，")
    text = text.replace('"', "")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ，、；：。")


def clean_representative_body(text: str) -> str:
    text = re.sub(
        r"(.+?)是[^。；，,]*?代表作[，,]\s*(还有.+)",
        r"\1，\2",
        text,
    )
    text = re.sub(
        r"(.+?)是[^。；，,]*?代表作$",
        r"\1",
        text,
    )
    return text.strip(" ，、；：。")


def build_source_speech(
    question: str,
    sources: list[HeritageItem],
    max_chars: int = 760,
) -> str:
    if not sources:
        return ""

    item = sources[0]
    title = item.title
    intro = extract_structured_field(item.content, "介绍") or item.summary
    history = extract_structured_field(item.content, "历史")
    feature = extract_structured_field(item.content, "主要特色")
    value = extract_structured_field(item.content, "重要价值")
    level = extract_structured_field(item.content, "归属")
    city = extract_structured_field(item.content, "城市")
    district = extract_structured_field(item.content, "地区")

    location = city
    if district and district != city:
        location = f"{city}{district}" if city else district
    project_level = f"{level}非遗" if level and level not in {"未分类", "无"} else "非遗"
    category = f"{item.category}类" if item.category else ""

    sentences = []
    if normalize_text(question) == title:
        opening = f"{title}是{location + '的' if location else ''}{category}{project_level}项目。"
    else:
        opening = (
            f"关于{normalize_text(question) or title}，资料里最相关的是{title}。"
            f"它是{location + '的' if location else ''}{category}{project_level}项目。"
        )
    sentences.append(opening)

    intro_text = spoken_sentences(intro, max_chars=150, count=2)
    if intro_text:
        sentences.append(intro_text)

    feature_text = spoken_sentences(feature or history, max_chars=190, count=2)
    if feature_text and feature_text not in intro_text:
        sentences.append(f"它最突出的特点是，{feature_text}")

    value_text = spoken_sentences(value, max_chars=150, count=1)
    if value_text:
        sentences.append(f"它的价值在于，{value_text}")

    speech = normalize_text("".join(sentences))
    speech = re.sub(r"[，、；：]\s*([。！？])", r"\1", speech)
    speech = re.sub(r"。{2,}", "。", speech).strip(" 。")
    if not speech:
        return ""
    if len(speech) > max_chars:
        boundary = max(speech.rfind(mark, 0, max_chars) for mark in "。！？")
        if boundary < max_chars // 2:
            boundary = max_chars
        speech = speech[: boundary + 1].rstrip("，、；： ")
        if speech and speech[-1] not in "。！？":
            speech += "。"
    return speech


def spoken_sentences(text: str, max_chars: int, count: int) -> str:
    text = clean_spoken_source_text(text)
    if not text:
        return ""
    parts = [
        part.strip(" ，,；;")
        for part in re.split(r"[。！？]", text)
        if part.strip(" ，,；;")
    ]
    selected = []
    total = 0
    for part in parts:
        if not part:
            continue
        if is_admin_sentence(part):
            continue
        next_len = len(part) + 1
        if selected and (len(selected) >= count or total + next_len > max_chars):
            break
        selected.append(part)
        total += next_len
    return "。".join(selected).strip(" 。") + ("。" if selected else "")


def is_admin_sentence(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "党和政府",
            "市委",
            "市政府",
            "战略部署",
            "从业人员",
            "销售额",
            "就业",
            "地址",
            "电话",
            "面积",
            "经度",
            "纬度",
            "经纬度",
        )
    )


def clean_spoken_source_text(text: str) -> str:
    text = clean_knowledge_text(text)
    text = re.sub(r"根据提供的信息[^：:]*[:：]?", " ", text)
    text = re.sub(r"经度[:：]?\s*[-\d.]+", " ", text)
    text = re.sub(r"纬度[:：]?\s*[-\d.]+", " ", text)
    text = re.sub(r"地理位置[:：][^。；;]+[。；;]?", " ", text)
    text = re.sub(r"地址[:：][^。；;]+[。；;]?", " ", text)
    text = re.sub(r"面积[:：][^。；;]+[。；;]?", " ", text)
    text = re.sub(r"从业人员[:：][^。；;]+[。；;]?", " ", text)
    text = re.sub(r"年销售额[:：][^。；;]+[。；;]?", " ", text)
    text = re.sub(r"\d+[、.)]\s*", "", text)
    text = text.replace("：", "，")
    return normalize_text(text)


def source_payload(item: HeritageItem) -> dict[str, Any]:
    data = item_to_dict(item)
    data["excerpt"] = summarize_snippet(item.content, max_chars=120)
    return data
