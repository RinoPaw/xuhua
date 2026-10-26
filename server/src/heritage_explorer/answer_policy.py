"""Localized answer fallback, citations and suggestion policy."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .dataset import HeritageItem, normalize_text
from .language import DEFAULT_LOCALE
from .models import ConversationTurn
from .retrieval_policy import requested_item_count

GREETING_QUESTIONS = frozenset({"你好", "您好", "嗨", "哈喽", "在吗", "恁好"})
MULTILINGUAL_GREETINGS = {
    "en-US": frozenset(
        {
            "hello",
            "hello there",
            "hi",
            "hi there",
            "hey",
            "hey there",
            "good morning",
            "good afternoon",
            "good evening",
        }
    ),
    "ja-JP": frozenset({"こんにちは", "もしもし", "おはよう", "こんばんは"}),
    "ko-KR": frozenset({"안녕하세요", "안녕", "여보세요"}),
}
SHORT_REPLY_MODES = {
    "嗯": "continuation",
    "嗯嗯": "continuation",
    "好": "continuation",
    "好的": "continuation",
    "行": "continuation",
    "可以": "continuation",
    "继续": "continuation",
    "接着说": "continuation",
    "然后呢": "continuation",
    "中": "continuation",
    "等一下": "pause",
    "等等": "pause",
    "先等一下": "pause",
    "停一下": "pause",
}

_FALLBACK_COPY = {
    "zh-CN": {
        "greeting": "你好。想了解哪项非遗？",
        "pause": "好，你慢慢来。我先停在这里。",
        "continuation": "好，我们就接着刚才的内容看。你想先听哪一处？",
        "no_results": "资料库暂时没有找到与这个问题直接对应的项目。你可以换一个项目名称、地区或类别再试试。",
        "list_intro": "如果想先抓住这一类非遗的不同气质，我会带你从{names}看起。",
        "list_close": "你对哪一项更有感觉？我可以接着带你往它的历史和现场里走。",
        "missing_detail": "它的详细资料还在整理中。",
        "single_missing": "资料库中暂未提供该项目的详细简介。",
    },
    "en-US": {
        "greeting": "Hello. Which piece of China's intangible cultural heritage would you like to explore?",
        "pause": "Of course. Take your time; I'll pause here.",
        "continuation": "Let's continue from where we left off. Which part would you like to hear first?",
        "no_results": "I couldn't find a project in the collection that directly matches that question. Try a project name, region, or category.",
        "list_intro": "To see the different character of this heritage category, I would begin with {names}.",
        "list_close": "Which one draws you in most? I can take you further into its history and living practice.",
        "missing_detail": "Its detailed record is still being prepared.",
        "single_missing": "The collection does not yet include a detailed introduction for this project.",
    },
    "ja-JP": {
        "greeting": "こんにちは。どの中国無形文化遺産から見てみましょうか。",
        "pause": "はい、ゆっくりどうぞ。ここでいったん止めます。",
        "continuation": "では、先ほどの続きから見ていきましょう。まずどこを聞きたいですか。",
        "no_results": "この質問に直接対応する項目は資料庫で見つかりませんでした。項目名、地域、または分類を変えてお試しください。",
        "list_intro": "この分野の違いをつかむなら、まず{names}から見ていきましょう。",
        "list_close": "どの項目が一番気になりましたか。歴史や現在の姿をさらにご案内できます。",
        "missing_detail": "詳しい資料は現在整理中です。",
        "single_missing": "この項目の詳しい紹介は、まだ資料庫に収録されていません。",
    },
    "ko-KR": {
        "greeting": "안녕하세요. 어떤 중국 무형문화유산부터 살펴볼까요?",
        "pause": "네, 천천히 하세요. 여기서 잠시 멈출게요.",
        "continuation": "그럼 앞의 이야기에서 이어가겠습니다. 어느 부분부터 듣고 싶으세요?",
        "no_results": "이 질문과 직접 맞는 항목을 자료에서 찾지 못했습니다. 종목명, 지역 또는 분류를 바꿔 다시 시도해 보세요.",
        "list_intro": "이 분야의 서로 다른 매력을 보려면 {names}부터 살펴보는 것이 좋습니다.",
        "list_close": "어느 항목이 가장 마음에 닿나요? 역사와 현장의 모습까지 이어서 안내해 드릴게요.",
        "missing_detail": "상세 자료는 현재 정리 중입니다.",
        "single_missing": "이 항목의 상세 소개는 아직 자료에 수록되지 않았습니다.",
    },
}


def copy_catalog(locale: str) -> dict[str, str]:
    return _FALLBACK_COPY.get(locale, _FALLBACK_COPY[DEFAULT_LOCALE])


def localized_copy(locale: str, key: str, **values: str) -> str:
    return copy_catalog(locale)[key].format(**values)


def localized_greeting_suggestions(locale: str) -> list[str]:
    values = {
        "zh-CN": ("按地区查找非遗项目", "按类别浏览资料"),
        "en-US": ("Explore heritage by region", "Browse the collection by category"),
        "ja-JP": ("地域から無形文化遺産を探す", "分類から資料を見る"),
        "ko-KR": ("지역별 무형문화유산 찾기", "분류별 자료 보기"),
    }
    return list(values.get(locale, values["en-US"]))


def is_greeting(question: str, locale: str) -> bool:
    compact = question.casefold().strip("。！!？?～~，,、；;：: .")
    if compact in GREETING_QUESTIONS:
        return True
    return compact in MULTILINGUAL_GREETINGS.get(locale, ())


def short_reply_mode(question: str) -> str | None:
    compact = normalize_text(question).lower().strip("。！？!?，,、；;：: ")
    multilingual = {
        "ok": "continuation",
        "okay": "continuation",
        "yes": "continuation",
        "continue": "continuation",
        "go on": "continuation",
        "wait": "pause",
        "wait a moment": "pause",
        "hold on": "pause",
        "stop": "pause",
        "はい": "continuation",
        "続けて": "continuation",
        "ちょっと待って": "pause",
        "네": "continuation",
        "계속": "continuation",
        "잠깐만": "pause",
    }
    return SHORT_REPLY_MODES.get(compact) or multilingual.get(compact)


def fallback_answer(
    question: str,
    items: Sequence[HeritageItem],
    *,
    history: Sequence[ConversationTurn] = (),
    locale: str = DEFAULT_LOCALE,
) -> str:
    mode = short_reply_mode(question)
    if mode == "pause":
        return localized_copy(locale, "pause")
    if mode == "continuation" and history:
        return localized_copy(locale, "continuation")
    if not items:
        return localized_copy(locale, "no_results")
    if (
        any(marker in question for marker in ("有哪些", "推荐", "值得", "几个", "项目"))
        or locale != "zh-CN"
    ) and len(items) > 1:
        requested = requested_item_count(question)
        selected: list[HeritageItem] = []
        remaining_chars = 760
        for item in items:
            summary = normalize_text(item.summary or item.content)
            cost = max(80, min(len(summary), 180))
            if selected and requested is None and remaining_chars < cost:
                break
            selected.append(item)
            remaining_chars -= cost
            if requested is not None and len(selected) >= requested:
                break
            if len(selected) >= 6:
                break
        separator = (
            "、"
            if locale == "zh-CN"
            else ", "
        )
        names = separator.join(item.title for item in selected)
        passages = []
        for item in selected:
            summary = normalize_text(item.summary or item.content)
            summary = re.sub(r"^申报地区或单位：\S+\s*", "", summary)[:180]
            detail = summary or localized_copy(locale, "missing_detail")
            passages.append(f"**{item.title}**。{detail}")
        return (
            localized_copy(locale, "list_intro", names=names)
            + "\n\n"
            + "\n\n".join(passages)
            + "\n\n"
            + localized_copy(locale, "list_close")
        )
    item = items[0]
    summary = normalize_text(item.summary or item.content)[:500]
    return f"### {item.title}\n\n{summary or localized_copy(locale, 'single_missing')}"


def confidence(items: Sequence[HeritageItem], answer: str) -> float:
    if not items:
        return 0.2
    return 0.85 if answer else 0.4


def used_sources(answer: str, candidates: Sequence[HeritageItem]) -> tuple[HeritageItem, ...]:
    """Keep citations tied to projects the final answer actually names."""
    if not candidates:
        return ()
    text = normalize_text(answer).casefold()
    alias_counts: dict[str, int] = {}
    for item in candidates:
        aliases = {
            normalize_text(value).casefold()
            for value in (item.family, *item.display_forms)
            if len(normalize_text(value)) >= 3
        }
        for alias in aliases:
            alias_counts[alias] = alias_counts.get(alias, 0) + 1
    matches: list[tuple[int, int, HeritageItem]] = []
    for index, item in enumerate(candidates):
        title = normalize_text(item.title).casefold()
        names = {title} if len(title) >= 2 else set()
        names.update(
            alias
            for alias in {
                normalize_text(value).casefold()
                for value in (item.family, *item.display_forms)
                if len(normalize_text(value)) >= 3
            }
            if alias_counts.get(alias) == 1
        )
        positions = [text.find(name) for name in names if name in text]
        if positions:
            matches.append((min(positions), index, item))
    if not matches:
        return (candidates[0],)
    matches.sort(key=lambda match: (match[0], match[1]))
    return tuple(match[2] for match in matches)


def suggestions(
    items: Sequence[HeritageItem],
    *,
    locale: str = DEFAULT_LOCALE,
) -> list[str]:
    if not items:
        base = localized_greeting_suggestions(locale)
        third = {
            "zh-CN": "如何介绍一个非遗项目？",
            "en-US": "How do you introduce a heritage project?",
            "ja-JP": "無形文化遺産をどう紹介しますか？",
            "ko-KR": "무형문화유산을 어떻게 소개하나요?",
        }
        return [*base, third.get(locale, third["en-US"])]

    output: list[str] = []
    seen: set[str] = set()
    item_templates = {
        "zh-CN": "{title}的历史和特色是什么？",
        "en-US": "What are the history and distinctive features of {title}?",
        "ja-JP": "{title}の歴史と特色は？",
        "ko-KR": "{title}의 역사와 특징은 무엇인가요?",
    }
    template = item_templates.get(locale, item_templates["en-US"])
    for item in items:
        title = normalize_text(item.title)
        if not title or title in seen:
            continue
        seen.add(title)
        output.append(template.format(title=title))
        if len(output) == 3:
            break
    browse = {
        "zh-CN": ("按地区继续比较", "按类别继续浏览"),
        "en-US": ("Compare by region", "Keep browsing by category"),
        "ja-JP": ("地域別に比較する", "分類別に続けて見る"),
        "ko-KR": ("지역별로 계속 비교하기", "분류별로 계속 보기"),
    }
    output.extend(browse.get(locale, browse["en-US"]))
    return output[:3]


__all__ = [
    "confidence",
    "fallback_answer",
    "is_greeting",
    "localized_copy",
    "localized_greeting_suggestions",
    "short_reply_mode",
    "suggestions",
    "used_sources",
]
