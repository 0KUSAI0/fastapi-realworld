import asyncio
from typing import List, Optional
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.models.domain.articles import Article
from app.models.domain.profiles import Profile
from app.services.ai.cross_reranker import (
    EMBEDDING_WEIGHT,
    LLM_WEIGHT,
    CrossRankLLMResponse,
    CrossReranker,
)
from app.services.ai.errors import AIServiceError
from app.services.ai.llm_client import ChatMessage


def _make_article(slug: str, title: str, tags: List[str]) -> Article:
    return Article(
        id=hash(slug) % 10000,
        slug=slug,
        title=title,
        description="desc",
        body="body " * 20,
        tags=tags,
        author=Profile(username="author", bio="", image=None, following=False),
        favorited=False,
        favorites_count=0,
    )


class FakeLLMClient:
    model_name = "fake-qwen"

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.call_count = 0

    async def generate_json(
        self,
        *,
        messages: List[ChatMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        self.call_count += 1
        return schema.parse_obj(self._payload)


class FailingLLMClient:
    model_name = "failing-llm"

    async def generate_json(self, *, messages, schema):
        raise AIServiceError("vLLM is down")


async def test_score_pair_returns_llm_response() -> None:
    client = FakeLLMClient({"relevance_score": 0.87, "reason": "主题高度相关"})
    reranker = CrossReranker(client)
    source = _make_article("src", "FastAPI Guide", ["fastapi"])
    candidate = _make_article("cand", "FastAPI Best Practices", ["fastapi", "python"])

    result = await reranker.score_pair(source, candidate)

    assert result.relevance_score == pytest.approx(0.87)
    assert result.reason == "主题高度相关"


async def test_score_pairs_returns_results_for_all_candidates() -> None:
    client = FakeLLMClient({"relevance_score": 0.7, "reason": "相关"})
    reranker = CrossReranker(client)
    source = _make_article("src", "Source Article", ["ai"])
    candidates = [
        _make_article("c1", "Candidate One", ["ai"]),
        _make_article("c2", "Candidate Two", ["ml"]),
        _make_article("c3", "Candidate Three", ["ops"]),
    ]

    results = await reranker.score_pairs(source, candidates)

    assert len(results) == 3
    assert all(r is not None for r in results)
    assert client.call_count == 3


async def test_score_pairs_limits_concurrent_calls() -> None:
    """Verify that at most _CONCURRENT_CALLS LLM calls run simultaneously."""
    import app.services.ai.cross_reranker as module

    max_seen = 0
    active = 0

    original_score = CrossReranker.score_pair

    async def counting_score(self, source, candidate):
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return CrossRankLLMResponse(relevance_score=0.5, reason="ok")

    client = FakeLLMClient({"relevance_score": 0.5, "reason": "ok"})
    reranker = CrossReranker(client)
    source = _make_article("src", "Source", [])
    candidates = [_make_article("c{0}".format(i), "C{0}".format(i), []) for i in range(9)]

    with patch.object(CrossReranker, "score_pair", counting_score):
        await reranker.score_pairs(source, candidates)

    assert max_seen <= module._CONCURRENT_CALLS


async def test_score_pairs_returns_none_when_llm_fails() -> None:
    reranker = CrossReranker(FailingLLMClient())
    source = _make_article("src", "Source Article", [])
    candidates = [_make_article("c1", "Candidate", ["ai"])]

    results = await reranker.score_pairs(source, candidates)

    assert results == [None]


async def test_score_pairs_partial_failure_does_not_abort_others() -> None:
    """One failing call should return None; other calls should still complete."""
    call_count = 0

    class SometimesFailingClient:
        model_name = "partial-fail"

        async def generate_json(self, *, messages, schema):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise AIServiceError("intermittent failure")
            return schema.parse_obj({"relevance_score": 0.6, "reason": "ok"})

    reranker = CrossReranker(SometimesFailingClient())
    source = _make_article("src", "Source", [])
    candidates = [_make_article("c{0}".format(i), "C{0}".format(i), []) for i in range(3)]

    results = await reranker.score_pairs(source, candidates)

    assert len(results) == 3
    assert results[1] is None
    assert results[0] is not None
    assert results[2] is not None


async def test_combined_score_weights_are_applied() -> None:
    """Verify EMBEDDING_WEIGHT + LLM_WEIGHT == 1 and values are in [0,1]."""
    assert EMBEDDING_WEIGHT + LLM_WEIGHT == pytest.approx(1.0)

    embedding_score = 0.4
    llm_score = 0.9
    combined = EMBEDDING_WEIGHT * embedding_score + LLM_WEIGHT * llm_score

    assert 0.0 <= combined <= 1.0
    assert combined > embedding_score


async def test_cross_reranker_model_name_matches_llm_client() -> None:
    client = FakeLLMClient({"relevance_score": 0.5, "reason": "ok"})
    reranker = CrossReranker(client)
    assert reranker.model_name == "fake-qwen"


async def test_prompt_includes_source_and_candidate_titles() -> None:
    """Ensure both article titles appear in the generated prompt."""
    captured: List[List[ChatMessage]] = []

    class CapturingClient:
        model_name = "capturing"

        async def generate_json(self, *, messages, schema):
            captured.append(messages)
            return schema.parse_obj({"relevance_score": 0.5, "reason": "ok"})

    reranker = CrossReranker(CapturingClient())
    source = _make_article("src", "FastAPI Internals", ["fastapi"])
    candidate = _make_article("cand", "Async Python Deep Dive", ["asyncio"])

    await reranker.score_pair(source, candidate)

    assert len(captured) == 1
    user_msg = captured[0][1].content
    assert "FastAPI Internals" in user_msg
    assert "Async Python Deep Dive" in user_msg
