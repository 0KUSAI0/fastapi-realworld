from typing import List
from unittest.mock import AsyncMock, call, patch

import pytest
from pydantic import BaseModel

from app.services.ai.article_polish import (
    ArticlePolishService,
    _CritiqueOutput,
    _RevisionOutput,
    _VerificationOutput,
    _compute_diff,
    _split_sentences,
    _MAX_ITERATIONS,
    _IMPROVEMENT_THRESHOLD,
)
from app.services.ai.llm_client import ChatMessage


class FakeLLMClient:
    model_name = "fake-qwen"

    def __init__(self, responses: List[dict]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate_json(
        self,
        *,
        messages: List[ChatMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        payload = self._responses[self._index % len(self._responses)]
        self._index += 1
        return schema.parse_obj(payload)


_CRITIQUE_PAYLOAD = {
    "issues": ["句子过长", "开头缺少吸引力"],
    "overall_assessment": "文章结构松散，表达冗长。",
}
_REVISION_PAYLOAD = {
    "polished_text": "FastAPI 提供了高性能的 API 框架。它支持异步请求处理。",
    "changes_made": ["拆分长句", "改写开头"],
}
_VERIFICATION_GOOD_PAYLOAD = {
    "improvement_score": 0.85,
    "addressed_issues": ["句子过长", "开头缺少吸引力"],
    "remaining_issues": [],
    "feedback": "",
}
_VERIFICATION_POOR_PAYLOAD = {
    "improvement_score": 0.4,
    "addressed_issues": ["句子过长"],
    "remaining_issues": ["开头缺少吸引力"],
    "feedback": "建议改写开头段落",
}


async def test_polish_runs_three_llm_calls_in_one_iteration() -> None:
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        _REVISION_PAYLOAD,
        _VERIFICATION_GOOD_PAYLOAD,
    ])
    service = ArticlePolishService(client)
    original = "FastAPI 是一个基于 Python 的高性能 Web 框架，它提供了非常方便的异步请求处理能力。"

    result = await service.polish(text=original, instruction="使语言更简洁")

    assert result.iterations == 1
    assert result.original == original
    assert result.polished == _REVISION_PAYLOAD["polished_text"]
    assert result.improvement_score == pytest.approx(0.85)
    assert result.model == "fake-qwen"
    assert client._index == 3


async def test_polish_iterates_when_first_verification_is_below_threshold() -> None:
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        _REVISION_PAYLOAD,
        _VERIFICATION_POOR_PAYLOAD,
        {**_REVISION_PAYLOAD, "polished_text": "FastAPI 让开发更简单。"},
        _VERIFICATION_GOOD_PAYLOAD,
    ])
    service = ArticlePolishService(client)
    original = "This is a verbose, poorly structured sentence that goes on and on."

    result = await service.polish(text=original, instruction="简化句子结构")

    assert result.iterations == 2
    assert result.improvement_score == pytest.approx(0.85)
    assert client._index == 5


async def test_polish_returns_best_result_when_second_iteration_is_worse() -> None:
    """If the second revision scores lower than the first, return the first."""
    very_poor = {**_VERIFICATION_POOR_PAYLOAD, "improvement_score": 0.2}
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        _REVISION_PAYLOAD,
        _VERIFICATION_POOR_PAYLOAD,
        {**_REVISION_PAYLOAD, "polished_text": "worse version"},
        very_poor,
    ])
    service = ArticlePolishService(client)

    result = await service.polish(text="original text here.", instruction="改善结构")

    assert result.polished == _REVISION_PAYLOAD["polished_text"]
    assert result.improvement_score == pytest.approx(0.4)


async def test_polish_stops_early_when_threshold_met_on_first_try() -> None:
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        _REVISION_PAYLOAD,
        _VERIFICATION_GOOD_PAYLOAD,
    ])
    service = ArticlePolishService(client)

    result = await service.polish(text="some text.", instruction="提升可读性")

    assert result.iterations == 1
    assert client._index == 3


async def test_polish_never_exceeds_max_iterations() -> None:
    always_poor = {
        "improvement_score": 0.3,
        "addressed_issues": [],
        "remaining_issues": ["still bad"],
        "feedback": "keep trying",
    }
    payloads = [_CRITIQUE_PAYLOAD]
    for _ in range(_MAX_ITERATIONS):
        payloads.append(_REVISION_PAYLOAD)
        payloads.append(always_poor)

    client = FakeLLMClient(payloads)
    service = ArticlePolishService(client)

    result = await service.polish(text="a b c.", instruction="polish")

    assert result.iterations == _MAX_ITERATIONS


async def test_polish_changes_summary_comes_from_revision() -> None:
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        _REVISION_PAYLOAD,
        _VERIFICATION_GOOD_PAYLOAD,
    ])
    service = ArticlePolishService(client)

    result = await service.polish(text="text.", instruction="instruction")

    assert result.changes_summary == ["拆分长句", "改写开头"]


async def test_polish_diff_contains_keep_and_insert_entries() -> None:
    client = FakeLLMClient([
        _CRITIQUE_PAYLOAD,
        {
            "polished_text": "FastAPI 提供高性能框架。它支持异步处理。新增的介绍句。",
            "changes_made": ["added sentence"],
        },
        _VERIFICATION_GOOD_PAYLOAD,
    ])
    service = ArticlePolishService(client)
    original = "FastAPI 提供高性能框架。它支持异步处理。"

    result = await service.polish(text=original, instruction="扩展内容")

    ops = {entry.op for entry in result.diff}
    assert "keep" in ops or "insert" in ops
    assert len(result.diff) > 0


async def test_split_sentences_handles_chinese_punctuation() -> None:
    text = "今天天气很好。我们去爬山！你去吗？"
    sentences = _split_sentences(text)
    assert len(sentences) == 3
    assert sentences[0] == "今天天气很好。"
    assert sentences[1] == "我们去爬山！"
    assert sentences[2] == "你去吗？"


async def test_split_sentences_handles_english_punctuation() -> None:
    text = "FastAPI is fast. It is easy to use. Try it now."
    sentences = _split_sentences(text)
    assert len(sentences) == 3


async def test_split_sentences_handles_double_newlines() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    sentences = _split_sentences(text)
    assert len(sentences) == 2


async def test_compute_diff_equal_texts_produce_only_keep() -> None:
    text = "Hello world. This is a test."
    diff = _compute_diff(text, text)
    assert all(entry.op == "keep" for entry in diff)


async def test_compute_diff_detects_inserted_sentence() -> None:
    original = "First sentence. Third sentence."
    polished = "First sentence. Second sentence. Third sentence."
    diff = _compute_diff(original, polished)
    ops = [entry.op for entry in diff]
    assert "insert" in ops
    inserted = [entry.text for entry in diff if entry.op == "insert"]
    assert any("Second sentence" in t for t in inserted)


async def test_compute_diff_detects_deleted_sentence() -> None:
    original = "Keep this. Remove this. Keep this too."
    polished = "Keep this. Keep this too."
    diff = _compute_diff(original, polished)
    deleted = [entry for entry in diff if entry.op == "delete"]
    assert len(deleted) == 1
    assert "Remove this" in deleted[0].text


async def test_compute_diff_detects_replaced_sentence() -> None:
    original = "The quick brown fox."
    polished = "The swift red fox."
    diff = _compute_diff(original, polished)
    ops = {entry.op for entry in diff}
    assert "delete" in ops
    assert "insert" in ops
