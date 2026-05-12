"""Retrieval-augmented question answering over the heritage dataset."""

from __future__ import annotations

from ..ai.client import (
    call_chat_model,
    call_model_with_messages,
    call_speech_model,
    describe_model_error,
)
from ..ai.context import (
    build_context,
    clean_knowledge_text,
    extract_structured_field,
    item_context_text,
)
from ..ai.qa import (
    Answer,
    answer_question,
    build_local_answer,
    direct_item_matches,
    fact_question_sources,
    source_payload,
    summarize_snippet,
)
from ..ai.speech import (
    build_messages,
    build_speech_messages,
    build_speech_text,
    build_spoken_answer,
    clean_spoken_output,
)

__all__ = [
    "Answer",
    "answer_question",
    "build_context",
    "build_local_answer",
    "build_messages",
    "build_speech_messages",
    "build_speech_text",
    "build_spoken_answer",
    "call_chat_model",
    "call_model_with_messages",
    "call_speech_model",
    "clean_knowledge_text",
    "clean_spoken_output",
    "describe_model_error",
    "direct_item_matches",
    "extract_structured_field",
    "fact_question_sources",
    "item_context_text",
    "source_payload",
    "summarize_snippet",
]
