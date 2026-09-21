"""Localized answer fallback, citations and suggestion policy."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .dataset import HeritageItem, normalize_text
from .language import DEFAULT_LOCALE
from .models import ConversationTurn
from .retrieval_policy import requested_item_count

GREETING_QUESTIONS = frozenset({"你好", "您好", "嗨", "哈喽", "在吗"})
MULTILINGUAL_GREETINGS = {
    "zh-CN-henan": frozenset({"恁好"}),
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
    "yue-CN": {
        "greeting": "你好呀。想由边一项非遗开始了解？",
        "pause": "好呀，你慢慢嚟，我先停喺度。",
        "continuation": "好，我哋接住头先嘅内容讲。你想先听边一部分？",
        "no_results": "资料库暂时搵唔到同呢个问题直接对应嘅项目。你可以换个项目名、地区或者类别再试。",
        "list_intro": "想先睇清呢类非遗各自嘅味道，我会由{names}讲起。",
        "list_close": "你对边一项最有感觉？我可以继续讲佢嘅历史同现场。",
        "missing_detail": "呢一项嘅详细资料仲整理紧。",
        "single_missing": "资料库暂时未有呢个项目嘅详细简介。",
    },
    "zh-CN-sichuan": {
        "greeting": "你好。想从哪一项非遗开始摆起？",
        "pause": "要得，你慢慢来，我先停到这儿。",
        "continuation": "要得，我们接到刚才的内容摆。你想先听哪一截？",
        "no_results": "资料库暂时没找到直接对应的项目。你可以换个项目名、地区或者类别再试一下。",
        "list_intro": "想先看出这一类非遗各自的味道，我带你从{names}摆起。",
        "list_close": "你对哪一项更感兴趣？我可以接到讲它的历史和现场。",
        "missing_detail": "这项的详细资料还在整理中。",
        "single_missing": "资料库暂时还没有这个项目的详细简介。",
    },
    "zh-CN-henan": {
        "greeting": "恁好。想从哪一项非遗开始聊？",
        "pause": "中，恁慢慢来，我先停到这儿。",
        "continuation": "中，咱接着刚才的内容聊。恁想先听哪一段？",
        "no_results": "资料库暂时没找着直接对应的项目。恁可以换个项目名、地区或者类别再试试。",
        "list_intro": "想先看看这一类非遗各有啥味道，咱可以从{names}聊起。",
        "list_close": "恁对哪一项更感兴趣？我可以接着聊它的历史和现在。",
        "missing_detail": "这一项的详细资料还在整理中。",
        "single_missing": "资料库暂时还没有这个项目的详细介绍。",
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
    "fr-FR": {
        "greeting": "Bonjour. Quel patrimoine culturel immatériel chinois souhaitez-vous découvrir ?",
        "pause": "Bien sûr. Prenez votre temps ; je m'arrête ici un instant.",
        "continuation": "Reprenons là où nous en étions. Quelle partie souhaitez-vous entendre d'abord ?",
        "no_results": "Je n'ai pas trouvé de projet correspondant directement à cette question. Essayez un nom de projet, une région ou une catégorie.",
        "list_intro": "Pour saisir les différentes facettes de ce patrimoine, je commencerais par {names}.",
        "list_close": "Lequel vous attire le plus ? Je peux poursuivre avec son histoire et sa pratique vivante.",
        "missing_detail": "Sa notice détaillée est encore en préparation.",
        "single_missing": "La collection ne contient pas encore de présentation détaillée de ce projet.",
    },
    "es-ES": {
        "greeting": "Hola. ¿Qué patrimonio cultural inmaterial de China te gustaría descubrir?",
        "pause": "Claro. Tómate tu tiempo; haré una pausa aquí.",
        "continuation": "Sigamos desde donde lo dejamos. ¿Qué parte te gustaría escuchar primero?",
        "no_results": "No encontré un proyecto que coincida directamente con la pregunta. Prueba con el nombre de un proyecto, una región o una categoría.",
        "list_intro": "Para apreciar los distintos matices de este patrimonio, empezaría por {names}.",
        "list_close": "¿Cuál te atrae más? Puedo continuar con su historia y su práctica viva.",
        "missing_detail": "Su ficha detallada todavía está en preparación.",
        "single_missing": "La colección aún no incluye una introducción detallada de este proyecto.",
    },
    "de-DE": {
        "greeting": "Hallo. Welches immaterielle Kulturerbe Chinas möchten Sie entdecken?",
        "pause": "Gern. Nehmen Sie sich Zeit; ich pausiere hier.",
        "continuation": "Machen wir dort weiter, wo wir aufgehört haben. Welchen Teil möchten Sie zuerst hören?",
        "no_results": "Ich habe kein Projekt gefunden, das direkt zu dieser Frage passt. Versuchen Sie einen Projektnamen, eine Region oder eine Kategorie.",
        "list_intro": "Um die unterschiedlichen Facetten dieses Kulturerbes zu erfassen, würde ich mit {names} beginnen.",
        "list_close": "Welches spricht Sie am meisten an? Ich kann seine Geschichte und heutige Praxis weiter erläutern.",
        "missing_detail": "Der ausführliche Eintrag wird noch vorbereitet.",
        "single_missing": "Die Sammlung enthält noch keine ausführliche Einführung zu diesem Projekt.",
    },
    "ru-RU": {
        "greeting": "Здравствуйте. С каким объектом нематериального наследия Китая вы хотели бы познакомиться?",
        "pause": "Конечно. Не спешите — я пока остановлюсь здесь.",
        "continuation": "Продолжим с того места, где остановились. О чём рассказать сначала?",
        "no_results": "Я не нашёл в коллекции проект, напрямую соответствующий вопросу. Попробуйте указать название, регион или категорию.",
        "list_intro": "Чтобы увидеть разные грани этого наследия, я бы начал с {names}.",
        "list_close": "Что заинтересовало вас больше всего? Я могу продолжить рассказ об истории и живой практике.",
        "missing_detail": "Подробная запись ещё готовится.",
        "single_missing": "В коллекции пока нет подробного описания этого проекта.",
    },
    "ar-SA": {
        "greeting": "مرحباً. أي عنصر من التراث الثقافي غير المادي في الصين تود استكشافه؟",
        "pause": "بكل تأكيد. خذ وقتك؛ سأتوقف هنا قليلاً.",
        "continuation": "لنواصل من حيث توقفنا. أي جزء تود سماعه أولاً؟",
        "no_results": "لم أجد في المجموعة مشروعاً يطابق هذا السؤال مباشرة. جرّب اسم مشروع أو منطقة أو فئة.",
        "list_intro": "لرؤية الجوانب المختلفة لهذا التراث، سأبدأ بـ {names}.",
        "list_close": "أيها جذبك أكثر؟ يمكنني متابعة الحديث عن تاريخه وممارسته الحية.",
        "missing_detail": "لا يزال السجل التفصيلي قيد الإعداد.",
        "single_missing": "لا تتضمن المجموعة بعد مقدمة تفصيلية لهذا المشروع.",
    },
    "hi-IN": {
        "greeting": "नमस्ते। आप चीन की किस अमूर्त सांस्कृतिक विरासत के बारे में जानना चाहेंगे?",
        "pause": "ज़रूर। आराम से समय लें; मैं यहीं रुकता हूँ।",
        "continuation": "जहाँ रुके थे वहीं से आगे बढ़ते हैं। आप पहले कौन-सा भाग सुनना चाहेंगे?",
        "no_results": "संग्रह में इस प्रश्न से सीधे मेल खाने वाली परियोजना नहीं मिली। किसी परियोजना का नाम, क्षेत्र या श्रेणी आज़माएँ।",
        "list_intro": "इस विरासत के अलग-अलग रूप समझने के लिए मैं {names} से शुरुआत करूँगा।",
        "list_close": "इनमें से किसने आपको सबसे अधिक आकर्षित किया? मैं उसके इतिहास और जीवित परंपरा पर आगे बता सकता हूँ।",
        "missing_detail": "इसका विस्तृत अभिलेख अभी तैयार किया जा रहा है।",
        "single_missing": "संग्रह में अभी इस परियोजना का विस्तृत परिचय उपलब्ध नहीं है।",
    },
    "th-TH": {
        "greeting": "สวัสดี คุณอยากสำรวจมรดกทางวัฒนธรรมที่จับต้องไม่ได้ของจีนรายการใด?",
        "pause": "ได้เลย ค่อย ๆ ใช้เวลานะ ฉันจะหยุดไว้ตรงนี้ก่อน",
        "continuation": "มาต่อจากที่เราค้างไว้ คุณอยากฟังส่วนไหนก่อน?",
        "no_results": "ฉันไม่พบรายการในคลังที่ตรงกับคำถามนี้โดยตรง ลองใช้ชื่อโครงการ ภูมิภาค หรือหมวดหมู่",
        "list_intro": "หากต้องการเห็นลักษณะที่หลากหลายของมรดกประเภทนี้ ฉันขอเริ่มจาก {names}",
        "list_close": "รายการไหนดึงดูดคุณมากที่สุด? ฉันเล่าต่อถึงประวัติและการสืบทอดในปัจจุบันได้",
        "missing_detail": "ข้อมูลฉบับละเอียดยังอยู่ระหว่างการจัดทำ",
        "single_missing": "คลังยังไม่มีคำแนะนำฉบับละเอียดสำหรับโครงการนี้",
    },
}


def copy_catalog(locale: str) -> dict[str, str]:
    return _FALLBACK_COPY.get(locale, _FALLBACK_COPY["en-US"])


def localized_copy(locale: str, key: str, **values: str) -> str:
    return copy_catalog(locale)[key].format(**values)


def localized_greeting_suggestions(locale: str) -> list[str]:
    values = {
        "zh-CN": ("按地区查找非遗项目", "按类别浏览资料"),
        "zh-CN-sichuan": ("按地区查找非遗项目", "按类别浏览资料"),
        "zh-CN-henan": ("按地区找非遗项目", "按类别看看资料"),
        "yue-CN": ("按地区搵非遗项目", "按类别浏览资料"),
        "en-US": ("Explore heritage by region", "Browse the collection by category"),
        "ja-JP": ("地域から無形文化遺産を探す", "分類から資料を見る"),
        "ko-KR": ("지역별 무형문화유산 찾기", "분류별 자료 보기"),
        "fr-FR": ("Explorer le patrimoine par région", "Parcourir la collection par catégorie"),
        "es-ES": ("Explorar el patrimonio por región", "Ver la colección por categoría"),
        "de-DE": ("Kulturerbe nach Region erkunden", "Sammlung nach Kategorie durchsuchen"),
        "ru-RU": ("Искать наследие по регионам", "Просматривать коллекцию по категориям"),
        "ar-SA": ("استكشاف التراث حسب المنطقة", "تصفح المجموعة حسب الفئة"),
        "hi-IN": ("क्षेत्र के अनुसार विरासत खोजें", "श्रेणी के अनुसार संग्रह देखें"),
        "th-TH": ("สำรวจมรดกตามภูมิภาค", "ดูคลังตามหมวดหมู่"),
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
        "oui": "continuation",
        "continuez": "continuation",
        "attendez": "pause",
        "sí": "continuation",
        "continúa": "continuation",
        "espera": "pause",
        "ja": "continuation",
        "weiter": "continuation",
        "warten": "pause",
        "да": "continuation",
        "продолжайте": "continuation",
        "подождите": "pause",
        "نعم": "continuation",
        "تابع": "continuation",
        "انتظر": "pause",
        "हाँ": "continuation",
        "जारी रखें": "continuation",
        "रुकिए": "pause",
        "ใช่": "continuation",
        "ต่อเลย": "continuation",
        "รอก่อน": "pause",
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
        or locale not in {"zh-CN", "yue-CN", "zh-CN-sichuan", "zh-CN-henan"}
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
            if locale in {"zh-CN", "yue-CN", "zh-CN-sichuan", "zh-CN-henan"}
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
            "zh-CN-sichuan": "如何介绍一个非遗项目？",
            "zh-CN-henan": "咋介绍一个非遗项目？",
            "yue-CN": "点样介绍一项非遗？",
            "en-US": "How do you introduce a heritage project?",
            "ja-JP": "無形文化遺産をどう紹介しますか？",
            "ko-KR": "무형문화유산을 어떻게 소개하나요?",
            "fr-FR": "Comment présenter un projet patrimonial ?",
            "es-ES": "¿Cómo se presenta un proyecto patrimonial?",
            "de-DE": "Wie stellt man ein Kulturerbe-Projekt vor?",
            "ru-RU": "Как представить объект наследия?",
            "ar-SA": "كيف نقدّم مشروعاً تراثياً؟",
            "hi-IN": "किसी विरासत परियोजना का परिचय कैसे दें?",
            "th-TH": "ควรแนะนำโครงการมรดกอย่างไร?",
        }
        return [*base, third.get(locale, third["en-US"])]

    output: list[str] = []
    seen: set[str] = set()
    item_templates = {
        "zh-CN": "{title}的历史和特色是什么？",
        "zh-CN-sichuan": "{title}的历史和特色是什么？",
        "zh-CN-henan": "{title}有啥历史和特色？",
        "yue-CN": "{title}有咩历史同特色？",
        "en-US": "What are the history and distinctive features of {title}?",
        "ja-JP": "{title}の歴史と特色は？",
        "ko-KR": "{title}의 역사와 특징은 무엇인가요?",
        "fr-FR": "Quelle est l'histoire et quelles sont les particularités de {title} ?",
        "es-ES": "¿Cuál es la historia y qué distingue a {title}?",
        "de-DE": "Was sind Geschichte und Besonderheiten von {title}?",
        "ru-RU": "Какова история и особенности {title}?",
        "ar-SA": "ما تاريخ {title} وما سماته المميزة؟",
        "hi-IN": "{title} का इतिहास और विशेषताएँ क्या हैं?",
        "th-TH": "{title} มีประวัติและลักษณะเด่นอย่างไร?",
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
        "zh-CN-sichuan": ("按地区继续比较", "按类别继续浏览"),
        "zh-CN-henan": ("按地区接着比", "按类别接着看"),
        "yue-CN": ("按地区继续比较", "按类别继续睇"),
        "en-US": ("Compare by region", "Keep browsing by category"),
        "ja-JP": ("地域別に比較する", "分類別に続けて見る"),
        "ko-KR": ("지역별로 계속 비교하기", "분류별로 계속 보기"),
        "fr-FR": ("Comparer par région", "Continuer par catégorie"),
        "es-ES": ("Comparar por región", "Seguir por categoría"),
        "de-DE": ("Nach Region vergleichen", "Nach Kategorie weiterstöbern"),
        "ru-RU": ("Сравнить по регионам", "Продолжить по категориям"),
        "ar-SA": ("المقارنة حسب المنطقة", "متابعة التصفح حسب الفئة"),
        "hi-IN": ("क्षेत्र के अनुसार तुलना करें", "श्रेणी के अनुसार आगे देखें"),
        "th-TH": ("เปรียบเทียบตามภูมิภาค", "ดูต่อตามหมวดหมู่"),
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
