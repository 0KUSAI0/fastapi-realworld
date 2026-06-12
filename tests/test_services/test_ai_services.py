from typing import List

import pytest
from pydantic import BaseModel

from app.core.settings.app import AppSettings
from app.models.domain.articles import Article
from app.models.domain.profiles import Profile
from app.models.domain.users import User
from app.models.schemas.articles import (
    ArticleForResponse,
    ArticleInCreate,
    RecommendedArticleForResponse,
)
from app.services.ai.article_assistant import ArticleAssistantService
from app.services.ai.article_library_qa import ArticleLibraryQAService
from app.services.ai.article_revision import ArticleSuggestionRevisionService
from app.services.ai.comment_moderation import CommentModerationService
from app.services.ai.embedding_client import EmbeddingClient
from app.services.ai.llm_client import ChatMessage


class FakeLLMClient:
    model_name = "fake-qwen"

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_messages = []

    async def generate_json(
        self,
        *,
        messages: List[ChatMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        self.last_messages = messages
        return schema.parse_obj(self._payload)


class FakeRecommendationService:
    def __init__(self, sources) -> None:
        self._sources = sources
        self.last_limit = None

    async def search_by_text(self, *, query: str, requested_user, limit: int):
        self.last_limit = limit
        return self._sources[:limit]


def _article_source(
    *,
    slug: str,
    title: str,
    description: str,
    body: str,
    tags: List[str],
    score: float,
) -> RecommendedArticleForResponse:
    article = Article(
        slug=slug,
        title=title,
        description=description,
        body=body,
        tags=tags,
        author=Profile(username="demo", bio="", image=None, following=False),
        favorited=False,
        favorites_count=0,
    )
    return RecommendedArticleForResponse(
        article=ArticleForResponse.from_orm(article),
        similarityScore=score,
        reason="正文语义与搜索意图接近",
    )


async def test_article_assistant_uses_llm_structured_output() -> None:
    assistant = ArticleAssistantService(
        FakeLLMClient(
            {
                "summary": "这是一篇关于 FastAPI AI 功能的文章。",
                "recommendedTagList": ["fastapi", "ai"],
                "contentScore": 88,
                "riskLabels": [],
                "suggestions": ["增加一个接口调用示例。"],
            },
        ),
    )

    analysis = await assistant.analyze_article(
        ArticleInCreate(
            title="FastAPI AI article assistant",
            description="AI assisted backend features.",
            body="FastAPI AI backend " * 90,
            tagList=["fastapi"],
        ),
    )

    assert analysis.summary == "这是一篇关于 FastAPI AI 功能的文章。"
    assert analysis.recommended_tags == ["fastapi", "ai"]
    assert analysis.content_score == 88
    assert analysis.model == "fake-qwen"
    assert analysis.reading_time_minutes == 1


async def test_comment_moderation_uses_llm_structured_output() -> None:
    settings = AppSettings(
        database_url="postgresql://postgres:postgres@localhost:15432/rwdb",
        secret_key="secret",
        ai_comment_moderation_mode="block",
    )
    moderation_service = CommentModerationService(
        FakeLLMClient(
            {
                "allowed": False,
                "category": "spam",
                "severity": "high",
                "reason": "包含广告推广内容。",
                "suggestedRevision": "删除广告链接后重新提交。",
                "confidence": 0.91,
            },
        ),
        settings,
    )
    user = User(username="demo", email="demo@example.com")
    article = Article(
        slug="demo",
        title="Demo",
        description="Demo article",
        body="body",
        tags=[],
        author=Profile(username="demo", bio="", image=None, following=False),
        favorited=False,
        favorites_count=0,
    )

    moderation = await moderation_service.moderate_comment(
        article=article,
        user=user,
        body="buy now",
    )

    assert moderation.allowed is False
    assert moderation.category == "spam"
    assert moderation.severity == "high"
    assert moderation.suggested_revision == "删除广告链接后重新提交。"


async def test_article_revision_uses_selected_suggestion() -> None:
    service = ArticleSuggestionRevisionService(
        FakeLLMClient(
            {
                "revisedBody": "第一段保留。\n\n第二段加入了一个具体接口调用示例。",
                "changedParagraphIndex": 1,
                "rationale": "补充示例后，文章论证更具体。",
                "changesSummary": ["补充接口调用示例"],
                "confidence": 0.86,
            },
        ),
    )
    original = "第一段保留。\n\n第二段需要更多细节。"

    result = await service.revise_for_suggestion(
        article=ArticleInCreate(
            title="FastAPI AI article assistant",
            description="AI assisted backend features.",
            body=original,
            tagList=["fastapi"],
        ),
        suggestion="增加一个接口调用示例。",
    )

    assert result.original == original
    assert result.revised == "第一段保留。\n\n第二段加入了一个具体接口调用示例。"
    assert result.changed_paragraph_index == 1
    assert result.suggestion == "增加一个接口调用示例。"
    assert result.confidence == pytest.approx(0.86)
    assert result.model == "fake-qwen"
    assert any(entry.op in {"delete", "insert"} for entry in result.diff)


async def test_article_library_qa_uses_retrieved_sources() -> None:
    source = _article_source(
        slug="city-walks",
        title="City Walks and Focus",
        description="Walking helps restore attention.",
        body="A short walk can create a buffer before work and help people focus.",
        tags=["city", "focus"],
        score=0.82,
    )
    service = ArticleLibraryQAService(
        llm_client=FakeLLMClient(
            {
                "answer": "文章库里有一篇关于城市散步和注意力恢复的文章。",
                "citations": ["city-walks", "unknown-slug"],
                "suggestedQueries": ["还有哪些文章谈到通勤？"],
            },
        ),
        recommendation_service=FakeRecommendationService([source]),
    )

    result = await service.answer_question(
        question="有没有关于散步恢复注意力的文章？",
        requested_user=None,
        limit=5,
    )

    assert result.answer == "文章库里有一篇关于城市散步和注意力恢复的文章。"
    assert result.sources[0].article.slug == "city-walks"
    assert result.citations == ["city-walks"]
    assert result.suggested_queries == ["还有哪些文章谈到通勤？"]
    assert result.model == "fake-qwen"


async def test_article_library_qa_reranks_noisy_test_article_below_topic_match() -> None:
    noisy_source = _article_source(
        slug="test-article",
        title="这是一篇测试文章",
        description="用于测试列表展示。",
        body="这是一篇测试文章，内容没有实际主题。",
        tags=["测试"],
        score=0.91,
    )
    topic_source = _article_source(
        slug="morning-walk-focus",
        title="连续一个月早起散步后，我的工作日早晨变了什么",
        description="一篇关于城市生活、散步和注意力恢复的观察。",
        body="早起散步之后，工作日前半程的注意力更稳定，也更容易进入状态。",
        tags=["城市生活", "散步", "注意力"],
        score=0.71,
    )
    llm_client = FakeLLMClient(
        {
            "answer": "有，文章库里有关于城市散步和注意力恢复的内容。",
            "citations": ["morning-walk-focus"],
            "suggestedQueries": ["还有哪些文章谈到通勤？"],
        },
    )
    recommendation_service = FakeRecommendationService([noisy_source, topic_source])
    service = ArticleLibraryQAService(
        llm_client=llm_client,
        recommendation_service=recommendation_service,
    )

    result = await service.answer_question(
        question="有没有关于城市生活和注意力恢复的文章？",
        requested_user=None,
        limit=2,
    )

    assert recommendation_service.last_limit >= 16
    assert result.sources[0].article.slug == "morning-walk-focus"
    assert result.sources[1].article.slug == "test-article"
    assert result.citations == ["morning-walk-focus"]
    assert llm_client.last_messages[-1].content.find("morning-walk-focus") < llm_client.last_messages[
        -1
    ].content.find("test-article")


async def test_embedding_client_falls_back_without_cached_model() -> None:
    settings = AppSettings(
        database_url="postgresql://postgres:postgres@localhost:15432/rwdb",
        secret_key="secret",
        embedding_model="sentence-transformers/not-cached",
        embedding_dimensions=16,
        embedding_allow_download=False,
        embedding_fallback_enabled=True,
    )
    client = EmbeddingClient(settings)

    vector = await client.embed_text("FastAPI AI recommendation article")

    assert client.model_name == "hashing-fallback-16"
    assert len(vector) == 16
    assert sum(value * value for value in vector) == pytest.approx(1.0)
